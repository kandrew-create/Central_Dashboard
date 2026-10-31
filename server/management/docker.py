"""Trusted Linux desktop access to one local Compose project, without an admin port."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import time

import httpx

from collector.errors import CollectorError
from server.management.linux_vault import private_directory, private_read, private_write
from server.management.settings import ServerSettings


@dataclass(frozen=True)
class DockerSettings:
    workspace: Path
    project: str = 'linker-scada-wsl'
    mode: str = 'local'
    server_host: str = 'localhost'
    listen_address: str = '127.0.0.1'
    https_port: int = 443
    database_port: int = 5432
    postgres_bin: Path = Path('Managed inside Docker')

    def __post_init__(self):
        ServerSettings(self.workspace, self.postgres_bin, mode=self.mode, server_host=self.server_host,
                       listen_address=self.listen_address).validate_network()
        if type(self.https_port) is not int or not 1 <= self.https_port <= 65535:
            raise CollectorError('Choose a valid HTTPS port for the Docker server.')

    @property
    def data_dir(self):
        return self.workspace / 'secrets' / 'docker-manager'

    @property
    def upload_url(self):
        port = '' if self.https_port == 443 else ':' + str(self.https_port)
        return 'https://' + self.server_host + port + '/v1/uploads'


def bind_mount(source, target, readonly=False):
    if ':' in str(source):
        raise CollectorError('Choose a Linux folder without a colon for Docker management or setup export.')
    return str(source) + ':' + target + (':ro' if readonly else ':rw')


class DockerManagerService:
    def __init__(self, workspace, project='linker-scada-wsl'):
        if os.name != 'posix' or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}', project):
            raise CollectorError('Launch this manager inside Linux with a valid local Compose project name.')
        workspace = Path(workspace).resolve(strict=True)
        lock = workspace / 'secrets' / 'setup.lock'
        if lock.exists():
            import fcntl
            with lock.open('rb') as stream:
                try:
                    fcntl.flock(stream, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise CollectorError('Setup is updating this workspace. Finish setup before opening its manager.') from None
                fcntl.flock(stream, fcntl.LOCK_UN)
        environment = private_read(workspace / '.env', 16384).decode('utf-8')
        values = {key.strip(): value.strip().strip('\"\'') for key, value in
                  (line.split('=', 1) for line in environment.splitlines() if '=' in line and not line.lstrip().startswith('#'))}
        try:
            https_port = int(values.get('LINKER_HTTPS_PORT', '443'))
            http_port = int(values.get('LINKER_HTTP_PORT', '80'))
            if not 1 <= https_port <= 65535 or not 1 <= http_port <= 65535 or https_port == http_port:
                raise ValueError()
        except ValueError:
            raise CollectorError('The saved Docker HTTP and HTTPS ports must be different valid TCP ports.') from None
        self.settings = DockerSettings(workspace, project, mode=values.get('LINKER_MODE', 'local'),
                                       server_host=values.get('SCADA_HOSTNAME', 'localhost'),
                                       listen_address=values.get('LINKER_LISTEN_ADDRESS', '127.0.0.1'), https_port=https_port)
        self.config_keys = set(values)
        self.files = [workspace / 'deploy' / name for name in ('docker-compose.yml', 'docker-compose.wsl.yml')]
        if any(not file.is_file() for file in self.files):
            raise CollectorError('Select the WSL workspace containing its Compose file and saved deployment override.')
        private_directory(self.settings.data_dir)
        private_write(self.settings.data_dir / 'agent-compose.yml',
                      b'services:\n  migrate:\n    logging: !override\n      driver: none\n')
        self.export_directory = private_directory(workspace / 'exports')
        self.ca_path = workspace / 'caddy-root.crt'

    def _command(self, arguments):
        command = ['docker', '--host', 'unix:///var/run/docker.sock', 'compose',
                   '--project-name', self.settings.project, '--env-file', str(self.settings.workspace / '.env')]
        for file in self.files:
            command.extend(('-f', str(file)))
        return command + list(arguments)

    def _run(self, arguments, payload=None, timeout=90, agent=False):
        environment = {key: value for key, value in os.environ.items()
                       if key not in self.config_keys and not key.startswith('COMPOSE_')
                       and not key.startswith('LINKER_MANAGER_')
                       and key not in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'LINKER_HTTP_PORT', 'LINKER_HTTPS_PORT',
                                       'LINKER_MODE', 'LINKER_LISTEN_ADDRESS', 'SCADA_HOSTNAME')}
        try:
            result = subprocess.run(self._command(arguments), input=payload, capture_output=True,
                                    cwd=self.settings.workspace, env=environment, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise CollectorError('Docker did not finish in time. Refresh the sources and server status before retrying an operation.') from None
        except OSError:
            raise CollectorError('Docker is unavailable. Start Docker Desktop and enable its Ubuntu integration, then refresh.') from None
        if len(result.stdout) > 4 * 1024 * 1024:
            raise CollectorError('Docker management returned too much data. No response was displayed.')
        if result.returncode and not agent:
            raise CollectorError('Docker operation failed. Check Docker Desktop and the selected WSL project; existing data is retained.')
        return result.stdout

    def _rpc(self, action, arguments=None, export_parent=None):
        command = ['-f', str(self.settings.data_dir / 'agent-compose.yml'),
                   'run', '--rm', '--no-deps', '-T', '--user', f'{os.getuid()}:{os.getgid()}',
                   '-e', 'LINKER_MANAGER_HTTPS_PORT=' + str(self.settings.https_port),
                   '-e', 'LINKER_MANAGER_MODE=' + self.settings.mode,
                   '-e', 'LINKER_MANAGER_HOST=' + self.settings.server_host,
                   '-e', 'LINKER_MANAGER_LISTEN_ADDRESS=' + self.settings.listen_address,
                   '--volume', bind_mount(self.settings.data_dir, '/manager-state')]
        if self.ca_path.is_file():
            command += ['--volume', bind_mount(self.ca_path, '/manager-ca.pem', True)]
        if export_parent:
            command += ['--volume', bind_mount(export_parent, '/exports')]
        command += ['--entrypoint', 'python', 'migrate', '-m', 'server.management.docker_agent']
        output = self._run(command, json.dumps(dict(action=action, arguments=arguments or {}), default=str).encode(), agent=True)
        try:
            response = json.loads(output)
            if not response['ok']:
                raise CollectorError(response['error'])
            return response['result']
        except (ValueError, KeyError, TypeError):
            raise CollectorError('Cannot read the Docker manager response. Install the current management image and refresh before retrying.') from None

    def _refresh_ca(self):
        certificate = self._run(['exec', '-T', 'caddy', 'cat', '/data/caddy/pki/authorities/local/root.crt'])
        if not 0 < len(certificate) <= 16384:
            raise CollectorError('Cannot read the Docker server public CA certificate.')
        ssl.create_default_context(cadata=certificate.decode('ascii'))
        private_write(self.ca_path, certificate)

    def _services(self):
        output = self._run(['ps', '-a', '--format', 'json']).decode().strip()
        try:
            rows = json.loads(output) if output else []
            if isinstance(rows, dict):
                rows = [rows]
        except ValueError:
            try:
                rows = [json.loads(line) for line in output.splitlines()]
            except ValueError:
                raise CollectorError('Cannot read the selected Docker project status.') from None
        return {row['Service']: row for row in rows}

    def status(self):
        result = dict(initialized=False, api_ready=False, database_ready=False, worker_running=False,
                      sources=0, batches=0, revisions=0, quarantined_batches=0, failed_jobs=0,
                      upload_url=self.settings.upload_url, data_dir=str(self.settings.data_dir), error=None)
        services = self._services()
        ready = lambda name: services.get(name, {}).get('State') == 'running'
        healthy = lambda name: ready(name) and services[name].get('Health') == 'healthy'
        result['initialized'] = 'db' in services
        result['worker_running'] = ready('worker')
        if ready('caddy'):
            try:
                self._refresh_ca()
                with httpx.Client(verify=ssl.create_default_context(cafile=str(self.ca_path)), trust_env=False, timeout=3) as client:
                    response = client.post(self.settings.upload_url.replace('/v1/uploads', '/v1/collector-check'), json={})
                    result['api_ready'] = healthy('api') and response.status_code == 401
            except (CollectorError, httpx.HTTPError, OSError, ValueError):
                pass
        if healthy('db'):
            try:
                result.update(self._rpc('counts'))
                result['database_ready'] = True
            except CollectorError as error:
                result['error'] = str(error)
        else:
            result['error'] = 'Docker Central Server is stopped. Use Start Docker server to resume it.'
        return result

    def start(self):
        before = self._services()
        try:
            self._run(['up', '-d', '--wait', '--wait-timeout', '180'], timeout=240)
            for attempt in range(3):
                result = self.status()
                if all(result[key] for key in ('api_ready', 'database_ready', 'worker_running')):
                    return result
                if attempt < 2:
                    time.sleep(.5)
            raise CollectorError('Docker startup did not reach API, database and worker readiness. Check the selected project logs.')
        except CollectorError:
            for name in ('api', 'worker'):
                if before.get(name, {}).get('State') != 'running':
                    try:
                        self._run(['stop', '--timeout', '15', name], timeout=45)
                    except CollectorError:
                        pass
            raise

    def stop(self):
        self._run(['stop', '--timeout', '30'], timeout=150)
        return self.status()

    def catalog(self):
        return self._rpc('catalog')

    def sources(self):
        return self._rpc('sources')

    def register(self, **arguments):
        return self._rpc('register', arguments)

    def delete_source(self, source_id):
        return self._rpc('delete_source', dict(source_id=source_id))

    def rotate(self, source_id):
        return self._rpc('rotate', dict(source_id=source_id))

    def batches(self, source_id):
        return self._rpc('batches', dict(source_id=source_id))

    def machine_interpretations(self, include_records=True):
        if not include_records:
            return dict(configuration=dict(enabled=False, model='Not configured in Docker'), rows=[], records_available=False)
        return self._rpc('machine_interpretations')

    def export(self, source_id, path, password):
        path = Path(path).absolute()
        if path.exists() or path.is_symlink() or not path.parent.is_dir():
            raise CollectorError('Choose a new setup filename in an existing folder; existing files are preserved.')
        self._refresh_ca()
        result = self._rpc('export', dict(source_id=source_id, path='/exports/' + path.name, password=password), path.parent.resolve())
        return dict(result, path=str(path))

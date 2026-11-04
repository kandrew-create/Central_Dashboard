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
    http_port: int = 80

    def __post_init__(self):
        ServerSettings(self.workspace, self.postgres_bin, mode=self.mode, server_host=self.server_host,
                       listen_address=self.listen_address).validate_network()
        if type(self.https_port) is not int or not 1 <= self.https_port <= 65535:
            raise CollectorError('Choose a valid HTTPS port for the Docker server.')
        if type(self.http_port) is not int or not 1 <= self.http_port <= 65535 or self.http_port == self.https_port:
            raise CollectorError('Choose different valid HTTP and HTTPS ports for the Docker server.')

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


class GatewayMountError(CollectorError):
    """A failed Caddyfile mount can be recovered by recreating only the gateway."""


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
        from server.management.docker_configuration import deployment_lock, recover_settings
        with deployment_lock(workspace):
            recover_settings(workspace)
        self._environment = private_read(workspace / '.env', 16384)
        environment = self._environment.decode('utf-8')
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
                                       listen_address=values.get('LINKER_LISTEN_ADDRESS', '127.0.0.1'), https_port=https_port,
                                       http_port=http_port)
        self.config_keys = set(values)
        self.ai_provider = values.get('LINKER_AI_PROVIDER', '1')
        if self.ai_provider not in ('1', 'container'):
            raise CollectorError('Choose host (1) or container for the saved local AI provider.')
        self.files = [workspace / 'deploy' / name for name in ('docker-compose.yml', 'docker-compose.wsl.yml')]
        if any(not file.is_file() for file in self.files):
            raise CollectorError('Select the WSL workspace containing its Compose file and saved deployment override.')
        self._override = self.files[1].read_bytes()
        private_directory(self.settings.data_dir)
        private_write(self.settings.data_dir / 'agent-compose.yml',
                      b'services:\n  migrate:\n    logging: !override\n      driver: none\n')
        private_write(self.settings.data_dir / 'ai-compose.yml',
                      ('services:\n  migrate:\n    networks: !override\n      - database\n      - gateway\n' +
                       ('      - local-ai\n' if self.ai_provider == 'container' else '') +
                       'volumes:\n  ai-settings:\n').encode())
        self.export_directory = private_directory(workspace / 'exports')
        self.ca_path = workspace / 'caddy-root.crt'

    def _command(self, arguments):
        command = ['docker', '--host', 'unix:///var/run/docker.sock', 'compose',
                   '--project-name', self.settings.project, '--env-file', str(self.settings.workspace / '.env')]
        for file in self.files:
            command.extend(('-f', str(file)))
        if getattr(self, 'ai_provider', '1') == 'container':
            command.extend(('--profile', 'local-ai'))
        return command + list(arguments)

    def _assert_current(self):
        if (private_read(self.settings.workspace / '.env', 16384) != self._environment
                or self.files[1].read_bytes() != self._override):
            raise CollectorError('Deployment settings changed outside this window. Reopen the manager before continuing.')

    def _run(self, arguments, payload=None, timeout=90, agent=False):
        environment = {key: value for key, value in os.environ.items()
                       if key not in self.config_keys and not key.startswith('COMPOSE_')
                       and not key.startswith('LINKER_MANAGER_')
                       and key not in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'LINKER_HTTP_PORT', 'LINKER_HTTPS_PORT',
                                       'LINKER_MODE', 'LINKER_LISTEN_ADDRESS', 'SCADA_HOSTNAME', 'LINKER_AI_PROVIDER')}
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
            # Classify known faults without displaying native output, which may contain secrets.
            detail = (result.stdout + result.stderr).lower()
            if any(marker in detail for marker in (
                    b'cannot connect to the docker daemon', b'is the docker daemon running',
                    b'failed to connect to the docker api', b'could not be found in this wsl 2 distro')):
                raise CollectorError('Docker Desktop is not reachable. Start Docker Desktop, wait for its engine, '
                                     'and enable Ubuntu integration, then refresh and retry.')
            if any(marker in detail for marker in (
                    b'ports are not available', b'address already in use', b'only one usage of each socket address')):
                raise CollectorError(f'Cannot publish HTTPS at {self.settings.listen_address}:{self.settings.https_port}. '
                                     'Check that this address belongs to the Windows host and the port is free. '
                                     'If Windows Central Server uses the same endpoint, use its Stop server action '
                                     'before starting WSL/Docker. Existing data is retained.')
            if b'/etc/caddy/caddyfile' in detail and b'error mounting' in detail:
                raise GatewayMountError('The HTTPS gateway configuration mount failed. Check the saved Caddyfile '
                                        'in this WSL workspace; existing data and certificates are retained.')
            raise CollectorError('Docker operation failed. Check Docker Desktop and the selected WSL project; existing data is retained.')
        return result.stdout

    def _rpc(self, action, arguments=None, export_parent=None):
        self._assert_current()
        ai_action = action in ('machine_interpretations', 'enable_machine_ai', 'disable_machine_ai')
        identity = '10001:10001' if ai_action else f'{os.getuid()}:{os.getgid()}'
        command = ['-f', str(self.settings.data_dir / 'agent-compose.yml')]
        if ai_action:
            command += ['-f', str(self.settings.data_dir / 'ai-compose.yml')]
        command += ['run', '--rm', '--no-deps', '-T', '--user', identity,
                   '-e', 'LINKER_MANAGER_HTTPS_PORT=' + str(self.settings.https_port),
                   '-e', 'LINKER_MANAGER_MODE=' + self.settings.mode,
                   '-e', 'LINKER_MANAGER_HOST=' + self.settings.server_host,
                   '-e', 'LINKER_MANAGER_LISTEN_ADDRESS=' + self.settings.listen_address,
                   '--volume', bind_mount(self.settings.data_dir, '/manager-state')]
        if ai_action:
            command += ['-e', 'LINKER_MANAGER_AI_DIR=/ai-settings', '-e', 'LINKER_DOCKER_LOCAL_AI=' + getattr(self, 'ai_provider', '1'),
                        '--volume', self.settings.project + '_ai-settings:/ai-settings']
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

    def start_if_needed(self):
        self._assert_current()
        result = self.status()
        if all(result[key] for key in ('api_ready', 'database_ready', 'worker_running')):
            return result
        return self.start()

    def start(self):
        self._assert_current()
        before = self._services()
        try:
            try:
                self._run(['up', '-d', '--wait', '--wait-timeout', '180'], timeout=240)
            except GatewayMountError:
                caddyfile = self.settings.workspace / 'deploy' / 'wsl' / (
                    'Caddyfile.network' if self.settings.mode == 'network' else 'Caddyfile.local')
                if not caddyfile.is_file():
                    raise
                # Docker Desktop can retain a stale WSL file mount after a restart.
                # Recreate only Caddy, retaining its named certificate/configuration volumes.
                self._run(['up', '-d', '--no-deps', '--force-recreate', 'caddy'], timeout=90)
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

    def validate_settings(self, candidate):
        from server.management.docker_configuration import probe_host
        if candidate.workspace != self.settings.workspace or candidate.project != self.settings.project:
            raise CollectorError('Keep this server workspace and project. Moving storage requires a separate migration.')
        ports = []
        if self._services().get('caddy', {}).get('State') == 'running':
            if (candidate.listen_address == self.settings.listen_address or
                    '0.0.0.0' in (candidate.listen_address, self.settings.listen_address)):
                ports = [self.settings.https_port]
                if self.settings.mode == 'local':
                    ports.append(self.settings.http_port)
        probe_host(candidate, ports)
        return candidate

    def save_settings(self, candidate):
        from server.management.docker_configuration import deployment_lock, environment_update, save_pair
        workspace = self.settings.workspace
        with deployment_lock(workspace):
            if private_read(workspace / '.env', 16384) != self._environment or self.files[1].read_bytes() != self._override:
                raise CollectorError('Deployment settings changed outside this window. Reopen the manager before saving.')
            if any(row.get('State') in ('running', 'restarting', 'paused') for row in self._services().values()):
                raise CollectorError('Stop this Docker server before saving deployment settings, or use Apply and restart.')
            self.validate_settings(candidate)
            template = workspace / 'deploy/wsl' / ('docker-compose.network.yml.template' if candidate.mode == 'network'
                                                   else 'docker-compose.wsl.yml.template')
            content = environment_update(self._environment, candidate)
            save_pair(workspace, content, template.read_bytes(), lambda: self._run(['config', '--quiet']))
            self._environment, self._override = content, self.files[1].read_bytes()
            self.settings = candidate
        return candidate

    def apply_settings(self, candidate):
        self._assert_current()
        self.validate_settings(candidate)
        self.stop()
        self.save_settings(candidate)
        try:
            return self.start()
        except CollectorError as error:
            raise CollectorError('Server settings were saved successfully, but startup failed. ' + str(error)) from None

    def catalog(self):
        return self._rpc('catalog')

    def load_refresh_settings(self):
        path = self.settings.data_dir / 'gui-refresh.json'
        if not path.exists():
            return dict(interval_seconds=60)
        try:
            value = json.loads(private_read(path, 2048))
            if set(value) != {'interval_seconds'}:
                raise ValueError()
            self._validate_refresh_interval(value['interval_seconds'])
            return value
        except (OSError, ValueError, TypeError, KeyError):
            raise CollectorError('Cannot read automatic refresh settings. Save a new interval in Deployment.') from None

    @staticmethod
    def _validate_refresh_interval(seconds):
        if type(seconds) is not int or (seconds != 0 and not 5 <= seconds <= 3600):
            raise CollectorError('Choose Off (0), or an automatic refresh interval from 0.08 to 60 minutes.')

    def save_refresh_settings(self, seconds):
        self._validate_refresh_interval(seconds)
        value = dict(interval_seconds=seconds)
        try:
            private_write(self.settings.data_dir / 'gui-refresh.json', json.dumps(value).encode())
        except OSError:
            raise CollectorError('Cannot save automatic refresh settings. Check the private settings folder.') from None
        return value

    def sources(self):
        return self._rpc('sources')

    def alarm_analysis(self, days=30, source_id=None, customer_id=None):
        return self._rpc('alarm_analysis', dict(days=days, source_id=source_id, customer_id=customer_id))

    def register(self, **arguments):
        return self._rpc('register', arguments)

    def delete_source(self, source_id):
        return self._rpc('delete_source', dict(source_id=source_id))

    def rotate(self, source_id):
        return self._rpc('rotate', dict(source_id=source_id))

    def batches(self, source_id):
        return self._rpc('batches', dict(source_id=source_id))

    def machine_interpretations(self, include_records=True):
        return self._rpc('machine_interpretations', dict(include_records=include_records))

    def enable_machine_ai(self, model):
        return self._rpc('enable_machine_ai', dict(model=model))

    def disable_machine_ai(self):
        return self._rpc('disable_machine_ai')

    def export(self, source_id, path, password):
        path = Path(path).absolute()
        if path.exists() or path.is_symlink() or not path.parent.is_dir():
            raise CollectorError('Choose a new setup filename in an existing folder; existing files are preserved.')
        self._refresh_ca()
        result = self._rpc('export', dict(source_id=source_id, path='/exports/' + path.name, password=password), path.parent.resolve())
        return dict(result, path=str(path))

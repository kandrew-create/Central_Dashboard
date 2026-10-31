"""Stdlib-only WSL installer. Never resets databases, credentials, queues or WSL distributions."""
import argparse
import contextlib
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shlex
import socket
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class SetupError(Exception):
    pass


def emit(step, message):
    print(json.dumps(dict(step=step, message=message)), flush=True)


def options(folder, project, http_port, https_port):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', folder):
        raise SetupError('Use a simple folder name below your Linux home directory.')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}', project):
        raise SetupError('Use a lowercase Docker project name containing letters, digits, underscores or dashes.')
    if not all(type(value) is int and 1 <= value <= 65535 for value in (http_port, https_port)) or http_port == https_port:
        raise SetupError('Choose different valid HTTP and HTTPS ports.')


def private_dir(path):
    path = Path(path)
    if path.is_symlink():
        raise SetupError('Setup cannot use a symbolic link for private local state.')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise SetupError('The selected workspace and private state must be owned by this Linux account with mode 0700.')
    return path


def atomic_write(path, content, mode=0o600):
    path = Path(path)
    if path.is_symlink():
        raise SetupError('Setup refuses to replace a symbolic link.')
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.setup-')
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def validated_payload(payload, manifest):
    if manifest.get('format') != 1 or manifest.get('database_major') != 17:
        raise SetupError('This application package is not supported by this installer.')
    if hashlib.sha256(Path(payload).read_bytes()).hexdigest() != manifest['payload_sha256']:
        raise SetupError('The application package checksum does not match. Download a fresh installer.')
    result = {}
    with tarfile.open(payload, 'r:gz') as archive:
        for member in archive.getmembers():
            name = PurePosixPath(member.name)
            if (not member.isfile() or member.name != str(name) or name.is_absolute() or '..' in name.parts or str(name) in result
                    or member.size > 8 * 1024 * 1024 or member.name not in manifest['files']):
                raise SetupError('The application package contains an invalid entry.')
            if (name.parts[0] not in ('server', 'collector', 'shared', 'deploy') and str(name) not in
                    ('pyproject.toml', 'alembic.ini', '.dockerignore')):
                raise SetupError('The application package contains an unsupported path.')
            if {'secrets', '.env', '.tools', '.venv', '.venv-gui', 'tests'}.intersection(name.parts):
                raise SetupError('Operational state cannot be included in an application package.')
            if name.suffix in ('.dpapi', '.vault', '.key', '.db', '.log', '.linker-collector'):
                raise SetupError('Private local files cannot be included in an application package.')
            data = archive.extractfile(member).read()
            metadata = manifest['files'][member.name]
            if (metadata['mode'] not in (0o644, 0o755) or len(data) != metadata['size']
                    or hashlib.sha256(data).hexdigest() != metadata['sha256']):
                raise SetupError('An application file failed integrity verification.')
            result[member.name] = data
    if set(result) != set(manifest['files']) or sum(map(len, result.values())) > 32 * 1024 * 1024:
        raise SetupError('The application package is incomplete or too large.')
    return result


def existing_environment(path):
    if path.is_symlink() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise SetupError('Existing .env must be a private file owned by this Linux account. It has not been changed.')
    values = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('\"\'')
    mode = values.get('LINKER_MODE', 'local')
    host = values.get('SCADA_HOSTNAME', '')
    listener = values.get('LINKER_LISTEN_ADDRESS', '127.0.0.1')
    try:
        address = ipaddress.IPv4Address(listener)
        try:
            destination = ipaddress.IPv4Address(host)
            valid_host = not (destination.is_unspecified or destination.is_multicast or destination.is_loopback)
        except ValueError:
            valid_host = bool(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*', host))
            valid_host = valid_host and len(host) <= 253 and host != 'localhost' and not host.endswith('.localhost') and not all(c in '0123456789.' for c in host)
        valid = ((mode == 'local' and host == 'localhost' and listener == '127.0.0.1') or
                 (mode == 'network' and valid_host and not address.is_loopback and not address.is_multicast))
        if not valid:
            raise ValueError()
    except ValueError:
        raise SetupError('Saved connection mode, server hostname or listen address is invalid. Existing settings were preserved.') from None
    from urllib.parse import unquote
    for key, user, password in (('MIGRATION_DATABASE_URL', 'scada_migrator', 'POSTGRES_PASSWORD'),
                                ('INGEST_DATABASE_URL', 'scada_api_login', 'INGEST_DATABASE_PASSWORD'),
                                ('WORKER_DATABASE_URL', 'scada_worker_login', 'WORKER_DATABASE_PASSWORD')):
        url = urlsplit(values.get(key, ''))
        if ((url.scheme, url.hostname, url.username, url.path) != ('postgresql+psycopg', 'db', user, '/scada_platform')
                or url.port not in (None, 5432) or not url.password or unquote(url.password) != values.get(password)):
            raise SetupError('Existing credentials must target this project\'s Central database service. No settings were replaced.')
    return values


def new_environment(http_port, https_port):
    passwords = {name: secrets.token_hex(24) for name in ('migration', 'api', 'worker')}
    values = dict(POSTGRES_PASSWORD=passwords['migration'],
                  MIGRATION_DATABASE_URL=f"postgresql+psycopg://scada_migrator:{passwords['migration']}@db:5432/scada_platform",
                  INGEST_DATABASE_PASSWORD=passwords['api'], WORKER_DATABASE_PASSWORD=passwords['worker'],
                  INGEST_DATABASE_URL=f"postgresql+psycopg://scada_api_login:{passwords['api']}@db:5432/scada_platform",
                  WORKER_DATABASE_URL=f"postgresql+psycopg://scada_worker_login:{passwords['worker']}@db:5432/scada_platform",
                  SCADA_HOSTNAME='localhost', LINKER_HTTP_PORT=str(http_port), LINKER_HTTPS_PORT=str(https_port))
    return ('\n'.join(key + '=' + value for key, value in values.items()) + '\n').encode()


class Installer:
    def __init__(self, args):
        options(args.folder, args.project, args.http_port, args.https_port)
        self.args = args
        self.home = Path.home().resolve()
        self.workspace = self.home / args.folder
        if self.workspace.is_symlink() or self.workspace.resolve().parent != self.home:
            raise SetupError('Select a dedicated directory directly below this Linux account\'s home.')
        self.existing = (self.workspace / '.env').is_file()
        self.environment_keys = {'POSTGRES_PASSWORD', 'MIGRATION_DATABASE_URL', 'INGEST_DATABASE_URL',
                                 'WORKER_DATABASE_URL', 'INGEST_DATABASE_PASSWORD', 'WORKER_DATABASE_PASSWORD',
                                 'LINKER_HTTP_PORT', 'LINKER_HTTPS_PORT', 'SCADA_HOSTNAME'}
        self.environment_keys.update(('LINKER_MODE', 'LINKER_LISTEN_ADDRESS'))

    def run(self, command, *, payload=None, timeout=900, message='A setup command failed.', env=None):
        environment = {key: value for key, value in os.environ.items() if key not in self.environment_keys
                       and not key.startswith('COMPOSE_') and key not in ('DOCKER_HOST', 'DOCKER_CONTEXT')}
        if env:
            environment.update(env)
        try:
            result = subprocess.run(command, input=payload, capture_output=True, cwd=self.workspace if self.workspace.exists() else self.home,
                                    env=environment, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            raise SetupError(message) from None
        if result.returncode:
            raise SetupError(message)
        return result.stdout

    def docker(self, *arguments, **kwargs):
        return self.run(['docker', '--host', 'unix:///var/run/docker.sock', *arguments], **kwargs)

    def compose(self, *arguments, **kwargs):
        return self.docker('compose', '--project-name', self.args.project, '--env-file', str(self.workspace / '.env'),
                           '-f', str(self.workspace / 'deploy/docker-compose.yml'),
                           '-f', str(self.workspace / 'deploy/docker-compose.wsl.yml'), *arguments, **kwargs)

    def containers(self):
        output = self.docker('ps', '-a', '--filter', 'label=com.docker.compose.project=' + self.args.project,
                             '--format', '{{.ID}}').decode().splitlines()
        result = []
        for identifier in output:
            info = json.loads(self.docker('inspect', '--format',
                              '{"labels":{{json .Config.Labels}},"state":{{json .State.Status}},"ports":{{json .HostConfig.PortBindings}}}', identifier))
            files = info['labels'].get('com.docker.compose.project.config_files', '')
            if str(self.workspace / 'deploy/docker-compose.yml') not in files.split(','):
                raise SetupError('This Docker project belongs to another workspace. Choose another project name; its data was preserved.')
            info['id'] = identifier
            result.append(info)
        return result

    def preflight(self, package):
        if os.getuid() == 0:
            raise SetupError('Finish Ubuntu setup with a normal Linux account before installing the application.')
        if self.workspace.exists() and not self.existing and any(self.workspace.iterdir()):
            raise SetupError('The selected folder contains files without saved server settings. Select a new folder; existing files are preserved.')
        private_dir(self.workspace)
        processes = self.run(['ps', '-u', str(os.getuid()), '-o', 'args='], message='Cannot check the selected manager window.').decode()
        for line in processes.splitlines():
            try:
                arguments = shlex.split(line)
            except ValueError:
                continue
            if any(module in arguments for module in ('server.management.qt_docker_gui', 'server.management.docker_gui')):
                selected = Path(arguments[arguments.index('--workspace') + 1]) if '--workspace' in arguments else self.home / 'central-server'
                if selected.resolve() == self.workspace.resolve():
                    raise SetupError('Close the manager window for this workspace, then retry setup. No files were replaced.')
        values = dict(SCADA_HOSTNAME='localhost', LINKER_MODE='local')
        if self.existing:
            values = existing_environment(self.workspace / '.env')
            try:
                self.args.http_port = int(values.get('LINKER_HTTP_PORT', '80'))
                self.args.https_port = int(values.get('LINKER_HTTPS_PORT', '443'))
            except ValueError:
                raise SetupError('Saved HTTP/HTTPS ports are invalid. Existing settings were preserved.') from None
            options(self.args.folder, self.args.project, self.args.http_port, self.args.https_port)
        receipt_path = self.workspace / 'secrets/docker-install.json'
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text())
            if receipt.get('project') != self.args.project or receipt.get('workspace') != str(self.workspace):
                raise SetupError('This workspace was installed for another Docker project. Restore its setup options; data was preserved.')
        if (self.workspace / '.venv-gui').is_symlink():
            raise SetupError('The private Python environment cannot be a linked directory. Existing files were preserved.')
        volume = self.args.project + '_postgres-data'
        volumes = self.docker('volume', 'ls', '--format', '{{.Name}}').decode().splitlines()
        if volume in volumes:
            if not self.existing:
                raise SetupError('Saved Docker data exists without matching local credentials. Restore its settings or choose another project; data was preserved.')
            major = self.docker('run', '--rm', '--network', 'none', '--entrypoint', 'cat',
                                '--volume', volume + ':/database:ro', 'postgres:17.6', '/database/PG_VERSION',
                                message='Cannot verify the existing Central database version. Data was preserved.').decode().strip()
            if major != str(package['database_major']):
                raise SetupError('Existing PostgreSQL data uses another major version. A separate migration is required; data was preserved.')
        containers = self.containers()
        if any(info['state'] == 'running' and info['labels'].get('com.docker.compose.oneoff', '').lower() == 'true' for info in containers):
            raise SetupError('A management command is still running for this workspace. Wait for it to finish and retry setup.')
        owned_ports = {int(binding['HostPort']) for item in containers if item['state'] == 'running'
                       for bindings in (item['ports'] or {}).values() for binding in bindings or []}
        ports = (self.args.https_port,) if values.get('LINKER_MODE') == 'network' else (self.args.http_port, self.args.https_port)
        for port in ports:
            with socket.socket() as probe:
                probe.settimeout(.5)
                if probe.connect_ex((values['SCADA_HOSTNAME'], port)) == 0 and port not in owned_ports:
                    raise SetupError('A selected localhost port is in use by another application. Choose different ports; no server was stopped.')
        return containers

    def install_code(self, files, manifest):
        backup = private_dir(self.workspace / 'secrets' / ('code-backup-' + str(time.time_ns())))
        for name, data in files.items():
            target = self.workspace / name
            for parent in target.relative_to(self.workspace).parents:
                if (self.workspace / parent).is_symlink():
                    raise SetupError('An application directory is a symbolic link. No linked target was modified.')
            if target.is_symlink():
                raise SetupError('An application file is a symbolic link. Its target was preserved.')
            if target.is_file():
                saved = backup / name
                saved.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(saved, target.read_bytes(), target.stat().st_mode & 0o777)
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(target, data, manifest['files'][name]['mode'])
        override = self.workspace / 'deploy/docker-compose.wsl.yml'
        if not override.exists():
            atomic_write(override, files['deploy/wsl/docker-compose.wsl.yml.template'], 0o600)

    def install_uv(self, package):
        requirements = json.loads(Path(self.args.prerequisites).read_text())['uv']
        archive = Path(self.args.uv_archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != requirements['sha256']:
            raise SetupError('The bundled Linux setup tool failed its checksum check.')
        directory = private_dir(self.workspace / 'secrets' / 'setup-tools')
        with tarfile.open(archive, 'r:gz') as source:
            members = [item for item in source.getmembers() if item.isfile() and PurePosixPath(item.name).name == 'uv']
            if len(members) != 1 or members[0].size > 100 * 1024 * 1024:
                raise SetupError('The bundled Linux setup tool is invalid.')
            atomic_write(directory / 'uv', source.extractfile(members[0]).read(), 0o700)
        return directory / 'uv'

    def verify(self):
        ca = self.compose('exec', '-T', 'caddy', 'cat', '/data/caddy/pki/authorities/local/root.crt',
                          message='The server did not produce its public HTTPS CA certificate.')
        ca_path = self.workspace / 'caddy-root.crt'
        if ca_path.exists() and ca_path.read_bytes() != ca:
            raise SetupError('The saved and server CA certificates do not match. Existing trust settings were preserved; inspect the selected Docker volumes.')
        atomic_write(ca_path, ca)
        port = '' if self.args.https_port == 443 else ':' + str(self.args.https_port)
        hostname = existing_environment(self.workspace / '.env')['SCADA_HOSTNAME']
        request = urllib.request.Request('https://' + hostname + port + '/v1/collector-check', data=b'{}',
                                         headers={'Content-Type': 'application/json'})
        try:
            urllib.request.urlopen(request, context=ssl.create_default_context(cafile=str(ca_path)), timeout=10)
        except urllib.error.HTTPError as error:
            if error.code != 401:
                raise SetupError('HTTPS did not return the expected authenticated endpoint response.') from None
        except (OSError, urllib.error.URLError):
            raise SetupError('Cannot verify local HTTPS. Data and credentials were preserved.') from None
        else:
            raise SetupError('The upload connection test unexpectedly accepted an unauthenticated request.')

    def install(self):
        # The home lock also serializes the first installation before .env exists.
        path = self.home / ('.linker-setup-' + self.args.folder + '.lock')
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'a+b') as lock:
            info = os.fstat(lock.fileno())
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise SetupError('The setup lock must be private to this Linux account.')
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SetupError('Another setup is already working on this workspace.') from None
            self.existing = (self.workspace / '.env').is_file()
            return self._install()

    def _install(self):
        emit('verify', 'Checking package integrity and the selected Linux workspace…')
        manifest = json.loads(Path(self.args.manifest).read_text())
        files = validated_payload(self.args.payload, manifest)
        containers = self.preflight(manifest)
        state = private_dir(self.workspace / 'secrets')
        lock_path = state / 'setup.lock'
        if lock_path.is_symlink():
            raise SetupError('The setup lock cannot be a symbolic link. Existing files were preserved.')
        with lock_path.open('a+b') as lock:
            os.chmod(lock_path, 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SetupError('Another setup is already working on this workspace.') from None
            if any(info['state'] == 'running' for info in containers):
                emit('stop', 'Stopping only the configured Docker project before updating application files…')
                self.compose('stop', '--timeout', '30', message='The configured server could not stop safely. No application files were replaced.')
            emit('application', 'Installing application files; existing settings, keys and data are retained…')
            if not self.existing:
                atomic_write(self.workspace / '.env', new_environment(self.args.http_port, self.args.https_port))
            self.install_code(files, manifest)
            uv = self.install_uv(manifest)
            emit('python', 'Preparing the private Python 3.13 and Qt environment…')
            interpreter = self.workspace / '.venv-gui/bin/python'
            if not interpreter.exists():
                self.run([str(uv), 'venv', '--python', '3.13', str(interpreter.parent.parent)],
                         message='Cannot download or prepare private Python. Check internet access and retry; no data was removed.')
            version = self.run([str(interpreter), '-c', 'import sys;print(str(sys.version_info.major)+"."+str(sys.version_info.minor))']).decode().strip()
            if version not in ('3.12', '3.13'):
                raise SetupError('The existing private Python version is unsupported. It was preserved; use Python 3.12 or 3.13.')
            self.run([str(uv), 'pip', 'install', '--python', str(interpreter), '-r', str(self.workspace / 'deploy/requirements.lock'),
                      '-e', str(self.workspace) + '[docker-gui]'], message='Cannot install GUI dependencies. Check internet access and retry setup.')
            self.run([str(interpreter), '-c', 'from PySide6.QtWidgets import QApplication; app=QApplication([])'],
                      env={'QT_QPA_PLATFORM': 'offscreen'}, message='The Linux GUI dependencies are incomplete. Retry prerequisite installation.')
            emit('images', 'Building the Docker application images. First installation needs internet access…')
            self.compose('config', '--quiet', message='The saved Docker configuration is invalid. Existing settings were preserved.')
            self.compose('build', message='Docker image build failed. Check Docker Desktop and internet access; existing data is retained.')
            emit('server', 'Starting PostgreSQL, HTTPS, API and worker in the selected project…')
            try:
                # Atomic source replacement changes file inodes. Recreate containers so
                # Docker Desktop refreshes WSL file mounts; named data volumes stay put.
                self.compose('up', '-d', '--force-recreate', '--wait', '--wait-timeout', '180', timeout=240,
                             message='The Docker server did not reach readiness. Check this project; data and credentials are retained.')
                self.verify()
            except SetupError:
                with contextlib.suppress(SetupError):
                    self.compose('stop', '--timeout', '15', 'api', 'worker', timeout=60)
                raise
            receipt = dict(format=1, project=self.args.project, workspace=str(self.workspace),
                           application_version=manifest['application_version'], payload_sha256=manifest['payload_sha256'],
                           http_port=self.args.http_port, https_port=self.args.https_port, status='ready')
            atomic_write(state / 'docker-install.json', (json.dumps(receipt, indent=2) + '\n').encode())
        emit('ready', 'Central Server is ready. Open the GUI and register your SCADA sources.')
        return receipt


def main():
    parser = argparse.ArgumentParser()
    for name in ('payload', 'manifest', 'uv-archive', 'prerequisites'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--folder', default='central-server')
    parser.add_argument('--project', default='linker-scada-wsl')
    parser.add_argument('--http-port', type=int, default=80)
    parser.add_argument('--https-port', type=int, default=443)
    args = parser.parse_args()
    try:
        result = Installer(args).install()
    except SetupError as error:
        emit('error', str(error))
        return 1
    except Exception:
        emit('error', 'Setup could not complete. Existing local state was retained; check prerequisites and retry setup.')
        return 1
    print(json.dumps(dict(result=result)), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

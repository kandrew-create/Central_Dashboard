"""Scoped Docker actions for the local Collector desktop; no source access."""
import json
from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import threading
import time
from uuid import uuid4

from collector.errors import CollectorError


class DockerControl:
    def __init__(self, native_config=None):
        self.workspace = Path(__file__).resolve().parents[2]
        self.compose = self.workspace / 'deploy/docker-compose.collector.yml'
        self.native_config = native_config

    def _execute(self, arguments, timeout=30, payload=None):
        try:
            host = 'npipe:////./pipe/dockerDesktopLinuxEngine' if os.name == 'nt' else 'unix:///var/run/docker.sock'
            environment = {key: value for key, value in os.environ.items()
                           if key not in {'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'}
                           and not key.startswith('COMPOSE_')}
            return subprocess.run(
                ['docker', '--host', host, *arguments],
                cwd=self.workspace, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=timeout,
                input=payload,
                env=environment,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        except FileNotFoundError:
            raise CollectorError('Docker Desktop is not installed or its docker command is unavailable. Install or open Docker Desktop to manage the Collector.') from None
        except subprocess.TimeoutExpired:
            raise CollectorError('Docker timed out. Check Docker Desktop and the existing Collector deployment before retrying.') from None
        except OSError:
            raise CollectorError('Cannot run Docker. Check Docker Desktop installation and access permissions.') from None

    def _engine(self):
        result = self._execute(['info', '--format', '{{.OSType}}'])
        if result.returncode:
            # Classify internally; never expose Docker output or expanded settings.
            detail = (result.stderr or '').casefold()
            if 'access is denied' in detail or 'permission denied' in detail:
                return False, 'Docker engine access was denied. Check Docker Desktop access for this Windows account.'
            return False, 'Docker Desktop is not running or its engine is unavailable. Open Docker Desktop and wait for the Linux engine, then Refresh.'
        if result.stdout.strip() != 'linux':
            return False, 'The Docker Collector requires Linux containers. Switch Docker Desktop to Linux containers, then Refresh.'
        return True, None

    def command(self, *arguments):
        files = ['compose', '--project-name', 'linker-collector', '-f', str(self.compose)]
        host = self.compose.with_name('docker-compose.collector.host.yml')
        if host.is_file():
            files += ['-f', str(host)]
        return files + list(arguments)

    def rpc(self, action, arguments=None, stop=None):
        name = 'linker-collector-manager-' + uuid4().hex
        finished = threading.Event()

        def cancel():
            while not finished.wait(.1):
                if stop.is_set():
                    # Stop only this bounded operation; never terminate another
                    # collector or discard its queue. The agent handles SIGTERM.
                    try:
                        deadline = time.monotonic() + 60
                        while not finished.is_set():
                            ready = self._execute(['inspect', '--format', '{{.State.Running}}', name], timeout=5)
                            if ready.returncode == 0 and ready.stdout.strip() == 'true':
                                break
                            if time.monotonic() >= deadline or finished.wait(.1):
                                return
                        if finished.is_set():
                            return
                        self._execute(['stop', '--time', '120', name], timeout=150)
                    except CollectorError:
                        pass
                    return

        if stop is not None:
            threading.Thread(target=cancel, name='collector-operation-stop', daemon=True).start()
        try:
            result = self._execute(self.command('run', '--rm', '--no-deps', '-T', '--name', name, 'manager'),
                                   timeout=600, payload=json.dumps(dict(action=action, arguments=arguments or {})))
        finally:
            finished.set()
        try:
            response = json.loads(result.stdout)
            if not response['ok']:
                raise CollectorError(response['error'])
            if result.returncode:
                raise ValueError()
            return response['result']
        except (ValueError, KeyError, TypeError):
            raise CollectorError('Cannot contact the Docker Collector configuration. Check Docker Desktop and the commissioned Collector image/volumes.') from None

    def _call(self, *arguments, timeout=30):
        result = self._execute(self.command(*arguments), timeout)
        if result.returncode:
            detail = (result.stderr or '').casefold()
            if any(marker in detail for marker in ('dockerdesktoplinuxengine', 'is the docker daemon running', 'failed to connect to the docker api')):
                raise CollectorError('The Docker engine became unavailable. Open Docker Desktop, wait for the Linux engine and Refresh before retrying.')
            raise CollectorError('The Docker Collector operation failed. Check its image build and saved Docker configuration. Existing durable volumes are retained.')
        return result.stdout

    def perform(self, action):
        if action not in ('start', 'stop', 'status'):
            raise CollectorError('Unsupported Collector Docker action.')
        with ExitStack() as guard:
            if action == 'start' and self.native_config and self.native_config.state_path.is_file():
                from collector.state import State
                state = State(self.native_config)
                guard.callback(state.close)
                try:
                    guard.enter_context(state.lock(scheduler=True))
                    guard.enter_context(state.lock())
                except CollectorError:
                    raise CollectorError('The Windows Collector is already collecting, possibly in the notification area or another window. Stop it there before starting a separately configured Docker Collector. Its existing queue is preserved.') from None
            try:
                ready, message = self._engine()
            except CollectorError as error:
                if action != 'stop':
                    raise
                ready, message = False, str(error)
            if not ready:
                if action == 'stop':
                    return dict(running=False, engine_ready=False, action=action, stop_confirmed=False,
                                message='Docker stop could not be confirmed because its Linux engine is unavailable; no stop command was sent. '
                                        'Open Docker Desktop, wait for its Linux engine, then Refresh before stopping the Collector.')
                if action == 'status':
                    return dict(running=False, engine_ready=False, action=action, message=message)
                raise CollectorError(message)
            if action == 'start':
                self._call('up', '-d', '--build', 'collector', timeout=300)
            elif action == 'stop':
                self._call('stop', 'collector', timeout=150)
            try:
                raw = self._call('ps', '--all', '--format', 'json', 'collector').strip()
                rows = json.loads(raw) if raw.startswith('[') else [json.loads(line) for line in raw.splitlines() if line]
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    raise ValueError()
                running = any(row.get('State') == 'running' for row in rows)
            except (ValueError, TypeError):
                raise CollectorError('Docker returned an invalid Collector status.') from None
            return {'running': running, 'engine_ready': True, 'action': action}

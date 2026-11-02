"""Local deployment validation and recoverable settings writes; no database access."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time

from collector.errors import CollectorError
from server.management.linux_vault import private_directory, private_read, private_write


@contextmanager
def deployment_lock(workspace):
    import fcntl
    private_directory(workspace / 'secrets')
    descriptor = os.open(workspace / 'secrets/setup.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'r+b') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CollectorError('Another setup or settings operation is active. Wait for it to finish and retry.') from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def recover_settings(workspace):
    """A journal surviving an interrupted two-file save always restores the prior pair."""
    journal = workspace / 'secrets/deployment-change.json'
    if not journal.exists():
        return
    try:
        name = json.loads(private_read(journal, 2048))['backup']
        if not isinstance(name, str) or not name.startswith('deployment-backup-') or Path(name).name != name:
            raise ValueError()
        backup = private_directory(workspace / 'secrets' / name)
        for filename, target in (('environment', workspace / '.env'), ('override', workspace / 'deploy/docker-compose.wsl.yml')):
            private_write(target, private_read(backup / filename))
        journal.unlink()
    except (OSError, ValueError, KeyError, TypeError):
        raise CollectorError('Cannot recover the interrupted settings save. Preserve the private deployment backup and repair it before starting.') from None


def environment_update(content, settings):
    updates = dict(LINKER_MODE=settings.mode, SCADA_HOSTNAME=settings.server_host,
                   LINKER_LISTEN_ADDRESS=settings.listen_address, LINKER_HTTP_PORT=str(settings.http_port),
                   LINKER_HTTPS_PORT=str(settings.https_port))
    lines = []
    for line in content.decode('utf-8').splitlines():
        key = line.split('=', 1)[0].strip() if '=' in line and not line.lstrip().startswith('#') else ''
        # Replace every occurrence, so a duplicate cannot silently override the requested value.
        lines.append(key + '=' + updates[key] if key in updates else line)
    present = {line.split('=', 1)[0].strip() for line in lines if '=' in line and not line.lstrip().startswith('#')}
    lines.extend(key + '=' + value for key, value in updates.items() if key not in present)
    return ('\n'.join(lines) + '\n').encode('utf-8')


def save_pair(workspace, environment, override, validate):
    backup = private_directory(workspace / 'secrets' / ('deployment-backup-' + str(time.time_ns())))
    private_write(backup / 'environment', private_read(workspace / '.env', 16384))
    private_write(backup / 'override', (workspace / 'deploy/docker-compose.wsl.yml').read_bytes())
    journal = workspace / 'secrets/deployment-change.json'
    private_write(journal, json.dumps(dict(backup=backup.name)).encode())
    try:
        private_write(workspace / '.env', environment)
        private_write(workspace / 'deploy/docker-compose.wsl.yml', override)
        validate()
    except Exception:
        recover_settings(workspace)
        raise
    journal.unlink()


def probe_host(settings, owned_ports=()):
    ports = [settings.https_port] + ([settings.http_port] if settings.mode == 'local' else [])
    ports = [port for port in ports if port not in owned_ports]
    powershell = shutil.which('powershell.exe') if os.environ.get('WSL_DISTRO_NAME') else None
    if powershell:
        # WSL's adapters and sockets differ from the Windows host that publishes Docker ports.
        script = r'''$ErrorActionPreference='Stop'; $v=[Console]::In.ReadToEnd() | ConvertFrom-Json;
$sockets=@(); $result=@{address_available=$false; ports_free=$false};
try { foreach($port in (@(0)+@($v.ports))) {
  $s=[Net.Sockets.Socket]::new([Net.Sockets.AddressFamily]::InterNetwork,[Net.Sockets.SocketType]::Stream,[Net.Sockets.ProtocolType]::Tcp);
  $sockets+=,$s; $s.ExclusiveAddressUse=$true; $s.Bind([Net.IPEndPoint]::new([Net.IPAddress]::Parse($v.address),[int]$port));
  $result.address_available=$true;
}; $result.ports_free=$true } catch {} finally { foreach($s in $sockets) { $s.Dispose() } };
$result | ConvertTo-Json -Compress'''
        try:
            result = subprocess.run([powershell, '-NoProfile', '-NonInteractive', '-Command', script],
                                    input=json.dumps(dict(address=settings.listen_address, ports=ports)).encode(),
                                    capture_output=True, timeout=15)
            if result.returncode:
                raise ValueError()
            state = json.loads(result.stdout)
            if not state['address_available']:
                raise CollectorError('The HTTPS listen address is not assigned to this Windows server PC. Choose its IPv4 address or 0.0.0.0.')
            if not state['ports_free']:
                raise CollectorError('A selected server port is already bound. Stop the application using it, or choose another port.')
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
            raise CollectorError('Cannot validate the Windows host listener. Check Windows access and retry; settings were not changed.') from None
    else:
        if os.environ.get('WSL_DISTRO_NAME'):
            raise CollectorError('Windows listener validation is unavailable. Restore WSL Windows interoperability and retry.')
        try:
            with socket.socket() as probe:
                probe.bind((settings.listen_address, 0))
        except OSError:
            raise CollectorError('The HTTPS listen address is not assigned to this server PC.') from None
        for port in ports:
            try:
                with socket.socket() as probe:
                    probe.bind((settings.listen_address, port))
            except OSError:
                raise CollectorError('A selected server port is already bound. Stop the application using it, or choose another port.') from None

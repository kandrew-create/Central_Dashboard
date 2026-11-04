"""Bounded, console-free Docker Desktop startup for Windows WSL launchers."""
import os
from pathlib import Path
import subprocess
import time


class DesktopStartupError(RuntimeError):
    pass


def ensure_desktop(distribution, timeout=120):
    wsl = str(Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32/wsl.exe')
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('DOCKER_', 'COMPOSE_'))}

    def ready():
        try:
            result = subprocess.run(
                [wsl, '--distribution', distribution, '--exec', 'docker', '--host',
                 'unix:///var/run/docker.sock', 'info', '--format', '{{.OSType}}'],
                stdin=subprocess.DEVNULL, capture_output=True, env=environment,
                timeout=10, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            return result.returncode == 0 and result.stdout.strip() == b'linux'
        except (OSError, subprocess.TimeoutExpired):
            return False

    if ready():
        return
    locations = (Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/DockerDesktop/Docker Desktop.exe',
                 Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Docker/Docker/Docker Desktop.exe')
    desktop = next((path for path in locations if path.is_file()), None)
    if desktop is None:
        raise DesktopStartupError('Install Docker Desktop and enable its WSL integration for the selected Ubuntu distribution.')
    try:
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        subprocess.Popen([str(desktop)], startupinfo=startup, env=environment,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    except OSError:
        raise DesktopStartupError('Cannot start Docker Desktop. Open it once, finish its first-run prompts, and try again.') from None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ready():
            return
        time.sleep(1)
    raise DesktopStartupError('Docker Desktop did not become ready in time. Finish its first-run prompts and enable '
                              'WSL integration for the selected Ubuntu distribution, then reopen Central Server.')

"""Start Docker Desktop once; never install drivers, enable Windows features or reboot."""
import os
from pathlib import Path
import subprocess
import time

from collector.errors import CollectorError


def ensure_desktop(probe, timeout=120):
    def check():
        try:
            return probe()
        except CollectorError as error:
            return False, str(error)
    ready, message = check()
    if ready:
        return
    if os.name != 'nt':
        raise CollectorError(message or 'Start the local Docker engine before opening the Collector.')
    locations = (Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/DockerDesktop/Docker Desktop.exe',
                 Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Docker/Docker/Docker Desktop.exe')
    desktop = next((path for path in locations if path.is_file()), None)
    if desktop is None:
        raise CollectorError('Docker Desktop is not installed. Follow the Collector installation guide on the Collector PC; '
                             'Windows features and drivers are not changed automatically.')
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('DOCKER_', 'COMPOSE_'))}
    try:
        subprocess.Popen([str(desktop)], startupinfo=startup, env=environment,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    except OSError:
        raise CollectorError('Cannot start Docker Desktop. Open it once and finish its first-run prompts, then retry.') from None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, message = check()
        if ready:
            return
        time.sleep(1)
    raise CollectorError('Docker Desktop did not become ready in time. Finish its first-run prompts, select Linux '
                         'containers and refresh. Existing Collector state is retained.')

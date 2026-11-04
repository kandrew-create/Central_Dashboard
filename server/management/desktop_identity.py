"""Linux/WSLg desktop metadata matching the Qt application identity."""
import os
from pathlib import Path

from server.management.linux_vault import private_write


def runtime_caption():
    return 'WSL / Docker' if os.environ.get('WSL_DISTRO_NAME') else 'Linux / Docker'


def install_desktop_entry(workspace, project):
    workspace = Path(workspace)
    def quoted(value):
        value = str(value)
        if any(character in value for character in ('\n', '\r', '\x00')):
            raise ValueError('Invalid desktop launcher path.')
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'
    folder = Path.home() / '.local/share/applications'
    folder.mkdir(parents=True, exist_ok=True)
    content = ('[Desktop Entry]\nType=Application\nName=Central Server - '+runtime_caption().replace(' / ', ' ')+'\n'
               'Exec=/bin/bash ' + quoted(workspace / 'deploy/wsl/launch-manager.sh') + ' --project ' + quoted(project) + '\n'
               'Icon=' + str(workspace / 'deploy/wsl/central-server.png') + '\n'
               'StartupWMClass=linker-central-server\nTerminal=false\nCategories=Utility;\n')
    private_write(folder / 'linker-central-server.desktop', content.encode())

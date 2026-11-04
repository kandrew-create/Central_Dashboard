"""Open the source-checkout WSL manager without a Windows console (use pythonw)."""
import argparse
import ctypes
import os
from pathlib import Path
import subprocess

from server.management.windows_docker import DesktopStartupError, ensure_desktop


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--distribution', required=True)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--project', default='linker-scada-wsl')
    args = parser.parse_args()
    wsl = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32/wsl.exe'
    command = [str(wsl), '--distribution', args.distribution, '--exec', 'bash',
               args.workspace.rstrip('/') + '/deploy/wsl/launch-manager.sh',
               '--project', args.project]
    try:
        ensure_desktop(args.distribution)
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode == 0:
            return 0
    except DesktopStartupError as error:
        ctypes.windll.user32.MessageBoxW(None, str(error), 'Central Server - WSL Docker', 0x10)
        return 1
    except OSError:
        pass
    ctypes.windll.user32.MessageBoxW(
        None, 'The Central Server management window could not open or exited unexpectedly. '
        'Check Ubuntu and the selected WSL GUI installation, then try again.',
        'Central Server - WSL Docker', 0x10)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Stage only application sources needed by the packaged Docker manager."""
import argparse
from pathlib import Path
import shutil

RUNTIME_FILES = ('.dockerignore', 'deploy/collector/Dockerfile', 'deploy/collector/requirements.lock')
COMPOSE_FILES = ('deploy/docker-compose.collector.yml', 'deploy/docker-compose.collector.host.yml')
DESKTOP_FILES = (
    'deploy/docker-compose.collector.desktop.yml',
    'deploy/docker-compose.collector.container.yml',
    'deploy/collector/Dockerfile.desktop', 'deploy/collector/container_gui.py',
    'deploy/collector/control.py', 'deploy/collector/desktop.py',
    'deploy/collector/windows_runtime.py', 'deploy/collector/launch-container.sh',
    'deploy/collector/start-docker-desktop.ps1',
    'deploy/collector/windows-timezone.ps1',
    'deploy/collector/collector.png',
)


def stage(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Use an empty output directory for the Collector Docker context.')
    files = [root / name for name in (*RUNTIME_FILES, *COMPOSE_FILES, *DESKTOP_FILES)]
    for folder in ('collector', 'shared'):
        for path in (root / folder).rglob('*'):
            if (path.is_file() and path.suffix in ('.py', '.toml')
                    and not {'tests', '__pycache__', 'secrets'}.intersection(path.relative_to(root).parts)
                    and (path.suffix != '.toml' or path == root / 'collector/config.example.toml')):
                files.append(path)
    if any(not path.is_file() or path.is_symlink() for path in files):
        raise ValueError('A required Collector Docker source is missing or is a symbolic link.')
    for path in files:
        destination = output / path.relative_to(root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    return len(files)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    print(f'Staged {stage(options.root, options.output)} Collector Docker application files.')

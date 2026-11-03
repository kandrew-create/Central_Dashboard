"""Stage only application sources needed by the packaged Docker manager."""
import argparse
from pathlib import Path
import shutil

from deploy.wsl.build_payload import source_files

RUNTIME_FILES = frozenset(('pyproject.toml', 'alembic.ini', '.dockerignore',
                           'deploy/Dockerfile', 'deploy/requirements.lock'))
COMPOSE_FILES = ('deploy/docker-compose.collector.yml', 'deploy/docker-compose.collector.host.yml')


def stage(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Use an empty output directory for the Collector Docker context.')
    files = [path for path in source_files(root)
             if path.relative_to(root).parts[0] in {'collector', 'server', 'shared'}
             or path.relative_to(root).as_posix() in RUNTIME_FILES]
    files.extend(root / name for name in COMPOSE_FILES)
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

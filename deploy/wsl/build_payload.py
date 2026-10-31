"""Build a reproducible, allowlisted application payload without local operational state."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tomllib


TOP_FILES = ('pyproject.toml', 'alembic.ini', '.dockerignore')
DEPLOY_FILES = ('deploy/__init__.py', 'deploy/Dockerfile', 'deploy/requirements.lock',
                'deploy/wsl/launch-manager.sh', 'deploy/wsl/install-gui.sh',
                'deploy/wsl/docker-compose.wsl.yml.template', 'deploy/wsl/Caddyfile.local',
                'deploy/wsl/docker-compose.network.yml.template', 'deploy/wsl/Caddyfile.network',
                'deploy/docker-compose.yml')
SOURCE_EXTENSIONS = {'.py', '.sql', '.mako', '.toml'}


def source_files(root):
    root = Path(root)
    result = [root / name for name in (*TOP_FILES, *DEPLOY_FILES)]
    for folder in ('server', 'collector', 'shared'):
        for path in (root / folder).rglob('*'):
            if (path.is_file() and not path.is_symlink() and path.suffix in SOURCE_EXTENSIONS
                    and not {'tests', '__pycache__', 'secrets'}.intersection(path.relative_to(root).parts)):
                if path.suffix == '.sql' and path.parent != root / 'server/migrations/sql':
                    continue
                if path.suffix == '.toml' and path != root / 'collector/config.example.toml':
                    continue
                result.append(path)
    for path in result:
        if not path.is_file() or path.is_symlink():
            raise ValueError('A required package source is missing or is a symbolic link.')
    return sorted(set(result), key=lambda path: path.relative_to(root).as_posix())


def build(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    version = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    files = {}
    content = io.BytesIO()
    with tarfile.open(fileobj=content, mode='w', format=tarfile.PAX_FORMAT) as archive:
        for path in source_files(root):
            name = path.relative_to(root).as_posix()
            data = path.read_bytes()
            if path.suffix == '.sh':
                data = data.replace(b'\r\n', b'\n')
            entry = tarfile.TarInfo(name)
            entry.size, entry.mtime, entry.uid, entry.gid = len(data), 0, 0, 0
            entry.mode = 0o755 if path.suffix == '.sh' else 0o644
            archive.addfile(entry, io.BytesIO(data))
            files[name] = dict(sha256=hashlib.sha256(data).hexdigest(), size=len(data), mode=entry.mode)
    payload = output / 'application.tar.gz'
    with payload.open('wb') as stream, gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0) as compressed:
        compressed.write(content.getvalue())
    manifest = dict(format=1, application_version=version, database_major=17, files=files,
                    payload_sha256=hashlib.sha256(payload.read_bytes()).hexdigest())
    (output / 'application-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    result = build(options.root, options.output)
    print(json.dumps(dict(version=result['application_version'], files=len(result['files']), sha256=result['payload_sha256'])))

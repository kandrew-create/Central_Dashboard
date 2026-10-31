"""Build the separate online installer without replacing earlier Windows releases."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
import zipfile

import PyInstaller

from build_payload import build
from windows_setup import safe_download


def checksum(path):
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    Path(str(path) + '.sha256').write_text(digest + '  ' + Path(path).name + '\n', encoding='ascii')
    return digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if not args.compiler.is_file():
        raise SystemExit('Install Inno Setup 6 or pass --compiler.')
    version = tomllib.loads((root / 'pyproject.toml').read_text())['project']['version']
    (root / 'build').mkdir(exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='wsl-installer-', dir=root / 'build'))
    bundle = staging / 'bundle'
    payload = bundle / 'payload'
    payload.mkdir(parents=True)
    build(root, payload)
    for name in ('linux_setup.py', 'prerequisites.json'):
        shutil.copyfile(root / 'deploy/wsl' / name, payload / name)
    prerequisites = json.loads((payload / 'prerequisites.json').read_text())
    cache = root / '.cache/wsl-installer'
    cache.mkdir(parents=True, exist_ok=True)
    uv = prerequisites['uv']
    archive = safe_download(uv['url'], uv['sha256'], cache / ('uv-' + uv['version'] + '.tar.gz'))
    shutil.copyfile(archive, payload / 'uv-linux.tar.gz')
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--noconsole',
               '--name', 'linker-wsl-setup', '--distpath', str(bundle), '--workpath', str(staging / 'pyinstaller'),
               '--specpath', str(staging), str(root / 'deploy/wsl/windows_setup.py')]
    log = staging / 'pyinstaller.log'
    with log.open('w', encoding='utf-8') as stream:
        subprocess.run(command, cwd=root, stdout=stream, stderr=subprocess.STDOUT, check=True)
    (bundle / 'Setup.cmd').write_text('@echo off\r\nstart "" "%~dp0linker-wsl-setup.exe" %*\r\n', encoding='ascii')
    (bundle / 'Read me.txt').write_text(
        'Linker Central Server ' + version + ' - WSL / Docker online setup\n\n'
        'Run Setup.cmd. Windows 11 23H2+ x64 and internet access are required.\n'
        'Follow Windows restart, Ubuntu account and Docker first-run prompts, then resume.\n'
        'Python and Qt are installed privately in Linux; no Windows Python is required.\n'
        'Keep the same Ubuntu, folder and Docker project to retain existing settings and data.\n'
        'Close the selected server GUI before rerunning setup. Existing Windows packages are separate.\n'
        'Uninstalling the Windows launcher does not delete Linux files, Docker volumes or credentials.\n', encoding='utf-8')
    licenses = bundle / 'licenses'
    licenses.mkdir()
    for filename in ('LICENSE-MIT', 'LICENSE-APACHE'):
        with urllib.request.urlopen('https://raw.githubusercontent.com/astral-sh/uv/' + uv['version'] + '/' + filename, timeout=30) as response:
            (licenses / ('uv-' + filename + '.txt')).write_bytes(response.read())
    shutil.copyfile(Path(sys.base_prefix) / 'LICENSE.txt', licenses / 'Python.txt')
    shutil.copyfile(Path(sys.base_prefix) / 'tcl/tk8.6/license.terms', licenses / 'Tcl-Tk.txt')
    bootloader_license = next(Path(PyInstaller.__file__).parent.parent.glob('pyinstaller-*.dist-info/licenses/COPYING.txt'))
    shutil.copyfile(bootloader_license, licenses / 'PyInstaller.txt')
    (licenses / 'Read me.txt').write_text('The Windows launcher bundles CPython, Tcl/Tk and the PyInstaller bootloader.\n'
        'The Linux setup archive bundles uv ' + uv['version'] + '. Their notices are included here.\n'
        'Docker Desktop, Linux Python and Qt are downloaded during setup under their respective licenses.\n', encoding='utf-8')
    manifest = dict(format=1, application_version=version, files={
        path.relative_to(bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(bundle.rglob('*')) if path.is_file()})
    (bundle / 'package.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    output = root / 'dist/wsl-docker' / (version + '-' + staging.name.removeprefix('wsl-installer-'))
    output.mkdir(parents=True)
    name = 'Linker-Central-Server-WSL-Docker-Setup-' + version
    subprocess.run([str(args.compiler), '/Qp', '/DPackageSource=' + str(bundle), '/DPackageOutput=' + str(output),
                    '/DPackageVersion=' + version, str(root / 'deploy/wsl/central-server-wsl.iss')], check=True)
    archive = output / (name + '-portable.zip')
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as destination:
        for path in sorted(bundle.rglob('*')):
            if path.is_file():
                destination.write(path, path.relative_to(bundle).as_posix())
    artifacts = {path.name: checksum(path) for path in (output / (name + '.exe'), archive)}
    checksum(bundle / 'linker-wsl-setup.exe')
    (output / 'build.json').write_text(json.dumps(dict(application_version=version, artifacts=artifacts,
                                                     bundle=str(bundle)), indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(output=str(output), bundle=str(bundle), artifacts=artifacts), indent=2))


if __name__ == '__main__':
    main()

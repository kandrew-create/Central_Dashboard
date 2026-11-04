"""Build a fresh VMware desktop VM bundle without touching existing installations."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import urllib.request
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from collector.secrets import write_private_file
from deploy.wsl.build_payload import build as build_payload

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def download(url, checksum, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and digest(target) == checksum:
        return target
    temporary = target.with_suffix(target.suffix+'.download')
    with urllib.request.urlopen(url, timeout=90) as response, temporary.open('wb') as output:
        shutil.copyfileobj(response, output, 1024*1024)
    if digest(temporary) != checksum:
        raise RuntimeError('A VM prerequisite failed its pinned SHA-256 verification.')
    os.replace(temporary, target)
    return target


def docker(arguments, *, payload=None, timeout=900):
    host = 'npipe:////./pipe/dockerDesktopLinuxEngine' if os.name == 'nt' else 'unix:///var/run/docker.sock'
    environment = {key: value for key, value in os.environ.items() if not key.startswith(('DOCKER_', 'COMPOSE_'))}
    result = subprocess.run(['docker', '--host', host, *arguments], input=payload, capture_output=True,
        cwd=ROOT, env=environment, timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        (ROOT/'.tools').mkdir(exist_ok=True)
        write_private_file(ROOT/'.tools/vmware-build-error.log', result.stdout+result.stderr)
        raise RuntimeError('The isolated VM build command failed. Details are retained in the private build log.')
    return result.stdout


def vmx(memory_mb=8192, cpus=4):
    if memory_mb < 4096 or memory_mb > 32768 or not 1 <= cpus <= 16:
        raise ValueError('Choose 4096–32768 MiB RAM and 1–16 virtual CPUs.')
    return '\n'.join((
        '.encoding = "UTF-8"', 'config.version = "8"', 'virtualHW.version = "19"',
        'displayName = "Linker Central Server - Ubuntu Docker"', 'guestOS = "ubuntu-64"',
        'firmware = "efi"', f'memsize = "{memory_mb}"', f'numvcpus = "{cpus}"',
        'pciBridge0.present = "TRUE"',
        *(line for bridge in range(4, 8) for line in (
            f'pciBridge{bridge}.present = "TRUE"',
            f'pciBridge{bridge}.virtualDev = "pcieRootPort"',
            f'pciBridge{bridge}.functions = "8"')),
        'scsi0.present = "TRUE"', 'scsi0.virtualDev = "lsilogic"',
        'scsi0:0.present = "TRUE"', 'scsi0:0.fileName = "central-server.vmdk"',
        'sata0.present = "TRUE"', 'sata0:0.present = "TRUE"',
        'sata0:0.deviceType = "cdrom-image"', 'sata0:0.fileName = "seed.iso"',
        'ethernet0.present = "TRUE"', 'ethernet0.virtualDev = "vmxnet3"',
        'ethernet0.connectionType = "nat"', 'ethernet0.addressType = "generated"',
        'usb.present = "FALSE"', 'sound.present = "FALSE"', 'mks.enable3d = "FALSE"',
        'tools.syncTime = "TRUE"', 'uuid.action = "create"', ''))


def cloud_config(build_id, public_key, password_hash):
    return '#cloud-config\n'+json.dumps(dict(
        hostname='linker-central', manage_etc_hosts=True, timezone='UTC',
        disable_root=True, ssh_pwauth=False,
        users=[dict(name='linker', gecos='Central Server Administrator', groups=['sudo'], shell='/bin/bash',
                    sudo='ALL=(ALL) NOPASSWD:ALL', lock_passwd=False, hashed_passwd=password_hash,
                    ssh_authorized_keys=[public_key])],
        growpart=dict(mode='auto', devices=['/']), resize_rootfs=True,
        write_files=[dict(path='/etc/linker-vm-build.json', permissions='0644',
                         content=json.dumps(dict(build_id=build_id, component='central-server')))],
        runcmd=[['bash', '-c', 'mkdir -p /run/linker-seed; mount -o ro -L cidata /run/linker-seed; bash /run/linker-seed/provision.sh']]
    ), indent=2)+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--memory-mb', type=int, default=8192)
    parser.add_argument('--cpus', type=int, default=4)
    args = parser.parse_args()
    config = json.loads((ROOT/'deploy/vmware/prerequisites.json').read_text())
    text = vmx(args.memory_mb, args.cpus)
    build_id = '0.6.2-'+uuid4().hex[:10]
    output = ROOT/'dist/vmware'/build_id
    output.mkdir(parents=True)
    state = ROOT/'secrets/vmware'/build_id
    state.mkdir(parents=True)
    seed = output/'seed'
    package = seed/'package'
    package.mkdir(parents=True)
    image = download(config['ubuntu']['url'], config['ubuntu']['sha256'], ROOT/'.cache/vmware/ubuntu-24.04-20261017.img')
    print('Verified pinned Ubuntu 24.04 base image.', flush=True)
    tools = config['tools_image']
    docker(['build', '-t', tools, '-f', 'deploy/vmware/Dockerfile', 'deploy/vmware'])
    build_payload(ROOT, package)
    for name in ('linux_setup.py', 'prerequisites.json'):
        shutil.copyfile(ROOT/'deploy/wsl'/name, package/name)
    shutil.copyfile(ROOT/'deploy/vmware/install_guest.py', package/'install_guest.py')
    (seed/'provision.sh').write_bytes((ROOT/'deploy/vmware/provision.sh').read_bytes().replace(b'\r\n', b'\n'))
    prerequisites = json.loads((package/'prerequisites.json').read_text())['uv']
    uv = download(prerequisites['url'], prerequisites['sha256'], ROOT/'.cache/wsl-installer'/('uv-'+prerequisites['version']+'.tar.gz'))
    shutil.copyfile(uv, package/'uv-linux.tar.gz')
    password = secrets.token_urlsafe(18)
    private_key = Ed25519PrivateKey.generate()
    write_private_file(state/'id_ed25519', private_key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()))
    public_key = private_key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
    write_private_file(state/'login.txt', ('VM user: linker\nInitial desktop password: '+password+'\n').encode())
    password_hash = docker(['run', '--rm', '--network', 'none', '-i', tools, 'openssl', 'passwd', '-6', '-stdin'],
                           payload=(password+'\n').encode()).decode().strip()
    (seed/'user-data').write_text(cloud_config(build_id, public_key, password_hash), encoding='utf-8')
    (seed/'meta-data').write_text(json.dumps({'instance-id':'linker-'+build_id,'local-hostname':'linker-central'}), encoding='utf-8')
    source = output/'central-server.qcow2'
    shutil.copyfile(image, source)
    mount = ['--mount','type=bind,source='+str(output)+',target=/work']
    docker(['run','--rm',*mount,tools,'qemu-img','resize','/work/central-server.qcow2',str(config['disk_gb'])+'G'])
    docker(['run','--rm',*mount,tools,'qemu-img','convert','-f','qcow2','-O','vmdk','-o',
            'subformat=monolithicSparse,adapter_type=lsilogic','/work/central-server.qcow2','/work/central-server.vmdk'])
    docker(['run','--rm',*mount,tools,'xorriso','-as','mkisofs','-V','cidata','-J','-r','-o','/work/seed.iso','/work/seed'])
    (output/'Central Server.vmx').write_text(text, encoding='utf-8')
    artifacts = {name:digest(output/name) for name in ('central-server.vmdk','seed.iso','Central Server.vmx')}
    for name, checksum in artifacts.items():
        (output/(name+'.sha256')).write_text(checksum+'  '+name+'\n')
    manifest = dict(build_id=build_id, ubuntu=config['ubuntu'], memory_mb=args.memory_mb, cpus=args.cpus,
        disk_gb=config['disk_gb'], desktop='Xfce', docker='Docker Engine inside guest',
        project='linker-scada-vmware', first_boot_internet_required=True,
        plaintext_credentials_bundled=False, login_password_hash_in_seed=True,
        collector_service_included=False, artifacts=artifacts)
    manifest['vmware_boot_verified'] = False
    (output/'build.json').write_text(json.dumps(manifest, indent=2)+'\n')
    shutil.copyfile(ROOT/'docs/vmware-linux.md', output/'Read me.md')
    print(json.dumps(dict(output=str(output), private_login_file=str(state/'login.txt'),
                         private_ssh_key=str(state/'id_ed25519'), vmware_boot_verified=False), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

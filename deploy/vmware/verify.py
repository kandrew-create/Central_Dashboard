"""Validate a fresh extracted VM bundle using an isolated software-emulated guest."""
import argparse
import json
from pathlib import Path
import time
from uuid import uuid4

from deploy.vmware.build import ROOT, digest, docker


def inputs(bundle, key):
    bundle, key = Path(bundle).resolve(strict=True), Path(key).resolve(strict=True)
    if key.is_relative_to(bundle):
        raise ValueError('Keep the private SSH key outside the VM bundle.')
    manifest = json.loads((bundle/'build.json').read_text())
    if set(manifest['artifacts']) != {'central-server.vmdk','seed.iso','Central Server.vmx'}:
        raise ValueError('Unexpected VM artifact manifest.')
    for name, expected in manifest['artifacts'].items():
        target = bundle/name
        if target.is_symlink() or digest(target) != expected:
            raise ValueError('VM artifact integrity check failed.')
    if (bundle/'validation.qcow2').exists():
        raise ValueError('Use a fresh extracted bundle for each validation; existing test state is preserved.')
    return bundle, key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--ssh-key', type=Path, required=True)
    args = parser.parse_args()
    bundle, key = inputs(args.bundle, args.ssh_key)
    tools = json.loads((ROOT/'deploy/vmware/prerequisites.json').read_text())['tools_image']
    mount = ['--mount','type=bind,source='+str(bundle)+',target=/work']
    if not (bundle/'central-server.qcow2').exists():
        docker(['run','--rm',*mount,tools,'qemu-img','convert','-f','vmdk','-O','qcow2',
                '/work/central-server.vmdk','/work/central-server.qcow2'])
    docker(['run','--rm',*mount,tools,'qemu-img','compare','-f','vmdk','-F','qcow2',
            '/work/central-server.vmdk','/work/central-server.qcow2'])
    name = 'linker-vmware-check-'+uuid4().hex[:10]
    docker(['run','-d','--name',name,'--memory','6g','--cpus','4',*mount,
            '--mount','type=bind,source='+str(key)+',target=/private/id_ed25519,readonly',
            '--mount','type=bind,source='+str(ROOT/'deploy/vmware/validate_guest.py')+',target=/runner.py,readonly',
            tools,'python3','-u','/runner.py'])
    seen = set()
    try:
        deadline = time.monotonic()+7500
        while time.monotonic() < deadline:
            state = json.loads(docker(['inspect','--format','{{json .State}}',name]))
            logs = docker(['logs',name]).decode()
            for line in logs.splitlines():
                if line not in seen and line.startswith(('Booting an isolated','Guest SSH','Guest provisioning phase:')):
                    print(line,flush=True)
                    seen.add(line)
            if not state['Running']:
                if state['ExitCode'] or not (bundle/'validation.json').is_file():
                    raise RuntimeError('VM validation failed; preserve the private guest diagnostics for review.')
                print((bundle/'validation.json').read_text())
                return 0
            time.sleep(5)
        raise RuntimeError('VM validation exceeded its bounded timeout.')
    finally:
        # QEMU's SIGTERM handling flushes a disposable overlay. Never stop the
        # host Docker engine, another VM or an operational application project.
        docker(['stop','--time','120',name],timeout=150)
        docker(['rm',name])


if __name__ == '__main__':
    raise SystemExit(main())

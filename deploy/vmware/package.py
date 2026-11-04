"""Package verified VMware boot artifacts; exclude local test and credential state."""
import argparse
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from deploy.vmware.build import digest


ARTIFACTS = ('Central Server.vmx', 'central-server.vmdk', 'seed.iso')
FILES = (*ARTIFACTS, *(name+'.sha256' for name in ARTIFACTS), 'build.json', 'Read me.md')


def package(bundle):
    bundle = Path(bundle).resolve(strict=True)
    manifest = json.loads((bundle/'build.json').read_text())
    if set(manifest['artifacts']) != set(ARTIFACTS):
        raise ValueError('Unexpected VM artifact manifest.')
    for name in FILES:
        target = bundle/name
        if not target.is_file() or target.is_symlink():
            raise ValueError('Missing or unsafe VM bundle input.')
        if name in ARTIFACTS:
            checksum = digest(target)
            if checksum != manifest['artifacts'][name]:
                raise ValueError('VM artifact integrity check failed.')
            if (bundle/(name+'.sha256')).read_text().strip() != checksum+'  '+name:
                raise ValueError('VM checksum sidecar does not match its artifact.')
    archive = bundle.parent/('Linker-Central-Server-VMware-'+bundle.name+'.zip')
    # Never silently replace a prior handoff with potentially different contents.
    with ZipFile(archive, 'x', compression=ZIP_DEFLATED, compresslevel=6) as output:
        for name in FILES:
            output.write(bundle/name, arcname=name)
    with ZipFile(archive) as check:
        if set(check.namelist()) != set(FILES) or check.testzip() is not None:
            raise RuntimeError('VM archive verification failed.')
    checksum = digest(archive)
    archive.with_suffix('.zip.sha256').write_text(checksum+'  '+archive.name+'\n')
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, type=Path)
    args = parser.parse_args()
    print(package(args.bundle))


if __name__ == '__main__':
    main()

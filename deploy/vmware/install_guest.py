"""Native Linux guest installation through the existing state-preserving installer."""
import argparse
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

sys.path.insert(0, '/opt/linker-vm')
import linux_setup


def vm_health_settings(content):
    """Add VM health grace to a generated API section; retain custom settings."""
    match = re.search(r'(?ms)^  api:\n(?P<body>.*?)(?=^  [\w-]+:|\Z)', content)
    if not match:
        raise linux_setup.SetupError('Cannot recognize the VM Compose profile; existing settings were retained.')
    if re.search(r'^    healthcheck:', match['body'], re.MULTILINE):
        return content
    health = '    healthcheck: {timeout: 30s, start_period: 120s}\n'
    return content[:match.end()]+health+content[match.end():]


class GuestInstaller(linux_setup.Installer):
    def compose(self, *arguments, **kwargs):
        if arguments and arguments[0] == 'up':
            # Large optional AI/runtime images must not consume the bounded
            # service readiness interval on a fresh online installation.
            super().compose('pull', '--ignore-buildable', '--policy', 'missing', timeout=1800,
                message='Runtime image download failed. Check network access and retry; saved data is retained.')
            arguments = list(arguments)
            if '--wait-timeout' in arguments:
                arguments[arguments.index('--wait-timeout')+1] = '600'
            kwargs['timeout'] = max(kwargs.get('timeout', 660), 660)
        return super().compose(*arguments, **kwargs)

    def install_code(self, files, manifest):
        super().install_code(files, manifest)
        for name in ('deploy/docker-compose.wsl.yml', 'deploy/wsl/docker-compose.wsl.yml.template',
                     'deploy/wsl/docker-compose.network.yml.template'):
            path = self.workspace/name
            content = path.read_text()
            updated = vm_health_settings(content)
            if updated != content:
                linux_setup.atomic_write(path, updated.encode())
        if not self.existing:
            path = self.workspace / '.env'
            linux_setup.atomic_write(path, path.read_bytes() + b'LINKER_AI_PROVIDER=container\n')


def main():
    package = Path('/opt/linker-vm')
    args = SimpleNamespace(payload=package/'application.tar.gz', manifest=package/'application-manifest.json',
        uv_archive=package/'uv-linux.tar.gz', prerequisites=package/'prerequisites.json',
        folder='central-server', project='linker-scada-vmware', http_port=80, https_port=443)
    result = GuestInstaller(args).install()
    workspace = Path.home()/'central-server'
    applications = Path.home()/'.local/share/applications'
    applications.mkdir(parents=True, exist_ok=True)
    entry = ('[Desktop Entry]\nType=Application\nName=Central Server\n'
             'Exec=/bin/bash '+str(workspace/'deploy/wsl/launch-manager.sh')+' --project linker-scada-vmware\n'
             'Icon='+str(workspace/'deploy/wsl/central-server.png')+'\n'
             'Terminal=false\nCategories=Utility;\nStartupWMClass=linker-central-server\n')
    for target in (applications/'linker-central-server.desktop', Path.home()/'Desktop/Central Server.desktop',
                   Path.home()/'.config/autostart/linker-central-server.desktop'):
        target.parent.mkdir(parents=True, exist_ok=True)
        linux_setup.atomic_write(target, entry.encode(), 0o755)
    print(json.dumps(dict(guest_install_ready=True, workspace=str(workspace), project=args.project)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

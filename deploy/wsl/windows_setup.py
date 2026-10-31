"""Per-user Windows setup wizard/launcher for the WSL package. No Windows server control."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.request


class SetupError(Exception):
    pass


class ActionRequired(SetupError):
    pass


def decode(value):
    return value.decode('utf-16-le' if b'\0' in value[:100] else 'utf-8', errors='replace').replace('\0', '')


def validate_configuration(value):
    for key in ('distribution', 'folder', 'project'):
        pattern = r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}' if key == 'distribution' else r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}'
        if not re.fullmatch(pattern, value[key]):
            raise SetupError('Use simple distribution, Linux folder and Docker project names without spaces or path separators.')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}', value['project']):
        raise SetupError('The Docker project name must be lowercase.')
    if (not all(type(value[key]) is int and 1 <= value[key] <= 65535 for key in ('http_port', 'https_port'))
            or value['http_port'] == value['https_port']):
        raise SetupError('Choose different valid HTTP and HTTPS ports.')
    return value


def registered_distributions():
    import winreg
    result = {}
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Lxss')
    except OSError:
        return result
    with root:
        for index in range(winreg.QueryInfoKey(root)[0]):
            with winreg.OpenKey(root, winreg.EnumKey(root, index)) as child:
                name = winreg.QueryValueEx(child, 'DistributionName')[0]
                result[name] = dict(version=winreg.QueryValueEx(child, 'Version')[0],
                                    uid=winreg.QueryValueEx(child, 'DefaultUid')[0])
    return result


def safe_download(url, checksum, target, progress=lambda message: None):
    target = Path(target)
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == checksum:
        return target
    partial = target.with_suffix(target.suffix + '.download')
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(url, timeout=60) as response, partial.open('wb') as stream:
            size = int(response.headers.get('Content-Length', '0'))
            downloaded, notified = 0, -1
            while block := response.read(1024 * 1024):
                stream.write(block)
                digest.update(block)
                downloaded += len(block)
                percent = int(downloaded * 100 / size) if size else 0
                if percent // 10 != notified:
                    progress('Downloading Docker Desktop: ' + str(percent) + '%')
                    notified = percent // 10
        if digest.hexdigest() != checksum:
            raise SetupError('A prerequisite checksum did not match. The download was not executed.')
        os.replace(partial, target)
    except SetupError:
        raise
    except Exception:
        raise SetupError('The prerequisite download failed. Check internet access and retry setup.') from None
    finally:
        partial.unlink(missing_ok=True)
    return target


class Setup:
    def __init__(self, bundle, state, configuration, notify=lambda step, message: None):
        self.bundle = Path(bundle).resolve()
        self.payload = self.bundle / 'payload'
        self.state = Path(state).resolve()
        self.configuration = validate_configuration(configuration)
        self.notify = notify
        self.wsl = str(Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32/wsl.exe')

    def run(self, command, *, payload=None, timeout=180, visible=False, check=True, environment=None):
        try:
            result = subprocess.run(command, input=payload, capture_output=True, timeout=timeout,
                                    env=environment, creationflags=0 if visible else getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired):
            raise SetupError('A setup command could not finish. Check the current step and retry; existing state is retained.') from None
        if check and result.returncode:
            raise SetupError('A setup command failed. Check the current step and retry; existing state is retained.')
        return result

    def private_state(self):
        self.state.mkdir(parents=True, exist_ok=True)
        who = self.run(['whoami.exe', '/user', '/fo', 'csv', '/nh']).stdout.decode(errors='replace')
        match = re.search(r'S-1-5-[0-9-]+', who)
        if not match:
            raise SetupError('Cannot identify the Windows account for private setup state.')
        self.run(['icacls.exe', str(self.state), '/inheritance:r', '/grant:r', '*' + match.group(0) + ':(OI)(CI)F',
                  '*S-1-5-18:(OI)(CI)F'])

    def verify_package(self):
        try:
            manifest = json.loads((self.bundle / 'package.json').read_text(encoding='utf-8'))
            required = {'payload/application.tar.gz', 'payload/application-manifest.json', 'payload/linux_setup.py',
                        'payload/prerequisites.json', 'payload/uv-linux.tar.gz', 'linker-wsl-setup.exe'}
            if manifest.get('format') != 1 or not required.issubset(manifest['files']):
                raise ValueError()
            for name, expected in manifest['files'].items():
                relative = Path(name)
                if (relative.is_absolute() or relative.drive or '..' in relative.parts or ':' in name
                        or hashlib.sha256((self.bundle / relative).read_bytes()).hexdigest() != expected):
                    raise ValueError()
            self.prerequisites = json.loads((self.payload / 'prerequisites.json').read_text(encoding='utf-8'))
            return manifest
        except Exception:
            raise SetupError('The installer package is incomplete or failed its checksum check. Download a fresh copy.') from None

    def saved_configuration(self):
        try:
            return validate_configuration(json.loads((self.state / 'configuration.json').read_text(encoding='utf-8')))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def save_configuration(self):
        self.private_state()
        temporary = self.state / 'configuration.new'
        temporary.write_text(json.dumps(self.configuration, indent=2) + '\n', encoding='utf-8')
        os.replace(temporary, self.state / 'configuration.json')

    def ensure_wsl(self):
        self.notify('wsl', 'Checking WSL 2 and Ubuntu…')
        architecture = os.environ.get('PROCESSOR_ARCHITEW6432', platform.machine()).lower()
        if architecture not in ('amd64', 'x86_64') or sys.getwindowsversion().build < 22631:
            raise ActionRequired('This package requires Windows 11 23H2 or newer on an x64 PC.')
        distros = registered_distributions()
        selected = distros.get(self.configuration['distribution'])
        if not selected:
            probe = self.run([self.wsl, '--system', '--exec', 'true'], check=False, timeout=30)
            if probe.returncode:
                command = "$ErrorActionPreference='Stop'; $p=Start-Process -FilePath $env:LINKER_WSL_EXE -Verb RunAs -WindowStyle Hidden -Wait -PassThru -ArgumentList '--install','--no-distribution','--no-launch'; if($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010){exit 1}"
                environment = dict(os.environ, LINKER_WSL_EXE=self.wsl)
                self.notify('wsl', 'Approve the Windows prompt to enable WSL. Setup will never restart Windows automatically.')
                self.run(['powershell.exe', '-NoProfile', '-Command', command], environment=environment, timeout=900)
                raise ActionRequired('Save your work and restart Windows, then open Finish WSL Docker Setup again. Windows was not restarted automatically.')
            self.notify('wsl', 'Downloading Ubuntu for your Windows account…')
            self.run([self.wsl, '--install', '--web-download', '--distribution', self.configuration['distribution'], '--no-launch'], timeout=1200)
            selected = registered_distributions().get(self.configuration['distribution'])
        if not selected:
            raise ActionRequired('Ubuntu registration is pending. Restart Windows if requested, then retry setup.')
        if selected['version'] != 2:
            raise ActionRequired('The selected distribution is not WSL 2. Convert it explicitly or choose a WSL 2 Ubuntu distribution.')
        if selected['uid'] == 0:
            subprocess.Popen([self.wsl, '--distribution', self.configuration['distribution']],
                             creationflags=getattr(subprocess, 'CREATE_NEW_CONSOLE', 0))
            raise ActionRequired('Finish creating your Linux username and password in the Ubuntu window, then click Resume setup. Keep the password private.')

    def docker_desktop(self):
        for directory in (Path(os.environ['LOCALAPPDATA']) / 'Programs/DockerDesktop',
                          Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Docker/Docker'):
            if (directory / 'Docker Desktop.exe').is_file():
                return directory / 'Docker Desktop.exe'
        return None

    def ensure_docker(self):
        self.notify('docker', 'Checking Docker Desktop and Ubuntu integration…')
        desktop = self.docker_desktop()
        if not desktop:
            info = self.prerequisites['docker_desktop']
            installer = safe_download(info['url'], info['sha256'], self.state / 'Docker Desktop Installer.exe',
                                      lambda message: self.notify('docker', message))
            environment = dict(os.environ, LINKER_DOCKER_INSTALLER=str(installer))
            signature = "$s=Get-AuthenticodeSignature -LiteralPath $env:LINKER_DOCKER_INSTALLER; if($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'O=Docker Inc'){exit 1}"
            self.run(['powershell.exe', '-NoProfile', '-Command', signature], environment=environment)
            self.notify('docker', 'Complete the official Docker Desktop installation window. Choose the WSL 2 backend.')
            self.run([str(installer), 'install', '--user', '--backend=wsl-2'], visible=True, timeout=1800)
            desktop = self.docker_desktop()
        if not desktop:
            raise ActionRequired('Docker Desktop installation is not complete. Finish its installer, then resume setup.')
        probe = self.run([self.wsl, '--distribution', self.configuration['distribution'], '--exec', 'docker',
                          '--host', 'unix:///var/run/docker.sock', 'info', '--format', '{{.OSType}}'], check=False, timeout=30)
        if probe.returncode or decode(probe.stdout).strip() != 'linux':
            subprocess.Popen([str(desktop)], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            raise ActionRequired('Open Docker Desktop and finish its first-run prompts. Enable Settings → Resources → WSL Integration for '
                                 + self.configuration['distribution'] + ', wait for the Linux engine to run, then Resume setup.')
        self.run([self.wsl, '--distribution', self.configuration['distribution'], '--exec', 'docker',
                  '--host', 'unix:///var/run/docker.sock', 'compose', 'version'])

    def linux_path(self, path):
        result = self.run([self.wsl, '--distribution', self.configuration['distribution'], '--exec', 'wslpath', '-a', '-u', str(path)])
        return decode(result.stdout).strip()

    def install_application(self):
        self.notify('linux', 'Installing the Linux display dependencies…')
        distro = self.configuration['distribution']
        self.run([self.wsl, '--distribution', distro, '--user', 'root', '--exec', 'apt-get', 'update', '-qq'], timeout=900)
        self.run([self.wsl, '--distribution', distro, '--user', 'root', '--exec', 'env', 'DEBIAN_FRONTEND=noninteractive',
                  'apt-get', 'install', '-y', '-qq', 'ca-certificates', 'python3', 'libegl1', 'libopengl0', 'libxcb-cursor0',
                  'libxcb-icccm4', 'libxcb-image0', 'libxcb-keysyms1', 'libxcb-render-util0', 'libxcb-xinerama0', 'libxkbcommon-x11-0'], timeout=900)
        command = [self.wsl, '--distribution', distro, '--exec', 'python3', '-',
                   '--payload', self.linux_path(self.payload / 'application.tar.gz'),
                   '--manifest', self.linux_path(self.payload / 'application-manifest.json'),
                   '--uv-archive', self.linux_path(self.payload / 'uv-linux.tar.gz'),
                   '--prerequisites', self.linux_path(self.payload / 'prerequisites.json'),
                   '--folder', self.configuration['folder'], '--project', self.configuration['project'],
                   '--http-port', str(self.configuration['http_port']), '--https-port', str(self.configuration['https_port'])]
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            process.stdin.write((self.payload / 'linux_setup.py').read_bytes())
            process.stdin.close()
            result = None
            for line in process.stdout:
                try:
                    event = json.loads(line)
                    if 'step' in event:
                        self.notify(event['step'], event['message'])
                        if event['step'] == 'error':
                            result = dict(error=event['message'])
                    elif 'result' in event:
                        result = event['result']
                except (ValueError, KeyError, TypeError):
                    continue
            code = process.wait()
        except OSError:
            raise SetupError('Cannot start Linux application setup. Check Ubuntu and retry.') from None
        if code or result is None or 'error' in result:
            raise SetupError(result.get('error', 'Linux setup did not complete. Existing local state is retained.') if result else 'Linux setup did not complete. Existing local state is retained.')
        self.configuration.update(workspace=result['workspace'], http_port=result['http_port'], https_port=result['https_port'], ready=True)
        self.save_configuration()
        return result

    def install(self, prerequisites=True, shortcuts=True):
        self.private_state()
        self.verify_package()
        self.save_configuration()
        if prerequisites:
            self.ensure_wsl()
            self.ensure_docker()
        result = self.install_application()
        if shortcuts:
            self.install_shortcut()
        return result

    def install_shortcut(self):
        if not getattr(sys, 'frozen', False):
            return
        script = "$s=New-Object -ComObject WScript.Shell; $p=Join-Path ([Environment]::GetFolderPath('Desktop')) 'Central Server - WSL Docker.lnk'; $l=$s.CreateShortcut($p); $l.TargetPath=$env:LINKER_SETUP_EXE; $l.Arguments='--launch'; $l.Description='Linker Central Server in WSL and Docker'; $l.Save()"
        self.run(['powershell.exe', '-NoProfile', '-Command', script], environment=dict(os.environ, LINKER_SETUP_EXE=sys.executable))

    def launch(self, wait=False):
        configuration = self.saved_configuration()
        if not configuration or not configuration.get('ready'):
            raise ActionRequired('Finish WSL/Docker setup before opening its management window.')
        command = [self.wsl, '--distribution', configuration['distribution'], '--exec', 'bash',
                   configuration['workspace'] + '/deploy/wsl/launch-manager.sh', '--project', configuration['project']]
        process = subprocess.Popen(command, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if wait and process.wait():
            raise SetupError('The Linux manager could not open. Start Docker Desktop, check Ubuntu and retry setup if needed.')


def default_configuration():
    distributions = registered_distributions() if os.name == 'nt' else {}
    selected = next((name for name, value in distributions.items() if name.lower().startswith('ubuntu') and value['version'] == 2), 'Ubuntu-24.04')
    return dict(distribution=selected, folder='central-server', project='linker-scada-wsl', http_port=80, https_port=443)


def wizard(setup, smoke=False):
    import tkinter as tk
    from tkinter import messagebox, ttk
    root = tk.Tk()
    root.title('Linker Central Server — WSL / Docker Setup')
    root.geometry('850x650')
    root.minsize(790, 620)
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('TLabel', font=('Segoe UI', 10))
    style.configure('TButton', padding=(14, 8), font=('Segoe UI', 10))
    header = tk.Frame(root, bg='#13233d', padx=26, pady=22)
    header.pack(fill='x')
    tk.Label(header, text='LINKER  /  WSL + DOCKER', bg='#13233d', fg='#aac7fa', font=('Segoe UI', 10, 'bold')).pack(anchor='w')
    tk.Label(header, text='Set up your Central Server', bg='#13233d', fg='white', font=('Segoe UI', 21, 'bold')).pack(anchor='w', pady=5)
    tk.Label(header, text='A separate Linux server and desktop GUI. Existing Windows installations are preserved.',
             bg='#13233d', fg='#d2dced', font=('Segoe UI', 10)).pack(anchor='w')
    body = ttk.Frame(root, padding=24)
    body.pack(fill='both', expand=True)
    body.columnconfigure(1, weight=1)
    values = setup.saved_configuration() or setup.configuration
    entries = {}
    for index, (key, title) in enumerate((('distribution', 'Ubuntu distribution'), ('folder', 'Folder below your Linux home'),
                                         ('project', 'Docker project'), ('https_port', 'Local HTTPS port'), ('http_port', 'Local HTTP port'))):
        ttk.Label(body, text=title).grid(row=index, column=0, sticky='w', padx=(0, 18), pady=6)
        variable = tk.StringVar(root, str(values[key]))
        entry = ttk.Entry(body, textvariable=variable)
        entry.grid(row=index, column=1, sticky='ew', pady=6)
        entries[key] = variable
    ttk.Label(body, text='Internet is required for first setup. Windows may request elevation or a restart.\n'
              'Ubuntu account passwords and Docker first-run prompts stay in their own windows.', wraplength=740).grid(row=5, column=0, columnspan=2, sticky='w', pady=(15, 10))
    state = tk.StringVar(root, 'Ready to check prerequisites and install. Use the same settings to resume a previous setup.')
    ttk.Label(body, textvariable=state, wraplength=740).grid(row=6, column=0, columnspan=2, sticky='w', pady=10)
    progress = ttk.Progressbar(body, mode='indeterminate')
    progress.grid(row=7, column=0, columnspan=2, sticky='ew', pady=10)
    actions = ttk.Frame(body)
    actions.grid(row=8, column=0, columnspan=2, sticky='ew', pady=(10, 0))
    pending = queue.Queue()
    busy = [False]
    def notice(step, message):
        pending.put(('progress', message))
    setup.notify = notice
    def begin():
        if busy[0]:
            return
        try:
            setup.configuration = validate_configuration({key: int(value.get()) if key.endswith('_port') else value.get().strip()
                                                           for key, value in entries.items()})
        except (SetupError, ValueError):
            messagebox.showerror('Setup options', 'Enter valid names and different HTTP/HTTPS ports.', parent=root)
            return
        busy[0] = True
        start.configure(state='disabled')
        open_gui.configure(state='disabled')
        progress.start(12)
        def work():
            try:
                setup.install()
            except ActionRequired as error:
                pending.put(('action', str(error)))
            except SetupError as error:
                pending.put(('error', str(error)))
            except Exception:
                pending.put(('error', 'Setup could not finish. Existing data is retained. Check prerequisites and retry.'))
            else:
                pending.put(('ready', 'Central Server is ready. Open the GUI to register sources and export collector setups.'))
        threading.Thread(target=work, daemon=False, name='wsl-server-setup').start()
    def opened():
        try:
            setup.launch()
        except SetupError as error:
            messagebox.showinfo('Complete setup', str(error), parent=root)
    start = ttk.Button(actions, text='Start / resume setup', command=begin)
    start.pack(side='left')
    open_gui = ttk.Button(actions, text='Open server GUI', command=opened)
    open_gui.pack(side='left', padx=10)
    if not values.get('ready'):
        open_gui.configure(state='disabled')
    def close():
        if busy[0]:
            state.set('Please wait for the current setup step to finish before closing.')
        else:
            root.destroy()
    ttk.Button(actions, text='Close', command=close).pack(side='right')
    root.protocol('WM_DELETE_WINDOW', close)
    def poll():
        try:
            while True:
                kind, message = pending.get_nowait()
                state.set(message)
                if kind != 'progress':
                    busy[0] = False
                    progress.stop()
                    start.configure(state='normal')
                    if kind == 'ready':
                        open_gui.configure(state='normal')
        except queue.Empty:
            pass
        root.after(100, poll)
    poll()
    if smoke:
        root.after(1500, root.destroy)
    root.mainloop()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Linker Central Server WSL / Docker Setup')
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--state-dir', type=Path)
    parser.add_argument('--verify-package', action='store_true')
    parser.add_argument('--smoke-gui', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--install-application', action='store_true')
    parser.add_argument('--launch', action='store_true')
    parser.add_argument('--no-shortcuts', action='store_true')
    parser.add_argument('--report', type=Path)
    defaults = default_configuration()
    for key in ('distribution', 'folder', 'project', 'http_port', 'https_port'):
        parser.add_argument('--' + key.replace('_', '-'), type=int if key.endswith('_port') else str, default=defaults[key])
    args = parser.parse_args(argv)
    bundle = args.bundle or (Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent)
    state = args.state_dir or Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Linker/WslDockerSetup'
    def report(step, message):
        if sys.stdout:
            print(json.dumps(dict(step=step, message=message)), flush=True)
    try:
        setup = Setup(bundle, state, {key: getattr(args, key) for key in defaults}, notify=report)
        if args.verify_package:
            result = dict(verified=True, application_version=setup.verify_package()['application_version'])
        elif args.install_application:
            result = setup.install(prerequisites=False, shortcuts=not args.no_shortcuts)
        elif args.launch:
            setup.launch(wait=True)
            return 0
        else:
            wizard(setup, smoke=args.smoke_gui)
            return 0
    except SetupError as error:
        result = dict(error=str(error))
    except Exception:
        result = dict(error='Setup failed. Existing data was retained. Check prerequisites and retry.')
    if 'error' in result and args.launch and not sys.stdout:
        from tkinter import messagebox
        messagebox.showerror('Linker WSL / Docker', result['error'])
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    if sys.stdout:
        print(json.dumps(result))
    return 1 if 'error' in result else 0


if __name__ == '__main__':
    raise SystemExit(main())

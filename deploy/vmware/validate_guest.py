"""Run inside the tools container: boot a disposable overlay and verify Linux/Docker/Qt."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time


def interrupted(signum, frame):
    raise KeyboardInterrupt('Disposable validation stop requested')


signal.signal(signal.SIGTERM, interrupted)


def run(args, timeout=60, check=True):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        if not check:
            return subprocess.CompletedProcess(args, 124, '', 'Readiness probe timed out.')
        raise
    if check and result.returncode:
        Path('/work/validation-command-error.log').write_text(result.stdout+result.stderr)
        raise RuntimeError('Guest validation command failed; diagnostics retained privately.')
    return result


def ssh(command, timeout=90, check=True):
    return run(['ssh', '-i', '/tmp/guest-key', '-p', '2222', '-o', 'StrictHostKeyChecking=accept-new',
        '-o', 'ControlMaster=auto', '-o', 'ControlPersist=120', '-o', 'ControlPath=/tmp/linker-ssh-%C',
        '-o', 'UserKnownHostsFile=/tmp/guest-known-hosts', '-o', 'ConnectTimeout=5',
        '-o', 'BatchMode=yes', 'linker@127.0.0.1', command], timeout=timeout, check=check)


shutil.copyfile('/private/id_ed25519', '/tmp/guest-key')
os.chmod('/tmp/guest-key', 0o600)
overlay = Path('/work/validation.qcow2')
if overlay.exists():
    raise RuntimeError('Use a new validation overlay; existing test data was preserved.')
run(['qemu-img','create','-f','qcow2','-F','qcow2','-b','/work/central-server.qcow2',str(overlay)])
firmware = Path('/usr/share/OVMF/OVMF_CODE_4M.fd')
variables = Path('/usr/share/OVMF/OVMF_VARS_4M.fd')
shutil.copyfile(variables, '/work/validation-vars.fd')
with Path('/work/validation-qemu.log').open('w') as log:
    vm = subprocess.Popen(['qemu-system-x86_64','-machine','q35','-accel','tcg,thread=multi','-cpu','max',
        '-smp','4','-m','4096','-drive','if=pflash,format=raw,readonly=on,file='+str(firmware),
        '-drive','if=pflash,format=raw,file=/work/validation-vars.fd',
        '-drive','file='+str(overlay)+',format=qcow2,if=virtio','-cdrom','/work/seed.iso',
        '-netdev','user,id=net0,hostfwd=tcp:127.0.0.1:2222-:22','-device','virtio-net-pci,netdev=net0',
        '-display','none','-serial','file:/work/validation-serial.log'], stdout=log, stderr=log)
try:
    print('Booting an isolated Linux test guest; no host ports are published.', flush=True)
    # Full desktop/package installation is slow under software CPU emulation.
    deadline = time.monotonic()+7200
    connected = False
    previous = None
    while time.monotonic() < deadline:
        if vm.poll() is not None:
            raise RuntimeError('The isolated VM exited before readiness.')
        if not connected:
            connected = ssh('true', timeout=60, check=False).returncode == 0
            if connected:
                print('Guest SSH is ready; waiting for desktop and application provisioning.', flush=True)
        if connected:
            ready = ssh('sudo -n test -f /var/lib/linker-vm/ready', check=False).returncode == 0
            if ready:
                break
            phase = ssh('sudo -n cat /var/lib/linker-vm/phase 2>/dev/null || true', check=False).stdout.strip()
            if phase and phase != previous:
                previous = phase
                print('Guest provisioning phase: '+phase, flush=True)
            status = ssh('sudo -n cloud-init status --format json 2>/dev/null || true', check=False).stdout
            if status.startswith('{') and json.loads(status).get('status') == 'error':
                Path('/work/validation-provision-error.log').write_text(
                    ssh('sudo -n cat /var/log/linker-vm-provision.log', check=False).stdout)
                raise RuntimeError('Guest first-boot setup failed; private diagnostics were retained.')
        time.sleep(20)
    else:
        raise RuntimeError('Guest provisioning exceeded the isolated validation timeout.')
    probe = r'''
import json,os,subprocess,sys,time
from pathlib import Path
os.chdir('/home/linker/central-server')
sys.path.insert(0,str(Path.cwd()))
from server.management.docker import DockerManagerService
from server.management.qt_docker_gui import DockerManagerWindow
from PySide6.QtWidgets import QApplication
service=DockerManagerService(Path.cwd(),'linker-scada-vmware')
status=service.status()
assert all(status[k] for k in ('api_ready','database_ready','worker_running'))
assert status['sources']==0
assert service.alarm_analysis(days=30)['summary']['occurrences']==0
configuration=service.machine_interpretations(include_records=False)['configuration']
assert configuration['enabled'] is False
app=QApplication([])
window=DockerManagerWindow(service,auto_refresh=False)
window.show()
window.refresh()
deadline=time.monotonic()+300
while window.busy and time.monotonic()<deadline:
    app.processEvents();time.sleep(.05)
assert not window.busy
assert window.runtime_caption=='Linux / Docker'
assert window.status['database_ready']
window.navigate(5)
deadline=time.monotonic()+300
while window.busy and time.monotonic()<deadline:
    app.processEvents();time.sleep(.05)
assert not window.busy
window.grab().save('/home/linker/vm-validation-manager.png')
window.close()
subprocess.run(['systemctl','is-active','--quiet','lightdm'],check=True)
print(json.dumps(dict(ubuntu=Path('/etc/os-release').read_text().split('VERSION_ID=')[1].splitlines()[0],
    docker=subprocess.check_output(['docker','version','--format','{{.Server.Version}}'],text=True).strip(),
    central_server_ready=True,empty_isolated_database=True,analysis_readable=True,ai_disabled=True,
    native_linux_qt_window=True,desktop_display_manager=True)))
'''
    encoded = __import__('base64').b64encode(probe.encode()).decode()
    command = ("cd /home/linker/central-server && QT_QPA_PLATFORM=offscreen .venv-gui/bin/python -c "
        +__import__('shlex').quote("import base64;exec(base64.b64decode('"+encoded+"'))"))
    report = json.loads(ssh(command, timeout=900).stdout.strip().splitlines()[-1])
    run(['scp','-i','/tmp/guest-key','-P','2222','-o','UserKnownHostsFile=/tmp/guest-known-hosts',
         'linker@127.0.0.1:/home/linker/vm-validation-manager.png','/work/validation-manager.png'])
    Path('/work/validation.json').write_text(json.dumps(report,indent=2)+'\n')
    ssh('sudo -n shutdown -h now', timeout=20, check=False)
    vm.wait(timeout=90)
    print(json.dumps(report), flush=True)
finally:
    if vm.poll() is None:
        ssh('sudo -n shutdown -h now', timeout=20, check=False)
        try:
            vm.wait(timeout=60)
        except subprocess.TimeoutExpired:
            vm.terminate()
            vm.wait(timeout=30)

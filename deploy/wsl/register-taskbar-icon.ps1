param([string]$Distribution = 'Ubuntu', [string]$Workspace = '/home/station7/central-server', [string]$Project = 'linker-scada-wsl')
$ErrorActionPreference = 'Stop'
# Read only public artwork as the normal WSL user. The root step below writes
# only two fixed shell-metadata paths; it does not execute application code.
$readIcon = 'import base64,json,pathlib,sys; p=pathlib.Path(sys.argv[1]); print(json.dumps(dict(png=base64.b64encode((p/"deploy/wsl/central-server.png").read_bytes()).decode(),workspace=str(p),project=sys.argv[2])))'
$readerEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($readIcon))
$readerBootstrap = "import base64;exec(base64.b64decode('" + $readerEncoded + "'))"
$payload = & wsl.exe -d $Distribution --exec python3 -c $readerBootstrap $Workspace $Project
if ($LASTEXITCODE -ne 0) { throw 'Cannot read the selected server artwork.' }
$register = @'
import base64,json,os,re,sys,tempfile
from pathlib import Path
v=json.load(sys.stdin)
assert re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}',v['project'])
workspace=Path(v['workspace'])
assert workspace.is_absolute() and not any(c in str(workspace) for c in ('\n','\r','\x00'))
png=base64.b64decode(v['png'],validate=True)
assert png.startswith(b'\x89PNG\r\n\x1a\n') and len(png)<=2097152
def quote(s):
    return '"'+str(s).replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$').replace('%','%%')+'"'
def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    assert not path.is_symlink()
    fd,tmp=tempfile.mkstemp(dir=path.parent)
    with os.fdopen(fd,'wb') as stream:
        stream.write(data);os.fchmod(stream.fileno(),0o644)
    os.replace(tmp,path)
icon=Path('/usr/share/icons/hicolor/256x256/apps/linker-central-server.png')
write(icon,png)
entry='[Desktop Entry]\nType=Application\nName=Central Server - WSL Docker\nExec=/bin/bash '+quote(workspace/'deploy/wsl/launch-manager.sh')+' --project '+quote(v['project'])+'\nIcon='+str(icon)+'\nStartupWMClass=linker-central-server\nTerminal=false\nCategories=Utility;\n'
write(Path('/usr/share/applications/linker-central-server.desktop'),entry.encode())
print('Registered the Central Server taskbar icon with WSLg.')
'@
$registerEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($register))
$registerBootstrap = "import base64;exec(base64.b64decode('" + $registerEncoded + "'))"
$payload | & wsl.exe -d $Distribution -u root --exec python3 -c $registerBootstrap
if ($LASTEXITCODE -ne 0) { throw 'Could not register the WSLg taskbar icon.' }

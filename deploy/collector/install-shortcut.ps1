$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $repositoryRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Install the project Python environment before installing the Collector shortcut.' }
# Windows caches icons by path. Give each design a distinct, stable filename
# so replacing collector.ico cannot leave the Start menu using the old bitmap.
$iconSource = Join-Path $PSScriptRoot 'collector.ico'
$iconHash = (Get-FileHash -LiteralPath $iconSource -Algorithm SHA256).Hash.ToLowerInvariant()
$iconDirectory = Join-Path $env:LOCALAPPDATA 'Linker\Collector\Icons'
$null = New-Item -ItemType Directory -Path $iconDirectory -Force
$iconPath = Join-Path $iconDirectory ('collector-' + $iconHash + '.ico')
if (-not (Test-Path -LiteralPath $iconPath)) { Copy-Item -LiteralPath $iconSource -Destination $iconPath }
$shell = New-Object -ComObject WScript.Shell
$programs = [Environment]::GetFolderPath('Programs')
# Search caches app artwork against the shortcut's identity as well as the
# icon file. Migrate the former root-level entry to a dedicated app group.
$folder = Join-Path $programs 'Linker SCADA Collector'
$null = New-Item -ItemType Directory -Path $folder -Force
$shortcutPath = Join-Path $folder 'SCADA Collector - WSL Docker.lnk'
$shortcutExisted = Test-Path -LiteralPath $shortcutPath
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $python
$shortcut.Arguments = '-m collector.gui'
$shortcut.WorkingDirectory = $repositoryRoot
$shortcut.Description = 'SCADA Collector setup, preview, collection and Docker controls'
$shortcut.IconLocation = $iconPath + ',0'
$shortcut.Save()
# Keep Search's app identity separate from the shared Python interpreter.
# This ID must match collector.gui.launch.
@'
import sys
from win32com.propsys import propsys, pscon
from win32com.shell import shellcon

store = propsys.SHGetPropertyStoreFromParsingName(
    sys.argv[1], None, shellcon.GPS_READWRITE, propsys.IID_IPropertyStore)
store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType('Linker.SCADA.Collector'))
store.Commit()
'@ | & (Join-Path $repositoryRoot '.venv\Scripts\python.exe') - $shortcutPath
if ($LASTEXITCODE -ne 0) { throw 'Could not set the Collector shortcut app identity.' }
if (-not ('Linker.CollectorShortcutShell' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace Linker {
    public static class CollectorShortcutShell {
        [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
        public static extern void SHChangeNotify(uint change, uint flags, string path, IntPtr extra);
    }
}
'@
}
$notification = if ($shortcutExisted) { 0x00002000 } else { 0x00000002 }
[Linker.CollectorShortcutShell]::SHChangeNotify($notification, 0x1005, $shortcutPath, [IntPtr]::Zero)
$oldShortcut = Join-Path $programs 'SCADA Collector - WSL Docker.lnk'
if (Test-Path -LiteralPath $oldShortcut) {
    Remove-Item -LiteralPath $oldShortcut -ErrorAction Stop
    [Linker.CollectorShortcutShell]::SHChangeNotify(0x00000004, 0x1005, $oldShortcut, [IntPtr]::Zero)
}
foreach ($directory in @($programs, $folder, [Environment]::GetFolderPath('DesktopDirectory'), $repositoryRoot)) {
    foreach ($name in @('SCADA Collector Docker.lnk', 'SCADA Collector.lnk', 'SCADA Collector - Setup.lnk')) {
        $old = Join-Path $directory $name
        if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -ErrorAction Stop }
    }
}
Write-Output 'Installed one SCADA Collector - WSL Docker app shortcut with setup and Docker controls.'

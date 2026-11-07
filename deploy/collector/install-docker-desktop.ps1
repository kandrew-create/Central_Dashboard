param([string]$Distribution = 'Ubuntu')
$ErrorActionPreference = 'Stop'
$repository = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$interpreter = Join-Path $repository '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $interpreter)) { throw 'Use the existing build environment to stage the Collector Docker desktop.' }
$installRoot = Join-Path $env:LOCALAPPDATA ('Linker\Collector\docker-desktop\' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
& $interpreter -m deploy.collector.build_context --root $repository --output $installRoot
if ($LASTEXITCODE -ne 0) { throw 'Cannot stage the Collector desktop.' }
& docker --context desktop-linux build --file (Join-Path $installRoot 'deploy\collector\Dockerfile.desktop') --tag linker-scada-collector-desktop:local $installRoot
if ($LASTEXITCODE -ne 0) { throw 'Cannot build the Collector desktop image. Earlier packages and all volumes are preserved.' }
$launcher = Join-Path $installRoot 'launch.vbs'
$hostScript = Join-Path $installRoot 'deploy\collector\start-docker-desktop.ps1'
$command = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $hostScript + '" -Distribution "' + $Distribution + '"'
# This script contains launcher paths only, never Collector code or credentials.
$vbs = 'CreateObject("WScript.Shell").Run "' + $command.Replace('"', '""') + '", 0, False'
Set-Content -LiteralPath $launcher -Value $vbs -Encoding Unicode
$currentLauncher = Join-Path $env:LOCALAPPDATA 'Linker\Collector\docker-desktop\current-launch.vbs'
Copy-Item -LiteralPath $launcher -Destination $currentLauncher -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'collector.ico') -Destination (Join-Path $installRoot 'collector.ico')
$shell = New-Object -ComObject WScript.Shell
$shortcutFolder = Join-Path ([Environment]::GetFolderPath('Programs')) 'Linker SCADA Collector'
$null = New-Item -ItemType Directory -Path $shortcutFolder -Force
$shortcut = $shell.CreateShortcut((Join-Path $shortcutFolder 'SCADA Collector - Docker.lnk'))
$shortcut.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
$shortcut.Arguments = '"' + $launcher + '"'
$shortcut.WorkingDirectory = $installRoot
$shortcut.IconLocation = (Join-Path $installRoot 'collector.ico') + ',0'
$shortcut.Description = 'SCADA Collector interface and runtime in Linux Docker containers'
$shortcut.Save()
$legacyShortcut = Join-Path $shortcutFolder 'SCADA Collector - WSL Docker.lnk'
if (Test-Path -LiteralPath $legacyShortcut -PathType Leaf) {
    Copy-Item -LiteralPath $legacyShortcut -Destination (Join-Path $installRoot 'previous-windows-launcher.lnk')
    Remove-Item -LiteralPath $legacyShortcut
}
$desktopShortcut = Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'SCADA Collector - Docker.lnk'
try {
    Copy-Item -LiteralPath (Join-Path $shortcutFolder 'SCADA Collector - Docker.lnk') -Destination $desktopShortcut -Force
} catch [System.UnauthorizedAccessException] {
    Write-Warning 'The desktop folder does not allow shortcut creation. Open SCADA Collector - Docker from Start or Launch Collector.cmd.'
}
Write-Output ('Installed Docker-only Collector desktop: ' + $installRoot)

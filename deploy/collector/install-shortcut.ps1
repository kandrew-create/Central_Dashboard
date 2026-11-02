$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $repositoryRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Install the project Python environment before installing the Collector shortcut.' }
$config = Join-Path $env:ProgramData 'Linker\Collector\config.toml'
if (-not (Test-Path -LiteralPath $config)) { $config = Join-Path $repositoryRoot 'collector-local\config.toml' }
$shell = New-Object -ComObject WScript.Shell
$folder = [Environment]::GetFolderPath('Programs')
$shortcut = $shell.CreateShortcut((Join-Path $folder 'SCADA Collector - WSL Docker.lnk'))
$shortcut.TargetPath = $python
$shortcut.Arguments = '-m collector.gui --config "' + $config + '"'
$shortcut.WorkingDirectory = $repositoryRoot
$shortcut.Description = 'SCADA Collector setup, preview, collection and Docker controls'
$shortcut.IconLocation = Join-Path $PSScriptRoot 'collector.ico'
$shortcut.Save()
foreach ($directory in @($folder, [Environment]::GetFolderPath('DesktopDirectory'), $repositoryRoot)) {
    foreach ($name in @('SCADA Collector Docker.lnk', 'SCADA Collector.lnk', 'SCADA Collector - Setup.lnk')) {
        $old = Join-Path $directory $name
        if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -ErrorAction Stop }
    }
}
Write-Output 'Installed one SCADA Collector - WSL Docker app shortcut with setup and Docker controls.'

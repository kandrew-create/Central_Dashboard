param([string]$Compiler = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
Push-Location -LiteralPath $projectRoot
try {
    $pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
    $entries = @(@('collector','cli_entry.py'),@('collector-gui','gui_entry.py'),@('collector-service','service_entry.py'),@('collector-admin','admin_entry.py'))
    foreach ($entry in $entries) {
        $buildArgs = @('-m','PyInstaller','--noconfirm','--onefile','--name',$entry[0],'--distpath','dist\collector','--workpath',('build\'+$entry[0]),'--specpath','build','--collect-all','tzdata','--hidden-import','win32timezone','--hidden-import','win32crypt','--hidden-import','win32security','--hidden-import','servicemanager')
        if ($entry[0] -in @('collector-gui','collector-service')) { $buildArgs += '--noconsole' }
        $buildArgs += Join-Path 'deploy\windows' $entry[1]
        $ErrorActionPreference = 'Continue'
        & $pythonExe @buildArgs 2>&1 | ForEach-Object { "$_" }
        $ErrorActionPreference = 'Stop'
        if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
    }
    if (Test-Path -LiteralPath $Compiler) {
        $ErrorActionPreference = 'Continue'
        & $Compiler (Join-Path $PSScriptRoot 'collector.iss') 2>&1 | ForEach-Object { "$_" }
        $ErrorActionPreference = 'Stop'
        if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
    } else { throw 'Inno Setup compiler not found. Executables were built; set -Compiler to build the installer.' }
    Get-ChildItem -LiteralPath 'dist\collector' -Filter '*.exe' | Get-FileHash -Algorithm SHA256 | Format-Table
    Get-ChildItem -LiteralPath 'dist\installer' -Filter '*.exe' | Get-FileHash -Algorithm SHA256 | Format-Table
} finally { Pop-Location }

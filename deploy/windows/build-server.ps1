param([string]$Compiler = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
Push-Location -LiteralPath $projectRoot
try {
    $pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
    $buildArgs = @('-m','PyInstaller','--noconfirm','--onefile','--noconsole','--name','central-server','--distpath','dist\central-server','--workpath','build\central-server','--specpath','build',
        '--add-data',((Join-Path $projectRoot 'alembic.ini')+';.'), '--add-data',((Join-Path $projectRoot 'server\migrations')+';server\migrations'),
        '--collect-all','tzdata','--collect-all','uvicorn','--collect-submodules','sqlalchemy.dialects.postgresql',
        '--hidden-import','server.app.ingestion','--hidden-import','win32timezone','--hidden-import','win32crypt','--hidden-import','win32security',
        'deploy\windows\server_entry.py')
    $ErrorActionPreference = 'Continue'
    & $pythonExe @buildArgs 2>&1 | ForEach-Object { "$_" }
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) { throw 'Central Server executable build failed.' }
    if (!(Test-Path -LiteralPath $Compiler)) { throw 'Install Inno Setup 6 or set -Compiler.' }
    $ErrorActionPreference = 'Continue'
    & $Compiler (Join-Path $PSScriptRoot 'central-server.iss') 2>&1 | ForEach-Object { "$_" }
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) { throw 'Central Server installer build failed.' }
    Get-FileHash -Algorithm SHA256 -LiteralPath 'dist\central-server\central-server.exe','dist\installer\Linker-Central-Server-Setup.exe'
} finally { Pop-Location }

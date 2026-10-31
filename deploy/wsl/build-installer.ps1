param([string]$Compiler = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
Push-Location -LiteralPath $projectRoot
try {
    & (Join-Path $projectRoot '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'build_installer.py') --compiler $Compiler
    if ($LASTEXITCODE -ne 0) { throw 'The WSL/Docker package build failed.' }
} finally { Pop-Location }

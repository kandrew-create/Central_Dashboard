param([string]$Distribution = 'Ubuntu')
$ErrorActionPreference = 'Stop'
$context = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
# The host only starts Docker/WSLg; every Collector module runs in a container.
function Test-CollectorEngine {
    # A stopped engine writes stderr on Windows PowerShell 5; it must remain a
    # failed probe rather than terminating before Docker Desktop can be opened.
    $ErrorActionPreference = 'SilentlyContinue'
    $engineType = & docker --context desktop-linux info --format '{{.OSType}}' 2>$null
    return ($LASTEXITCODE -eq 0 -and "$engineType".Trim() -eq 'linux')
}
if (-not (Test-CollectorEngine)) {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'),
        (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe')
    )
    $desktop = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (-not $desktop) { throw 'Install Docker Desktop and finish its first-run setup before opening the Collector.' }
    Start-Process -FilePath $desktop -WindowStyle Hidden
    $deadline = (Get-Date).AddSeconds(120)
    do {
        Start-Sleep -Seconds 1
        $ready = Test-CollectorEngine
        if ($ready) { break }
    } while ((Get-Date) -lt $deadline)
    if (-not $ready) { throw 'Docker Desktop did not become ready. Open it, finish setup and retry.' }
}
$linuxContext = & wsl.exe -d $Distribution --exec wslpath -a $context
if ($LASTEXITCODE -ne 0) { throw 'Cannot find the Collector context in the configured WSL distribution.' }
& wsl.exe -d $Distribution --exec bash ($linuxContext.Trim() + '/deploy/collector/launch-container.sh')
if ($LASTEXITCODE -ne 0) { throw 'Cannot open the Docker Collector. Check WSLg, Docker and the preserved Collector volumes.' }

param([string]$Compiler = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
Push-Location -LiteralPath $projectRoot
try {
    $pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
    $collectorVersion = (& $pythonExe -c 'from collector import __version__; print(__version__)').Trim()
    if ($LASTEXITCODE -ne 0 -or $collectorVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'Cannot read the Collector version.' }
    $buildId = $collectorVersion + '-' + [guid]::NewGuid().ToString('N').Substring(0, 10)
    $collectorOutput = Join-Path $projectRoot ('dist\collector\' + $buildId)
    $installerOutput = Join-Path $projectRoot ('dist\installer\collector\' + $buildId)
    New-Item -ItemType Directory -Path $collectorOutput, $installerOutput | Out-Null
    $collectorIcon = Join-Path $projectRoot 'deploy\collector\collector.ico'
    $dockerContext = Join-Path $projectRoot ('build\collector-docker-context-' + [guid]::NewGuid().ToString('N'))
    & $pythonExe -m deploy.collector.build_context --output $dockerContext
    if ($LASTEXITCODE -ne 0) { throw 'Collector Docker context staging failed.' }
    $entries = @(@('collector','cli_entry.py'),@('collector-gui','gui_entry.py'),@('collector-service','service_entry.py'),@('collector-admin','admin_entry.py'))
    foreach ($entry in $entries) {
        $buildArgs = @('-m','PyInstaller','--noconfirm','--onefile','--name',$entry[0],'--distpath',$collectorOutput,'--workpath',('build\'+$buildId+'\'+$entry[0]),'--specpath',('build\'+$buildId),'--collect-all','tzdata','--hidden-import','win32timezone','--hidden-import','win32crypt','--hidden-import','win32security','--hidden-import','servicemanager')
        $buildArgs += @('--icon', $collectorIcon)
        if ($entry[0] -in @('collector','collector-gui')) {
            $buildArgs += @('--add-data', ($collectorIcon+';deploy\collector'))
            $buildArgs += @('--add-data', ($dockerContext+';collector-docker-context'))
        }
        if ($entry[0] -in @('collector-gui','collector-service')) { $buildArgs += '--noconsole' }
        $buildArgs += Join-Path 'deploy\windows' $entry[1]
        $ErrorActionPreference = 'Continue'
        & $pythonExe @buildArgs 2>&1 | ForEach-Object { "$_" }
        $ErrorActionPreference = 'Stop'
        if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
    }
    if (Test-Path -LiteralPath $Compiler) {
        $ErrorActionPreference = 'Continue'
        & $Compiler ('/DAppVersion='+$collectorVersion) ('/DCollectorSource='+$collectorOutput) ('/DPackageOutput='+$installerOutput) (Join-Path $PSScriptRoot 'collector.iss') 2>&1 | ForEach-Object { "$_" }
        $ErrorActionPreference = 'Stop'
        if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
    } else { throw 'Inno Setup compiler not found. Executables were built; set -Compiler to build the installer.' }
    Copy-Item -LiteralPath 'docs\collector-installation.md' -Destination $installerOutput
    $contextArchive = Join-Path $installerOutput ('Collector-Docker-Context-'+$collectorVersion+'.zip')
    Compress-Archive -Path (Join-Path $dockerContext '*') -DestinationPath $contextArchive
    $artifacts = @(Get-ChildItem -LiteralPath $collectorOutput -Filter '*.exe') + @(Get-Item -LiteralPath (Join-Path $installerOutput 'Linker-SCADA-Collector-Setup.exe')) + @(Get-Item -LiteralPath $contextArchive)
    foreach ($artifact in $artifacts) {
        $digest = Get-FileHash -Algorithm SHA256 -LiteralPath $artifact.FullName
        Set-Content -LiteralPath ($artifact.FullName+'.sha256') -Encoding Ascii -Value ($digest.Hash.ToLowerInvariant()+'  '+$artifact.Name)
        $digest
    }
    [pscustomobject]@{Version=$collectorVersion;Executables=$collectorOutput;Installer=$installerOutput;DockerContext=$dockerContext} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $installerOutput 'build.json') -Encoding UTF8
    Write-Output ('Collector package: ' + $installerOutput)
} finally { Pop-Location }

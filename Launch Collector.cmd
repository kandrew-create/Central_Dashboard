@echo off
setlocal
set "COLLECTOR_LAUNCHER=%LOCALAPPDATA%\Linker\Collector\docker-desktop\current-launch.vbs"
if not exist "%COLLECTOR_LAUNCHER%" (
    echo Install the Docker Collector desktop first.
    echo See docs\collector-container-desktop.md.
    pause
    exit /b 1
)
start "" "%WINDIR%\System32\wscript.exe" "%COLLECTOR_LAUNCHER%"

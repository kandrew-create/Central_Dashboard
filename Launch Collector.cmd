@echo off
setlocal
set "COLLECTOR_ROOT=%~dp0"
if not exist "%COLLECTOR_ROOT%.venv\Scripts\pythonw.exe" (
    echo Collector Python environment was not found.
    echo Follow collector\README.md to install the collector dependencies first.
    pause
    exit /b 1
)
start "" /D "%COLLECTOR_ROOT%" "%COLLECTOR_ROOT%.venv\Scripts\pythonw.exe" -m collector.gui --config "%COLLECTOR_ROOT%collector-local\config.toml"

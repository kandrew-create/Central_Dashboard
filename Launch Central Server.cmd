@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Install the Central Server manager dependencies first.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m server.management.entry

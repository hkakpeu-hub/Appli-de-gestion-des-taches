@echo off
setlocal
cd /d "%~dp0"
set "VENV=%LOCALAPPDATA%\SuiviTaches\venv"
if not exist "%VENV%\Scripts\pythonw.exe" (
  echo Premier lancement : installation en cours...
  call "%~dp0install.bat"
)
start "" "%VENV%\Scripts\pythonw.exe" "%~dp0run.py"

@echo off
setlocal
chcp 65001 >nul
title Installation - Suivi des taches
set "APPHOME=%LOCALAPPDATA%\SuiviTaches"
set "VENV=%APPHOME%\venv"
cd /d "%~dp0"

echo === Installation de "Suivi des taches" ===
where py >nul 2>nul && (set "PY=py -3") || (where python >nul 2>nul && (set "PY=python") || (
  echo Python 3.10 ou plus recent est introuvable. Installez-le depuis https://www.python.org/downloads/
  echo en cochant "Add python.exe to PATH", puis relancez install.bat.
  pause & exit /b 1))

if not exist "%APPHOME%" mkdir "%APPHOME%"
if not exist "%VENV%\Scripts\python.exe" (
  echo Creation de l'environnement Python dans %VENV% ...
  %PY% -m venv "%VENV%" || (echo Echec de la creation de l'environnement. & pause & exit /b 1)
)
echo Installation / mise a jour des dependances (Internet requis une seule fois) ...
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip >nul
"%VENV%\Scripts\python.exe" -m pip install -r requirements.txt || (echo Echec de l'installation des dependances. & pause & exit /b 1)

echo.
echo Installation terminee. Vos donnees sont dans %APPHOME% (jamais ecrasees par une mise a jour).
echo Lancez l'application avec start.bat
choice /m "Creer un raccourci sur le Bureau"
if errorlevel 2 goto end
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Suivi des taches.lnk');$s.TargetPath='%~dp0start.bat';$s.WorkingDirectory='%~dp0';$s.WindowStyle=7;$s.Save()"
echo Raccourci cree.
:end
pause

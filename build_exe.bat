@echo off
setlocal
cd /d "%~dp0"
set "VENV=%LOCALAPPDATA%\SuiviTaches\venv"
if not exist "%VENV%\Scripts\python.exe" call "%~dp0install.bat"
"%VENV%\Scripts\python.exe" -m pip install pyinstaller || exit /b 1
"%VENV%\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --name SuiviTaches ^
  --workpath "%LOCALAPPDATA%\SuiviTaches\build" --specpath "%LOCALAPPDATA%\SuiviTaches\build" ^
  --distpath "%~dp0dist" --paths "%~dp0." ^
  --hidden-import keyring.backends.Windows --hidden-import xlrd ^
  "%~dp0run.py" || (echo Echec de la creation de l'executable. & pause & exit /b 1)
echo.
echo Executable cree : %~dp0dist\SuiviTaches\SuiviTaches.exe
echo (Copiez tout le dossier dist\SuiviTaches. Les donnees restent dans %%LOCALAPPDATA%%\SuiviTaches.)
pause

@echo off
setlocal
cd /d "%~dp0"
set "VENV=%LOCALAPPDATA%\SuiviTaches\venv"
set "OUT=%LOCALAPPDATA%\SuiviTaches\dist"
if not exist "%VENV%\Scripts\python.exe" call "%~dp0install.bat"
taskkill /im SuiviTaches.exe /f >nul 2>nul
"%VENV%\Scripts\python.exe" -m pip install pyinstaller || exit /b 1
rem Construction dans un dossier local (hors OneDrive, dont la synchronisation verrouille les fichiers), puis copie dans dist\
"%VENV%\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --name SuiviTaches ^
  --workpath "%LOCALAPPDATA%\SuiviTaches\build" --specpath "%LOCALAPPDATA%\SuiviTaches\build" ^
  --distpath "%OUT%" --paths "%~dp0." ^
  --hidden-import keyring.backends.Windows --hidden-import xlrd ^
  "%~dp0run.py" || (echo Echec de la creation de l'executable. & pause & exit /b 1)
robocopy "%OUT%\SuiviTaches" "%~dp0dist\SuiviTaches" /MIR /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (echo Echec de la copie vers dist\. L'executable est disponible dans %OUT%\SuiviTaches & pause & exit /b 1)
echo.
echo Executable cree : %~dp0dist\SuiviTaches\SuiviTaches.exe
echo (Copiez tout le dossier dist\SuiviTaches. Les donnees restent dans %%LOCALAPPDATA%%\SuiviTaches.)
pause

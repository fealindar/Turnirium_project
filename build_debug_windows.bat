@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.13 -m venv .venv
  if errorlevel 1 py -3.12 -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -r requirements-build.txt
for /f "delims=" %%V in ('python -c "from app.version import APP_VERSION; print(chr(46).join(APP_VERSION.split(chr(46))[:2]))"') do set "BUILD_VERSION=%%V"
if not defined BUILD_VERSION goto :error
set "OUTPUT_NAME=TurniriumDebug_%BUILD_VERSION%.exe"
python -m PyInstaller --noconfirm --clean --onefile --console --name TurniriumDebug --icon "assets\turnirium.ico" --add-data "app/static:app/static" --add-data "assets/turnirium_icon.png:assets" --add-data "assets/turnirium.ico:assets" --add-data "branding.json:." run.py
if errorlevel 1 goto :error
move /Y "dist\TurniriumDebug.exe" "dist\%OUTPUT_NAME%" >nul
if errorlevel 1 goto :error
echo Debug build: %CD%\dist\%OUTPUT_NAME%
pause
exit /b 0
:error
pause
exit /b 1

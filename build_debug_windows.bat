@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  py -3.13 -m venv .venv
  if errorlevel 1 py -3.12 -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install -r requirements-build.txt
if errorlevel 1 goto :error

for /f "delims=" %%V in ('python -c "from app.version import APP_VERSION; print(chr(46).join(APP_VERSION.split(chr(46))[:2]))"') do set "BUILD_VERSION=%%V"
if not defined BUILD_VERSION goto :error
set "OUTPUT_DIR=TurniriumDebug_%BUILD_VERSION%"

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

python tools\generate_version_info.py
if errorlevel 1 goto :error

python -m PyInstaller --noconfirm --clean --onedir --console --debug noarchive --noupx --name TurniriumDebug ^
  --icon "assets\turnirium.ico" ^
  --version-file "version_info.txt" ^
  --add-data "app/static:app/static" ^
  --add-data "assets/turnirium_icon.png:assets" ^
  --add-data "assets/turnirium.ico:assets" ^
  --add-data "branding.json:." ^
  --hidden-import uvicorn.logging ^
  --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import uvicorn.lifespan.on ^
  --hidden-import pystray._win32 ^
  run.py
if errorlevel 1 goto :error

move /Y "dist\TurniriumDebug" "dist\%OUTPUT_DIR%" >nul
if errorlevel 1 goto :error

echo Debug build:
echo   %CD%\dist\%OUTPUT_DIR%\TurniriumDebug.exe
echo Copy the entire %OUTPUT_DIR% folder, including _internal.
pause
exit /b 0

:error
echo.
echo BUILD FAILED.
pause
exit /b 1

@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating build virtual environment...
  py -3.13 -m venv .venv
  if errorlevel 1 py -3.12 -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt

for /f "delims=" %%V in ('python -c "from app.version import APP_VERSION; print(chr(46).join(APP_VERSION.split(chr(46))[:2]))"') do set "BUILD_VERSION=%%V"
if not defined BUILD_VERSION goto :error
set "OUTPUT_NAME=Turnirium_%BUILD_VERSION%.exe"

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

python -m PyInstaller --noconfirm --clean Turnirium.spec
if errorlevel 1 goto :error

move /Y "dist\Turnirium.exe" "dist\%OUTPUT_NAME%" >nul
if errorlevel 1 goto :error

echo.
echo Build finished:
echo   %CD%\dist\%OUTPUT_NAME%
echo.
echo Copy only %OUTPUT_NAME% to the competition computer.
echo The data folder will be created next to the EXE on first launch.
pause
exit /b 0

:error
echo.
echo BUILD FAILED.
pause
exit /b 1

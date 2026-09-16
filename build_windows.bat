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
if errorlevel 1 goto :error

for /f "delims=" %%V in ('python -c "from app.version import APP_VERSION; print(APP_VERSION)"') do set "BUILD_VERSION=%%V"
if not defined BUILD_VERSION goto :error

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

python tools\generate_version_info.py
if errorlevel 1 goto :error

python -m PyInstaller --noconfirm --clean Turnirium.spec
if errorlevel 1 goto :error

if not exist "dist\Turnirium.exe" goto :error

for %%F in ("dist\Turnirium.exe") do set "EXE_SIZE=%%~zF"

echo.
echo Build finished: Turnirium %BUILD_VERSION%
echo   %CD%\dist\Turnirium.exe
echo   Size: %EXE_SIZE% bytes
echo.
echo SHA-256:
certutil -hashfile "dist\Turnirium.exe" SHA256 | findstr /V /I "hash CertUtil"
echo.
echo Distribution: copy only dist\Turnirium.exe.
echo The data folder will be created next to the executable on first launch.
echo.
echo NOTE: a PyInstaller onefile application extracts bundled runtime files to

echo a temporary _MEI directory while it is running. This is expected behavior.
pause
exit /b 0

:error
echo.
echo BUILD FAILED.
pause
exit /b 1

@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating build virtual environment...
  py -3.13 -m venv .venv
  if errorlevel 1 py -3.12 -m venv .venv
  if errorlevel 1 goto :error
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto :error
python -m pip install -r requirements-build.txt
if errorlevel 1 goto :error

for /f "delims=" %%V in ('python -c "from app.version import APP_VERSION; print(APP_VERSION)"') do set "BUILD_VERSION=%%V"
if not defined BUILD_VERSION goto :error
set "ARTIFACT_BASENAME=Turnirium_v%BUILD_VERSION%"

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
mkdir dist
if errorlevel 1 goto :error

python tools\generate_version_info.py
if errorlevel 1 goto :error

echo.
echo [1/2] Building onefile release: %ARTIFACT_BASENAME%.exe
python -m PyInstaller --noconfirm --clean --distpath dist --workpath build\onefile Turnirium.spec
if errorlevel 1 goto :error
if not exist "dist\%ARTIFACT_BASENAME%.exe" goto :error

call tools\sign_windows_artifact.bat "dist\%ARTIFACT_BASENAME%.exe"
if errorlevel 1 goto :error

echo.
echo [2/2] Building onedir + noarchive release and packaging ZIP...
python -m PyInstaller --noconfirm --clean --distpath build\onedir-dist --workpath build\onedir Turnirium_onedir.spec
if errorlevel 1 goto :error
if not exist "build\onedir-dist\%ARTIFACT_BASENAME%\%ARTIFACT_BASENAME%.exe" goto :error

call tools\sign_windows_artifact.bat "build\onedir-dist\%ARTIFACT_BASENAME%\%ARTIFACT_BASENAME%.exe"
if errorlevel 1 goto :error

python tools\package_onedir.py "build\onedir-dist\%ARTIFACT_BASENAME%" "dist\%ARTIFACT_BASENAME%.zip"
if errorlevel 1 goto :error
if not exist "dist\%ARTIFACT_BASENAME%.zip" goto :error

for %%F in ("dist\%ARTIFACT_BASENAME%.exe") do set "EXE_SIZE=%%~zF"
for %%F in ("dist\%ARTIFACT_BASENAME%.zip") do set "ZIP_SIZE=%%~zF"

echo.
echo Build finished: Turnirium %BUILD_VERSION%
echo dist contains exactly the two release variants:
echo   %CD%\dist\%ARTIFACT_BASENAME%.exe
echo     onefile, %EXE_SIZE% bytes
echo   %CD%\dist\%ARTIFACT_BASENAME%.zip
echo     onedir + noarchive, %ZIP_SIZE% bytes
echo.
echo SHA-256 - onefile:
certutil -hashfile "dist\%ARTIFACT_BASENAME%.exe" SHA256 | findstr /V /I "hash CertUtil"
echo SHA-256 - onedir ZIP:
certutil -hashfile "dist\%ARTIFACT_BASENAME%.zip" SHA256 | findstr /V /I "hash CertUtil"
echo.
if defined TURNIRIUM_SIGN_CERT_SHA1 (
  echo Authenticode signing: enabled.
) else (
  echo Authenticode signing: disabled.
  echo For public releases, configure TURNIRIUM_SIGN_CERT_SHA1 and TURNIRIUM_TIMESTAMP_URL.
)
echo.
echo The onedir ZIP is the preferred distribution when antivirus false positives matter.
echo Onefile uses the stock PyInstaller self-extracting bootloader and may still receive
echo more ML/heuristic scrutiny even with UPX disabled and clean version metadata.
pause
exit /b 0

:error
echo.
echo BUILD FAILED.
pause
exit /b 1

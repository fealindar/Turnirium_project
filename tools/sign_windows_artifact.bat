@echo off
setlocal

rem Optional Authenticode signing for release artifacts.
rem Nothing is signed unless TURNIRIUM_SIGN_CERT_SHA1 is explicitly configured.
rem This uses a certificate already installed in the Windows certificate store;
rem no private key or password is stored in the repository.

set "TARGET=%~1"
if not defined TARGET exit /b 2
if not exist "%TARGET%" (
  echo ERROR: signing target not found: %TARGET%
  exit /b 2
)

if not defined TURNIRIUM_SIGN_CERT_SHA1 exit /b 0

if not defined TURNIRIUM_TIMESTAMP_URL (
  echo ERROR: TURNIRIUM_SIGN_CERT_SHA1 is set, but TURNIRIUM_TIMESTAMP_URL is not.
  echo Configure an RFC3161 timestamp service URL before signing releases.
  exit /b 2
)

set "SIGNTOOL="
if defined TURNIRIUM_SIGNTOOL (
  if exist "%TURNIRIUM_SIGNTOOL%" set "SIGNTOOL=%TURNIRIUM_SIGNTOOL%"
)
if not defined SIGNTOOL (
  for /f "delims=" %%S in ('where signtool.exe 2^>nul') do if not defined SIGNTOOL set "SIGNTOOL=%%S"
)
if not defined SIGNTOOL (
  echo ERROR: signtool.exe was not found.
  echo Install the Windows SDK or set TURNIRIUM_SIGNTOOL to the full path.
  exit /b 2
)

"%SIGNTOOL%" sign /fd SHA256 /sha1 "%TURNIRIUM_SIGN_CERT_SHA1%" /tr "%TURNIRIUM_TIMESTAMP_URL%" /td SHA256 "%TARGET%"
if errorlevel 1 exit /b 1

"%SIGNTOOL%" verify /pa /v "%TARGET%"
if errorlevel 1 exit /b 1

exit /b 0

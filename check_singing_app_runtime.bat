@echo off
setlocal

set APP_ROOT=%~dp0
set PYTHON=%APP_ROOT%tools\ApplioV3.6.2\env\python.exe
set NO_PAUSE=
if /I "%~1"=="--no-pause" set NO_PAUSE=1

if not exist "%PYTHON%" (
  echo Missing bundled Python runtime:
  echo %PYTHON%
  if not defined NO_PAUSE pause
  exit /b 1
)

cd /d "%APP_ROOT%"
"%PYTHON%" -m singing_app.main check-runtime
echo.
if errorlevel 1 (
  echo Runtime check failed. Please reinstall or repair the app runtime.
) else (
  echo Runtime check passed.
)
if not defined NO_PAUSE pause

endlocal

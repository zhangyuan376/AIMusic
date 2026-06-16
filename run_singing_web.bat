@echo off
setlocal

set APP_ROOT=%~dp0
set PYTHON=%APP_ROOT%tools\ApplioV3.6.2\env\python.exe

if not exist "%PYTHON%" (
  echo Missing bundled Python runtime:
  echo %PYTHON%
  echo.
  echo Please reinstall the app runtime.
  pause
  exit /b 1
)

cd /d "%APP_ROOT%"
"%PYTHON%" -m singing_app.main web

endlocal

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
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":7860" ^| findstr "LISTENING"') do (
  echo Stopping old web server on port 7860, PID %%P
  taskkill /PID %%P /T /F >nul 2>nul
)
"%PYTHON%" -m singing_app.main web

endlocal

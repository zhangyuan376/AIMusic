@echo off
setlocal

cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0setup_env.ps1" %*
if errorlevel 1 (
  echo.
  echo Environment setup failed.
  pause
  exit /b 1
)

echo.
echo Environment setup finished.
pause
endlocal

$ErrorActionPreference = "Stop"

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
  throw "winget is not available on this machine."
}

Write-Host "Installing Python 3.10 ..."
winget install -e --id Python.Python.3.10 --accept-source-agreements --accept-package-agreements

Write-Host "Installing FFmpeg ..."
winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements

Write-Host ""
Write-Host "Install commands completed."
Write-Host "Please restart PowerShell/Cursor terminal, then run:"
Write-Host "python --version"
Write-Host "ffmpeg -version"
Write-Host "python -m pip install --upgrade pip"
Write-Host "python -m pip install edge-tts"

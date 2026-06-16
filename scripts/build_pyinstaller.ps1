param(
  [string]$Name = "AISingingVideo"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path "$PSScriptRoot\.."
$Python = Join-Path $Root "tools\ApplioV3.6.2\env\python.exe"

if (-not (Test-Path $Python)) {
  throw "Missing Python runtime: $Python"
}

& $Python -m pip show pyinstaller | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Installing PyInstaller into bundled runtime..."
  & $Python -m pip install pyinstaller
}

Push-Location $Root
try {
  & $Python -m PyInstaller `
    --name $Name `
    --noconsole `
    --clean `
    "singing_app_ui_launcher.py"

  $ExePath = Join-Path $Root "dist\$Name\$Name.exe"
  if (-not (Test-Path $ExePath)) {
    throw "PyInstaller did not create expected exe: $ExePath"
  }
  Write-Host "Created: $ExePath"
} finally {
  Pop-Location
}

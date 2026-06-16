param(
  [string]$StagingDir = "$PSScriptRoot\..\offline_staging",
  [switch]$SkipRuntime
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path "$PSScriptRoot\.."
$Staging = Resolve-Path $StagingDir
$ManifestPath = Join-Path $Root "installer\runtime_manifest.json"
$Manifest = Get-Content $ManifestPath -Raw | ConvertFrom-Json

$required = @()
$required += $Manifest.app.exe
$required += "run_singing_app.bat"
$required += "check_singing_app_runtime.bat"
$required += "USER_GUIDE_zh.md"
$required += $Manifest.default_assets
$required += $Manifest.default_models
$required += $Manifest.default_jobs
$required += "singing_app/main.py"
$required += "singing_app/ui.py"
$required += "singing_app/projects"

if (-not $SkipRuntime) {
  $required += $Manifest.runtime.python
  $required += $Manifest.runtime.ffmpeg
  $required += $Manifest.runtime.applio_core
}

$missing = @()
foreach ($relative in $required) {
  $path = Join-Path $Staging $relative
  if (-not (Test-Path $path)) {
    $missing += $relative
  }
}

if ($missing.Count -gt 0) {
  Write-Host "Offline staging verification failed. Missing:"
  foreach ($item in $missing) {
    Write-Host " - $item"
  }
  exit 1
}

$projectFiles = Get-ChildItem (Join-Path $Staging "singing_app\projects") -Recurse -File -ErrorAction SilentlyContinue
if ($projectFiles.Count -gt 0) {
  Write-Host "Offline staging verification failed. Projects folder should be empty."
  foreach ($file in $projectFiles) {
    Write-Host " - $($file.FullName)"
  }
  exit 1
}

Write-Host "Offline staging verification passed."

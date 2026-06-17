param(
  [string]$OutputDir = "$PSScriptRoot\..\offline_staging",
  [switch]$SkipRuntime
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path "$PSScriptRoot\.."
$Out = New-Item -ItemType Directory -Force -Path $OutputDir

Write-Host "Preparing offline staging folder at $($Out.FullName)"

$cleanItems = @("singing_app", "voice_pipeline", "tools", "run_singing_app.bat", "run_singing_web.bat", "check_singing_app_runtime.bat")
foreach ($item in $cleanItems) {
  $target = Join-Path $Out.FullName $item
  if (Test-Path $target) {
    Remove-Item $target -Recurse -Force
  }
}

$appSource = Join-Path $Root "singing_app"
$appTarget = Join-Path $Out.FullName "singing_app"
New-Item -ItemType Directory -Force -Path $appTarget | Out-Null
Get-ChildItem $appSource -Recurse -File | Where-Object {
  $_.FullName -notlike (Join-Path $appSource "projects\*") -and
  $_.FullName -notlike "*\__pycache__\*" -and
  $_.Name -ne "voice_library.json" -and
  $_.Extension -ne ".pyc"
} | ForEach-Object {
  $relative = $_.FullName.Substring($appSource.Length).TrimStart("\")
  $target = Join-Path $appTarget $relative
  New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
  Copy-Item $_.FullName $target -Force
}
New-Item -ItemType Directory -Force -Path (Join-Path $appTarget "projects") | Out-Null

Copy-Item (Join-Path $Root "run_singing_app.bat") (Join-Path $Out.FullName "run_singing_app.bat") -Force
Copy-Item (Join-Path $Root "run_singing_web.bat") (Join-Path $Out.FullName "run_singing_web.bat") -Force
Copy-Item (Join-Path $Root "check_singing_app_runtime.bat") (Join-Path $Out.FullName "check_singing_app_runtime.bat") -Force
Copy-Item (Join-Path $Root "USER_GUIDE_zh.md") (Join-Path $Out.FullName "USER_GUIDE_zh.md") -Force

$assetRoot = Join-Path $Out.FullName "voice_pipeline"
New-Item -ItemType Directory -Force -Path (Join-Path $assetRoot "models") | Out-Null
Copy-Item (Join-Path $Root "voice_pipeline\Generated_image*.png") $assetRoot -Force
Copy-Item (Join-Path $Root "voice_pipeline\models\pomao_clear_voice_10e_1350s.pth") (Join-Path $assetRoot "models") -Force
Copy-Item (Join-Path $Root "voice_pipeline\models\pomao_clear_voice.index") (Join-Path $assetRoot "models") -Force

if ($SkipRuntime) {
  Write-Host "Skipping runtime copy."
} else {
  $runtimeSource = Join-Path $Root "tools\ApplioV3.6.2"
  $runtimeTarget = Join-Path $Out.FullName "tools\ApplioV3.6.2"
  if (-not (Test-Path $runtimeSource)) {
    throw "Missing runtime: $runtimeSource"
  }
  Copy-Item $runtimeSource $runtimeTarget -Recurse -Force
}

Write-Host "Offline staging folder is ready."

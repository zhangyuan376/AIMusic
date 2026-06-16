param(
  [string]$OutputDir = "$PSScriptRoot\..\dist_dev"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path "$PSScriptRoot\.."
$Out = New-Item -ItemType Directory -Force -Path $OutputDir

Write-Host "Building development package at $($Out.FullName)"

$items = @(
  "singing_app",
  "installer",
  "run_singing_app.bat",
  "check_singing_app_runtime.bat"
)

foreach ($item in $items) {
  $source = Join-Path $Root $item
  $target = Join-Path $Out.FullName $item
  if (Test-Path $target) {
    Remove-Item $target -Recurse -Force
  }
  Copy-Item $source $target -Recurse -Force
}

$assetRoot = Join-Path $Out.FullName "voice_pipeline"
New-Item -ItemType Directory -Force -Path (Join-Path $assetRoot "models") | Out-Null

Copy-Item (Join-Path $Root "voice_pipeline\Generated_image*.png") $assetRoot -Force
Copy-Item (Join-Path $Root "voice_pipeline\models\pomao_clear_voice_10e_1350s.pth") (Join-Path $assetRoot "models") -Force
Copy-Item (Join-Path $Root "voice_pipeline\models\pomao_clear_voice.index") (Join-Path $assetRoot "models") -Force

Write-Host "Development package created."
Write-Host "Note: this package references the existing local runtime under tools/ApplioV3.6.2."
Write-Host "The full offline installer will copy runtime/ApplioV3.6.2 as described in installer/runtime_manifest.json."

param(
  [string]$Voice = "zh-CN-YunxiaNeural",
  [string]$ScriptPath = "$PSScriptRoot\pomao_training_script_zh.txt",
  [string]$OutputDir = "$PSScriptRoot\samples"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw "Python is not installed or not in PATH. Install Python 3.10 first."
}

if (-not (Test-Path $ScriptPath)) {
  throw "Training script not found: $ScriptPath"
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$raw = Get-Content -Raw -Encoding UTF8 $ScriptPath
$blocks = $raw -split "(\r?\n){2,}" | Where-Object { $_.Trim().Length -gt 0 }

if ($blocks.Count -eq 0) {
  throw "No text blocks found in $ScriptPath"
}

$variants = @(
  @{ Suffix = "child_soft"; Rate = "-5%"; Pitch = "+4Hz"; Volume = "-4%" },
  @{ Suffix = "child_tiny"; Rate = "-10%"; Pitch = "+8Hz"; Volume = "-5%" },
  @{ Suffix = "child_plain"; Rate = "-3%"; Pitch = "+2Hz"; Volume = "-4%" }
)

$sampleIndex = 1

foreach ($variant in $variants) {
  foreach ($block in $blocks) {
    $text = $block.Trim()
    if ($text.Length -lt 4) {
      continue
    }

    $baseName = "{0:D3}_{1}" -f $sampleIndex, $variant.Suffix
    $mp3Path = Join-Path $OutputDir "$baseName.mp3"
    $wavPath = Join-Path $OutputDir "$baseName.wav"

    Write-Host "Generating $baseName ..."

    python -m edge_tts `
      --voice $Voice `
      "--rate=$($variant.Rate)" `
      "--pitch=$($variant.Pitch)" `
      "--volume=$($variant.Volume)" `
      --text $text `
      --write-media $mp3Path

    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $mp3Path)) {
      throw "edge-tts failed to generate: $mp3Path"
    }

    if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
      ffmpeg -y -i $mp3Path -ac 1 -ar 44100 -sample_fmt s16 $wavPath | Out-Null
      if ($LASTEXITCODE -ne 0 -or -not (Test-Path $wavPath)) {
        throw "ffmpeg failed to convert: $wavPath"
      }
    }

    $sampleIndex += 1
  }
}

Write-Host ""
Write-Host "Done. Samples written to:"
Write-Host $OutputDir
Write-Host ""
Write-Host "If FFmpeg is installed, use the .wav files for RVC training."
Write-Host "If only .mp3 files were created, install FFmpeg and run this script again."

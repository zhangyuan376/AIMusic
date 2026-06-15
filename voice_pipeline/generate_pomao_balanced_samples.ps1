param(
  [string]$Voice = "zh-CN-YunxiaNeural",
  [string]$ScriptPath = "$PSScriptRoot\pomao_training_script_zh.txt",
  [string]$OutputDir = "$PSScriptRoot\samples_pomao_balanced"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw "Python is not installed or not in PATH. Install Python 3.10 first."
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  throw "FFmpeg is not installed or not in PATH."
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
  @{ Suffix = "balanced_a"; Rate = "-16%"; Pitch = "-10Hz"; Volume = "-5%"; Speed = "1.00" },
  @{ Suffix = "balanced_b"; Rate = "-18%"; Pitch = "-9Hz"; Volume = "-5%"; Speed = "1.015" },
  @{ Suffix = "balanced_c"; Rate = "-14%"; Pitch = "-11Hz"; Volume = "-5%"; Speed = "0.985" }
)

$sampleIndex = 1

foreach ($variant in $variants) {
  foreach ($block in $blocks) {
    $text = $block.Trim()
    if ($text.Length -lt 4) {
      continue
    }

    $baseName = "{0:D3}_{1}" -f $sampleIndex, $variant.Suffix
    $rawMp3Path = Join-Path $OutputDir "$baseName.raw.mp3"
    $wavPath = Join-Path $OutputDir "$baseName.wav"

    Write-Host "Generating $baseName ..."

    python -m edge_tts `
      --voice $Voice `
      "--rate=$($variant.Rate)" `
      "--pitch=$($variant.Pitch)" `
      "--volume=$($variant.Volume)" `
      --text $text `
      --write-media $rawMp3Path

    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $rawMp3Path)) {
      throw "edge-tts failed to generate: $rawMp3Path"
    }

    # Signature voice from audition 06: small creature boy, nasal midrange,
    # mild roughness, restrained weird-cute color, not sharp or feminine.
    ffmpeg -y -i $rawMp3Path `
      -af "asetrate=24000*1.00,aresample=44100,atempo=$($variant.Speed),acrusher=level_in=1:level_out=0.82:bits=14:mode=log:aa=1,vibrato=f=3.8:d=0.02,highpass=f=140,lowpass=f=4600,equalizer=f=780:t=q:w=1:g=4,equalizer=f=1550:t=q:w=0.9:g=5,acompressor=threshold=-22dB:ratio=3.0:attack=7:release=145" `
      -ac 1 -ar 44100 -sample_fmt s16 $wavPath | Out-Null

    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $wavPath)) {
      throw "ffmpeg failed to create styled WAV: $wavPath"
    }

    Remove-Item $rawMp3Path -Force
    $sampleIndex += 1
  }
}

Write-Host ""
Write-Host "Done. Balanced Pomao samples written to:"
Write-Host $OutputDir

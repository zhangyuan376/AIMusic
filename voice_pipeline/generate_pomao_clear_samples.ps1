param(
  [string]$Voice = "zh-CN-YunxiNeural",
  [string]$ScriptPath = "$PSScriptRoot\pomao_training_script_zh.txt",
  [string]$OutputDir = "$PSScriptRoot\samples_pomao_clear"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw "Python is not installed or not in PATH."
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  throw "FFmpeg is not installed or not in PATH."
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$raw = Get-Content -Raw -Encoding UTF8 $ScriptPath
$blocks = $raw -split "(\r?\n){2,}" | Where-Object { $_.Trim().Length -gt 0 }

$variants = @(
  @{ Suffix = "clear_a"; Rate = "-10%"; Pitch = "-5Hz"; Volume = "-4%"; Speed = "1.00" },
  @{ Suffix = "clear_b"; Rate = "-12%"; Pitch = "-7Hz"; Volume = "-4%"; Speed = "1.01" },
  @{ Suffix = "clear_c"; Rate = "-8%"; Pitch = "-4Hz"; Volume = "-4%"; Speed = "0.99" }
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

    # Clearer singer source: no bitcrush, no vibrato/tremolo, no chorus.
    # Keep only mild nasal-mid EQ and compression for a small boy creature tone.
    ffmpeg -y -i $rawMp3Path `
      -af "asetrate=24000*1.00,aresample=44100,atempo=$($variant.Speed),highpass=f=110,lowpass=f=6200,equalizer=f=850:t=q:w=1:g=2.5,equalizer=f=1550:t=q:w=1:g=2.5,equalizer=f=3200:t=q:w=1:g=1.5,acompressor=threshold=-20dB:ratio=2.0:attack=12:release=120" `
      -ac 1 -ar 44100 -sample_fmt s16 $wavPath | Out-Null

    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $wavPath)) {
      throw "ffmpeg failed to create WAV: $wavPath"
    }

    Remove-Item $rawMp3Path -Force
    $sampleIndex += 1
  }
}

Write-Host ""
Write-Host "Done. Clear Pomao samples written to:"
Write-Host $OutputDir

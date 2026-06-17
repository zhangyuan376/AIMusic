param(
    [string]$Python = "python",
    [switch]$SkipFfmpegInstall
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimeRoot = Join-Path $Root "tools\ApplioV3.6.2"
$VenvPath = Join-Path $RuntimeRoot "env"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
$RuntimePythonExe = Join-Path $VenvPath "python.exe"
$Requirements = Join-Path $Root "requirements.txt"
$FfmpegExe = Join-Path $RuntimeRoot "ffmpeg.exe"

function Invoke-Step {
    param(
        [string]$Title,
        [scriptblock]$Body
    )

    Write-Host ""
    Write-Host "==> $Title" -ForegroundColor Cyan
    & $Body
}

Invoke-Step "Check Python" {
    & $Python --version
}

Invoke-Step "Create runtime virtual environment" {
    New-Item -ItemType Directory -Force $RuntimeRoot | Out-Null
    if (-not (Test-Path $PythonExe)) {
        & $Python -m venv $VenvPath
    }
    if (-not (Test-Path $RuntimePythonExe)) {
        Copy-Item -Force $PythonExe $RuntimePythonExe
    }
    & $RuntimePythonExe -m pip install --upgrade pip setuptools wheel
}

Invoke-Step "Install Python requirements" {
    & $RuntimePythonExe -m pip install -r $Requirements
}

if (-not $SkipFfmpegInstall) {
    Invoke-Step "Check FFmpeg" {
        if (Test-Path $FfmpegExe) {
            Write-Host "FFmpeg already exists: $FfmpegExe"
            return
        }

        $systemFfmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
        if ($systemFfmpeg) {
            Copy-Item -Force $systemFfmpeg.Source $FfmpegExe
            Write-Host "Copied FFmpeg from PATH: $($systemFfmpeg.Source)"
            return
        }

        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if ($winget) {
            Write-Host "FFmpeg not found. Installing Gyan.FFmpeg via winget..."
            winget install --id Gyan.FFmpeg --source winget --accept-package-agreements --accept-source-agreements
            $installedFfmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
            if ($installedFfmpeg) {
                Copy-Item -Force $installedFfmpeg.Source $FfmpegExe
                Write-Host "Copied FFmpeg from PATH: $($installedFfmpeg.Source)"
                return
            }
        }

        Write-Warning "FFmpeg was not found. Install FFmpeg manually and copy ffmpeg.exe to: $FfmpegExe"
    }
}

Invoke-Step "Run runtime check" {
    & $RuntimePythonExe -m singing_app.main check-runtime
}

Write-Host ""
Write-Host "Environment setup finished." -ForegroundColor Green
Write-Host "Start the web UI with: run_singing_web.bat"
Write-Host ""
Write-Host "Note: RVC/Applio model files are large local runtime assets and are not stored in GitHub."
Write-Host "If runtime check reports missing core.py, .pth, .index, or character images, copy those assets into the paths shown by the check."

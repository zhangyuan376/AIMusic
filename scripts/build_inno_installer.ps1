param(
  [string]$InnoCompiler = ""
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path "$PSScriptRoot\.."
$ScriptPath = Join-Path $Root "installer\AISingingVideo.iss"

if (-not $InnoCompiler) {
  $candidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
  )
  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
      $InnoCompiler = $candidate
      break
    }
  }
}

if (-not $InnoCompiler -or -not (Test-Path $InnoCompiler)) {
  throw "Inno Setup compiler not found. Install Inno Setup 6 or pass -InnoCompiler path."
}

Push-Location (Join-Path $Root "installer")
try {
  & $InnoCompiler "/Q" $ScriptPath
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
} finally {
  Pop-Location
}

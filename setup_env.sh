#!/usr/bin/env bash
# Linux/macOS environment setup for AI Singing Video.
# Windows users: use setup_env.bat / setup_env.ps1 instead.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

VENV="$ROOT/.venv"
PYTHON="$VENV/bin/python"

echo "==> Check Python"
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install Python 3.10+ first." >&2
  exit 1
fi
python3 --version

echo "==> Create virtual environment"
if [ ! -x "$PYTHON" ]; then
  python3 -m venv "$VENV"
fi
"$PYTHON" -m pip install --upgrade pip setuptools wheel

echo "==> Install Python requirements"
# Honors PIP_INDEX_URL if exported, e.g.
#   PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple bash setup_env.sh
"$PYTHON" -m pip install -r "$ROOT/requirements.txt"

echo "==> Check Python audio support (lzma)"
# Some source-built Python interpreters are compiled without liblzma, so the
# stdlib "lzma" module is missing. Audio libraries (librosa/soundfile chain,
# used by Demucs and the Applio training pipeline) then fail with
# "No module named '_lzma'". Detect it early.
if ! "$PYTHON" -c "import lzma" >/dev/null 2>&1; then
  echo "WARNING: this Python lacks the 'lzma' module (built without liblzma)." >&2
  echo "Audio loading will fail with: No module named '_lzma'." >&2
  echo "Fix by installing liblzma dev headers and rebuilding Python, e.g.:" >&2
  echo "  sudo apt install -y liblzma-dev   # then reinstall/rebuild Python" >&2
  echo "or use a python-build-standalone / conda interpreter that ships lzma." >&2
fi

echo "==> Check FFmpeg"
if command -v ffmpeg >/dev/null 2>&1; then
  echo "FFmpeg found: $(command -v ffmpeg)"
else
  echo "FFmpeg not found on PATH."
  echo "Install it, e.g.: sudo apt install -y ffmpeg   (Debian/Ubuntu)"
  echo "             or:  brew install ffmpeg          (macOS)"
fi

echo "==> Run runtime check"
"$PYTHON" -m singing_app.main check-runtime || true

echo
echo "Environment setup finished."
echo "Start the web UI with: bash run_singing_web.sh"
echo
echo "Note: Applio toolkit and RVC model files (.pth/.index) are large local"
echo "runtime assets and are not stored in GitHub. If the runtime check reports"
echo "them missing, copy those assets into the paths shown above."

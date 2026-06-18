#!/usr/bin/env bash
# Set up CosyVoice 2 as an optional voice-cloning TTS engine for AIMusic.
#
# CosyVoice clones a voice from a short reference recording (zero-shot), giving
# genuinely distinct character voices instead of a fixed Edge TTS preset. It is
# a large external runtime asset (repo + model ~6 GB), so it is NOT committed to
# git — this script reproduces the install.
#
# Mirror-friendly for China: code from GitHub (with retries), Python deps from
# the Tsinghua PyPI mirror, model weights from ModelScope. Override via env:
#   PIP_INDEX     pip index (default Tsinghua)
#   GIT_RETRIES   clone/submodule retry count (default 12)
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CVROOT="${AI_SINGING_COSYVOICE_ROOT:-$ROOT/tools/CosyVoice}"
PIP_INDEX="${PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
GIT_RETRIES="${GIT_RETRIES:-12}"
PYTORCH_INDEX="${PYTORCH_INDEX:-https://download.pytorch.org/whl/cu128}"

command -v uv >/dev/null 2>&1 || { echo "uv is required (https://docs.astral.sh/uv/)"; exit 1; }

retry() {  # retry <n> <cmd...>
  local n="$1"; shift
  for i in $(seq 1 "$n"); do
    echo "=== attempt $i: $* ==="
    if timeout 200 "$@"; then return 0; fi
    echo "attempt $i failed, retrying..."; sleep 2
  done
  return 1
}

echo "== 1/4 clone CosyVoice code =="
if [ -d "$CVROOT/.git" ]; then
  echo "repo present at $CVROOT"
else
  retry "$GIT_RETRIES" git clone --depth 1 https://github.com/FunAudioLLM/CosyVoice "$CVROOT" \
    || { echo "clone failed"; exit 1; }
fi
( cd "$CVROOT" && retry "$GIT_RETRIES" git submodule update --init --recursive ) \
  || echo "WARN: submodule (Matcha-TTS) not fully fetched"

echo "== 2/4 create isolated venv =="
# Use a Python with the lzma module (audio loading needs it).
PY="${AI_SINGING_COSYVOICE_BASE_PYTHON:-python3}"
[ -x "$CVROOT/.venv/bin/python" ] || uv venv --python "$PY" "$CVROOT/.venv"
VENV="$CVROOT/.venv/bin/python"
"$VENV" -c "import lzma" 2>/dev/null || echo "WARN: venv Python lacks _lzma; audio loading may fail"

echo "== 3/4 install deps =="
uv pip install --python "$VENV" --index-url "$PIP_INDEX" setuptools wheel pip
uv pip install --python "$VENV" --index-url "$PYTORCH_INDEX" torch==2.7.1 torchaudio==2.7.1
# Inference-only subset of CosyVoice requirements (drops server/UI/training extras
# and torch pins so the cu128 build above is kept).
uv pip install --python "$VENV" --index-url "$PIP_INDEX" --extra-index-url https://pypi.org/simple \
  modelscope conformer diffusers==0.29.0 hydra-core==1.3.2 HyperPyYAML==1.2.3 inflect==7.3.1 \
  librosa==0.10.2 lightning==2.2.4 networkx==3.1 numpy==1.26.4 omegaconf==2.3.0 onnx==1.16.0 \
  "onnxruntime-gpu==1.18.0; sys_platform=='linux'" protobuf==4.25 pyarrow==18.1.0 pydantic==2.7.0 \
  pyworld==0.3.4 rich==13.7.1 soundfile==0.12.1 transformers==4.51.3 x-transformers==2.11.24 wetext==0.0.4 \
  gdown==5.1.0 matplotlib==3.7.5 wget==3.2
# openai-whisper is imported by CosyVoice's frontend; install separately so it can
# use the venv's setuptools (its sdist lacks a build-dep declaration).
uv pip install --python "$VENV" --index-url "$PIP_INDEX" --extra-index-url https://pypi.org/simple \
  --no-build-isolation openai-whisper

echo "== 4/4 download CosyVoice2-0.5B model from ModelScope =="
"$VENV" - <<PY
from modelscope import snapshot_download
dst = "$CVROOT/pretrained_models/CosyVoice2-0.5B"
for i in range(1, 11):
    try:
        snapshot_download("iic/CosyVoice2-0.5B", local_dir=dst); print("model OK", dst); break
    except Exception as e:
        print(f"model attempt {i} failed: {e}")
else:
    raise SystemExit("model download failed")
PY

echo "Done. Enable per-job with voice.tts_engine = 'cosyvoice' plus reference_audio + reference_text."

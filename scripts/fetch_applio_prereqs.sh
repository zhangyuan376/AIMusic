#!/usr/bin/env bash
# Download the public Applio/RVC model assets needed for training and inference.
#
# These files (rmvpe pitch model, ContentVec embedder, pretrained base models)
# are NOT private and NOT character-specific. They are required so that ANY user
# can train their own voice and run conversion. They live in the Applio toolkit
# tree, which is a large local runtime asset and is not stored in git.
#
# huggingface.co is unreachable from some regions (e.g. mainland China), so this
# script defaults to the hf-mirror.com mirror. Override with HF_ENDPOINT:
#   HF_ENDPOINT=https://huggingface.co bash scripts/fetch_applio_prereqs.sh
#
# Select sample rate(s) to fetch pretrained base models for (default 40k):
#   SAMPLE_RATES="40k" bash scripts/fetch_applio_prereqs.sh        # default
#   SAMPLE_RATES="32k 40k 48k" bash scripts/fetch_applio_prereqs.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPLIO_ROOT="${AI_SINGING_APPLIO_ROOT:-$ROOT/tools/ApplioV3.6.2}"
HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
SAMPLE_RATES="${SAMPLE_RATES:-40k}"
BASE="$HF_ENDPOINT/IAHispano/Applio/resolve/main/Resources"
MODELS="$APPLIO_ROOT/rvc/models"

if [ ! -d "$APPLIO_ROOT" ]; then
  echo "Applio toolkit not found at: $APPLIO_ROOT" >&2
  echo "Set AI_SINGING_APPLIO_ROOT to its location and retry." >&2
  exit 1
fi

echo "==> Applio root : $APPLIO_ROOT"
echo "==> Mirror      : $HF_ENDPOINT"
echo "==> Sample rates: $SAMPLE_RATES"

# fetch <remote-relative-path> <local-destination>
fetch() {
  local remote="$1" dest="$2"
  if [ -s "$dest" ]; then
    echo "    [skip] $(basename "$dest") already present"
    return 0
  fi
  mkdir -p "$(dirname "$dest")"
  echo "    [get ] $remote"
  curl -L --fail -sS --retry 8 --retry-delay 3 --retry-all-errors -C - \
    -o "$dest" "$BASE/$remote"
}

echo "==> Pitch model (rmvpe)"
fetch "predictors/rmvpe.pt" "$MODELS/predictors/rmvpe.pt"

echo "==> Embedder (ContentVec)"
fetch "embedders/contentvec/pytorch_model.bin" "$MODELS/embedders/contentvec/pytorch_model.bin"
fetch "embedders/contentvec/config.json" "$MODELS/embedders/contentvec/config.json"

echo "==> Pretrained base models (HiFi-GAN)"
for sr in $SAMPLE_RATES; do
  fetch "pretrained_v2/f0G${sr}.pth" "$MODELS/pretraineds/hifi-gan/f0G${sr}.pth"
  fetch "pretrained_v2/f0D${sr}.pth" "$MODELS/pretraineds/hifi-gan/f0D${sr}.pth"
done

echo
echo "Applio prerequisites ready under: $MODELS"

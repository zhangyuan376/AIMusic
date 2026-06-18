"""Standalone CosyVoice 2 zero-shot synthesis runner.

Executed by the CosyVoice virtualenv interpreter (not the app's own Python),
because CosyVoice has a heavy, version-pinned dependency stack that must stay
isolated from the Applio/RVC environment. The app invokes this as a subprocess
and passes a JSON job spec path as argv[1].

Job spec schema:
    {
      "model_dir": "<path to CosyVoice2-0.5B>",
      "cosyvoice_root": "<repo root, for sys.path / third_party>",
      "prompt_wav": "<reference clip to clone>",
      "prompt_text": "<transcript of the reference clip>",
      "items": [{"text": "...", "out": "<output wav path>"}, ...]
    }
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    root = Path(spec["cosyvoice_root"]).resolve()
    # CosyVoice imports assume the repo root is the cwd and Matcha-TTS is on path.
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "third_party" / "Matcha-TTS"))

    import torchaudio
    from cosyvoice.cli.cosyvoice import AutoModel

    model = AutoModel(model_dir=spec["model_dir"])
    prompt_wav = spec["prompt_wav"]
    prompt_text = spec["prompt_text"]

    for item in spec["items"]:
        out = Path(item["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        chunks = list(
            model.inference_zero_shot(
                item["text"], prompt_text, prompt_wav, stream=False
            )
        )
        if not chunks:
            print(f"WARN no audio for {out}", flush=True)
            continue
        # A single block normally yields one chunk; concatenate defensively.
        import torch

        speech = torch.cat([c["tts_speech"] for c in chunks], dim=1)
        torchaudio.save(str(out), speech, model.sample_rate)
        print(f"OK {out}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

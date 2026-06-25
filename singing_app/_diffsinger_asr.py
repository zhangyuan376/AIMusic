"""Whisper ASR for DiffSinger best-of-N seed selection.

Runs in the Applio virtualenv (transformers + torch), invoked by
``DiffSingerAdapter`` on CPU. Transcribes a synthesized clip to Chinese text so
the adapter can score it (in pinyin space) against the target lyrics and keep
the clearest seed. Offline-only (model cached under checkpoints/hf_cache).

Usage: _diffsinger_asr.py <cache_dir> <wav> [<wav> ...]
Prints one ``<basename>\\t<text>`` line per input.
"""

from __future__ import annotations

import os
import sys
import warnings

warnings.filterwarnings("ignore")
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"


def main() -> int:
    cache = sys.argv[1]
    wavs = sys.argv[2:]
    import librosa
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    proc = WhisperProcessor.from_pretrained("openai/whisper-small", cache_dir=cache)
    model = WhisperForConditionalGeneration.from_pretrained(
        "openai/whisper-small", cache_dir=cache
    )
    model.eval()
    forced = proc.get_decoder_prompt_ids(language="zh", task="transcribe")

    for path in wavs:
        wav, _ = librosa.load(path, sr=16000)
        feats = proc(wav, sampling_rate=16000, return_tensors="pt").input_features
        with torch.no_grad():
            ids = model.generate(
                feats, forced_decoder_ids=forced, max_new_tokens=60,
                no_repeat_ngram_size=3, repetition_penalty=1.5, num_beams=5,
            )
        txt = proc.batch_decode(ids, skip_special_tokens=True)[0]
        print(f"{os.path.basename(path)}\t{txt.strip()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

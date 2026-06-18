from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

from singing_app.config import RUNTIME

# F0 estimation runs in the Applio venv (the one with librosa) via a subprocess,
# mirroring separation_models._engine_available: the harness interpreter has no
# librosa, but the tool interpreter does. The probe reads a time budget (seconds)
# then audio paths from argv and prints the median *voiced* F0 (Hz) over all
# collected frames as JSON, or "null" when no voiced audio is found. pyin gives
# a voiced flag (unlike yin), so silent / breathy frames don't skew the median.
_F0_PROBE = r"""
import sys, json
import numpy as np
import librosa

budget = float(sys.argv[1])
collected = []
for path in sys.argv[2:]:
    if budget <= 0:
        break
    try:
        y, sr = librosa.load(path, sr=16000, mono=True, duration=budget)
    except Exception:
        continue
    if y.size == 0:
        continue
    budget -= y.size / sr
    f0, _voiced, _prob = librosa.pyin(y, sr=sr, fmin=65, fmax=1100, frame_length=2048)
    f0 = f0[~np.isnan(f0)]
    if f0.size:
        collected.append(f0)
if not collected:
    print("null")
else:
    print(json.dumps(float(np.median(np.concatenate(collected)))))
"""

# Per-call analysis budget. pyin on ~25s of 16kHz audio runs in a few seconds;
# capping keeps the suggestion responsive even when training samples are long.
_BUDGET_SECONDS = 25.0


def _median_f0(paths: list[Path], python_path: Path) -> float | None:
    args = [str(python_path), "-c", _F0_PROBE, str(_BUDGET_SECONDS)]
    args += [str(p) for p in paths]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=180)
    except Exception:
        return None
    if result.returncode != 0:
        return None
    lines = result.stdout.strip().splitlines()
    if not lines:
        return None
    try:
        value = json.loads(lines[-1])
    except Exception:
        return None
    return float(value) if value else None


def suggest_pitch_shift(
    source_vocals: Path,
    target_paths: list[Path],
    python_path: Path = RUNTIME.tool_python,
) -> dict:
    """Recommend a semitone shift to bring the source song into the voice's range.

    RVC keeps the *source* song's pitch contour and only swaps in the target
    timbre, so a male source covered by a female voice (or vice versa) must be
    transposed or it sounds like the wrong gender. We measure the median voiced
    F0 of both sides and recommend the octave-rounded shift, which matches the
    "+12 for male->female, -12 for female->male, 0 same-gender" rule of thumb and
    is robust to F0 estimation noise. ``semitones_raw`` is returned too so users
    can fine-tune off the octave if they want.
    """
    source_f0 = _median_f0([source_vocals], python_path)
    target_f0 = _median_f0(list(target_paths), python_path)
    if not source_f0 or not target_f0:
        return {
            "ok": False,
            "reason": "无法从音频里提取到稳定音高（可能太短或几乎没有人声）。",
            "source_f0": source_f0,
            "target_f0": target_f0,
        }
    semitones = 12.0 * math.log2(target_f0 / source_f0)
    recommended = max(-24, min(24, int(round(semitones / 12.0) * 12)))
    return {
        "ok": True,
        "source_f0": round(source_f0, 1),
        "target_f0": round(target_f0, 1),
        "semitones_raw": round(semitones, 1),
        "recommended": recommended,
    }

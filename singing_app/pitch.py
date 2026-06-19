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

# Like _F0_PROBE, but reports the voiced-F0 distribution (median + 10th/90th
# percentiles) so callers can reason about pitch *range*, not just center.
_F0_STATS_PROBE = r"""
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
    allf0 = np.concatenate(collected)
    print(json.dumps({
        "median": float(np.median(allf0)),
        "p10": float(np.percentile(allf0, 10)),
        "p90": float(np.percentile(allf0, 90)),
    }))
"""


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


def _f0_stats(paths: list[Path], python_path: Path) -> dict | None:
    args = [str(python_path), "-c", _F0_STATS_PROBE, str(_BUDGET_SECONDS)]
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
        data = json.loads(lines[-1])
    except Exception:
        return None
    return data or None


def decide_pitch_augment(
    paths: list[Path],
    python_path: Path = RUNTIME.tool_python,
    threshold_semitones: float = 7.0,
) -> dict:
    """Decide whether to pitch-augment training material from its f0 spread.

    Speaking voices occupy a narrow pitch band; singing already spans a wide
    range. When the material's voiced-F0 spread (p10..p90) is narrow, the model
    must extrapolate to sing, so augmentation helps; when it is already wide,
    augmentation adds little and just lengthens training. Measurement failure
    assumes speech (augment) — the common case here and the only cost is time.
    """
    stats = _f0_stats([Path(p) for p in paths], python_path)
    if not stats or not stats.get("p10") or not stats.get("p90") or stats["p10"] <= 0:
        return {
            "augment": True,
            "spread_semitones": None,
            "reason": "无法测量音域，按说话声处理（自动增强）",
        }
    spread = 12.0 * math.log2(stats["p90"] / stats["p10"])
    augment = spread < threshold_semitones
    tail = "偏窄（像说话），开启音高增强" if augment else "已较宽（像唱歌），无需增强"
    return {
        "augment": augment,
        "spread_semitones": round(spread, 1),
        "reason": f"音域跨度约 {spread:.1f} 半音，{tail}",
    }


def suggest_formant(recommended_pitch: int) -> dict:
    """Pick conservative formant-shift settings from the auto transpose.

    Applio applies the formant shift to the *source* vocals with ``distortion``
    (formant_timbre) as a spectral-envelope scale: >1 brightens (toward a
    higher/female timbre), <1 darkens (toward male). A large transpose means a
    cross-gender cover, where a gentle nudge in the transpose direction reduces
    the residual "wrong gender" impression; same-register covers need none. The
    strength is kept mild because the ideal value is ear-dependent — expert mode
    can override.
    """
    if abs(recommended_pitch) < 12:
        return {"formant_shifting": False, "formant_qfrency": 1.0, "formant_timbre": 1.0}
    octaves = recommended_pitch / 12.0
    if octaves > 0:
        timbre = min(1.3, 1.0 + 0.25 * octaves)
    else:
        timbre = max(0.8, 1.0 + 0.2 * octaves)
    return {
        "formant_shifting": True,
        "formant_qfrency": 1.0,
        "formant_timbre": round(timbre, 2),
    }

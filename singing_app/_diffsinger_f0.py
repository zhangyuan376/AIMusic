"""f0 extraction for the DiffSinger cover pipeline (RMVPE via Applio).

Runs in the Applio virtualenv (its RMVPE predictor + torch stack), invoked by
``DiffSingerAdapter`` as a subprocess on CPU (CUDA_VISIBLE_DEVICES=""). Extracts
a 10ms-hop f0 contour from the source vocal, optionally corrects octave jumps,
interpolates unvoiced gaps to a continuous contour, and writes
``{f0_timestep, f0_seq}`` JSON for ``_diffsinger_synth.py``.

Usage: _diffsinger_f0.py <vocal.wav> <out.json> <applio_root> <rmvpe.pt>
Env: OCTAVE_FIX=1 (default) enable octave correction; 0 = raw RMVPE.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np


def _roll_median(x, win):
    n = len(x)
    out = np.full(n, np.nan)
    half = win // 2
    for i in range(n):
        seg = x[max(0, i - half):min(n, i + half + 1)]
        seg = seg[~np.isnan(seg)]
        if seg.size:
            out[i] = np.median(seg)
    return out


def octave_correct(f0):
    """Snap voiced frames sitting ~>=1 octave off a rolling-median reference.
    RMVPE on breathy/slow notes occasionally doubles (or halves) the pitch; those
    frames blow past the voicebank range and smear the synthesis. Works in log2,
    iterates so the median de-contaminates, then a short median filter kills 1-2
    frame spikes. Genuine vibrato (<2 semitones) is untouched."""
    lf = np.log2(np.where(f0 > 0, f0, np.nan))
    n_fixed = 0
    for win in (61, 41, 31):
        ref = _roll_median(lf, win)
        for i in range(len(lf)):
            if np.isnan(lf[i]) or np.isnan(ref[i]):
                continue
            k = round(lf[i] - ref[i])
            if abs(k) >= 1:
                lf[i] -= k
                n_fixed += 1
    sm = _roll_median(lf, 5)
    lf = np.where(~np.isnan(sm), sm, lf)
    out = np.where(np.isnan(lf), 0.0, np.power(2.0, lf))
    return out, n_fixed


def main() -> int:
    wav_path, out_path, applio_root, model = sys.argv[1:5]
    sys.path.insert(0, applio_root)
    import librosa
    from rvc.lib.predictors.RMVPE import RMVPE0Predictor

    octave_fix = os.environ.get("OCTAVE_FIX", "1") != "0"
    audio, _ = librosa.load(wav_path, sr=16000, mono=True)
    pred = RMVPE0Predictor(model, device="cpu")
    f0 = np.asarray(pred.infer_from_audio(audio, thred=0.03), float)  # 10ms hop

    n_fixed = 0
    if octave_fix:
        f0, n_fixed = octave_correct(f0)

    voiced = f0 > 0
    if voiced.any():
        idx = np.arange(len(f0))
        f0 = np.interp(idx, idx[voiced], f0[voiced])
    else:
        f0[:] = 220.0

    json.dump(
        {"f0_timestep": 0.01, "f0_seq": " ".join(f"{x:.3f}" for x in f0)},
        open(out_path, "w"),
    )
    print(
        f"f0 frames={len(f0)} range[{f0.min():.1f},{f0.max():.1f}] "
        f"median={float(np.median(f0)):.1f} octave_fix={'on' if octave_fix else 'off'} "
        f"fixed={n_fixed} -> {out_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

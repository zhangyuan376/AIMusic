"""DiffSinger (Qixuan v2.7.0 OpenUTAU ONNX) synthesis bridge.

Runs in the DiffSinger virtualenv (onnxruntime + pypinyin + torch), invoked by
``DiffSingerAdapter`` as a subprocess. Two subcommands:

  g2p  <lyrics_file> <out_lab>
      Chinese lyrics -> space-separated toneless pinyin syllables (.lab for SOFA
      forced alignment). Keeps only CJK characters.

  synth <spec.json>
      Build the per-phoneme spec from SOFA's transcriptions.csv + an f0 contour,
      then drive Qixuan variance(breathiness/voicing) + acoustic -> mel ->
      NSF-HiFiGAN vocoder -> wav. Pitch is GIVEN (from the source vocal's f0),
      so the cover keeps the original melody and only the phonemes change.

``synth`` spec schema (all paths absolute)::

    {
      "trans_csv": "<SOFA transcriptions.csv>",
      "f0_json":   "<{f0_timestep, f0_seq}>",
      "voicebank": "<Qixuan_*_DiffSinger_OpenUtau dir>",
      "vocoder":   "<pc_nsf_hifigan_*.onnx>",
      "out":       "<output wav>",
      "seed": 7, "depth": 0.3, "steps": 100, "velocity": 0.85,
      "min_c": 0.05, "min_v": 0.09, "max_c": 0.13
    }
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from pathlib import Path

import numpy as np

SR, HOP = 44100, 512
HEAD = TAIL = 8  # OpenUTAU head/tail SP padding frames

# opencpop-extension (SOFA dictionary) notation -> Qixuan voicebank notation.
# SOFA emits ye->"y E" / yan->"y En"; Qixuan uses the standard finals ie/ian and
# has no E/En, so without this remap any line with 也/夜/言/烟/眼... crashes.
PH_REMAP = {"E": "ie", "En": "ian"}

CONS = set("b p m f d t n l g k h j q x zh ch sh r z c s y w".split())
SPECIAL = {"AP", "SP", "EP", "GS"}


# --------------------------------------------------------------------------- #
# g2p
# --------------------------------------------------------------------------- #
def cmd_g2p(lyrics_file: str, out_lab: str) -> int:
    from pypinyin import Style, lazy_pinyin

    text = Path(lyrics_file).read_text(encoding="utf-8")
    han = re.findall(r"[一-鿿]", text)
    py = lazy_pinyin("".join(han), style=Style.NORMAL)
    Path(out_lab).write_text(" ".join(py), encoding="utf-8")
    print(f"g2p chars={len(han)} syllables={len(py)} -> {out_lab}")
    return 0


def cmd_g2p_lines(lyrics_file: str) -> int:
    """Per-line g2p: print one stdout line of space-joined toneless pinyin per
    non-empty lyrics line. Lets the adapter keep the lyric line -> sung-phrase
    structure so it can align the song phrase-by-phrase (whole-song SOFA force
    alignment drifts badly on 5-min audio; short phrases stay accurate)."""
    from pypinyin import Style, lazy_pinyin

    text = Path(lyrics_file).read_text(encoding="utf-8")
    for line in text.splitlines():
        han = re.findall(r"[一-鿿]", line)
        if not han:
            continue
        py = lazy_pinyin("".join(han), style=Style.NORMAL)
        print(" ".join(py))
    return 0


# --------------------------------------------------------------------------- #
# build spec (SOFA transcriptions.csv + f0 -> ph_seq/ph_dur/f0_seq)
# --------------------------------------------------------------------------- #
def _floors(ph, min_c, min_v):
    out = []
    for p in ph:
        if p in SPECIAL:
            out.append(0.0)
        else:
            out.append(min_c if p in CONS else min_v)
    return out


def build_spec(trans_csv, f0_json, min_c, min_v, max_c):
    """SOFA sometimes collapses an onset/vowel to ~3ms (drops the sound) or
    stretches a consonant absurdly. Enforce per-phoneme floors (and an optional
    consonant ceiling), redistributing the borrowed time across the remaining
    phones so the segment total -- and thus f0 alignment -- stays constant."""
    rows = list(csv.DictReader(open(trans_csv)))
    assert rows, "empty transcriptions.csv"
    r = rows[0]
    ph = r["ph_seq"].split()
    du = [float(x) for x in r["ph_dur"].split()]
    total0 = sum(du)
    floors = _floors(ph, min_c, min_v)

    fixed = [None] * len(ph)
    for i, (p, d, fl) in enumerate(zip(ph, du, floors)):
        if p in SPECIAL:
            fixed[i] = d
        elif d < fl:
            fixed[i] = fl
        elif max_c > 0 and p in CONS and d > max_c:
            fixed[i] = max_c
    free_idx = [i for i in range(len(ph)) if fixed[i] is None]
    sum_fixed = sum(v for v in fixed if v is not None)
    remaining = total0 - sum_fixed
    sum_free = sum(du[i] for i in free_idx)
    adj = list(du)
    if free_idx and remaining > 0 and sum_free > 0:
        for i in range(len(ph)):
            adj[i] = fixed[i] if fixed[i] is not None else du[i] * remaining / sum_free
    else:
        print(f"WARN: cannot redistribute (free={len(free_idx)} remaining={remaining:.3f})")

    f0 = json.load(open(f0_json))
    return {
        "ph_seq": " ".join(ph),
        "ph_dur": " ".join(f"{x:.5f}" for x in adj),
        "f0_seq": f0["f0_seq"],
        "f0_timestep": f0["f0_timestep"],
    }


# --------------------------------------------------------------------------- #
# synth
# --------------------------------------------------------------------------- #
def _make_session(path, so, ort, onnx, seed):
    """Build an ORT session. If ``seed`` is not None, inject a fixed ``seed``
    attribute into the model's RandomNormalLike nodes so the diffusion initial
    noise x_T is reproducible -- DiffSinger's ONNX sampler is deterministic given
    x_T, so pinning that one node pins the whole output (otherwise it varies
    wildly run to run)."""
    if seed is None:
        return ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
    m = onnx.load(path)
    for n in m.graph.node:
        if n.op_type == "RandomNormalLike":
            keep = [a for a in n.attribute if a.name != "seed"]
            del n.attribute[:]
            n.attribute.extend(keep)
            n.attribute.append(onnx.helper.make_attribute("seed", float(seed)))
    return ort.InferenceSession(m.SerializeToString(), so, providers=["CPUExecutionProvider"])


def _ph_to_token_lang(ph_list, phmap, lgmap):
    tokens, langs = [], []
    for p in ph_list:
        if p in phmap:  # global phones: AP/SP/EP/GS
            tokens.append(phmap[p])
            langs.append(0)
        else:
            p = PH_REMAP.get(p, p)
            key = "zh/" + p
            if key not in phmap:
                raise KeyError(f"phoneme {p!r} (-> {key!r}) not in voicebank")
            tokens.append(phmap[key])
            langs.append(lgmap["zh"])
    return np.array(tokens, np.int64), np.array(langs, np.int64)


def cmd_synth(spec_path: str) -> int:
    import onnx
    import onnxruntime as ort
    import soundfile as sf

    job = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    vb = Path(job["voicebank"])
    seed = job.get("seed")
    steps = int(job.get("steps", 100))
    var_steps = int(job.get("var_steps", 50))
    depth = float(job.get("depth", 0.3))
    velocity = float(job.get("velocity", 0.85))

    spec = build_spec(
        job["trans_csv"], job["f0_json"],
        float(job.get("min_c", 0.05)), float(job.get("min_v", 0.09)),
        float(job.get("max_c", 0.13)),
    )
    ph_list = spec["ph_seq"].split()
    dur_sec = np.array(spec["ph_dur"].split(), "float")
    f0_seq = np.array(spec["f0_seq"].split(), "float")
    f0_ts = float(spec["f0_timestep"])

    ph_acc = np.round(np.add.accumulate(dur_sec) * SR / HOP).astype(np.int64)
    durations = np.diff(ph_acc, prepend=0).astype(np.int64)

    dt = HOP / SR
    body_frames = int(durations.sum())
    f0_t = f0_ts * np.arange(len(f0_seq))
    tgt_t = np.arange(body_frames) * dt
    f0_body = np.interp(tgt_t, f0_t, f0_seq).astype(np.float32)

    ph_list = ["SP"] + ph_list + ["SP"]
    durations = np.concatenate([[HEAD], durations, [TAIL]]).astype(np.int64)
    f0 = np.concatenate(
        [np.full(HEAD, f0_body[0]), f0_body, np.full(TAIL, f0_body[-1])]
    ).astype(np.float32)
    n_frames = int(durations.sum())

    acoustic = str(vb / "0101_qixuan_muon1_acoustic.qixuan.onnx")
    a_phon = json.load(open(vb / "0101_qixuan_muon1_acoustic.phonemes.json"))
    a_lang = json.load(open(vb / "0101_qixuan_muon1_acoustic.languages.json"))
    ling = str(vb / "dsvariance/0102_qixuan_muon1_multivar.qixuan.linguistic.onnx")
    var = str(vb / "dsvariance/0102_qixuan_muon1_multivar.qixuan.variance.onnx")
    v_phon = json.load(open(vb / "dsvariance/0102_qixuan_muon1_multivar.phonemes.json"))
    v_lang = json.load(open(vb / "dsvariance/0102_qixuan_muon1_multivar.languages.json"))

    so = ort.SessionOptions()
    # distinct per-model seed offsets so the two diffusion models don't share noise
    s_ling = None if seed is None else float(seed) + 0
    s_var = None if seed is None else float(seed) + 1
    s_aco = None if seed is None else float(seed) + 2

    # ---- variance: breathiness + voicing ----
    v_tokens, v_langs = _ph_to_token_lang(ph_list, v_phon, v_lang)
    ling_sess = _make_session(ling, so, ort, onnx, s_ling)
    var_sess = _make_session(var, so, ort, onnx, s_var)
    enc = ling_sess.run(None, {
        "tokens": v_tokens[None], "languages": v_langs[None], "ph_dur": durations[None],
    })[0]
    zeros_f = np.zeros((1, n_frames), np.float32)
    retake = np.ones((1, n_frames, 2), bool)
    # variance wants pitch in SEMITONES (MIDI tone), not Hz (acoustic gets Hz)
    pitch_semi = (12.0 * np.log2(f0 / 440.0) + 69.0).astype(np.float32)
    vout = var_sess.run(None, {
        "encoder_out": enc, "ph_dur": durations[None], "pitch": pitch_semi[None],
        "breathiness": zeros_f, "voicing": zeros_f, "retake": retake,
        "steps": np.array(var_steps, np.int64),
    })
    breathiness_pred, voicing_pred = vout[0], vout[1]

    # ---- acoustic -> mel ----
    a_tokens, a_langs = _ph_to_token_lang(ph_list, a_phon, a_lang)
    aco = _make_session(acoustic, so, ort, onnx, s_aco)
    mel = aco.run(None, {
        "tokens": a_tokens[None], "languages": a_langs[None], "durations": durations[None],
        "f0": f0[None], "breathiness": breathiness_pred, "voicing": voicing_pred,
        "gender": np.zeros((1, n_frames), np.float32),
        "velocity": np.full((1, n_frames), velocity, np.float32),
        "depth": np.array(depth, np.float32), "steps": np.array(steps, np.int64),
    })[0]

    # ---- vocoder (mel_base=e, matches Qixuan) ----
    voc = ort.InferenceSession(job["vocoder"], so, providers=["CPUExecutionProvider"])
    y = voc.run(None, {"mel": mel.astype(np.float32), "f0": f0[None]})[0].reshape(-1)

    out = Path(job["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), y, SR)
    print(f"synth n_ph={len(ph_list)} n_frames={n_frames} ({len(y)/SR:.2f}s) seed={seed} -> {out}")
    return 0


def cmd_score(lab_file: str, asr_text: str) -> int:
    """Pinyin-space exact-syllable match of an ASR transcription against the
    target .lab (space-separated toneless pinyin). Prints just the match count
    so best-of-N seed selection can parse ``<exact>/<total>`` from stdout.
    Toneless pinyin space means homophone substitutions by the ASR don't count
    as errors."""
    import difflib

    from pypinyin import Style, lazy_pinyin

    target = Path(lab_file).read_text(encoding="utf-8").split()
    if re.search(r"[一-鿿]", asr_text):
        han = re.findall(r"[一-鿿]", asr_text)
        hyp = lazy_pinyin("".join(han), style=Style.NORMAL)
    else:
        hyp = asr_text.split()
    sm = difflib.SequenceMatcher(a=target, b=hyp, autojunk=False)
    exact = sum(i2 - i1 for tag, i1, i2, _, _ in sm.get_opcodes() if tag == "equal")
    print(f"{exact}/{len(target)}")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: _diffsinger_synth.py {g2p|synth|score} ...", file=sys.stderr)
        return 2
    mode = sys.argv[1]
    if mode == "g2p":
        return cmd_g2p(sys.argv[2], sys.argv[3])
    if mode == "g2p_lines":
        return cmd_g2p_lines(sys.argv[2])
    if mode == "synth":
        return cmd_synth(sys.argv[2])
    if mode == "score":
        return cmd_score(sys.argv[2], sys.argv[3])
    print(f"unknown mode: {mode}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

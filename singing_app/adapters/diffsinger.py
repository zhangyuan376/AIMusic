from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from singing_app.adapters.command import run_command
from singing_app.config import RUNTIME

# DiffSinger ONNX inference is local (no HF download at runtime); RMVPE/Whisper
# weights are already on disk. Force CPU for the f0/SOFA/ASR helpers -- the GPU
# is reserved for RVC and these are light enough on CPU.
_CPU_ENV = {"CUDA_VISIBLE_DEVICES": ""}

# Bridge scripts live alongside the app package; each runs in the venv that owns
# its heavy deps (DiffSinger venv for synth/g2p/score, Applio venv for f0/ASR).
_PKG = Path(__file__).resolve().parents[1]
_SYNTH_BRIDGE = _PKG / "_diffsinger_synth.py"
_F0_BRIDGE = _PKG / "_diffsinger_f0.py"
_ASR_BRIDGE = _PKG / "_diffsinger_asr.py"


class DiffSingerAdapter:
    """Lyric-driven singing synthesis for per-character pronunciation control.

    Re-sings the original song with the user's (corrected) lyrics while keeping
    the original melody and rhythm: the source vocal's f0 (RMVPE) and per-phoneme
    timing (SOFA forced alignment of the lyrics onto the vocal) drive a Qixuan
    DiffSinger voicebank, which synthesizes a clean vocal whose phonemes are
    exactly what the lyrics specify. That clean vocal is then handed to RVC to
    take on the user's trained voice timbre.

    Spans three isolated venvs, so the adapter orchestrates several subprocess
    calls rather than one: g2p + synth + score in the DiffSinger venv, f0 + ASR
    in the Applio venv, forced alignment in the SOFA venv.

    best-of-N: DiffSinger's diffusion is reproducible once its noise seed is
    pinned, but different seeds render different syllables more clearly with no
    single seed best everywhere. With more than one seed, each candidate is
    transcribed (Whisper) and scored in pinyin space against the lyrics; the
    clearest wins. A single seed skips ASR entirely (fast, deterministic).
    """

    def __init__(
        self,
        diffsinger_python: Path = None,  # resolved lazily so env overrides apply
        applio_python: Path = None,
        sofa_python: Path = None,
        ffmpeg_path: Path = RUNTIME.ffmpeg,
    ) -> None:
        self.diffsinger_python = diffsinger_python or RUNTIME.diffsinger_python
        self.applio_python = applio_python or RUNTIME.applio_python
        self.sofa_python = sofa_python or RUNTIME.sofa_python
        self.ffmpeg_path = ffmpeg_path

    def available(self) -> bool:
        return (
            self.diffsinger_python.exists()
            and self.sofa_python.exists()
            and (RUNTIME.sofa_root / "infer.py").exists()
            and RUNTIME.diffsinger_voicebank.exists()
            and RUNTIME.diffsinger_vocoder.exists()
            and RUNTIME.sofa_ckpt.exists()
        )

    def synthesize_clean_vocals(
        self,
        source_vocals: Path,
        lyrics: str,
        output_path: Path,
        log_path: Path,
        seeds: list[int] | None = None,
        depth: float = 0.3,
        steps: int = 100,
        velocity: float = 0.85,
        min_c: float = 0.09,
        min_v: float = 0.14,
        max_c: float = 0.22,
        dry_run: bool = False,
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        seeds = [int(s) for s in (seeds or [7])]
        source_vocals = Path(source_vocals).resolve()
        work = Path(tempfile.mkdtemp(prefix="diffsinger_", dir=str(output_path.parent)))

        if dry_run:
            self._g2p(work / "lyrics.txt", work / "seg.lab", log_path, lyrics, dry_run=True)
            self._extract_f0(source_vocals, work / "f0.json", log_path, dry_run=True)
            self._align(source_vocals, work / "seg.lab", work, log_path, dry_run=True)
            self._synth(work, work / "trans.csv", work / "f0.json", output_path,
                        seeds[0], depth, steps, velocity, min_c, min_v, max_c,
                        log_path, dry_run=True)
            return output_path

        if not lyrics.strip():
            raise ValueError("歌词为空，无法合成。请填写这首歌的歌词。")

        # 1) lyrics -> pinyin .lab
        lab = work / "seg.lab"
        self._g2p(work / "lyrics.txt", lab, log_path, lyrics, dry_run=False)

        # 2) source vocal f0 (Applio RMVPE, CPU)
        f0_json = work / "f0.json"
        self._extract_f0(source_vocals, f0_json, log_path, dry_run=False)

        # 3) forced alignment -> transcriptions.csv (SOFA venv). Align phrase by
        #    phrase: whole-song force alignment drifts badly on full-length audio.
        try:
            trans_csv = self._align_phrases(
                source_vocals, work / "lyrics.txt", f0_json, work, log_path)
        except Exception as exc:  # noqa: BLE001 -- fall back to whole-song align
            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"phrase-align failed ({exc}); falling back to whole-song\n")
            trans_csv = self._align(source_vocals, lab, work, log_path, dry_run=False)

        # 4) synth each seed; pick the clearest via ASR when more than one
        candidates = []
        for seed in seeds:
            cand = work / f"synth_{seed}.wav"
            self._synth(work, trans_csv, f0_json, cand, seed, depth, steps,
                        velocity, min_c, min_v, max_c, log_path, dry_run=False)
            candidates.append((seed, cand))

        best = candidates[0][1]
        if len(candidates) > 1:
            best = self._select_best(candidates, lab, log_path)

        # 5) normalize for the RVC stage (mono 44.1k s16)
        run_command(
            [str(self.ffmpeg_path), "-y", "-i", str(best),
             "-ar", "44100", "-ac", "1", "-sample_fmt", "s16", str(output_path)],
            cwd=RUNTIME.app_root, log_path=log_path, dry_run=False,
        )
        shutil.rmtree(work, ignore_errors=True)
        return output_path

    # ----- pipeline stages ------------------------------------------------- #
    def _g2p(self, lyrics_file, lab, log_path, lyrics, dry_run):
        if not dry_run:
            lyrics_file.write_text(lyrics, encoding="utf-8")
        run_command(
            [str(self.diffsinger_python), str(_SYNTH_BRIDGE), "g2p",
             str(lyrics_file), str(lab)],
            cwd=RUNTIME.app_root, log_path=log_path, dry_run=dry_run,
        )

    def _extract_f0(self, vocals, f0_json, log_path, dry_run):
        run_command(
            [str(self.applio_python), str(_F0_BRIDGE), str(vocals), str(f0_json),
             str(RUNTIME.applio_root), str(RUNTIME.applio_rmvpe)],
            cwd=RUNTIME.app_root, log_path=log_path, dry_run=dry_run, env=_CPU_ENV,
        )

    def _align(self, vocals, lab, work, log_path, dry_run) -> Path:
        """SOFA infer.py force-aligns one folder of <name>.wav + <name>.lab pairs
        and writes transcriptions.csv next to them. cwd must be the SOFA repo so
        its relative ckpt/dictionary paths resolve."""
        sofa_dir = work / "sofa"
        trans_csv = work / "trans.csv"
        if not dry_run:
            sofa_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(vocals, sofa_dir / "seg.wav")
            shutil.copy(lab, sofa_dir / "seg.lab")
        self._run_sofa(sofa_dir, log_path, dry_run)
        if dry_run:
            return trans_csv
        produced = next(sofa_dir.rglob("transcriptions.csv"), None)
        if produced is None:
            raise FileNotFoundError(
                f"SOFA 未生成 transcriptions.csv（{sofa_dir}），请查看日志 {log_path}。"
            )
        shutil.copy(produced, trans_csv)
        return trans_csv

    def _run_sofa(self, sofa_dir, log_path, dry_run):
        run_command(
            [str(self.sofa_python), "infer.py",
             "--ckpt", str(RUNTIME.sofa_ckpt.resolve()),
             "--folder", str(Path(sofa_dir).resolve()),
             "--mode", "force", "--g2p", "Dictionary",
             "--dictionary", str(RUNTIME.sofa_dictionary.resolve()),
             "--out_formats", "trans"],
            cwd=RUNTIME.sofa_root, log_path=log_path, dry_run=dry_run, env=_CPU_ENV,
        )

    # ----- phrase-by-phrase forced alignment ------------------------------- #
    # Whole-song SOFA force alignment drifts badly on 5-min audio (it mislabels
    # long stretches as silence and shoves words seconds out of place, collapsing
    # most phonemes). SOFA is accurate on short clips, so we walk the song one
    # lyric phrase at a time: align each phrase inside a short window anchored at
    # where the previous phrase ended (self-correcting), then stitch every
    # phrase's phonemes back onto the absolute timeline with SP filling the gaps.
    _TARGET_SYL = 10   # group lyric lines into chunks of at least this many syllables
    _BACK = 0.3        # seconds of audio to include before the running cursor
    _SPECIAL = {"AP", "SP", "EP", "GS"}

    def _align_phrases(self, vocals, lyrics_file, f0_json, work, log_path) -> Path:
        import json

        out = self._capture(
            [str(self.diffsinger_python), str(_SYNTH_BRIDGE), "g2p_lines",
             str(lyrics_file)],
            cwd=RUNTIME.app_root,
        )
        lines = [ln.split() for ln in out.splitlines() if ln.strip()]
        if not lines:
            raise ValueError("g2p_lines 未产出任何音节")

        # group consecutive lyric lines into ~_TARGET_SYL-syllable chunks
        chunks, cur = [], []
        for syls in lines:
            cur.extend(syls)
            if len(cur) >= self._TARGET_SYL:
                chunks.append(cur)
                cur = []
        if cur:
            chunks.append(cur)

        f0 = json.loads(Path(f0_json).read_text(encoding="utf-8"))
        total_dur = len(f0["f0_seq"].split()) * float(f0["f0_timestep"])
        total_syl = sum(len(c) for c in chunks)
        sec_per_syl = total_dur / max(1, total_syl)

        align_root = work / "phrases"
        align_root.mkdir(parents=True, exist_ok=True)
        ph_seq, ph_dur = [], []
        prev_end, cursor = 0.0, 0.0
        for ci, syls in enumerate(chunks):
            est = len(syls) * sec_per_syl
            w0 = max(0.0, cursor - self._BACK)
            w1 = min(total_dur, cursor + est + max(2.5, est * 0.7))
            cdir = align_root / f"c{ci}"
            cdir.mkdir(parents=True, exist_ok=True)
            run_command(
                [str(self.ffmpeg_path), "-y", "-ss", f"{w0:.3f}", "-t",
                 f"{max(0.1, w1 - w0):.3f}", "-i", str(vocals),
                 "-ar", "44100", "-ac", "1", str(cdir / "seg.wav")],
                cwd=RUNTIME.app_root, log_path=log_path, dry_run=False,
            )
            (cdir / "seg.lab").write_text(" ".join(syls), encoding="utf-8")
            self._run_sofa(cdir, log_path, dry_run=False)
            produced = next(cdir.rglob("transcriptions.csv"), None)
            if produced is None:
                raise FileNotFoundError(f"SOFA 未对齐第 {ci} 句（{cdir}）")

            ph, du = self._read_trans(produced)
            reals = [i for i, p in enumerate(ph) if p not in self._SPECIAL]
            if not reals:  # SOFA heard only silence here; keep the timeline moving
                cursor = min(total_dur, cursor + est)
                continue
            starts, t = [], 0.0
            for d in du:
                starts.append(t)
                t += d
            first, last = reals[0], reals[-1]
            first_abs = w0 + starts[first]
            last_abs = w0 + starts[last] + du[last]

            gap = first_abs - prev_end
            if gap > 0.02:
                ph_seq.append("SP")
                ph_dur.append(gap)
            for i in range(first, last + 1):
                ph_seq.append(ph[i])
                ph_dur.append(du[i])
            prev_end = last_abs
            cursor = last_abs

        tail = total_dur - prev_end
        if tail > 0.02:
            ph_seq.append("SP")
            ph_dur.append(tail)

        trans_csv = work / "trans.csv"
        self._write_trans(trans_csv, ph_seq, ph_dur)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"phrase-align chunks={len(chunks)} n_ph={len(ph_seq)} "
                    f"span={prev_end:.1f}/{total_dur:.1f}s -> {trans_csv}\n")
        return trans_csv

    @staticmethod
    def _read_trans(csv_path):
        import csv as _csv

        row = list(_csv.DictReader(open(csv_path)))[0]
        return row["ph_seq"].split(), [float(x) for x in row["ph_dur"].split()]

    @staticmethod
    def _write_trans(csv_path, ph_seq, ph_dur):
        import csv as _csv

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(["name", "word_seq", "word_dur", "ph_seq", "ph_dur"])
            w.writerow(["song", "SP", f"{sum(ph_dur):.5f}",
                        " ".join(ph_seq), " ".join(f"{d:.5f}" for d in ph_dur)])


    def _synth(self, work, trans_csv, f0_json, out, seed, depth, steps, velocity,
               min_c, min_v, max_c, log_path, dry_run):
        import json

        spec = {
            "trans_csv": str(trans_csv), "f0_json": str(f0_json),
            "voicebank": str(RUNTIME.diffsinger_voicebank),
            "vocoder": str(RUNTIME.diffsinger_vocoder),
            "out": str(out), "seed": seed, "depth": depth, "steps": steps,
            "velocity": velocity, "min_c": min_c, "min_v": min_v, "max_c": max_c,
        }
        spec_path = Path(work) / f"spec_{seed}.json"
        if not dry_run:
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
        run_command(
            [str(self.diffsinger_python), str(_SYNTH_BRIDGE), "synth", str(spec_path)],
            cwd=RUNTIME.app_root, log_path=log_path, dry_run=dry_run, env=_CPU_ENV,
        )

    def _select_best(self, candidates, lab, log_path) -> Path:
        """ASR each candidate (Applio/Whisper) and keep the one whose transcription
        scores the most exact pinyin matches against the target lyrics. Falls back
        to the first candidate if ASR/scoring is unavailable."""
        from singing_app.adapters.command import CommandError

        asr_log = log_path.parent / "diffsinger_select.log"
        wavs = [str(c) for _, c in candidates]
        try:
            out = self._capture(
                [str(self.applio_python), str(_ASR_BRIDGE),
                 str(RUNTIME.whisper_cache), *wavs],
                cwd=RUNTIME.app_root, env=_CPU_ENV,
            )
        except (CommandError, OSError):
            return candidates[0][1]

        texts = {}
        for line in out.splitlines():
            if "\t" in line:
                name, txt = line.split("\t", 1)
                texts[name] = txt.strip()

        best_score, best_path = -1, candidates[0][1]
        for seed, cand in candidates:
            txt = texts.get(cand.name, "")
            score = self._score(lab, txt) if txt else -1
            with asr_log.open("a", encoding="utf-8") as f:
                f.write(f"seed={seed} score={score} asr={txt}\n")
            if score > best_score:
                best_score, best_path = score, cand
        return best_path

    def _score(self, lab, asr_text) -> int:
        from singing_app.adapters.command import CommandError

        try:
            out = self._capture(
                [str(self.diffsinger_python), str(_SYNTH_BRIDGE), "score",
                 str(lab), asr_text],
                cwd=RUNTIME.app_root,
            )
        except (CommandError, OSError):
            return -1
        line = out.strip().splitlines()[-1] if out.strip() else ""
        if "/" in line:
            try:
                return int(line.split("/")[0])
            except ValueError:
                return -1
        return -1

    @staticmethod
    def _capture(command, cwd, env=None) -> str:
        import os
        import subprocess

        run_env = dict(os.environ)
        if env:
            run_env.update(env)
        proc = subprocess.run(
            [str(c) for c in command], cwd=str(cwd), env=run_env,
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            from singing_app.adapters.command import CommandError

            raise CommandError(proc.stderr.strip() or "command failed")
        return proc.stdout

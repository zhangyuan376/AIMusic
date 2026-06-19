from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from singing_app.adapters.command import run_command
from singing_app.config import RUNTIME

# HuggingFace is blocked on this machine; route Seed-VC's first-run checkpoint
# download through the mirror, and disable HF Xet (its CAS host
# cas-bridge.xethub.hf.co is not proxied by the mirror and times out).
# Harmless once weights are cached.
_HF_MIRROR = "https://hf-mirror.com"
_HF_ENV = {"HF_ENDPOINT": _HF_MIRROR, "HF_HUB_DISABLE_XET": "1"}


class SeedVcAdapter:
    """Zero-shot singing voice conversion via Seed-VC.

    Unlike RVC (which needs a trained per-voice model), Seed-VC takes the
    source song's separated vocals plus a short reference clip of the target
    voice and converts the timbre with no training. Runs in its own isolated
    venv via the repo's ``inference.py`` CLI; the SVC model (seed-uvit-whisper-
    base) is selected by ``--f0-condition True`` and auto-downloaded on first
    run.
    """

    def __init__(
        self,
        python_path: Path = None,  # resolved lazily so env overrides apply
        seedvc_root: Path = None,
        ffmpeg_path: Path = RUNTIME.ffmpeg,
    ) -> None:
        self.python_path = python_path or RUNTIME.seedvc_python
        self.seedvc_root = seedvc_root or RUNTIME.seedvc_root
        self.ffmpeg_path = ffmpeg_path

    def available(self) -> bool:
        return self.python_path.exists() and (self.seedvc_root / "inference.py").exists()

    def convert_vocals(
        self,
        source_vocals: Path,
        reference_audio: Path,
        output_path: Path,
        log_path: Path,
        semitones: int = 0,
        diffusion_steps: int = 30,
        inference_cfg_rate: float = 0.7,
        dry_run: bool = False,
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # inference.py runs with cwd=seedvc_root, so any relative input path would
        # resolve against the wrong directory. Pin both inputs to absolute paths.
        source_vocals = Path(source_vocals).resolve()
        reference_audio = Path(reference_audio).resolve()
        out_dir = Path(tempfile.mkdtemp(prefix="seedvc_", dir=str(output_path.parent)))
        # f0-condition keeps the source melody; semi-tone-shift transposes for a
        # cross-register cover; auto-f0-adjust off (per Seed-VC docs, not used
        # for singing). diffusion-steps 30 is the lower end of the recommended
        # 30~50 for singing, trading a little quality for speed.
        run_command(
            [
                str(self.python_path),
                str(self.seedvc_root / "inference.py"),
                "--source",
                str(source_vocals),
                "--target",
                str(reference_audio),
                "--output",
                str(out_dir),
                "--f0-condition",
                "True",
                "--auto-f0-adjust",
                "False",
                "--semi-tone-shift",
                str(int(semitones)),
                "--diffusion-steps",
                str(int(diffusion_steps)),
                "--inference-cfg-rate",
                str(inference_cfg_rate),
                "--fp16",
                "True",
            ],
            cwd=self.seedvc_root,
            log_path=log_path,
            dry_run=dry_run,
            env=_HF_ENV,
        )
        if dry_run:
            return output_path

        produced = self._newest_wav(out_dir)
        if produced is None:
            raise FileNotFoundError(
                f"Seed-VC 未在 {out_dir} 生成输出音频，请查看日志 {log_path}。"
            )
        # Normalize to the mix stage's expected format (stereo 44.1k s16).
        run_command(
            [
                str(self.ffmpeg_path),
                "-y",
                "-i",
                str(produced),
                "-ar",
                "44100",
                "-ac",
                "2",
                "-sample_fmt",
                "s16",
                str(output_path),
            ],
            cwd=RUNTIME.app_root,
            log_path=log_path,
            dry_run=dry_run,
        )
        shutil.rmtree(out_dir, ignore_errors=True)
        return output_path

    @staticmethod
    def _newest_wav(directory: Path) -> Path | None:
        wavs = sorted(
            directory.rglob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        return wavs[0] if wavs else None

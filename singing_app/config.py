from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

IS_WINDOWS = os.name == "nt"


def _default_app_root() -> Path:
    override = os.environ.get("AI_SINGING_APP_ROOT")
    if override:
        return Path(override).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


APP_ROOT = _default_app_root()


def _venv_python(venv_dir: Path) -> Path:
    if IS_WINDOWS:
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


@dataclass(frozen=True)
class RuntimePaths:
    app_root: Path = APP_ROOT
    voice_pipeline_root: Path = APP_ROOT / "voice_pipeline"

    @property
    def output_root(self) -> Path:
        """Single root for everything the app produces at runtime.

        Samples/audio/results live under ``projects/``, trained voice models
        under ``models/``, and the library index files sit at the root. Override
        with ``AI_SINGING_OUTPUT_ROOT`` to relocate all products at once.
        """
        override = os.environ.get("AI_SINGING_OUTPUT_ROOT")
        if override:
            return Path(override).resolve()
        return self.app_root / "output"

    @property
    def projects_root(self) -> Path:
        return self.output_root / "projects"

    @property
    def models_root(self) -> Path:
        return self.output_root / "models"

    @property
    def applio_root(self) -> Path:
        override = os.environ.get("AI_SINGING_APPLIO_ROOT")
        if override:
            return Path(override)
        return self.app_root / "tools" / "ApplioV3.6.2"

    @property
    def tool_python(self) -> Path:
        """Python that runs the pip-installable tools (Demucs, Edge TTS).

        These tools are torch-dependent, so prefer the Applio runtime env which
        already ships a coherent torch/torchaudio stack (and GPU support). Fall
        back to the project's own .venv, then the current interpreter, so the
        tools still resolve on machines where Applio is not installed.
        """
        override = os.environ.get("AI_SINGING_PYTHON")
        if override:
            return Path(override)
        candidates = [
            _venv_python(self.applio_root / ".venv"),
            _venv_python(self.applio_root / "env"),
            _venv_python(self.app_root / ".venv"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return Path(sys.executable)

    @property
    def applio_python(self) -> Path:
        """Python that runs the Applio/RVC engine (core.py, training).

        This is the external Applio runtime; it is not pip-installable. When the
        Applio env is absent the expected path is returned so runtime checks
        report it missing instead of silently using the wrong interpreter.
        """
        override = os.environ.get("AI_SINGING_APPLIO_PYTHON")
        if override:
            return Path(override)
        env = self.applio_root / "env"
        applio_venv = self.applio_root / ".venv"
        if IS_WINDOWS:
            candidates = [
                env / "python.exe",
                env / "Scripts" / "python.exe",
                applio_venv / "Scripts" / "python.exe",
            ]
        else:
            candidates = [env / "bin" / "python", applio_venv / "bin" / "python"]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    @property
    def ffmpeg(self) -> Path:
        override = os.environ.get("AI_SINGING_FFMPEG")
        if override:
            return Path(override)
        if IS_WINDOWS:
            return self.applio_root / "ffmpeg.exe"
        found = shutil.which("ffmpeg")
        return Path(found) if found else Path("ffmpeg")

    @property
    def applio_core(self) -> Path:
        return self.applio_root / "core.py"

    @property
    def ffprobe(self) -> Path:
        override = os.environ.get("AI_SINGING_FFPROBE")
        if override:
            return Path(override)
        if IS_WINDOWS:
            return self.applio_root / "ffprobe.exe"
        found = shutil.which("ffprobe")
        return Path(found) if found else Path("ffprobe")

    @property
    def cosyvoice_root(self) -> Path:
        """CosyVoice repo root (external runtime asset, not in git)."""
        override = os.environ.get("AI_SINGING_COSYVOICE_ROOT")
        if override:
            return Path(override)
        return self.app_root / "tools" / "CosyVoice"

    @property
    def cosyvoice_python(self) -> Path:
        """Python for the CosyVoice engine (its own venv, isolated from Applio)."""
        override = os.environ.get("AI_SINGING_COSYVOICE_PYTHON")
        if override:
            return Path(override)
        return _venv_python(self.cosyvoice_root / ".venv")

    @property
    def cosyvoice_model(self) -> Path:
        """CosyVoice2-0.5B model directory."""
        override = os.environ.get("AI_SINGING_COSYVOICE_MODEL")
        if override:
            return Path(override)
        return self.cosyvoice_root / "pretrained_models" / "CosyVoice2-0.5B"

    @property
    def applio_rmvpe(self) -> Path:
        """Pitch-extraction model required for training (extract) and inference."""
        return self.applio_root / "rvc" / "models" / "predictors" / "rmvpe.pt"

    @property
    def applio_contentvec(self) -> Path:
        """ContentVec embedder required for training (extract) and inference."""
        return (
            self.applio_root
            / "rvc"
            / "models"
            / "embedders"
            / "contentvec"
            / "pytorch_model.bin"
        )

    @property
    def hifigan_pretraineds_root(self) -> Path:
        """Where Applio's HiFi-GAN training base models (f0G/f0D) live."""
        return self.applio_root / "rvc" / "models" / "pretraineds" / "hifi-gan"

    @property
    def available_training_sample_rates(self) -> list[int]:
        """Sample rates that have a usable HiFi-GAN base (both f0G and f0D).

        Training with --pretrained True fails without a matching base, so the
        UI must only offer rates whose base weights are present on this machine.
        """
        root = self.hifigan_pretraineds_root
        rates = []
        for sr in (32000, 40000, 48000):
            tag = f"{str(sr)[:2]}k"
            if (root / f"f0G{tag}.pth").exists() and (root / f"f0D{tag}.pth").exists():
                rates.append(sr)
        return rates or [40000]

    @property
    def default_model(self) -> Path:
        return self.voice_pipeline_root / "models" / "pomao_clear_voice_10e_1350s.pth"

    @property
    def default_index(self) -> Path:
        return self.voice_pipeline_root / "models" / "pomao_clear_voice.index"


RUNTIME = RuntimePaths()


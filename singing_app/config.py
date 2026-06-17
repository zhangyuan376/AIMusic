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
    projects_root: Path = APP_ROOT / "singing_app" / "projects"

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
    def default_model(self) -> Path:
        return self.voice_pipeline_root / "models" / "pomao_clear_voice_10e_1350s.pth"

    @property
    def default_index(self) -> Path:
        return self.voice_pipeline_root / "models" / "pomao_clear_voice.index"


RUNTIME = RuntimePaths()


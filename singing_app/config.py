from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _default_app_root() -> Path:
    override = os.environ.get("AI_SINGING_APP_ROOT")
    if override:
        return Path(override).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


APP_ROOT = _default_app_root()


@dataclass(frozen=True)
class RuntimePaths:
    app_root: Path = APP_ROOT
    applio_root: Path = APP_ROOT / "tools" / "ApplioV3.6.2"
    voice_pipeline_root: Path = APP_ROOT / "voice_pipeline"
    projects_root: Path = APP_ROOT / "singing_app" / "projects"

    @property
    def applio_python(self) -> Path:
        return self.applio_root / "env" / "python.exe"

    @property
    def ffmpeg(self) -> Path:
        return self.applio_root / "ffmpeg.exe"

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


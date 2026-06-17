from __future__ import annotations

from pathlib import Path

from singing_app.adapters.command import run_command
from singing_app.config import RUNTIME


class DemucsAdapter:
    def __init__(self, python_path: Path = RUNTIME.tool_python) -> None:
        self.python_path = python_path

    def separate_vocals(
        self,
        input_path: Path,
        output_dir: Path,
        log_path: Path,
        dry_run: bool = False,
    ) -> tuple[Path, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        run_command(
            [
                str(self.python_path),
                "-m",
                "demucs",
                "--two-stems",
                "vocals",
                "-n",
                "htdemucs",
                "--out",
                str(output_dir),
                str(input_path),
            ],
            cwd=RUNTIME.app_root,
            log_path=log_path,
            dry_run=dry_run,
        )
        stem_dir = output_dir / "htdemucs" / input_path.stem
        return stem_dir / "vocals.wav", stem_dir / "no_vocals.wav"


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
        model: str = "htdemucs_ft",
        shifts: int = 2,
        overlap: float = 0.5,
        float32: bool = True,
        dry_run: bool = False,
    ) -> tuple[Path, Path]:
        # Quality-first defaults: htdemucs_ft is the best Demucs v4 model;
        # --shifts averages predictions over random time shifts (test-time
        # augmentation), --overlap reduces chunk-boundary artifacts, and
        # --float32 keeps full precision for the downstream RVC conversion.
        # All of these trade speed for quality, so separation is slower
        # (markedly so on CPU).
        output_dir.mkdir(parents=True, exist_ok=True)
        command = [
            str(self.python_path),
            "-m",
            "demucs",
            "--two-stems",
            "vocals",
            "-n",
            model,
            "--shifts",
            str(shifts),
            "--overlap",
            str(overlap),
        ]
        if float32:
            command.append("--float32")
        command += ["--out", str(output_dir), str(input_path)]
        run_command(
            command,
            cwd=RUNTIME.app_root,
            log_path=log_path,
            dry_run=dry_run,
        )
        stem_dir = output_dir / model / input_path.stem
        return stem_dir / "vocals.wav", stem_dir / "no_vocals.wav"


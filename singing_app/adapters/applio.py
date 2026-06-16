from __future__ import annotations

from pathlib import Path

from singing_app.adapters.command import run_command
from singing_app.config import RUNTIME


class ApplioInferAdapter:
    def __init__(
        self,
        python_path: Path = RUNTIME.applio_python,
        applio_root: Path = RUNTIME.applio_root,
    ) -> None:
        self.python_path = python_path
        self.applio_root = applio_root

    def convert_vocals(
        self,
        input_path: Path,
        output_path: Path,
        model_path: Path,
        index_path: Path,
        log_path: Path,
        pitch: int = 0,
        index_rate: float = 0.25,
        protect: float = 0.45,
        dry_run: bool = False,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        run_command(
            [
                str(self.python_path),
                "core.py",
                "infer",
                "--pitch",
                str(pitch),
                "--index_rate",
                str(index_rate),
                "--volume_envelope",
                "1",
                "--protect",
                str(protect),
                "--f0_method",
                "rmvpe",
                "--input_path",
                str(input_path),
                "--output_path",
                str(output_path),
                "--pth_path",
                str(model_path),
                "--index_path",
                str(index_path),
                "--split_audio",
                "False",
                "--f0_autotune",
                "False",
                "--clean_audio",
                "False",
                "--export_format",
                "WAV",
                "--embedder_model",
                "contentvec",
            ],
            cwd=self.applio_root,
            log_path=log_path,
            dry_run=dry_run,
        )


class ApplioTrainAdapter:
    def __init__(
        self,
        python_path: Path = RUNTIME.applio_python,
        applio_root: Path = RUNTIME.applio_root,
    ) -> None:
        self.python_path = python_path
        self.applio_root = applio_root

    def train(
        self,
        model_name: str,
        dataset_path: Path,
        log_path: Path,
        epochs: int = 10,
        dry_run: bool = False,
    ) -> dict[str, Path]:
        run_command(
            [
                str(self.python_path),
                "mochi_train_direct.py",
                "--stage",
                "all",
                "--dataset",
                str(dataset_path),
                "--model-name",
                model_name,
                "--sample-rate",
                "40000",
                "--cpu-cores",
                "4",
                "--gpu",
                "-",
                "--epochs",
                str(epochs),
                "--batch-size",
                "1",
                "--save-every",
                "5",
            ],
            cwd=self.applio_root,
            log_path=log_path,
            dry_run=dry_run,
        )
        model_dir = self.applio_root / "logs" / model_name
        return {
            "model_dir": model_dir,
            "latest_model": self._latest_file(model_dir, f"{model_name}_*e_*s.pth"),
            "latest_index": self._latest_file(model_dir, "*.index"),
        }

    @staticmethod
    def _latest_file(directory: Path, pattern: str) -> Path:
        if not directory.exists():
            return Path("")
        matches = [path for path in directory.glob(pattern) if path.is_file()]
        if not matches:
            return Path("")
        return max(matches, key=lambda path: path.stat().st_mtime)


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
        index_rate: float = 0.5,
        protect: float = 0.45,
        clean_audio: bool = False,
        clean_strength: float = 0.3,
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
                str(clean_audio),
                "--clean_strength",
                str(clean_strength),
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
        sample_rate: int = 40000,
        gpu: str = "0",
        batch_size: int = 8,
        cpu_cores: int = 4,
        save_every: int = 5,
        f0_method: str = "rmvpe",
        embedder_model: str = "contentvec",
        dry_run: bool = False,
    ) -> dict[str, Path]:
        """Train an RVC model with the stock Applio pipeline.

        Runs the four standard Applio stages (preprocess -> extract -> train ->
        index) via ``core.py`` so any user can train a voice from a folder of
        audio samples without private scripts or pre-trained character weights.
        """
        core = [str(self.python_path), "core.py"]

        run_command(
            core
            + [
                "preprocess",
                "--model_name",
                model_name,
                "--dataset_path",
                str(dataset_path),
                "--sample_rate",
                str(sample_rate),
                "--cpu_cores",
                str(cpu_cores),
                "--cut_preprocess",
                "Automatic",
            ],
            cwd=self.applio_root,
            log_path=log_path,
            dry_run=dry_run,
        )

        run_command(
            core
            + [
                "extract",
                "--model_name",
                model_name,
                "--f0_method",
                f0_method,
                "--sample_rate",
                str(sample_rate),
                "--cpu_cores",
                str(cpu_cores),
                "--gpu",
                gpu,
                "--embedder_model",
                embedder_model,
                "--include_mutes",
                "2",
            ],
            cwd=self.applio_root,
            log_path=log_path,
            dry_run=dry_run,
        )

        run_command(
            core
            + [
                "train",
                "--model_name",
                model_name,
                "--save_every_epoch",
                str(save_every),
                "--save_every_weights",
                "True",
                "--total_epoch",
                str(epochs),
                "--sample_rate",
                str(sample_rate),
                "--batch_size",
                str(batch_size),
                "--gpu",
                gpu,
                "--pretrained",
                "True",
            ],
            cwd=self.applio_root,
            log_path=log_path,
            dry_run=dry_run,
        )

        run_command(
            core
            + [
                "index",
                "--model_name",
                model_name,
                "--index_algorithm",
                "Auto",
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


from __future__ import annotations

import json
from pathlib import Path

from singing_app.adapters.command import run_command
from singing_app.config import RUNTIME

# audio-separator pulls its checkpoints from HuggingFace on first use; route
# through the mirror like the other engines (see adapters/seedvc.py).
_HF_ENV = {"HF_ENDPOINT": "https://hf-mirror.com", "HF_HUB_DISABLE_XET": "1"}


class AudioSeparatorAdapter:
    """Optional post-passes on a separated vocal stem via audio-separator.

    Demucs lumps lead + backing vocals into one "vocals" stem and leaves some
    noise/bleed. This adapter runs torch-based Mel-Band-RoFormer models (GPU via
    torch even though onnxruntime is CPU-only here) to (a) split lead from
    backing vocals so RVC only reshapes the lead, and (b) denoise the vocal.
    Each model runs through a bridge script in the Applio venv (the harness
    interpreter has no audio-separator), mirroring DemucsAdapter.
    """

    # vocals=lead, instrumental=backing harmony.
    KARAOKE_MODEL = "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt"
    # dry=clean signal, other=noise.
    DENOISE_MODEL = "denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt"

    def __init__(self, python_path: Path = None) -> None:
        self.python_path = python_path or RUNTIME.tool_python
        self.model_dir = RUNTIME.audio_separator_models
        self._bridge = Path(__file__).resolve().parent.parent / "_audio_separator_run.py"

    def available(self) -> bool:
        from singing_app.separation_models import _engine_available

        return self.python_path.exists() and _engine_available(
            "roformer", str(self.python_path)
        )

    def _run(
        self,
        model_filename: str,
        input_path: Path,
        output_dir: Path,
        log_path: Path,
        dry_run: bool,
    ) -> dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        run_command(
            [
                str(self.python_path),
                str(self._bridge),
                model_filename,
                str(Path(input_path).resolve()),
                str(output_dir.resolve()),
                str(self.model_dir.resolve()),
            ],
            cwd=RUNTIME.app_root,
            log_path=log_path,
            dry_run=dry_run,
            env=_HF_ENV,
        )
        if dry_run:
            return {}
        result_file = output_dir / "result.json"
        if not result_file.exists():
            raise FileNotFoundError(
                f"audio-separator 未生成结果（{result_file} 缺失），请查看日志 {log_path}。"
            )
        raw = json.loads(result_file.read_text(encoding="utf-8"))
        return {label: Path(path) for label, path in raw.items()}

    def remove_harmony(
        self, vocals_in: Path, output_dir: Path, log_path: Path, dry_run: bool = False
    ) -> tuple[Path, Path]:
        """Split a vocal stem into (lead, backing harmony)."""
        stems = self._run(self.KARAOKE_MODEL, vocals_in, output_dir, log_path, dry_run)
        if dry_run:
            return vocals_in, vocals_in
        lead = stems.get("vocals")
        backing = stems.get("instrumental")
        if lead is None or backing is None:
            raise FileNotFoundError(
                f"去和声未得到主唱/和声两轨（得到 {list(stems)}），日志 {log_path}。"
            )
        return lead, backing

    def denoise(
        self, vocals_in: Path, output_dir: Path, log_path: Path, dry_run: bool = False
    ) -> Path:
        """Return a denoised copy of the vocal stem (drops noise/bleed)."""
        stems = self._run(self.DENOISE_MODEL, vocals_in, output_dir, log_path, dry_run)
        if dry_run:
            return vocals_in
        clean = stems.get("dry")
        if clean is None:
            raise FileNotFoundError(
                f"降噪未得到 dry 轨（得到 {list(stems)}），日志 {log_path}。"
            )
        return clean

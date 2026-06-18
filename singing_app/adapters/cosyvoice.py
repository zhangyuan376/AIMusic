from __future__ import annotations

import json
import tempfile
from pathlib import Path

from singing_app.adapters.command import run_command
from singing_app.config import RUNTIME

# Final training-sample format, matching the Edge TTS path (mono 44.1k s16).
_NEUTRAL_FILTER = "aresample=44100"


class CosyVoiceAdapter:
    """Zero-shot voice cloning via CosyVoice 2.

    Unlike Edge TTS (which speaks in a fixed Microsoft preset voice), CosyVoice
    clones the timbre of a user-provided reference clip, so it needs both the
    reference audio and its transcript.
    """

    def __init__(
        self,
        python_path: Path = RUNTIME.cosyvoice_python,
        model_dir: Path = RUNTIME.cosyvoice_model,
        cosyvoice_root: Path = RUNTIME.cosyvoice_root,
        ffmpeg_path: Path = RUNTIME.ffmpeg,
    ) -> None:
        self.python_path = python_path
        self.model_dir = model_dir
        self.cosyvoice_root = cosyvoice_root
        self.ffmpeg_path = ffmpeg_path

    def generate_samples(
        self,
        training_text_path: Path,
        output_dir: Path,
        log_path: Path,
        reference_audio: Path,
        reference_text: str,
        dry_run: bool = False,
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        blocks = self._read_blocks(training_text_path)

        raw_dir = output_dir / "_cosyvoice_raw"
        items = []
        final_outputs: list[Path] = []
        for index, text in enumerate(blocks, start=1):
            base = f"{index:03d}_cosyvoice"
            raw_wav = raw_dir / f"{base}.wav"
            final_wav = output_dir / f"{base}.wav"
            items.append({"text": text, "out": str(raw_wav)})
            final_outputs.append(final_wav)

        spec = {
            "model_dir": str(self.model_dir),
            "cosyvoice_root": str(self.cosyvoice_root),
            "prompt_wav": str(reference_audio),
            "prompt_text": reference_text,
            "items": items,
        }
        spec_path = Path(tempfile.gettempdir()) / f"cosyvoice_job_{output_dir.name}.json"
        if not dry_run:
            raw_dir.mkdir(parents=True, exist_ok=True)
            spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

        # Synthesize all blocks in one model load (model init is the slow part).
        run_command(
            [
                str(self.python_path),
                str(RUNTIME.app_root / "singing_app" / "_cosyvoice_synth.py"),
                str(spec_path),
            ],
            cwd=self.cosyvoice_root,
            log_path=log_path,
            dry_run=dry_run,
        )

        # Convert each raw clone to the RVC training format (mono 44.1k s16).
        for raw_wav, final_wav in zip(
            [Path(item["out"]) for item in items], final_outputs
        ):
            run_command(
                [
                    str(self.ffmpeg_path),
                    "-y",
                    "-i",
                    str(raw_wav),
                    "-af",
                    _NEUTRAL_FILTER,
                    "-ac",
                    "1",
                    "-ar",
                    "44100",
                    "-sample_fmt",
                    "s16",
                    str(final_wav),
                ],
                cwd=RUNTIME.app_root,
                log_path=log_path,
                dry_run=dry_run,
            )
            if not dry_run and raw_wav.exists():
                raw_wav.unlink()

        if not dry_run and raw_dir.exists() and not any(raw_dir.iterdir()):
            raw_dir.rmdir()

        return final_outputs

    @staticmethod
    def _read_blocks(path: Path) -> list[str]:
        raw = path.read_text(encoding="utf-8")
        blocks = [block.strip() for block in raw.replace("\r\n", "\n").split("\n\n")]
        return [block for block in blocks if len(block) >= 4]

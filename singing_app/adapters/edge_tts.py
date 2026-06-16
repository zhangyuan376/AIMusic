from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from singing_app.adapters.command import run_command
from singing_app.config import RUNTIME


@dataclass(frozen=True)
class TtsVariant:
    suffix: str
    rate: str
    pitch: str
    volume: str
    speed: str


DEFAULT_CLEAR_VARIANTS = [
    TtsVariant("clear_a", "-10%", "-5Hz", "-4%", "1.00"),
    TtsVariant("clear_b", "-12%", "-7Hz", "-4%", "1.01"),
    TtsVariant("clear_c", "-8%", "-4Hz", "-4%", "0.99"),
]


class EdgeTtsAdapter:
    def __init__(
        self,
        python_path: Path = RUNTIME.applio_python,
        ffmpeg_path: Path = RUNTIME.ffmpeg,
    ) -> None:
        self.python_path = python_path
        self.ffmpeg_path = ffmpeg_path

    def generate_samples(
        self,
        training_text_path: Path,
        output_dir: Path,
        log_path: Path,
        voice: str = "zh-CN-YunxiNeural",
        variants: list[TtsVariant] | None = None,
        dry_run: bool = False,
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        blocks = self._read_blocks(training_text_path)
        variants = variants or DEFAULT_CLEAR_VARIANTS

        outputs: list[Path] = []
        sample_index = 1
        for variant in variants:
            for text in blocks:
                base_name = f"{sample_index:03d}_{variant.suffix}"
                raw_mp3 = output_dir / f"{base_name}.raw.mp3"
                wav_path = output_dir / f"{base_name}.wav"

                run_command(
                    [
                        str(self.python_path),
                        "-m",
                        "edge_tts",
                        "--voice",
                        voice,
                        f"--rate={variant.rate}",
                        f"--pitch={variant.pitch}",
                        f"--volume={variant.volume}",
                        "--text",
                        text,
                        "--write-media",
                        str(raw_mp3),
                    ],
                    cwd=RUNTIME.app_root,
                    log_path=log_path,
                    dry_run=dry_run,
                )

                run_command(
                    [
                        str(self.ffmpeg_path),
                        "-y",
                        "-i",
                        str(raw_mp3),
                        "-af",
                        (
                            "asetrate=24000*1.00,aresample=44100,"
                            f"atempo={variant.speed},"
                            "highpass=f=110,lowpass=f=6200,"
                            "equalizer=f=850:t=q:w=1:g=2.5,"
                            "equalizer=f=1550:t=q:w=1:g=2.5,"
                            "equalizer=f=3200:t=q:w=1:g=1.5,"
                            "acompressor=threshold=-20dB:ratio=2.0:attack=12:release=120"
                        ),
                        "-ac",
                        "1",
                        "-ar",
                        "44100",
                        "-sample_fmt",
                        "s16",
                        str(wav_path),
                    ],
                    cwd=RUNTIME.app_root,
                    log_path=log_path,
                    dry_run=dry_run,
                )

                if not dry_run and raw_mp3.exists():
                    raw_mp3.unlink()

                outputs.append(wav_path)
                sample_index += 1

        return outputs

    @staticmethod
    def _read_blocks(path: Path) -> list[str]:
        raw = path.read_text(encoding="utf-8")
        blocks = [block.strip() for block in raw.replace("\r\n", "\n").split("\n\n")]
        return [block for block in blocks if len(block) >= 4]


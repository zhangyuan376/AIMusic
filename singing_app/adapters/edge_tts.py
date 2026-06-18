from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from singing_app.adapters.command import run_command
from singing_app.config import RUNTIME


@dataclass(frozen=True)
class TtsVariant:
    suffix: str
    rate: str = "+0%"
    pitch: str = "+0Hz"
    volume: str = "+0%"
    speed: str = "1.00"
    filter_chain: str = ""  # empty -> NEUTRAL_FILTER


# Neutral mastering: only the format conversion RVC training needs (mono 44.1k s16).
# No EQ / band-limiting / compression that would color the timbre toward any
# particular character. {speed} is substituted from the variant.
NEUTRAL_FILTER = "atempo={speed},aresample=44100"

# Default preset: neutral pitch/volume, a spread of speaking rates for natural
# prosody variety in the training set without biasing the voice toward any
# character. Pitch is left neutral on purpose — shifting it would color the
# timbre away from the source TTS voice.
DEFAULT_VARIANTS = [
    TtsVariant("v1"),
    TtsVariant("v2", rate="-10%"),
    TtsVariant("v3", rate="-5%"),
    TtsVariant("v4", rate="+5%"),
    TtsVariant("v5", rate="+10%"),
]

# Opt-in preset reproducing the original Pomao "clear small voice" shaping
# (lowered pitch/rate + EQ boosts + band-limit + compression).
POMAO_CLEAR_FILTER = (
    "asetrate=24000*1.00,aresample=44100,"
    "atempo={speed},"
    "highpass=f=110,lowpass=f=6200,"
    "equalizer=f=850:t=q:w=1:g=2.5,"
    "equalizer=f=1550:t=q:w=1:g=2.5,"
    "equalizer=f=3200:t=q:w=1:g=1.5,"
    "acompressor=threshold=-20dB:ratio=2.0:attack=12:release=120"
)
POMAO_CLEAR_VARIANTS = [
    TtsVariant("clear_a", "-10%", "-5Hz", "-4%", "1.00", POMAO_CLEAR_FILTER),
    TtsVariant("clear_b", "-12%", "-7Hz", "-4%", "1.01", POMAO_CLEAR_FILTER),
    TtsVariant("clear_c", "-8%", "-4Hz", "-4%", "0.99", POMAO_CLEAR_FILTER),
]

PRESETS: dict[str, list[TtsVariant]] = {
    "neutral": DEFAULT_VARIANTS,
    "pomao_clear": POMAO_CLEAR_VARIANTS,
}

# Backwards-compatible alias for callers that imported the old name.
DEFAULT_CLEAR_VARIANTS = POMAO_CLEAR_VARIANTS


def resolve_variants(preset: str | None) -> list[TtsVariant]:
    if not preset:
        return DEFAULT_VARIANTS
    try:
        return PRESETS[preset]
    except KeyError:
        raise ValueError(
            f"Unknown TTS preset '{preset}'. Available: {', '.join(sorted(PRESETS))}."
        ) from None


class EdgeTtsAdapter:
    def __init__(
        self,
        python_path: Path = RUNTIME.tool_python,
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
        preset: str | None = None,
        dry_run: bool = False,
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        blocks = self._read_blocks(training_text_path)
        variants = variants or resolve_variants(preset)

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
                        (variant.filter_chain or NEUTRAL_FILTER).replace(
                            "{speed}", variant.speed
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


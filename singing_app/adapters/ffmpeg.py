from __future__ import annotations

from pathlib import Path

from singing_app.adapters.command import run_command
from singing_app.config import RUNTIME


class FfmpegAdapter:
    def __init__(self, ffmpeg_path: Path = RUNTIME.ffmpeg) -> None:
        self.ffmpeg_path = ffmpeg_path

    def trim_audio(
        self,
        input_path: Path,
        output_path: Path,
        start_seconds: float,
        duration_seconds: float,
        log_path: Path,
        dry_run: bool = False,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        run_command(
            [
                str(self.ffmpeg_path),
                "-y",
                "-ss",
                str(start_seconds),
                "-t",
                str(duration_seconds),
                "-i",
                str(input_path),
                "-ar",
                "44100",
                "-ac",
                "2",
                str(output_path),
            ],
            cwd=RUNTIME.app_root,
            log_path=log_path,
            dry_run=dry_run,
        )

    def to_training_wav(
        self,
        input_path: Path,
        output_path: Path,
        log_path: Path,
        sample_rate: int = 44100,
        dry_run: bool = False,
    ) -> None:
        """Normalize an arbitrary recording into the RVC training format.

        Mono, 16-bit PCM at the target sample rate. Leading/trailing silence is
        trimmed so the dataset is dense; Applio's preprocess slices the rest.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        run_command(
            [
                str(self.ffmpeg_path),
                "-y",
                "-i",
                str(input_path),
                "-af",
                "silenceremove=start_periods=1:start_silence=0.1:start_threshold=-50dB:"
                "stop_periods=-1:stop_silence=0.3:stop_threshold=-50dB,"
                f"aresample={sample_rate}",
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-sample_fmt",
                "s16",
                str(output_path),
            ],
            cwd=RUNTIME.app_root,
            log_path=log_path,
            dry_run=dry_run,
        )

    def pitch_shift(
        self,
        input_path: Path,
        output_path: Path,
        semitones: float,
        log_path: Path,
        sample_rate: int = 44100,
        dry_run: bool = False,
    ) -> None:
        """Pitch-shift a recording while preserving its formants (timbre).

        Used for training-data augmentation: a speech dataset only covers a
        narrow pitch range, so an RVC model trained on it has to extrapolate
        when asked to sing high notes. Generating formant-preserved copies at
        shifted pitches gives the model real examples of the *same* timbre at a
        wider f0 range, which reduces the pinched/"夹嗓子" artifacts on high
        notes. ``formant=preserved`` keeps the spectral envelope fixed, so only
        the pitch moves — the perceived voice identity stays the same.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        ratio = 2.0 ** (semitones / 12.0)
        run_command(
            [
                str(self.ffmpeg_path),
                "-y",
                "-i",
                str(input_path),
                "-af",
                f"rubberband=pitch={ratio:.6f}:formant=preserved:pitchq=quality",
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-sample_fmt",
                "s16",
                str(output_path),
            ],
            cwd=RUNTIME.app_root,
            log_path=log_path,
            dry_run=dry_run,
        )

    def mix_audio(
        self,
        instrumental_path: Path,
        vocal_path: Path,
        output_path: Path,
        log_path: Path,
        instrumental_volume: float = 0.88,
        vocal_volume: float = 1.12,
        deess_strength: float = 0.0,
        dry_run: bool = False,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # De-essing tames the sibilance (sh/ch/s high-frequency energy) that makes
        # a converted vocal sound harshly retroflex. It only ducks the detected
        # sibilant band, so it cannot change pronunciation — it just softens the
        # listening impression. f=0.25 centers detection on the ~5-6kHz sibilant
        # band at 44.1kHz; i is the ducking amount. Skipped entirely at 0 so the
        # default (no de-essing) is bit-for-bit unchanged.
        deess = ""
        if deess_strength > 0:
            intensity = max(0.0, min(1.0, deess_strength))
            deess = f"deesser=i={intensity}:f=0.25,"
        filter_graph = (
            f"[0:a]volume={instrumental_volume}[a0];"
            f"[1:a]volume={vocal_volume},{deess}highpass=f=80,lowpass=f=12000[a1];"
            "[a0][a1]amix=inputs=2:duration=longest,alimiter=limit=0.95[out]"
        )
        run_command(
            [
                str(self.ffmpeg_path),
                "-y",
                "-i",
                str(instrumental_path),
                "-i",
                str(vocal_path),
                "-filter_complex",
                filter_graph,
                "-map",
                "[out]",
                "-ar",
                "44100",
                "-ac",
                "2",
                str(output_path),
            ],
            cwd=RUNTIME.app_root,
            log_path=log_path,
            dry_run=dry_run,
        )


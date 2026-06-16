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

    def mix_audio(
        self,
        instrumental_path: Path,
        vocal_path: Path,
        output_path: Path,
        log_path: Path,
        instrumental_volume: float = 0.88,
        vocal_volume: float = 1.12,
        dry_run: bool = False,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        filter_graph = (
            f"[0:a]volume={instrumental_volume}[a0];"
            f"[1:a]volume={vocal_volume},highpass=f=80,lowpass=f=12000[a1];"
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

    def compose_static_video(
        self,
        audio_path: Path,
        character_image: Path,
        output_path: Path,
        log_path: Path,
        background_image: Path | None = None,
        duration_seconds: float = 30,
        width: int = 1080,
        height: int = 1920,
        dry_run: bool = False,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        character_scale = min(width // 2, 540)
        overlay_x = f"(W-w)/2"
        overlay_y = f"H-h-160+20*sin(t*2)"

        if background_image:
            command = [
                str(self.ffmpeg_path),
                "-y",
                "-loop",
                "1",
                "-t",
                str(duration_seconds),
                "-i",
                str(background_image),
                "-loop",
                "1",
                "-t",
                str(duration_seconds),
                "-i",
                str(character_image),
                "-i",
                str(audio_path),
                "-filter_complex",
                (
                    f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{height}[bg];"
                    f"[1:v]scale={character_scale}:-1[char];"
                    f"[bg][char]overlay=x={overlay_x}:y='{overlay_y}'[v]"
                ),
                "-map",
                "[v]",
                "-map",
                "2:a",
                "-shortest",
                "-r",
                "30",
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ]
        else:
            command = [
                str(self.ffmpeg_path),
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x151820:s={width}x{height}:d={duration_seconds}",
                "-loop",
                "1",
                "-t",
                str(duration_seconds),
                "-i",
                str(character_image),
                "-i",
                str(audio_path),
                "-filter_complex",
                (
                    f"[1:v]scale={character_scale}:-1[char];"
                    f"[0:v][char]overlay=x={overlay_x}:y='{overlay_y}'[v]"
                ),
                "-map",
                "[v]",
                "-map",
                "2:a",
                "-shortest",
                "-r",
                "30",
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ]

        run_command(command, cwd=RUNTIME.app_root, log_path=log_path, dry_run=dry_run)


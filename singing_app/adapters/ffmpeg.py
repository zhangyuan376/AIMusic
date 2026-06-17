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

    def compose_mv_video(
        self,
        audio_path: Path,
        character_image: Path,
        background_image: Path,
        output_path: Path,
        log_path: Path,
        duration_seconds: float,
        width: int = 3840,
        height: int = 2160,
        character_height_ratio: float = 0.24,
        character_x_ratio: float = 0.44,
        ground_offset_ratio: float = 0.16,
        dry_run: bool = False,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fps = 30
        frames = max(1, int(duration_seconds * fps))
        character_height_ratio = min(max(character_height_ratio, 0.12), 0.75)
        character_x_ratio = min(max(character_x_ratio, 0.05), 0.95)
        ground_offset_ratio = min(max(ground_offset_ratio, 0.0), 0.35)
        character_height = int(height * character_height_ratio)
        ground_offset = int(height * ground_offset_ratio)
        character_x = f"W*{character_x_ratio:.4f}-w/2+8*sin(t*1.1)"
        character_y = f"H-h-{ground_offset}"
        shadow_y = f"H-h-{ground_offset}+18"
        filter_graph = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"zoompan=z='min(zoom+0.00016,1.045)':"
            f"x='iw/2-(iw/zoom/2)+18*sin(on/180)':"
            f"y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={fps}[bg];"
            f"[1:v]scale=-1:{character_height},format=rgba[char];"
            "[char]split[char_main][char_shadow_src];"
            "[char_shadow_src]colorchannelmixer=rr=0:gg=0:bb=0:aa=0.28[shadow];"
            f"[bg][shadow]overlay=x='{character_x}':y='{shadow_y}'[bg_shadow];"
            f"[bg_shadow][char_main]overlay=x='{character_x}':y='{character_y}',format=yuv420p[v]"
        )
        command = [
            str(self.ffmpeg_path),
            "-y",
            "-loop",
            "1",
            "-framerate",
            "1",
            "-t",
            "1",
            "-i",
            str(background_image),
            "-loop",
            "1",
            "-framerate",
            str(fps),
            "-t",
            str(duration_seconds),
            "-i",
            str(character_image),
            "-i",
            str(audio_path),
            "-filter_complex",
            filter_graph,
            "-map",
            "[v]",
            "-map",
            "2:a",
            "-shortest",
            "-r",
            str(fps),
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "mpeg4",
            "-q:v",
            "3",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        run_command(command, cwd=RUNTIME.app_root, log_path=log_path, dry_run=dry_run)


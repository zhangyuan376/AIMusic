from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import wave
from array import array
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from singing_app.config import RUNTIME


def _read_wave_mono(path: Path) -> tuple[list[float], int]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())

    if sample_width != 2:
        raise ValueError(f"Only 16-bit PCM wav is supported for now: {path}")

    samples = array("h")
    samples.frombytes(frames)
    if channels > 1:
        mono = []
        for index in range(0, len(samples), channels):
            mono.append(sum(samples[index : index + channels]) / channels / 32768.0)
        return mono, sample_rate
    return [sample / 32768.0 for sample in samples], sample_rate


def _frame_rms(samples: list[float], sample_rate: int, fps: int, frame_count: int) -> list[float]:
    values = []
    samples_per_frame = sample_rate / fps
    for frame in range(frame_count):
        start = int(frame * samples_per_frame)
        end = min(len(samples), int((frame + 1) * samples_per_frame))
        if end <= start:
            values.append(0.0)
            continue
        total = sum(sample * sample for sample in samples[start:end])
        values.append(math.sqrt(total / (end - start)))
    return values


def _smooth(values: list[float], radius: int = 2) -> list[float]:
    smoothed = []
    for index in range(len(values)):
        start = max(0, index - radius)
        end = min(len(values), index + radius + 1)
        smoothed.append(sum(values[start:end]) / (end - start))
    return smoothed


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return values
    sorted_values = sorted(values)
    peak = sorted_values[int(len(sorted_values) * 0.95)] or max(values) or 1.0
    return [min(1.0, value / peak) for value in values]


def _estimate_beat_frames(energy: list[float], fps: int) -> int:
    centered = [value - (sum(energy) / len(energy) if energy else 0.0) for value in energy]
    min_lag = max(1, int(fps * 60 / 180))
    max_lag = max(min_lag + 1, int(fps * 60 / 70))
    best_lag = int(fps * 0.5)
    best_score = float("-inf")
    for lag in range(min_lag, max_lag + 1):
        score = 0.0
        for index in range(lag, len(centered)):
            score += centered[index] * centered[index - lag]
        if score > best_score:
            best_score = score
            best_lag = lag
    return max(1, best_lag)


def _mouth_level(volume: float) -> int:
    if volume < 0.10:
        return 0
    if volume < 0.28:
        return 1
    if volume < 0.55:
        return 2
    return 3


def _draw_mouth(draw: ImageDraw.ImageDraw, center: tuple[int, int], scale: float, level: int) -> None:
    x, y = center
    widths = [12, 19, 26, 34]
    heights = [3, 8, 14, 20]
    width = max(2, int(widths[level] * scale))
    height = max(1, int(heights[level] * scale))
    box = (x - width // 2, y - height // 2, x + width // 2, y + height // 2)
    if level == 0:
        draw.line((box[0], y, box[2], y), fill=(28, 20, 20, 240), width=max(1, int(3 * scale)))
    else:
        draw.ellipse(box, fill=(24, 16, 18, 245), outline=(150, 92, 78, 220), width=max(1, int(2 * scale)))
        if level >= 2:
            shine = (x - width // 5, y - height // 4, x + width // 5, y)
            draw.arc(shine, 195, 345, fill=(235, 182, 170, 110), width=max(1, int(scale)))


def _draw_strum(draw: ImageDraw.ImageDraw, origin: tuple[int, int], scale: float, phase: float, strength: float) -> None:
    x, y = origin
    swing = math.sin(phase * math.tau)
    offset = int(16 * scale * swing)
    color = (255, 214, 128, int(120 + 110 * strength))
    width = max(2, int(3 * scale))
    draw.line(
        (
            x + offset,
            y - int(22 * scale),
            x - int(10 * scale) + offset // 2,
            y + int(20 * scale),
        ),
        fill=color,
        width=width,
    )
    if strength > 0.55:
        draw.arc(
            (
                x - int(34 * scale),
                y - int(26 * scale),
                x + int(34 * scale),
                y + int(30 * scale),
            ),
            325,
            40,
            fill=(255, 230, 160, 145),
            width=width,
        )


def _add_contact_shadow(frame: Image.Image, scale_x: float, scale_y: float) -> None:
    shadow = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow)
    cx = int(470 * scale_x)
    cy = int(493 * scale_y)
    rx = int(72 * scale_x)
    ry = int(14 * scale_y)
    draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=(0, 0, 0, 48))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(2, int(5 * scale_x))))
    frame.alpha_composite(shadow)


def _load_layout(layout_path: Path | None) -> dict:
    if not layout_path:
        return {}
    with layout_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _scaled_point(layout: dict, key: str, default: tuple[int, int], scale_x: float, scale_y: float) -> tuple[int, int]:
    value = layout.get(key, {}).get("center", default)
    return int(value[0] * scale_x), int(value[1] * scale_y)


def _load_sprite(path: Path | None, scale: float) -> Image.Image | None:
    if not path or not path.is_file():
        return None
    sprite = Image.open(path).convert("RGBA")
    if scale != 1.0:
        size = (max(1, int(sprite.width * scale)), max(1, int(sprite.height * scale)))
        sprite = sprite.resize(size, Image.Resampling.LANCZOS)
    return sprite


def _sprite_paths(layout: dict, asset_root: Path | None, group: str) -> list[Path | None]:
    if not asset_root:
        return []
    entries = layout.get(group, {}).get("sprites", [])
    return [(asset_root / entry) if entry else None for entry in entries]


def _overlay_center(frame: Image.Image, sprite: Image.Image, center: tuple[int, int]) -> None:
    x = int(center[0] - sprite.width / 2)
    y = int(center[1] - sprite.height / 2)
    frame.alpha_composite(sprite, (x, y))


def _strum_sprite_index(phase: float) -> int:
    if phase < 0.33:
        return 0
    if phase < 0.66:
        return 1
    return 2


def render_performance_video(
    image_path: Path,
    mix_audio_path: Path,
    output_path: Path,
    vocal_audio_path: Path | None = None,
    asset_root: Path | None = None,
    layout_path: Path | None = None,
    ffmpeg_path: Path = RUNTIME.ffmpeg,
    fps: int = 24,
    width: int = 1280,
    height: int = 720,
    max_seconds: float | None = None,
) -> None:
    analysis_audio = vocal_audio_path or mix_audio_path
    samples, sample_rate = _read_wave_mono(analysis_audio)
    duration = len(samples) / sample_rate
    if max_seconds:
        duration = min(duration, max_seconds)
    frame_count = max(1, int(duration * fps))

    volumes = _normalize(_smooth(_frame_rms(samples, sample_rate, fps, frame_count), radius=2))
    beat_energy = _normalize(_smooth(_frame_rms(samples, sample_rate, fps, frame_count), radius=4))
    beat_frames = _estimate_beat_frames(beat_energy, fps)

    work_dir = output_path.parent / f"{output_path.stem}_frames"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    layout = _load_layout(layout_path)
    source_size = layout.get("source_size", [1024, 576])
    source_width, source_height = source_size

    base = Image.open(image_path).convert("RGBA")
    base = base.resize((width, height), Image.Resampling.LANCZOS)
    scale_x = width / source_width
    scale_y = height / source_height
    draw_scale = (scale_x + scale_y) / 2
    mouth_center = _scaled_point(layout, "mouth", (445, 444), scale_x, scale_y)
    strum_origin = _scaled_point(layout, "strum", (487, 459), scale_x, scale_y)
    sprite_scale = draw_scale * float(layout.get("sprite_scale", 1.0))
    mouth_sprites = [_load_sprite(path, sprite_scale) for path in _sprite_paths(layout, asset_root, "mouth")]
    strum_sprites = [_load_sprite(path, sprite_scale) for path in _sprite_paths(layout, asset_root, "strum")]

    last_level = 0
    for frame_index in range(frame_count):
        frame = base.copy()
        _add_contact_shadow(frame, scale_x, scale_y)
        overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        # A tiny global tint ties the procedural overlays into the night scene.
        draw.rectangle((0, 0, width, height), fill=(18, 28, 62, 10))

        target_level = _mouth_level(volumes[frame_index])
        if abs(target_level - last_level) > 1:
            target_level = last_level + (1 if target_level > last_level else -1)
        last_level = target_level

        beat_phase = (frame_index % beat_frames) / beat_frames
        beat_strength = max(0.25, beat_energy[frame_index])

        frame.alpha_composite(overlay)
        if target_level < len(mouth_sprites) and mouth_sprites[target_level]:
            _overlay_center(frame, mouth_sprites[target_level], mouth_center)
        else:
            draw = ImageDraw.Draw(frame)
            _draw_mouth(draw, mouth_center, draw_scale, target_level)
        strum_index = _strum_sprite_index(beat_phase)
        if strum_index < len(strum_sprites) and strum_sprites[strum_index]:
            _overlay_center(frame, strum_sprites[strum_index], strum_origin)
        else:
            draw = ImageDraw.Draw(frame)
            _draw_strum(draw, strum_origin, draw_scale, beat_phase, beat_strength)
        frame.convert("RGB").save(work_dir / f"frame_{frame_index:05d}.jpg", quality=92)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(ffmpeg_path),
        "-y",
        "-framerate",
        str(fps),
        "-i",
        str(work_dir / "frame_%05d.jpg"),
        "-i",
        str(mix_audio_path),
        "-t",
        f"{duration:.3f}",
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-c:v",
        "mpeg4",
        "-q:v",
        "3",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    subprocess.run(command, cwd=RUNTIME.app_root, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a fixed-camera, audio-driven Pomao performance MV.")
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--mix-audio", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--vocal-audio", type=Path)
    parser.add_argument("--asset-root", type=Path)
    parser.add_argument("--layout", type=Path)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--max-seconds", type=float)
    args = parser.parse_args()

    render_performance_video(
        image_path=args.image,
        mix_audio_path=args.mix_audio,
        vocal_audio_path=args.vocal_audio,
        output_path=args.output,
        asset_root=args.asset_root,
        layout_path=args.layout,
        fps=args.fps,
        width=args.width,
        height=args.height,
        max_seconds=args.max_seconds,
    )


if __name__ == "__main__":
    main()

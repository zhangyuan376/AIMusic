from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from singing_app.adapters.command import run_command
from singing_app.config import RUNTIME


class MediaDownloader:
    """Fetch audio/video from a URL (Douyin, YouTube, Bilibili, ...) via yt-dlp.

    yt-dlp downloads the best available stream into an isolated work dir; the
    audio is then transcoded to the mix stage's expected WAV format (stereo
    44.1k s16) so the result can be used directly as cover source material or a
    zero-shot reference clip. The original video is kept only when requested.
    """

    def __init__(
        self,
        ytdlp_path: Path = None,  # resolved lazily so env overrides apply
        ffmpeg_path: Path = RUNTIME.ffmpeg,
    ) -> None:
        self.ytdlp_path = ytdlp_path or RUNTIME.ytdlp
        self.ffmpeg_path = ffmpeg_path

    def available(self) -> bool:
        path = self.ytdlp_path
        if path.is_absolute() or "/" in str(path) or "\\" in str(path):
            return path.exists()
        return shutil.which(str(path)) is not None

    def download(
        self,
        url: str,
        out_dir: Path,
        log_path: Path,
        keep_video: bool = True,
        dry_run: bool = False,
    ) -> dict[str, object]:
        out_dir.mkdir(parents=True, exist_ok=True)
        # Download into a throwaway sub-dir so the produced files (media +
        # .info.json) can be identified unambiguously, regardless of what other
        # downloads already sit in out_dir.
        workdir = Path(tempfile.mkdtemp(prefix="dl_", dir=str(out_dir)))
        run_command(
            [
                str(self.ytdlp_path),
                "--no-playlist",
                "--no-warnings",
                "--write-info-json",
                "-o",
                "%(id)s.%(ext)s",
                "-P",
                str(workdir),
                url,
            ],
            cwd=RUNTIME.app_root,
            log_path=log_path,
            dry_run=dry_run,
        )
        if dry_run:
            return {"video_path": None, "audio_path": str(out_dir / "dry_run.wav")}

        info = self._read_info(workdir)
        media = self._media_file(workdir)
        if media is None:
            shutil.rmtree(workdir, ignore_errors=True)
            raise FileNotFoundError(
                f"yt-dlp 未在 {workdir} 下载到媒体文件，请查看日志 {log_path}（链接可能需要登录、已失效或暂不支持）。"
            )

        stem = info.get("id") or media.stem
        audio_path = out_dir / f"{stem}.wav"
        run_command(
            [
                str(self.ffmpeg_path),
                "-y",
                "-i",
                str(media),
                "-vn",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-sample_fmt",
                "s16",
                str(audio_path),
            ],
            cwd=RUNTIME.app_root,
            log_path=log_path,
            dry_run=dry_run,
        )

        video_path = None
        if keep_video:
            video_path = out_dir / media.name
            shutil.move(str(media), str(video_path))
        shutil.rmtree(workdir, ignore_errors=True)

        return {
            "video_path": str(video_path) if video_path else None,
            "audio_path": str(audio_path),
            "title": info.get("title") or stem,
            "duration": info.get("duration"),
        }

    @staticmethod
    def _read_info(directory: Path) -> dict:
        for info in directory.glob("*.info.json"):
            try:
                return json.loads(info.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    @staticmethod
    def _media_file(directory: Path) -> Path | None:
        candidates = [
            p
            for p in directory.iterdir()
            if p.is_file() and not p.name.endswith((".info.json", ".part"))
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime)

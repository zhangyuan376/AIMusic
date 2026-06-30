from __future__ import annotations

import json
import re
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from singing_app.adapters.command import CommandError, run_command
from singing_app.config import RUNTIME


# Mobile Safari UA: the iesdouyin share H5 returns a JSON-rich, public,
# cookie-free response only when the request looks like an iPhone browser.
# Desktop UAs get the gated detail page that yt-dlp can't parse without fresh
# session cookies.
_DOUYIN_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Mobile/15E148 Safari/604.1"
)
_DOUYIN_HOSTS = ("douyin.com", "iesdouyin.com")


class MediaDownloader:
    """Fetch audio/video from a URL (Douyin, YouTube, Bilibili, ...) via yt-dlp.

    For Douyin links a direct path through the public ``iesdouyin.com`` mobile
    share H5 is used instead — yt-dlp's Douyin extractor needs fresh session
    cookies, which often can't be obtained on a Linux desktop (ETP, snap
    sandboxing, root-owned Chrome profiles). The H5 path needs no cookies and
    returns the same no-watermark MP4 the official share preview plays.

    The audio is then transcoded to the mix stage's expected WAV format (stereo
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
        cookies_file: Path | None = None,
        cookies_from_browser: str | None = None,
    ) -> dict[str, object]:
        out_dir.mkdir(parents=True, exist_ok=True)
        # Users paste raw browser-bar text which may lack a scheme (e.g.
        # ``www.douyin.com/...``). urlparse needs a scheme to populate netloc,
        # so the host classifier falls through to yt-dlp. Add it back here so
        # both the Douyin and yt-dlp paths receive a canonical URL.
        url = self._ensure_scheme(url)
        # Download into a throwaway sub-dir so the produced files (media +
        # .info.json) can be identified unambiguously, regardless of what other
        # downloads already sit in out_dir.
        workdir = Path(tempfile.mkdtemp(prefix="dl_", dir=str(out_dir)))
        try:
            if self._is_douyin_url(url):
                self._fetch_douyin(url, workdir, log_path, dry_run)
            else:
                self._fetch_via_ytdlp(
                    url,
                    workdir,
                    log_path,
                    dry_run,
                    cookies_file=cookies_file,
                    cookies_from_browser=cookies_from_browser,
                )
        except Exception:
            shutil.rmtree(workdir, ignore_errors=True)
            raise

        if dry_run:
            return {"video_path": None, "audio_path": str(out_dir / "dry_run.wav")}

        info = self._read_info(workdir)
        media = self._media_file(workdir)
        if media is None:
            shutil.rmtree(workdir, ignore_errors=True)
            raise FileNotFoundError(
                f"未在 {workdir} 下载到媒体文件，请查看日志 {log_path}（链接可能需要登录、已失效或暂不支持）。"
            )

        # File stem prefers a sanitized title so a folder of clips is readable
        # at a glance; falls back to the id when the title isn't usable. The
        # numeric id and source URL go into a side-car .info.json for
        # traceability back to the original post.
        raw_title = str(info.get("title") or "").strip()
        aweme_id = str(info.get("id") or "").strip()
        fallback_stem = aweme_id or media.stem
        clean_title = self._sanitize_for_filename(raw_title) or fallback_stem
        final_stem = self._unique_stem(out_dir, clean_title)
        audio_path = out_dir / f"{final_stem}.wav"
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
            video_path = out_dir / f"{final_stem}{media.suffix}"
            shutil.move(str(media), str(video_path))

        # Side-car preserves the source id even after the title-based rename so
        # users can map the file back to the douyin/YT post.
        sidecar = audio_path.with_suffix(".info.json")
        sidecar.write_text(
            json.dumps(
                {
                    "id": aweme_id or None,
                    "title": raw_title or None,
                    "source_url": url,
                    "duration": info.get("duration"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        shutil.rmtree(workdir, ignore_errors=True)

        return {
            "video_path": str(video_path) if video_path else None,
            "audio_path": str(audio_path),
            "title": raw_title or final_stem,
            "duration": info.get("duration"),
        }

    def _fetch_via_ytdlp(
        self,
        url: str,
        workdir: Path,
        log_path: Path,
        dry_run: bool,
        cookies_file: Path | None,
        cookies_from_browser: str | None,
    ) -> None:
        cmd: list[str] = [
            str(self.ytdlp_path),
            "--no-playlist",
            "--no-warnings",
            "--write-info-json",
            "-o",
            "%(id)s.%(ext)s",
            "-P",
            str(workdir),
        ]
        # Sites like YouTube can also gate behind cookies. cookies.txt wins over
        # the auto-browser path: it survives snap sandboxes / root-owned profile
        # dirs and lets the user export cookies from a session that actually
        # browsed the site.
        if cookies_file is not None:
            cmd += ["--cookies", str(cookies_file)]
        elif cookies_from_browser:
            cmd += ["--cookies-from-browser", cookies_from_browser]
        cmd.append(url)
        try:
            run_command(cmd, cwd=RUNTIME.app_root, log_path=log_path, dry_run=dry_run)
        except CommandError as exc:
            tail = (exc.log_tail or "").strip()
            hint = self._hint_from_tail(tail)
            msg = "yt-dlp 下载失败。"
            if hint:
                msg += f" {hint}"
            if tail:
                msg += f"\n\n日志末尾:\n{tail}"
            raise RuntimeError(msg) from exc

    def _fetch_douyin(
        self,
        url: str,
        workdir: Path,
        log_path: Path,
        dry_run: bool,
    ) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)

        def log(line: str) -> None:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(line.rstrip() + "\n")

        log(f"$ [douyin-h5] {url}")
        if dry_run:
            log("[dry-run] douyin fetch skipped")
            return

        try:
            aweme_id = self._resolve_douyin_id(url)
            log(f"[douyin] aweme_id={aweme_id}")
            share_url = f"https://www.iesdouyin.com/share/video/{aweme_id}/"
            html = self._http_get_text(share_url, log=log)
            mp4_url, title, duration = self._parse_douyin_share(html)
            log(f"[douyin] title={title!r} duration={duration}")
            log(f"[douyin] play_url={mp4_url}")
            media_path = workdir / f"{aweme_id}.mp4"
            self._http_download(
                mp4_url, media_path, referer="https://www.iesdouyin.com/", log=log
            )
            info_path = workdir / f"{aweme_id}.info.json"
            info_path.write_text(
                json.dumps(
                    {"id": aweme_id, "title": title, "duration": duration},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            log(f"[douyin] saved media={media_path.name} info={info_path.name}")
        except _DouyinError as exc:
            raise RuntimeError(f"抖音下载失败：{exc}\n\n详情见日志 {log_path}。") from exc

    @staticmethod
    def _ensure_scheme(url: str) -> str:
        u = url.strip()
        if "://" not in u:
            u = "https://" + u.lstrip("/")
        return u

    @staticmethod
    def _sanitize_for_filename(text: str, max_len: int = 40) -> str:
        """Reduce a clip title to a short, filesystem-safe stem.

        Douyin/YouTube titles are mostly hashtags, @mentions and emoji noise
        wrapped around the actual song name. Stripping that tail leaves the
        readable head (song title or hook line), which is what users skim a
        folder for. Returns "" when nothing legible remains so callers can
        fall back to the id.
        """
        t = (text or "").strip()
        # Drop everything from the first hashtag onward — douyin titles put the
        # song head first and tag soup at the tail; the head is what users skim
        # for. Also drop douyin's "原声：@xxx" credit and stray @mentions.
        t = t.split("#", 1)[0]
        t = re.sub(r"原声[:：]\s*[@＠]?\S+.*$", "", t)
        t = re.sub(r"[@＠]\S+", "", t)
        # Replace filesystem-unsafe punctuation; Windows also blocks * ? " < > |.
        t = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", t)
        t = re.sub(r"\s+", " ", t).strip(" ._-")
        if len(t) > max_len:
            t = t[:max_len].rstrip(" ._-")
        return t

    @staticmethod
    def _unique_stem(directory: Path, stem: str) -> str:
        """Return ``stem`` if no <stem>.wav/.mp4/.info.json exists, else append _N.

        Checks all three suffixes the downloader writes so the audio, video and
        side-car info live as one self-consistent triple.
        """
        suffixes = (".wav", ".mp4", ".info.json")

        def taken(candidate: str) -> bool:
            return any((directory / f"{candidate}{s}").exists() for s in suffixes)

        if not taken(stem):
            return stem
        n = 2
        while taken(f"{stem}_{n}"):
            n += 1
        return f"{stem}_{n}"

    @staticmethod
    def _is_douyin_url(url: str) -> bool:
        try:
            host = urllib.parse.urlparse(url).netloc.lower()
        except Exception:
            return False
        return any(host == h or host.endswith("." + h) for h in _DOUYIN_HOSTS)

    @classmethod
    def _resolve_douyin_id(cls, url: str) -> str:
        # Short links (v.douyin.com/<code>) 302 to the canonical URL — follow
        # once to find the digit id.
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc.lower().startswith("v.douyin.com"):
            url = cls._http_resolve_redirect(url)
            parsed = urllib.parse.urlparse(url)

        # /video/<id> in path, or modal_id / aweme_id in query.
        m = re.search(r"/(?:video|share/video|note)/(\d{6,})", parsed.path)
        if m:
            return m.group(1)
        qs = urllib.parse.parse_qs(parsed.query)
        for key in ("modal_id", "aweme_id", "item_id"):
            value = (qs.get(key, [""])[0] or "").strip()
            if value.isdigit() and len(value) >= 6:
                return value
        # Fallback: first long digit run anywhere in the URL.
        m = re.search(r"(\d{15,})", url)
        if m:
            return m.group(1)
        raise _DouyinError(f"无法从链接里解析出抖音视频 id：{url}")

    @staticmethod
    def _parse_douyin_share(html: str) -> tuple[str, str, float | None]:
        # play_addr.url_list[0] is the no-watermark mp4 once `playwm` is swapped
        # for `play`. The HTML is UTF-8 with CJK as literal characters, but JSON
        # string values still escape ASCII punctuation (/ for slash). Decode
        # via json.loads so escapes are resolved without trashing the CJK title.
        def _json_str(raw: str) -> str:
            try:
                return json.loads(f'"{raw}"')
            except json.JSONDecodeError:
                return raw

        m = re.search(
            r'"play_addr":\s*\{[^}]*?"url_list":\s*\[\s*"([^"]+)"',
            html,
        )
        if not m:
            raise _DouyinError("share H5 里未找到 play_addr.url_list，页面结构可能变更。")
        url = _json_str(m.group(1)).replace("/playwm/", "/play/")
        title = ""
        m = re.search(r'"desc":"((?:[^"\\]|\\.){0,400})"', html)
        if m:
            title = _json_str(m.group(1)).strip()
        duration: float | None = None
        m = re.search(r'"duration":\s*(\d+)', html)
        if m:
            ms = int(m.group(1))
            # Heuristic: Douyin's video duration is in milliseconds (~25034 for a
            # 25-second clip); a small value (<1000) is already seconds.
            duration = ms / 1000.0 if ms >= 1000 else float(ms)
        return url, title, duration

    @staticmethod
    def _http_get_text(url: str, log) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": _DOUYIN_UA})
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = resp.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise _DouyinError(f"抓取 share 页失败：{exc}") from exc
        log(f"[douyin] GET {url} -> {len(data)} bytes")
        return data.decode("utf-8", errors="replace")

    @staticmethod
    def _http_resolve_redirect(url: str) -> str:
        req = urllib.request.Request(
            url, headers={"User-Agent": _DOUYIN_UA}, method="GET"
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.geturl()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise _DouyinError(f"短链解析失败：{exc}") from exc

    @staticmethod
    def _http_download(url: str, dest: Path, referer: str, log) -> None:
        req = urllib.request.Request(
            url, headers={"User-Agent": _DOUYIN_UA, "Referer": referer}
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp, dest.open("wb") as fh:
                total = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    fh.write(chunk)
                    total += len(chunk)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise _DouyinError(f"下载 mp4 失败：{exc}") from exc
        if total < 1024:
            raise _DouyinError(f"下载的 mp4 过小 ({total} bytes)，可能是错误页。")
        log(f"[douyin] downloaded {dest.name} ({total} bytes)")

    @staticmethod
    def _hint_from_tail(tail: str) -> str:
        low = tail.lower()
        if "fresh cookies" in low or "cookies (not necessarily" in low:
            return (
                "抖音/YouTube 要求 fresh cookies。请在「下载选项」里指定一个 cookies.txt"
                "（用浏览器扩展 Get cookies.txt LOCALLY 在登录/已浏览过该站点的页面导出），"
                "或选一个本机能读到 cookies 的浏览器。"
            )
        if "could not find" in low and "cookies database" in low:
            return (
                "yt-dlp 读不到所选浏览器的 cookies 数据库（可能是权限或路径问题）。"
                "换一个浏览器,或者用 cookies.txt 路径。"
            )
        if "sign in to confirm" in low or "login required" in low:
            return "视频要求登录,请使用导出的 cookies.txt。"
        if "http error 403" in low or "forbidden" in low:
            return "服务器拒绝访问(403),通常意味着需要 cookies 或 IP 被限速。"
        return ""

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


class _DouyinError(RuntimeError):
    """Internal-only error from the Douyin H5 path; surfaces as RuntimeError."""

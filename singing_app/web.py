from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tkinter import filedialog
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from singing_app.config import RUNTIME
from singing_app.harness.runner import HarnessRunner
from singing_app.pitch import suggest_pitch_shift
from singing_app.runtime_check import checks_as_dicts
from singing_app.separation_models import (
    DEFAULT_SEPARATION_MODEL,
    list_separation_models,
    resolve_separation_model,
)


STATIC_ROOT = Path(__file__).resolve().parent / "web_static"
VOICE_LIBRARY_PATH = RUNTIME.output_root / "voice_library.json"
SEPARATION_LIBRARY_PATH = RUNTIME.output_root / "separation_library.json"
COVER_LIBRARY_PATH = RUNTIME.output_root / "cover_library.json"


class WebJobManager:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running_thread: threading.Thread | None = None
        self.current_job = ""
        self.messages: list[str] = []

    def start(self, job_path: Path, dry_run: bool, resume: bool) -> dict[str, str]:
        with self.lock:
            if self.running_thread and self.running_thread.is_alive():
                return {"status": "busy", "message": f"Job already running: {self.current_job}"}
            self.current_job = str(job_path)
            self.messages.append(f"Starting job: {job_path}")
            self.running_thread = threading.Thread(target=self._run, args=(job_path, dry_run, resume), daemon=True)
            self.running_thread.start()
        return {"status": "started", "message": f"Started job: {job_path}"}

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            running = bool(self.running_thread and self.running_thread.is_alive())
            return {"running": running, "current_job": self.current_job, "messages": list(self.messages[-100:])}

    def _run(self, job_path: Path, dry_run: bool, resume: bool) -> None:
        extra_messages: list[str] = []
        try:
            HarnessRunner.from_file(job_path, dry_run=dry_run).run(resume=resume)
            if not dry_run:
                auto_bind_message = auto_bind_trained_voice(job_path)
                if auto_bind_message:
                    extra_messages.append(auto_bind_message)
                separation_message = auto_save_separation_result(job_path)
                if separation_message:
                    extra_messages.append(separation_message)
                cover_message = auto_save_cover_result(job_path)
                if cover_message:
                    extra_messages.append(cover_message)
            message = "Job finished."
        except Exception as exc:
            message = f"Job failed: {exc}"
        with self.lock:
            self.messages.extend(extra_messages)
            self.messages.append(message)


class SingingWebHandler(SimpleHTTPRequestHandler):
    manager: WebJobManager

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self._send_file(STATIC_ROOT / "index.html", "text/html; charset=utf-8")
            elif parsed.path == "/api/defaults":
                self._send_json(default_values())
            elif parsed.path == "/api/runtime":
                self._send_json({"checks": checks_as_dicts()})
            elif parsed.path == "/api/jobs":
                self._send_json({"jobs": list_jobs()})
            elif parsed.path == "/api/voices":
                ensure_default_voice()
                self._send_json({"voices": load_voice_library()})
            elif parsed.path == "/api/separations":
                self._send_json({"separations": load_separation_library()})
            elif parsed.path == "/api/separation-models":
                self._send_json({"models": list_separation_models()})
            elif parsed.path == "/api/suggest-pitch":
                query = parse_qs(parsed.query)
                self._send_json(suggest_cover_pitch(
                    query.get("voice_id", [""])[0],
                    query.get("separation_job_path", [""])[0],
                ))
            elif parsed.path == "/api/covers":
                self._send_json({"covers": load_cover_library()})
            elif parsed.path == "/api/samples":
                job_path = Path(parse_qs(parsed.query).get("job_path", [""])[0])
                self._send_json({"samples": list_voice_samples(job_path)})
            elif parsed.path == "/api/file":
                query = parse_qs(parsed.query)
                file_path = Path(query.get("path", [""])[0])
                download = query.get("download", ["0"])[0] in ("1", "true", "yes")
                self._send_file(file_path, _content_type(file_path), download=download)
            elif parsed.path == "/api/status":
                job_path = Path(parse_qs(parsed.query).get("job_path", [""])[0])
                self._send_json(job_status(job_path, self.manager.snapshot()))
            elif parsed.path == "/api/open-output":
                job_path = Path(parse_qs(parsed.query).get("job_path", [""])[0])
                self._send_json(open_output_folder(job_path))
            elif parsed.path == "/api/checkpoints":
                voice_id = parse_qs(parsed.query).get("voice_id", [""])[0]
                self._send_json(list_voice_checkpoints(voice_id))
            elif parsed.path == "/api/pick-file":
                query = parse_qs(parsed.query)
                self._send_json(pick_file(
                    kind=query.get("kind", ["any"])[0],
                    initial=query.get("initial", [""])[0],
                ))
            elif parsed.path.startswith("/api/"):
                self._send_json({"error": f"Unknown API endpoint: {parsed.path}"}, status=HTTPStatus.NOT_FOUND)
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
            if parsed.path == "/api/create-audio-cover-job":
                self._send_json({"job_path": str(write_audio_cover_job(payload))})
            elif parsed.path == "/api/create-separation-job":
                self._send_json({"job_path": str(write_separation_job(payload))})
            elif parsed.path == "/api/create-voice-job":
                self._send_json({"job_path": str(write_voice_sample_job(payload))})
            elif parsed.path == "/api/create-training-job":
                self._send_json({"job_path": str(write_training_job(payload))})
            elif parsed.path == "/api/create-recording-prepare-job":
                self._send_json({"job_path": str(write_recording_prepare_job(payload))})
            elif parsed.path == "/api/create-training-from-voice":
                self._send_json({"job_path": str(write_training_job_from_voice(payload))})
            elif parsed.path == "/api/bind-trained-voice":
                self._send_json({"voice": bind_trained_voice(payload)})
            elif parsed.path == "/api/rebind-checkpoint":
                self._send_json({"voice": rebind_checkpoint(payload)})
            elif parsed.path == "/api/save-voice":
                self._send_json({"voice": save_voice_selection(payload)})
            elif parsed.path == "/api/run-job":
                job_path = Path(str(payload.get("job_path", "")))
                if not job_path.exists():
                    raise FileNotFoundError(f"Job file not found: {job_path}")
                result = self.manager.start(
                    job_path,
                    dry_run=bool(payload.get("dry_run", True)),
                    resume=not bool(payload.get("no_resume", False)),
                )
                self._send_json(result)
            elif parsed.path.startswith("/api/"):
                self._send_json({"error": f"Unknown API endpoint: {parsed.path}"}, status=HTTPStatus.NOT_FOUND)
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send_json(self, data: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        encoded = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_file(self, path: Path, content_type: str, download: bool = False) -> None:
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        file_size = path.stat().st_size
        range_header = self.headers.get("Range", "")
        start = 0
        end = file_size - 1
        status = HTTPStatus.OK

        if range_header.startswith("bytes="):
            requested = range_header.removeprefix("bytes=").split(",", 1)[0].strip()
            start_text, _, end_text = requested.partition("-")
            try:
                if start_text:
                    start = int(start_text)
                    end = int(end_text) if end_text else file_size - 1
                else:
                    suffix_length = int(end_text)
                    start = max(0, file_size - suffix_length)
                end = min(end, file_size - 1)
                if start > end or start >= file_size:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{file_size}")
                    self.end_headers()
                    return
                status = HTTPStatus.PARTIAL_CONTENT
            except ValueError:
                start = 0
                end = file_size - 1

        content_length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        if download:
            self.send_header(
                "Content-Disposition",
                f"attachment; filename*=UTF-8''{quote(path.name)}",
            )
        if path.name == "index.html":
            self.send_header("Cache-Control", "no-store")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.send_header("Content-Length", str(content_length))
        self.end_headers()
        with path.open("rb") as file:
            file.seek(start)
            remaining = content_length
            while remaining > 0:
                chunk = file.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


def default_values() -> dict[str, str]:
    ensure_default_voice()
    return {
        "app_root": str(RUNTIME.app_root),
        "jobs_root": str(RUNTIME.app_root / "singing_app" / "jobs"),
        "projects_root": str(RUNTIME.projects_root),
        "default_job": str(RUNTIME.app_root / "singing_app" / "jobs" / "pomao_demo_job.json"),
        "default_character_name": "Pomao",
        "default_voice_description": "小只、安静、略带鼻音和一点点沙哑，但吐字要清楚",
        "default_model": str(RUNTIME.default_model),
        "default_index": str(RUNTIME.default_index),
        "default_song": str(RUNTIME.voice_pipeline_root / "input_song" / "cancel_send_20s_30s_test.wav"),
        "default_sample_dir": str(RUNTIME.projects_root / "demo_character_voice_samples" / "character" / "voice" / "samples"),
        "default_voice_id": "pomao_default",
        "available_sample_rates": RUNTIME.available_training_sample_rates,
    }


def ensure_default_voice() -> None:
    voices = load_voice_library(create=False)
    default_voice = {
        "id": "pomao_default",
        "name": "Pomao 默认声线",
        "description": "内置 Pomao 清晰自然声线，可直接用于翻唱。",
        "sample_path": "",
        "sample_dir": "",
        "model_path": str(RUNTIME.default_model),
        "index_path": str(RUNTIME.default_index),
        "ready": RUNTIME.default_model.is_file() and RUNTIME.default_index.is_file(),
    }
    existing = next((voice for voice in voices if voice.get("id") == "pomao_default"), None)
    if existing:
        model_path = Path(str(existing.get("model_path", "")))
        index_path = Path(str(existing.get("index_path", "")))
        if model_path.is_file() and index_path.is_file():
            existing["ready"] = True
            _write_json(VOICE_LIBRARY_PATH, {"voices": voices})
            return
        voices = [voice for voice in voices if voice.get("id") != "pomao_default"]
    voices.insert(0, default_voice)
    _write_json(VOICE_LIBRARY_PATH, {"voices": voices})


def load_voice_library(create: bool = True) -> list[dict[str, Any]]:
    if not VOICE_LIBRARY_PATH.exists():
        if create:
            _write_json(VOICE_LIBRARY_PATH, {"voices": []})
        return []
    data = _read_json(VOICE_LIBRARY_PATH)
    voices = []
    for item in data.get("voices", []):
        voice = dict(item)
        model_path = str(voice.get("model_path", "")).strip()
        index_path = str(voice.get("index_path", "")).strip()
        voice["ready"] = bool(model_path and index_path and Path(model_path).is_file() and Path(index_path).is_file())
        voices.append(voice)
    return voices


def save_voice_selection(payload: dict[str, Any]) -> dict[str, Any]:
    name = _required_text(payload, "name")
    raw_sample_path = str(payload.get("sample_path", "")).strip()
    sample_path = Path(raw_sample_path) if raw_sample_path else None
    if sample_path and not sample_path.exists():
        raise FileNotFoundError(f"sample_path not found: {sample_path}")
    model_path = Path(str(payload.get("model_path", ""))) if payload.get("model_path") else None
    index_path = Path(str(payload.get("index_path", ""))) if payload.get("index_path") else None
    if model_path and not model_path.is_file():
        raise FileNotFoundError(f"model_path file not found: {model_path}")
    if index_path and not index_path.is_file():
        raise FileNotFoundError(f"index_path file not found: {index_path}")

    voice_id = _slugify(name)
    voice = {
        "id": voice_id,
        "name": name,
        "description": str(payload.get("description", "")).strip(),
        "sample_path": str(sample_path) if sample_path else "",
        "sample_dir": str(payload.get("sample_dir", "")).strip(),
        "model_path": str(model_path) if model_path else "",
        "index_path": str(index_path) if index_path else "",
        "ready": bool(model_path and index_path),
    }
    voices = [item for item in load_voice_library() if item.get("id") != voice_id]
    voices.append(voice)
    _write_json(VOICE_LIBRARY_PATH, {"voices": voices})
    return voice


def update_voice(voice: dict[str, Any]) -> dict[str, Any]:
    voices = [item for item in load_voice_library() if item.get("id") != voice.get("id")]
    voices.append(voice)
    _write_json(VOICE_LIBRARY_PATH, {"voices": voices})
    return voice


def find_voice(voice_id: str) -> dict[str, Any]:
    ensure_default_voice()
    for voice in load_voice_library():
        if voice.get("id") == voice_id:
            return voice
    raise FileNotFoundError(f"Voice not found: {voice_id}")


def write_training_job_from_voice(payload: dict[str, Any]) -> Path:
    voice = find_voice(_required_text(payload, "voice_id"))
    sample_dir = _required_existing_path(str(voice.get("sample_dir", "")), "voice sample_dir")
    model_name = str(payload.get("model_name", f"{voice['id']}_voice_model")).strip() or f"{voice['id']}_voice_model"
    epochs = _parse_epochs(payload.get("epochs"))
    job_path = write_training_job({
        "character_name": voice.get("name", voice["id"]),
        "sample_dir": str(sample_dir),
        "model_name": model_name,
        "epochs": epochs,
        "voice_id": voice["id"],
        "sample_rate": payload.get("sample_rate"),
        "batch_size": payload.get("batch_size"),
        "save_every": payload.get("save_every"),
    })
    voice["training_job_path"] = str(job_path)
    voice["training_model_name"] = model_name
    update_voice(voice)
    return job_path


def auto_bind_trained_voice(job_path: Path) -> str:
    try:
        job = _read_json(job_path)
        voice_id = str((job.get("inputs", {}).get("voice", {}) or {}).get("voice_id", "")).strip()
        if not voice_id:
            return ""
        voice = bind_trained_voice({"voice_id": voice_id, "job_path": str(job_path)})
        return f"Auto-bound trained model to voice: {voice.get('name', voice_id)}"
    except Exception as exc:
        return f"Auto-bind trained voice failed: {exc}"


def bind_trained_voice(payload: dict[str, Any]) -> dict[str, Any]:
    voice = find_voice(_required_text(payload, "voice_id"))
    job_path = Path(str(payload.get("job_path") or voice.get("training_job_path", "")))
    if not job_path.exists():
        raise FileNotFoundError(f"Training job not found: {job_path}")
    status = job_status(job_path, {"running": False, "current_job": "", "messages": []})
    artifacts = status.get("artifacts") or {}
    model_path = _required_existing_file(str(artifacts.get("trained_model_path", "")), "trained model")
    index_path = _required_existing_file(str(artifacts.get("trained_index_path", "")), "trained index")
    voice["model_path"] = str(model_path)
    voice["index_path"] = str(index_path)
    voice["ready"] = True
    voice["training_job_path"] = str(job_path)
    return update_voice(voice)


def _voice_model_name(voice: dict[str, Any]) -> str:
    """Resolve the Applio model name for a voice's training checkpoints.

    Prefer the explicit training_model_name recorded at training time; fall
    back to the directory the bound model lives in (Applio names each
    checkpoint ``<model_name>_<N>e_<M>s.pth``).
    """
    name = str(voice.get("training_model_name", "")).strip()
    if name:
        return name
    model_path = str(voice.get("model_path", "")).strip()
    if model_path:
        return Path(model_path).parent.name
    return ""


def _checkpoint_epoch(path: Path, model_name: str) -> int:
    match = re.search(rf"{re.escape(model_name)}_(\d+)e_\d+s", path.stem)
    return int(match.group(1)) if match else -1


def list_voice_checkpoints(voice_id: str) -> dict[str, Any]:
    """List every saved training checkpoint for a voice's model.

    Checkpoints live in Applio's ``logs/<model_name>/`` and are the actionable
    way to pick an earlier epoch when the final one is overfit. The currently
    bound checkpoint is flagged so the UI can mark it.
    """
    voice = find_voice(voice_id)
    model_name = _voice_model_name(voice)
    bound_model = str(voice.get("model_path", "")).strip()
    bound_name = Path(bound_model).name if bound_model else ""
    checkpoints: list[dict[str, Any]] = []
    if model_name:
        logs_dir = RUNTIME.applio_root / "logs" / model_name
        if logs_dir.exists():
            matches = [
                p for p in logs_dir.glob(f"{model_name}_*e_*s.pth")
                if p.is_file() and _checkpoint_epoch(p, model_name) >= 0
            ]
            for path in sorted(matches, key=lambda p: _checkpoint_epoch(p, model_name)):
                checkpoints.append({
                    "name": path.name,
                    "epoch": _checkpoint_epoch(path, model_name),
                    "path": str(path),
                    "bound": path.name == bound_name,
                })
    return {
        "voice_id": voice_id,
        "model_name": model_name,
        "bound_model_path": bound_model,
        "checkpoints": checkpoints,
    }


def rebind_checkpoint(payload: dict[str, Any]) -> dict[str, Any]:
    """Point a voice at an earlier training checkpoint.

    Copies the chosen ``.pth`` into ``output/models/<model_name>/`` (alongside
    the shared ``.index``) and updates the voice's ``model_path``. The index is
    epoch-independent, so it is reused as-is.
    """
    voice = find_voice(_required_text(payload, "voice_id"))
    model_name = _voice_model_name(voice)
    checkpoint = _required_existing_file(str(payload.get("checkpoint_path", "")), "checkpoint")
    if _checkpoint_epoch(checkpoint, model_name) < 0:
        raise ValueError(f"Not a checkpoint for model '{model_name}': {checkpoint.name}")
    dest_dir = RUNTIME.models_root / model_name
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / checkpoint.name
    if checkpoint.resolve() != dest.resolve():
        shutil.copy2(checkpoint, dest)
    voice["model_path"] = str(dest)
    voice["ready"] = bool(str(voice.get("index_path", "")).strip())
    return update_voice(voice)


def load_separation_library(create: bool = True) -> list[dict[str, Any]]:
    if not SEPARATION_LIBRARY_PATH.exists():
        if create:
            _write_json(SEPARATION_LIBRARY_PATH, {"separations": []})
        return []
    data = _read_json(SEPARATION_LIBRARY_PATH)
    separations = []
    for item in data.get("separations", []):
        item = dict(item)
        item["ready"] = Path(str(item.get("vocals_path", ""))).exists() and Path(str(item.get("instrumental_path", ""))).exists()
        separations.append(item)
    return separations


def update_separation(record: dict[str, Any]) -> dict[str, Any]:
    records = [item for item in load_separation_library() if item.get("id") != record.get("id")]
    records.append(record)
    records.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
    _write_json(SEPARATION_LIBRARY_PATH, {"separations": records})
    return record


def auto_save_separation_result(job_path: Path) -> str:
    try:
        job = _read_json(job_path)
        steps = list(job.get("steps", []))
        if steps != ["check_runtime", "trim_song", "separate_vocals", "export_result"]:
            return ""
        song = job.get("inputs", {}).get("song", {})
        artifacts = job_status(job_path, {"running": False, "current_job": "", "messages": []}).get("artifacts") or {}
        vocals = _required_existing_path(str(artifacts.get("vocals", "")), "separated vocals")
        instrumental = _required_existing_path(str(artifacts.get("instrumental", "")), "separated instrumental")
        song_path = _required_existing_path(str(song.get("path", "")), "song")
        start_seconds = float(song.get("start_seconds", 0))
        duration_seconds = float(song.get("duration_seconds", 30))
        record_id = _slugify(f"{song_path.stem}_{start_seconds:.2f}_{duration_seconds:.2f}")
        record = {
            "id": record_id,
            "label": f"{song_path.stem} [{start_seconds:.2f}s - {start_seconds + duration_seconds:.2f}s]",
            "song_path": str(song_path),
            "start_seconds": start_seconds,
            "duration_seconds": duration_seconds,
            "job_path": str(job_path),
            "vocals_path": str(vocals),
            "instrumental_path": str(instrumental),
            "ready": True,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        update_separation(record)
        return f"Saved separation history: {record['label']}"
    except Exception as exc:
        return f"Save separation history failed: {exc}"


def load_cover_library(create: bool = True) -> list[dict[str, Any]]:
    if not COVER_LIBRARY_PATH.exists():
        if create:
            _write_json(COVER_LIBRARY_PATH, {"covers": []})
        return []
    data = _read_json(COVER_LIBRARY_PATH)
    covers = []
    for item in data.get("covers", []):
        item = dict(item)
        item["ready"] = Path(str(item.get("audio_path", ""))).is_file()
        covers.append(item)
    return covers


def update_cover(record: dict[str, Any]) -> dict[str, Any]:
    records = [item for item in load_cover_library() if item.get("id") != record.get("id")]
    records.append(record)
    records.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
    _write_json(COVER_LIBRARY_PATH, {"covers": records})
    return record


def auto_save_cover_result(job_path: Path) -> str:
    try:
        job = _read_json(job_path)
        steps = list(job.get("steps", []))
        if steps != ["check_runtime", "import_voice_model", "use_separated_audio", "convert_vocals", "mix_audio", "export_result"]:
            return ""
        song = job.get("inputs", {}).get("song", {})
        voice = job.get("inputs", {}).get("voice", {})
        artifacts = job_status(job_path, {"running": False, "current_job": "", "messages": []}).get("artifacts") or {}
        audio_path = _required_existing_file(str(artifacts.get("result_audio") or artifacts.get("final_mix") or ""), "cover audio")
        song_path = Path(str(song.get("path", "")))
        start_seconds = float(song.get("start_seconds", 0))
        duration_seconds = float(song.get("duration_seconds", 30))
        voice_id = str(voice.get("voice_id", "")).strip()
        label_base = song_path.stem if song_path.name else Path(audio_path).stem
        record_id = _slugify(f"{label_base}_{voice_id}_{start_seconds:.2f}_{duration_seconds:.2f}")
        record = {
            "id": record_id,
            "label": f"{label_base} / {voice_id or 'voice'} [{start_seconds:.2f}s - {start_seconds + duration_seconds:.2f}s]",
            "song_path": str(song_path),
            "voice_id": voice_id,
            "start_seconds": start_seconds,
            "duration_seconds": duration_seconds,
            "job_path": str(job_path),
            "audio_path": str(audio_path),
            "ready": True,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        update_cover(record)
        return f"Saved cover history: {record['label']}"
    except Exception as exc:
        return f"Save cover history failed: {exc}"


def list_voice_samples(job_path: Path) -> list[dict[str, str]]:
    if not job_path.exists():
        return []
    status = job_status(job_path, {"running": False, "current_job": "", "messages": []})
    artifacts = status.get("artifacts") or {}
    sample_dir = Path(str(artifacts.get("sample_dir", "")))
    if not sample_dir.exists():
        return []
    samples = []
    for path in sorted(sample_dir.glob("*.wav")):
        samples.append({"name": path.stem, "path": str(path), "url": f"/api/file?path={quote(str(path))}"})
    return samples


def _voice_sample_files(sample_dir: Path, limit: int = 4) -> list[Path]:
    """Pick a few representative training-sample audio files for F0 estimation.

    Skips our own denoise intermediates (same exclusion as the auto-epoch
    duration probe) so a file is not measured twice, and caps the count so the
    suggestion stays fast on large datasets.
    """
    exts = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac", ".opus"}
    files = [
        p
        for p in sorted(sample_dir.rglob("*"))
        if p.is_file() and p.suffix.lower() in exts and "denoise" not in p.parts
    ]
    return files[:limit]


def _separation_vocals_path(separation_job_path: str) -> Path:
    job_path = Path(separation_job_path)
    if not job_path.exists():
        raise FileNotFoundError("找不到对应的人声分离任务，请先完成第 3 步人声分离。")
    output_dir = Path(_read_json(job_path)["output_dir"])
    artifacts = _read_json_if_exists(output_dir / "artifacts.json") or {}
    return Path(str(artifacts.get("vocals", "")))


def suggest_cover_pitch(voice_id: str, separation_job_path: str) -> dict[str, Any]:
    """Recommend a cover transpose from the song's vocals vs. the voice's samples."""
    voice = find_voice(_require_nonempty(voice_id, "voice_id"))
    sample_dir = Path(str(voice.get("sample_dir", "")))
    if not sample_dir.exists():
        raise FileNotFoundError("该声线没有可用的训练素材目录，无法自动估计音高。")
    targets = _voice_sample_files(sample_dir)
    if not targets:
        raise FileNotFoundError("训练素材目录里没有可用的音频文件。")
    vocals = _separation_vocals_path(_require_nonempty(separation_job_path, "separation_job_path"))
    if not vocals.exists():
        raise FileNotFoundError("找不到分离出的人声文件，请先完成第 3 步人声分离。")
    return suggest_pitch_shift(vocals, targets)


def _require_nonempty(value: str, field: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError(f"缺少参数：{field}")
    return value


def list_jobs() -> list[dict[str, str]]:
    jobs_root = RUNTIME.app_root / "singing_app" / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    jobs = []
    for path in sorted(jobs_root.glob("*.json")):
        try:
            label = _read_json(path).get("job_id", path.stem)
        except Exception:
            label = path.stem
        jobs.append({"label": label, "path": str(path)})
    return jobs


def job_status(job_path: Path, runner_snapshot: dict[str, Any]) -> dict[str, Any]:
    status: dict[str, Any] = {"job_path": str(job_path), "runner": runner_snapshot}
    if not job_path.exists():
        return status | {"exists": False, "state": None, "artifacts": None, "logs": []}
    data = _read_json(job_path)
    output_dir = Path(data["output_dir"])
    return status | {
        "exists": True,
        "output_dir": str(output_dir),
        "state": _read_json_if_exists(output_dir / "state.json"),
        "artifacts": _read_json_if_exists(output_dir / "artifacts.json"),
        "logs": read_logs(output_dir / "logs"),
        "progress": _training_progress(output_dir / "logs")
        or _separation_progress(output_dir / "logs"),
    }


def _training_progress(logs_dir: Path) -> dict[str, Any] | None:
    """Parse epoch progress from the training log, if a training is underway.

    Applio writes one ``... | epoch=N | step=M | ...`` line per finished epoch
    and the launching command carries ``--total_epoch N``. Reading the full log
    here (not the truncated tail sent to the UI) keeps the total reliable even
    after many epochs. Returns None when there is no training log yet.
    """
    log_path = logs_dir / "train_voice_model.log"
    if not log_path.exists():
        return None
    text = log_path.read_text(encoding="utf-8", errors="replace")
    total_match = re.findall(r"--total_epoch\s+(\d+)", text)
    epoch_match = re.findall(r"\bepoch=(\d+)", text)
    total = int(total_match[-1]) if total_match else 0
    current = int(epoch_match[-1]) if epoch_match else 0
    done = "successfully completed" in text
    percent = 100 if done else (min(99, round(current / total * 100)) if total else 0)
    return {
        "phase": "train",
        "epoch": current,
        "total_epoch": total,
        "percent": percent,
        "done": done,
    }


def _separation_progress(logs_dir: Path) -> dict[str, Any] | None:
    """Parse demucs separation progress from the streamed separation log.

    Demucs prints ``Selected model is a bag of N models.`` for ensemble models
    (e.g. htdemucs_ft = 4) and runs ``--shifts`` passes per sub-model, emitting
    one tqdm bar (0->100%) per pass. So the total number of bars is
    ``bag * shifts`` and overall progress = (finished bars + current bar
    fraction) / total. ``run_command`` streams the log live (carriage-return
    tqdm frames included), so this updates while separation runs. Returns None
    when there is no separation log yet.
    """
    log_path = logs_dir / "separate_vocals.log"
    if not log_path.exists():
        return None
    text = log_path.read_text(encoding="utf-8", errors="replace")
    shifts_match = re.search(r"--shifts\s+(\d+)", text)
    shifts = int(shifts_match.group(1)) if shifts_match else 1
    bag_match = re.search(r"bag of (\d+) models", text)
    bag = int(bag_match.group(1)) if bag_match else 1
    total_bars = max(1, bag * max(1, shifts))

    completed = 0
    in_done = False
    current = 0
    seen_any = False
    for frame in re.split(r"[\r\n]", text):
        match = re.search(r"(\d+)%\|", frame)
        if not match:
            continue
        seen_any = True
        pct = int(match.group(1))
        if pct >= 100:
            if not in_done:
                completed += 1
                in_done = True
            current = 100
        else:
            in_done = False
            current = pct

    done = seen_any and completed >= total_bars
    if not seen_any:
        percent = 0
    else:
        partial = current / 100 if current < 100 else 0
        percent = 100 if done else min(99, round((completed + partial) / total_bars * 100))
    return {
        "phase": "separate",
        "bars_done": completed,
        "total_bars": total_bars,
        "percent": percent,
        "done": done,
    }


def read_logs(logs_dir: Path) -> list[dict[str, str]]:
    if not logs_dir.exists():
        return []
    logs = []
    for path in sorted(logs_dir.glob("*.log")):
        text = path.read_text(encoding="utf-8", errors="replace")
        logs.append({"name": path.name, "text": text[-12000:]})
    return logs


def _open_path(target: Path) -> None:
    if os.name == "nt":
        os.startfile(str(target))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", str(target)], check=False)
    else:
        subprocess.run(["xdg-open", str(target)], check=False)


def open_output_folder(job_path: Path) -> dict[str, str]:
    if not job_path.exists():
        raise FileNotFoundError(f"Job file not found: {job_path}")
    output_dir = Path(_read_json(job_path)["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    _open_path(output_dir)
    return {"opened": str(output_dir)}


def pick_file(kind: str = "any", initial: str = "") -> dict[str, str]:
    # On Linux, prefer the native GTK chooser (zenity): the Tk bundled with the
    # uv standalone Python is built without Xft, so its dialogs use scaled
    # bitmap fonts that look blurry on HiDPI. zenity renders crisply and returns
    # an absolute path. Windows/macOS keep the Tk dialog (native + crisp there).
    if sys.platform.startswith("linux") and shutil.which("zenity"):
        result = _pick_file_zenity(kind, initial)
        if result is not None:
            return result
    return _pick_file_tk(kind, initial)


def _pick_file_zenity(kind: str, initial: str) -> dict[str, str] | None:
    cmd = ["zenity", "--file-selection"]
    initial_path = Path(initial) if initial else None
    if kind == "folder":
        start = initial_path if initial_path and initial_path.is_dir() else RUNTIME.app_root
        cmd += ["--directory", "--title", "选择录音文件夹", f"--filename={start}/"]
    else:
        start = initial_path.parent if initial_path and initial_path.exists() else RUNTIME.app_root
        cmd += ["--title", _file_dialog_title(kind), f"--filename={start}/"]
        for label, pattern in _file_dialog_types(kind):
            cmd.append(f"--file-filter={label} | {pattern.replace('*.*', '*')}")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except Exception:
        return None
    if proc.returncode == 0:
        return {"path": proc.stdout.strip()}
    if proc.returncode == 1:  # user cancelled
        return {"path": ""}
    return None  # zenity error -> fall back to Tk


def _pick_file_tk(kind: str = "any", initial: str = "") -> dict[str, str]:
    try:
        root = tk.Tk()
    except tk.TclError:
        return {"path": "", "error": "无法打开文件对话框,请手动粘贴路径"}
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        initial_path = Path(initial) if initial else None
        if kind == "folder":
            initial_dir = str(initial_path if initial_path and initial_path.is_dir() else RUNTIME.app_root)
            path = filedialog.askdirectory(
                title="选择录音文件夹",
                initialdir=initial_dir,
                parent=root,
            )
            return {"path": str(path) if path else ""}
        initial_dir = str(initial_path.parent if initial_path and initial_path.exists() else RUNTIME.app_root)
        filetypes = _file_dialog_types(kind)
        path = filedialog.askopenfilename(
            title=_file_dialog_title(kind),
            initialdir=initial_dir,
            filetypes=filetypes,
            parent=root,
        )
        return {"path": str(path) if path else ""}
    finally:
        root.destroy()


def _file_dialog_title(kind: str) -> str:
    if kind == "image":
        return "选择角色图片"
    if kind == "audio":
        return "选择音乐文件"
    if kind == "job":
        return "选择 Job JSON"
    return "选择文件"


def _file_dialog_types(kind: str) -> list[tuple[str, str]]:
    if kind == "image":
        return [("Image files", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All files", "*.*")]
    if kind == "audio":
        return [("Audio files", "*.wav *.mp3 *.flac *.m4a *.aac *.ogg"), ("All files", "*.*")]
    if kind == "job":
        return [("Job JSON", "*.json"), ("All files", "*.*")]
    return [("All files", "*.*")]


def write_audio_cover_job(payload: dict[str, Any]) -> Path:
    character_name = _required_text(payload, "character_name")
    song_path = _required_path(payload, "song_path")
    voice_id = _required_text(payload, "voice_id")
    voice = find_voice(voice_id)
    if not voice.get("model_path") or not voice.get("index_path"):
        raise ValueError("这个历史声线还没有可用模型，请先训练后再生成翻唱音频。")
    model_path = _required_existing_file(voice["model_path"], "voice model")
    index_path = _required_existing_file(voice["index_path"], "voice index")
    separation = load_separation_artifacts(
        str(payload.get("separation_job_path", "")).strip(),
        validate=not bool(payload.get("dry_run", False)),
    )
    if not separation:
        raise ValueError("请先完成人声分离，或从分离历史选择一个结果。")

    character_id = _slugify(character_name)
    job_id = f"{character_id}_cover_audio"
    project_dir = RUNTIME.projects_root / job_id
    job_path = _job_path(job_id)
    _write_json(job_path, {
        "job_id": job_id,
        "output_dir": str(project_dir),
        "steps": ["check_runtime", "import_voice_model", "use_separated_audio", "convert_vocals", "mix_audio", "export_result"],
        "inputs": {
            "voice": {"model_name": model_path.stem, "model_path": str(model_path), "index_path": str(index_path), "voice_id": voice_id},
            "song": {
                "path": str(song_path),
                "start_seconds": float(payload.get("start_seconds", 0)),
                "duration_seconds": float(payload.get("duration_seconds", 30)),
                "vocals_path": separation["vocals"],
                "instrumental_path": separation["instrumental"],
            },
        },
        "settings": {
            "rvc": {
                "pitch": int(payload.get("pitch", 0) or 0),
                "index_rate": float(payload.get("index_rate", 0.7) or 0.7),
                "protect": float(payload.get("protect", 0.45) or 0.45),
                "clean_audio": bool(payload.get("clean_audio", False)),
                "clean_strength": float(payload.get("clean_strength", 0.3) or 0.3),
            },
            "mix": {"instrumental_volume": 0.88, "vocal_volume": 1.12},
        },
    })
    return job_path


def write_separation_job(payload: dict[str, Any]) -> Path:
    song_path = _required_path(payload, "song_path")
    song_id = _slugify(Path(song_path).stem)
    job_id = f"{song_id}_vocal_separation"
    project_dir = RUNTIME.projects_root / job_id
    job_path = _job_path(job_id)
    model_id = str(payload.get("separation_model") or DEFAULT_SEPARATION_MODEL).strip()
    model = resolve_separation_model(model_id)
    if model is None:
        raise ValueError(f"未知的分离模型: {model_id}")
    if not next(
        (m["available"] for m in list_separation_models() if m["id"] == model_id),
        False,
    ):
        raise ValueError(
            f"分离模型「{model['label']}」尚未安装，无法使用。"
            "请先安装 audio-separator 包并下载对应权重，或改用 Demucs 模型。"
        )
    _write_json(job_path, {
        "job_id": job_id,
        "output_dir": str(project_dir),
        "steps": ["check_runtime", "trim_song", "separate_vocals", "export_result"],
        "inputs": {
            "song": {
                "path": str(song_path),
                "start_seconds": float(payload.get("start_seconds", 0)),
                "duration_seconds": float(payload.get("duration_seconds", 30)),
            },
        },
        "settings": {"separation": {"model": model_id}},
    })
    return job_path


def load_separation_artifacts(job_path_value: str, validate: bool = True) -> dict[str, str]:
    if not job_path_value:
        return {}
    job_path = Path(job_path_value)
    if not job_path.exists():
        raise FileNotFoundError(f"Separation job not found: {job_path}")
    artifacts = job_status(job_path, {"running": False, "current_job": "", "messages": []}).get("artifacts") or {}
    vocals = str(artifacts.get("vocals", "")).strip()
    instrumental = str(artifacts.get("instrumental", "")).strip()
    if validate:
        if not vocals or not instrumental:
            raise ValueError(f"Separation artifacts are not ready: {job_path}")
        vocals = str(_required_existing_path(vocals, "separated vocals"))
        instrumental = str(_required_existing_path(instrumental, "separated instrumental"))
    elif not vocals or not instrumental:
        raise ValueError(f"Separation artifacts are not ready: {job_path}")
    return {"vocals": vocals, "instrumental": instrumental}


def write_voice_sample_job(payload: dict[str, Any]) -> Path:
    character_name = _required_text(payload, "character_name")
    character_id = _slugify(character_name)
    job_id = f"{character_id}_voice_samples"
    project_dir = RUNTIME.projects_root / job_id
    job_path = _job_path(job_id)
    _write_json(job_path, {
        "job_id": job_id,
        "output_dir": str(project_dir),
        "steps": ["check_runtime", "create_character", "generate_training_text", "generate_voice_samples", "export_result"],
        "inputs": {
            "character": {"id": character_id, "name": character_name, "root_dir": str(project_dir / "character"), "voice_description": str(payload.get("voice_description", "")).strip()},
            "voice": {
                "model_name": f"{character_id}_voice",
                "tts_engine": str(payload.get("tts_engine", "edge_tts")).strip() or "edge_tts",
                "tts_voice": str(payload.get("tts_voice", "zh-CN-YunxiNeural")).strip() or "zh-CN-YunxiNeural",
                "voice_preset": str(payload.get("voice_preset", "")).strip(),
                "training_text": str(payload.get("training_text", "")).strip(),
                "reference_audio": str(payload.get("reference_audio", "")).strip(),
                "reference_text": str(payload.get("reference_text", "")).strip(),
            },
        },
        "settings": {},
    })
    return job_path


def _parse_epochs(value: Any) -> Any:
    """Normalize an epochs payload value to an int or the sentinel 'auto'.

    Empty/missing/'auto' means let the runner pick epochs from data length.
    """
    if value is None or str(value).strip() == "" or str(value).strip().lower() == "auto":
        return "auto"
    epochs = int(value)
    if epochs < 1:
        raise ValueError("Epochs must be >= 1.")
    return epochs


def _apply_train_tuning(voice_inputs: dict[str, Any], payload: dict[str, Any]) -> None:
    """Thread optional quality/perf training knobs into voice_inputs.

    Only set keys the caller provided so runner defaults stay authoritative.
    Sample rate is the exception: when unset, default to the highest rate that
    has a usable HiFi-GAN base on this machine (quality-optimal yet safe — it
    never selects a rate whose pretrained weights are missing).
    """
    for key in ("sample_rate", "batch_size", "save_every"):
        value = payload.get(key)
        if value not in (None, ""):
            voice_inputs[key] = int(value)
    if "sample_rate" not in voice_inputs:
        voice_inputs["sample_rate"] = max(RUNTIME.available_training_sample_rates)


def write_training_job(payload: dict[str, Any]) -> Path:
    character_name = _required_text(payload, "character_name")
    sample_dir = _required_path(payload, "sample_dir")
    model_name = _required_text(payload, "model_name")
    epochs = _parse_epochs(payload.get("epochs"))
    character_id = _slugify(character_name)
    job_id = f"{character_id}_train_{_slugify(model_name)}"
    project_dir = RUNTIME.projects_root / job_id
    job_path = _job_path(job_id)
    voice_inputs = {"model_name": model_name, "dataset_path": str(sample_dir), "epochs": epochs}
    voice_id = str(payload.get("voice_id", "")).strip()
    if voice_id:
        voice_inputs["voice_id"] = voice_id
    _apply_train_tuning(voice_inputs, payload)
    _write_json(job_path, {
        "job_id": job_id,
        "output_dir": str(project_dir),
        "steps": ["check_runtime", "train_voice_model", "export_result"],
        "inputs": {"voice": voice_inputs},
        "settings": {},
    })
    return job_path


def write_recording_prepare_job(payload: dict[str, Any]) -> Path:
    """Step 1 for recordings: normalize them into a training-ready sample_dir.

    Mirrors what AI-generated auditions produce, so step 2 (training) is a
    single unified flow for both material sources — no per-source branching.
    Denoising (demucs) happens here, up front, so the resulting wavs are clean
    and ready to train on directly.
    """
    character_name = _required_text(payload, "character_name")
    recordings = payload.get("recordings", "")
    if not (isinstance(recordings, list) and recordings) and not str(recordings).strip():
        raise ValueError("recordings is required (a folder of audio files or a list of paths).")
    character_id = _slugify(character_name)
    job_id = f"{character_id}_recprep"
    project_dir = RUNTIME.projects_root / job_id
    job_path = _job_path(job_id)
    voice_inputs: dict[str, Any] = {"recordings": recordings}
    if payload.get("preprocess_vocals"):
        voice_inputs["preprocess_vocals"] = True
    separation_model = str(payload.get("separation_model", "")).strip()
    if separation_model:
        voice_inputs["separation_model"] = separation_model
    _write_json(job_path, {
        "job_id": job_id,
        "output_dir": str(project_dir),
        "steps": [
            "check_runtime",
            "create_character",
            "prepare_recordings",
            "export_result",
        ],
        "inputs": {
            "character": {
                "id": character_id,
                "name": character_name,
                "root_dir": str(project_dir / "character"),
                "voice_description": str(payload.get("voice_description", "")).strip(),
            },
            "voice": voice_inputs,
        },
        "settings": {},
    })
    return job_path


def _job_path(job_id: str) -> Path:
    path = RUNTIME.app_root / "singing_app" / "jobs" / f"{job_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ValueError(f"{key} is required.")
    return value


def _required_path(payload: dict[str, Any], key: str) -> Path:
    return _required_existing_path(_required_text(payload, key), key)


def _required_file(payload: dict[str, Any], key: str) -> Path:
    return _required_existing_file(_required_text(payload, key), key)


def _required_existing_path(value: str, label: str) -> Path:
    path = Path(value)
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path


def _required_existing_file(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_file():
        raise FileNotFoundError(f"{label} file not found: {path}")
    return path


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    audio_types = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
        ".opus": "audio/ogg",
    }
    if suffix in audio_types:
        return audio_types[suffix]
    if suffix == ".mp4":
        return "video/mp4"
    return "application/octet-stream"


def _slugify(value: str) -> str:
    try:
        from pypinyin import lazy_pinyin

        value = "".join(lazy_pinyin(value))
    except Exception:
        pass
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_").lower() or "character"


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _read_json_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    return _read_json(path)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def run_web_server(host: str = "127.0.0.1", port: int = 7860, open_browser: bool = True) -> None:
    SingingWebHandler.manager = WebJobManager()
    server = ThreadingHTTPServer((host, port), SingingWebHandler)
    url = f"http://{host}:{port}"
    print(f"AI Singing Video web UI: {url}")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    server.serve_forever()


def main() -> None:
    run_web_server()


if __name__ == "__main__":
    main()

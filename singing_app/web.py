from __future__ import annotations

import json
import os
import re
import threading
import tkinter as tk
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tkinter import filedialog
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from singing_app.config import RUNTIME
from singing_app.harness.runner import HarnessRunner
from singing_app.runtime_check import checks_as_dicts


STATIC_ROOT = Path(__file__).resolve().parent / "web_static"
VOICE_LIBRARY_PATH = RUNTIME.app_root / "singing_app" / "voice_library.json"


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
            elif parsed.path == "/api/samples":
                job_path = Path(parse_qs(parsed.query).get("job_path", [""])[0])
                self._send_json({"samples": list_voice_samples(job_path)})
            elif parsed.path == "/api/file":
                file_path = Path(parse_qs(parsed.query).get("path", [""])[0])
                self._send_file(file_path, _content_type(file_path))
            elif parsed.path == "/api/status":
                job_path = Path(parse_qs(parsed.query).get("job_path", [""])[0])
                self._send_json(job_status(job_path, self.manager.snapshot()))
            elif parsed.path == "/api/open-output":
                job_path = Path(parse_qs(parsed.query).get("job_path", [""])[0])
                self._send_json(open_output_folder(job_path))
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
            if parsed.path == "/api/create-video-job":
                self._send_json({"job_path": str(write_video_job(payload))})
            elif parsed.path == "/api/create-separation-job":
                self._send_json({"job_path": str(write_separation_job(payload))})
            elif parsed.path == "/api/create-voice-job":
                self._send_json({"job_path": str(write_voice_sample_job(payload))})
            elif parsed.path == "/api/create-training-job":
                self._send_json({"job_path": str(write_training_job(payload))})
            elif parsed.path == "/api/create-training-from-voice":
                self._send_json({"job_path": str(write_training_job_from_voice(payload))})
            elif parsed.path == "/api/bind-trained-voice":
                self._send_json({"voice": bind_trained_voice(payload)})
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

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        if path.name == "index.html":
            self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def default_values() -> dict[str, str]:
    ensure_default_voice()
    return {
        "app_root": str(RUNTIME.app_root),
        "jobs_root": str(RUNTIME.app_root / "singing_app" / "jobs"),
        "projects_root": str(RUNTIME.projects_root),
        "default_job": str(RUNTIME.app_root / "singing_app" / "jobs" / "pomao_demo_job.json"),
        "default_character_name": "Pomao",
        "default_voice_description": "小只、安静、略带鼻音和一点点沙哑，但吐字要清楚",
        "default_character_image": str(RUNTIME.voice_pipeline_root / "Generated_image.png"),
        "default_model": str(RUNTIME.default_model),
        "default_index": str(RUNTIME.default_index),
        "default_song": str(RUNTIME.voice_pipeline_root / "input_song" / "cancel_send_20s_30s_test.wav"),
        "default_sample_dir": str(RUNTIME.projects_root / "demo_character_voice_samples" / "character" / "voice" / "samples"),
        "default_voice_id": "pomao_default",
    }


def ensure_default_voice() -> None:
    voices = load_voice_library(create=False)
    if any(voice.get("id") == "pomao_default" for voice in voices):
        return
    voices.insert(0, {
        "id": "pomao_default",
        "name": "Pomao 默认声线",
        "description": "内置 Pomao 清晰自然声线，可直接用于翻唱。",
        "sample_path": "",
        "sample_dir": "",
        "model_path": str(RUNTIME.default_model),
        "index_path": str(RUNTIME.default_index),
        "ready": RUNTIME.default_model.exists() and RUNTIME.default_index.exists(),
    })
    _write_json(VOICE_LIBRARY_PATH, {"voices": voices})


def load_voice_library(create: bool = True) -> list[dict[str, Any]]:
    if not VOICE_LIBRARY_PATH.exists():
        if create:
            _write_json(VOICE_LIBRARY_PATH, {"voices": []})
        return []
    data = _read_json(VOICE_LIBRARY_PATH)
    return list(data.get("voices", []))


def save_voice_selection(payload: dict[str, Any]) -> dict[str, Any]:
    name = _required_text(payload, "name")
    raw_sample_path = str(payload.get("sample_path", "")).strip()
    sample_path = Path(raw_sample_path) if raw_sample_path else None
    if sample_path and not sample_path.exists():
        raise FileNotFoundError(f"sample_path not found: {sample_path}")
    model_path = Path(str(payload.get("model_path", ""))) if payload.get("model_path") else None
    index_path = Path(str(payload.get("index_path", ""))) if payload.get("index_path") else None
    if model_path and not model_path.exists():
        raise FileNotFoundError(f"model_path not found: {model_path}")
    if index_path and not index_path.exists():
        raise FileNotFoundError(f"index_path not found: {index_path}")

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
    model_name = str(payload.get("model_name", f"{voice['id']}_voice")).strip() or f"{voice['id']}_voice"
    epochs = int(payload.get("epochs", 5))
    job_path = write_training_job({
        "character_name": voice.get("name", voice["id"]),
        "sample_dir": str(sample_dir),
        "model_name": model_name,
        "epochs": epochs,
        "voice_id": voice["id"],
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
    model_path = _required_existing_path(str(artifacts.get("trained_model_path", "")), "trained model")
    index_path = _required_existing_path(str(artifacts.get("trained_index_path", "")), "trained index")
    voice["model_path"] = str(model_path)
    voice["index_path"] = str(index_path)
    voice["ready"] = True
    voice["training_job_path"] = str(job_path)
    return update_voice(voice)


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
    }


def read_logs(logs_dir: Path) -> list[dict[str, str]]:
    if not logs_dir.exists():
        return []
    logs = []
    for path in sorted(logs_dir.glob("*.log")):
        text = path.read_text(encoding="utf-8", errors="replace")
        logs.append({"name": path.name, "text": text[-12000:]})
    return logs


def open_output_folder(job_path: Path) -> dict[str, str]:
    if not job_path.exists():
        raise FileNotFoundError(f"Job file not found: {job_path}")
    output_dir = Path(_read_json(job_path)["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    os.startfile(str(output_dir))
    return {"opened": str(output_dir)}


def pick_file(kind: str = "any", initial: str = "") -> dict[str, str]:
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        initial_path = Path(initial) if initial else None
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


def write_video_job(payload: dict[str, Any]) -> Path:
    character_name = _required_text(payload, "character_name")
    song_path = _required_path(payload, "song_path")
    character_image = _required_path(payload, "character_image")
    voice_id = str(payload.get("voice_id", "")).strip()
    if voice_id:
        voice = find_voice(voice_id)
        if not voice.get("model_path") or not voice.get("index_path"):
            raise ValueError("这个历史声线还没有可用模型，请先训练或导入 .pth/.index 后再翻唱。")
        model_path = _required_existing_path(voice["model_path"], "voice model")
        index_path = _required_existing_path(voice["index_path"], "voice index")
    else:
        model_path = _required_path(payload, "model_path")
        index_path = _required_path(payload, "index_path")
    character_id = _slugify(character_name)
    job_id = f"{character_id}_singing_video"
    project_dir = RUNTIME.projects_root / job_id
    job_path = _job_path(job_id)
    separation = load_separation_artifacts(
        str(payload.get("separation_job_path", "")).strip(),
        validate=not bool(payload.get("dry_run", False)),
    )
    song_inputs: dict[str, Any] = {
        "path": str(song_path),
        "start_seconds": float(payload.get("start_seconds", 0)),
        "duration_seconds": float(payload.get("duration_seconds", 30)),
    }
    if separation:
        steps = ["check_runtime", "create_character", "generate_training_text", "import_voice_model", "use_separated_audio", "convert_vocals", "mix_audio", "compose_video", "export_result"]
        song_inputs["vocals_path"] = separation["vocals"]
        song_inputs["instrumental_path"] = separation["instrumental"]
    else:
        steps = ["check_runtime", "create_character", "generate_training_text", "import_voice_model", "trim_song", "separate_vocals", "convert_vocals", "mix_audio", "compose_video", "export_result"]
    _write_json(job_path, {
        "job_id": job_id,
        "output_dir": str(project_dir),
        "steps": steps,
        "inputs": {
            "character": {"id": character_id, "name": character_name, "root_dir": str(project_dir / "character"), "voice_description": str(payload.get("voice_description", "")).strip(), "image_path": str(character_image), "mouth_shape_paths": [str(character_image)]},
            "voice": {"model_name": model_path.stem, "model_path": str(model_path), "index_path": str(index_path), "voice_id": voice_id},
            "song": song_inputs,
            "video": {"character_image": str(character_image)},
        },
        "settings": {"rvc": {"pitch": 0, "index_rate": 0.25, "protect": 0.45}, "mix": {"instrumental_volume": 0.88, "vocal_volume": 1.12}},
    })
    return job_path


def write_separation_job(payload: dict[str, Any]) -> Path:
    song_path = _required_path(payload, "song_path")
    song_id = _slugify(Path(song_path).stem)
    job_id = f"{song_id}_vocal_separation"
    project_dir = RUNTIME.projects_root / job_id
    job_path = _job_path(job_id)
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
        "settings": {},
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
    character_image = _required_path(payload, "character_image")
    character_id = _slugify(character_name)
    job_id = f"{character_id}_voice_samples"
    project_dir = RUNTIME.projects_root / job_id
    job_path = _job_path(job_id)
    _write_json(job_path, {
        "job_id": job_id,
        "output_dir": str(project_dir),
        "steps": ["check_runtime", "create_character", "generate_training_text", "generate_voice_samples", "export_result"],
        "inputs": {
            "character": {"id": character_id, "name": character_name, "root_dir": str(project_dir / "character"), "voice_description": str(payload.get("voice_description", "")).strip(), "image_path": str(character_image), "mouth_shape_paths": [str(character_image)]},
            "voice": {"model_name": f"{character_id}_voice", "tts_voice": str(payload.get("tts_voice", "zh-CN-YunxiNeural")).strip() or "zh-CN-YunxiNeural"},
        },
        "settings": {},
    })
    return job_path


def write_training_job(payload: dict[str, Any]) -> Path:
    character_name = _required_text(payload, "character_name")
    sample_dir = _required_path(payload, "sample_dir")
    model_name = _required_text(payload, "model_name")
    epochs = int(payload.get("epochs", 5))
    if epochs < 1:
        raise ValueError("Epochs must be >= 1.")
    character_id = _slugify(character_name)
    job_id = f"{character_id}_train_{_slugify(model_name)}"
    project_dir = RUNTIME.projects_root / job_id
    job_path = _job_path(job_id)
    voice_inputs = {"model_name": model_name, "dataset_path": str(sample_dir), "epochs": epochs}
    voice_id = str(payload.get("voice_id", "")).strip()
    if voice_id:
        voice_inputs["voice_id"] = voice_id
    _write_json(job_path, {
        "job_id": job_id,
        "output_dir": str(project_dir),
        "steps": ["check_runtime", "train_voice_model", "export_result"],
        "inputs": {"voice": voice_inputs},
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


def _required_existing_path(value: str, label: str) -> Path:
    path = Path(value)
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".wav":
        return "audio/wav"
    if suffix == ".mp3":
        return "audio/mpeg"
    if suffix == ".mp4":
        return "video/mp4"
    return "application/octet-stream"


def _slugify(value: str) -> str:
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

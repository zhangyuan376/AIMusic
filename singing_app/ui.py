from __future__ import annotations

import json
import os
import queue
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from singing_app.config import RUNTIME
from singing_app.harness.runner import HarnessRunner
from singing_app.runtime_check import run_runtime_checks


class SingingAppUi(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("AI Singing Video Harness")
        self.geometry("980x680")
        self.minsize(900, 620)

        self.job_path = tk.StringVar(value=str(RUNTIME.app_root / "singing_app" / "jobs" / "pomao_demo_job.json"))
        self.dry_run = tk.BooleanVar(value=True)
        self.no_resume = tk.BooleanVar(value=False)
        self.character_name = tk.StringVar(value="Demo Character")
        self.voice_description = tk.StringVar(value="小只、安静、略带鼻音和一点点沙哑，但吐字要清楚")
        self.song_path = tk.StringVar(value=str(RUNTIME.voice_pipeline_root / "input_song" / "cancel_send_20s_30s_test.wav"))
        self.character_image = tk.StringVar(value=str(RUNTIME.voice_pipeline_root / "Generated_image.png"))
        self.model_path = tk.StringVar(value=str(RUNTIME.default_model))
        self.index_path = tk.StringVar(value=str(RUNTIME.default_index))
        self.tts_voice = tk.StringVar(value="zh-CN-YunxiNeural")
        self.sample_dir = tk.StringVar(
            value=str(RUNTIME.projects_root / "demo_character_voice_samples" / "character" / "voice" / "samples")
        )
        self.train_model_name = tk.StringVar(value="demo_character_voice")
        self.train_epochs = tk.StringVar(value="5")
        self.start_seconds = tk.StringVar(value="0")
        self.duration_seconds = tk.StringVar(value="30")
        self.status_queue: queue.Queue[str] = queue.Queue()
        self.running_thread: threading.Thread | None = None

        self._build_layout()
        self._poll_queue()
        self.refresh_status()

    def _build_layout(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        self.tabs = ttk.Notebook(root)
        self.tabs.pack(fill=tk.BOTH, expand=True)

        builder_tab = ttk.Frame(self.tabs, padding=8)
        voice_tab = ttk.Frame(self.tabs, padding=8)
        train_tab = ttk.Frame(self.tabs, padding=8)
        runtime_tab = ttk.Frame(self.tabs, padding=8)
        harness_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(builder_tab, text="Create Singing Video")
        self.tabs.add(voice_tab, text="Voice Builder")
        self.tabs.add(train_tab, text="Train Model")
        self.tabs.add(runtime_tab, text="Runtime Check")
        self.tabs.add(harness_tab, text="Harness Status")

        self._build_builder_tab(builder_tab)
        self._build_voice_tab(voice_tab)
        self._build_train_tab(train_tab)
        self._build_runtime_tab(runtime_tab)
        self._build_harness_tab(harness_tab)

    def _build_builder_tab(self, root: ttk.Frame) -> None:
        form = ttk.LabelFrame(root, text="Simple Job Builder")
        form.pack(fill=tk.X)

        self._path_row(form, 0, "Song", self.song_path, self.choose_song)
        self._path_row(form, 1, "Character image", self.character_image, self.choose_character_image)
        self._path_row(form, 2, "Voice model (.pth)", self.model_path, self.choose_model)
        self._path_row(form, 3, "Voice index (.index)", self.index_path, self.choose_index)

        ttk.Label(form, text="Character name").grid(row=4, column=0, sticky=tk.W, padx=8, pady=6)
        ttk.Entry(form, textvariable=self.character_name).grid(row=4, column=1, sticky=tk.EW, padx=8, pady=6)

        ttk.Label(form, text="Voice description").grid(row=5, column=0, sticky=tk.W, padx=8, pady=6)
        ttk.Entry(form, textvariable=self.voice_description).grid(row=5, column=1, sticky=tk.EW, padx=8, pady=6)

        times = ttk.Frame(form)
        times.grid(row=6, column=1, sticky=tk.W, padx=8, pady=6)
        ttk.Label(form, text="Clip").grid(row=6, column=0, sticky=tk.W, padx=8, pady=6)
        ttk.Label(times, text="Start").pack(side=tk.LEFT)
        ttk.Entry(times, textvariable=self.start_seconds, width=8).pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(times, text="Duration").pack(side=tk.LEFT)
        ttk.Entry(times, textvariable=self.duration_seconds, width=8).pack(side=tk.LEFT, padx=(4, 12))

        form.columnconfigure(1, weight=1)

        actions = ttk.Frame(root)
        actions.pack(fill=tk.X, pady=12)
        ttk.Checkbutton(actions, text="Dry run", variable=self.dry_run).pack(side=tk.LEFT)
        ttk.Button(actions, text="Create Job JSON", command=self.create_job_from_form).pack(side=tk.LEFT, padx=10)
        ttk.Button(actions, text="Create And Run", command=self.create_and_run_job).pack(side=tk.LEFT)

        hint = (
            "第一版先用已导入/已训练的 RVC 模型做全流程出片。"
            "声线样本生成和训练已经在 harness 中有步骤，后续会接成单独的可视化页面。"
        )
        ttk.Label(root, text=hint, wraplength=860).pack(anchor=tk.W, pady=8)

    def _build_voice_tab(self, root: ttk.Frame) -> None:
        form = ttk.LabelFrame(root, text="Voice Sample Builder")
        form.pack(fill=tk.X)

        ttk.Label(form, text="Character name").grid(row=0, column=0, sticky=tk.W, padx=8, pady=6)
        ttk.Entry(form, textvariable=self.character_name).grid(row=0, column=1, sticky=tk.EW, padx=8, pady=6)

        ttk.Label(form, text="Voice description").grid(row=1, column=0, sticky=tk.W, padx=8, pady=6)
        ttk.Entry(form, textvariable=self.voice_description).grid(row=1, column=1, sticky=tk.EW, padx=8, pady=6)

        ttk.Label(form, text="TTS voice").grid(row=2, column=0, sticky=tk.W, padx=8, pady=6)
        ttk.Entry(form, textvariable=self.tts_voice).grid(row=2, column=1, sticky=tk.EW, padx=8, pady=6)

        self._path_row(form, 3, "Character image", self.character_image, self.choose_character_image)
        form.columnconfigure(1, weight=1)

        actions = ttk.Frame(root)
        actions.pack(fill=tk.X, pady=12)
        ttk.Checkbutton(actions, text="Dry run", variable=self.dry_run).pack(side=tk.LEFT)
        ttk.Button(actions, text="Create Voice Sample Job", command=self.create_voice_sample_job).pack(side=tk.LEFT, padx=10)
        ttk.Button(actions, text="Create And Run Samples", command=self.create_and_run_voice_sample_job).pack(side=tk.LEFT)

        info = (
            "这个页签会生成角色 character.json、训练文本和 TTS 训练样本。"
            "正式运行会联网调用 Edge TTS；CPU 训练模型会在下一步接入。"
        )
        ttk.Label(root, text=info, wraplength=860).pack(anchor=tk.W, pady=8)

    def _build_train_tab(self, root: ttk.Frame) -> None:
        form = ttk.LabelFrame(root, text="Model Trainer")
        form.pack(fill=tk.X)

        ttk.Label(form, text="Character name").grid(row=0, column=0, sticky=tk.W, padx=8, pady=6)
        ttk.Entry(form, textvariable=self.character_name).grid(row=0, column=1, sticky=tk.EW, padx=8, pady=6)

        ttk.Label(form, text="Model name").grid(row=1, column=0, sticky=tk.W, padx=8, pady=6)
        ttk.Entry(form, textvariable=self.train_model_name).grid(row=1, column=1, sticky=tk.EW, padx=8, pady=6)

        ttk.Label(form, text="Epochs").grid(row=2, column=0, sticky=tk.W, padx=8, pady=6)
        ttk.Entry(form, textvariable=self.train_epochs).grid(row=2, column=1, sticky=tk.W, padx=8, pady=6)

        self._path_row(form, 3, "Sample directory", self.sample_dir, self.choose_sample_dir)
        form.columnconfigure(1, weight=1)

        actions = ttk.Frame(root)
        actions.pack(fill=tk.X, pady=12)
        ttk.Checkbutton(actions, text="Dry run", variable=self.dry_run).pack(side=tk.LEFT)
        ttk.Button(actions, text="Create Training Job", command=self.create_training_job).pack(side=tk.LEFT, padx=10)
        ttk.Button(actions, text="Create And Run Training", command=self.create_and_run_training_job).pack(side=tk.LEFT)

        info = (
            "训练会非常慢，尤其是没有 NVIDIA GPU 的机器。"
            "建议先 dry-run 检查路径，确认后再关闭 dry-run 正式训练。"
        )
        ttk.Label(root, text=info, wraplength=860).pack(anchor=tk.W, pady=8)

    def _build_runtime_tab(self, root: ttk.Frame) -> None:
        actions = ttk.Frame(root)
        actions.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(actions, text="Run Runtime Check", command=self.refresh_runtime_checks).pack(side=tk.LEFT)

        columns = ("name", "status", "message", "path")
        self.runtime_tree = ttk.Treeview(root, columns=columns, show="headings", height=16)
        for column, width in (("name", 180), ("status", 80), ("message", 220), ("path", 460)):
            self.runtime_tree.heading(column, text=column.title())
            self.runtime_tree.column(column, width=width, anchor=tk.W)
        self.runtime_tree.pack(fill=tk.BOTH, expand=True)

        note = (
            "安装器和首次启动会复用这些检测项。"
            "如果这里有 Missing，应用应提示一键修复或重新安装运行时。"
        )
        ttk.Label(root, text=note, wraplength=860).pack(anchor=tk.W, pady=8)
        self.refresh_runtime_checks()

    def _build_harness_tab(self, root: ttk.Frame) -> None:
        job_frame = ttk.LabelFrame(root, text="Job")
        job_frame.pack(fill=tk.X)
        ttk.Entry(job_frame, textvariable=self.job_path).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8, pady=8)
        ttk.Button(job_frame, text="Choose...", command=self.choose_job).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(job_frame, text="Refresh", command=self.refresh_status).pack(side=tk.LEFT, padx=(0, 8))

        controls = ttk.Frame(root)
        controls.pack(fill=tk.X, pady=10)
        ttk.Checkbutton(controls, text="Dry run", variable=self.dry_run).pack(side=tk.LEFT)
        ttk.Checkbutton(controls, text="Run from first step", variable=self.no_resume).pack(side=tk.LEFT, padx=16)
        ttk.Button(controls, text="Run Job", command=self.run_job).pack(side=tk.LEFT, padx=8)
        ttk.Button(controls, text="Open Output Folder", command=self.open_output_folder).pack(side=tk.LEFT, padx=8)
        ttk.Button(controls, text="Open Logs Folder", command=self.open_logs_folder).pack(side=tk.LEFT, padx=8)

        panes = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(panes)
        right = ttk.Frame(panes)
        panes.add(left, weight=1)
        panes.add(right, weight=1)

        ttk.Label(left, text="State").pack(anchor=tk.W)
        self.state_text = tk.Text(left, wrap=tk.NONE, height=18)
        self.state_text.pack(fill=tk.BOTH, expand=True)

        ttk.Label(right, text="Artifacts").pack(anchor=tk.W)
        self.artifacts_text = tk.Text(right, wrap=tk.NONE, height=18)
        self.artifacts_text.pack(fill=tk.BOTH, expand=True)

        ttk.Label(root, text="Runtime Log").pack(anchor=tk.W, pady=(10, 0))
        self.runtime_log = tk.Text(root, wrap=tk.WORD, height=8)
        self.runtime_log.pack(fill=tk.BOTH)

    def _path_row(
        self,
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        variable: tk.StringVar,
        command: callable,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, padx=8, pady=6)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky=tk.EW, padx=8, pady=6)
        ttk.Button(parent, text="Choose...", command=command).grid(row=row, column=2, sticky=tk.E, padx=8, pady=6)

    def choose_job(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose job JSON",
            initialdir=str(RUNTIME.app_root / "singing_app" / "jobs"),
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.job_path.set(path)
            self.refresh_status()

    def choose_song(self) -> None:
        self._choose_file(self.song_path, [("Audio/video files", "*.wav *.mp3 *.m4a *.flac *.mp4"), ("All files", "*.*")])

    def choose_character_image(self) -> None:
        self._choose_file(self.character_image, [("Image files", "*.png *.jpg *.jpeg *.webp"), ("All files", "*.*")])

    def choose_model(self) -> None:
        self._choose_file(self.model_path, [("RVC model", "*.pth"), ("All files", "*.*")])

    def choose_index(self) -> None:
        self._choose_file(self.index_path, [("RVC index", "*.index"), ("All files", "*.*")])

    def choose_sample_dir(self) -> None:
        path = filedialog.askdirectory(title="Choose sample directory")
        if path:
            self.sample_dir.set(path)

    def _choose_file(self, variable: tk.StringVar, filetypes: list[tuple[str, str]]) -> None:
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            variable.set(path)

    def create_and_run_job(self) -> None:
        if self.create_job_from_form():
            self.tabs.select(4)
            self.no_resume.set(True)
            self.run_job()

    def create_job_from_form(self) -> bool:
        try:
            job_path = self._write_job_from_form()
        except Exception as exc:
            messagebox.showerror("Create job failed", str(exc))
            return False

        self.job_path.set(str(job_path))
        self.refresh_status()
        self._append_log(f"Created job: {job_path}")
        return True

    def create_and_run_voice_sample_job(self) -> None:
        if self.create_voice_sample_job():
            self.tabs.select(4)
            self.no_resume.set(True)
            self.run_job()

    def create_voice_sample_job(self) -> bool:
        try:
            job_path = self._write_voice_sample_job()
        except Exception as exc:
            messagebox.showerror("Create voice job failed", str(exc))
            return False

        self.job_path.set(str(job_path))
        self.refresh_status()
        self._append_log(f"Created voice sample job: {job_path}")
        return True

    def create_and_run_training_job(self) -> None:
        if self.create_training_job():
            if not self.dry_run.get():
                proceed = messagebox.askyesno(
                    "Start training?",
                    "Training can take a long time on CPU. Continue with real training?",
                )
                if not proceed:
                    return
            self.tabs.select(4)
            self.no_resume.set(True)
            self.run_job()

    def create_training_job(self) -> bool:
        try:
            job_path = self._write_training_job()
        except Exception as exc:
            messagebox.showerror("Create training job failed", str(exc))
            return False

        self.job_path.set(str(job_path))
        self.refresh_status()
        self._append_log(f"Created training job: {job_path}")
        return True

    def _write_job_from_form(self) -> Path:
        character_name = self.character_name.get().strip()
        if not character_name:
            raise ValueError("Character name is required.")

        song_path = Path(self.song_path.get())
        character_image = Path(self.character_image.get())
        model_path = Path(self.model_path.get())
        index_path = Path(self.index_path.get())

        for label, path in (
            ("Song", song_path),
            ("Character image", character_image),
            ("Voice model", model_path),
            ("Voice index", index_path),
        ):
            if not path.exists():
                raise FileNotFoundError(f"{label} not found: {path}")

        character_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", character_name).strip("_").lower() or "character"
        job_id = f"{character_id}_singing_video"
        project_dir = RUNTIME.projects_root / job_id
        job_path = RUNTIME.app_root / "singing_app" / "jobs" / f"{job_id}.json"
        job_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "job_id": job_id,
            "output_dir": str(project_dir),
            "steps": [
                "check_runtime",
                "create_character",
                "generate_training_text",
                "import_voice_model",
                "trim_song",
                "separate_vocals",
                "convert_vocals",
                "mix_audio",
                "compose_video",
                "export_result",
            ],
            "inputs": {
                "character": {
                    "id": character_id,
                    "name": character_name,
                    "root_dir": str(project_dir / "character"),
                    "voice_description": self.voice_description.get().strip(),
                    "image_path": str(character_image),
                    "mouth_shape_paths": [str(character_image)],
                },
                "voice": {
                    "model_name": model_path.stem,
                    "model_path": str(model_path),
                    "index_path": str(index_path),
                },
                "song": {
                    "path": str(song_path),
                    "start_seconds": float(self.start_seconds.get()),
                    "duration_seconds": float(self.duration_seconds.get()),
                },
                "video": {
                    "character_image": str(character_image),
                },
            },
            "settings": {
                "rvc": {"pitch": 0, "index_rate": 0.25, "protect": 0.45},
                "mix": {"instrumental_volume": 0.88, "vocal_volume": 1.12},
            },
        }

        with job_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")

        return job_path

    def _write_voice_sample_job(self) -> Path:
        character_name = self.character_name.get().strip()
        if not character_name:
            raise ValueError("Character name is required.")

        character_image = Path(self.character_image.get())
        if not character_image.exists():
            raise FileNotFoundError(f"Character image not found: {character_image}")

        character_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", character_name).strip("_").lower() or "character"
        job_id = f"{character_id}_voice_samples"
        project_dir = RUNTIME.projects_root / job_id
        job_path = RUNTIME.app_root / "singing_app" / "jobs" / f"{job_id}.json"
        job_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "job_id": job_id,
            "output_dir": str(project_dir),
            "steps": [
                "check_runtime",
                "create_character",
                "generate_training_text",
                "generate_voice_samples",
                "export_result",
            ],
            "inputs": {
                "character": {
                    "id": character_id,
                    "name": character_name,
                    "root_dir": str(project_dir / "character"),
                    "voice_description": self.voice_description.get().strip(),
                    "image_path": str(character_image),
                    "mouth_shape_paths": [str(character_image)],
                },
                "voice": {
                    "model_name": f"{character_id}_voice",
                    "tts_voice": self.tts_voice.get().strip() or "zh-CN-YunxiNeural",
                },
            },
            "settings": {},
        }

        with job_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")

        return job_path

    def _write_training_job(self) -> Path:
        character_name = self.character_name.get().strip()
        if not character_name:
            raise ValueError("Character name is required.")

        sample_dir = Path(self.sample_dir.get())
        if not sample_dir.exists():
            raise FileNotFoundError(f"Sample directory not found: {sample_dir}")

        model_name = self.train_model_name.get().strip()
        if not model_name:
            raise ValueError("Model name is required.")

        epochs = int(self.train_epochs.get())
        if epochs < 1:
            raise ValueError("Epochs must be >= 1.")

        character_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", character_name).strip("_").lower() or "character"
        job_id = f"{character_id}_train_{model_name}"
        project_dir = RUNTIME.projects_root / job_id
        job_path = RUNTIME.app_root / "singing_app" / "jobs" / f"{job_id}.json"
        job_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "job_id": job_id,
            "output_dir": str(project_dir),
            "steps": [
                "check_runtime",
                "train_voice_model",
                "export_result",
            ],
            "inputs": {
                "voice": {
                    "model_name": model_name,
                    "dataset_path": str(sample_dir),
                    "epochs": epochs,
                },
            },
            "settings": {},
        }

        with job_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")

        return job_path

    def refresh_runtime_checks(self) -> None:
        if not hasattr(self, "runtime_tree"):
            return
        for item in self.runtime_tree.get_children():
            self.runtime_tree.delete(item)
        for check in run_runtime_checks():
            self.runtime_tree.insert(
                "",
                tk.END,
                values=(
                    check.name,
                    "OK" if check.ok else "MISSING",
                    check.message,
                    check.path,
                ),
            )

    def run_job(self) -> None:
        if self.running_thread and self.running_thread.is_alive():
            messagebox.showinfo("Job running", "A job is already running.")
            return

        path = Path(self.job_path.get())
        if not path.exists():
            messagebox.showerror("Missing job", f"Job file not found:\n{path}")
            return

        self._append_log(f"Starting job: {path}")
        self.running_thread = threading.Thread(target=self._run_job_worker, args=(path,), daemon=True)
        self.running_thread.start()

    def _run_job_worker(self, path: Path) -> None:
        try:
            runner = HarnessRunner.from_file(path, dry_run=self.dry_run.get())
            runner.run(resume=not self.no_resume.get())
            self.status_queue.put("Job finished.")
        except Exception as exc:
            self.status_queue.put(f"Job failed: {exc}")
        finally:
            self.status_queue.put("__refresh__")

    def refresh_status(self) -> None:
        output_dir = self._job_output_dir()
        self._set_text(self.state_text, self._read_json_file(output_dir / "state.json"))
        self._set_text(self.artifacts_text, self._read_json_file(output_dir / "artifacts.json"))

    def open_output_folder(self) -> None:
        output_dir = self._job_output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(output_dir))

    def open_logs_folder(self) -> None:
        logs_dir = self._job_output_dir() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(logs_dir))

    def _job_output_dir(self) -> Path:
        path = Path(self.job_path.get())
        if not path.exists():
            return RUNTIME.projects_root
        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
            return Path(data["output_dir"])
        except Exception:
            return RUNTIME.projects_root

    def _poll_queue(self) -> None:
        try:
            while True:
                message = self.status_queue.get_nowait()
                if message == "__refresh__":
                    self.refresh_status()
                else:
                    self._append_log(message)
        except queue.Empty:
            pass
        self.after(500, self._poll_queue)

    def _append_log(self, message: str) -> None:
        self.runtime_log.insert(tk.END, message + "\n")
        self.runtime_log.see(tk.END)

    @staticmethod
    def _set_text(widget: tk.Text, text: str) -> None:
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, text)

    @staticmethod
    def _read_json_file(path: Path) -> str:
        if not path.exists():
            return "(not found)"
        try:
            with path.open("r", encoding="utf-8") as file:
                return json.dumps(json.load(file), ensure_ascii=False, indent=2)
        except Exception as exc:
            return f"Failed to read {path}: {exc}"


def main() -> None:
    app = SingingAppUi()
    app.mainloop()


if __name__ == "__main__":
    main()


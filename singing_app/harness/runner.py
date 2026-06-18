from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable

from singing_app.adapters.applio import ApplioInferAdapter, ApplioTrainAdapter
from singing_app.adapters.cosyvoice import CosyVoiceAdapter
from singing_app.adapters.demucs import DemucsAdapter
from singing_app.adapters.edge_tts import EdgeTtsAdapter
from singing_app.adapters.ffmpeg import FfmpegAdapter
from singing_app.characters.project import CharacterProject, VoiceModelRef
from singing_app.config import RUNTIME
from singing_app.harness.models import HarnessJob, StepContext, StepResult


class HarnessRunner:
    def __init__(self, job: HarnessJob, dry_run: bool = False) -> None:
        self.job = job
        self.dry_run = dry_run
        self.workspace = job.output_dir
        self.logs_dir = self.workspace / "logs"
        self.state_path = self.workspace / "state.json"
        self.artifacts_path = self.workspace / "artifacts.json"
        self.ffmpeg = FfmpegAdapter()
        self.demucs = DemucsAdapter()
        self.applio_infer = ApplioInferAdapter()
        self.applio_train = ApplioTrainAdapter()
        self.edge_tts = EdgeTtsAdapter()
        self.cosyvoice = CosyVoiceAdapter()

        self.handlers: dict[str, Callable[[StepContext], StepResult]] = {
            "check_runtime": self.check_runtime,
            "create_character": self.create_character,
            "generate_training_text": self.generate_training_text,
            "generate_voice_samples": self.generate_voice_samples,
            "prepare_recordings": self.prepare_recordings,
            "train_voice_model": self.train_voice_model,
            "import_voice_model": self.import_voice_model,
            "trim_song": self.trim_song,
            "separate_vocals": self.separate_vocals,
            "use_separated_audio": self.use_separated_audio,
            "convert_vocals": self.convert_vocals,
            "mix_audio": self.mix_audio,
            "export_result": self.export_result,
        }

    @classmethod
    def from_file(cls, job_path: Path, dry_run: bool = False) -> "HarnessRunner":
        with job_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        job = HarnessJob.from_dict(data)
        return cls(job, dry_run=dry_run)

    def run(self, resume: bool = True) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        state = self._load_json(self.state_path, {})
        artifacts = self._load_json(self.artifacts_path, {})

        for step in self.job.steps:
            if resume and state.get(step, {}).get("status") == "succeeded":
                continue

            if step not in self.handlers:
                raise ValueError(f"Unknown harness step: {step}")

            self._write_step_state(state, step, "running")
            context = StepContext(
                job=self.job,
                workspace=self.workspace,
                logs_dir=self.logs_dir,
                artifacts=artifacts,
                dry_run=self.dry_run,
            )

            try:
                result = self.handlers[step](context)
            except Exception as exc:
                self._write_step_state(state, step, "failed", str(exc))
                self._save_json(self.artifacts_path, artifacts)
                raise

            artifacts.update(result.artifacts)
            self._save_json(self.artifacts_path, artifacts)
            self._write_step_state(state, step, result.status, result.message)

    def check_runtime(self, context: StepContext) -> StepResult:
        required = {
            "applio_python": RUNTIME.applio_python,
            "ffmpeg": RUNTIME.ffmpeg,
            "applio_core": RUNTIME.applio_core,
        }

        missing = [name for name, path in required.items() if not path.exists()]
        if missing:
            raise FileNotFoundError(f"Missing runtime components: {', '.join(missing)}")

        return StepResult(
            status="succeeded",
            artifacts={name: str(path) for name, path in required.items()},
            message="Runtime components are available.",
        )

    def create_character(self, context: StepContext) -> StepResult:
        character = context.job.inputs["character"]
        root_dir = Path(character.get("root_dir", context.workspace / "character"))
        if root_dir.exists() and (root_dir / "character.json").exists():
            project = CharacterProject.load(root_dir / "character.json")
        else:
            project = CharacterProject.create(
                root_dir=root_dir,
                character_id=character["id"],
                name=character["name"],
                voice_description=character.get("voice_description", ""),
            )

        project.save()

        return StepResult(
            status="succeeded",
            artifacts={"character_config": str(project.config_path)},
            message=f"Character project ready: {project.name}",
        )

    def generate_training_text(self, context: StepContext) -> StepResult:
        project = CharacterProject.load(context.artifact_path("character_config"))
        output_path = Path(project.training_text_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        provided_text = context.job.inputs.get("voice", {}).get("training_text", "")
        text = provided_text.strip() or self._default_training_text(project)
        output_path.write_text(text + "\n", encoding="utf-8")

        return StepResult(
            status="succeeded",
            artifacts={"training_text": str(output_path)},
            message="Training text is ready.",
        )

    def generate_voice_samples(self, context: StepContext) -> StepResult:
        project = CharacterProject.load(context.artifact_path("character_config"))
        voice = context.job.inputs.get("voice", {})
        sample_dir = Path(project.sample_dir)
        engine = (voice.get("tts_engine") or "edge_tts").strip()

        if engine == "cosyvoice":
            reference_audio = voice.get("reference_audio", "")
            reference_text = voice.get("reference_text", "")
            if not reference_audio or not reference_text:
                raise ValueError(
                    "CosyVoice engine needs a reference recording to clone: "
                    "set 'reference_audio' (a short clip) and 'reference_text' "
                    "(its transcript) in the job's voice inputs."
                )
            samples = self.cosyvoice.generate_samples(
                training_text_path=context.artifact_path("training_text"),
                output_dir=sample_dir,
                log_path=context.logs_dir / "generate_voice_samples.log",
                reference_audio=Path(reference_audio),
                reference_text=reference_text,
                dry_run=context.dry_run,
            )
        elif engine == "edge_tts":
            samples = self.edge_tts.generate_samples(
                training_text_path=context.artifact_path("training_text"),
                output_dir=sample_dir,
                log_path=context.logs_dir / "generate_voice_samples.log",
                voice=voice.get("tts_voice", "zh-CN-YunxiNeural"),
                preset=voice.get("voice_preset"),
                dry_run=context.dry_run,
            )
        else:
            raise ValueError(
                f"Unknown tts_engine '{engine}'. Use 'edge_tts' or 'cosyvoice'."
            )
        return StepResult(
            status="succeeded",
            artifacts={"sample_dir": str(sample_dir), "sample_count": str(len(samples))},
            message=f"Generated {len(samples)} voice samples ({engine}).",
        )

    def prepare_recordings(self, context: StepContext) -> StepResult:
        """Build a training dataset directly from the user's own recordings.

        Skips TTS entirely — real audio is the highest-quality RVC input. Accepts
        a directory (all audio files inside) or an explicit list of files via
        voice.recordings, normalizes each to the training format, and exposes
        sample_dir so train_voice_model picks it up.
        """
        project = CharacterProject.load(context.artifact_path("character_config"))
        voice = context.job.inputs.get("voice", {})
        sample_dir = Path(project.sample_dir)
        sample_rate = int(voice.get("sample_rate", 44100))

        sources = self._collect_recordings(voice.get("recordings", ""))
        if not sources and not context.dry_run:
            raise ValueError(
                "No recordings found. Set 'recordings' in the job's voice inputs "
                "to a folder of audio files or a list of file paths."
            )

        outputs: list[Path] = []
        for index, src in enumerate(sources, start=1):
            out = sample_dir / f"{index:03d}_recording.wav"
            self.ffmpeg.to_training_wav(
                input_path=src,
                output_path=out,
                log_path=context.logs_dir / "prepare_recordings.log",
                sample_rate=sample_rate,
                dry_run=context.dry_run,
            )
            outputs.append(out)

        return StepResult(
            status="succeeded",
            artifacts={"sample_dir": str(sample_dir), "sample_count": str(len(outputs))},
            message=f"Prepared {len(outputs)} recordings for training.",
        )

    @staticmethod
    def _collect_recordings(recordings: object) -> list[Path]:
        audio_exts = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".wma", ".opus"}
        if isinstance(recordings, list):
            return [Path(item) for item in recordings if str(item).strip()]
        text = str(recordings).strip()
        if not text:
            return []
        path = Path(text)
        if path.is_dir():
            return sorted(
                p for p in path.iterdir() if p.suffix.lower() in audio_exts
            )
        return [path]

    def train_voice_model(self, context: StepContext) -> StepResult:
        voice = context.job.inputs.get("voice", {})
        dataset = Path(voice.get("dataset_path", context.artifacts.get("sample_dir", "")))
        model_name = voice["model_name"]
        epochs = int(voice.get("epochs", 10))
        trained = self.applio_train.train(
            model_name=model_name,
            dataset_path=dataset,
            log_path=context.logs_dir / "train_voice_model.log",
            epochs=epochs,
            sample_rate=int(voice.get("sample_rate", 40000)),
            gpu=str(voice.get("gpu", "0")),
            batch_size=int(voice.get("batch_size", 8)),
            cpu_cores=int(voice.get("cpu_cores", 4)),
            save_every=int(voice.get("save_every", 5)),
            dry_run=context.dry_run,
        )
        if not context.dry_run and not trained["latest_model"]:
            raise FileNotFoundError(f"No trained model artifact found for {model_name}.")

        # Applio writes training output to its own logs dir; copy the final
        # model+index into the unified output/models/<name>/ so every product
        # lives under one root (RUNTIME.output_root).
        model_dir = trained["model_dir"]
        model_path = trained["latest_model"]
        index_path = trained["latest_index"]
        if not context.dry_run and model_path:
            dest_dir = RUNTIME.models_root / model_name
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_model = dest_dir / Path(model_path).name
            shutil.copy2(model_path, dest_model)
            model_dir = dest_dir
            model_path = dest_model
            if index_path:
                dest_index = dest_dir / Path(index_path).name
                shutil.copy2(index_path, dest_index)
                index_path = dest_index

        artifacts = {
            "trained_model_dir": str(model_dir),
            "trained_model_path": str(model_path),
            "trained_index_path": str(index_path),
        }
        return StepResult(
            status="succeeded",
            artifacts=artifacts,
            message=f"Training finished for {model_name}.",
        )

    def import_voice_model(self, context: StepContext) -> StepResult:
        voice = context.job.inputs.get("voice", {})
        model_path = Path(
            voice.get("model_path")
            or context.artifacts.get("trained_model_path")
            or RUNTIME.default_model
        )
        index_path = Path(
            voice.get("index_path")
            or context.artifacts.get("trained_index_path")
            or RUNTIME.default_index
        )
        if not context.dry_run:
            if not model_path.exists():
                raise FileNotFoundError(f"Model file not found: {model_path}")
            if not index_path.exists():
                raise FileNotFoundError(f"Index file not found: {index_path}")

        character_config = context.artifacts.get("character_config")
        if character_config:
            project = CharacterProject.load(Path(character_config))
            model_name = voice.get("model_name", model_path.stem)
            existing = [model for model in project.models if model.name != model_name]
            existing.append(
                VoiceModelRef(
                    name=model_name,
                    model_path=str(model_path),
                    index_path=str(index_path),
                    notes=voice.get("notes", ""),
                )
            )
            project.models = existing
            if not context.dry_run:
                project.save()
        return StepResult(
            status="succeeded",
            artifacts={"model_path": str(model_path), "index_path": str(index_path)},
        )

    def trim_song(self, context: StepContext) -> StepResult:
        song = context.job.inputs["song"]
        input_path = Path(song["path"])
        output_path = context.workspace / "audio" / "song_clip.wav"
        self.ffmpeg.trim_audio(
            input_path=input_path,
            output_path=output_path,
            start_seconds=float(song.get("start_seconds", 0)),
            duration_seconds=float(song.get("duration_seconds", 30)),
            log_path=context.logs_dir / "trim_song.log",
            dry_run=context.dry_run,
        )
        return StepResult(status="succeeded", artifacts={"song_clip": str(output_path)})

    def separate_vocals(self, context: StepContext) -> StepResult:
        input_path = context.artifact_path("song_clip")
        output_dir = context.workspace / "separated"
        model = str(context.job.settings.get("separation", {}).get("model", "htdemucs_ft")).strip() or "htdemucs_ft"
        vocals, instrumental = self.demucs.separate_vocals(
            input_path=input_path,
            output_dir=output_dir,
            log_path=context.logs_dir / "separate_vocals.log",
            model=model,
            dry_run=context.dry_run,
        )
        return StepResult(
            status="succeeded",
            artifacts={"vocals": str(vocals), "instrumental": str(instrumental)},
        )

    def use_separated_audio(self, context: StepContext) -> StepResult:
        song = context.job.inputs["song"]
        vocals = Path(song["vocals_path"])
        instrumental = Path(song["instrumental_path"])
        if not context.dry_run:
            if not vocals.exists():
                raise FileNotFoundError(f"Separated vocals not found: {vocals}")
            if not instrumental.exists():
                raise FileNotFoundError(f"Separated instrumental not found: {instrumental}")
        return StepResult(
            status="succeeded",
            artifacts={"vocals": str(vocals), "instrumental": str(instrumental)},
            message="Using pre-separated vocal and instrumental tracks.",
        )

    def convert_vocals(self, context: StepContext) -> StepResult:
        output_path = context.workspace / "audio" / "vocals_converted.wav"
        settings = context.job.settings.get("rvc", {})
        self.applio_infer.convert_vocals(
            input_path=context.artifact_path("vocals"),
            output_path=output_path,
            model_path=context.artifact_path("model_path"),
            index_path=context.artifact_path("index_path"),
            log_path=context.logs_dir / "convert_vocals.log",
            pitch=int(settings.get("pitch", 0)),
            index_rate=float(settings.get("index_rate", 0.5)),
            protect=float(settings.get("protect", 0.45)),
            clean_audio=bool(settings.get("clean_audio", False)),
            clean_strength=float(settings.get("clean_strength", 0.3)),
            dry_run=context.dry_run,
        )
        return StepResult(status="succeeded", artifacts={"converted_vocals": str(output_path)})

    def mix_audio(self, context: StepContext) -> StepResult:
        output_path = context.workspace / "audio" / "final_mix.wav"
        settings = context.job.settings.get("mix", {})
        self.ffmpeg.mix_audio(
            instrumental_path=context.artifact_path("instrumental"),
            vocal_path=context.artifact_path("converted_vocals"),
            output_path=output_path,
            log_path=context.logs_dir / "mix_audio.log",
            instrumental_volume=float(settings.get("instrumental_volume", 0.88)),
            vocal_volume=float(settings.get("vocal_volume", 1.12)),
            dry_run=context.dry_run,
        )
        return StepResult(status="succeeded", artifacts={"final_mix": str(output_path)})

    def export_result(self, context: StepContext) -> StepResult:
        return StepResult(
            status="succeeded",
            artifacts={
                "result_audio": context.artifacts.get("final_mix", ""),
            },
            message="Result artifacts are ready.",
        )

    @staticmethod
    def _default_training_text(project: CharacterProject) -> str:
        description = project.voice_description or "自然、清晰的原创角色声线"
        # Phonetically varied, persona-neutral script: covers statements,
        # questions, numbers and a range of finals/tones so the TTS samples
        # exercise the voice broadly. Character name/description are filled in
        # so the same template adapts to any character.
        return (
            f"你好，我是 {project.name}。我的声音设定是：{description}。\n"
            "今天天气晴朗，微风从窗外轻轻吹进来。\n"
            "请把这段话读得自然一些，不快也不慢。\n\n"
            "一、二、三、四、五、六、七、八、九、十。\n"
            "春天的花、夏天的雨、秋天的叶、冬天的雪。\n"
            "我们一起去公园散步，好不好？\n\n"
            "这是一句陈述句，用来记录平稳的语气。\n"
            "这是一句疑问句吗？声调要往上扬一点。\n"
            "太好了！这是一句感叹句，语气更有力量。\n\n"
            "无论清晨还是夜晚，无论安静还是热闹，\n"
            "声音都可以保持清楚、稳定、容易听懂。\n"
            "谢谢你听我把这段话读完。\n"
        )

    def _write_step_state(
        self,
        state: dict[str, dict[str, str]],
        step: str,
        status: str,
        message: str = "",
    ) -> None:
        state[step] = {
            "status": status,
            "message": message,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._save_json(self.state_path, state)

    @staticmethod
    def _load_json(path: Path, default: dict) -> dict:
        if not path.exists():
            return dict(default)
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    @staticmethod
    def _save_json(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")


from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from singing_app.adapters.applio import ApplioInferAdapter, ApplioTrainAdapter
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

        self.handlers: dict[str, Callable[[StepContext], StepResult]] = {
            "check_runtime": self.check_runtime,
            "create_character": self.create_character,
            "generate_training_text": self.generate_training_text,
            "generate_voice_samples": self.generate_voice_samples,
            "train_voice_model": self.train_voice_model,
            "import_voice_model": self.import_voice_model,
            "trim_song": self.trim_song,
            "separate_vocals": self.separate_vocals,
            "use_separated_audio": self.use_separated_audio,
            "convert_vocals": self.convert_vocals,
            "mix_audio": self.mix_audio,
            "compose_video": self.compose_video,
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

        project.image_path = character.get("image_path", project.image_path)
        project.mouth_shape_paths = list(character.get("mouth_shape_paths", project.mouth_shape_paths))
        project.background_path = character.get("background_path", project.background_path)
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
        samples = self.edge_tts.generate_samples(
            training_text_path=context.artifact_path("training_text"),
            output_dir=sample_dir,
            log_path=context.logs_dir / "generate_voice_samples.log",
            voice=voice.get("tts_voice", "zh-CN-YunxiNeural"),
            dry_run=context.dry_run,
        )
        return StepResult(
            status="succeeded",
            artifacts={"sample_dir": str(sample_dir), "sample_count": str(len(samples))},
            message=f"Generated {len(samples)} voice samples.",
        )

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
            dry_run=context.dry_run,
        )
        artifacts = {
            "trained_model_dir": str(trained["model_dir"]),
            "trained_model_path": str(trained["latest_model"]),
            "trained_index_path": str(trained["latest_index"]),
        }
        if not context.dry_run and not trained["latest_model"]:
            raise FileNotFoundError(f"No trained model artifact found for {model_name}.")
        return StepResult(
            status="succeeded",
            artifacts=artifacts,
            message=f"Training finished for {model_name}.",
        )

    def import_voice_model(self, context: StepContext) -> StepResult:
        voice = context.job.inputs.get("voice", {})
        model_path = Path(voice.get("model_path", RUNTIME.default_model))
        index_path = Path(voice.get("index_path", RUNTIME.default_index))
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
        vocals, instrumental = self.demucs.separate_vocals(
            input_path=input_path,
            output_dir=output_dir,
            log_path=context.logs_dir / "separate_vocals.log",
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
            index_rate=float(settings.get("index_rate", 0.25)),
            protect=float(settings.get("protect", 0.45)),
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

    def compose_video(self, context: StepContext) -> StepResult:
        video = context.job.inputs.get("video", {})
        character_image = Path(video["character_image"])
        background_image = video.get("background_image")
        output_path = context.workspace / "video" / "final_video.mp4"
        duration = float(context.job.inputs["song"].get("duration_seconds", 30))
        self.ffmpeg.compose_static_video(
            audio_path=context.artifact_path("final_mix"),
            character_image=character_image,
            background_image=Path(background_image) if background_image else None,
            output_path=output_path,
            log_path=context.logs_dir / "compose_video.log",
            duration_seconds=duration,
            dry_run=context.dry_run,
        )
        return StepResult(status="succeeded", artifacts={"final_video": str(output_path)})

    def export_result(self, context: StepContext) -> StepResult:
        return StepResult(
            status="succeeded",
            artifacts={
                "result_audio": context.artifacts.get("final_mix", ""),
                "result_video": context.artifacts.get("final_video", ""),
            },
            message="Result artifacts are ready.",
        )

    @staticmethod
    def _default_training_text(project: CharacterProject) -> str:
        description = project.voice_description or "安静、自然、有一点情绪的原创角色声线"
        return (
            f"{project.name} 的声音设定是：{description}。\n"
            "我说没事，只是今天的风有一点安静。\n"
            "如果你听见这首歌，不用回头，也不用回答。\n\n"
            "我把话说得很轻，因为太认真会显得难过。\n"
            "窗外的雨慢慢落下，我抱着小小的吉他。\n"
            "每一个尾音都短一点，软一点，像藏起来的心事。\n\n"
            "啦，啦，啦，啦。\n"
            "别担心，我会没事。\n"
            "啦，啦，啦，啦。\n"
            "只是今晚有一点冷。\n\n"
            "如果明天你忘了我的名字。\n"
            "如果故事停在这里。\n"
            "我也会小声地唱下去，唱到灯光慢慢安静。\n"
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


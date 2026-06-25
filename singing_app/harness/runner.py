from __future__ import annotations

import json
import re
import shutil
import subprocess
import wave
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Callable

from singing_app.adapters.applio import ApplioInferAdapter, ApplioTrainAdapter
from singing_app.adapters.audio_separator import AudioSeparatorAdapter
from singing_app.adapters.cosyvoice import CosyVoiceAdapter
from singing_app.adapters.demucs import DemucsAdapter
from singing_app.adapters.diffsinger import DiffSingerAdapter
from singing_app.adapters.edge_tts import EdgeTtsAdapter
from singing_app.adapters.ffmpeg import FfmpegAdapter
from singing_app.adapters.seedvc import SeedVcAdapter
from singing_app.characters.project import CharacterProject, VoiceModelRef
from singing_app.config import RUNTIME
from singing_app.harness.models import HarnessJob, StepContext, StepResult
from singing_app.pitch import decide_pitch_augment
from singing_app.separation_models import resolve_separation_model


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
        self.audio_separator = AudioSeparatorAdapter()
        self.applio_infer = ApplioInferAdapter()
        self.applio_train = ApplioTrainAdapter()
        self.edge_tts = EdgeTtsAdapter()
        self.cosyvoice = CosyVoiceAdapter()
        self.seedvc = SeedVcAdapter()
        self.diffsinger = DiffSingerAdapter()

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
            "convert_vocals_zeroshot": self.convert_vocals_zeroshot,
            "synthesize_diffsinger": self.synthesize_diffsinger,
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
        denoise = bool(voice.get("preprocess_vocals", False))

        sources = self._collect_recordings(voice.get("recordings", ""))
        if not sources and not context.dry_run:
            raise ValueError(
                "No recordings found. Set 'recordings' in the job's voice inputs "
                "to a folder of audio files or a list of file paths."
            )

        augment, augment_note = self._resolve_pitch_augment(
            voice.get("pitch_augment", "auto"), sources, context.dry_run
        )

        outputs: list[Path] = []
        for index, src in enumerate(sources, start=1):
            cleaned = src
            if denoise:
                # Strip background music/noise so only the singer's voice trains
                # the model. Demucs splits into vocals/no_vocals; we keep vocals.
                stem_dir = sample_dir / "denoise" / f"{index:03d}"
                vocals, _ = self.demucs.separate_vocals(
                    input_path=src,
                    output_dir=stem_dir,
                    log_path=context.logs_dir / "prepare_recordings.log",
                    model=str(voice.get("separation_model", "htdemucs_ft")),
                    dry_run=context.dry_run,
                )
                if not context.dry_run:
                    cleaned = vocals
            out = sample_dir / f"{index:03d}_recording.wav"
            self.ffmpeg.to_training_wav(
                input_path=cleaned,
                output_path=out,
                log_path=context.logs_dir / "prepare_recordings.log",
                sample_rate=sample_rate,
                dry_run=context.dry_run,
            )
            outputs.append(out)
            # Pitch-augmented copies widen the model's f0 coverage so a
            # speech-trained voice can sing high notes without pinching. Files
            # carry the '_aug_' marker so epoch estimation can skip them (they
            # are duplicate content, not new material).
            for semitones in augment:
                tag = ("p" if semitones >= 0 else "m") + f"{abs(int(round(semitones)))}"
                aug_out = sample_dir / f"{index:03d}_recording_aug_{tag}.wav"
                self.ffmpeg.pitch_shift(
                    input_path=out,
                    output_path=aug_out,
                    semitones=semitones,
                    log_path=context.logs_dir / "prepare_recordings.log",
                    sample_rate=sample_rate,
                    dry_run=context.dry_run,
                )
                outputs.append(aug_out)

        notes = []
        if denoise:
            notes.append("denoised")
        if augment:
            notes.append(
                f"pitch-augmented ±{','.join(str(abs(int(round(s)))) for s in sorted({abs(s) for s in augment}))} semitones"
            )
        if augment_note:
            notes.append(augment_note)
        suffix = f" ({', '.join(notes)})." if notes else "."
        return StepResult(
            status="succeeded",
            artifacts={"sample_dir": str(sample_dir), "sample_count": str(len(outputs))},
            message=f"Prepared {len(outputs)} recordings for training" + suffix,
        )

    @staticmethod
    def _resolve_pitch_augment(
        value: object, sources: list[Path], dry_run: bool
    ) -> tuple[list[float], str]:
        """Resolve pitch augmentation to (semitone offsets, human note).

        ``"auto"`` (the default) measures the material's voiced-f0 spread and
        only augments when it is narrow (speech-like), since a speaking voice is
        what forces the model to extrapolate to sing. ``"on"``/truthy forces a
        balanced ±4-semitone spread (3x the data); ``"off"``/falsey disables it.
        A measurement failure falls back to augmenting (speech is the common
        case here and the only cost is extra training time).
        """
        spread = [-4.0, 4.0]
        text = str(value).strip().lower()
        if text in ("1", "true", "yes", "on"):
            return spread, ""
        if text in ("0", "false", "no", "off"):
            return [], ""
        # "auto"
        if dry_run:
            return spread, "auto: dry-run 预览按说话声处理（增强）"
        if not sources:
            return [], ""
        decision = decide_pitch_augment([str(s) for s in sources])
        return (spread if decision.get("augment") else []), str(decision.get("reason", ""))

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
        sample_rate = int(voice.get("sample_rate", 40000))

        epochs, epochs_note = self._resolve_epochs(voice.get("epochs", "auto"), dataset, context.dry_run)

        trained = self.applio_train.train(
            model_name=model_name,
            dataset_path=dataset,
            log_path=context.logs_dir / "train_voice_model.log",
            epochs=epochs,
            sample_rate=sample_rate,
            gpu=str(voice.get("gpu", "auto")),
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
            "trained_checkpoints": ", ".join(
                Path(p).name for p in trained.get("checkpoints", [])
            ),
            "trained_epochs": str(epochs),
        }
        return StepResult(
            status="succeeded",
            artifacts=artifacts,
            message=f"Training finished for {model_name} ({epochs} epochs, {epochs_note}).",
        )

    def _resolve_epochs(
        self, raw: object, dataset: Path, dry_run: bool
    ) -> tuple[int, str]:
        """Return (epochs, human note). 'auto' picks epochs from data length.

        More data tolerates (and needs) more epochs; little data overfits fast,
        so short datasets get fewer epochs. A fixed number can't be safe for all
        data sizes, so the default scales with the measured audio duration.
        """
        if str(raw).strip().lower() != "auto":
            return int(raw), "manual"
        if dry_run:
            return 100, "auto (dry-run placeholder)"
        minutes = self._dataset_duration_minutes(dataset)
        epochs = self._recommend_epochs(minutes)
        return epochs, f"auto from {minutes:.1f} min of audio"

    @staticmethod
    def _recommend_epochs(minutes: float) -> int:
        # Ascending (max_minutes, epochs) thresholds. Tuned to RVC community
        # experience: tiny datasets overfit, so they get few epochs; larger
        # clean datasets can train longer before overfitting.
        ladder = [
            (1.5, 60),
            (3.0, 90),
            (6.0, 130),
            (12.0, 180),
            (25.0, 240),
            (50.0, 300),
        ]
        for max_minutes, epochs in ladder:
            if minutes < max_minutes:
                return epochs
        return 360

    def _dataset_duration_minutes(self, dataset: Path) -> float:
        audio_exts = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".wma", ".opus"}
        if not dataset.exists():
            return 0.0
        total_seconds = 0.0
        for path in dataset.rglob("*"):
            # Skip our own intermediate denoise outputs so they aren't counted
            # twice alongside the normalized training files. Also skip pitch-
            # augmented copies: they are duplicate content, so counting them
            # would over-estimate unique audio and pick too many epochs.
            if "denoise" in path.parts:
                continue
            if "_aug_" in path.name:
                continue
            if path.is_file() and path.suffix.lower() in audio_exts:
                total_seconds += self._probe_duration_seconds(path)
        return total_seconds / 60.0

    def _probe_duration_seconds(self, path: Path) -> float:
        try:
            result = subprocess.run(
                [
                    str(RUNTIME.ffprobe),
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            value = result.stdout.strip()
            if value:
                return float(value)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        # Fallback for plain PCM wav when ffprobe is unavailable or failed.
        if path.suffix.lower() == ".wav":
            try:
                with closing(wave.open(str(path), "rb")) as handle:
                    frames = handle.getnframes()
                    rate = handle.getframerate()
                    if rate:
                        return frames / float(rate)
            except (OSError, wave.Error):
                pass
        return 0.0

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
        sep_settings = context.job.settings.get("separation", {})
        model = str(sep_settings.get("model", "htdemucs_ft")).strip() or "htdemucs_ft"
        spec = resolve_separation_model(model)
        engine = spec["engine"] if spec else "demucs"
        if engine != "demucs":
            raise RuntimeError(
                f"分离引擎「{engine}」尚未接入运行时，请先安装并切换到 Demucs 模型（如 htdemucs_ft）。"
            )
        vocals, instrumental = self.demucs.separate_vocals(
            input_path=input_path,
            output_dir=output_dir,
            log_path=context.logs_dir / "separate_vocals.log",
            model=model,
            dry_run=context.dry_run,
        )
        # Optional audio-separator post-passes on the vocal stem. Demucs bundles
        # lead+backing into one stem and leaves some bleed; these refine it.
        remove_harmony = bool(sep_settings.get("remove_harmony", False))
        denoise = bool(sep_settings.get("denoise", False))
        notes: list[str] = []
        if (remove_harmony or denoise) and not self.audio_separator.available():
            raise RuntimeError(
                "去和声 / 降噪需要 audio-separator，但当前环境未安装。请先安装后再开启，"
                "或关闭这两个选项改用纯 Demucs 分离。"
            )
        post_log = context.logs_dir / "separate_postprocess.log"
        if remove_harmony:
            lead, backing = self.audio_separator.remove_harmony(
                vocals_in=vocals,
                output_dir=output_dir / "karaoke",
                log_path=post_log,
                dry_run=context.dry_run,
            )
            if not context.dry_run:
                # Keep the original backing harmony in the accompaniment so the
                # song stays full; only the lead goes on to RVC.
                combined = output_dir / "instrumental_with_backing.wav"
                self.ffmpeg.combine_stems(
                    first_path=instrumental,
                    second_path=backing,
                    output_path=combined,
                    log_path=post_log,
                    dry_run=context.dry_run,
                )
                vocals, instrumental = lead, combined
            notes.append("去和声")
        if denoise:
            clean = self.audio_separator.denoise(
                vocals_in=vocals,
                output_dir=output_dir / "denoise",
                log_path=post_log,
                dry_run=context.dry_run,
            )
            if not context.dry_run:
                vocals = clean
            notes.append("降噪")
        message = (
            f"Separated vocals ({model})"
            + (f" + {'+'.join(notes)}" if notes else "")
        )
        return StepResult(
            status="succeeded",
            artifacts={"vocals": str(vocals), "instrumental": str(instrumental)},
            message=message,
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
            formant_shifting=bool(settings.get("formant_shifting", False)),
            formant_qfrency=float(settings.get("formant_qfrency", 1.0)),
            formant_timbre=float(settings.get("formant_timbre", 1.0)),
            dry_run=context.dry_run,
        )
        return StepResult(status="succeeded", artifacts={"converted_vocals": str(output_path)})

    def convert_vocals_zeroshot(self, context: StepContext) -> StepResult:
        """Zero-shot SVC: convert the song's vocals into a reference voice's timbre.

        No trained model — Seed-VC takes the separated vocals (source pitch +
        articulation) and a short reference clip (target timbre) and produces
        converted vocals. Writes the same ``converted_vocals`` artifact as the
        RVC path, so ``mix_audio``/``export_result`` are reused unchanged.
        """
        if not context.dry_run and not self.seedvc.available():
            raise RuntimeError(
                "零样本翻唱引擎 Seed-VC 尚未安装。请先安装 tools/seed-vc 及其 venv，"
                "或改用「用已训练的声线模型（RVC）」方式。"
            )
        reference = context.job.inputs.get("reference", {})
        reference_audio = Path(reference.get("audio", ""))
        if not context.dry_run and not reference_audio.is_file():
            raise FileNotFoundError(f"参考音频不存在: {reference_audio}")
        settings = context.job.settings.get("seedvc", {})
        output_path = context.workspace / "audio" / "vocals_converted.wav"
        self.seedvc.convert_vocals(
            source_vocals=context.artifact_path("vocals"),
            reference_audio=reference_audio,
            output_path=output_path,
            log_path=context.logs_dir / "convert_vocals_zeroshot.log",
            semitones=int(settings.get("semitones", 0)),
            diffusion_steps=int(settings.get("diffusion_steps", 30)),
            inference_cfg_rate=float(settings.get("inference_cfg_rate", 0.7)),
            dry_run=context.dry_run,
        )
        return StepResult(status="succeeded", artifacts={"converted_vocals": str(output_path)})

    def synthesize_diffsinger(self, context: StepContext) -> StepResult:
        """Lyric-driven SVS: re-sing the song's vocals with the user's lyrics,
        keeping the original melody (source f0) and rhythm (forced alignment), so
        every character's pronunciation is exactly what the lyrics specify.

        Produces a clean synthesized vocal and overwrites the ``vocals`` artifact
        with it, so the downstream RVC ``convert_vocals`` step (which reads
        ``vocals``) takes on the user's timbre with no change -- the hybrid route.
        """
        if not context.dry_run and not self.diffsinger.available():
            raise RuntimeError(
                "纠正发音翻唱引擎 DiffSinger/SOFA 尚未安装。请先安装 tools/DiffSinger 与 "
                "tools/SOFA 及其 venv 和声库，或改用「用已训练的声线模型（RVC）」方式。"
            )
        lyrics = str(context.job.inputs.get("diffsinger", {}).get("lyrics", "")).strip()
        if not context.dry_run and not lyrics:
            raise ValueError("歌词为空，无法用纠正发音方式翻唱。请填写这首歌的歌词。")
        settings = context.job.settings.get("diffsinger", {})
        seeds = settings.get("seeds") or [7]
        clean_path = context.workspace / "audio" / "vocals_diffsinger.wav"
        self.diffsinger.synthesize_clean_vocals(
            source_vocals=context.artifact_path("vocals"),
            lyrics=lyrics,
            output_path=clean_path,
            log_path=context.logs_dir / "synthesize_diffsinger.log",
            seeds=[int(s) for s in seeds],
            depth=float(settings.get("depth", 0.3)),
            steps=int(settings.get("steps", 100)),
            velocity=float(settings.get("velocity", 0.85)),
            dry_run=context.dry_run,
        )
        # Overwrite the vocals artifact so RVC convert_vocals reuses it unchanged.
        return StepResult(
            status="succeeded",
            artifacts={"clean_vocals": str(clean_path), "vocals": str(clean_path)},
            message="Synthesized clean vocals from lyrics (DiffSinger); handed to RVC.",
        )

    def mix_audio(self, context: StepContext) -> StepResult:
        output_path = context.workspace / "audio" / f"{self._cover_basename(context)}.wav"
        settings = context.job.settings.get("mix", {})
        self.ffmpeg.mix_audio(
            instrumental_path=context.artifact_path("instrumental"),
            vocal_path=context.artifact_path("converted_vocals"),
            output_path=output_path,
            log_path=context.logs_dir / "mix_audio.log",
            instrumental_volume=float(settings.get("instrumental_volume", 0.88)),
            vocal_volume=float(settings.get("vocal_volume", 1.12)),
            deess_strength=float(settings.get("deess_strength", 0.0)),
            dry_run=context.dry_run,
        )
        return StepResult(status="succeeded", artifacts={"final_mix": str(output_path)})

    @staticmethod
    def _cover_basename(context: StepContext) -> str:
        """Name the cover output ``<声线名>_<音乐名>_<日期时间>`` so files are
        self-describing and regenerations don't overwrite each other.

        Voice name comes from the RVC voice block or the zero-shot reference; song
        name is the stem of the picked song; a ``YYYYMMDD_HHMMSS`` stamp keeps
        every run as a distinct version. Illegal filename characters are stripped
        while Unicode (Chinese) is kept. Falls back to ``cover`` for the name part
        when neither voice nor song is available.
        """
        inputs = context.job.inputs
        voice_name = str(
            (inputs.get("voice") or {}).get("name")
            or (inputs.get("reference") or {}).get("name")
            or ""
        ).strip()
        song_path = str((inputs.get("song") or {}).get("path") or "").strip()
        song_name = Path(song_path).stem if song_path else ""

        def clean(text: str) -> str:
            text = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "", text)
            return re.sub(r"\s+", "_", text.strip())

        parts = [clean(p) for p in (voice_name, song_name) if clean(p)]
        name = ("_".join(parts) or "cover")[:120]
        return f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

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
            "谢谢你听我把这段话读完。\n\n"
            "知道、日子、吃饭、唱歌、上山、入水，\n"
            "这些词把卷舌音和平舌音都念一遍。\n"
            "白天与黑夜，前面和后面，里里外外都说清楚。\n\n"
            "二零二五年，三百六十五天，每一天都值得记录。\n"
            "电话号码是一三八，七九零，二四六八。\n"
            "价格是九块九，重量是两千克，距离是十公里。\n\n"
            "她轻声说：别担心，慢慢来，一切都会好起来。\n"
            "他大声喊：快看，那边的烟花真漂亮！\n"
            "雨停了，云散了，远处传来悠扬的歌声。\n\n"
            "啊、喔、鹅、衣、乌、迂，六个单韵母依次念出。\n"
            "安、恩、昂、英、翁，这些后鼻音也要饱满。\n"
            "风轻轻、水缓缓、心暖暖，叠词读得连贯又自然。\n\n"
            "从早到晚，由近及远，声音始终清楚而温和。\n"
            "无论高音还是低音，都尽量稳住气息，不抖不飘。\n"
            "好了，这段练习就到这里，辛苦你陪我读完。\n"
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


from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class VoiceModelRef:
    name: str
    model_path: str = ""
    index_path: str = ""
    notes: str = ""


@dataclass
class CharacterProject:
    character_id: str
    name: str
    root_dir: Path
    voice_description: str = ""
    training_text_path: str = ""
    sample_dir: str = ""
    image_path: str = ""
    mouth_shape_paths: list[str] = field(default_factory=list)
    background_path: str = ""
    models: list[VoiceModelRef] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def config_path(self) -> Path:
        return self.root_dir / "character.json"

    @classmethod
    def load(cls, config_path: Path) -> "CharacterProject":
        with config_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        data["root_dir"] = Path(data["root_dir"])
        data["models"] = [VoiceModelRef(**item) for item in data.get("models", [])]
        return cls(**data)

    def save(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data["root_dir"] = str(self.root_dir)
        with self.config_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")

    @classmethod
    def create(
        cls,
        root_dir: Path,
        character_id: str,
        name: str,
        voice_description: str = "",
    ) -> "CharacterProject":
        project = cls(
            character_id=character_id,
            name=name,
            root_dir=root_dir,
            voice_description=voice_description,
            training_text_path=str(root_dir / "voice" / "training_text.txt"),
            sample_dir=str(root_dir / "voice" / "samples"),
        )
        project.save()
        return project


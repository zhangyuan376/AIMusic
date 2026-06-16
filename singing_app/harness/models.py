from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


StepStatus = Literal["pending", "running", "succeeded", "failed", "skipped"]


@dataclass
class StepResult:
    status: StepStatus
    artifacts: dict[str, str] = field(default_factory=dict)
    message: str = ""


@dataclass
class HarnessJob:
    job_id: str
    output_dir: Path
    steps: list[str]
    inputs: dict[str, Any]
    settings: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HarnessJob":
        return cls(
            job_id=data["job_id"],
            output_dir=Path(data["output_dir"]),
            steps=list(data["steps"]),
            inputs=dict(data.get("inputs", {})),
            settings=dict(data.get("settings", {})),
        )


@dataclass
class StepContext:
    job: HarnessJob
    workspace: Path
    logs_dir: Path
    artifacts: dict[str, str]
    dry_run: bool = False

    def artifact_path(self, key: str) -> Path:
        return Path(self.artifacts[key])

    def resolve(self, value: str | Path) -> Path:
        path = Path(value)
        return path if path.is_absolute() else (self.workspace / path)


from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from singing_app.config import RUNTIME


@dataclass
class RuntimeCheck:
    name: str
    ok: bool
    path: str = ""
    message: str = ""


def run_runtime_checks() -> list[RuntimeCheck]:
    checks = [
        _check_file("Tool Python", RUNTIME.tool_python),
        _check_python_module("Demucs", "demucs", RUNTIME.tool_python),
        _check_python_module("Edge TTS", "edge_tts", RUNTIME.tool_python),
        _check_file("FFmpeg", RUNTIME.ffmpeg),
        _check_file("Applio Python", RUNTIME.applio_python),
        _check_file("Applio core.py", RUNTIME.applio_core),
        _check_file("Default Pomao model", RUNTIME.default_model),
        _check_file("Default Pomao index", RUNTIME.default_index),
    ]
    return checks


def checks_as_dicts() -> list[dict[str, object]]:
    return [asdict(check) for check in run_runtime_checks()]


def all_checks_passed() -> bool:
    return all(check.ok for check in run_runtime_checks())


def _check_file(name: str, path: Path) -> RuntimeCheck:
    if path.exists():
        return RuntimeCheck(name=name, ok=True, path=str(path), message="Found")
    return RuntimeCheck(name=name, ok=False, path=str(path), message="Missing")


def _check_python_module(name: str, module_name: str, python_path: Path) -> RuntimeCheck:
    if not python_path.exists():
        return RuntimeCheck(
            name=name,
            ok=False,
            path=str(python_path),
            message="Python interpreter is missing",
        )

    process = subprocess.run(
        [str(python_path), "-c", f"import {module_name}; print('ok')"],
        cwd=str(RUNTIME.app_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return RuntimeCheck(
        name=name,
        ok=process.returncode == 0,
        path=module_name,
        message="Available" if process.returncode == 0 else process.stdout.strip(),
    )


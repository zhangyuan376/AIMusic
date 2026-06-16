from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence


class CommandError(RuntimeError):
    pass


def run_command(
    command: Sequence[str],
    cwd: Path,
    log_path: Path,
    dry_run: bool = False,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command_text = " ".join(f'"{part}"' if " " in part else part for part in command)

    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"$ {command_text}\n")

        if dry_run:
            log.write("[dry-run] command not executed\n")
            return

        process = subprocess.run(
            list(command),
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        log.write(process.stdout)
        if process.returncode != 0:
            raise CommandError(f"Command failed with exit code {process.returncode}: {command_text}")


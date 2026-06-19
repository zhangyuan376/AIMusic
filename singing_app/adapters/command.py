from __future__ import annotations

import codecs
import os
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
    env: dict[str, str] | None = None,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command_text = " ".join(f'"{part}"' if " " in part else part for part in command)

    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"$ {command_text}\n")
        log.flush()

        if dry_run:
            log.write("[dry-run] command not executed\n")
            return

        # Stream output to the log as it arrives so live progress (e.g. demucs /
        # Applio tqdm bars, which use carriage returns) can be parsed by the
        # WebUI while the command is still running. We merge stderr into stdout
        # and read raw bytes via read1 (returns whatever is available without
        # waiting to fill a buffer), decoding incrementally so multibyte UTF-8
        # split across chunk boundaries is not corrupted.
        process = subprocess.Popen(
            list(command),
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=({**os.environ, **env} if env else None),
        )
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        assert process.stdout is not None
        try:
            while True:
                chunk = process.stdout.read1(65536)
                if not chunk:
                    break
                text = decoder.decode(chunk)
                if text:
                    log.write(text)
                    log.flush()
        finally:
            process.stdout.close()
            returncode = process.wait()
        tail = decoder.decode(b"", final=True)
        if tail:
            log.write(tail)
            log.flush()
        if returncode != 0:
            raise CommandError(
                f"Command failed with exit code {returncode}: {command_text}"
            )


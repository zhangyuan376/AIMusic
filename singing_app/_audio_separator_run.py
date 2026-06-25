"""Bridge: run one audio-separator model on one file, in the Applio venv.

Invoked as a subprocess by adapters/audio_separator.py (the harness interpreter
has no audio-separator / onnxruntime; the Applio venv does, mirroring how Demucs
runs). Writes a result.json mapping {stem_label_lower: absolute_path} into the
output dir so the caller can pick the lead / clean stem without parsing the log.

argv: model_filename  input_path  output_dir  model_dir
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    model_filename, input_path, output_dir, model_dir = sys.argv[1:5]
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    from audio_separator.separator import Separator

    sep = Separator(
        model_file_dir=model_dir,
        output_dir=str(out),
        output_format="WAV",
    )
    sep.load_model(model_filename=model_filename)
    produced = sep.separate(str(input_path))

    # audio-separator returns basenames relative to output_dir; resolve them and
    # key each by the stem label embedded in "(Vocals)" / "(Dry)" style names.
    # The stem label is the LAST "(...)" group: audio-separator appends it as
    # "..._(StemLabel)_<modelname>.wav", and the input basename may itself carry
    # an earlier "(...)" (e.g. a karaoke lead is "..._(Vocals)_...") which must
    # not be mistaken for the stem label.
    mapping: dict[str, str] = {}
    for name in produced:
        path = Path(name)
        if not path.is_absolute():
            path = out / path
        label = "stem"
        open_idx = path.name.rfind("(")
        if open_idx != -1:
            close_idx = path.name.find(")", open_idx)
            if close_idx != -1:
                label = path.name[open_idx + 1 : close_idx].strip().lower()
        mapping[label] = str(path.resolve())

    (out / "result.json").write_text(json.dumps(mapping), encoding="utf-8")
    print("AUDIOSEP_RESULT " + json.dumps(mapping), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# AI Singing App Harness

This package contains the workflow harness for the local AI audio-cover app.

The harness runs jobs described by JSON files. Each job records:

- `state.json`: per-step status and failure messages
- `artifacts.json`: generated file paths
- `logs/*.log`: command output for each external tool

Commands below use `python` to mean the project interpreter. On Linux/macOS that
is `.venv/bin/python`; on Windows it is `tools\ApplioV3.6.2\env\python.exe`.

## Run A Job

```bash
python -m singing_app.main run --job singing_app/jobs/<job>.json
```

## Launch Web UI

```bash
python -m singing_app.main web
```

Or, in an installed app:

```bat
run_singing_web.bat
```

The web UI opens `http://127.0.0.1:7860` and exposes the same harness flow through local JSON APIs. It is intended for easier debugging in a browser.

The browser workflow is designed for non-technical use:

1. Describe the character voice style, or upload a folder of real recordings.
2. Generate audition samples and listen in the browser (TTS route).
3. Save the preferred voice / prepared recordings into local voice history.
4. Train an RVC model from the prepared material; it auto-binds on completion.
5. Pick a song; vocal separation runs as its own step.
6. Convert the separated vocal to the chosen voice and mix the cover audio.

Historical voices are stored locally in `singing_app/voice_library.json`. This file is user data and should not be committed or bundled into installer builds.

The UI is a harness control panel. It can:

- create a voice sample generation / recording-prep job from a simple form
- create a model training job from a simple form
- create a cover-audio job from a simple form
- choose a job JSON
- run dry-run or real processing
- show `state.json` and `artifacts.json`
- open the output and logs folders

Print status:

```bash
python -m singing_app.main status --job singing_app/jobs/<job>.json
```

Dry-run without heavy processing:

```bash
python -m singing_app.main run --job singing_app/jobs/<job>.json --dry-run --no-resume
```

## Current Steps

- `check_runtime`
- `create_character`
- `generate_training_text`
- `generate_voice_samples`
- `prepare_recordings`
- `train_voice_model`
- `import_voice_model`
- `trim_song`
- `separate_vocals`
- `convert_vocals`
- `mix_audio`
- `export_result`

## Notes

The UI should call this harness instead of invoking Applio, Demucs, or FFmpeg directly.
This keeps the workflow resumable, testable, and easier to package.

## Packaging

Prepare and verify the offline staging folder:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_offline_staging.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_offline_staging.ps1
```

For quick validation without copying the large runtime:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_offline_staging.ps1 -SkipRuntime
powershell -ExecutionPolicy Bypass -File scripts\verify_offline_staging.ps1 -SkipRuntime
```

Build the final Inno Setup installer:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_inno_installer.ps1
```

## Current Limitations

This is a functional V1 harness and local Web UI. The app can create jobs, resume steps, inspect logs, generate samples, prepare recordings, train/import models, separate vocals, convert singing vocals, and mix cover audio. The scope is audio-only. Stronger repair flows and GPU-specific training presets are still future work.

# AI Singing App Harness

This package contains the workflow harness for the local AI singing video app.

The harness runs jobs described by JSON files. Each job records:

- `state.json`: per-step status and failure messages
- `artifacts.json`: generated file paths
- `logs/*.log`: command output for each external tool

## Run A Job

```powershell
d:\further\IP\tools\ApplioV3.6.2\env\python.exe -m singing_app.main run --job d:\further\IP\singing_app\jobs\pomao_demo_job.json
```

## Launch Desktop UI

Installed app:

```powershell
run_singing_app.bat
```

Development checkout:

```powershell
d:\further\IP\tools\ApplioV3.6.2\env\python.exe -m singing_app.main ui
```

## Launch Web UI

Installed app:

```powershell
run_singing_web.bat
```

Development checkout:

```powershell
d:\further\IP\tools\ApplioV3.6.2\env\python.exe -m singing_app.main web
```

The web UI opens `http://127.0.0.1:7860` and exposes the same harness flow through local JSON APIs. It is intended for easier debugging in a browser.

The first UI is a harness control panel. It can:

- create a singing video job from a simple form
- create a voice sample generation job from a simple form
- create a model training job from a simple form
- choose a job JSON
- run dry-run or real processing
- show `state.json`
- show `artifacts.json`
- open the output folder
- open the logs folder

Print status:

```powershell
d:\further\IP\tools\ApplioV3.6.2\env\python.exe -m singing_app.main status --job d:\further\IP\singing_app\jobs\pomao_demo_job.json
```

Dry-run without heavy processing:

```powershell
d:\further\IP\tools\ApplioV3.6.2\env\python.exe -m singing_app.main run --job d:\further\IP\singing_app\jobs\new_character_voice_job.json --dry-run --no-resume
```

Generate voice samples only:

```powershell
d:\further\IP\tools\ApplioV3.6.2\env\python.exe -m singing_app.main run --job d:\further\IP\singing_app\jobs\demo_character_voice_samples.json --dry-run --no-resume
```

Train a model from a sample directory:

```powershell
d:\further\IP\tools\ApplioV3.6.2\env\python.exe -m singing_app.main run --job d:\further\IP\singing_app\jobs\demo_character_train_demo_character_voice.json --dry-run --no-resume
```

## Current Steps

- `check_runtime`
- `create_character`
- `generate_training_text`
- `generate_voice_samples`
- `train_voice_model`
- `import_voice_model`
- `trim_song`
- `separate_vocals`
- `convert_vocals`
- `mix_audio`
- `compose_video`
- `export_result`

## Notes

The UI should call this harness instead of invoking Applio, Demucs, or FFmpeg directly.
This keeps the workflow resumable, testable, and easier to package into a Windows installer.

## Packaging

Build the desktop exe:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_pyinstaller.ps1
```

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

This is a functional V1 harness and Windows UI prototype. The app can create jobs, resume steps, inspect logs, generate samples, train/import models, separate vocals, convert singing vocals, mix audio, and synthesize a basic singing video. The UI is intentionally simple; a polished PySide6 interface, stronger repair flows, GPU-specific training presets, and richer mouth-shape animation are still future work.


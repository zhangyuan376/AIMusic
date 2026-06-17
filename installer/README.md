# Installer Plan

The application should install everything needed for a non-technical user to run the full workflow.

## First Version: Offline Full Installer

Ship a large but self-contained Windows installer:

- local WebUI app files
- `run_singing_web.bat`
- bundled Python runtime
- bundled Applio runtime
- bundled Demucs and Edge TTS Python packages
- bundled FFmpeg
- default Pomao example model
- default character images

The installed app must not depend on system `PATH`.

Expected installed layout:

```text
AISingingVideo/
  run_singing_web.bat
  run_singing_app.bat
  check_singing_app_runtime.bat
  tools/
    ApplioV3.6.2/
      env/python.exe
      ffmpeg.exe
      core.py
      ...
  voice_pipeline/
    Generated_image.png
    Generated_image1.png
    Generated_image2.png
    Generated_image3.png
    models/
      pomao_clear_voice_10e_1350s.pth
      pomao_clear_voice.index
  singing_app/
    jobs/
    projects/
```

The browser-based UI is launched with `run_singing_web.bat` and opens `http://127.0.0.1:7860`.

## Runtime Check

After install and on first launch, run:

```powershell
python -m singing_app.main check-runtime
```

The UI also exposes the same checks in the `Runtime Check` tab.

Required checks:

- Applio Python exists
- Applio `core.py` exists
- FFmpeg exists
- `demucs` imports successfully
- `edge_tts` imports successfully
- default `.pth` model exists
- default `.index` file exists
- default character image exists

## Build Commands

Prepare an offline staging folder:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_offline_staging.ps1
```

Prepare staging without copying the large runtime, useful for quick validation:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_offline_staging.ps1 -SkipRuntime
```

Build the Inno Setup installer:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_inno_installer.ps1
```

If Inno Setup is not installed, install Inno Setup 6 first or pass `-InnoCompiler`.

## Future Lightweight Installer

Later, split the installer into:

- small app installer
- first-launch runtime downloader
- resumable runtime download and verification
- one-click repair if files are missing


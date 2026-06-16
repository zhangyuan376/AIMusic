# AIMusic

Pomao 角色唱歌视频与声线实验工程。

这个仓库保留可复用的工程文件：

- 角色图片素材
- 声线设定
- 训练文本
- 本地样本生成脚本
- RVC/Applio 工作流说明
- AI Singing Video 桌面应用源码
- harness 工作流、安装器配置和打包脚本

不会提交本地大工具包、训练缓存、歌曲素材、模型权重、生成音频、离线 staging 或最终安装包分卷文件。

## 目录

```text
assets/images/
  角色图片素材

voice_pipeline/
  README.md                         声线流程说明
  voice_profile.md                  Pomao 声线设定
  pomao_training_script_zh.txt       训练文本
  install_prereqs.ps1               安装 Python/FFmpeg
  generate_pomao_tts_samples.ps1     初版 TTS 样本生成
  generate_pomao_balanced_samples.ps1 角色感样本生成
  generate_pomao_clear_samples.ps1   清晰自然版样本生成

singing_app/
  main.py                            harness CLI
  ui.py                              tkinter 桌面 UI
  web.py                             本地浏览器 Web UI/API
  harness/                           可恢复工作流引擎
  adapters/                          Applio/Demucs/FFmpeg/Edge TTS 适配器
  jobs/                              示例 job

installer/
  AISingingVideo.iss                 Inno Setup 安装器配置
  runtime_manifest.json              离线运行时清单

scripts/
  build_pyinstaller.ps1              构建桌面 exe
  build_offline_staging.ps1          生成完整离线 staging
  verify_offline_staging.ps1         验证 staging 缺失文件
  build_inno_installer.ps1           构建 Inno 分卷安装包
```

## 当前推荐流程

1. 用 `voice_pipeline/generate_pomao_clear_samples.ps1` 生成清晰版声线样本。
2. 用 Applio/RVC 训练角色声线模型。
3. 用 Demucs 做人声/伴奏分离。
4. 只转换人声，再混回伴奏。

详细步骤见 `voice_pipeline/README.md`。

## 桌面应用

开发环境启动：

```powershell
tools\ApplioV3.6.2\env\python.exe -m singing_app.main ui
```

安装包环境启动：

```bat
run_singing_app.bat
```

浏览器调试版：

```bat
run_singing_web.bat
```

默认打开 `http://127.0.0.1:7860`。

运行时检查：

```bat
check_singing_app_runtime.bat --no-pause
```

## 打包

构建 UI exe：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_pyinstaller.ps1
```

准备完整离线 staging：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_offline_staging.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_offline_staging.ps1
```

构建最终安装包：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_inno_installer.ps1
```

完整离线安装包会生成到本地 `installer_output/`，体积很大，不提交到 GitHub。
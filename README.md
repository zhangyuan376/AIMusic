# AIMusic

Pomao 角色翻唱音频与声线实验工程。

这个仓库保留可复用的工程文件：

- 角色图片素材
- 声线设定
- 训练文本
- 本地样本生成脚本
- RVC/Applio 工作流说明
- AI Singing Video 本地 WebUI 源码
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
  web.py                             本地浏览器 Web UI/API
  harness/                           可恢复工作流引擎
  adapters/                          Applio/Demucs/FFmpeg/Edge TTS 适配器
  jobs/                              示例 job

installer/
  AISingingVideo.iss                 Inno Setup 安装器配置
  runtime_manifest.json              离线运行时清单

scripts/
  fetch_applio_prereqs.sh            下载 Applio 公开前置模型(镜像友好)
  setup_cosyvoice.sh                 安装可选的 CosyVoice 2 声线克隆引擎(镜像友好)
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

## 本地 WebUI

新电脑首次搭建环境：

```bat
setup_env.bat
```

这会在 `tools\ApplioV3.6.2\env` 创建本地 Python 环境，并安装 `requirements.txt` 里的 Python 依赖。模型权重、歌曲素材、生成音频、完整 Applio 工具包等大文件仍属于本机运行时资产，不会提交到 GitHub；如果运行时检查提示缺失，按提示把对应文件复制到本机路径。

开发环境启动：

```powershell
tools\ApplioV3.6.2\env\python.exe -m singing_app.main web
```

安装包环境启动：

```bat
run_singing_web.bat
```

默认打开 `http://127.0.0.1:7860`。

### Linux / macOS

代码已跨平台。在 Linux/macOS 上首次搭建环境:

```bash
bash setup_env.sh
```

这会在仓库根目录创建 `.venv`,安装 `requirements.txt` 依赖,并检查 FFmpeg(缺失时会提示用 `apt`/`brew` 安装)。国内可走镜像:

```bash
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple bash setup_env.sh
```

启动 WebUI:

```bash
bash run_singing_web.sh
```

可执行文件路径按平台自动解析。框架区分两类运行环境:

- **工具环境**(Demucs / Edge TTS):pip 可安装,跑在项目自管的 `.venv` 里。
- **Applio 环境**(RVC 翻唱推理 `core.py`、训练):外部重型工具包,装在 `tools/ApplioV3.6.2/`,自带独立 Python。

可用环境变量覆盖默认路径:

- `AI_SINGING_PYTHON` — 工具环境的 Python(Demucs/Edge TTS)
- `AI_SINGING_APPLIO_ROOT` — Applio 工具包根目录(换版本/换位置)
- `AI_SINGING_APPLIO_PYTHON` — Applio 环境的 Python(RVC)
- `AI_SINGING_FFMPEG` — FFmpeg 可执行文件

Applio 工具包、模型权重(`.pth`/`.index`)等大文件仍是本机运行时资产,不提交到 GitHub;运行时检查会显示缺失路径,按提示拷入即可。

### 下载 Applio 公开前置资产

训练和翻唱都依赖一组**公开、非私有**的 RVC 模型:`rmvpe`(音高提取)、`contentvec`(嵌入)、HiFi-GAN 预训练底模。它们体积大,不入库。装好 Applio 工具包后下载一次即可:

```bash
bash scripts/fetch_applio_prereqs.sh
```

国内默认走 `hf-mirror.com` 镜像;海外可指定官方源,或一次拉多个采样率底模:

```bash
HF_ENDPOINT=https://huggingface.co bash scripts/fetch_applio_prereqs.sh
SAMPLE_RATES="32k 40k 48k" bash scripts/fetch_applio_prereqs.sh
```

### 训练自己的声线(通用流程,不依赖任何预置模型)

1. 创建角色、用 Edge TTS 生成声线样本(`generate_voice_samples`)。
   - 默认走 `neutral` 预设:音高/音量不偏移、只做必要的格式转换(单声道 44.1k),
     训练文本是与角色名/声线设定自动拼接的通用、音素多样脚本——不会把任何角色带偏到某个固定音色。
   - 可在 job 的 `voice` 里设 `voice_preset` 切换预设(目前内置 `neutral`、`pomao_clear`),
     或用 `training_text` 直接提供自定义训练文本。
2. `train_voice_model` 用 Applio 自带的标准流程训练:`preprocess → extract → train → index`,产出 `tools/ApplioV3.6.2/logs/<model_name>/` 下的 `.pth` + `.index`。
3. `import_voice_model` 自动登记训练好的模型(也可手动指定 `model_path`/`index_path`)。
4. 选歌 → 人声分离 → `convert_vocals` 翻唱 → 混音,输出翻唱音频。

> 若音频处理报 `No module named '_lzma'`,说明当前 Python 编译时缺 `liblzma`;装 `liblzma-dev` 重建 Python,或改用自带 lzma 的 python-build-standalone / conda 解释器。

### 可选:CosyVoice 2 声线克隆引擎

Edge TTS 用的是固定的微软预置嗓音;若想从**一小段真人录音**克隆出真正不同的音色,可启用 CosyVoice 2(零样本克隆,本地离线、GPU 加速)。它是体积较大的外部运行时(代码 + 模型约 6 GB),不入库,一次性安装:

```bash
bash scripts/setup_cosyvoice.sh
```

脚本镜像友好(代码走 GitHub 带重试、Python 依赖走清华源、模型走 ModelScope),装到 `tools/CosyVoice/`(独立 venv,不污染 Applio 环境)。可用环境变量覆盖路径:`AI_SINGING_COSYVOICE_ROOT`、`AI_SINGING_COSYVOICE_PYTHON`、`AI_SINGING_COSYVOICE_MODEL`。

启用方式:在 job 的 `voice` 里设

```json
"tts_engine": "cosyvoice",
"reference_audio": "<一段 3–10s 的参考录音.wav>",
"reference_text": "<这段录音对应的文字>"
```

CosyVoice 会用参考录音的音色把训练文本逐句念出来,生成的样本同样可直接进 `train_voice_model` 训练 RVC。不设 `tts_engine` 时默认仍是 `edge_tts`,无需录音。


浏览器版目标流程：

1. 用户输入角色名和声线风格。
2. 系统自动生成多条声线试听样本，用户在浏览器里播放试听。
3. 用户保存喜欢的试听到历史声线；如果已训练/导入模型，可绑定 `.pth` 和 `.index`。
4. 用户选择音乐和历史声线，系统自动做人声分离、RVC 翻唱、混音，输出翻唱音频。

历史声线保存在本机 `singing_app/voice_library.json`，属于用户数据，不提交到 GitHub。

运行时检查：

```bat
check_singing_app_runtime.bat --no-pause
```

## 打包

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
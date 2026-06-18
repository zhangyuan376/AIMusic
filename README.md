# AIMusic

通用的 AI 音频翻唱工具。任何人都能在本机走完整条链路:

```text
创建角色 → 生成 / 克隆声线样本 → 训练自己的 RVC 声线模型 → 给歌曲翻唱换声
```

只做**音频**(人声转换 + 混音),不涉及视频合成。支持 Windows 和桌面 Linux / macOS,同一份代码跨平台运行。

## 仓库内容

会提交到 GitHub 的是可复用的工程文件:

- `singing_app/` —— harness 工作流引擎 + 本地浏览器 WebUI 源码
- `scripts/` —— 前置资产下载、可选引擎安装、打包脚本
- `installer/` —— Windows 安装器配置
- 跨平台启动 / 搭环境脚本

**不会**提交本机大文件资产:Applio 工具包、模型权重(`.pth`/`.index`)、训练缓存、歌曲素材、生成音频、离线 staging、安装包分卷。运行时检查会列出缺失项,按提示拷入或下载即可。

## 目录

```text
singing_app/
  main.py            harness CLI
  web.py             本地浏览器 WebUI / API
  web_static/        WebUI 前端
  harness/           可恢复工作流引擎
  adapters/          Applio / Demucs / FFmpeg / Edge TTS 适配器
  jobs/              示例 job

scripts/
  fetch_applio_prereqs.sh   下载 Applio 公开前置模型(镜像友好)
  setup_cosyvoice.sh        安装可选的 CosyVoice 2 声线克隆引擎(镜像友好)
  build_offline_staging.ps1 生成完整离线 staging
  verify_offline_staging.ps1 验证 staging 缺失文件
  build_inno_installer.ps1  构建 Inno 分卷安装包

installer/
  AISingingVideo.iss        Inno Setup 安装器配置
  runtime_manifest.json     离线运行时清单

voice_pipeline/             早期 Pomao 声线的手动流程脚本与笔记(示例,WebUI 已自动化)
```

## 快速开始

### Linux / macOS

首次搭建环境:

```bash
bash setup_env.sh
```

会在仓库根目录创建 `.venv`、安装 `requirements.txt` 依赖,并检查 FFmpeg(缺失时提示用 `apt`/`brew` 安装)。国内可走镜像:

```bash
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple bash setup_env.sh
```

启动 WebUI:

```bash
bash run_singing_web.sh
```

### Windows

```bat
setup_env.bat
run_singing_web.bat
```

`setup_env.bat` 在 `tools\ApplioV3.6.2\env` 创建本地 Python 环境并安装依赖。

两个平台默认都打开 `http://127.0.0.1:7860`。

## 跨平台与环境变量

可执行文件路径按平台自动解析。框架区分两类运行环境:

- **工具环境**(Demucs / Edge TTS):pip 可安装,跑在项目自管的 `.venv` 里。
- **Applio 环境**(RVC 翻唱推理 `core.py`、训练):外部重型工具包,装在 `tools/ApplioV3.6.2/`,自带独立 Python。

可用环境变量覆盖默认路径:

- `AI_SINGING_PYTHON` — 工具环境的 Python(Demucs / Edge TTS)
- `AI_SINGING_APPLIO_ROOT` — Applio 工具包根目录(换版本 / 换位置)
- `AI_SINGING_APPLIO_PYTHON` — Applio 环境的 Python(RVC)
- `AI_SINGING_FFMPEG` — FFmpeg 可执行文件

## 下载 Applio 公开前置资产

训练和翻唱都依赖一组**公开、非私有**的 RVC 模型:`rmvpe`(音高提取)、`contentvec`(嵌入)、HiFi-GAN 预训练底模。它们体积大,不入库。装好 Applio 工具包后下载一次即可:

```bash
bash scripts/fetch_applio_prereqs.sh
```

国内默认走 `hf-mirror.com` 镜像;海外可指定官方源,或一次拉多个采样率底模:

```bash
HF_ENDPOINT=https://huggingface.co bash scripts/fetch_applio_prereqs.sh
SAMPLE_RATES="32k 40k 48k" bash scripts/fetch_applio_prereqs.sh
```

## 训练自己的声线(通用流程,不依赖任何预置角色)

1. 创建角色、用 Edge TTS 生成声线样本(`generate_voice_samples`)。
   - 默认走 `neutral` 预设:音高 / 音量不偏移、只做必要的格式转换(单声道 44.1k),训练文本是与角色名 / 声线设定自动拼接的通用、音素多样脚本——不会把角色带偏到某个固定音色。
   - 可在 job 的 `voice` 里设 `voice_preset` 切换预设(内置 `neutral`、`pomao_clear`),或用 `training_text` 直接提供自定义训练文本。
   - 也可以改用**真人录音**(在 WebUI「素材 B」上传一个文件夹的录音)代替 TTS 样本。
2. `train_voice_model` 用 Applio 标准流程训练:`preprocess → extract → train → index`,产出 `tools/ApplioV3.6.2/logs/<model_name>/` 下的 `.pth` + `.index`。
3. `import_voice_model` 自动登记训练好的模型(也可手动指定 `model_path`/`index_path`)。
4. 选歌 → 人声分离 → `convert_vocals` 翻唱 → 混音,输出翻唱音频。

> 若音频处理报 `No module named '_lzma'`,说明当前 Python 编译时缺 `liblzma`;装 `liblzma-dev` 重建 Python,或改用自带 lzma 的 python-build-standalone / conda 解释器。

## 可选:CosyVoice 2 声线克隆引擎

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

## 浏览器流程

1. 输入角色名和声线风格,或上传一个文件夹的真人录音。
2. 系统自动生成多条声线试听样本(TTS 路线),在浏览器里播放试听。
3. 把准备好的素材训练成 RVC 声线模型;训练完成后自动绑定。也可查看训练检查点,改用更早的一轮防过拟合。
4. 选择音乐和声线,系统自动做人声分离、RVC 翻唱、混音,输出翻唱音频。

历史声线保存在本机 `singing_app/voice_library.json`,属于用户数据,不提交到 GitHub。

运行时检查:

```bash
.venv/bin/python -m singing_app.main check-runtime
```

Windows:

```bat
check_singing_app_runtime.bat --no-pause
```

## 打包(Windows 安装包)

准备并验证完整离线 staging:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_offline_staging.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_offline_staging.ps1
```

构建最终安装包:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_inno_installer.ps1
```

完整离线安装包会生成到本地 `installer_output/`,体积很大,不提交到 GitHub。

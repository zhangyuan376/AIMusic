# AIMusic

通用的本地 AI 音频翻唱工具,只做**音频**(人声转换 + 混音),不涉及视频合成。同一份代码跨 Windows / Linux / macOS 运行。

```text
创建角色 → 生成 / 克隆声线样本 → 训练 RVC 声线模型 → 给歌曲翻唱换声
```

---

## 搭建环境(三步走)

### 1. 装好系统依赖

| 工具 | 最低版本 | 安装方式 |
| --- | --- | --- |
| Python | 3.10+(推荐 3.12) | [python.org](https://www.python.org/downloads/) / `apt install python3` / `brew install python` |
| FFmpeg | 4.x+ | `apt install ffmpeg` / `brew install ffmpeg` / Windows 装 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) 并加进 PATH |
| Git | 任意 | 用于克隆仓库 |

> Linux 装 Python 时如果是从源码编译的,记得先 `apt install -y liblzma-dev`,否则音频处理会报 `No module named '_lzma'`。Windows / macOS 官方安装包默认带 lzma,无需操心。

### 2. 克隆仓库并跑一键脚本

```bash
git clone https://github.com/zhangyuan376/AIMusic.git
cd AIMusic
```

**Linux / macOS:**

```bash
bash setup_env.sh
```

**Windows:**

```bat
setup_env.bat
```

脚本会创建 `.venv`、装齐 `requirements.txt`、检查 FFmpeg 和 lzma。国内可走清华源:

```bash
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple bash setup_env.sh
```

### 3. 启动 WebUI

**Linux / macOS:**

```bash
bash run_singing_web.sh
```

**Windows:**

```bat
run_singing_web.bat
```

浏览器打开 `http://127.0.0.1:7860` 即可使用。

---

## 选装模块(按需)

下面两块都是体积大、不入库的外部运行时,**只在你要用 RVC 训练 / 翻唱、或者要做声线克隆时才装**。WebUI 在用到时会提示缺失项。

### A. Applio 工具包(RVC 训练 / 翻唱必装)

Applio 提供 RVC 训练和翻唱推理。下载 Applio 工具包到 `tools/ApplioV3.6.2/`(自带独立 Python 环境),然后拉一次公开前置模型:

```bash
bash scripts/fetch_applio_prereqs.sh
```

国内默认走 `hf-mirror.com`;海外可指定官方源:

```bash
HF_ENDPOINT=https://huggingface.co bash scripts/fetch_applio_prereqs.sh
```

### B. CosyVoice 2(可选,真人声线零样本克隆)

如果想从一段 3–10 秒真人录音克隆出新音色,启用 CosyVoice 2(代码 + 模型约 6 GB,本地离线 GPU 推理):

```bash
bash scripts/setup_cosyvoice.sh
```

脚本自带镜像友好策略(GitHub 重试 / 清华源 / ModelScope),装到 `tools/CosyVoice/` 独立 venv,不污染 Applio 环境。

---

## 验证环境

```bash
.venv/bin/python -m singing_app.main check-runtime
```

Windows:

```bat
check_singing_app_runtime.bat --no-pause
```

会列出所有可执行文件 / 模型 / 资产的就绪情况,缺什么按提示装即可。

---

## 自定义路径(可选)

环境变量可覆盖默认路径:

| 变量 | 用途 |
| --- | --- |
| `AI_SINGING_PYTHON` | 工具环境 Python(Demucs / Edge TTS) |
| `AI_SINGING_APPLIO_ROOT` | Applio 工具包根目录 |
| `AI_SINGING_APPLIO_PYTHON` | Applio 环境 Python(RVC) |
| `AI_SINGING_FFMPEG` | FFmpeg 可执行文件 |
| `AI_SINGING_COSYVOICE_ROOT` | CosyVoice 安装根目录 |
| `AI_SINGING_COSYVOICE_PYTHON` | CosyVoice 环境 Python |
| `AI_SINGING_COSYVOICE_MODEL` | CosyVoice 模型路径 |

---

## 仓库结构

```text
singing_app/        harness 工作流引擎 + WebUI 源码
  main.py           harness CLI
  web.py            本地 WebUI / API
  web_static/       前端
  harness/          可恢复工作流引擎
  adapters/         Applio / Demucs / FFmpeg / Edge TTS / DiffSinger 等适配器
  jobs/             示例 job

scripts/            前置资产 / 选装引擎脚本
```

**不入库:** Applio 工具包、`.pth` / `.index` 模型权重、训练缓存、歌曲素材、生成音频。

---

## 浏览器流程

1. 输入角色名和声线风格,或上传一个文件夹的真人录音。
2. 系统生成多条声线试听样本(TTS 路线),浏览器试听。
3. 把准备好的素材训练成 RVC 声线模型,完成后自动绑定。
4. 选歌 → 自动人声分离 → RVC 翻唱 → 混音,输出翻唱音频。

历史声线保存在 `singing_app/voice_library.json`(本地用户数据,不入库)。

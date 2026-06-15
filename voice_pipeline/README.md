# Pomao 角色声线流程

目标：不用自己录音，先做一个“原创感”的 Pomao 男声，用来翻唱歌曲片段。

推荐路线：

```text
AI/TTS 生成 Pomao 声线样本
-> 用 RVC/Applio 训练角色声线模型
-> 用 UVR5 分离歌曲人声和伴奏
-> 用 RVC 把原唱人声转换成 Pomao 声线
-> 混回伴奏，导出 15-30 秒片段
```

## 重要边界

不要用真实歌手、主播、演员的声音训练，也不要把多个歌手模型融合。那样技术上可行，但发布风险高。

本流程先用免费 TTS 生成 demo 声线样本。免费 TTS 的平台条款不一定支持商业使用，所以适合测试账号风格和视频效果。后续如果要商业化，把 `samples` 里的声音源替换成明确可商用的授权 AI 声音或配音素材。

## 当前机器状态

已检测：

- Git 已安装
- winget 可用
- Python 未安装
- FFmpeg 未安装
- 未检测到 NVIDIA GPU

所以第一版建议用：

- `edge-tts` 生成 demo 训练样本
- RVC/Applio 做离线换声
- CPU 可以推理，训练会很慢；如果没有 GPU，建议先用 Google Colab 或找 Windows 一键包跑训练

## 第一步：安装基础工具

在 PowerShell 里执行：

```powershell
winget install -e --id Python.Python.3.10
winget install -e --id Gyan.FFmpeg
```

安装完后重新打开 Cursor/PowerShell，检查：

```powershell
python --version
ffmpeg -version
```

## 第二步：生成 Pomao 声线样本

安装 Python 依赖：

```powershell
python -m pip install --upgrade pip
python -m pip install edge-tts
```

然后运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\voice_pipeline\generate_pomao_tts_samples.ps1
```

脚本会把 demo 声线样本输出到：

```text
voice_pipeline/samples/
```

## 第三步：训练 RVC 模型

建议使用 Applio 或 RVC WebUI。

### 选项 A：Applio

适合新手，界面更友好。搜索并下载官方 Applio Windows 版本后：

1. 打开 Applio
2. 进入训练/Train
3. 数据集路径选择 `voice_pipeline/samples`
4. 模型名填 `pomao_male_sad`
5. F0 方法优先选 `rmvpe`
6. 训练完成后保存 `.pth` 和 `.index`

### 选项 B：RVC WebUI

官方仓库：

```text
https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI
```

Windows 一键包一般可以直接解压运行 `go-web.bat`。训练时把 `voice_pipeline/samples` 作为数据集。

## 第四步：翻唱片段

1. 把歌曲片段放到 `voice_pipeline/input_song/`
2. 用 UVR5 或 RVC WebUI 自带 UVR5 分离：
   - vocals：原唱人声
   - instrumental：伴奏
3. 在 RVC 推理页面选择 `pomao_male_sad` 模型
4. 输入原唱人声，转换成 Pomao 声线
5. 用 Audacity/Reaper/剪映把转换后人声和伴奏混回去

## Pomao 声线设定

```text
年轻男声，偏低但不厚重，轻微沙哑，慵懒克制，悲伤但不夸张。
像抱着小吉他在雨夜房间里小声唱歌。
不要像任何真实歌手。
```

## 文件说明

- `voice_profile.md`：角色声线设定
- `pomao_training_script_zh.txt`：用于生成/录制训练样本的文本
- `generate_pomao_tts_samples.ps1`：用 TTS 批量生成 demo 样本
- `samples/`：训练样本输出目录
- `input_song/`：放待翻唱歌曲片段
- `output/`：放换声和混音结果

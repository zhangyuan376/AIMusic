# AI Singing Video 使用说明

## 一键启动

安装后双击桌面图标，或在安装目录运行：

```bat
run_singing_app.bat
```

如果想用浏览器调试版，运行：

```bat
run_singing_web.bat
```

浏览器版默认打开：

```text
http://127.0.0.1:7860
```

如果打不开，先运行：

```bat
check_singing_app_runtime.bat
```

所有项目结果会保存到：

```text
singing_app\projects\
```

## 推荐流程

1. 打开 `Runtime Check`，确认 Python、FFmpeg、Applio、Demucs、Edge TTS、默认模型都显示 OK。
2. 打开 `Create Singing Video`，选择角色图片、歌曲文件和 Pomao 默认模型。
3. 点击创建 job，再到 `Harness Status` 选择这个 job。
4. 第一次建议勾选 dry-run，确认流程能跑通。
5. 取消 dry-run 后再正式运行。
6. 完成后点击打开输出目录，查看 `final_mix.wav` 和 `final_video.mp4`。

## 声线制作

如果要做新角色声线：

1. 在 `Voice Builder` 里填写角色名和声线描述，生成 TTS 训练样本。
2. 在 `Train Model` 里选择样本目录，创建训练任务。
3. 训练很慢，CPU 上可能需要很久。建议先用少量 epoch 测试，再增加训练轮数。
4. 训练完成后，使用生成的 `.pth` 和 `.index` 文件做翻唱转换。

## 出错时看哪里

每个 job 都会保存：

```text
state.json
artifacts.json
logs\
```

`state.json` 记录每一步成功或失败；`logs` 里是 FFmpeg、Demucs、Applio 等工具的原始输出。

## 当前版本限制

这是 V1 本地离线版，已经包含完整 harness 流程和基础桌面 UI。当前视频合成还是基础版：角色轻微移动、静态背景、基础嘴型/画面合成。后续可以继续升级成更精细的嘴型驱动、PySide6 高级界面、GPU 训练预设和一键修复运行时。

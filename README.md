# AIMusic

Mochi 角色唱歌视频与声线实验工程。

这个仓库只保留可复用的轻量文件：

- 角色图片素材
- 声线设定
- 训练文本
- 本地样本生成脚本
- RVC/Applio 工作流说明

不会提交本地大工具包、训练缓存、歌曲素材、模型权重或生成音频。

## 目录

```text
assets/images/
  角色图片素材

voice_pipeline/
  README.md                         声线流程说明
  voice_profile.md                  Mochi 声线设定
  mochi_training_script_zh.txt       训练文本
  install_prereqs.ps1               安装 Python/FFmpeg
  generate_mochi_tts_samples.ps1     初版 TTS 样本生成
  generate_mochi_balanced_samples.ps1 角色感样本生成
  generate_mochi_clear_samples.ps1   清晰自然版样本生成
```

## 当前推荐流程

1. 用 `voice_pipeline/generate_mochi_clear_samples.ps1` 生成清晰版声线样本。
2. 用 Applio/RVC 训练角色声线模型。
3. 用 Demucs 做人声/伴奏分离。
4. 只转换人声，再混回伴奏。

详细步骤见 `voice_pipeline/README.md`。
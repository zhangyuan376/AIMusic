# 声线流程参考(早期手动版)

> 这个目录是项目早期**手动**做声线的脚本和笔记,以 Pomao 男声为例。
> 现在 `singing_app` 的 WebUI 已经把整条链路自动化了——日常使用请直接用 WebUI
> (见仓库根 `README.md`)。这里保留下来,只作为理解底层流程的参考和示例素材。

## 底层流程

不管是哪个角色,RVC 翻唱的底层链路都是这几步,WebUI 现在自动完成它们:

```text
AI/TTS 生成声线样本(或上传真人录音)
-> 用 RVC/Applio 训练角色声线模型
-> 用 Demucs 分离歌曲的人声和伴奏
-> 用 RVC 把原唱人声转换成目标声线
-> 混回伴奏,导出翻唱音频
```

## 重要边界

不要用真实歌手、主播、演员的声音训练,也不要把多个歌手模型融合。那样技术上可行,但发布风险高。

用免费 TTS 生成的样本适合测试声线风格;免费 TTS 的平台条款不一定支持商业使用。后续如要商业化,把样本来源替换成明确可商用的授权 AI 声音或配音素材。

## 本目录文件(示例)

- `voice_profile.md` —— Pomao 角色声线设定示例
- `pomao_training_script_zh.txt` —— 用于生成 / 录制训练样本的文本示例
- `install_prereqs.ps1` —— 早期手动安装 Python / FFmpeg 的脚本
- `generate_pomao_tts_samples.ps1` —— 初版 TTS 样本生成
- `generate_pomao_balanced_samples.ps1` —— 角色感样本生成
- `generate_pomao_clear_samples.ps1` —— 清晰自然版样本生成

WebUI 里的 `generate_voice_samples` 步骤已经覆盖了这些 `.ps1` 的功能,并支持任意角色名 / 声线风格,无需手动跑脚本。

## Pomao 声线设定示例

```text
年轻男声,偏低但不厚重,轻微沙哑,慵懒克制,悲伤但不夸张。
像抱着小吉他在雨夜房间里小声唱歌。
不要像任何真实歌手。
```

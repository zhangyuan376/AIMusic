from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

from singing_app.config import RUNTIME

DEFAULT_SEPARATION_MODEL = "htdemucs_ft"

# Static catalogue of vocal-separation models surfaced in the WebUI. Each entry
# carries display metadata (quality / speed / vram / requirements) plus the
# engine that runs it. Only the "demucs" engine is wired into the runtime today;
# "roformer" is shown but flagged needs-install via availability detection.
SEPARATION_MODELS: list[dict] = [
    {
        "id": "htdemucs_ft",
        "label": "Demucs htdemucs_ft（推荐）",
        "engine": "demucs",
        "quality": "★★★★☆ · 人声 SDR≈9",
        "speed": "较慢（4 子模型集成，约 4×）",
        "vram": "建议 ≥4GB，可回退 CPU",
        "requirements": "Demucs 自带，首次使用自动下载权重（facebook 源，非 HF）。",
        "recommended": True,
    },
    {
        "id": "htdemucs",
        "label": "Demucs htdemucs（均衡）",
        "engine": "demucs",
        "quality": "★★★★☆ · 人声 SDR≈8.5",
        "speed": "中等",
        "vram": "建议 ≥4GB，可回退 CPU",
        "requirements": "Demucs v4 基础版，速度与质量均衡，首次使用自动下载权重。",
        "recommended": False,
    },
    {
        "id": "mdx_extra",
        "label": "Demucs mdx_extra（备选音色）",
        "engine": "demucs",
        "quality": "★★★☆☆ · 人声 SDR≈8",
        "speed": "中等",
        "vram": "建议 ≥4GB，可回退 CPU",
        "requirements": "MDX 额外数据训练，音色风格不同，可作为备选，首次使用自动下载权重。",
        "recommended": False,
    },
    {
        "id": "bs_roformer",
        "label": "BS-RoFormer（SOTA，需安装）",
        "engine": "roformer",
        "quality": "★★★★★ · 人声 SDR≈12-13",
        "speed": "较慢",
        "vram": "建议 ≥6GB",
        "requirements": "质量最佳，但需先安装 audio-separator 包并从 HuggingFace（走 hf-mirror）下载约几百 MB 权重。",
        "recommended": False,
    },
]

_ENGINE_PROBE = {
    "demucs": "import demucs",
    "roformer": "import audio_separator",
}


@lru_cache(maxsize=None)
def _engine_available(engine: str, python_path: str) -> bool:
    """Probe whether the given interpreter can import the engine's package.

    Mirrors adapters.applio._cuda_available: query the tool interpreter (Applio
    venv) that actually runs separation, not the harness interpreter. Any failure
    is treated as unavailable so the UI flags the model needs-install.
    """
    probe = _ENGINE_PROBE.get(engine)
    if probe is None:
        return False
    try:
        result = subprocess.run(
            [python_path, "-c", probe],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
        )
        return result.returncode == 0
    except Exception:
        return False


def resolve_separation_model(model_id: str) -> dict | None:
    for model in SEPARATION_MODELS:
        if model["id"] == model_id:
            return model
    return None


def list_separation_models(python_path: Path = RUNTIME.tool_python) -> list[dict]:
    py = str(python_path)
    return [
        {**model, "available": _engine_available(model["engine"], py)}
        for model in SEPARATION_MODELS
    ]

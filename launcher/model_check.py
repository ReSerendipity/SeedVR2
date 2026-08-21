# launcher/model_check.py
"""SeedVR2 启动器 - 模型文件校验与显存推荐（第 5/6 步）。

必装 3 项（VAE + 文本嵌入），主模型 6 选 1。文件名与 config.yaml 一致。
仅做文件存在 + 大小 + safetensors 头校验，不做自动下载。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

MANDATORY_FILES = ["ema_vae_fp16.safetensors", "pos_emb.pt", "neg_emb.pt"]

# 主模型：尺寸 × 精度（与 config.yaml model.models 对齐）
MAIN_MODEL_FILES = [
    "seedvr2_ema_3b_fp16.safetensors",
    "seedvr2_ema_3b_fp8_e4m3fn.safetensors",
    "seedvr2_ema_7b_fp16.safetensors",
    "seedvr2_ema_7b_fp8_e4m3fn.safetensors",
    "seedvr2_ema_7b_sharp_fp16.safetensors",
    "seedvr2_ema_7b_sharp_fp8_e4m3fn.safetensors",
]

_SAFETENSORS_MAGIC = b"<safetensors>"


def recommend_main_model(vram_gb: float) -> str:
    """按显存推荐主模型（与 README 选型一致）。"""
    if vram_gb < 12:
        return "3b_fp8"
    if vram_gb < 24:
        return "3b_fp16"
    return "7b_sharp_fp16"


def _validate_file(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "文件不存在"
    size = path.stat().st_size
    if size <= 0:
        return False, "文件为空"
    if path.suffix == ".safetensors":
        with open(path, "rb") as fh:
            if fh.read(len(_SAFETENSORS_MAGIC)) != _SAFETENSORS_MAGIC:
                return False, "safetensors 头无效（文件可能损坏）"
    return True, f"{size / 1024**3:.2f} GB"


@dataclass
class ModelCheckResult:
    files: dict = field(default_factory=dict)
    mandatory_ok: bool = False
    main_model_ok: bool = False
    ready: bool = False

    def to_dict(self) -> dict:
        return {
            "files": self.files,
            "mandatory_ok": self.mandatory_ok,
            "main_model_ok": self.main_model_ok,
            "ready": self.ready,
        }


def check_models(model_dir: Path) -> ModelCheckResult:
    files: dict = {}
    for name in MANDATORY_FILES + MAIN_MODEL_FILES:
        ok, detail = _validate_file(model_dir / name)
        files[name] = {"ok": ok, "detail": detail}
    mandatory_ok = all(files[n]["ok"] for n in MANDATORY_FILES)
    main_model_ok = any(files[n]["ok"] for n in MAIN_MODEL_FILES)
    return ModelCheckResult(
        files=files,
        mandatory_ok=mandatory_ok,
        main_model_ok=main_model_ok,
        ready=mandatory_ok and main_model_ok,
    )

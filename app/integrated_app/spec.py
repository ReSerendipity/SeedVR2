#!/usr/bin/env python3
"""SeedVR2 领域公式契约层（Spec Contract）。

将分散在 routes/engines/config 中的领域公式收口为纯函数，
不依赖 PyTorch 或 GPU 硬件，可离线测试和文档化。

公式来源：
  - common.parse_unified_params: batch_size 正规化 (4n+1)
  - _memory_utils: 时间维度对齐 (T-1) % (4*sp_size) == 0, Tile 对齐 16
  - common.enforce_double_resolution_if_enabled: 两倍模式分辨率与 tile 参数
  - configs_3b/configs_7b + config.yaml: 模型架构常量 / VRAM 阈值
  - video_processor: 帧率帧数计算公式
  - config_models: 分辨率回退规则

所属项目：SeedVR2 (SeedVR2 视频/图像修复工具)
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# VAE 空间下采样因子 (s8 = 空间 8x)
VAE_SPATIAL_FACTOR = 8

# DiT patch_size [1, 2, 2]: 空间 2x 下采样
PATCH_SIZE_SPATIAL = 2

# 潜空间空间缩放因子 = VAE_SPATIAL * PATCH_SPATIAL = 16
LATENT_SPATIAL_FACTOR = VAE_SPATIAL_FACTOR * PATCH_SIZE_SPATIAL  # 16

# Tile 对齐因子 (H/W 是 16 的倍数)
TILE_ALIGNMENT = 16

# 时间维度对齐: (T-1) 能被 4*sp_size 整除
TEMPORAL_ALIGN_MULTIPLE = 4

# 默认 sp_size (sequence parallel)
DEFAULT_SP_SIZE = 1

# 文本嵌入维度
TEXT_EMBED_DIM = 5120

# VAE 缩放因子
VAE_SCALING_FACTOR = 0.9152

# 扩散参数
DIFFUSION_T = 1000.0
DIFFUSION_STEPS = 50
DIFFUSION_CFG_SCALE = 7.5

# 条件参数
CONDITION_NOISE_SCALE = 0.25
CONDITION_SR = 1.0
CONDITION_I2V = 0.0
CONDITION_V2V = 0.0

# 默认输出分辨率 (config.yaml restore 节)
DEFAULT_RESOLUTION_H = 1080
DEFAULT_RESOLUTION_W = 1920
DEFAULT_SCALE_FACTOR = 2.0

# 模型架构规格 (来源: configs_3b/config.json, configs_7b/config.json)
_BASE_SPEC = {
    "vae_config": "model_lib/video_vae_v3/s8_c16_t4_inflation_sd3.yaml",
    "vae_scaling_factor": 0.9152,
    "diffusion": {"schedule_type": "lerp", "T": 1000.0, "sampler": "euler", "prediction_type": "v_lerp", "steps": 50},
    "cfg_scale": 7.5,
    "condition": {"i2v": 0.0, "v2v": 0.0, "sr": 1.0, "noise_scale": 0.25},
    "patch_size": [1, 2, 2],
    "window": [4, 3, 3],
    "attention_mode": "sdpa",
    "block_type": "mmdit_sr",
    "mlp_type": "swiglu",
    "rope_type": "mmrope3d",
    "rope_dim": 128,
    "expand_ratio": 4,
    "head_dim": 128,
    "qk_bias": False,
    "qk_norm": "fusedrms",
    "norm": "fusedrms",
    "norm_eps": 1e-05,
    "ada": "single",
    "mm_layers": 10,
}

MODEL_SPECS: dict[str, dict[str, Any]] = {
    "3b": {
        **_BASE_SPEC,
        "num_layers": 32,
        "vid_dim": 2560,
        "txt_in_dim": 5120,
        "txt_dim": 2560,
        "emb_dim": 15360,
        "heads": 20,
        "num_blocks": 32,
        "min_vram_fp16_gb": 16,
        "min_vram_fp8_gb": 8,
        "name": "SeedVR2-3B",
    },
    "7b": {
        **_BASE_SPEC,
        "num_layers": 36,
        "vid_dim": 3072,
        "txt_in_dim": 5120,
        "txt_dim": 3072,
        "emb_dim": 18432,
        "heads": 24,
        "num_blocks": 36,
        "min_vram_fp16_gb": 24,
        "min_vram_fp8_gb": 12,
        "name": "SeedVR2-7B",
        "mlp_type": "normal",
        "shared_mlp": False,
        "shared_qkv": False,
        "qk_rope": True,
    },
    "7b_sharp": {
        **_BASE_SPEC,
        "num_layers": 36,
        "vid_dim": 3072,
        "txt_in_dim": 5120,
        "txt_dim": 3072,
        "emb_dim": 18432,
        "heads": 24,
        "num_blocks": 36,
        "min_vram_fp16_gb": 24,
        "min_vram_fp8_gb": 12,
        "name": "SeedVR2-7B-Sharp",
        "mlp_type": "normal",
        "shared_mlp": False,
        "shared_qkv": False,
        "qk_rope": True,
    },
}

# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------


def normalize_batch_size(batch_size: int) -> int:
    """将 batch_size 正规化为 4n+1 形式。

    公式: max(1, 4 * round((batch_size - 1) / 4) + 1)
    来源: common.parse_unified_params

    Examples:
        >>> normalize_batch_size(5)   # 4*1+1 = 5
        5
        >>> normalize_batch_size(9)   # 4*2+1 = 9
        9
        >>> normalize_batch_size(10)  # round(9/4)=2 -> 4*2+1=9
        9
        >>> normalize_batch_size(3)   # round(2/4)=0 -> 4*0+1=1
        1
        >>> normalize_batch_size(-1)  # max(1, ...) = 1
        1
    """
    if batch_size < 1:
        return 1
    n = max(0, round((batch_size - 1) / 4))
    return max(1, 4 * n + 1)


def is_valid_batch_size(batch_size: int) -> bool:
    """检查 batch_size 是否满足 4n+1 形式。

    Returns:
        True 如果 (batch_size - 1) % 4 == 0。
    """
    return batch_size > 0 and (batch_size - 1) % 4 == 0


def pad_temporal_frames(num_frames: int, sp_size: int = DEFAULT_SP_SIZE) -> int:
    """将视频帧数向上对齐到满足 (T-1) % (4*sp_size) == 0。

    公式: 若 (num_frames - 1) % (4 * sp_size) != 0，
    则补齐到 num_frames + (4*sp_size - ((num_frames-1) % (4*sp_size)))

    Args:
        num_frames: 原始视频帧数。
        sp_size: 序列并行大小，默认 1。

    Returns:
        对齐后的帧数 (>= num_frames)。

    Examples:
        >>> pad_temporal_frames(33, 1)  # (32) % 4 == 0 -> 33
        33
        >>> pad_temporal_frames(32, 1)  # (31) % 4 == 3 -> 32+1=33
        33
        >>> pad_temporal_frames(1, 1)   # (0) % 4 == 0 -> 1
        1
    """
    if num_frames < 1:
        return 1
    align = TEMPORAL_ALIGN_MULTIPLE * sp_size
    remainder = (num_frames - 1) % align
    if remainder == 0:
        return num_frames
    return num_frames + align - remainder


def align_tile_dimension(dim: int, alignment: int = TILE_ALIGNMENT) -> int:
    """将空间维度向上对齐到 alignment 的倍数。

    Args:
        dim: 原始像素尺寸 (W 或 H)。
        alignment: 对齐因子，默认 16（满足 VAE/DIT 下采样要求）。

    Returns:
        对齐后的尺寸。

    Examples:
        >>> align_tile_dimension(1080)  # ceil(1080/16)*16 = 1088
        1088
        >>> align_tile_dimension(1920)  # 1920 / 16 = 120 -> 1920
        1920
        >>> align_tile_dimension(0)
        0
    """
    if dim <= 0:
        return 0
    remainder = dim % alignment
    if remainder == 0:
        return dim
    return dim + alignment - remainder


def double_res_target_resolution(width: int, height: int) -> int:
    """两倍模式目标分辨率：短边 × 2。

    公式: target_res = min(width, height) * 2

    Args:
        width: 图片宽度 (px)。
        height: 图片高度 (px)。

    Returns:
        目标分辨率 (int)。

    Examples:
        >>> double_res_target_resolution(1080, 1920)  # min(1080,1920)*2
        2160
    """
    if width <= 0 or height <= 0:
        return 0
    return min(width, height) * 2


def double_res_tile_params(short_edge: int) -> tuple[int, int]:
    """两倍模式 VAE tile 参数。

    公式:
      tile_size = max(64, short_edge)
      tile_overlap = max(0, min(int(short_edge * 0.5), tile_size // 2))

    Args:
        short_edge: 图片短边像素值。

    Returns:
        (tile_size, tile_overlap) 元组。

    Examples:
        >>> double_res_tile_params(1080)
        (1080, 540)
        >>> double_res_tile_params(256)
        (256, 128)
    """
    tile_size = max(64, int(short_edge))
    tile_overlap = max(0, min(int(short_edge * 0.5), tile_size // 2))
    return tile_size, tile_overlap


def latent_spatial_size(width: int, height: int) -> tuple[int, int]:
    """计算潜空间空间尺寸。

    公式: latent_w = pixel_w / LATENT_SPATIAL_FACTOR
          latent_h = pixel_h / LATENT_SPATIAL_FACTOR

    其中 LATENT_SPATIAL_FACTOR = VAE_SPATIAL_FACTOR(8) × PATCH_SIZE_SPATIAL(2) = 16

    Args:
        width: 对齐后的像素宽度。
        height: 对齐后的像素高度。

    Returns:
        (latent_w, latent_h)，均为整数。

    Examples:
        >>> latent_spatial_size(1920, 1088)
        (120, 68)
    """
    return (width // LATENT_SPATIAL_FACTOR, height // LATENT_SPATIAL_FACTOR)


def recommend_precision(vram_gb: float, min_vram_fp16: float, min_vram_fp8: float) -> str:
    """根据可用显存推荐模型精度。

    Args:
        vram_gb: 可用显存 (GB)。
        min_vram_fp16: fp16 最低显存要求 (GB)。
        min_vram_fp8: fp8 最低显存要求 (GB)。

    Returns:
        "fp16" 或 "fp8"。

    Examples:
        >>> recommend_precision(24.0, 16.0, 8.0)
        'fp16'
        >>> recommend_precision(10.0, 16.0, 8.0)
        'fp8'
        >>> recommend_precision(4.0, 16.0, 8.0)
        'fp8'
    """
    if vram_gb >= min_vram_fp16:
        return "fp16"
    if vram_gb >= min_vram_fp8:
        return "fp8"
    return "fp8"


def resolution_clamp(
    resolution: int,
    max_resolution: int = 0,
    default_h: int = DEFAULT_RESOLUTION_H,
    default_w: int = DEFAULT_RESOLUTION_W,
) -> tuple[int, int]:
    """分辨率回退与钳位。

    来源: VideoRestoreParams 文档:
      - resolution=0 时回退到 config.yaml restore 节默认值
      - max_resolution=0 时表示不限制
      - 短边=resolution, 长边<=max_resolution

    Args:
        resolution: 输出短边像素，0 表示用默认值。
        max_resolution: 长边上限，0 表示不限制。
        default_h: config.yaml restore.default_resolution_h。
        default_w: config.yaml restore.default_resolution_w。

    Returns:
        (resolution, max_resolution) 钳位后的值。
    """
    if resolution <= 0:
        # 回退到默认短边
        resolution = min(default_h, default_w)
    if max_resolution < 0:
        max_resolution = 0
    return resolution, max_resolution


def frame_count_from_duration(duration_sec: float, fps: float) -> int:
    """根据时长和帧率计算帧数。

    公式: frame_count = int(duration_sec × fps)

    Args:
        duration_sec: 视频时长 (秒)。
        fps: 帧率。

    Returns:
        帧数 (int)。

    Examples:
        >>> frame_count_from_duration(10.0, 30.0)
        300
        >>> frame_count_from_duration(0.5, 24.0)
        12
    """
    if duration_sec <= 0 or fps <= 0:
        return 0
    return int(duration_sec * fps)


def model_size_from_dit_model(dit_model: str) -> str:
    """从 dit_model 字符串提取模型尺寸标识。

    来源: common.model_size_from_dit_model

    Args:
        dit_model: 如 "3b_fp16"、"7b_sharp_fp16"。

    Returns:
        模型尺寸，如 "3b"、"7b_sharp"；空字符串返回 "3b"。

    Examples:
        >>> model_size_from_dit_model("3b_fp16")
        '3b'
        >>> model_size_from_dit_model("7b_sharp_fp16")
        '7b_sharp'
        >>> model_size_from_dit_model("")
        '3b'
    """
    if not dit_model:
        return "3b"
    parts = dit_model.split("_")
    if len(parts) >= 3 and parts[1] in ("sharp",):
        return f"{parts[0]}_{parts[1]}"
    return parts[0]


__all__ = [
    # Constants
    "VAE_SPATIAL_FACTOR",
    "PATCH_SIZE_SPATIAL",
    "LATENT_SPATIAL_FACTOR",
    "TILE_ALIGNMENT",
    "TEMPORAL_ALIGN_MULTIPLE",
    "DEFAULT_SP_SIZE",
    "TEXT_EMBED_DIM",
    "VAE_SCALING_FACTOR",
    "DIFFUSION_T",
    "DIFFUSION_STEPS",
    "DIFFUSION_CFG_SCALE",
    "CONDITION_NOISE_SCALE",
    "CONDITION_SR",
    "DEFAULT_RESOLUTION_H",
    "DEFAULT_RESOLUTION_W",
    "DEFAULT_SCALE_FACTOR",
    "MODEL_SPECS",
    # Functions
    "normalize_batch_size",
    "is_valid_batch_size",
    "pad_temporal_frames",
    "align_tile_dimension",
    "double_res_target_resolution",
    "double_res_tile_params",
    "latent_spatial_size",
    "recommend_precision",
    "resolution_clamp",
    "frame_count_from_duration",
    "model_size_from_dit_model",
]
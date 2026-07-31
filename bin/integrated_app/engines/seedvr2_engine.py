"""SeedVR2 - SeedVR2 视频/图像修复推理引擎核心实现

本模块实现基于 ByteDance SeedVR2 官方推理逻辑的完整修复引擎，
是 SeedVR2 项目的核心推理模块，继承自 RestoreEngine 抽象基类。

所属项目: SeedVR2 - SeedVR2 视频修复独立应用
核心技术栈: Python 3.10+, PyTorch, CUDA, safetensors, einops, OmegaConf

模块职责:
- 实现 SeedVR2 DiT (Diffusion Transformer) 模型的加载与推理
- 实现 VideoVAE v3 的编解码，支持 tiled VAE 处理高分辨率输入
- 实现 4 阶段流水线: VAE编码 → DiT采样 → VAE解码 → 后处理
- 支持分阶段模型加载/销毁策略，任何时刻内存中最多一个大模型
- 集成 BlockSwap 动态块交换技术，支持低显存 GPU 运行大模型
- 支持蒸馏模式(1步)和标准模式(50步)两种推理模式
- 提供内存监控、显存预检、OOM 自动回退、推理取消等健壮性机制
- 集成多种后处理增强: 颜色校正、小波重建、锐化、文本修复、EXIF复制

初始化流程:
1. 加载 JSON 模型配置和文本嵌入 (~1MB，常驻内存)
2. VAE 和 DiT 大模型采用延迟加载策略，推理时按阶段加载/销毁

推理流水线 (4 阶段):
1. VAE 编码: 像素空间 -> 潜空间 (VAE在GPU, DiT未加载)
2. DiT 采样: 低分辨率潜空间 -> 高分辨率潜空间 (DiT在GPU/BlockSwap, VAE在CPU)
3. VAE 解码: 潜空间 -> 像素空间 (VAE在GPU, DiT已销毁)
4. 后处理: 颜色校正、小波重建、锐化、EXIF复制 (无模型)

内存安全机制:
- 严格内存监控: RAM 使用率超过 90% 立即终止推理
- 加载前预检: 确认可用内存至少为模型大小的 1.5 倍
- 分阶段销毁: DiT/VAE 用完立即完全销毁，释放 VRAM+RAM
- BlockSwap: transformer 块动态在 GPU/CPU 间交换，降低峰值显存
- Tiled VAE: 支持分块编解码，自动 tile size 推荐和 OOM 回退
- 推理取消: 支持在阶段切换点取消任务，避免资源泄漏
"""
import asyncio
import gc
import json
import logging
import os
import random
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# 环境变量: 防止 diffusers/huggingface 尝试联网导致卡住
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import numpy as np
import torch
from einops import rearrange
from omegaconf import DictConfig
from torchvision.transforms import Compose, Lambda, Normalize

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    psutil = None
    _HAS_PSUTIL = False

# 可选导入 - 视频读取
try:
    from torchvision.io.video import read_video
    _HAS_TORCHVISION_IO = True
except (ImportError, ModuleNotFoundError):
    _HAS_TORCHVISION_IO = False

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import contextlib  # noqa: E402

from bin.integrated_app.color_fix import apply_color_correction  # noqa: E402
from bin.integrated_app.engine_interface import RestoreEngine, RestoreResult  # noqa: E402
from bin.integrated_app.exceptions import InferenceCancelledError  # noqa: E402
from bin.integrated_app.optimization.blockswap import apply_block_swap_to_dit, cleanup_blockswap  # noqa: E402
from bin.integrated_app.optimization.cache_manager import get_cache_manager  # noqa: E402
from bin.integrated_app.optimization.memory_manager import (  # noqa: E402
    clear_memory,
    clear_rope_lru_caches,
    release_model_memory,
)
from bin.integrated_app.optimization.tile_blend import (  # noqa: E402
    compute_temporal_segments,
)
from bin.integrated_app.video_processor import FFmpegWrapper, VideoProcessor  # noqa: E402

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 内存监控 (严格模式: 超 90% 立即终止模型)
# ---------------------------------------------------------------------------

_MEMORY_THRESHOLD = 0.90
"""内存使用率阈值 (90%)，超过此阈值立即终止模型加载/推理，防止系统卡死"""

DEFAULT_SCALING_FACTOR = 0.9152
"""VAE 潜空间默认缩放因子，来自模型配置默认值，用于归一化/反归一化潜变量"""

DEFAULT_VAE_SPATIAL_DOWNSAMPLE = 8
"""VAE 默认空间下采样因子，即像素空间到潜空间的空间分辨率缩放倍数"""

TILE_ALIGNMENT_FACTOR = 16
"""Tile 处理对齐因子，确保图像 H/W 维度是 16 的倍数，满足 VAE/DiT 下采样要求"""

TEMPORAL_ALIGN_MULTIPLE = 4
"""SeedVR2 时间维度对齐倍数: 视频帧数需满足 (T-1) 能被 4*sp_size 整除，
不足时用最后一帧填充"""

TEXT_EMBED_DIM = 5120
"""SeedVR2 文本嵌入维度，当文本嵌入文件缺失时使用零嵌入 fallback"""

DTYPE_CONVERSION_GC_INTERVAL = 50
"""dtype 转换循环中的 GC 间隔: 每转换 50 个参数执行一次垃圾回收，控制内存峰值"""

MAX_SEED = 2**32 - 1
"""最大随机种子值 (32 位无符号整数最大值)，用于生成合法的随机种子范围"""

def _check_memory(threshold: float = _MEMORY_THRESHOLD, force_cleanup: bool = True) -> float:
    """检查系统内存使用率，超过阈值立即清理并抛出异常

    严格模式: 内存超过 90% 立即终止模型加载/推理，防止系统卡死。

    Args:
        threshold: 内存使用率阈值 (0-1)，默认 90%
        force_cleanup: 是否在超阈值时强制清理所有模型

    Returns:
        当前内存使用率 (0-1)

    Raises:
        MemoryError: 内存使用率超过阈值
    """
    if not _HAS_PSUTIL:
        return 0.0
    mem = psutil.virtual_memory()
    usage = mem.percent / 100.0
    if usage > threshold:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        gc.collect()
        _force_release_memory()

        mem = psutil.virtual_memory()
        usage = mem.percent / 100.0
        if usage > threshold:
            raise MemoryError(
                f"内存使用率 {usage:.1%} 超过阈值 {threshold:.0%}，"
                f"可用: {mem.available/1024**3:.1f}GB / {mem.total/1024**3:.1f}GB。"
                f"必须立即终止模型！"
            )
    return usage


def _estimate_model_size_gb(checkpoint_path: str) -> float:
    """估算模型文件大小 (GB)"""
    try:
        size_bytes = os.path.getsize(checkpoint_path)
        return size_bytes / (1024 ** 3)
    except OSError:
        return 0.0


def _check_memory_before_load(checkpoint_path: str, label: str = "模型") -> None:
    """加载模型前检查是否有足够内存

    估算模型大小并检查当前可用内存是否足够。
    如果可用内存不足模型大小的 1.5 倍 (考虑 dtype 转换开销)，抛出异常。

    Args:
        checkpoint_path: 模型文件路径
        label: 模型标签 (用于日志)

    Raises:
        MemoryError: 可用内存不足
    """
    if not _HAS_PSUTIL:
        return
    model_size_gb = _estimate_model_size_gb(checkpoint_path)
    mem = psutil.virtual_memory()
    available_gb = mem.available / (1024 ** 3)
    usage = mem.percent / 100.0

    required_gb = model_size_gb * 1.5

    logger.info(f"[内存预检] {label}: 文件={model_size_gb:.2f}GB, "
                 f"需要>={required_gb:.1f}GB, 可用={available_gb:.1f}GB, "
                 f"当前使用率={usage:.1%}")

    if usage > _MEMORY_THRESHOLD:
        raise MemoryError(
            f"内存使用率 {usage:.1%} 已超过阈值 {_MEMORY_THRESHOLD:.0%}，"
            f"无法加载 {label} ({model_size_gb:.2f}GB)。"
            f"可用: {available_gb:.1f}GB"
        )

    if available_gb < required_gb:
        raise MemoryError(
            f"可用内存 {available_gb:.1f}GB 不足以加载 {label} "
            f"(需要 {required_gb:.1f}GB, 文件 {model_size_gb:.2f}GB)。"
            f"当前使用率: {usage:.1%}"
        )


def _log_memory(tag: str = ""):
    """记录当前内存状态 (RAM + VRAM)"""
    try:
        if _HAS_PSUTIL:
            mem = psutil.virtual_memory()
            ram_info = f"RAM: {mem.percent:.0f}% ({mem.available/1024**3:.1f}GB可用/{mem.total/1024**3:.1f}GB)"
        else:
            ram_info = "RAM: N/A"
        vram_alloc = torch.cuda.memory_allocated(0) / 1024**3 if torch.cuda.is_available() else 0
        vram_resv = torch.cuda.memory_reserved(0) / 1024**3 if torch.cuda.is_available() else 0
        logger.info(f"[内存{tag}] {ram_info}, "
                     f"VRAM: {vram_alloc:.2f}GB使用/{vram_resv:.2f}GB保留")
    except Exception:
        pass


def _force_release_memory():
    """强制释放 Python/PyTorch 缓存的 CPU 内存

    Python 的内存分配器不会立即将释放的内存返回给操作系统，
    导致多次推理后 RAM 累积不释放。此函数尝试强制释放缓存内存。

    Windows: 调用 msvcrt._heapmin() 返回堆内存给 OS
    Linux: 调用 malloc_trim(0) 返回内存给 OS
    """
    for _ in range(3):
        gc.collect()

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()

    try:
        import ctypes
        import platform
        if platform.system() == 'Windows':
            ctypes.CDLL('msvcrt')._heapmin()
        else:
            ctypes.CDLL('libc.so.6').malloc_trim(0)
    except Exception:
        pass


def _cleanup_cuda_cache(deep: bool = True):
    """统一清理 CUDA 缓存和系统内存

    整合 clear_memory + CUDA 缓存清理 + cuBLAS workspace 清理的重复逻辑，
    防止显存碎片化导致后续推理 OOM。

    Args:
        deep: 是否执行深度内存清理（调用 clear_memory(deep=True)）
    """
    clear_memory(deep=deep, force=True)

    if hasattr(torch._C, '_cuda_clearCublasWorkspaces'):
        with contextlib.suppress(Exception):
            torch._C._cuda_clearCublasWorkspaces()

    _force_release_memory()


def _tensor_to_uint8_np(tensor: torch.Tensor) -> np.ndarray:
    """将 [-1, 1] 范围的张量转换为 [0, 255] uint8 numpy 数组

    统一视频和图像后处理中的张量转换逻辑。

    Args:
        tensor: 输入张量，值域 [-1, 1]，形状通常为 (..., C, H, W) 或 (C, H, W)

    Returns:
        np.ndarray: uint8 类型的 numpy 数组，值域 [0, 255]，通道在最后一维
    """
    return (
        tensor.float()
        .clamp(-1, 1)
        .mul(0.5)
        .add(0.5)
        .mul(255)
        .round()
        .to(torch.uint8)
        .cpu()
        .numpy()
    )


# ---------------------------------------------------------------------------
# 数据变换 (与官方 projects/inference_seedvr2_3b.py 一致)
# ---------------------------------------------------------------------------

class _NaResize:
    """自适应分辨率缩放变换（与官方 data.image.transforms.na_resize 对齐）

    支持两种缩放模式:
    - area: 按面积缩放，resolution 参数为目标像素面积的平方根（等比缩放）
    - 其他模式: 按长边缩放，resolution 参数为目标长边像素数

    可选仅下采样模式（downsample_only=True），当输入分辨率小于目标时不放大。
    使用双三次插值（bicubic）保证缩放质量。

    输入张量形状: T C H W（时间、通道、高度、宽度）
    输出张量形状: T C H' W'（缩放后尺寸）
    """
    def __init__(self, resolution: float, mode: str = "area", downsample_only: bool = False):
        """初始化缩放变换

        Args:
            resolution: 目标分辨率参数，语义由 mode 决定
            mode: 缩放模式，"area" 为面积缩放，其他为长边缩放
            downsample_only: 是否仅允许下采样，True 时输入小于目标不放大
        """
        self.resolution = resolution
        self.mode = mode
        self.downsample_only = downsample_only

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        """执行缩放变换

        Args:
            x: 输入张量，形状为 T C H W，值域应为 [0, 1]

        Returns:
            torch.Tensor: 缩放后的张量，形状 T C new_H new_W
        """
        t, c, h, w = x.shape
        if self.mode == "area":
            current_area = h * w
            target_area = self.resolution ** 2
            if self.downsample_only and current_area <= target_area:
                scale = 1.0
            else:
                scale = (target_area / current_area) ** 0.5
        else:
            scale = self.resolution / max(h, w)
            if self.downsample_only and scale >= 1.0:
                scale = 1.0

        if scale == 1.0:
            return x
        new_h, new_w = int(h * scale), int(w * scale)
        x = x.float()
        x = torch.nn.functional.interpolate(
            x.reshape(1, t * c, h, w), size=(new_h, new_w), mode="bicubic", align_corners=False
        )
        return x.reshape(t, c, new_h, new_w)


class _DivisibleCrop:
    """整除裁剪变换，确保空间维度能被指定因子整除

    VAE 和 DiT 包含多次步长为 2 的下采样，要求输入 H/W 必须是 2^n 的倍数。
    此变换从右/下边缘裁剪多余像素，使 H/W 满足整除要求。

    输入张量形状: ... H W（任意前导维度）
    输出张量形状: ... H' W'，其中 H' % factor_h == 0, W' % factor_w == 0
    """
    def __init__(self, factor):
        """初始化整除裁剪

        Args:
            factor: 整除因子，可以是单个整数（同时应用于 H 和 W）
                   或 (h_factor, w_factor) 元组分别指定高度和宽度的因子
        """
        if not isinstance(factor, tuple):
            factor = (factor, factor)
        self.h_factor, self.w_factor = factor

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        """执行整除裁剪

        Args:
            x: 输入张量，最后两维为 H 和 W

        Returns:
            torch.Tensor: 裁剪后的张量，H/W 维度已对齐
        """
        h, w = x.shape[-2], x.shape[-1]
        new_h = h - (h % self.h_factor)
        new_w = w - (w % self.w_factor)
        if new_h != h or new_w != w:
            x = x[:, :, :new_h, :new_w]
        return x


class _RearrangeTCHW2CTHW:
    """张量维度重排变换: T C H W -> C T H W

    SeedVR2 模型内部使用 C T H W 顺序（通道在前），
    而预处理流水线输出 T C H W 顺序（时间在前），
    此变换完成维度顺序转换。
    """
    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        """执行维度重排

        Args:
            x: 输入张量，形状 T C H W

        Returns:
            torch.Tensor: 重排后的张量，形状 C T H W
        """
        return rearrange(x, "t c h w -> c t h w")


# ---------------------------------------------------------------------------
# FP8 反量化
# ---------------------------------------------------------------------------

def dequantize_fp8_to_fp16(state_dict: dict) -> dict:
    """将 FP8 E4M3FN 格式的权重量化为 FP16 格式

    FP8 (E4M3FN) 是一种 8 位浮点数格式，用于减小模型文件大小和显存占用。
    推理时需要将其转换为 FP16/BF16 才能进行计算。此函数遍历 state_dict，
    将所有 FP8 张量转换为 FP16，其他张量保持不变。

    Args:
        state_dict: 模型状态字典，键为参数名，值为 torch.Tensor

    Returns:
        dict: 转换后的状态字典，FP8 张量已转为 FP16

    Note:
        这是原地转换的替代方案，返回新字典避免修改输入。
        为控制内存峰值，应配合逐个参数转换和定期 GC 使用。
    """
    new_state_dict = {}
    for key, value in state_dict.items():
        if isinstance(value, torch.Tensor) and value.dtype == torch.float8_e4m3fn:
            new_state_dict[key] = value.to(torch.float16)
        else:
            new_state_dict[key] = value
    return new_state_dict


# ---------------------------------------------------------------------------
# 图像推理配置数据类
# ---------------------------------------------------------------------------

@dataclass
class ImageInferenceConfig:
    """图像推理配置数据类，封装 DiT/VAE/推理/后处理的所有参数

    集中管理单次图像推理的完整配置，避免通过修改全局 config 字典传递参数，
    保证请求级配置隔离和线程安全。使用 from_config_dict() 从全局配置构建，
    支持通过 kwargs 覆盖特定字段。

    Attributes:
        dit_model: DiT 模型标识，格式如 "3b_fp16"
        dit_device: DiT 推理设备，如 "cuda:0"
        blocks_to_swap: BlockSwap 交换的 transformer 块数量，0 表示禁用
        swap_io_components: 是否交换 I/O 组件（输入/输出投影层）到 CPU
        dit_offload_device: DiT 卸载目标设备，通常为 "cpu"
        dit_cache_model: 是否缓存 DiT 模型（当前实现为推理后销毁，此参数保留）
        attention_mode: 注意力实现模式，"sdpa"（PyTorch SDPA）或 "xformers"
        vae_model: VAE 模型标识
        vae_device: VAE 推理设备
        encode_tiled: 是否启用分块 VAE 编码（高分辨率必需）
        encode_tile_size: 编码块大小（像素空间）
        encode_tile_overlap: 编码块重叠像素数
        decode_tiled: 是否启用分块 VAE 解码
        decode_tile_size: 解码块大小（像素空间）
        decode_tile_overlap: 解码块重叠像素数
        tile_debug: 是否启用 tile 调试模式（输出可视化）
        vae_offload_device: VAE 卸载目标设备
        vae_cache_model: 是否缓存 VAE 模型
        seed: 随机种子，-1 表示随机生成
        resolution: 目标分辨率（长边像素）
        max_resolution: 最大分辨率上限，0 表示不限制
        batch_size: 批处理大小（当前实现为 1）
        uniform_batch_size: 是否使用统一批大小
        color_correction: 颜色校正方法，"lab"/"wavelet"/"adain"/"none"
        temporal_overlap: 时间维度重叠帧数（视频用）
        prepend_frames: 前导帧数
        input_noise_scale: 输入噪声缩放因子
        latent_noise_scale: 潜空间噪声缩放因子（蒸馏模式用）
        offload_device: 通用卸载设备
        enable_debug: 是否启用调试输出
    """
    dit_model: str = "3b_fp16"
    dit_device: str = "cuda:0"
    blocks_to_swap: int = 32
    swap_io_components: bool = True
    dit_offload_device: str = "cpu"
    dit_cache_model: bool = True
    attention_mode: str = "sdpa"
    vae_model: str = "ema_vae_fp16"
    vae_device: str = "cuda:0"
    encode_tiled: bool = True
    encode_tile_size: int = 1024
    encode_tile_overlap: int = 512
    decode_tiled: bool = True
    decode_tile_size: int = 1024
    decode_tile_overlap: int = 512
    tile_debug: str = "false"
    vae_offload_device: str = "cpu"
    vae_cache_model: bool = True
    seed: int = -1
    resolution: int = 2160
    max_resolution: int = 0
    batch_size: int = 1
    uniform_batch_size: bool = False
    color_correction: str = "lab"
    temporal_overlap: int = 0
    prepend_frames: int = 0
    input_noise_scale: float = 0.0
    latent_noise_scale: float = 0.0
    offload_device: str = "cpu"
    enable_debug: bool = False

    @classmethod
    def from_config_dict(cls, config: dict, **overrides) -> "ImageInferenceConfig":
        """从全局配置字典构建 ImageInferenceConfig 实例

        从 config.yaml 的 model、model.vae、inference 段读取默认值，
        并使用 overrides 参数覆盖特定字段。用于在推理入口快速构建配置。

        Args:
            config: 全局应用配置字典（通常为 app.state.config）
            **overrides: 要覆盖的字段键值对，优先级高于配置文件默认值

        Returns:
            ImageInferenceConfig: 构建好的配置实例
        """
        model_cfg = config.get("model", {})
        vae_cfg = model_cfg.get("vae", {})
        infer_cfg = config.get("inference", {})

        defaults = {
            "dit_model": f"{model_cfg.get('default_size', '3b')}_fp16",
            "blocks_to_swap": model_cfg.get("blocks_to_swap", 32),
            "swap_io_components": model_cfg.get("swap_io_components", True),
            "dit_offload_device": model_cfg.get("offload_device", "cpu"),
            "dit_cache_model": model_cfg.get("cache_model", True),
            "attention_mode": model_cfg.get("attention_mode", "sdpa"),
            "encode_tiled": vae_cfg.get("encode_tiled", True),
            "encode_tile_size": vae_cfg.get("encode_tile_size", 1024),
            "encode_tile_overlap": vae_cfg.get("encode_tile_overlap", 512),
            "decode_tiled": vae_cfg.get("decode_tiled", True),
            "decode_tile_size": vae_cfg.get("decode_tile_size", 1024),
            "decode_tile_overlap": vae_cfg.get("decode_tile_overlap", 512),
            "tile_debug": vae_cfg.get("tile_debug", "false"),
            "vae_offload_device": vae_cfg.get("offload_device", "cpu"),
            "vae_cache_model": vae_cfg.get("cache_model", True),
            "seed": infer_cfg.get("seed", -1),
            "resolution": infer_cfg.get("resolution", 2160),
            "max_resolution": infer_cfg.get("max_resolution", 0),
            "batch_size": infer_cfg.get("batch_size", 1),
            "uniform_batch_size": infer_cfg.get("uniform_batch_size", False),
            "color_correction": infer_cfg.get("color_correction", "lab"),
            "temporal_overlap": infer_cfg.get("temporal_overlap", 0),
            "prepend_frames": infer_cfg.get("prepend_frames", 0),
            "input_noise_scale": infer_cfg.get("input_noise_scale", 0.0),
            "latent_noise_scale": infer_cfg.get("latent_noise_scale", 0.0),
            "offload_device": infer_cfg.get("offload_device", "cpu"),
            "enable_debug": infer_cfg.get("enable_debug", False),
        }
        defaults.update(overrides)
        return cls(**defaults)


# ---------------------------------------------------------------------------
# SeedVR2 推理引擎
# ---------------------------------------------------------------------------

class SeedVR2Engine(RestoreEngine):
    """SeedVR2 视频/图像修复推理引擎 - 完整 4 阶段推理流水线实现

    继承自 RestoreEngine 抽象基类，实现 SeedVR2 模型的完整推理功能。
    采用延迟加载策略：启动时仅加载配置和文本嵌入(~1MB)，VAE/DiT 大模型
    在推理时按阶段加载，用完立即销毁，严格控制内存峰值。

    核心特性:
    - 4 阶段流水线: VAE编码 → DiT采样 → VAE解码 → 后处理
    - 分阶段模型加载/销毁: 任何时刻内存中最多一个大模型
    - BlockSwap 动态块交换: 在 GPU/CPU 间动态交换 transformer 块，降低显存需求
    - Tiled VAE: 支持分块编解码处理高分辨率输入，自动 tile size 和 OOM 回退
    - 蒸馏/标准双模式: 蒸馏模式(1步, cfg=1.0)快速推理，标准模式(50步, cfg=7.5)高质量
    - 内存安全: 90% 阈值监控、加载前预检、推理取消机制
    - 后处理增强: LAB颜色校正、小波重建、锐化、文本修复、EXIF复制

    推理模式:
    - 蒸馏模式 (distilled): cfg_scale=1.0, steps=1, 配合噪声增强实现快速推理
    - 标准模式 (standard): cfg_scale=7.5, steps=50, Euler采样 + Classifier-Free Guidance

    Args:
        config (dict): 应用配置字典，包含 model、inference、postprocessing 等段
    """

    def __init__(self, config: dict):
        """初始化 SeedVR2 引擎实例

        初始化模型组件引用、状态变量、取消令牌和外部工具。
        注意: __init__ 不加载大模型权重，仅初始化状态和工具，
        实际模型加载通过 load_model() 完成（延迟加载策略）。

        Args:
            config: 完整应用配置字典，从 config.yaml 加载
        """
        self.config = config
        self.dit = None
        self.vae = None
        self.pos_emb = None
        self.neg_emb = None
        self.schedule = None
        self.sampling_timesteps = None
        self.sampler = None
        self.model_size = None
        self.precision = "fp16"
        self.device = "cpu"
        self._loaded = False
        self._progress_callback = None
        self._model_config = None
        self._blockswap_active = False
        self._dit_checkpoint_path = None
        self._dit_model_size = None
        self._dit_precision = None
        self._cancel_event = threading.Event()
        self._thread_lock = threading.Lock()
        self._ffmpeg = FFmpegWrapper()
        self._video_processor = VideoProcessor(self._ffmpeg)

    def set_progress_callback(self, callback: Callable):
        """设置进度回调函数

        用于推理过程中向外部报告进度（当前未在核心推理中调用，保留接口）。

        Args:
            callback: 回调函数，接收进度参数
        """
        self._progress_callback = callback

    # REFACTOR [E4-1]: 推理取消机制
    # task_queue 超时或用户主动取消时调用 request_cancel()，
    # 推理线程在阶段切换点通过 _check_cancelled() 主动检查并抛出 InferenceCancelledError

    def request_cancel(self) -> None:
        """请求取消当前推理任务

        由 TaskQueue 在超时或用户取消时调用（可能来自外部线程）。
        线程安全地设置 _cancel_event，推理线程在下一个阶段切换点检测到后退出。
        """
        with self._thread_lock:
            self._cancel_event.set()
        logger.info("推理取消信号已发送")

    def _check_cancelled(self, stage: str = "") -> None:
        """检查取消信号，若已取消则抛出 InferenceCancelledError

        在推理阶段切换点调用（阶段1/2/3/4 开始前），确保：
        - 不会在阶段中间退出导致 GPU 资源泄漏
        - 取消响应延迟 <= 一个阶段的执行时间（通常 < 30s）

        Args:
            stage: 当前阶段名称（用于日志）
        """
        with self._thread_lock:
            is_cancelled = self._cancel_event.is_set()
        if is_cancelled:
            logger.info(f"推理在阶段 '{stage}' 被取消")
            raise InferenceCancelledError(
                f"推理在阶段 '{stage}' 被取消",
                detail={"stage": stage},
            )

    def _reset_cancel_token(self) -> None:
        """重置取消令牌（在每次推理开始前调用）"""
        with self._thread_lock:
            self._cancel_event.clear()

    def _cleanup_after_error(self) -> None:
        """错误/取消后统一清理模型资源和 CUDA 缓存

        统一异常处理路径中的资源清理逻辑，确保 DiT/VAE 被销毁、CUDA 缓存被清空。
        """
        try:
            if self.dit is not None:
                self._destroy_dit()
        except Exception as e:
            logger.debug(f"清理 DiT 时出错: {e}")
        try:
            if self.vae is not None:
                self._destroy_vae()
        except Exception as e:
            logger.debug(f"清理 VAE 时出错: {e}")
        _cleanup_cuda_cache(deep=True)

    # ------------------------------------------------------------------
    # 模型加载
    # ------------------------------------------------------------------

    async def load_model(self, model_size: str = "3b", device: str = "auto",
                         precision: str = None) -> bool:
        """加载 SeedVR2 模型配置 (不加载大模型，推理时按阶段加载/销毁)
        注意: 仅支持 NVIDIA CUDA GPU，不支持 CPU 推理。

        严格按 ComfyUI 工作流策略:
        - 启动时只加载配置文件和文本嵌入 (~1MB)
        - VAE 和 DiT 在推理时按阶段加载，用完立即销毁
        - 任何时刻 RAM 中最多只有一个大模型
        """
        try:
            if precision is None:
                precision = self.config.get("model", {}).get("default_precision", "fp16")

            if self._loaded and self.model_size == model_size and self.precision == precision:
                logger.info(f"模型 {model_size}/{precision} 已加载，跳过")
                return True

            if self._loaded:
                await self.unload_model()

            self.device = self._resolve_device(device)
            logger.info(f"初始化 SeedVR2-{model_size.upper()}/{precision}，设备: {self.device}")

            # 获取模型配置
            model_cfg = self.config.get("model", {}).get("models", {}).get(model_size)
            if not model_cfg:
                raise ValueError(f"未找到模型配置: {model_size}")

            pretrained_dir = self.config.get("model", {}).get("pretrained_dir", ".")
            config_dir = model_cfg["config_dir"]

            # 加载 JSON 模型配置
            config_path = PROJECT_ROOT / config_dir / "config.json"
            if not config_path.exists():
                raise FileNotFoundError(f"模型配置文件未找到: {config_path}")
            with open(config_path) as f:
                self._model_config = json.load(f)

            # 记录 DiT 路径 (延迟加载)
            checkpoint_key = f"checkpoint_{precision}"
            checkpoint_name = model_cfg.get(checkpoint_key) or model_cfg.get("checkpoint_fp16")
            checkpoint_path = PROJECT_ROOT / pretrained_dir / checkpoint_name
            if not checkpoint_path.exists():
                raise FileNotFoundError(f"DiT 模型文件未找到: {checkpoint_path}")
            self._dit_checkpoint_path = str(checkpoint_path)
            self._dit_model_size = model_size
            self._dit_precision = precision
            self.dit = None

            # 记录 VAE 路径 (延迟加载)
            vae_checkpoint_name = model_cfg["vae_checkpoint"]
            self._vae_checkpoint_path = str(PROJECT_ROOT / pretrained_dir / vae_checkpoint_name)
            if not os.path.exists(self._vae_checkpoint_path):
                raise FileNotFoundError(f"VAE 模型文件未找到: {self._vae_checkpoint_path}")
            self.vae = None

            # 加载文本嵌入 (~1MB，常驻内存)
            pos_emb_name = model_cfg.get("pos_emb", "pos_emb.pt")
            neg_emb_name = model_cfg.get("neg_emb", "neg_emb.pt")
            pos_path = PROJECT_ROOT / pretrained_dir / pos_emb_name
            neg_path = PROJECT_ROOT / pretrained_dir / neg_emb_name

            if pos_path.exists() and neg_path.exists():
                logger.info(f"加载文本嵌入: {pos_path}, {neg_path}")
                self.pos_emb = torch.load(str(pos_path), map_location="cpu", weights_only=True)
                self.neg_emb = torch.load(str(neg_path), map_location="cpu", weights_only=True)
            else:
                logger.warning("文本嵌入文件未找到，将使用零嵌入")
                self.pos_emb = None
                self.neg_emb = None

            # 配置扩散组件 (不需要模型实例)
            self._configure_diffusion(self._model_config, self.device)

            self.model_size = model_size
            self.precision = precision
            self._loaded = True
            logger.info(f"SeedVR2-{model_size.upper()}/{precision} 配置加载完成 (模型延迟加载)")
            return True

        except Exception as e:
            logger.error(f"模型配置加载失败: {e}")
            self._loaded = False
            raise

    def _destroy_module(self, model_attr: str, *, cleanup_blockswap: bool = False,
                        cleanup_rope: bool = False, label: str = "模型",
                        log_tag: str = "模型销毁后"):
        """完全销毁模型模块，释放全部 VRAM 和 RAM

        统一 DiT/VAE 的销毁逻辑，避免重复代码。
        关键: 必须同时释放 CPU 上的参数 (BlockSwap offload) 和 GPU 上的激活，
        否则 RAM 不会释放，多次推理后内存爆满。

        Args:
            model_attr: 模型属性名（'dit' 或 'vae'）
            cleanup_blockswap: 是否清理 BlockSwap 状态（仅 DiT 需要）
            cleanup_rope: 是否清理 RoPE LRU 缓存（仅 DiT 需要）
            label: 日志标签
            log_tag: _log_memory 调用时的标签
        """
        model = getattr(self, model_attr, None)
        if model is None:
            return

        if cleanup_blockswap and self._blockswap_active:
            cleanup_blockswap(model)
            self._blockswap_active = False

        if cleanup_rope:
            for _name, module in model.named_modules():
                if hasattr(module, 'get_axial_freqs') and hasattr(module.get_axial_freqs, 'cache_clear'):
                    with contextlib.suppress(Exception):
                        module.get_axial_freqs.cache_clear()

        for param in list(model.parameters()):
            if param.numel() > 0:
                param.data = torch.empty(0, dtype=param.dtype, device='cpu')
            param.grad = None
        for buffer in list(model.buffers()):
            if buffer.numel() > 0:
                buffer.data = torch.empty(0, dtype=buffer.dtype, device='cpu')

        model.zero_grad(set_to_none=True)

        setattr(self, model_attr, None)
        del model

        _force_release_memory()
        if hasattr(torch._C, '_cuda_clearCublasWorkspaces'):
            with contextlib.suppress(Exception):
                torch._C._cuda_clearCublasWorkspaces()
        _log_memory(log_tag)
        logger.info(f"{label} 已完全销毁，VRAM+RAM 已释放")

    def _destroy_dit(self):
        """完全销毁 DiT 模型，释放全部 VRAM 和 RAM"""
        if self.dit is None:
            return
        self._destroy_module(
            'dit',
            cleanup_blockswap=True,
            cleanup_rope=True,
            label="DiT 模型",
            log_tag="DiT销毁后"
        )

    def _destroy_vae(self):
        """完全销毁 VAE 模型，释放 RAM 和 VRAM"""
        if self.vae is None:
            return
        self._destroy_module('vae', label="VAE 模型", log_tag="VAE销毁后")

    async def unload_model(self) -> bool:
        """卸载模型释放显存"""
        try:
            if self.dit is not None:
                if self._blockswap_active:
                    cleanup_blockswap(self.dit)
                    self._blockswap_active = False
                clear_rope_lru_caches(self.dit)
                release_model_memory(self.dit)
                self.dit = None
            if self.vae is not None:
                release_model_memory(self.vae)
                self.vae = None
            self.pos_emb = None
            self.neg_emb = None
            self.schedule = None
            self.sampling_timesteps = None
            self.sampler = None

            self._loaded = False
            self.model_size = None
            self.precision = None

            _cleanup_cuda_cache(deep=True)

            logger.info("模型已卸载，显存已释放")
            return True
        except Exception as e:
            logger.error(f"模型卸载失败: {e}")
            return False

    # ------------------------------------------------------------------
    # 推理接口
    # ------------------------------------------------------------------

    def _get_inference_config(self, **kwargs) -> dict:
        """从 config.yaml 的 inference 部分读取推理参数，kwargs 可覆盖

        ComfyUI 工作流默认使用蒸馏模式 (1步, cfg=1.0):
        - 蒸馏模式: cfg_scale=1.0, steps=1, 噪声增强 base*0.1+randn*0.05
        - 标准模式: cfg_scale=7.5, steps=50
        """
        inf_cfg = self.config.get("inference", {})
        inference_mode = kwargs.get("inference_mode", inf_cfg.get("inference_mode", "distilled"))

        if inference_mode == "distilled":
            # ComfyUI 工作流默认: 1步蒸馏 + cfg=1.0
            default_cfg_scale = 1.0
            default_steps = 1
        else:  # standard (50步 Euler + CFG=7.5)
            default_cfg_scale = 7.5
            default_steps = 50

        return {
            "resolution": kwargs.get("resolution", inf_cfg.get("resolution", 2048)),
            "max_resolution": kwargs.get("max_resolution", inf_cfg.get("max_resolution", 0)),
            "batch_size": kwargs.get("batch_size", inf_cfg.get("batch_size", 1)),
            "uniform_batch_size": kwargs.get("uniform_batch_size", inf_cfg.get("uniform_batch_size", False)),
            "color_correction": kwargs.get("color_fix", inf_cfg.get("color_correction", "lab")),
            "temporal_overlap": kwargs.get("temporal_overlap", inf_cfg.get("temporal_overlap", 0)),
            "prepend_frames": kwargs.get("prepend_frames", inf_cfg.get("prepend_frames", 0)),
            "input_noise_scale": kwargs.get("input_noise_scale", inf_cfg.get("input_noise_scale", 0.0)),
            "latent_noise_scale": kwargs.get("latent_noise_scale", inf_cfg.get("latent_noise_scale", 0.0)),
            "seed": kwargs.get("seed", inf_cfg.get("seed", -1)),
            "attention_mode": kwargs.get("attention_mode",
                                         inf_cfg.get("attention_mode",
                                                     self.config.get("model", {}).get("attention_mode", "sdpa"))),
            "enable_debug": kwargs.get("enable_debug", inf_cfg.get("enable_debug", False)),
            "inference_mode": inference_mode,
            "cfg_scale": kwargs.get("cfg_scale", default_cfg_scale),
            "cfg_rescale": kwargs.get("cfg_rescale", inf_cfg.get("cfg_rescale", 0.0)),
            "sample_steps": kwargs.get("sample_steps", default_steps),
            # Restoration guidance scale (Vivid-VR inspired): controls fidelity-realism tradeoff
            "restoration_guidance_scale": kwargs.get(
                "restoration_guidance_scale",
                inf_cfg.get("restoration_guidance_scale", 1.0),
            ),
            # Temporal segment processing for long videos (RVRT/DiffVSR inspired)
            "temporal_segment_size": kwargs.get(
                "temporal_segment_size",
                inf_cfg.get("temporal_segment_size", 0),
            ),
            "temporal_segment_overlap": kwargs.get(
                "temporal_segment_overlap",
                inf_cfg.get("temporal_segment_overlap", 8),
            ),
            # BlockSwap configuration
            "blocks_to_swap": kwargs.get(
                "blocks_to_swap",
                self.config.get("model", {}).get("blocks_to_swap", 32),
            ),
            "swap_io_components": kwargs.get(
                "swap_io_components",
                self.config.get("model", {}).get("swap_io_components", True),
            ),
            "offload_device": kwargs.get(
                "offload_device",
                self.config.get("model", {}).get("offload_device", "cpu"),
            ),
        }

    async def infer_video(self, video_path: str, output_dir: str, **kwargs) -> RestoreResult:
        """视频修复推理 - 在线程中运行以避免阻塞事件循环

        阶段1 (VAE编码): VAE在GPU, DiT在CPU
        阶段2 (DiT推理): DiT在GPU(BlockSwap动态交换), VAE在CPU
        阶段3 (VAE解码): VAE在GPU, DiT已清理
        阶段4 (后处理): 无模型
        """
        # REFACTOR [E4-1]: 每次推理开始前重置取消令牌
        self._reset_cancel_token()
        # VRAM 预检 (DiffBIR inspired)
        try:
            from bin.integrated_app.optimization.vram_monitor import VRAMPeakMonitor
            self._vram_monitor = VRAMPeakMonitor(device=self.device, enabled=True)
        except Exception:
            self._vram_monitor = None
        return await asyncio.to_thread(self._infer_video_impl, video_path, output_dir, **kwargs)

    def _infer_video_impl(self, video_path: str, output_dir: str, **kwargs) -> RestoreResult:
        """视频修复推理同步实现 - 在线程中运行"""
        start_time = time.time()

        if not self._loaded:
            return RestoreResult(success=False, error="模型未加载")

        _check_memory()

        # 开始 VRAM 监控 (DiffBIR inspired)
        if self._vram_monitor is not None:
            self._vram_monitor.start_inference()

        tensor_cache = None
        try:
            tensor_cache = get_cache_manager()
            tensor_cache.clear()
        except Exception as e:
            logger.debug(f"TensorCacheManager init skipped: {e}")

        try:
            os.makedirs(output_dir, exist_ok=True)
            _check_memory()
            _log_memory("视频推理初始")

            # REFACTOR [E4-1]: 阶段0 检查取消信号
            self._check_cancelled("video:init")

            # 从配置读取推理参数
            inf = self._get_inference_config(**kwargs)

            # 分辨率处理: resolution 作为长边，max_resolution 作为上限
            res_h = kwargs.get("res_h", self.config.get("restore", {}).get("default_resolution_h", 1080))
            res_w = kwargs.get("res_w", self.config.get("restore", {}).get("default_resolution_w", 1920))
            if inf["max_resolution"] > 0:
                max_res = inf["max_resolution"]
                if max(res_h, res_w) > max_res:
                    scale = max_res / max(res_h, res_w)
                    res_h = int(res_h * scale)
                    res_w = int(res_w * scale)

            seed = inf["seed"]
            if seed == -1:
                seed = random.randint(0, MAX_SEED)
                logger.info(f"随机种子: {seed}")

            sp_size = kwargs.get("sp_size", self.config.get("restore", {}).get("sp_size", 1))
            cfg_scale = inf["cfg_scale"]
            cfg_rescale = inf["cfg_rescale"]
            sample_steps = inf["sample_steps"]
            color_fix_method = inf["color_correction"]
            input_noise_scale = inf["input_noise_scale"]
            latent_noise_scale = inf["latent_noise_scale"]

            logger.info(f"开始视频修复: {video_path} -> {res_w}x{res_h}, seed={seed}")

            # 获取视频信息
            video_info = self._ffmpeg.get_video_info(video_path)
            if not video_info:
                return RestoreResult(success=False, error="无法获取视频信息")

            total_frames = video_info.frame_count
            fps = video_info.fps
            out_fps = kwargs.get("out_fps", fps)
            logger.info(f"视频帧数: {total_frames}, 帧率: {fps}")

            # 长视频时间分段处理 (RVRT/DiffVSR inspired)
            temporal_segments = None
            segment_size = kwargs.get("segment_size", self.config.get("restore", {}).get("segment_size", 0))
            segment_overlap = kwargs.get("segment_overlap", self.config.get("restore", {}).get("segment_overlap", 0))
            if segment_size > 0 and total_frames > segment_size:
                try:
                    from bin.integrated_app.optimization.tile_blend import compute_temporal_segments
                    temporal_segments = compute_temporal_segments(
                        total_frames=total_frames,
                        segment_size=segment_size,
                        overlap=segment_overlap,
                    )
                    logger.info(f"长视频分段: {len(temporal_segments)} 段, 每段 {segment_size} 帧, 重叠 {segment_overlap} 帧")
                except Exception as e:
                    logger.debug(f"Temporal segments calculation skipped: {e}")

            # 读取视频
            # ROBUSTNESS [E4-2]: cv2.VideoCapture 必须在 finally 中 release，
            # 否则异常路径下文件句柄泄漏，导致后续 ffmpeg 操作失败
            cap = None
            try:
                if _HAS_TORCHVISION_IO:
                    video, _, info = read_video(video_path, output_format="TCHW")
                    video = video / 255.0
                    if out_fps is None:
                        out_fps = info.get("video_fps", fps)
                else:
                    # 使用 cv2 作为 fallback
                    import cv2
                    cap = cv2.VideoCapture(video_path)
                    frames = []
                    while True:
                        ret, frame = cap.read()
                        if not ret:
                            break
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        frame = torch.from_numpy(frame).permute(2, 0, 1).float() / 255.0
                        frames.append(frame)
                    video = torch.stack(frames)  # T C H W
            finally:
                # ROBUSTNESS [E4-2]: 确保视频句柄释放
                if cap is not None:
                    cap.release()

            # 构建变换
            video_transform = self._build_video_transform(res_h, res_w)

            # 编码
            cond_latent = video_transform(video.to(self.device))
            ori_length = cond_latent.shape[1]
            input_video = cond_latent.clone()

            # 视频帧数对齐
            cond_latent = self._cut_videos(cond_latent, sp_size)

            # ==================== 阶段1: VAE 编码 ====================
            # VAE 在 GPU, DiT 在 CPU 或未加载
            # REFACTOR [E4-1]: 阶段切换点检查取消信号
            self._check_cancelled("video:stage1-vae-encode")
            logger.info("阶段1: VAE 编码 (VAE=GPU)")
            # VRAM 监控: VAE 编码阶段
            vram_stage = self._vram_monitor.stage("vae_encode") if self._vram_monitor else None
            if vram_stage:
                vram_stage.__enter__()
            try:
                # 注意: BlockSwap 的 _protect_model_from_move 阻止了 dit.to("cpu")
                self.vae.to(device=self.device)
                logger.info(f"VAE 编码: {cond_latent.size()}")
                cond_latents = self._vae_encode([cond_latent])
            finally:
                if vram_stage:
                    vram_stage.__exit__(None, None, None)

            # 释放 VAE，为 DiT 腾出显存
            self.vae.to(device="cpu")
            self.vae.zero_grad(set_to_none=True)
            clear_memory(deep=False, force=True)

            # ==================== 阶段2: DiT 采样 ====================
            # DiT 在 GPU (BlockSwap 动态交换), VAE 在 CPU
            # REFACTOR [E4-1]: 阶段切换点检查取消信号
            self._check_cancelled("video:stage2-dit-sample")
            logger.info("阶段2: DiT 采样 (DiT=GPU/BlockSwap, VAE=CPU)")
            # VRAM 监控: DiT 采样阶段
            vram_stage = self._vram_monitor.stage("dit_sample") if self._vram_monitor else None
            if vram_stage:
                vram_stage.__enter__()
            try:
                if self.dit is None:
                    # DiT 已在之前的推理中被销毁或延迟加载，需要加载
                    logger.info("DiT 模型按需加载...")
                    # REFACTOR [B1-1] [P3-1]: 显式参数化 _load_dit_model，
                    # 不再修改 self.config 全局状态
                    model_cfg = self.config.get("model", {})
                    self.dit = self._load_dit_model(
                        model_size=self._dit_model_size,
                        model_config=self._model_config,
                        checkpoint_path=self._dit_checkpoint_path,
                        precision=self._dit_precision,
                        device=self.device,
                        blocks_to_swap=inf.get("blocks_to_swap", model_cfg.get("blocks_to_swap", 0)),
                        swap_io_components=inf.get("swap_io_components", model_cfg.get("swap_io_components", False)),
                        offload_device=inf.get("offload_device", model_cfg.get("offload_device", "cpu")),
                        attention_mode=inf.get("attention_mode", model_cfg.get("attention_mode", "sdpa")),
                    )

                # 文本嵌入
                text_embeds = self._get_text_embeds()

                # DiT 采样
                logger.info("DiT 采样...")
                # Tensor Cache: 缓存 cond_latents 以释放 VRAM
                if tensor_cache is not None:
                    tensor_cache.maybe_cache_tensor(cond_latents, "dit_cond_latents")
                    cond_latents = None  # 释放引用

                samples = self._generation_step(
                    cond_latents=cond_latents,
                    text_embeds=text_embeds,
                    cfg_scale=cfg_scale,
                    cfg_rescale=cfg_rescale,
                    sample_steps=sample_steps,
                    seed=seed,
                    input_noise_scale=input_noise_scale,
                    latent_noise_scale=latent_noise_scale,
                    restoration_guidance_scale=inf.get("restoration_guidance_scale", 0.0),
                )

                # Tensor Cache: 恢复 cond_latents（如果被缓存）
                if tensor_cache is not None and cond_latents is None:
                    restored = tensor_cache.restore_tensor("dit_cond_latents", self.device)
                    if restored is not None:
                        cond_latents = restored
            finally:
                if vram_stage:
                    vram_stage.__exit__(None, None, None)

            # 完全销毁 DiT 释放全部 VRAM（BlockSwap 阻止了 model.to("cpu") 的正常执行）
            self._destroy_dit()

            # ==================== 阶段3: VAE 解码 ====================
            # VAE 在 GPU, DiT 已销毁
            # REFACTOR [E4-1]: 阶段切换点检查取消信号
            self._check_cancelled("video:stage3-vae-decode")
            logger.info("阶段3: VAE 解码 (VAE=GPU, DiT已销毁)")
            # VRAM 监控: VAE 解码阶段
            vram_stage = self._vram_monitor.stage("vae_decode") if self._vram_monitor else None
            if vram_stage:
                vram_stage.__enter__()
            try:
                self.vae.to(device=self.device)
                decoded = self._vae_decode(samples)
            finally:
                if vram_stage:
                    vram_stage.__exit__(None, None, None)

            # 释放 VAE
            self.vae.to(device="cpu")
            clear_memory(deep=False, force=True)

            # ==================== 阶段4: 后处理 ====================
            # REFACTOR [E4-1]: 阶段切换点检查取消信号
            self._check_cancelled("video:stage4-postprocess")
            logger.info("阶段4: 后处理")
            # VRAM 监控: 后处理阶段
            vram_stage = self._vram_monitor.stage("postprocess") if self._vram_monitor else None
            if vram_stage:
                vram_stage.__enter__()
            try:
                sample = decoded[0]
                # C T H W -> T C H W
                if sample.ndim == 3:
                    sample = rearrange(sample[:, None], "c t h w -> t c h w")
                else:
                    sample = rearrange(sample, "c t h w -> t c h w")

                # 截断到原始长度
                if ori_length < sample.shape[0]:
                    sample = sample[:ori_length]

                # 颜色校正和后处理
                from bin.integrated_app.optimization.post_processing import (
                    wavelet_reconstruction, apply_sharpening,
                )
                postprocess_cfg = self.config.get("postprocessing", {})
                enable_wavelet = postprocess_cfg.get("wavelet_reconstruction", False)  # 视频默认关闭小波重建以节省时间
                sharpen_strength = postprocess_cfg.get("video_sharpen_strength", 0.0)

                input_frames = rearrange(input_video, "c t h w -> t c h w") if input_video.ndim == 4 else rearrange(input_video[:, None], "c t h w -> t c h w")
                input_frames_cpu = input_frames[:sample.shape[0]].cpu()

                sample_np = _tensor_to_uint8_np(sample)
                input_np = _tensor_to_uint8_np(input_frames_cpu)

                restored_frames = []
                # Feature propagation: temporal consistency enhancement (Upscale-A-Video inspired)
                # 在相邻帧间传播特征，提升时间一致性
                temporal_propagator = None
                temporal_propagation_enabled = self.config.get("inference", {}).get("temporal_propagation", True)
                if temporal_propagation_enabled:
                    try:
                        from bin.integrated_app.optimization.temporal_processing import FeaturePropagation
                        prop_weight = postprocess_cfg.get("temporal_propagation_weight", 0.2)
                        temporal_propagator = FeaturePropagation(propagation_weight=prop_weight)
                    except Exception as e:
                        logger.debug(f"FeaturePropagation init skipped: {e}")

                prev_frame = None
                for i in range(sample_np.shape[0]):
                    frame = sample_np[i].transpose(1, 2, 0)  # C H W -> H W C
                    ref = input_np[i].transpose(1, 2, 0)
                    if color_fix_method != "none":
                        frame = apply_color_correction(frame, ref, method=color_fix_method)

                    # 小波重建后处理 (视频可选，默认关闭以节省时间)
                    if enable_wavelet:
                        try:
                            level = postprocess_cfg.get("wavelet_level", 2)
                            low_freq_weight = postprocess_cfg.get("low_freq_weight", 0.8)
                            frame = wavelet_reconstruction(frame, ref, level=level, low_freq_weight=low_freq_weight)
                        except Exception as e:
                            logger.debug(f"Video wavelet_reconstruction skipped: {e}")

                    # 视频锐化
                    if sharpen_strength > 0:
                        try:
                            frame = apply_sharpening(frame, strength=sharpen_strength, method="unsharp_mask")
                        except Exception as e:
                            logger.debug(f"Video sharpening skipped: {e}")

                    # Apply temporal feature propagation
                    if temporal_propagator is not None:
                        frame = temporal_propagator.propagate(
                            current_frame=frame,
                            previous_frame=prev_frame,
                        )
                    prev_frame = frame
                    restored_frames.append(frame)

                # 保存
                import mediapy
                output_filename = os.path.basename(video_path)
                output_name = os.path.splitext(output_filename)[0] + "_restored.mp4"
                output_path = os.path.join(output_dir, output_name)

                # 长视频分段混合 (RVRT/DiffVSR inspired)
                if temporal_segments is not None and len(temporal_segments) > 1:
                    try:
                        from bin.integrated_app.optimization.tile_blend import blend_temporal_segments
                        # 将 restored_frames 转换为 tensor
                        frames_tensor = torch.from_numpy(np.array(restored_frames))  # T H W C
                        frames_tensor = frames_tensor.permute(0, 3, 1, 2)  # T C H W
                        blended = blend_temporal_segments(
                            segment_results=[frames_tensor],
                            segments=temporal_segments,
                            total_frames=total_frames,
                            overlap=segment_overlap,
                        )
                        # 混合后转换回 numpy
                        restored_frames = blended.permute(0, 2, 3, 1).numpy()  # T H W C
                        logger.info(f"长视频分段混合完成: {len(restored_frames)} 帧")
                    except Exception as e:
                        logger.debug(f"Temporal segments blending skipped: {e}")

                if len(restored_frames) == 1:
                    mediapy.write_image(output_path, restored_frames[0])
                else:
                    mediapy.write_video(output_path, np.array(restored_frames), fps=out_fps)

                # Tensor Cache: 清理缓存
                if tensor_cache is not None:
                    tensor_cache.clear()
                    cache_stats = tensor_cache.get_stats()
                    logger.info(f"Tensor Cache 统计: cached={cache_stats['total_cached']}, "
                                f"restored={cache_stats['total_restored']}, "
                                f"peak={cache_stats['peak_cache_mb']:.1f}MB")

                # VRAM 监控: 结束并输出报告
                if self._vram_monitor is not None:
                    self._vram_monitor.end_inference()
                    self._vram_monitor.log_report()
            finally:
                if vram_stage:
                    vram_stage.__exit__(None, None, None)

            _cleanup_cuda_cache(deep=True)

            processing_time = time.time() - start_time
            return RestoreResult(
                success=True,
                output_path=output_path,
                processing_time=processing_time,
                metadata={
                    "model_size": self.model_size,
                    "precision": self.precision,
                    "input_frames": total_frames,
                    "output_resolution": f"{res_w}x{res_h}",
                    "fps": out_fps,
                    "blockswap_active": self._blockswap_active,
                    "processing_fps": total_frames / processing_time if processing_time > 0 else 0,
                    "avg_frame_time_ms": (processing_time / total_frames * 1000) if total_frames > 0 else 0,
                    "cfg_scale": cfg_scale,
                    "sample_steps": sample_steps,
                    "inference_mode": inf["inference_mode"],
                }
            )

        except InferenceCancelledError as e:
            logger.warning(f"视频推理被取消: {e}")
            self._cleanup_after_error()
            return RestoreResult(
                success=False,
                error="推理已被取消",
                processing_time=time.time() - start_time,
                metadata={"cancelled": True, "stage": e.detail.get("stage", "")},
            )
        except Exception as e:
            logger.error(f"视频修复失败: {e}", exc_info=True)
            self._cleanup_after_error()
            return RestoreResult(success=False, error=str(e), processing_time=time.time() - start_time)

    async def infer_image(
        self,
        image_path: str,
        output_dir: str,
        config: ImageInferenceConfig | None = None,
        **kwargs,
    ) -> RestoreResult:
        """图像修复推理 - 在线程中运行以避免阻塞事件循环

        阶段1: 加载VAE → 编码 → 销毁VAE
        阶段2: 加载DiT → 采样 → 销毁DiT
        阶段3: 加载VAE → 解码 → 销毁VAE
        阶段4: 后处理 (无模型)

        任何时刻 RAM 中最多只有一个大模型，内存超过 90% 立即终止

        Args:
            image_path: 输入图像路径
            output_dir: 输出目录
            config: 图像推理配置 (为 None 时从 self.config 构建默认配置)
            **kwargs: 额外参数，会覆盖 config 中的同名字段 (兼容旧调用方)
        """
        if config is None:
            config = ImageInferenceConfig.from_config_dict(self.config, **kwargs)
        elif kwargs:
            # kwargs 覆盖 config 字段
            for k, v in kwargs.items():
                if hasattr(config, k):
                    object.__setattr__(config, k, v)

        # REFACTOR [E4-1]: 每次推理开始前重置取消令牌
        self._reset_cancel_token()
        return await asyncio.to_thread(self._infer_image_impl, image_path, output_dir, config)

    def _prepare_image_input(
        self, image_path: str, resolution: int
    ) -> tuple:
        """读取图像并预处理为模型输入

        Args:
            image_path: 输入图像路径
            resolution: 目标分辨率 (长边)

        Returns:
            (cond_latent, input_video, res_h, res_w, scale_factor)
        """
        from PIL import Image as PILImage
        orig_img = PILImage.open(image_path).convert('RGB')
        orig_w, orig_h = orig_img.size

        # 分辨率计算
        scale_factor = 2.0
        if resolution > 0:
            target_long = resolution
            current_long = max(orig_h, orig_w)
            if target_long > current_long:
                scale_factor = target_long / current_long
            else:
                scale_factor = 1.0

        res_h = int(orig_h * scale_factor)
        res_w = int(orig_w * scale_factor)
        res_h = res_h - (res_h % 2)
        res_w = res_w - (res_w % 2)

        # 预处理图像 (与 ComfyUI 工作流一致: [0,1] 传入 transform)
        img_np = np.array(orig_img).astype(np.float32) / 255.0  # [0, 1]
        image = torch.from_numpy(img_np).permute(2, 0, 1)  # C H W
        image = image.unsqueeze(0)  # T C H W (T=1)
        del orig_img, img_np
        gc.collect()

        # 变换: NaResize + DivisibleCrop
        video_transform = self._build_video_transform(res_h, res_w)
        cond_latent = video_transform(image)  # C T H W
        input_video = cond_latent.clone()
        del image
        gc.collect()

        return cond_latent, input_video, res_h, res_w, scale_factor

    def _postprocess_output(
        self,
        decoded: list,
        input_video: torch.Tensor,
        color_fix_method: str,
        res_h: int,
        res_w: int,
        image_path: str,
        output_dir: str,
        scale_factor: float,
        inf: dict,
        cfg_scale: float,
        sample_steps: int,
        blockswap_was_active: bool,
    ) -> RestoreResult:
        """后处理: 颜色校正、保存输出、创建 RestoreResult

        集成多种后处理增强:
        - 颜色校正 (LAB/Wavelet/AdaIN)
        - 小波重建锐化增强 (DiffBIR inspired)
        - Alpha 通道处理 (waifu2x inspired)
        - EXIF 元数据复制 (upscayl inspired)
        - 图像锐化增强 (Real-ESRGAN inspired)
        - 文本修复流水线 (Vivid-VR inspired, 可选)

        Args:
            decoded: VAE 解码结果
            input_video: 原始输入视频张量 (用于颜色校正参考)
            color_fix_method: 颜色校正方法
            res_h, res_w: 输出分辨率
            image_path: 输入图像路径
            output_dir: 输出目录
            scale_factor: 缩放因子
            inf: 推理配置字典 (含 inference_mode 等)
            cfg_scale: CFG 缩放
            sample_steps: 采样步数
            blockswap_was_active: BlockSwap 是否激活

        Returns:
            RestoreResult
        """
        from bin.integrated_app.optimization.post_processing import (
            wavelet_reconstruction, apply_sharpening, copy_exif_metadata,
            extract_alpha_from_image, merge_alpha_to_image,
            TextRestorationPipeline, TextRestorationConfig,
        )
        from PIL import Image as PILImage

        # 读取原始图像，处理 Alpha 通道
        original_alpha = None
        try:
            orig_img_pil = PILImage.open(image_path)
            orig_img_np = np.array(orig_img_pil)
            _, original_alpha = extract_alpha_from_image(orig_img_np)
            del orig_img_pil, orig_img_np
        except Exception as e:
            logger.debug(f"Alpha 通道提取失败: {e}")

        sample = decoded[0]  # [C, T, H, W] or [C, H, W]

        # 处理时间维度: C T H W -> C H W (单帧图像)
        if sample.ndim == 4:
            sample = rearrange(sample, "c t h w -> t c h w")  # T C H W
            sample = sample[0]  # C H W

        result_np = _tensor_to_uint8_np(sample)
        result_np = result_np.transpose(1, 2, 0)  # C H W -> H W C

        del sample, decoded
        gc.collect()

        ref_np = None
        if input_video is not None:
            ref = input_video
            if ref.ndim == 4:
                ref = rearrange(ref, "c t h w -> t c h w")[0]
            ref_np = _tensor_to_uint8_np(ref)
            ref_np = ref_np.transpose(1, 2, 0)

        # 颜色校正
        if color_fix_method != "none" and ref_np is not None:
            result_np = apply_color_correction(result_np, ref_np, method=color_fix_method)

        # 小波重建后处理 (DiffBIR inspired) - 提升锐度
        postprocess_cfg = self.config.get("postprocessing", {})
        enable_wavelet = postprocess_cfg.get("wavelet_reconstruction", True)
        if enable_wavelet and ref_np is not None:
            try:
                level = postprocess_cfg.get("wavelet_level", 3)
                low_freq_weight = postprocess_cfg.get("low_freq_weight", 0.8)
                result_np = wavelet_reconstruction(result_np, ref_np, level=level, low_freq_weight=low_freq_weight)
                logger.debug(f"小波重建应用: level={level}, low_freq_weight={low_freq_weight}")
            except Exception as e:
                logger.debug(f"wavelet_reconstruction skipped: {e}")

        # 锐化增强 (Real-ESRGAN inspired)
        sharpen_strength = postprocess_cfg.get("sharpen_strength", 0.0)
        if sharpen_strength > 0:
            try:
                result_np = apply_sharpening(result_np, strength=sharpen_strength, method="unsharp_mask")
                logger.debug(f"锐化增强应用: strength={sharpen_strength}")
            except Exception as e:
                logger.debug(f"sharpening skipped: {e}")

        # 文本修复流水线 (Vivid-VR inspired, 可选)
        enable_text_restoration = postprocess_cfg.get("text_restoration", False)
        if enable_text_restoration and ref_np is not None:
            try:
                text_config = TextRestorationConfig(
                    enabled=True,
                    ocr_languages=postprocess_cfg.get("ocr_languages", ["ch_sim", "en"]),
                    ocr_confidence_threshold=postprocess_cfg.get("ocr_confidence", 0.5),
                    text_enhance_method=postprocess_cfg.get("text_enhance_method", "sharpen"),
                )
                text_pipeline = TextRestorationPipeline(text_config)
                result_np = text_pipeline.process(result_np, ref_np)
                logger.info("文本修复流水线已应用")
            except Exception as e:
                logger.debug(f"text_restoration skipped: {e}")

        # 合并 Alpha 通道 (如果有)
        if original_alpha is not None:
            try:
                result_np = merge_alpha_to_image(result_np, original_alpha)
                logger.debug("Alpha 通道已合并")
            except Exception as e:
                logger.debug(f"Alpha 通道合并失败: {e}")

        del input_video, ref_np, original_alpha
        gc.collect()

        # 保存
        output_name = f"SeedVR2_{Path(image_path).stem}_000001.png"
        output_path = os.path.join(output_dir, output_name)
        PILImage.fromarray(result_np).save(output_path)

        # 复制 EXIF 元数据 (upscayl inspired)
        enable_exif_copy = postprocess_cfg.get("copy_exif", True)
        if enable_exif_copy:
            try:
                copy_exif_metadata(image_path, output_path)
            except Exception as e:
                logger.debug(f"EXIF 复制失败: {e}")

        # 计算输出统计
        if result_np.shape[-1] >= 3:
            mean_val = result_np[..., :3].mean()
            std_val = result_np[..., :3].std()
        else:
            mean_val = result_np.mean()
            std_val = result_np.std()
        logger.info(f"输出: {result_np.shape[1]}x{result_np.shape[0]}, Mean={mean_val:.1f}, Std={std_val:.1f}")
        logger.info(f"保存: {output_path}")

        del result_np
        _cleanup_cuda_cache(deep=True)

        return RestoreResult(
            success=True,
            output_path=output_path,
            processing_time=0.0,  # 由调用方填充
            metadata={
                "model_size": self.model_size,
                "precision": self.precision,
                "output_resolution": f"{res_w}x{res_h}",
                "scale_factor": scale_factor,
                "inference_mode": inf["inference_mode"],
                "cfg_scale": cfg_scale,
                "sample_steps": sample_steps,
                "blockswap_active": blockswap_was_active,
                "mean": float(mean_val),
                "std": float(std_val),
                "postprocessing": {
                    "wavelet": enable_wavelet,
                    "sharpen": sharpen_strength > 0,
                    "text_restoration": enable_text_restoration,
                },
            }
        )

    def _infer_image_impl(
        self,
        image_path: str,
        output_dir: str,
        cfg: ImageInferenceConfig,
    ) -> RestoreResult:
        """图像修复推理同步实现 - 在线程中运行

        REFACTOR [B1-1] [P3-1]: 删除 copy.deepcopy(self.config) 配置快照
        - 原实现通过修改 self.config 全局状态传递请求级参数给 _load_dit_model/_load_vae_model，
          违反单一职责原则（引擎级配置不应被单个请求污染），且 deepcopy 大字典有性能开销
        - 改为显式参数化 _load_dit_model / _load_vae_model，参数直接从 cfg 读取
        - 删除 finally 中的 self.config = _config_snapshot 恢复逻辑
        """
        start_time = time.time()

        if not self._loaded:
            return RestoreResult(success=False, error="模型未加载")

        try:
            os.makedirs(output_dir, exist_ok=True)
            _check_memory()
            _log_memory("推理初始")

            # REFACTOR [E4-1]: 阶段0 检查取消信号
            self._check_cancelled("image:init")

            # 从 ImageInferenceConfig 读取推理参数
            inf = self._get_inference_config(
                seed=cfg.seed,
                resolution=cfg.resolution,
                max_resolution=cfg.max_resolution,
                batch_size=cfg.batch_size,
                uniform_batch_size=cfg.uniform_batch_size,
                color_correction=cfg.color_correction,
                temporal_overlap=cfg.temporal_overlap,
                prepend_frames=cfg.prepend_frames,
                input_noise_scale=cfg.input_noise_scale,
                latent_noise_scale=cfg.latent_noise_scale,
                attention_mode=cfg.attention_mode,
                enable_debug=cfg.enable_debug,
            )

            seed = inf["seed"]
            if seed == -1:
                seed = random.randint(0, MAX_SEED)

            cfg_scale = inf["cfg_scale"]
            cfg_rescale = inf["cfg_rescale"]
            sample_steps = inf["sample_steps"]
            color_fix_method = inf["color_correction"]
            input_noise_scale = inf["input_noise_scale"]
            latent_noise_scale = inf["latent_noise_scale"]

            # 读取并预处理图像
            cond_latent, input_video, res_h, res_w, scale_factor = self._prepare_image_input(
                image_path, inf["resolution"]
            )
            logger.info(f"图像修复: {image_path}, -> {res_w}x{res_h}, "
                        f"seed={seed}, mode={inf['inference_mode']}, cfg={cfg_scale}, steps={sample_steps}")

            # REFACTOR [B1-1] [P3-1]: 构建请求级 VAE tiled 配置（从 cfg 读取）
            # 替代原 self.config["model"]["vae"][...] = ... 的配置污染
            vae_tiled_config = {
                "encode_tiled": cfg.encode_tiled,
                "encode_tile_size": cfg.encode_tile_size,
                "encode_tile_overlap": cfg.encode_tile_overlap,
                "decode_tiled": cfg.decode_tiled,
                "decode_tile_size": cfg.decode_tile_size,
                "decode_tile_overlap": cfg.decode_tile_overlap,
                "tile_debug": cfg.tile_debug,
                "offload_device": cfg.vae_offload_device,
                "cache_model": cfg.vae_cache_model,
            }

            logger.info(f"工作流参数: dit_model={cfg.dit_model}, dit_device={cfg.dit_device}, "
                        f"blocks_to_swap={cfg.blocks_to_swap}, swap_io_components={cfg.swap_io_components}, "
                        f"attention_mode={cfg.attention_mode}, "
                        f"vae_model={cfg.vae_model}, vae_device={cfg.vae_device}, "
                        f"encode_tiled={cfg.encode_tiled}, decode_tiled={cfg.decode_tiled}, "
                        f"encode_tile_size={cfg.encode_tile_size}, decode_tile_size={cfg.decode_tile_size}, "
                        f"tile_debug={cfg.tile_debug}, "
                        f"resolution={cfg.resolution}, seed={cfg.seed}, color_correction={cfg.color_correction}")

            # ==================== 阶段1: 加载VAE → 编码 → 销毁VAE ====================
            # REFACTOR [E4-1]: 阶段切换点检查取消信号
            self._check_cancelled("image:stage1-vae-encode")
            logger.info("=" * 60)
            logger.info("阶段1: VAE 编码")
            logger.info("=" * 60)
            _check_memory()
            _log_memory("阶段1开始")

            # REFACTOR [B1-1] [P3-1]: 显式参数化 _load_vae_model，
            # 不再修改 self.config 全局状态
            self.vae = self._load_vae_model(
                model_config=self._model_config,
                checkpoint_path=self._vae_checkpoint_path,
                device=self.device,
                vae_tiled_config=vae_tiled_config,
            )
            self.vae.to(device=self.device)
            _log_memory("VAE加载到GPU后")
            _check_memory()

            cond_latents = self._vae_encode([cond_latent])
            del cond_latent
            gc.collect()

            # 销毁 VAE 释放内存，为 DiT 腾出空间
            self._destroy_vae()
            _log_memory("VAE销毁后")
            _check_memory()

            # ==================== 阶段2: 加载DiT → 采样 → 销毁DiT ====================
            # REFACTOR [E4-1]: 阶段切换点检查取消信号
            self._check_cancelled("image:stage2-dit-sample")
            logger.info("=" * 60)
            logger.info("阶段2: DiT 采样")
            logger.info("=" * 60)
            _check_memory()
            _log_memory("阶段2开始")

            # REFACTOR [B1-1] [P3-1]: 显式参数化 _load_dit_model，
            # 不再修改 self.config 全局状态
            self.dit = self._load_dit_model(
                model_size=self._dit_model_size,
                model_config=self._model_config,
                checkpoint_path=self._dit_checkpoint_path,
                precision=self._dit_precision,
                device=self.device,
                blocks_to_swap=cfg.blocks_to_swap,
                swap_io_components=cfg.swap_io_components,
                offload_device=cfg.dit_offload_device,
                attention_mode=cfg.attention_mode,
            )
            _log_memory("DiT加载后")
            _check_memory()

            text_embeds = self._get_text_embeds()

            logger.info(f"开始 DiT 采样: cfg={cfg_scale}, steps={sample_steps}, blockswap={self._blockswap_active}")
            samples = self._generation_step(
                cond_latents=cond_latents,
                text_embeds=text_embeds,
                cfg_scale=cfg_scale,
                cfg_rescale=cfg_rescale,
                sample_steps=sample_steps,
                seed=seed,
                input_noise_scale=input_noise_scale,
                latent_noise_scale=latent_noise_scale,
                restoration_guidance_scale=inf.get("restoration_guidance_scale", 0.0),
            )

            # 释放中间变量
            del cond_latents, text_embeds
            gc.collect()

            # 保存 blockswap 状态 (销毁 DiT 后会清除标志)
            blockswap_was_active = self._blockswap_active

            # 销毁 DiT 释放全部 VRAM
            self._destroy_dit()
            _log_memory("DiT销毁后")
            _check_memory()

            # ==================== 阶段3: 加载VAE → 解码 → 销毁VAE ====================
            # REFACTOR [E4-1]: 阶段切换点检查取消信号
            self._check_cancelled("image:stage3-vae-decode")
            logger.info("=" * 60)
            logger.info("阶段3: VAE 解码")
            logger.info("=" * 60)
            _check_memory()
            _log_memory("阶段3开始")

            # REFACTOR [B1-1] [P3-1]: 显式参数化 _load_vae_model（复用 vae_tiled_config）
            self.vae = self._load_vae_model(
                model_config=self._model_config,
                checkpoint_path=self._vae_checkpoint_path,
                device=self.device,
                vae_tiled_config=vae_tiled_config,
            )
            self.vae.to(device=self.device)
            _log_memory("VAE重新加载到GPU后")
            _check_memory()

            decoded = self._vae_decode(samples)

            # 释放 samples
            del samples
            gc.collect()

            # 销毁 VAE
            self._destroy_vae()
            _log_memory("VAE最终销毁后")

            # ==================== 阶段4: 后处理 ====================
            # REFACTOR [E4-1]: 阶段切换点检查取消信号
            self._check_cancelled("image:stage4-postprocess")
            logger.info("=" * 60)
            logger.info("阶段4: 后处理")
            logger.info("=" * 60)
            result = self._postprocess_output(
                decoded=decoded,
                input_video=input_video,
                color_fix_method=color_fix_method,
                res_h=res_h,
                res_w=res_w,
                image_path=image_path,
                output_dir=output_dir,
                scale_factor=scale_factor,
                inf=inf,
                cfg_scale=cfg_scale,
                sample_steps=sample_steps,
                blockswap_was_active=blockswap_was_active,
            )
            result.processing_time = time.time() - start_time
            return result

        except InferenceCancelledError as e:
            logger.warning(f"图像推理被取消: {e}")
            self._cleanup_after_error()
            return RestoreResult(
                success=False,
                error="推理已被取消",
                processing_time=time.time() - start_time,
                metadata={"cancelled": True, "stage": e.detail.get("stage", "")},
            )

        except MemoryError as e:
            logger.error(f"内存不足，紧急终止推理: {e}")
            self._cleanup_after_error()
            return RestoreResult(success=False, error=str(e), processing_time=time.time() - start_time)

        except Exception as e:
            logger.error(f"图像修复失败: {e}", exc_info=True)
            self._cleanup_after_error()
            return RestoreResult(success=False, error=str(e), processing_time=time.time() - start_time)
        # REFACTOR [B1-1]: 删除 finally 中的 self.config = _config_snapshot
        # 显式参数化后不再修改 self.config，无需恢复

    async def infer_batch(self, input_dir: str, output_dir: str, **kwargs) -> list[RestoreResult]:
        """批量图像修复 - 从文件夹加载图片并逐张处理

        Args:
            input_dir: 输入图片文件夹路径
            output_dir: 输出目录
            **kwargs: 传递给 infer_image 的参数

        Returns:
            每张图片的修复结果列表
        """
        if not self._loaded:
            return [RestoreResult(success=False, error="模型未加载")]

        input_path = Path(input_dir)
        if not input_path.is_dir():
            return [RestoreResult(success=False, error=f"输入目录不存在: {input_dir}")]

        # 支持的图片格式
        image_extensions = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff", ".tif"}
        image_files = sorted([
            f for f in input_path.iterdir()
            if f.is_file() and f.suffix.lower() in image_extensions
        ])

        if not image_files:
            return [RestoreResult(success=False, error=f"目录中未找到图片: {input_dir}")]

        logger.info(f"批量处理: 找到 {len(image_files)} 张图片")
        os.makedirs(output_dir, exist_ok=True)

        results = []
        for i, image_file in enumerate(image_files):
            logger.info(f"处理 [{i+1}/{len(image_files)}]: {image_file.name}")
            try:
                result = await self.infer_image(
                    image_path=str(image_file),
                    output_dir=output_dir,
                    **kwargs,
                )
                results.append(result)
                if result.success:
                    logger.info(f"完成 [{i+1}/{len(image_files)}]: {image_file.name} -> {result.output_path}")
                else:
                    logger.warning(f"失败 [{i+1}/{len(image_files)}]: {image_file.name} - {result.error}")
            except Exception as e:
                logger.error(f"异常 [{i+1}/{len(image_files)}]: {image_file.name} - {e}")
                results.append(RestoreResult(success=False, error=str(e)))

        success_count = sum(1 for r in results if r.success)
        logger.info(f"批量处理完成: {success_count}/{len(results)} 成功")
        return results

    def is_loaded(self) -> bool:
        """检查模型配置是否已加载完成

        注意: 这表示配置和文本嵌入已加载（延迟加载策略的"已加载"状态），
        DiT 和 VAE 大模型是在推理时按需加载/销毁的。

        Returns:
            bool: 模型配置已加载返回 True，否则返回 False
        """
        return self._loaded

    def get_model_info(self) -> dict:
        """获取当前模型的状态信息

        Returns:
            dict: 模型信息字典，包含:
                - loaded: bool - 是否已加载
                - model_size: str - 模型大小标识
                - precision: str - 模型精度
                - device: str - 推理设备
                - model_name: str - 人类可读的模型名称
                - blockswap_active: bool - BlockSwap 是否激活
        """
        if not self._loaded:
            return {"loaded": False}
        return {
            "loaded": True,
            "model_size": self.model_size,
            "precision": self.precision,
            "device": self.device,
            "model_name": f"SeedVR2-{self.model_size.upper()}/{self.precision}",
            "blockswap_active": self._blockswap_active,
        }

    def estimate_vram_required(self, model_size: str, resolution: tuple, precision: str = "fp16") -> int:
        """估算指定配置下推理所需的显存大小

        根据模型大小的基础显存需求和输入分辨率的像素因子，
        估算推理过程中的峰值显存占用。

        Args:
            model_size: 模型大小标识，如 "3b", "7b"
            resolution: 输入分辨率元组 (height, width)，单位为像素
            precision: 模型精度，"fp16" 或 "fp8"

        Returns:
            int: 估算所需显存，单位为 MB

        Note:
            估算基于 1080p (1920x1080) 分辨率的基准显存按比例缩放，
            分辨率低于 1080p 时使用基础显存需求（不缩小）。
        """
        model_cfg = self.config.get("model", {}).get("models", {}).get(model_size, {})
        if precision == "fp8":
            base_vram = model_cfg.get("min_vram_fp8_gb", 8) * 1024
        else:
            base_vram = model_cfg.get("min_vram_fp16_gb", 16) * 1024
        h, w = resolution
        pixel_factor = (h * w) / (1080 * 1920)
        return int(base_vram * max(1.0, pixel_factor))

    # ------------------------------------------------------------------
    # 内部方法 - 模型构建
    # ------------------------------------------------------------------

    def _resolve_device(self, device: str) -> str:
        """解析推理设备字符串

        将 "auto" 自动解析为可用的 CUDA 设备，或直接返回指定设备。
        SeedVR2 仅支持 NVIDIA CUDA GPU 推理，不支持 CPU。

        Args:
            device: 设备字符串，"auto" 表示自动选择，"cuda" 表示使用 GPU

        Returns:
            str: 解析后的设备字符串，当前仅返回 "cuda"

        Raises:
            RuntimeError: device="auto" 但 CUDA 不可用时抛出，提示需要 NVIDIA GPU
        """
        if device == "auto":
            if torch.cuda.is_available():
                return "cuda"
            raise RuntimeError(
                "CUDA 不可用。SeedVR2 模型仅支持 NVIDIA GPU 推理，不支持 CPU。"
            )
        return device

    def _load_dit_model(
        self,
        model_size: str,
        model_config: dict,
        checkpoint_path: str,
        precision: str,
        device: str,
        *,
        blocks_to_swap: int | None = None,
        swap_io_components: bool | None = None,
        offload_device: str | None = None,
        attention_mode: str | None = None,
    ):
        """构建并加载 DiT 模型 - 严格对齐 ComfyUI 工作流参数

        REFACTOR [B1-1] [P3-1]: 显式参数化 BlockSwap 配置
        - 原实现从 self.config["model"] 读取 blocks_to_swap / swap_io_components / offload_device，
          要求调用方先修改 self.config 全局状态，导致配置污染
        - 改为通过显式参数接收，调用方直接传入请求级配置
        - 参数为 None 时回退到 self.config，保持向后兼容

        关键优化:
        - 使用 meta device 构建模型结构 (零内存占用)
        - 使用 assign=True 加载权重 (避免额外拷贝)
        - 逐个转换 dtype 避免内存翻倍
        - BlockSwap 参数通过显式参数传入 (从 inference 配置段读取，如 blocks_to_swap=32)
        - 每个关键步骤检查内存，超 90% 立即终止
        - 加载前预检: 估算模型大小，确认可用内存足够

        内存峰值估算 (3B fp16 -> bf16):
        - state_dict 加载: ~6GB (fp16)
        - dtype 逐个转换: ~6GB + 单个张量额外开销
        - meta 模型构建: 0
        - assign=True 加载: 0 (直接使用 state_dict 张量)
        - 总峰值: ~12GB (加载+转换期间)
        """
        from safetensors.torch import load_file

        # 预导入: 防止模块导入时卡住
        import common.distributed.advanced  # noqa: F401

        # 预先确定目标 dtype
        dit_config = model_config["dit"]
        dit_dtype = getattr(torch, dit_config.get("dtype", "bfloat16"))

        # ==================== 步骤1: 加载权重到 CPU ====================
        _check_memory_before_load(checkpoint_path, "DiT")
        _check_memory()
        _log_memory("DiT权重加载前")
        logger.info(f"加载 safetensors 权重: {checkpoint_path}")
        state_dict = load_file(checkpoint_path, device="cpu")
        _log_memory("DiT权重加载后(raw)")
        _check_memory()

        # FP8 反量化 (逐个转换，避免内存翻倍)
        if precision == "fp8":
            logger.info("FP8 权重反量化为 FP16...")
            for k in list(state_dict.keys()):
                v = state_dict[k]
                if isinstance(v, torch.Tensor) and v.dtype == torch.float8_e4m3fn:
                    state_dict[k] = v.to(torch.float16)
                    del v
            gc.collect()
            _check_memory()

        # 逐个转换为目标 dtype (避免同时存在两份权重的内存峰值)
        # 关键: 每转换一个张量就删除旧张量，并定期 GC
        converted_count = 0
        for k in list(state_dict.keys()):
            v = state_dict[k]
            if isinstance(v, torch.Tensor) and v.dtype != dit_dtype:
                state_dict[k] = v.to(dtype=dit_dtype)
                del v
                converted_count += 1
                # 每转换 50 个参数检查一次内存 + GC
                if converted_count % 50 == 0:
                    gc.collect()
                    _check_memory()
        if converted_count > 0:
            gc.collect()
            logger.info(f"已将 {converted_count} 个参数转换为 {dit_dtype}")

        _check_memory()
        _log_memory("DiT权重dtype转换后")

        # ==================== 步骤2: 构建 DiT 模型 (meta device) ====================
        num_layers = dit_config["num_layers"]

        # 展开短列表参数到 num_layers 长度
        window_method = dit_config.get("window_method")
        if isinstance(window_method, list) and len(window_method) < num_layers:
            repeats = num_layers // len(window_method)
            window_method = window_method * repeats
            remainder = num_layers - len(window_method)
            if remainder > 0:
                window_method = window_method + window_method[:remainder]
            logger.info(f"window_method 展开为 {len(window_method)} 个元素")

        with torch.device("meta"):
            if model_size == "3b":
                from models.dit_v2.nadit import NaDiT
                model = NaDiT(
                    vid_in_channels=dit_config["vid_in_channels"],
                    vid_out_channels=dit_config["vid_out_channels"],
                    vid_dim=dit_config["vid_dim"],
                    vid_out_norm=dit_config.get("vid_out_norm"),
                    txt_in_dim=dit_config["txt_in_dim"],
                    txt_in_norm=dit_config.get("txt_in_norm"),
                    txt_dim=dit_config["txt_dim"],
                    emb_dim=dit_config["emb_dim"],
                    heads=dit_config["heads"],
                    head_dim=dit_config["head_dim"],
                    expand_ratio=dit_config["expand_ratio"],
                    norm=dit_config["norm"],
                    norm_eps=dit_config["norm_eps"],
                    ada=dit_config["ada"],
                    qk_bias=dit_config["qk_bias"],
                    qk_norm=dit_config["qk_norm"],
                    patch_size=dit_config["patch_size"],
                    num_layers=num_layers,
                    block_type=dit_config["block_type"],
                    mm_layers=dit_config.get("mm_layers", num_layers),
                    mlp_type=dit_config.get("mlp_type", "swiglu"),
                    msa_type=dit_config.get("msa_type"),
                    rope_type=dit_config.get("rope_type", "mmrope3d"),
                    rope_dim=dit_config.get("rope_dim", 128),
                    window=dit_config.get("window"),
                    window_method=window_method,
                )
            elif model_size == "7b":
                from models.dit.nadit import NaDiT
                model = NaDiT(
                    vid_in_channels=dit_config["vid_in_channels"],
                    vid_out_channels=dit_config["vid_out_channels"],
                    vid_dim=dit_config["vid_dim"],
                    txt_in_dim=dit_config["txt_in_dim"],
                    txt_dim=dit_config["txt_dim"],
                    emb_dim=dit_config["emb_dim"],
                    heads=dit_config["heads"],
                    head_dim=dit_config["head_dim"],
                    expand_ratio=dit_config["expand_ratio"],
                    norm=dit_config["norm"],
                    norm_eps=dit_config["norm_eps"],
                    ada=dit_config["ada"],
                    qk_bias=dit_config["qk_bias"],
                    qk_rope=dit_config.get("qk_rope", True),
                    qk_norm=dit_config["qk_norm"],
                    patch_size=dit_config["patch_size"],
                    num_layers=num_layers,
                    block_type=dit_config["block_type"],
                    shared_qkv=dit_config.get("shared_qkv", False),
                    shared_mlp=dit_config.get("shared_mlp", False),
                    mlp_type=dit_config.get("mlp_type", "normal"),
                    window=dit_config.get("window"),
                    window_method=window_method,
                )
            else:
                raise ValueError(f"未知模型大小: {model_size}")

        model.set_gradient_checkpointing(dit_config.get("gradient_checkpoint", True))

        # 诊断: 确认模型有 blocks 属性
        has_blocks = hasattr(model, "blocks")
        num_blocks = len(model.blocks) if has_blocks else 0
        logger.info(f"DiT 模型结构诊断: has_blocks={has_blocks}, num_blocks={num_blocks}")

        # ==================== 步骤3: 加载权重 (assign=True) ====================
        # assign=True 让模型直接使用 state_dict 中的张量，避免拷贝
        loading_info = model.load_state_dict(state_dict, strict=False, assign=True)
        # 立即删除 state_dict (模型已通过 assign=True 接管张量)
        del state_dict
        gc.collect()
        logger.info(f"DiT 加载信息: missing={len(loading_info.missing_keys)}, unexpected={len(loading_info.unexpected_keys)}")

        # 手动初始化 meta buffers
        for _name, module in model.named_modules():
            for buffer_name, buffer in list(module.named_buffers(recurse=False)):
                if buffer.is_meta:
                    setattr(module, buffer_name, torch.zeros_like(buffer, device="cpu"))

        model.eval()

        _check_memory()
        _log_memory("DiT权重assign后")

        # VRAM optimization toolchain (CogVideo/FlashVSR inspired)
        try:
            from bin.integrated_app.optimization.vram_toolchain import FP8Quantizer, XFormersIntegration
            # FP8 quantization
            fp8_enabled = self.config.get("inference", {}).get("fp8_enabled", False)
            if fp8_enabled:
                quantizer = FP8Quantizer()
                model = quantizer.quantize(model)
                logger.info("FP8 quantization applied")
            # xformers memory-efficient attention
            xformers_ok = XFormersIntegration.try_enable(model)
            if xformers_ok:
                logger.info("xformers memory-efficient attention enabled")
        except Exception as e:
            logger.debug(f"VRAM toolchain skipped: {e}")

        # ==================== 步骤4: 应用 BlockSwap (严格对齐 ComfyUI 工作流) ====================
        # REFACTOR [B1-1]: 显式参数优先，None 时回退到 self.config
        # 原实现总是从 self.config["model"] 读取 blocks_to_swap/swap_io_components/offload_device，
        # 要求调用方先修改 self.config 全局状态（_infer_image_impl 中曾通过 copy.deepcopy + 配置写入实现），
        # 这导致全局配置污染与并发安全问题
        # 改为显式参数优先：调用方直接传入请求级配置；None 时回退到 self.config 保持向后兼容
        model_cfg = self.config.get("model", {})
        if blocks_to_swap is None:
            blocks_to_swap = model_cfg.get("blocks_to_swap", dit_config.get("blocks_to_swap", 0))
        if swap_io_components is None:
            swap_io_components = model_cfg.get("swap_io_components", dit_config.get("swap_io_components", False))
        if offload_device is None:
            offload_device = model_cfg.get("offload_device", dit_config.get("offload_device", "cpu"))

        logger.info(f"BlockSwap 配置: blocks_to_swap={blocks_to_swap}, "
                     f"swap_io_components={swap_io_components}, offload_device={offload_device}, "
                     f"model_blocks={num_blocks}")

        if blocks_to_swap > 0 or swap_io_components:
            logger.info(f"应用 BlockSwap: blocks_to_swap={blocks_to_swap}, "
                        f"swap_io_components={swap_io_components}, offload_device={offload_device}")
            apply_block_swap_to_dit(
                model=model,
                blocks_to_swap=blocks_to_swap,
                swap_io_components=swap_io_components,
                main_device=device,
                offload_device=offload_device,
                debug=False,
            )
            self._blockswap_active = True

            # 诊断: 验证 BlockSwap 确实生效
            blockswap_marker = getattr(model, '_blockswap_active', False)
            blockswap_config = getattr(model, '_block_swap_config', None)
            logger.info(f"BlockSwap 诊断: model._blockswap_active={blockswap_marker}, "
                        f"config={blockswap_config}")

            if not blockswap_marker:
                logger.error("BlockSwap 未正确应用! 模型._blockswap_active=False，"
                             "这会导致模型整体加载到 GPU，内存爆满!")
                # 尝试手动设置
                model._blockswap_active = True

            logger.info("BlockSwap 已应用，模型将使用动态块交换")
        else:
            self._blockswap_active = False
            logger.warning(f"BlockSwap 未启用 (blocks_to_swap={blocks_to_swap}, "
                          f"swap_io_components={swap_io_components})，"
                          f"模型将整体加载到 GPU，可能内存不足!")
            if device in ["cuda", self._resolve_device("auto")]:
                model.to(device)

        _check_memory()
        _log_memory("DiT BlockSwap后")

        # DiT optimization reference (FlashVSR inspired)
        # LCSA sparse attention would be applied here when model supports it
        # Currently disabled as it requires model architecture changes

        num_params = sum(p.numel() for p in model.parameters())
        logger.info(f"DiT 参数数量: {num_params:,}, dtype={dit_dtype}, "
                     f"blockswap={self._blockswap_active}")

        return model

    def _load_vae_model(
        self,
        model_config: dict,
        checkpoint_path: str,
        device: str,
        *,
        vae_tiled_config: dict | None = None,
    ):
        """构建并加载 VAE 模型 - 严格对齐 ComfyUI HD 工作流参数

        REFACTOR [B1-1] [P3-1]: 显式参数化 VAE tiled 配置
        - 原实现从 self.config["model"]["vae"] 读取 tiled 参数，要求调用方先修改 self.config
        - 改为通过显式参数 vae_tiled_config 接收，调用方直接传入请求级配置
        - 参数为 None 时回退到 self.config，保持向后兼容

        ComfyUI 的 VAE 加载方式 (model_loader.py):
        1. 在 meta device 上构建模型结构 (零内存)
        2. 加载 safetensors 权重到 offload_device (CPU)
        3. 使用 assign=True 加载 (避免权重拷贝，零额外内存)
        4. 初始化 meta buffers
        5. 不做 model.to(dtype=...) 转换 (权重已在 state_dict 中转换)

        ComfyUI HD 工作流参数:
        - encode_tiled=true, decode_tiled=true, decode_tile_size=768
        - offload_device=cpu
        """
        from safetensors.torch import load_file

        # 预导入: 防止 attn_video_vae 导入时卡住
        import common.distributed.advanced  # noqa: F401

        # 读取 VAE YAML 配置获取完整参数
        vae_config = model_config["vae"]
        from models.video_vae_v3.modules.attn_video_vae import VideoAutoencoderKLWrapper

        vae_yaml_path = PROJECT_ROOT / vae_config.get("config", "models/video_vae_v3/s8_c16_t4_inflation_sd3.yaml")
        vae_params = self._load_vae_yaml_config(vae_yaml_path)

        # REFACTOR [B1-1]: 显式参数优先，None 时回退到 self.config
        # 原实现总是从 self.config["model"]["vae"] 读取，要求调用方先污染全局配置
        # 改为显式参数优先：调用方直接传入请求级 vae_tiled_config；None 时回退到 self.config
        if vae_tiled_config is None:
            vae_cfg = self.config.get("model", {}).get("vae", {})
            vae_tiled_config = {
                "encode_tiled": vae_cfg.get("encode_tiled", True),
                "encode_tile_size": vae_cfg.get("encode_tile_size", 1024),
                "encode_tile_overlap": vae_cfg.get("encode_tile_overlap", 128),
                "decode_tiled": vae_cfg.get("decode_tiled", True),
                "decode_tile_size": vae_cfg.get("decode_tile_size", 768),
                "decode_tile_overlap": vae_cfg.get("decode_tile_overlap", 128),
                "tile_debug": vae_cfg.get("tile_debug", False),
                "offload_device": vae_cfg.get("offload_device", "cpu"),
                "cache_model": vae_cfg.get("cache_model", True),
                "auto_tile_size": vae_cfg.get("auto_tile_size", True),
                "gaussian_blend": vae_cfg.get("gaussian_blend", True),
                "groupnorm_accumulate": vae_cfg.get("groupnorm_accumulate", True),
            }
        self._vae_tiled_config = vae_tiled_config
        logger.info(f"VAE tiled 配置: encode_tiled={self._vae_tiled_config['encode_tiled']}, "
                     f"decode_tiled={self._vae_tiled_config['decode_tiled']}, "
                     f"encode_tile_size={self._vae_tiled_config['encode_tile_size']}, "
                     f"decode_tile_size={self._vae_tiled_config['decode_tile_size']}, "
                     f"tile_overlap={self._vae_tiled_config['encode_tile_overlap']}")

        block_out_channels = tuple(vae_params.get("block_out_channels", [128, 256, 512, 512]))
        down_block_types = tuple(vae_params.get("down_block_types", ["DownEncoderBlock3D"] * len(block_out_channels)))
        up_block_types = tuple(vae_params.get("up_block_types", ["UpDecoderBlock3D"] * len(block_out_channels)))

        # ==================== 步骤1: 在 meta device 上构建 VAE (零内存) ====================
        _check_memory_before_load(checkpoint_path, "VAE")
        _check_memory()
        _log_memory("VAE构建前")
        with torch.device("meta"):
            model = VideoAutoencoderKLWrapper(
                spatial_downsample_factor=vae_params.get("spatial_downsample_factor", 8),
                temporal_downsample_factor=vae_params.get("temporal_downsample_factor", 4),
                in_channels=vae_params.get("in_channels", 3),
                out_channels=vae_params.get("out_channels", 3),
                down_block_types=down_block_types,
                up_block_types=up_block_types,
                block_out_channels=block_out_channels,
                layers_per_block=vae_params.get("layers_per_block", 2),
                latent_channels=vae_params.get("latent_channels", 16),
                use_quant_conv=vae_params.get("use_quant_conv", False),
                use_post_quant_conv=vae_params.get("use_post_quant_conv", False),
                temporal_scale_num=vae_params.get("temporal_scale_num", 2),
                inflation_mode=vae_params.get("inflation_mode", "pad"),
                slicing_sample_min_size=vae_params.get("slicing_sample_min_size", 4),
                freeze_encoder=vae_config.get("freeze_encoder", False),
            )

        # ==================== 步骤2: 加载权重到 CPU (offload_device) ====================
        _log_memory("VAE meta构建后")
        _check_memory()
        logger.info(f"加载 VAE safetensors 权重: {checkpoint_path}")
        state_dict = load_file(checkpoint_path, device="cpu")
        _log_memory("VAE权重加载后(raw)")
        _check_memory()

        # 逐个转换为目标 dtype (避免内存翻倍)
        # ComfyUI: VAE YAML 默认 dtype=float16, 但会被 compute_dtype 覆盖为 bfloat16
        vae_dtype = getattr(torch, vae_config.get("dtype", "bfloat16"))
        converted_count = 0
        for k in list(state_dict.keys()):
            v = state_dict[k]
            if isinstance(v, torch.Tensor) and v.dtype != vae_dtype:
                state_dict[k] = v.to(dtype=vae_dtype)
                del v
                converted_count += 1
                if converted_count % 50 == 0:
                    gc.collect()
                    _check_memory()
        if converted_count > 0:
            gc.collect()
            logger.info(f"VAE: 已将 {converted_count} 个参数转换为 {vae_dtype}")

        _check_memory()
        _log_memory("VAE权重dtype转换后")

        # ==================== 步骤3: 使用 assign=True 加载 (避免权重拷贝) ====================
        loading_info = model.load_state_dict(state_dict, strict=False, assign=True)
        del state_dict
        gc.collect()
        logger.info(f"VAE 加载信息: missing={len(loading_info.missing_keys)}, unexpected={len(loading_info.unexpected_keys)}")

        # 初始化 meta buffers (与 ComfyUI model_loader.py 一致)
        for _name, module in model.named_modules():
            for buffer_name, buffer in list(module.named_buffers(recurse=False)):
                if buffer.is_meta:
                    setattr(module, buffer_name, torch.zeros_like(buffer, device="cpu"))

        model.requires_grad_(False).eval()

        # 设置 causal slicing (与 ComfyUI 工作流一致)
        slicing_cfg = vae_config.get("slicing", {})
        if slicing_cfg:
            model.set_causal_slicing(
                split_size=slicing_cfg.get("split_size"),
                memory_device=slicing_cfg.get("memory_device", "same"),
            )

        # 设置内存限制 (与 ComfyUI 工作流一致)
        memory_limit_cfg = vae_config.get("memory_limit", {})
        if memory_limit_cfg and hasattr(model, "set_memory_limit"):
            model.set_memory_limit(**memory_limit_cfg)

        # 注意: 不做 model.to(dtype=vae_dtype)，权重已在 state_dict 中转换
        # ComfyUI 也不做这一步，model.to(dtype=...) 会创建 dtype 转换副本导致内存翻倍

        _check_memory()
        _log_memory("VAE权重加载后")

        return model

    def _load_vae_yaml_config(self, yaml_path: Path) -> dict:
        """加载 VAE YAML 配置文件

        读取并解析 VAE 架构配置文件（包含通道数、层数、下采样因子等参数）。
        文件不存在或解析失败时返回空字典，使用默认参数。

        Args:
            yaml_path: VAE YAML 配置文件路径

        Returns:
            dict: 解析后的配置字典，失败时返回空字典
        """
        if not yaml_path.exists():
            logger.warning(f"VAE YAML 配置未找到: {yaml_path}，使用默认参数")
            return {}

        try:
            import yaml as _yaml
            with open(str(yaml_path), encoding="utf-8") as f:
                params = _yaml.safe_load(f)
            return params if isinstance(params, dict) else {}
        except Exception as e:
            logger.warning(f"加载 VAE YAML 配置失败: {e}，使用默认参数")
            return {}

    # ------------------------------------------------------------------
    # 内部方法 - 扩散配置
    # ------------------------------------------------------------------

    def _configure_diffusion(self, model_config: dict, device: str):
        """配置扩散采样组件

        根据模型配置初始化噪声调度器（schedule）、采样时间步（timesteps）
        和采样器（sampler），这些组件是 DiT 采样的核心依赖。

        Args:
            model_config: 模型配置字典，应包含 "diffusion" 段
            device: 设备字符串，如 "cuda"

        Note:
            此方法会覆盖 self.schedule、self.sampling_timesteps、self.sampler，
            在每次采样前会根据 cfg_scale 和 sample_steps 重新配置。
        """
        from common.diffusion import (
            create_sampler_from_config,
            create_sampling_timesteps_from_config,
            create_schedule_from_config,
        )

        diff_cfg = model_config["diffusion"]
        # 转换为 OmegaConf DictConfig
        schedule_cfg = DictConfig(diff_cfg["schedule"])
        sampler_cfg = DictConfig(diff_cfg["sampler"])
        timesteps_cfg = DictConfig(diff_cfg["timesteps"]["sampling"])

        self.schedule = create_schedule_from_config(schedule_cfg, device)
        self.sampling_timesteps = create_sampling_timesteps_from_config(
            timesteps_cfg, self.schedule, device
        )
        self.sampler = create_sampler_from_config(
            sampler_cfg, self.schedule, self.sampling_timesteps
        )
        logger.info(f"扩散组件配置完成: schedule={diff_cfg['schedule']['type']}, "
                     f"sampler={diff_cfg['sampler']['type']}, "
                     f"steps={diff_cfg['timesteps']['sampling']['steps']}")

    # ------------------------------------------------------------------
    # 内部方法 - VAE 编解码
    # ------------------------------------------------------------------

    @torch.no_grad()
    def _vae_encode(self, samples: list[torch.Tensor]) -> list[torch.Tensor]:
        """VAE 编码: 像素空间 -> 潜空间，支持 tiled 编码

        与 ComfyUI/test_e2e.py 一致: 使用 vae.encode(x, tiled=True, tile_size=..., tile_overlap=...)
        集成 SCST 启发的自动 tile size 推荐和 NaN 检测回退。
        """
        from bin.integrated_app.optimization.vae_tiled_enhance import (
            get_optimal_tile_size, detect_nan,
        )

        vae_cfg = self._model_config["vae"]
        use_sample = vae_cfg.get("use_sample", True)
        scale = vae_cfg.get("scaling_factor", DEFAULT_SCALING_FACTOR)
        shift = vae_cfg.get("shifting_factor", 0.0)
        dtype = getattr(torch, vae_cfg.get("dtype", "bfloat16"))

        # tiled VAE 配置 (默认值对齐 ComfyUI HD 工作流: encode_tiled=True, tile_overlap=128)
        tiled_cfg = getattr(self, "_vae_tiled_config", {})
        encode_tiled = tiled_cfg.get("encode_tiled", True)
        tile_size = tiled_cfg.get("encode_tile_size", 1024)
        tile_overlap = tiled_cfg.get("encode_tile_overlap", 128)
        auto_tile_size = tiled_cfg.get("auto_tile_size", True)

        # 自动 tile size 推荐 (SCST inspired)
        if auto_tile_size and encode_tiled:
            try:
                # 根据输入尺寸和 GPU 显存计算最优 tile size
                if samples and len(samples) > 0:
                    sample = samples[0]
                    if sample.ndim >= 3:
                        h, w = sample.shape[-2], sample.shape[-1]
                        recommended_ts, recommended_overlap = get_optimal_tile_size(
                            h, w, is_decoder=False, device=self.device
                        )
                        # 如果配置的 tile_size 太大，使用推荐值
                        if tile_size <= 0 or tile_size > recommended_ts * 1.5:
                            tile_size = recommended_ts
                            tile_overlap = recommended_overlap
                            logger.info(f"VAE 编码自动 tile size: {tile_size}, overlap: {tile_overlap}")
            except Exception as e:
                logger.debug(f"自动 tile size 推荐失败: {e}")

        if isinstance(scale, list):
            scale = torch.tensor(scale, device=self.device, dtype=dtype)
        if isinstance(shift, list):
            shift = torch.tensor(shift, device=self.device, dtype=dtype)

        latents = []
        oom_fallback_used = False
        for sample in samples:
            # sample: C T H W -> B C T H W
            batch = sample.unsqueeze(0).to(self.device, dtype)
            if hasattr(self.vae, "preprocess"):
                batch = self.vae.preprocess(batch)

            if encode_tiled:
                logger.info(f"VAE tiled 编码: tile_size={tile_size}, overlap={tile_overlap}")
                try:
                    enc_result = self.vae.encode(
                        batch,
                        tiled=True,
                        tile_size=(tile_size, tile_size),
                        tile_overlap=(tile_overlap, tile_overlap),
                    )
                except RuntimeError as e:
                    if "out of memory" in str(e).lower() and not oom_fallback_used:
                        logger.warning(f"VAE 编码 OOM，尝试更小的 tile size")
                        torch.cuda.empty_cache()
                        tile_size = max(tile_size // 2, 256)
                        tile_overlap = max(tile_overlap // 2, 32)
                        enc_result = self.vae.encode(
                            batch,
                            tiled=True,
                            tile_size=(tile_size, tile_size),
                            tile_overlap=(tile_overlap, tile_overlap),
                        )
                        oom_fallback_used = True
                    else:
                        raise
            else:
                enc_result = self.vae.encode(batch)

            # 提取 latent
            if use_sample:
                latent = enc_result.latent
            else:
                latent = enc_result.posterior.mode().squeeze(2)

            latent = latent.unsqueeze(2) if latent.ndim == 4 else latent

            # NaN 检测
            if encode_tiled and detect_nan(latent, "vae_encode_latent"):
                logger.warning("VAE 编码检测到 NaN，回退到非 tiled 编码")
                torch.cuda.empty_cache()
                enc_result = self.vae.encode(batch)
                if use_sample:
                    latent = enc_result.latent
                else:
                    latent = enc_result.posterior.mode().squeeze(2)
                latent = latent.unsqueeze(2) if latent.ndim == 4 else latent

            # channels-first -> channels-last + 缩放
            latent = rearrange(latent, "b c ... -> b ... c")
            latent = (latent - shift) * scale
            latents.append(latent.squeeze(0))  # 去掉 batch 维度

        return latents

    @torch.no_grad()
    def _vae_decode(self, latents: list[torch.Tensor]) -> list[torch.Tensor]:
        """VAE 解码: 潜空间 -> 像素空间，支持 tiled 解码

        与 ComfyUI/test_e2e.py 一致: 使用 vae.decode(x, tiled=True, tile_size=..., tile_overlap=...)
        集成 SCST 启发的自动 tile size 推荐、OOM 回退和 NaN 检测。
        """
        from bin.integrated_app.optimization.vae_tiled_enhance import (
            get_optimal_tile_size, detect_nan, GroupNormAccumulator, TiledVAEHook,
        )

        vae_cfg = self._model_config["vae"]
        scale = vae_cfg.get("scaling_factor", DEFAULT_SCALING_FACTOR)
        shift = vae_cfg.get("shifting_factor", 0.0)
        dtype = getattr(torch, vae_cfg.get("dtype", "bfloat16"))

        # tiled VAE 配置 (默认值对齐 ComfyUI HD 工作流: decode_tiled=True, decode_tile_size=768)
        tiled_cfg = getattr(self, "_vae_tiled_config", {})
        decode_tiled = tiled_cfg.get("decode_tiled", True)
        tile_size = tiled_cfg.get("decode_tile_size", 768)
        tile_overlap = tiled_cfg.get("decode_tile_overlap", 128)
        auto_tile_size = tiled_cfg.get("auto_tile_size", True)
        gaussian_blend = tiled_cfg.get("gaussian_blend", True)
        use_groupnorm_accum = tiled_cfg.get("groupnorm_accumulate", True)

        if isinstance(scale, list):
            scale = torch.tensor(scale, device=self.device, dtype=dtype)
        if isinstance(shift, list):
            shift = torch.tensor(shift, device=self.device, dtype=dtype)

        # 准备 GroupNorm 累积器和 TiledVAEHook
        groupnorm_accum = None
        tiled_hook = None
        if decode_tiled and use_groupnorm_accum:
            try:
                groupnorm_accum = GroupNormAccumulator(self.vae)
                groupnorm_accum.start_accumulation()
            except Exception as e:
                logger.debug(f"GroupNormAccumulator init failed: {e}")
                groupnorm_accum = None

        if decode_tiled and gaussian_blend:
            try:
                tiled_hook = TiledVAEHook(self.vae)
                tiled_hook.install()
            except Exception as e:
                logger.debug(f"TiledVAEHook install failed: {e}")
                tiled_hook = None

        samples = []
        oom_fallback_used = False
        nan_fallback_used = False
        try:
            for latent in latents:
                # latent: ... C -> B ... C
                batch = latent.unsqueeze(0).to(self.device, dtype)
                batch = batch / scale + shift
                batch = rearrange(batch, "b ... c -> b c ...")
                batch = batch.squeeze(2)

                # 自动 tile size 推荐 (SCST inspired)
                # 重要: vae.decode 的 tile_size 参数为像素空间单位！VAE 内部自动 // 8 转换为潜空间
                current_tile_size = tile_size  # 像素空间
                current_tile_overlap = tile_overlap  # 像素空间
                if auto_tile_size and decode_tiled:
                    try:
                        if batch.ndim >= 4:
                            h_latent, w_latent = batch.shape[-2], batch.shape[-1]
                            # latent 空间尺寸 * 8 = 输出像素空间尺寸
                            h_pixel = h_latent * 8
                            w_pixel = w_latent * 8
                            # get_optimal_tile_size 直接返回像素空间推荐值
                            recommended_ts, recommended_overlap = get_optimal_tile_size(
                                h_pixel, w_pixel, is_decoder=True, device=self.device
                            )
                            # 如果配置的 tile_size 太大，使用推荐值（像素空间）
                            if current_tile_size <= 0 or current_tile_size > recommended_ts * 1.5:
                                current_tile_size = recommended_ts
                                current_tile_overlap = recommended_overlap
                                logger.info(
                                    f"VAE 解码自动 tile size (像素): {current_tile_size}, "
                                    f"overlap: {current_tile_overlap} "
                                    f"(潜空间: ~{current_tile_size//8}, ~{current_tile_overlap//8})"
                                )
                    except Exception as e:
                        logger.debug(f"自动 tile size 推荐失败: {e}")

                if decode_tiled:
                    logger.info(
                        f"VAE tiled 解码: tile_size={current_tile_size}, "
                        f"overlap={current_tile_overlap}, gaussian_blend={gaussian_blend}, "
                        f"groupnorm_accum={use_groupnorm_accum}"
                    )
                    try:
                        dec_result = self.vae.decode(
                            batch,
                            tiled=True,
                            tile_size=(current_tile_size, current_tile_size),
                            tile_overlap=(current_tile_overlap, current_tile_overlap),
                        )
                    except RuntimeError as e:
                        if "out of memory" in str(e).lower() and not oom_fallback_used:
                            logger.warning(f"VAE 解码 OOM，尝试更小的 tile size")
                            torch.cuda.empty_cache()
                            _force_release_memory()
                            # OOM 回退: 像素空间 tile size 减半，最小 256
                            current_tile_size = max(current_tile_size // 2, 256)
                            current_tile_overlap = max(current_tile_overlap // 2, 32)
                            dec_result = self.vae.decode(
                                batch,
                                tiled=True,
                                tile_size=(current_tile_size, current_tile_size),
                                tile_overlap=(current_tile_overlap, current_tile_overlap),
                            )
                            oom_fallback_used = True
                        elif "out of memory" in str(e).lower():
                            # 第二次 OOM，完全禁用 tiled
                            logger.warning("VAE 解码再次 OOM，回退到非 tiled 解码")
                            torch.cuda.empty_cache()
                            _force_release_memory()
                            dec_result = self.vae.decode(batch)
                        else:
                            raise

                    sample = dec_result.sample

                    # Gaussian 权重混合增强 (SCST/VEncancer inspired)
                    if gaussian_blend and getattr(self.vae, '_last_tile_outputs', None):
                        try:
                            from bin.integrated_app.optimization.vae_tiled_enhance import blend_tiles_gaussian
                            tile_outputs = self.vae._last_tile_outputs
                            tile_positions = self.vae._last_tile_positions
                            if tile_outputs and tile_positions:
                                output_h, output_w = sample.shape[-2:]
                                # tile_size 已经是像素空间
                                actual_tile_size = getattr(self.vae, '_last_tile_size', current_tile_size)
                                actual_tile_overlap = getattr(self.vae, '_last_tile_overlap', current_tile_overlap)
                                sample = blend_tiles_gaussian(
                                    tile_outputs, tile_positions,
                                    (output_h, output_w),
                                    actual_tile_size,
                                    actual_tile_overlap,
                                    device=self.device, dtype=sample.dtype,
                                )
                                logger.info(f"VAE tiled: Gaussian 混合完成, {len(tile_outputs)} tiles")
                        except Exception as e:
                            logger.debug(f"Gaussian 混合失败: {e}")

                    # NaN 检测
                    if detect_nan(sample, "vae_decode_sample") and not nan_fallback_used:
                        logger.warning("VAE 解码检测到 NaN，回退到非 tiled 解码")
                        torch.cuda.empty_cache()
                        _force_release_memory()
                        dec_result = self.vae.decode(batch)
                        sample = dec_result.sample
                        nan_fallback_used = True
                else:
                    dec_result = self.vae.decode(batch)
                    sample = dec_result.sample

                if hasattr(self.vae, "postprocess"):
                    sample = self.vae.postprocess(sample)

                # 输出 NaN 最终检测
                if detect_nan(sample, "vae_decode_final"):
                    logger.error("VAE 解码最终输出仍包含 NaN，使用零填充")
                    sample = torch.nan_to_num(sample, nan=0.0, posinf=1.0, neginf=-1.0)

                samples.append(sample.squeeze(0))
        finally:
            # 清理 hook 和累积器
            if tiled_hook is not None:
                try:
                    tiled_hook.uninstall()
                except Exception:
                    pass
            if groupnorm_accum is not None:
                try:
                    groupnorm_accum.apply_accumulated_stats()
                except Exception as e:
                    logger.debug(f"GroupNorm stats apply failed: {e}")

        return samples

    # ------------------------------------------------------------------
    # 内部方法 - DiT 采样
    # ------------------------------------------------------------------

    def _get_text_embeds(self) -> dict:
        """获取正负文本嵌入张量

        加载预训练的正面和负面文本嵌入，移动到推理设备。
        如果文本嵌入文件不存在，使用零嵌入作为 fallback（仍可推理但无文本引导）。

        Returns:
            dict: 包含 "texts_pos" 和 "texts_neg" 键的字典，
                 值为嵌入张量列表（长度为1，适配 batch 接口）
        """
        if self.pos_emb is not None and self.neg_emb is not None:
            return {
                "texts_pos": [self.pos_emb.to(self.device)],
                "texts_neg": [self.neg_emb.to(self.device)],
            }
        else:
            logger.warning("使用零文本嵌入")
            dummy = torch.zeros(1, TEXT_EMBED_DIM, device=self.device, dtype=torch.float16)
            return {
                "texts_pos": [dummy],
                "texts_neg": [dummy],
            }

    def _get_condition(self, latent: torch.Tensor, latent_blur: torch.Tensor,
                       task: str = "sr") -> torch.Tensor:
        """构建 DiT 条件输入张量

        根据任务类型将低分辨率潜变量与条件标记拼接为模型输入。
        不同任务使用不同的帧作为条件:
        - sr (超分): 所有帧使用模糊潜变量作为条件，最后一通道为 1.0 标记
        - i2v (图像生视频): 仅第一帧使用原始潜变量
        - v2v (视频生视频): 前两帧使用原始潜变量

        Args:
            latent: 原始潜变量张量，形状 T H W C
            latent_blur: 模糊/退化潜变量张量（低分辨率输入），形状 T H W C
            task: 任务类型，"sr"/"i2v"/"v2v"

        Returns:
            torch.Tensor: 条件张量，形状 T H W (C+1)，最后一通道为条件标记

        Raises:
            NotImplementedError: 未知任务类型时抛出
        """
        t, h, w, c = latent.shape
        cond = torch.zeros([t, h, w, c + 1], device=latent.device, dtype=latent.dtype)
        if task == "sr" or t == 1:
            cond[:, ..., :-1] = latent_blur[:]
            cond[:, ..., -1:] = 1.0
            return cond
        if task == "i2v":
            cond[:1, ..., :-1] = latent[:1]
            cond[:1, ..., -1:] = 1.0
            return cond
        if task == "v2v":
            cond[:2, ..., :-1] = latent[:2]
            cond[:2, ..., -1:] = 1.0
            return cond
        raise NotImplementedError(f"未知任务类型: {task}")

    def _timestep_transform(self, timesteps: torch.Tensor, latents_shapes: torch.Tensor) -> torch.Tensor:
        """分辨率自适应时间步变换

        根据输入分辨率和帧数动态调整扩散时间步，使不同分辨率/长度的输入
        都能获得合适的噪声调度。这是高分辨率/长视频生成的关键技巧。

        算法原理:
        - 小分辨率/短帧: shift=1.0，不做变换
        - 大分辨率/长帧: 使用线性函数增大 shift 值，等效于加强早期去噪
        - 图像和视频使用不同的 shift 函数（视频需要更大的 shift）

        Args:
            timesteps: 原始时间步张量
            latents_shapes: 潜变量形状张量 [batch, [t, h, w, c]]

        Returns:
            torch.Tensor: 变换后的时间步张量

        Note:
            此方法对齐 VideoDiffusionInfer.timestep_transform 官方实现，
            如果配置中 timesteps.transform=False 则直接返回原始时间步。
        """
        diff_cfg = self._model_config["diffusion"]
        if not diff_cfg.get("timesteps", {}).get("transform", False):
            return timesteps

        vae_cfg = self._model_config["vae"]
        vt = vae_cfg.get("temporal_downsample_factor", 4)
        vs = DEFAULT_VAE_SPATIAL_DOWNSAMPLE

        frames = (latents_shapes[:, 0] - 1) * vt + 1
        heights = latents_shapes[:, 1] * vs
        widths = latents_shapes[:, 2] * vs

        def get_lin_function(x1, y1, x2, y2):
            m = (y2 - y1) / (x2 - x1)
            b = y1 - m * x1
            return lambda x: m * x + b

        img_shift_fn = get_lin_function(x1=256 * 256, y1=1.0, x2=1024 * 1024, y2=3.2)
        vid_shift_fn = get_lin_function(x1=256 * 256 * 37, y1=1.0, x2=1280 * 720 * 145, y2=5.0)
        shift = torch.where(
            frames > 1,
            vid_shift_fn(heights * widths * frames),
            img_shift_fn(heights * widths),
        )

        timesteps = timesteps / self.schedule.T
        timesteps = shift * timesteps / (1 + (shift - 1) * timesteps)
        timesteps = timesteps * self.schedule.T
        return timesteps

    def _generation_step(self, cond_latents: list[torch.Tensor], text_embeds: dict,
                         cfg_scale: float = 7.5, cfg_rescale: float = 0.0,
                         sample_steps: int = 50, seed: int = 42,
                         input_noise_scale: float = 0.0,
                         latent_noise_scale: float = 0.0,
                         restoration_guidance_scale: float = 0.0) -> list[torch.Tensor]:
        """DiT 采样步骤

        支持两种模式:
        - 标准模式 (cfg_scale=7.5, steps=50): 50步 Euler 采样 + CFG
        - 蒸馏模式 (cfg_scale=1.0, steps=1): 单步推理 + 噪声增强

        关键: 采样前必须对 timesteps 应用 timestep_transform (分辨率自适应偏移)
        """
        from common.diffusion import classifier_free_guidance_dispatcher
        from models.dit_v2 import na

        # 更新 CFG 和采样步数，重新配置扩散组件
        diff_cfg = self._model_config["diffusion"]
        diff_cfg["cfg"]["scale"] = cfg_scale
        diff_cfg["cfg"]["rescale"] = cfg_rescale
        diff_cfg["timesteps"]["sampling"]["steps"] = sample_steps
        self._configure_diffusion(self._model_config, self.device)

        # 设置随机种子
        torch.manual_seed(seed)

        # 生成噪声
        noises = [torch.randn_like(latent) for latent in cond_latents]
        logger.info(f"噪声形状: {noises[0].size()}, cfg_scale={cfg_scale}, steps={sample_steps}")

        is_distilled = (sample_steps == 1 and cfg_scale == 1.0)

        # 噪声增强: 严格对齐 ComfyUI 工作流
        # ComfyUI 中 latent_noise_scale 默认为 0.0 (不加噪声到条件)
        # aug_noises 仅在 latent_noise_scale > 0 时才有意义
        if is_distilled and latent_noise_scale > 0:
            aug_noises = [base * 0.1 + torch.randn_like(base) * 0.05 for base in noises]
            cond_noise_scale = latent_noise_scale
        else:
            # 默认路径: 不对条件添加噪声 (与 ComfyUI 工作流一致)
            aug_noises = [torch.zeros_like(n) for n in noises]
            cond_noise_scale = 0.0

        def _add_noise(x, aug_noise):
            if cond_noise_scale <= 0:
                return x
            t = torch.tensor([1000.0], device=self.device) * cond_noise_scale
            shape = torch.tensor(x.shape, device=self.device)[None]  # 包含 T 维度
            t = self._timestep_transform(t, shape)
            x = self.schedule.forward(x, aug_noise, t)
            return x

        # 构建条件
        conditions = [
            self._get_condition(
                noise,
                task="sr",
                latent_blur=_add_noise(latent_blur, aug_noise),
            )
            for noise, aug_noise, latent_blur in zip(noises, aug_noises, cond_latents, strict=False)
        ]

        # 文本嵌入
        texts_pos = text_embeds["texts_pos"]
        texts_neg = text_embeds["texts_neg"]

        # Flatten
        text_pos_embeds, text_pos_shapes = na.flatten(texts_pos)
        text_neg_embeds, text_neg_shapes = na.flatten(texts_neg)
        latents, latents_shapes = na.flatten(noises)
        latents_cond, _ = na.flatten(conditions)

        batch_size = len(noises)

        # ===== 关键: 对采样时间步应用 timestep_transform =====
        # 与 test_e2e.py 一致: 在采样前替换 sampler 的 timesteps
        original_timesteps = self.sampler.timesteps.timesteps
        raw_timesteps = self.sampling_timesteps.timesteps
        # latents_shapes[0] 是第一个样本的形状 [t, h, w, c]
        first_latent_shape = torch.tensor(noises[0].shape, device=self.device)
        transformed_timesteps = self._timestep_transform(raw_timesteps, first_latent_shape.unsqueeze(0))
        self.sampler.timesteps.timesteps = transformed_timesteps
        logger.info(f"timestep_transform 已应用, timesteps 范围: [{transformed_timesteps.min():.1f}, {transformed_timesteps.max():.1f}]")

        # 采样
        self.dit.eval()

        # 初始化采样增强模块
        _restoration_sampler = None
        _dynamic_cfg = None
        if restoration_guidance_scale > 0:
            from bin.integrated_app.optimization.diffusion_sampling import (
                RestorationGuidedSampling, RestorationGuidanceConfig,
                apply_cfg_rescale as apply_cfg_rescale_fn,
            )
            _restoration_sampler = RestorationGuidedSampling(RestorationGuidanceConfig(
                enabled=True,
                guidance_scale=restoration_guidance_scale,
                timestep_decay=True,
                decay_type="cosine",
                decay_start_ratio=0.3,
            ))

        # 动态 CFG: 从配置读取是否启用
        dynamic_cfg_enabled = self.config.get("inference", {}).get("dynamic_cfg", False)
        if dynamic_cfg_enabled and cfg_scale > 1.0:
            from bin.integrated_app.optimization.diffusion_sampling import DynamicCFG
            _dynamic_cfg = DynamicCFG(initial_scale=cfg_scale * 0.5, final_scale=cfg_scale)

        try:
            with torch.no_grad(), torch.autocast("cuda", torch.bfloat16, enabled=(self.device == "cuda")):
                total_steps = len(self.sampler.timesteps.timesteps)
                latents = self.sampler.sample(
                    x=latents,
                    f=lambda args: self._guided_generation_step(
                        args=args,
                        latents_cond=latents_cond,
                        text_pos_embeds=text_pos_embeds,
                        text_neg_embeds=text_neg_embeds,
                        text_pos_shapes=text_pos_shapes,
                        text_neg_shapes=text_neg_shapes,
                        latents_shapes=latents_shapes,
                        batch_size=batch_size,
                        cfg_scale=(
                            _dynamic_cfg.get_scale(args.i, total_steps) if _dynamic_cfg is not None
                            else (
                                cfg_scale
                                if (args.i + 1) / total_steps
                                <= diff_cfg["cfg"].get("partial", 1)
                                else 1.0
                            )
                        ),
                        cfg_rescale=cfg_rescale,
                        restoration_guidance_scale=restoration_guidance_scale,
                        current_noisy=latents_cond,  # 使用原始条件 latent 而非初始噪声
                        restoration_sampler=_restoration_sampler,
                        current_step=args.i,
                        total_steps=total_steps,
                    ),
                )
        finally:
            # 恢复原始 timesteps
            self.sampler.timesteps.timesteps = original_timesteps

        # Unflatten
        latents = na.unflatten(latents, latents_shapes)
        return latents

    def _guided_generation_step(
        self,
        args,
        latents_cond: torch.Tensor,
        text_pos_embeds: torch.Tensor,
        text_neg_embeds: torch.Tensor,
        text_pos_shapes: list,
        text_neg_shapes: list,
        latents_shapes: list,
        batch_size: int,
        cfg_scale: float,
        cfg_rescale: float,
        restoration_guidance_scale: float,
        current_noisy: torch.Tensor,
        restoration_sampler=None,
        current_step: int = 0,
        total_steps: int = 1,
    ) -> torch.Tensor:
        """带 Restoration Guidance 的 DiT 生成步 (Vivid-VR inspired)

        在标准 CFG 基础上，额外约束输出与退化输入的一致性，
        使修复结果在保真度和真实感之间取得平衡。
        支持时间步衰减、cfg_rescale 稳定性增强和动态 CFG。

        当 restoration_guidance_scale == 0 时退化为标准 CFG，无额外开销。
        """
        from common.diffusion import classifier_free_guidance_dispatcher
        from models.dit_v2 import na

        # 正向条件输出
        pos_output = self.dit(
            vid=torch.cat([args.x_t, latents_cond], dim=-1),
            txt=text_pos_embeds,
            vid_shape=latents_shapes,
            txt_shape=text_pos_shapes,
            timestep=args.t.repeat(batch_size),
        ).vid_sample

        # 负向条件输出
        neg_output = self.dit(
            vid=torch.cat([args.x_t, latents_cond], dim=-1),
            txt=text_neg_embeds,
            vid_shape=latents_shapes,
            txt_shape=text_neg_shapes,
            timestep=args.t.repeat(batch_size),
        ).vid_sample

        # 计算标准 CFG 结果
        cfg_result = classifier_free_guidance_dispatcher(
            pos=lambda: pos_output,
            neg=lambda: neg_output,
            scale=cfg_scale,
            rescale=cfg_rescale,
        )

        # 应用 cfg_rescale 稳定性增强 (VEnhancer inspired)
        if cfg_rescale > 0:
            from bin.integrated_app.optimization.diffusion_sampling import apply_cfg_rescale as apply_cfg_rescale_fn
            cfg_result = apply_cfg_rescale_fn(cfg_result, pos_output, rescale_factor=cfg_rescale)

        # Restoration Guidance (Vivid-VR inspired) 带时间步衰减
        effective_restoration_scale = restoration_guidance_scale
        if restoration_sampler is not None and restoration_guidance_scale > 0:
            effective_restoration_scale = restoration_sampler.compute_guidance_scale(
                base_cfg_scale=1.0,
                current_step=current_step,
                total_steps=total_steps,
            )

        if effective_restoration_scale > 0:
            # 应用 Restoration Guidance: 将 CFG 结果向原始输入方向偏移
            # fidelity_direction = original_condition - current_noisy
            fidelity_direction = current_noisy - args.x_t
            guided_result = cfg_result + effective_restoration_scale * fidelity_direction
            return guided_result

        # 标准 CFG (无 restoration guidance)
        return cfg_result

    # ------------------------------------------------------------------
    # 内部方法 - 视频处理辅助
    # ------------------------------------------------------------------

    def _build_video_transform(self, res_h: int, res_w: int) -> Compose:
        """构建视频/图像预处理变换流水线

        创建与官方 ComfyUI 工作流一致的预处理变换序列，按顺序执行:
        1. _NaResize: 按短边缩放到目标分辨率（area 插值，保持长宽比）
        2. Clamp: 将像素值裁剪到 [0, 1] 范围
        3. _DivisibleCrop: 裁剪到 tile_size 整数倍，避免 VAE 分块边界问题
        4. Normalize: 标准化到 [-1, 1]（均值 0.5，标准差 0.5）
        5. _RearrangeTCHW2CTHW: 将 T C H W 重排为 C T H W（适配模型输入格式）

        Args:
            res_h: 目标高度
            res_w: 目标宽度

        Returns:
            Compose: torchvision Compose 变换对象
        """
        return Compose([
            _NaResize(
                resolution=(res_h * res_w) ** 0.5,
                mode="area",
                downsample_only=False,
            ),
            Lambda(lambda x: torch.clamp(x, 0.0, 1.0)),
            _DivisibleCrop((TILE_ALIGNMENT_FACTOR, TILE_ALIGNMENT_FACTOR)),
            Normalize(0.5, 0.5),
            _RearrangeTCHW2CTHW(),
        ])

    @staticmethod
    def _cut_videos(videos: torch.Tensor, sp_size: int) -> torch.Tensor:
        """视频帧数对齐填充

        将视频帧数填充到 TEMPORAL_ALIGN_MULTIPLE * sp_size 的整数倍，
        确保 VAE 时间下采样时不会出错。使用最后一帧作为填充内容。

        Args:
            videos: 视频张量，形状 B C T H W
            sp_size: 空间分块大小（影响时间对齐粒度）

        Returns:
            torch.Tensor: 填充后的视频张量，帧数已对齐
        """
        t = videos.size(1)
        align_frames = TEMPORAL_ALIGN_MULTIPLE * sp_size
        if t == 1:
            return videos
        if t <= align_frames:
            padding = [videos[:, -1].unsqueeze(1)] * (align_frames - t + 1)
            padding = torch.cat(padding, dim=1)
            videos = torch.cat([videos, padding], dim=1)
            return videos
        if (t - 1) % align_frames == 0:
            return videos
        else:
            padding = [videos[:, -1].unsqueeze(1)] * (align_frames - ((t - 1) % align_frames))
            padding = torch.cat(padding, dim=1)
            videos = torch.cat([videos, padding], dim=1)
            assert (videos.size(1) - 1) % align_frames == 0
            return videos

"""SeedVR2 推理引擎 - 基于 ByteDance SeedVR 官方推理逻辑实现

初始化流程:
1. 加载 safetensors 模型权重 (支持 FP16 / FP8 E4M3FN)
2. 构建 DiT / VAE 模型结构 (meta device + assign=True)

推理流水线 (4 阶段):
1. VAE 编码: 像素空间 -> 潜空间
2. DiT 采样: 低分辨率潜空间 -> 高分辨率潜空间 (BlockSwap 动态交换)
3. VAE 解码: 潜空间 -> 像素空间
4. 后处理: 颜色校正 (LAB/Wavelet) + 其他增强
"""
import asyncio
import gc
import json
import logging
import os
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

_MEMORY_THRESHOLD = 0.90  # 内存使用率阈值 (90%)

# Scaling factor for VAE latent space (from model config default)
DEFAULT_SCALING_FACTOR = 0.9152

# Default spatial downsample factor for VAE
DEFAULT_VAE_SPATIAL_DOWNSAMPLE = 8

# Tile processing alignment factor
TILE_ALIGNMENT_FACTOR = 16

# SeedVR2 时间维度对齐倍数: 帧数需满足 (T-1) 能被 4*sp_size 整除
TEMPORAL_ALIGN_MULTIPLE = 4

# SeedVR2 文本嵌入维度 (零嵌入 fallback 使用)
TEXT_EMBED_DIM = 5120

# GC interval (number of parameters) during dtype conversion loops
DTYPE_CONVERSION_GC_INTERVAL = 50

# Maximum random seed value (32-bit unsigned int)
MAX_SEED = 2**32 - 1

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
    try:
        import psutil
        mem = psutil.virtual_memory()
        usage = mem.percent / 100.0
        if usage > threshold:
            # 强制清理 GPU 缓存
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
            gc.collect()
            _force_release_memory()

            # 重新检查
            mem = psutil.virtual_memory()
            usage = mem.percent / 100.0
            if usage > threshold:
                raise MemoryError(
                    f"内存使用率 {usage:.1%} 超过阈值 {threshold:.0%}，"
                    f"可用: {mem.available/1024**3:.1f}GB / {mem.total/1024**3:.1f}GB。"
                    f"必须立即终止模型！"
                )
        return usage
    except ImportError:
        return 0.0


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
    try:
        import psutil
        model_size_gb = _estimate_model_size_gb(checkpoint_path)
        mem = psutil.virtual_memory()
        available_gb = mem.available / (1024 ** 3)
        usage = mem.percent / 100.0

        # 需要 1.5 倍模型大小的可用内存 (考虑 dtype 转换临时开销)
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
    except ImportError:
        pass


def _log_memory(tag: str = ""):
    """记录当前内存状态 (RAM + VRAM)"""
    try:
        import psutil
        mem = psutil.virtual_memory()
        vram_alloc = torch.cuda.memory_allocated(0) / 1024**3 if torch.cuda.is_available() else 0
        vram_resv = torch.cuda.memory_reserved(0) / 1024**3 if torch.cuda.is_available() else 0
        logger.info(f"[内存{tag}] RAM: {mem.percent:.0f}% ({mem.available/1024**3:.1f}GB可用/{mem.total/1024**3:.1f}GB), "
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
    # 多轮 GC 确保所有循环引用被清理
    for _ in range(3):
        gc.collect()

    # 清理 PyTorch GPU 缓存
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()

    # 强制 OS 回收空闲堆内存
    try:
        import ctypes
        import platform
        if platform.system() == 'Windows':
            # Windows: 调用 _heapmin() 返回空闲堆内存给 OS
            ctypes.CDLL('msvcrt')._heapmin()
        else:
            # Linux: 调用 malloc_trim(0) 返回空闲内存给 OS
            ctypes.CDLL('libc.so.6').malloc_trim(0)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 数据变换 (与官方 projects/inference_seedvr2_3b.py 一致)
# ---------------------------------------------------------------------------

class _NaResize:
    """面积/边缩放 (简化版，与 data.image.transforms.na_resize 对齐)"""
    def __init__(self, resolution: float, mode: str = "area", downsample_only: bool = False):
        self.resolution = resolution
        self.mode = mode
        self.downsample_only = downsample_only

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        # x: T C H W
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
        # 使用双三次插值
        x = x.float()
        x = torch.nn.functional.interpolate(
            x.reshape(1, t * c, h, w), size=(new_h, new_w), mode="bicubic", align_corners=False
        )
        return x.reshape(t, c, new_h, new_w)


class _DivisibleCrop:
    """确保 H/W 能被 factor 整除"""
    def __init__(self, factor):
        if not isinstance(factor, tuple):
            factor = (factor, factor)
        self.h_factor, self.w_factor = factor

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        # x: T C H W
        h, w = x.shape[-2], x.shape[-1]
        new_h = h - (h % self.h_factor)
        new_w = w - (w % self.w_factor)
        if new_h != h or new_w != w:
            x = x[:, :, :new_h, :new_w]
        return x


class _RearrangeTCHW2CTHW:
    """T C H W -> C T H W"""
    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        return rearrange(x, "t c h w -> c t h w")


# ---------------------------------------------------------------------------
# FP8 反量化
# ---------------------------------------------------------------------------

def dequantize_fp8_to_fp16(state_dict: dict) -> dict:
    """将 FP8 E4M3FN 权重反量化为 FP16"""
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
    """图像推理配置 - 封装所有 DiT/VAE/放大参数"""
    # DiT 配置
    dit_model: str = "3b_fp16"
    dit_device: str = "cuda:0"
    blocks_to_swap: int = 32
    swap_io_components: bool = True
    dit_offload_device: str = "cpu"
    dit_cache_model: bool = True
    attention_mode: str = "sdpa"
    # VAE 配置
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
    # 放大配置
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
        """从 config.yaml dict 构建，overrides 可覆盖特定字段"""
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
    """SeedVR2 视频修复引擎 - 完整推理流水线"""

    def __init__(self, config: dict):
        self.config = config
        # 模型组件
        self.dit = None
        self.vae = None
        self.pos_emb = None
        self.neg_emb = None
        # 扩散组件
        self.schedule = None
        self.sampling_timesteps = None
        self.sampler = None
        # 状态
        self.model_size = None
        self.precision = "fp16"
        self.device = "cpu"
        self._loaded = False
        self._progress_callback = None
        self._model_config = None
        self._blockswap_active = False
        self._dit_checkpoint_path = None  # 保存 DiT checkpoint 路径，用于 DiT 销毁后重新加载
        self._dit_model_size = None  # 延迟加载时保存模型大小
        self._dit_precision = None   # 延迟加载时保存精度
        # REFACTOR [E4-1]: 推理取消令牌
        # 原实现 task_queue 超时后调用 asyncio.wait_for 取消 asyncio.Task，
        # 但底层 asyncio.to_thread 包装的推理线程无法被 cancel，GPU 资源持续占用
        # 新增 _cancel_event，让推理线程在阶段切换点主动检查并退出
        self._cancel_event = threading.Event()
        # 外部工具
        self._ffmpeg = FFmpegWrapper()
        self._video_processor = VideoProcessor(self._ffmpeg)

    def set_progress_callback(self, callback: Callable):
        self._progress_callback = callback

    # REFACTOR [E4-1]: 推理取消机制
    # task_queue 超时或用户主动取消时调用 request_cancel()，
    # 推理线程在阶段切换点通过 _check_cancelled() 主动检查并抛出 InferenceCancelledError

    def request_cancel(self) -> None:
        """请求取消当前推理任务

        由 TaskQueue 在超时或用户取消时调用。
        设置 _cancel_event，推理线程在下一个阶段切换点检测到后退出。
        """
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
        if self._cancel_event.is_set():
            logger.info(f"推理在阶段 '{stage}' 被取消")
            raise InferenceCancelledError(
                f"推理在阶段 '{stage}' 被取消",
                detail={"stage": stage},
            )

    def _reset_cancel_token(self) -> None:
        """重置取消令牌（在每次推理开始前调用）"""
        self._cancel_event.clear()

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

    def _destroy_dit(self):
        """完全销毁 DiT 模型，释放全部 VRAM 和 RAM

        BlockSwap 的 _protect_model_from_move 阻止了 model.to("cpu") 的正常执行，
        导致 DiT 推理后 VRAM 无法释放，VAE 解码时 OOM。
        因此需要在 DiT 推理完成后完全销毁模型，而非仅移到 CPU。

        关键: 必须同时释放 CPU 上的参数 (BlockSwap offload) 和 GPU 上的激活，
        否则 RAM 不会释放，多次推理后内存爆满。
        """
        if self.dit is None:
            return
        if self._blockswap_active:
            cleanup_blockswap(self.dit)
            self._blockswap_active = False

        # 清理 RoPE LRU 缓存
        for _name, module in self.dit.named_modules():
            if hasattr(module, 'get_axial_freqs') and hasattr(module.get_axial_freqs, 'cache_clear'):
                with contextlib.suppress(Exception):
                    module.get_axial_freqs.cache_clear()

        # 释放所有参数 (CPU + GPU)
        # 必须先处理 CPU 上的参数 (BlockSwap offload)，否则 RAM 不释放
        for param in list(self.dit.parameters()):
            if param.numel() > 0:
                # 将参数数据替换为空张量，释放原始内存
                param.data = torch.empty(0, dtype=param.dtype, device='cpu')
            param.grad = None
        for buffer in list(self.dit.buffers()):
            if buffer.numel() > 0:
                buffer.data = torch.empty(0, dtype=buffer.dtype, device='cpu')

        # 清除梯度
        self.dit.zero_grad(set_to_none=True)

        del self.dit
        self.dit = None

        # 强制释放所有缓存的内存 (CPU + GPU)
        _force_release_memory()
        if hasattr(torch._C, '_cuda_clearCublasWorkspaces'):
            torch._C._cuda_clearCublasWorkspaces()
        _log_memory("DiT销毁后")
        logger.info("DiT 模型已完全销毁，VRAM+RAM 已释放")

    def _destroy_vae(self):
        """完全销毁 VAE 模型，释放 RAM 和 VRAM

        关键: 必须同时释放 CPU 上的参数和 GPU 上的激活，
        否则 RAM 不会释放，多次推理后内存爆满。
        """
        if self.vae is None:
            return
        # 释放所有参数 (CPU + GPU)
        for param in list(self.vae.parameters()):
            if param.numel() > 0:
                param.data = torch.empty(0, dtype=param.dtype, device='cpu')
        for buffer in list(self.vae.buffers()):
            if buffer.numel() > 0:
                buffer.data = torch.empty(0, dtype=buffer.dtype, device='cpu')
        self.vae.zero_grad(set_to_none=True)
        del self.vae
        self.vae = None
        _force_release_memory()
        _log_memory("VAE销毁后")
        logger.info("VAE 模型已完全销毁，RAM+VRAM 已释放")

    async def unload_model(self) -> bool:
        """卸载模型释放显存"""
        try:
            # 清理 BlockSwap 状态
            if self._blockswap_active and self.dit is not None:
                cleanup_blockswap(self.dit)
                self._blockswap_active = False

            if self.dit is not None:
                # 清理 RoPE 缓存
                clear_rope_lru_caches(self.dit)
                release_model_memory(self.dit)
                del self.dit
                self.dit = None
            if self.vae is not None:
                release_model_memory(self.vae)
                del self.vae
                self.vae = None
            self.pos_emb = None
            self.neg_emb = None
            self.schedule = None
            self.sampling_timesteps = None
            self.sampler = None

            self._loaded = False
            self.model_size = None
            self.precision = None

            clear_memory(deep=True, force=True)
            _force_release_memory()

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
            "cfg_rescale": kwargs.get("cfg_rescale", 0.0),
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

        # 初始化 Tensor Cache Manager (RVRT inspired)
        tensor_cache = None
        try:
            from bin.integrated_app.optimization.cache_manager import get_cache_manager
            tensor_cache = get_cache_manager()
            tensor_cache.clear()  # 清理上次推理的缓存
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

            # 种子: -1 表示随机
            seed = inf["seed"]
            if seed == -1:
                import random
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

                # 颜色校正
                input_frames = rearrange(input_video, "c t h w -> t c h w") if input_video.ndim == 4 else rearrange(input_video[:, None], "c t h w -> t c h w")
                input_frames_cpu = input_frames[:sample.shape[0]].cpu()

                # 转换为 numpy 并应用颜色校正
                sample_np = sample.cpu().clip(-1, 1).mul_(0.5).add_(0.5).mul_(255).round().to(torch.uint8).numpy()
                input_np = input_frames_cpu.clip(-1, 1).mul_(0.5).add_(0.5).mul_(255).round().to(torch.uint8).numpy()

                restored_frames = []
                # Feature propagation: temporal consistency enhancement (Upscale-A-Video inspired)
                # 在相邻帧间传播特征，提升时间一致性
                temporal_propagator = None
                try:
                    from bin.integrated_app.optimization.temporal_processing import FeaturePropagation
                    temporal_propagator = FeaturePropagation(propagation_weight=0.2)
                except Exception as e:
                    logger.debug(f"FeaturePropagation init skipped: {e}")
                
                prev_frame = None
                for i in range(sample_np.shape[0]):
                    frame = sample_np[i].transpose(1, 2, 0)  # C H W -> H W C
                    ref = input_np[i].transpose(1, 2, 0)
                    if color_fix_method != "none":
                        frame = apply_color_correction(frame, ref, method=color_fix_method)
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

                clear_memory(deep=True, force=True)

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
                    # Processing statistics (quality metrics)
                    "processing_fps": total_frames / processing_time if processing_time > 0 else 0,
                    "avg_frame_time_ms": (processing_time / total_frames * 1000) if total_frames > 0 else 0,
                    "cfg_scale": cfg_scale,
                    "sample_steps": sample_steps,
                    "inference_mode": inf["inference_mode"],
                }
            )

        except InferenceCancelledError as e:
            # REFACTOR [E4-1]: 推理被取消，清理模型资源后返回
            logger.warning(f"视频推理被取消: {e}")
            self._destroy_dit()
            self._destroy_vae()
            clear_memory(deep=True, force=True)
            return RestoreResult(
                success=False,
                error="推理已被取消",
                processing_time=time.time() - start_time,
                metadata={"cancelled": True, "stage": e.detail.get("stage", "")},
            )
        except Exception as e:
            logger.error(f"视频修复失败: {e}", exc_info=True)
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
        sample = decoded[0]  # [C, T, H, W] or [C, H, W]

        # 处理时间维度: C T H W -> C H W (单帧图像)
        if sample.ndim == 4:
            sample = rearrange(sample, "c t h w -> t c h w")  # T C H W
            sample = sample[0]  # C H W

        # [-1, 1] -> [0, 1] -> [0, 255] -> uint8
        sample_float = sample.float() / 2 + 0.5
        sample_float = sample_float.clamp(0, 1)
        result_np = sample_float.permute(1, 2, 0).cpu().numpy()  # H W C
        result_np = (result_np * 255).clip(0, 255).astype(np.uint8)

        del sample, sample_float, decoded
        gc.collect()

        # 颜色校正
        ref_np = None
        if color_fix_method != "none":
            ref = input_video
            if ref.ndim == 4:  # C T H W
                ref = rearrange(ref, "c t h w -> t c h w")[0]  # C H W
            ref_float = ref.float() / 2 + 0.5  # C H W
            ref_float = ref_float.clamp(0, 1)
            ref_np = ref_float.permute(1, 2, 0).cpu().numpy()  # H W C
            ref_np = (ref_np * 255).clip(0, 255).astype(np.uint8)
            result_np = apply_color_correction(result_np, ref_np, method=color_fix_method)
            del ref_float
        elif input_video is not None:
            # 仍需 ref_np 用于 wavelet_reconstruction
            ref = input_video
            if ref.ndim == 4:
                ref = rearrange(ref, "c t h w -> t c h w")[0]
            ref_float = ref.float() / 2 + 0.5
            ref_float = ref_float.clamp(0, 1)
            ref_np = ref_float.permute(1, 2, 0).cpu().numpy()
            ref_np = (ref_np * 255).clip(0, 255).astype(np.uint8)
            del ref_float

        # 小波重建后处理 (DiffBIR inspired) - 提升锐度
        if ref_np is not None:
            try:
                from bin.integrated_app.optimization.post_processing import wavelet_reconstruction
                result_np = wavelet_reconstruction(result_np, ref_np, level=3, low_freq_weight=0.8)
            except Exception as e:
                logger.debug(f"wavelet_reconstruction skipped: {e}")

        del input_video, ref_np
        gc.collect()

        # 保存
        from PIL import Image as PILImage
        output_name = f"SeedVR2_{Path(image_path).stem}_000001.png"
        output_path = os.path.join(output_dir, output_name)
        PILImage.fromarray(result_np).save(output_path)

        # 计算输出统计
        mean_val = result_np.mean()
        std_val = result_np.std()
        logger.info(f"输出: {result_np.shape[1]}x{result_np.shape[0]}, Mean={mean_val:.1f}, Std={std_val:.1f}")
        logger.info(f"保存: {output_path}")

        del result_np
        clear_memory(deep=True, force=True)
        # 强制清空 CUDA 缓存，防止显存碎片化导致第二次推理 OOM
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
            if hasattr(torch._C, '_cuda_clearCublasWorkspaces'):
                torch._C._cuda_clearCublasWorkspaces()

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
                import random
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
            # REFACTOR [E4-1]: 推理被取消，清理模型资源后返回
            logger.warning(f"图像推理被取消: {e}")
            self._destroy_dit()
            self._destroy_vae()
            clear_memory(deep=True, force=True)
            return RestoreResult(
                success=False,
                error="推理已被取消",
                processing_time=time.time() - start_time,
                metadata={"cancelled": True, "stage": e.detail.get("stage", "")},
            )

        except MemoryError as e:
            logger.error(f"内存不足，紧急终止推理: {e}")
            self._destroy_dit()
            self._destroy_vae()
            clear_memory(deep=True, force=True)
            return RestoreResult(success=False, error=str(e), processing_time=time.time() - start_time)

        except Exception as e:
            logger.error(f"图像修复失败: {e}", exc_info=True)
            self._destroy_dit()
            self._destroy_vae()
            clear_memory(deep=True, force=True)
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
        return self._loaded

    def get_model_info(self) -> dict:
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
        """估算所需显存(MB)"""
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
        """加载 VAE YAML 配置"""
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
        """配置扩散组件 (schedule, timesteps, sampler)"""
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
        """
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

        if isinstance(scale, list):
            scale = torch.tensor(scale, device=self.device, dtype=dtype)
        if isinstance(shift, list):
            shift = torch.tensor(shift, device=self.device, dtype=dtype)

        latents = []
        for sample in samples:
            # sample: C T H W -> B C T H W
            batch = sample.unsqueeze(0).to(self.device, dtype)
            if hasattr(self.vae, "preprocess"):
                batch = self.vae.preprocess(batch)

            if encode_tiled:
                logger.info(f"VAE tiled 编码: tile_size={tile_size}, overlap={tile_overlap}")
                enc_result = self.vae.encode(
                    batch,
                    tiled=True,
                    tile_size=(tile_size, tile_size),
                    tile_overlap=(tile_overlap, tile_overlap),
                )
            else:
                enc_result = self.vae.encode(batch)

            # 提取 latent
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
        """
        vae_cfg = self._model_config["vae"]
        scale = vae_cfg.get("scaling_factor", DEFAULT_SCALING_FACTOR)
        shift = vae_cfg.get("shifting_factor", 0.0)
        dtype = getattr(torch, vae_cfg.get("dtype", "bfloat16"))

        # tiled VAE 配置 (默认值对齐 ComfyUI HD 工作流: decode_tiled=True, decode_tile_size=768)
        tiled_cfg = getattr(self, "_vae_tiled_config", {})
        decode_tiled = tiled_cfg.get("decode_tiled", True)
        tile_size = tiled_cfg.get("decode_tile_size", 768)
        tile_overlap = tiled_cfg.get("decode_tile_overlap", 128)

        if isinstance(scale, list):
            scale = torch.tensor(scale, device=self.device, dtype=dtype)
        if isinstance(shift, list):
            shift = torch.tensor(shift, device=self.device, dtype=dtype)

        samples = []
        for latent in latents:
            # latent: ... C -> B ... C
            batch = latent.unsqueeze(0).to(self.device, dtype)
            batch = batch / scale + shift
            batch = rearrange(batch, "b ... c -> b c ...")
            batch = batch.squeeze(2)

            if decode_tiled:
                gaussian_blend = tiled_cfg.get("gaussian_blend", False)
                logger.info(f"VAE tiled 解码: tile_size={tile_size}, overlap={tile_overlap}, gaussian_blend={gaussian_blend}")
                dec_result = self.vae.decode(
                    batch,
                    tiled=True,
                    tile_size=(tile_size, tile_size),
                    tile_overlap=(tile_overlap, tile_overlap),
                )

                # Gaussian 权重混合增强 (SCST/VEncancer inspired)
                # 如果 VAE hook 捕获到了 tile 输出，使用高斯权重重新混合
                # 以消除原生 tiled 拼接可能产生的接缝伪影
                if gaussian_blend and getattr(self.vae, '_last_tile_outputs', None):
                    from bin.integrated_app.optimization.vae_tiled_enhance import blend_tiles_gaussian
                    tile_outputs = self.vae._last_tile_outputs
                    tile_positions = self.vae._last_tile_positions
                    if tile_outputs and tile_positions:
                        output_h, output_w = dec_result.sample.shape[-2:]
                        sample = blend_tiles_gaussian(
                            tile_outputs, tile_positions,
                            (output_h, output_w),
                            self.vae._last_tile_size,
                            self.vae._last_tile_overlap,
                            device=self.device, dtype=dec_result.sample.dtype,
                        )
                        logger.info(f"VAE tiled: Gaussian 混合完成, {len(tile_outputs)} tiles")
                    else:
                        sample = dec_result.sample
                else:
                    sample = dec_result.sample
            else:
                dec_result = self.vae.decode(batch)
                sample = dec_result.sample
            if hasattr(self.vae, "postprocess"):
                sample = self.vae.postprocess(sample)
            samples.append(sample.squeeze(0))

        return samples

    # ------------------------------------------------------------------
    # 内部方法 - DiT 采样
    # ------------------------------------------------------------------

    def _get_text_embeds(self) -> dict:
        """获取文本嵌入"""
        if self.pos_emb is not None and self.neg_emb is not None:
            return {
                "texts_pos": [self.pos_emb.to(self.device)],
                "texts_neg": [self.neg_emb.to(self.device)],
            }
        else:
            # 使用零嵌入作为 fallback
            logger.warning("使用零文本嵌入")
            dummy = torch.zeros(1, TEXT_EMBED_DIM, device=self.device, dtype=torch.float16)
            return {
                "texts_pos": [dummy],
                "texts_neg": [dummy],
            }

    def _get_condition(self, latent: torch.Tensor, latent_blur: torch.Tensor,
                       task: str = "sr") -> torch.Tensor:
        """构建条件输入 (与 VideoDiffusionInfer.get_condition 一致)"""
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
        """时间步变换 (与 VideoDiffusionInfer.timestep_transform 一致)"""
        diff_cfg = self._model_config["diffusion"]
        if not diff_cfg.get("timesteps", {}).get("transform", False):
            return timesteps

        vae_cfg = self._model_config["vae"]
        vt = vae_cfg.get("temporal_downsample_factor", 4)
        # 从 VAE YAML 获取
        vs = DEFAULT_VAE_SPATIAL_DOWNSAMPLE  # spatial_downsample_factor

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
        try:
            with torch.no_grad(), torch.autocast("cuda", torch.bfloat16, enabled=(self.device == "cuda")):
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
                            cfg_scale
                            if (args.i + 1) / len(self.sampler.timesteps)
                            <= diff_cfg["cfg"].get("partial", 1)
                            else 1.0
                        ),
                        cfg_rescale=cfg_rescale,
                        restoration_guidance_scale=restoration_guidance_scale,
                        current_noisy=latents,
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
    ) -> torch.Tensor:
        """带 Restoration Guidance 的 DiT 生成步 (Vivid-VR inspired)

        在标准 CFG 基础上，额外约束输出与退化输入的一致性，
        使修复结果在保真度和真实感之间取得平衡。

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

        # Restoration Guidance (Vivid-VR inspired)
        if restoration_guidance_scale > 0:
            from bin.integrated_app.optimization.diffusion_sampling import RestorationGuidedSampling, RestorationGuidanceConfig

            sampler = RestorationGuidedSampling(RestorationGuidanceConfig(
                enabled=True,
                guidance_scale=restoration_guidance_scale,
            ))

            # 标准 CFG 结果
            cfg_result = classifier_free_guidance_dispatcher(
                pos=lambda: pos_output,
                neg=lambda: neg_output,
                scale=cfg_scale,
                rescale=cfg_rescale,
            )

            # 应用 Restoration Guidance: 将 CFG 结果向原始输入方向偏移
            restoration_term = current_noisy - args.x_t
            return cfg_result + restoration_guidance_scale * restoration_term

        # 标准 CFG (无 restoration guidance)
        return classifier_free_guidance_dispatcher(
            pos=lambda: pos_output,
            neg=lambda: neg_output,
            scale=cfg_scale,
            rescale=cfg_rescale,
        )

    # ------------------------------------------------------------------
    # 内部方法 - 视频处理辅助
    # ------------------------------------------------------------------

    def _build_video_transform(self, res_h: int, res_w: int) -> Compose:
        """构建视频预处理变换 (与官方一致)"""
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
        """视频帧数对齐 (与 cut_videos 一致)"""
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

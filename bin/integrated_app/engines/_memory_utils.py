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
- 严格内存监控: RAM 使用率超过 95% 立即终止推理
- 加载前预检: 确认可用内存至少为模型大小的 1.5 倍
- 分阶段销毁: DiT/VAE 用完立即完全销毁，释放 VRAM+RAM
- BlockSwap: transformer 块动态在 GPU/CPU 间交换，降低峰值显存
- Tiled VAE: 支持分块编解码，自动 tile size 推荐和 OOM 回退
- 推理取消: 支持在阶段切换点取消任务，避免资源泄漏
"""

import gc
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# 环境变量: 防止 diffusers/huggingface 尝试联网导致卡住
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import numpy as np
import torch
from einops import rearrange

try:
    import psutil

    _HAS_PSUTIL = True
except ImportError:
    psutil = None
    _HAS_PSUTIL = False

# 可选导入 - 视频读取
try:
    from torchvision.io.video import read_video  # noqa: F401

    _HAS_TORCHVISION_IO = True
except (ImportError, ModuleNotFoundError):
    read_video = None
    _HAS_TORCHVISION_IO = False

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import contextlib  # noqa: E402

from bin.integrated_app.engine_interface import RestoreEngine  # noqa: E402
from bin.integrated_app.optimization.gpu.memory_manager import (  # noqa: E402
    clear_memory,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 内存监控 (严格模式: 超 95% 立即终止模型)
# ---------------------------------------------------------------------------

_MEMORY_THRESHOLD = 0.95
"""内存使用率阈值 (95%)，超过此阈值立即终止模型加载/推理，防止系统卡死"""

_MEMORY_MIN_AVAILABLE_GB = 2.0
"""绝对可用内存下限 (GB)，低于此值同样终止推理"""

_MEMORY_SAMPLES = 3
"""多次采样次数: 超阈值后连续采样 N 次取最小值，避免瞬时峰值误判"""

_MEMORY_SAMPLE_INTERVAL = 0.2
"""多次采样间隔 (秒): 每次采样之间的等待时间"""

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


@dataclass
class SystemMemory:
    """系统内存信息数据类，统一 psutil 和 Windows 原生 API 的返回格式

    在 Windows 上优先使用 GlobalMemoryStatusEx API（包含 Standby List），
    在其他平台使用 psutil。
    """

    total: int
    """总物理内存 (bytes)"""
    available: int
    """可用内存 (bytes)，包含 Standby List"""
    used: int
    """已用内存 (bytes)"""
    percent: float
    """使用率 (0-100)"""


def _get_system_memory() -> SystemMemory:
    """获取系统内存信息，Windows 上优先使用原生 API

    解决 psutil 在 Windows 上 available 不含 Standby List 导致 percent 偏高的问题。
    GlobalMemoryStatusEx 的 ullAvailPhys 包含 Standby List，更接近任务管理器显示值。

    Returns:
        SystemMemory: 统一格式的内存信息
    """
    if sys.platform == "win32":
        native = _get_memory_info_native()
        if native:
            native_usage, native_avail_gb = native
            # 通过可用内存反推 total（避免再次调用 API）
            total_gb = native_avail_gb / (1.0 - native_usage) if native_usage < 1.0 else native_avail_gb
            return SystemMemory(
                total=int(total_gb * 1024**3),
                available=int(native_avail_gb * 1024**3),
                used=int((total_gb - native_avail_gb) * 1024**3),
                percent=native_usage * 100.0,
            )

    # 非 Windows 或 API 失败时 fallback 到 psutil
    mem = psutil.virtual_memory()
    return SystemMemory(total=mem.total, available=mem.available, used=mem.used, percent=mem.percent)


def _get_memory_info_native() -> tuple[float, float] | None:
    """通过 Windows GlobalMemoryStatusEx 获取更准确的内存使用率和可用内存

    psutil 在 Windows 上的 available 不含 Standby List（可回收缓存页），
    导致 percent 系统性偏高。此函数直接调用 Win32 API 获取 ullAvailPhys，
    该值包含 Standby List，更接近任务管理器显示的"可用"内存。

    Returns:
        (usage_percent, available_gb) 元组，非 Windows 平台返回 None
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        statex = MEMORYSTATUSEX()
        statex.dwLength = ctypes.sizeof(statex)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(statex)):
            total_gb = statex.ullTotalPhys / (1024**3)
            avail_gb = statex.ullAvailPhys / (1024**3)
            usage = 1.0 - (avail_gb / total_gb) if total_gb > 0 else 0.0
            return (usage, avail_gb)
    except Exception:
        pass
    return None


def _load_memory_config() -> tuple[float, float]:
    """从 config.yaml 加载内存检测配置

    Returns:
        (threshold, min_available_gb) 元组，读取失败返回默认值
    """
    try:
        from bin.integrated_app.config import get_app_config

        cfg = get_app_config()
        return (cfg.inference.memory_threshold, cfg.inference.memory_min_available_gb)
    except Exception:
        return (_MEMORY_THRESHOLD, _MEMORY_MIN_AVAILABLE_GB)


def _log_memory_diagnostics() -> None:
    """记录详细的内存分解信息，用于超阈值时的诊断"""
    if not _HAS_PSUTIL:
        return
    try:
        mem = _get_system_memory()
        logger.warning(
            f"[内存诊断] 系统RAM: 总计={mem.total/1024**3:.1f}GB, "
            f"可用={mem.available/1024**3:.1f}GB, "
            f"已用={mem.used/1024**3:.1f}GB, "
            f"使用率={mem.percent:.1f}%"
        )

        process = psutil.Process()
        rss_gb = process.memory_info().rss / (1024**3)
        logger.warning(f"[内存诊断] 当前进程RSS: {rss_gb:.2f}GB")

        if torch.cuda.is_available():
            vram_alloc = torch.cuda.memory_allocated(0) / 1024**3
            vram_resv = torch.cuda.memory_reserved(0) / 1024**3
            logger.warning(f"[内存诊断] GPU显存: 已分配={vram_alloc:.2f}GB, 已保留={vram_resv:.2f}GB")

        top_procs = []
        for proc in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                rss = proc.info["memory_info"].rss / (1024**3)
                top_procs.append((proc.info["name"], proc.info["pid"], rss))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        top_procs.sort(key=lambda x: x[2], reverse=True)
        for name, pid, rss in top_procs[:5]:
            logger.warning(f"[内存诊断] Top进程: {name}(PID={pid}) RSS={rss:.2f}GB")

    except Exception as e:
        logger.debug(f"[内存诊断] 诊断信息获取失败: {e}")


def _check_memory(threshold: float | None = None, force_cleanup: bool = True) -> float:
    """检查系统内存使用率，超过阈值立即清理并抛出异常

    改进策略:
    1. 可配置阈值: 从 config.yaml 读取，支持运行时调整
    2. Windows 原生 API: 使用 GlobalMemoryStatusEx 获取更准确的可用内存
    3. 多次采样: 超阈值后连续采样 3 次取最小值，避免瞬时峰值误判
    4. 绝对下限: 可用内存 < memory_min_available_gb 时同样终止
    5. 详细诊断: 超阈值时自动记录内存分解信息

    Args:
        threshold: 内存使用率阈值 (0-1)，None 则从 config.yaml 读取
        force_cleanup: 是否在超阈值时强制清理所有模型

    Returns:
        当前内存使用率 (0-1)

    Raises:
        MemoryError: 内存使用率超过阈值
    """
    if not _HAS_PSUTIL:
        return 0.0

    cfg_threshold, cfg_min_avail = _load_memory_config()
    if threshold is None:
        threshold = cfg_threshold

    mem = _get_system_memory()
    usage = mem.percent / 100.0
    available_gb = mem.available / (1024**3)

    if usage > threshold or available_gb < cfg_min_avail:
        reason = (
            f"使用率 {usage:.1%} > 阈值 {threshold:.0%}"
            if usage > threshold
            else f"可用 {available_gb:.1f}GB < 下限 {cfg_min_avail:.1f}GB"
        )
        logger.warning(f"[内存] 超过阈值 ({reason})，执行清理后重试...")

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        gc.collect()
        _force_release_memory()

        best_usage = usage
        for i in range(_MEMORY_SAMPLES):
            time.sleep(_MEMORY_SAMPLE_INTERVAL)
            sample_mem = _get_system_memory()
            sample_usage = sample_mem.percent / 100.0

            if sample_usage < best_usage:
                best_usage = sample_usage
            logger.debug(f"[内存] 采样 {i+1}/{_MEMORY_SAMPLES}: " f"使用率={sample_usage:.1%}, 最佳={best_usage:.1%}")

        final_mem = _get_system_memory()
        available_gb = final_mem.available / (1024**3)

        if best_usage > threshold or available_gb < cfg_min_avail:
            _log_memory_diagnostics()
            raise MemoryError(
                f"内存使用率 {best_usage:.1%} 超过阈值 {threshold:.0%}，"
                f"可用: {available_gb:.1f}GB / {final_mem.total/1024**3:.1f}GB。"
                f"必须立即终止模型！"
            )

        logger.info(f"[内存] 清理后恢复: 使用率={best_usage:.1%}, 可用={available_gb:.1f}GB")

    return usage


def _estimate_model_size_gb(checkpoint_path: str) -> float:
    """估算模型文件大小 (GB)"""
    try:
        size_bytes = os.path.getsize(checkpoint_path)
        return size_bytes / (1024**3)
    except OSError:
        return 0.0


def _check_memory_before_load(checkpoint_path: str, label: str = "模型") -> None:
    """加载模型前检查是否有足够内存

    估算模型大小并检查当前可用内存是否足够。
    如果可用内存不足模型大小的 1.5 倍 (考虑 dtype 转换开销)，抛出异常。
    使用可配置阈值和统一内存获取函数提高准确性。

    Args:
        checkpoint_path: 模型文件路径
        label: 模型标签 (用于日志)

    Raises:
        MemoryError: 可用内存不足
    """
    if not _HAS_PSUTIL:
        return

    cfg_threshold, cfg_min_avail = _load_memory_config()
    model_size_gb = _estimate_model_size_gb(checkpoint_path)
    mem = _get_system_memory()
    available_gb = mem.available / (1024**3)
    usage = mem.percent / 100.0

    required_gb = model_size_gb * 1.5

    logger.info(
        f"[内存预检] {label}: 文件={model_size_gb:.2f}GB, "
        f"需要>={required_gb:.1f}GB, 可用={available_gb:.1f}GB, "
        f"当前使用率={usage:.1%}"
    )

    if usage > cfg_threshold:
        raise MemoryError(
            f"内存使用率 {usage:.1%} 已超过阈值 {cfg_threshold:.0%}，"
            f"无法加载 {label} ({model_size_gb:.2f}GB)。"
            f"可用: {available_gb:.1f}GB"
        )

    if available_gb < cfg_min_avail:
        raise MemoryError(
            f"可用内存 {available_gb:.1f}GB 低于下限 {cfg_min_avail:.1f}GB，"
            f"无法加载 {label} ({model_size_gb:.2f}GB)。"
            f"当前使用率: {usage:.1%}"
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
            mem = _get_system_memory()
            ram_info = f"RAM: {mem.percent:.0f}% ({mem.available/1024**3:.1f}GB可用/{mem.total/1024**3:.1f}GB)"
        else:
            ram_info = "RAM: N/A"
        vram_alloc = torch.cuda.memory_allocated(0) / 1024**3 if torch.cuda.is_available() else 0
        vram_resv = torch.cuda.memory_reserved(0) / 1024**3 if torch.cuda.is_available() else 0
        logger.info(f"[内存{tag}] {ram_info}, " f"VRAM: {vram_alloc:.2f}GB使用/{vram_resv:.2f}GB保留")
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

        if platform.system() == "Windows":
            ctypes.CDLL("msvcrt")._heapmin()
        else:
            ctypes.CDLL("libc.so.6").malloc_trim(0)
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

    if hasattr(torch._C, "_cuda_clearCublasWorkspaces"):
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
    return tensor.float().clamp(-1, 1).mul(0.5).add(0.5).mul(255).round().to(torch.uint8).cpu().numpy()


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
            target_area = self.resolution**2
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
    cache_model: bool = False
    torch_compile: dict = field(default_factory=dict)

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
            # BlockSwap 相关参数在 config.yaml 的 inference 段，勿从 model 段读取
            "blocks_to_swap": infer_cfg.get("blocks_to_swap", 32),
            "swap_io_components": infer_cfg.get("swap_io_components", True),
            "dit_offload_device": infer_cfg.get("offload_device", "cpu"),
            "dit_cache_model": infer_cfg.get("cache_model", True),
            "attention_mode": infer_cfg.get("attention_mode", "sdpa"),
            "encode_tiled": vae_cfg.get("encode_tiled", True),
            "encode_tile_size": vae_cfg.get("encode_tile_size", 1024),
            "encode_tile_overlap": vae_cfg.get("encode_tile_overlap", 512),
            "decode_tiled": vae_cfg.get("decode_tiled", True),
            "decode_tile_size": vae_cfg.get("decode_tile_size", 1024),
            "decode_tile_overlap": vae_cfg.get("decode_tile_overlap", 512),
            "tile_debug": vae_cfg.get("tile_debug", "false"),
            "vae_offload_device": vae_cfg.get("offload_device", "cpu"),
            "vae_cache_model": infer_cfg.get("cache_model", vae_cfg.get("cache_model", True)),
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
            "cache_model": infer_cfg.get("cache_model", False),
            "torch_compile": infer_cfg.get("torch_compile", {}),
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
    - 内存安全: 95% 阈值监控、加载前预检、推理取消机制
    - 后处理增强: LAB颜色校正、小波重建、锐化、文本修复、EXIF复制

    推理模式:
    - 蒸馏模式 (distilled): cfg_scale=1.0, steps=1, 配合噪声增强实现快速推理
    - 标准模式 (standard): cfg_scale=7.5, steps=50, Euler采样 + Classifier-Free Guidance

    Args:
        config (dict): 应用配置字典，包含 model、inference、postprocessing 等段
    """

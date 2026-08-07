"""GPU 显存检测与 OOM 预防工具模块 - SeedVR2 视频修复项目

本模块提供 GPU 显存查询、模型显存估算、缓存清理和 OOM 保护装饰器等工具函数，
是显存管理的底层工具集，为上层模块（模型管理器、内存管理器等）提供基础能力。

所属项目: SeedVR2 (基于 ComfyUI-SeedVR2_VideoUpscaler 独立重构)
核心技术栈: PyTorch CUDA API, psutil, functools, garbage collection

主要功能:
    - GPU 显存实时监控（总显存、已分配、已保留、可用、利用率）
    - 系统内存信息查询
    - 模型加载显存需求估算（考虑模型大小、精度、分辨率）
    - GPU 缓存清理与强制垃圾回收
    - OOM 保护装饰器（捕获显存不足异常并自动清理）
    - 完整系统信息聚合（GPU + 内存 + OS）

常量说明:
    显存估算常量集中管理，避免魔法数字散落在代码中。
    TODO: 未来应从 config.yaml 注入，保持单一数据源。
"""

import functools
import gc
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

# 模块级一次性导入 torch，避免每次函数调用都重新导入
# torch 不可用时优雅降级
try:
    import torch

    _HAS_TORCH_CUDA = torch.cuda.is_available()
except ImportError:
    torch = None  # type: ignore[assignment]
    _HAS_TORCH_CUDA = False

# ===========================================================================
# 显存估算常量 — 消除魔法数字，集中管理
# ===========================================================================
# TODO: 这些估值应与 config.yaml 中 models.*.min_vram_fp16_gb / min_vram_fp8_gb 对齐，
#       当前为独立硬编码，未来应从 config 注入以保持单一数据源 (F1)
_BASE_VRAM_MB = {
    "3b": {"fp16": 8000, "fp8": 4000},  # 3B 模型约需 8GB(FP16) / 4GB(FP8) 基础显存
    "7b": {"fp16": 16000, "fp8": 8000},  # 7B 模型约需 16GB(FP16) / 8GB(FP8) 基础显存
}
_DEFAULT_MODEL_VRAM_MB = {"fp16": 8000, "fp8": 4000}  # 未知模型大小的默认估值
_BASE_RESOLUTION_PIXELS = 1080 * 1920  # 基准分辨率（用于计算像素比例因子）
_BASE_INFERENCE_VRAM_MB = 4000  # 推理额外显存基线（4GB 起，随分辨率线性增长）


def get_gpu_memory_info() -> dict:
    """获取 GPU 显存详细信息（使用 mem_get_info 获取实际可用显存）

    使用 PyTorch CUDA API 查询设备 0 的显存状态，区分已分配（allocated）、
    已保留（reserved）和实际可用（free）三种状态。

    Returns:
        dict: 包含以下键的显存信息字典：
            - total_mb (int): 总显存（MB）
            - allocated_mb (int): PyTorch 已分配显存（MB，张量实际占用）
            - reserved_mb (int): PyTorch 已保留显存（MB，缓存分配器管理）
            - available_mb (int): 实际可用显存（MB，通过 mem_get_info 获取）
            - utilization_pct (float): 显存利用率百分比（0-100）

        查询失败时返回全 0 的默认字典。
    """
    try:
        if _HAS_TORCH_CUDA:
            # mem_get_info 返回 (free, total)，反映驱动层面实际可用显存
            free_memory, total_memory = torch.cuda.mem_get_info(0)
            allocated = torch.cuda.memory_allocated(0)
            reserved = torch.cuda.memory_reserved(0)
            used = total_memory - free_memory

            return {
                "total_mb": total_memory // (1024 * 1024),
                "allocated_mb": allocated // (1024 * 1024),
                "reserved_mb": reserved // (1024 * 1024),
                "available_mb": free_memory // (1024 * 1024),
                "utilization_pct": (used / total_memory) * 100 if total_memory > 0 else 0,
            }
    except Exception as e:
        logger.error(f"获取 GPU 显存信息失败: {e}")

    return {
        "total_mb": 0,
        "allocated_mb": 0,
        "reserved_mb": 0,
        "available_mb": 0,
        "utilization_pct": 0,
    }


def check_vram_available(required_mb: int) -> tuple[bool, int]:
    """检查是否有足够的可用显存

    Args:
        required_mb: 需要的显存大小（MB）

    Returns:
        tuple[bool, int]: (是否足够, 当前可用显存MB)
            - 第一个元素：可用显存 >= required_mb 时为 True
            - 第二个元素：当前实际可用显存（MB）
    """
    info = get_gpu_memory_info()
    available = info["available_mb"]
    return available >= required_mb, available


def estimate_model_vram(model_size: str, resolution: tuple | None = None, precision: str = "fp16") -> int:
    """估算模型加载和推理所需的总显存（MB）

    显存估算公式：
        总显存 = 模型权重显存 + 推理额外显存
        - 模型权重显存：根据模型大小和精度查表（_BASE_VRAM_MB）
        - 推理额外显存：与分辨率像素数成正比（相对于 1080x1920 基准）
          推理显存 = BASE_INFERENCE_VRAM_MB * max(1.0, pixel_factor)

    Args:
        model_size: 模型大小标识，支持 "3b" / "7b"
        resolution: 目标分辨率 (height, width) 元组；为 None 时仅计算权重显存
        precision: 计算精度，支持 "fp16" / "fp8"

    Returns:
        int: 估算的总显存需求（MB）
    """
    # 查表获取模型基础显存需求
    model_vram = _BASE_VRAM_MB.get(model_size, _DEFAULT_MODEL_VRAM_MB)
    base_vram = model_vram.get(precision, model_vram["fp16"])

    if resolution:
        h, w = resolution
        # 推理额外显存与像素数成正比：高分辨率需要更多中间激活显存
        pixel_factor = (h * w) / _BASE_RESOLUTION_PIXELS
        inference_vram = int(_BASE_INFERENCE_VRAM_MB * max(1.0, pixel_factor))
        return base_vram + inference_vram

    return base_vram


def clear_gpu_cache():
    """清理 GPU 显存缓存

    调用 torch.cuda.empty_cache() 释放 PyTorch 缓存分配器持有的未使用显存，
    归还给 CUDA 驱动。不会释放正在使用的张量显存。

    注意：这不会减少 torch.cuda.memory_allocated() 的显示值，
    但会增加 torch.cuda.mem_get_info() 报告的可用显存。
    """
    try:
        if _HAS_TORCH_CUDA:
            torch.cuda.empty_cache()
            logger.info("GPU 缓存已清理")
    except Exception as e:
        logger.error(f"GPU 缓存清理失败: {e}")


def force_garbage_collect():
    """强制进行 Python 垃圾回收并清理 GPU 缓存

    执行完整的二级清理流程：
        1. gc.collect()：回收 Python 层不可达对象，释放其持有的张量引用
        2. clear_gpu_cache()：释放 CUDA 缓存分配器的空闲显存

    通常在 OOM 后或模型卸载后调用，最大化显存回收。
    """
    gc.collect()
    clear_gpu_cache()


def oom_protect(func: Callable) -> Callable:
    """OOM 保护装饰器 - 异步函数显存不足自动捕获与恢复

    为异步推理函数提供显存异常保护：
        1. 捕获 RuntimeError 中包含 "out of memory" 或 "CUDA" 的异常
        2. 自动执行垃圾回收和 GPU 缓存清理
        3. 转换为友好的 MemoryError 并抛出，附带用户解决建议
        4. 非 OOM 异常原样抛出

    Args:
        func: 被装饰的异步函数

    Returns:
        Callable: 包装后的异步函数

    Raises:
        MemoryError: 捕获到 CUDA OOM 时抛出，包含解决建议信息
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except RuntimeError as e:
            if "out of memory" in str(e).lower() or "CUDA" in str(e):
                logger.error(f"GPU 显存不足: {e}")
                # OOM 后立即强制清理，尽可能回收显存
                force_garbage_collect()
                raise MemoryError(
                    "GPU 显存不足，请尝试：\n" "1. 切换到 3B 模型\n" "2. 降低输出分辨率\n" "3. 关闭其他占用显存的程序"
                ) from e
            raise
        except Exception as e:
            logger.error(f"推理执行失败: {e}")
            raise

    return wrapper


def get_system_memory_info() -> dict:
    """获取系统内存（RAM）信息

    使用 psutil 查询系统虚拟内存状态。

    Returns:
        dict: 包含以下键的内存信息字典：
            - total_mb (int): 总物理内存（MB）
            - available_mb (int): 可用内存（MB）
            - used_mb (int): 已用内存（MB）
            - utilization_pct (float): 内存利用率百分比（0-100）

        psutil 不可用时返回全 0 默认字典。
    """
    try:
        from bin.integrated_app.engines._memory_utils import _get_system_memory

        mem = _get_system_memory()
        return {
            "total_mb": mem.total // (1024 * 1024),
            "available_mb": mem.available // (1024 * 1024),
            "used_mb": mem.used // (1024 * 1024),
            "utilization_pct": mem.percent,
        }
    except Exception:
        return {
            "total_mb": 0,
            "available_mb": 0,
            "used_mb": 0,
            "utilization_pct": 0,
        }


def get_full_system_info() -> dict:
    """获取完整系统信息（GPU + 内存 + 操作系统）

    聚合 GPU 显存、系统内存、OS 版本、Python 版本等信息，
    用于系统状态展示和问题诊断。

    Returns:
        dict: 包含以下键的系统信息字典：
            - os (str): 操作系统名称（Windows/Linux/Darwin）
            - os_version (str): 操作系统版本号
            - processor (str): 处理器信息
            - python_version (str): Python 版本号
            - gpu (dict): GPU 显存信息（来自 get_gpu_memory_info）
            - memory (dict): 系统内存信息（来自 get_system_memory_info）
    """
    gpu_info = get_gpu_memory_info()
    mem_info = get_system_memory_info()

    import platform

    return {
        "os": platform.system(),
        "os_version": platform.version(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "gpu": gpu_info,
        "memory": mem_info,
    }

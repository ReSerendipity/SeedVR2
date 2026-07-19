"""GPU 显存检测与 OOM 预防工具（仅支持 NVIDIA CUDA GPU）"""
import functools
import gc
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# A4: 显存估算常量 — 消除魔法数字，集中管理
# ---------------------------------------------------------------------------
# TODO: 这些估值应与 config.yaml 中 models.*.min_vram_fp16_gb / min_vram_fp8_gb 对齐，
#       当前为独立硬编码，未来应从 config 注入以保持单一数据源 (F1)
_BASE_VRAM_MB = {
    "3b": {"fp16": 8000, "fp8": 4000},   # 3B 模型约需 8GB(FP16) / 4GB(FP8)
    "7b": {"fp16": 16000, "fp8": 8000},  # 7B 模型约需 16GB(FP16) / 8GB(FP8)
}
_DEFAULT_MODEL_VRAM_MB = {"fp16": 8000, "fp8": 4000}  # 未知模型大小的默认估值
_BASE_RESOLUTION_PIXELS = 1080 * 1920  # 基准分辨率（用于计算像素比例因子）
_BASE_INFERENCE_VRAM_MB = 4000         # 推理额外显存基线（4GB 起，随分辨率线性增长）


def get_gpu_memory_info() -> dict:
    """获取 GPU 显存信息（使用 mem_get_info 获取实际可用显存）"""
    try:
        import torch
        if torch.cuda.is_available():
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
    """检查是否有足够的显存可用

    Returns:
        (is_available, available_mb)
    """
    info = get_gpu_memory_info()
    available = info["available_mb"]
    return available >= required_mb, available


def estimate_model_vram(model_size: str, resolution: tuple = None, precision: str = "fp16") -> int:
    """估算模型加载所需显存(MB)

    Args:
        model_size: 模型大小 (3b/7b)
        resolution: 目标分辨率 (h, w)
        precision: 精度 (fp16/fp8)
    """
    # A4: 使用命名常量替代魔法数字
    model_vram = _BASE_VRAM_MB.get(model_size, _DEFAULT_MODEL_VRAM_MB)
    base_vram = model_vram.get(precision, model_vram["fp16"])

    if resolution:
        h, w = resolution
        # 推理时额外显存需求与分辨率成正比
        pixel_factor = (h * w) / _BASE_RESOLUTION_PIXELS
        inference_vram = int(_BASE_INFERENCE_VRAM_MB * max(1.0, pixel_factor))
        return base_vram + inference_vram

    return base_vram


def clear_gpu_cache():
    """清理 GPU 缓存"""
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            logger.info("GPU 缓存已清理")
    except Exception as e:
        logger.error(f"GPU 缓存清理失败: {e}")


def force_garbage_collect():
    """强制垃圾回收"""
    gc.collect()
    clear_gpu_cache()


def oom_protect(func: Callable) -> Callable:
    """OOM 保护装饰器 - 在函数执行前检查显存，失败后自动清理"""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except RuntimeError as e:
            if "out of memory" in str(e).lower() or "CUDA" in str(e):
                logger.error(f"GPU 显存不足: {e}")
                force_garbage_collect()
                raise MemoryError(
                    "GPU 显存不足，请尝试：\n"
                    "1. 切换到 3B 模型\n"
                    "2. 降低输出分辨率\n"
                    "3. 关闭其他占用显存的程序"
                ) from e
            raise
        except Exception as e:
            logger.error(f"推理执行失败: {e}")
            raise

    return wrapper


def get_system_memory_info() -> dict:
    """获取系统内存信息"""
    try:
        import psutil
        mem = psutil.virtual_memory()
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
    """获取完整系统信息（GPU + 内存）"""
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

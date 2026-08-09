"""VRAM/内存管理模块 - SeedVR2 视频修复项目

本模块负责 GPU 显存（VRAM）和系统内存（RAM）的监控、清理与模型设备调度，
是显存优化体系的核心组件，支持 BlockSwap 感知的模型设备管理。

所属项目: SeedVR2 (基于 ComfyUI-SeedVR2_VideoUpscaler 独立重构，已移除 ComfyUI 依赖)
核心技术栈: PyTorch CUDA API, psutil, gc, ctypes (OS 内存操作)

主要功能:
    - VRAM 基础信息查询（可用/总显存，GB 单位）
    - VRAM 使用指标监控（已分配/已保留/峰值）
    - 进程 RAM 使用监控（进程内存/可用内存/其他进程占用）
    - 两级内存清理策略（最小清理 vs 深度清理）
    - BlockSwap 感知的模型设备迁移（普通模型与 BlockSwap 模型区别处理）
    - 张量和模型内存原地释放（无需 CPU 传输）
    - RoPE LRU 缓存清理

关键约束:
    - SeedVR2 仅支持 NVIDIA CUDA GPU，不支持 CPU/MPS 推理
    - I/O 组件（embedding、norm 等）不应被卸载到 CPU（可配置）
    - 内存超过 90% 时必须立即终止相关推理
"""

import gc
import logging
import sys
from typing import Any

import psutil
import torch

logger = logging.getLogger(__name__)


def _device_str(device: torch.device | str) -> str:
    """将设备对象或字符串转换为大写标准化字符串用于比较和日志

    Args:
        device: torch.device 对象或设备字符串（如 "cuda:0", "cpu"）

    Returns:
        str: 大写的设备字符串（如 "CUDA:0", "CPU"）
    """
    return str(device).upper()


def is_cuda_available() -> bool:
    """检查 CUDA 后端是否可用

    Returns:
        bool: CUDA 可用返回 True，否则返回 False
    """
    return torch.cuda.is_available()


def _get_default_device() -> torch.device:
    """获取当前默认 CUDA 设备，支持多 GPU 环境

    使用 torch.cuda.current_device() 获取当前活跃设备，而非硬编码 cuda:0

    Returns:
        torch.device: 当前默认 CUDA 设备
    """
    return torch.device(f"cuda:{torch.cuda.current_device()}")


def _normalize_device(device: torch.device | str | None) -> torch.device:
    """标准化设备参数，None 时使用当前默认设备

    Args:
        device: 设备对象、字符串或 None

    Returns:
        torch.device: 标准化后的 torch.device 对象
    """
    if device is None:
        return _get_default_device()
    if isinstance(device, torch.device):
        return device
    return torch.device(device)


# ===========================================================================
# VRAM / RAM 监控
# ===========================================================================


def get_basic_vram_info(device: torch.device | None = None) -> dict[str, Any]:
    """获取 GPU 基础显存信息（可用和总显存）

    Args:
        device: 要查询的设备，None 时默认使用当前 CUDA 设备

    Returns:
        dict: 查询成功时返回 {"free_gb": float, "total_gb": float}，
              失败或 CUDA 不可用时返回 {"error": str} 错误信息
    """
    try:
        if is_cuda_available():
            device = _normalize_device(device)
            free_memory, total_memory = torch.cuda.mem_get_info(device)
        else:
            # CONSTRAINT: SeedVR2 仅支持 NVIDIA CUDA GPU，不支持 CPU/MPS 推理
            return {"error": "No CUDA GPU backend available"}

        return {"free_gb": free_memory / (1024**3), "total_gb": total_memory / (1024**3)}
    except Exception as e:
        return {"error": f"Failed to get memory info: {str(e)}"}


def get_vram_usage(device: torch.device | None = None) -> tuple[float, float, float, float]:
    """获取当前 VRAM 使用指标，用于监控和调试

    Args:
        device: 要查询的设备，None 时默认使用当前 CUDA 设备

    Returns:
        tuple[float, float, float, float]:
            (allocated_gb, reserved_gb, peak_allocated_gb, peak_reserved_gb)
            - allocated_gb: PyTorch 已分配的显存（GB，张量实际占用）
            - reserved_gb: PyTorch 缓存分配器已保留的显存（GB）
            - peak_allocated_gb: 本次进程生命周期内已分配显存峰值（GB）
            - peak_reserved_gb: 本次进程生命周期内已保留显存峰值（GB）

        查询失败时返回 (0.0, 0.0, 0.0, 0.0)
    """
    try:
        if is_cuda_available():
            device = _normalize_device(device)
            allocated = torch.cuda.memory_allocated(device) / (1024**3)
            reserved = torch.cuda.memory_reserved(device) / (1024**3)
            peak_allocated = torch.cuda.max_memory_allocated(device) / (1024**3)
            peak_reserved = torch.cuda.max_memory_reserved(device) / (1024**3)
            return allocated, reserved, peak_allocated, peak_reserved
    except Exception as e:
        logger.warning(f"Failed to get VRAM usage: {e}")
    return 0.0, 0.0, 0.0, 0.0


def get_ram_usage() -> tuple[float, float, float, float]:
    """获取当前进程和系统的 RAM 使用指标

    区分当前进程占用的内存和其他进程占用的内存，帮助判断内存压力来源。

    Returns:
        tuple[float, float, float, float]:
            (process_gb, available_gb, total_gb, used_by_others_gb)
            - process_gb: 当前进程占用的物理内存（GB，RSS）
            - available_gb: 系统可用内存（GB）
            - total_gb: 系统总物理内存（GB）
            - used_by_others_gb: 其他进程占用的内存（GB）

        查询失败时返回 (0.0, 0.0, 0.0, 0.0)
    """
    try:
        process = psutil.Process()
        process_memory = process.memory_info()
        process_gb = process_memory.rss / (1024**3)

        from bin.integrated_app.engines._memory_utils import _get_system_memory

        sys_memory = _get_system_memory()
        total_gb = sys_memory.total / (1024**3)
        available_gb = sys_memory.available / (1024**3)

        total_used_gb = total_gb - available_gb
        used_by_others_gb = max(0, total_used_gb - process_gb)

        return process_gb, available_gb, total_gb, used_by_others_gb
    except Exception as e:
        logger.warning(f"Failed to get RAM usage: {e}")
        return 0.0, 0.0, 0.0, 0.0


# ===========================================================================
# 内存清理
# ===========================================================================

# OS 内存库全局缓存（延迟初始化一次）
_os_memory_lib = None


def clear_memory(deep: bool = False, force: bool = True) -> None:
    """两级策略清理内存缓存，平衡清理效果与性能开销

    根据 VRAM/RAM 压力决定是否执行清理，支持最小清理和深度清理两种模式：
        - 最小模式（deep=False）：仅 GPU 缓存操作（约 1-5ms）
        - 深度模式（deep=True）：完整清理，含 Python GC 和 OS 内存归还（约 10-50ms）

    Args:
        force: 是否强制执行清理
            - True：始终执行清理（默认）
            - False：仅当空闲显存/内存 < 5% 时才清理
        deep: 是否执行深度清理
            - False（默认）：仅执行 GPU empty_cache + ipc_collect
            - True：额外执行 gc.collect() 和 OS 级内存归还（malloc_trim/SetProcessWorkingSetSize）
    """
    global _os_memory_lib

    # 非强制模式：检查内存压力，低于 5% 空闲才清理
    if not force:
        should_clear = False

        mem_info = get_basic_vram_info(device=None)

        if "error" not in mem_info and mem_info["total_gb"] > 0:
            free_ratio = mem_info["free_gb"] / mem_info["total_gb"]
            if free_ratio < 0.05:
                should_clear = True

        if not should_clear:
            from bin.integrated_app.engines._memory_utils import _get_system_memory

            mem = _get_system_memory()
            if mem.available < mem.total * 0.05:
                should_clear = True

        if not should_clear:
            return

    # ===== 最小清理操作（始终执行）=====
    if is_cuda_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()

    # ===== 深度清理操作（仅 deep=True 时执行）=====
    if deep:
        gc.collect()

        try:
            if sys.platform == "linux":
                import ctypes

                if _os_memory_lib is None:
                    _os_memory_lib = ctypes.CDLL("libc.so.6")
                _os_memory_lib.malloc_trim(0)

            elif sys.platform == "win32":
                import ctypes

                if _os_memory_lib is None:
                    _os_memory_lib = ctypes.windll.kernel32
                handle = _os_memory_lib.GetCurrentProcess()
                _os_memory_lib.SetProcessWorkingSetSize(handle, -1, -1)
        except Exception as e:
            logger.warning(f"Failed to perform OS memory operations: {e}")


def reset_vram_peak(device: torch.device | None = None) -> None:
    """重置 VRAM 峰值统计，用于新一次推理前的基线追踪

    Args:
        device: 要重置的设备，None 时默认使用当前 CUDA 设备
    """
    try:
        if is_cuda_available():
            device = _normalize_device(device)
            torch.cuda.reset_peak_memory_stats(device)
    except Exception as e:
        logger.warning(f"Failed to reset peak memory stats: {e}")


# ===========================================================================
# 模型设备管理
# ===========================================================================


def manage_model_device(
    model: torch.nn.Module,
    target_device: torch.device,
    model_name: str = "Model",
    reason: str | None = None,
) -> bool:
    """将模型迁移到目标设备，支持 BlockSwap 感知的特殊处理

    如果模型启用了 BlockSwap（model._blockswap_active = True），
    则采用特殊的迁移流程以保留 BlockSwap 配置：
        - 卸载到 CPU 时：临时绕过保护，整体迁移后保留配置
        - 加载回 GPU 时：按 BlockSwap 配置恢复 blocks 和 I/O 组件的设备分布

    Args:
        model: 要迁移的 PyTorch 模型
        target_device: 目标设备（torch.device 对象）
        model_name: 用于日志的模型名称（如 "VAE", "DiT"）
        reason: 可选的迁移原因说明，用于日志

    Returns:
        bool: 模型被实际迁移返回 True，已在目标设备或无需迁移返回 False
    """
    if model is None:
        return False

    try:
        current_device = next(model.parameters()).device
    except StopIteration:
        return False

    if current_device.type == "meta":
        logger.info(f"{model_name} is on meta device - skipping movement")
        return False

    is_blockswap_model = getattr(model, "_blockswap_active", False)
    same_device = current_device.type == target_device.type

    if same_device and not is_blockswap_model:
        return False

    if is_blockswap_model:
        return _handle_blockswap_model_movement(model, target_device, model_name, reason)

    return _standard_model_movement(model, current_device, target_device, model_name, reason)


def _handle_blockswap_model_movement(
    model: torch.nn.Module,
    target_device: torch.device,
    model_name: str,
    reason: str | None = None,
) -> bool:
    """处理 BlockSwap 启用模型的设备迁移（内部函数）

    BlockSwap 模型的迁移策略：
        - 迁移到 CPU（卸载）：启用 bypass，整体移动到卸载设备，zero_grad
        - 迁移到 GPU（恢复）：检查保护标志，按配置恢复 blocks 和 I/O 组件的设备分布，
          重新激活 BlockSwap，禁用 bypass

    Args:
        model: BlockSwap 模型
        target_device: 目标设备
        model_name: 模型名称（日志用）
        reason: 迁移原因

    Returns:
        bool: 执行了迁移返回 True，否则返回 False

    Raises:
        ValueError: BlockSwap 配置缺少 offload_device 时抛出
    """
    from .blockswap import set_blockswap_bypass

    if target_device.type == "cpu":
        reason = reason or "model offloading"
        logger.info(f"Moving {model_name} to {_device_str(target_device)} ({reason})")

        set_blockswap_bypass(model, bypass=True)
        model.to(target_device)
        model.zero_grad(set_to_none=True)

        return True

    if not getattr(model, "_blockswap_bypass_protection", False):
        logger.info(f"{model_name} with BlockSwap active - blocks already distributed, skipping movement")
        return False

    logger.info(f"Restoring {model_name} with BlockSwap to {_device_str(target_device)} ({reason or 'inference'})")

    if hasattr(model, "blocks") and hasattr(model, "blocks_to_swap"):
        offload_device = model._block_swap_config.get("offload_device")
        if not offload_device:
            raise ValueError("BlockSwap config missing offload_device")

        for b, block in enumerate(model.blocks):
            block.to(target_device if b > model.blocks_to_swap else offload_device)

        io_target = target_device if not model._block_swap_config.get("swap_io_components", False) else offload_device
        for name, module in model.named_children():
            if name != "blocks":
                module.to(io_target)

    model._blockswap_active = True
    set_blockswap_bypass(model, bypass=False)

    logger.info(f"BlockSwap model {model_name} restored")
    return True


def _standard_model_movement(
    model: torch.nn.Module,
    current_device: torch.device,
    target_device: torch.device,
    model_name: str,
    reason: str | None = None,
) -> bool:
    """处理普通（非 BlockSwap）模型的设备迁移（内部函数）

    额外处理：
        - VAE 模型迁移到 CPU 时自动清理内存缓冲区

    Args:
        model: 普通模型
        current_device: 当前设备
        target_device: 目标设备
        model_name: 模型名称
        reason: 迁移原因

    Returns:
        bool: 执行了迁移返回 True，否则返回 False
    """
    reason = reason or "inference requirement"
    logger.info(f"Moving {model_name} from {_device_str(current_device)} to {_device_str(target_device)} ({reason})")

    model.to(target_device)
    model.zero_grad(set_to_none=True)

    if target_device.type == "cpu" and model_name == "VAE":
        cleared_count = 0
        for module in model.modules():
            memory = getattr(module, "memory", None)
            if torch.is_tensor(memory) and memory.is_cuda:
                module.memory = None
                cleared_count += 1
        if cleared_count > 0:
            logger.info(f"Cleared {cleared_count} VAE memory buffers")

    return True


# ===========================================================================
# 张量内存管理
# ===========================================================================


def release_tensor_memory(tensor: torch.Tensor | None) -> None:
    """原地释放张量的内存（CPU/CUDA 均可），无需设备传输

    通过 set_() 清空张量数据指针并清除梯度，立即释放底层存储。

    Args:
        tensor: 要释放的张量，None 或非张量时无操作
    """
    if tensor is not None and torch.is_tensor(tensor):
        if tensor.numel() > 0:
            tensor.data.set_()
        tensor.grad = None


def _release_tensor_data(t: torch.Tensor) -> bool:
    """原地释放单个张量数据，返回是否执行了释放

    与 release_tensor_memory 保持一致的实现风格，使用 set_() 原地释放

    Args:
        t: 要释放的张量

    Returns:
        bool: 是否实际执行了释放操作
    """
    if t.numel() > 0:
        t.data.set_()
        return True
    return False


def release_model_memory(model: torch.nn.Module | None) -> None:
    """原地释放模型的所有 GPU 内存，无需 CPU 传输

    遍历模型的所有参数和缓冲区，清空 CUDA 张量的数据指针并清除梯度，
    直接释放显存而不先将张量移动到 CPU（比 model.to('cpu') 更快）。

    Args:
        model: 要释放内存的模型，None 时无操作
    """
    if model is None:
        return

    try:
        model.zero_grad(set_to_none=True)

        released_params = 0
        released_buffers = 0

        for param in model.parameters():
            if param.is_cuda and _release_tensor_data(param):
                released_params += 1

        for buffer in model.buffers():
            if buffer.is_cuda and _release_tensor_data(buffer):
                released_buffers += 1

        if released_params > 0 or released_buffers > 0:
            logger.info(f"Released GPU memory from {released_params} params and {released_buffers} buffers")

    except (AttributeError, RuntimeError) as e:
        logger.warning(f"Failed to release model GPU memory: {e}")


def _destroy_model(model: torch.nn.Module | None) -> None:
    """彻底释放模型内存（CPU+GPU），供外部调用完全销毁模型

    遍历模型的所有参数和缓冲区（无论位于 CPU 还是 GPU），
    原地释放所有张量数据并清除梯度，清空参数和缓冲区引用。

    Args:
        model: 要销毁的模型，None 时无操作
    """
    if model is None:
        return

    try:
        model.zero_grad(set_to_none=True)

        released_params = 0
        released_buffers = 0

        for param in model.parameters():
            if _release_tensor_data(param):
                released_params += 1
            param.grad = None

        for buffer in model.buffers():
            if _release_tensor_data(buffer):
                released_buffers += 1

        for module in model.modules():
            for key in list(module._parameters.keys()):
                del module._parameters[key]
            for key in list(module._buffers.keys()):
                del module._buffers[key]

        if released_params > 0 or released_buffers > 0:
            logger.info(f"Destroyed model: released {released_params} params and {released_buffers} buffers (CPU+GPU)")

    except (AttributeError, RuntimeError) as e:
        logger.warning(f"Failed to destroy model: {e}")


def clear_rope_lru_caches(model: torch.nn.Module | None) -> int:
    """清除模型中所有 RoPE（旋转位置编码）模块的 LRU 缓存

    RoPE 模块的 get_axial_freqs 方法通常使用 @lru_cache 装饰以加速频率计算，
    但在设备迁移或 OOM 后需要清除这些缓存以释放内存或避免设备不匹配。

    Args:
        model: 要清理的模型，None 时返回 0

    Returns:
        int: 实际清除的缓存数量
    """
    if model is None:
        return 0

    cleared_count = 0
    try:
        for name, module in model.named_modules():
            if hasattr(module, "get_axial_freqs") and hasattr(module.get_axial_freqs, "cache_clear"):
                try:
                    module.get_axial_freqs.cache_clear()
                    cleared_count += 1
                except Exception as e:
                    logger.warning(f"Failed to clear RoPE LRU cache for module {name}: {e}")
    except (AttributeError, RuntimeError) as e:
        logger.warning(f"Failed to iterate model modules for RoPE LRU cache clearing: {e}")

    return cleared_count

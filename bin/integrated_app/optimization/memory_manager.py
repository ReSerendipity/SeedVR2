"""
Memory management module for SeedVR2

Handles VRAM usage, cache management, and memory optimization.
Provides utilities for managing GPU/CPU memory during model inference,
including BlockSwap-aware model device management.

Adapted from ComfyUI-SeedVR2_VideoUpscaler, with ComfyUI dependencies removed.
"""

import gc
import logging
import sys
from typing import Any

import psutil
import torch

logger = logging.getLogger(__name__)


def _device_str(device: torch.device | str) -> str:
    """Normalized uppercase device string for comparison and logging."""
    return str(device).upper()


def is_cuda_available() -> bool:
    """Check if CUDA backend is available."""
    return torch.cuda.is_available()


# ---------------------------------------------------------------------------
# VRAM / RAM monitoring
# ---------------------------------------------------------------------------

def get_basic_vram_info(device: torch.device | None = None) -> dict[str, Any]:
    """
    Get basic VRAM availability info (free and total memory).

    Args:
        device: Optional device to query. If None, uses cuda:0

    Returns:
        dict: {"free_gb": float, "total_gb": float} or {"error": str}
    """
    try:
        if is_cuda_available():
            if device is None:
                device = torch.device("cuda:0")
            elif not isinstance(device, torch.device):
                device = torch.device(device)
            free_memory, total_memory = torch.cuda.mem_get_info(device)
        else:
            # CONSTRAINT: SeedVR2 仅支持 NVIDIA CUDA GPU，不支持 CPU/MPS 推理
            return {"error": "No CUDA GPU backend available"}

        return {
            "free_gb": free_memory / (1024**3),
            "total_gb": total_memory / (1024**3)
        }
    except Exception as e:
        return {"error": f"Failed to get memory info: {str(e)}"}


def get_vram_usage(device: torch.device | None = None) -> tuple[float, float, float, float]:
    """
    Get current VRAM usage metrics for monitoring.

    Args:
        device: Optional device to query. If None, uses cuda:0

    Returns:
        tuple: (allocated_gb, reserved_gb, peak_allocated_gb, peak_reserved_gb)
    """
    try:
        if is_cuda_available():
            if device is None:
                device = torch.device("cuda:0")
            elif not isinstance(device, torch.device):
                device = torch.device(device)
            allocated = torch.cuda.memory_allocated(device) / (1024**3)
            reserved = torch.cuda.memory_reserved(device) / (1024**3)
            peak_allocated = torch.cuda.max_memory_allocated(device) / (1024**3)
            peak_reserved = torch.cuda.max_memory_reserved(device) / (1024**3)
            return allocated, reserved, peak_allocated, peak_reserved
    except Exception as e:
        logger.warning(f"Failed to get VRAM usage: {e}")
    return 0.0, 0.0, 0.0, 0.0


def get_ram_usage() -> tuple[float, float, float, float]:
    """
    Get current RAM usage metrics for the current process.

    Returns:
        tuple: (process_gb, available_gb, total_gb, used_by_others_gb)
    """
    try:
        process = psutil.Process()
        process_memory = process.memory_info()
        process_gb = process_memory.rss / (1024**3)

        sys_memory = psutil.virtual_memory()
        total_gb = sys_memory.total / (1024**3)
        available_gb = sys_memory.available / (1024**3)

        total_used_gb = total_gb - available_gb
        used_by_others_gb = max(0, total_used_gb - process_gb)

        return process_gb, available_gb, total_gb, used_by_others_gb
    except Exception as e:
        logger.warning(f"Failed to get RAM usage: {e}")
        return 0.0, 0.0, 0.0, 0.0


# ---------------------------------------------------------------------------
# Memory clearing
# ---------------------------------------------------------------------------

# Global cache for OS libraries (initialized once)
_os_memory_lib = None


def clear_memory(deep: bool = False, force: bool = True) -> None:
    """
    Clear memory caches with two-tier approach for optimal performance.

    Args:
        force: If True, always clear. If False, only clear when <5% free
        deep: If True, perform deep cleanup including GC and OS operations.
              If False (default), only perform minimal GPU cache clearing.

    Two-tier approach:
        - Minimal mode (deep=False): GPU cache operations (~1-5ms)
        - Deep mode (deep=True): Complete cleanup with GC and OS operations (~10-50ms)
    """
    global _os_memory_lib

    # Check if we should clear based on memory pressure
    if not force:
        should_clear = False

        mem_info = get_basic_vram_info(device=None)

        if "error" not in mem_info and mem_info["total_gb"] > 0:
            free_ratio = mem_info["free_gb"] / mem_info["total_gb"]
            if free_ratio < 0.05:
                should_clear = True

        if not should_clear:
            mem = psutil.virtual_memory()
            if mem.available < mem.total * 0.05:
                should_clear = True

        if not should_clear:
            return

    # ===== MINIMAL OPERATIONS (Always performed) =====
    if is_cuda_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()

    # ===== DEEP OPERATIONS (Only when deep=True) =====
    if deep:
        gc.collect(2)

        try:
            if sys.platform == 'linux':
                import ctypes
                if _os_memory_lib is None:
                    _os_memory_lib = ctypes.CDLL("libc.so.6")
                _os_memory_lib.malloc_trim(0)

            elif sys.platform == 'win32':
                import ctypes
                if _os_memory_lib is None:
                    _os_memory_lib = ctypes.windll.kernel32
                handle = _os_memory_lib.GetCurrentProcess()
                _os_memory_lib.SetProcessWorkingSetSize(handle, -1, -1)
        except Exception as e:
            logger.warning(f"Failed to perform OS memory operations: {e}")


def reset_vram_peak(device: torch.device | None = None) -> None:
    """Reset VRAM peak memory statistics for fresh tracking."""
    try:
        if is_cuda_available():
            if device is None:
                device = torch.device("cuda:0")
            elif not isinstance(device, torch.device):
                device = torch.device(device)
            torch.cuda.reset_peak_memory_stats(device)
    except Exception as e:
        logger.warning(f"Failed to reset peak memory stats: {e}")


# ---------------------------------------------------------------------------
# Model device management
# ---------------------------------------------------------------------------

def manage_model_device(
    model: torch.nn.Module,
    target_device: torch.device,
    model_name: str = "Model",
    reason: str | None = None,
) -> bool:
    """
    Move model to target device with BlockSwap awareness.

    If the model has BlockSwap active (model._blockswap_active = True),
    handles the movement specially to preserve BlockSwap configuration.

    Args:
        model: The model to move
        target_device: Target device (torch.device object)
        model_name: Name for logging (e.g., "VAE", "DiT")
        reason: Optional custom reason for the movement

    Returns:
        bool: True if model was moved, False if already on target device
    """
    if model is None:
        return False

    # Check if this is a BlockSwap-enabled model
    is_blockswap_model = getattr(model, '_blockswap_active', False)

    # Get current device
    try:
        current_device = next(model.parameters()).device
    except StopIteration:
        return False

    target_type = target_device.type
    current_device_upper = _device_str(current_device)
    target_device_upper = _device_str(target_device)

    # Compare normalized device types
    if current_device_upper == target_device_upper and not is_blockswap_model:
        return False

    # Handle BlockSwap models specially
    if is_blockswap_model:
        return _handle_blockswap_model_movement(
            model, current_device, target_device, target_type,
            model_name, reason
        )

    # Standard model movement
    return _standard_model_movement(
        model, current_device, target_device, target_type, model_name, reason
    )


def _handle_blockswap_model_movement(
    model: torch.nn.Module,
    current_device: torch.device,
    target_device: torch.device,
    target_type: str,
    model_name: str,
    reason: str | None = None,
) -> bool:
    """Handle device movement for BlockSwap-enabled models."""
    from .blockswap import set_blockswap_bypass

    if target_type == "cpu":
        # Moving to offload device
        reason = reason or "model offloading"
        logger.info(f"Moving {model_name} to {_device_str(target_device)} ({reason})")

        # Enable bypass to allow movement
        set_blockswap_bypass(model, bypass=True)

        # Move entire model to target offload device
        model.to(target_device)
        model.zero_grad(set_to_none=True)

        return True
    else:
        # Moving to GPU (reload from offload)
        if not getattr(model, "_blockswap_bypass_protection", False):
            logger.info(f"{model_name} with BlockSwap active - blocks already distributed, skipping movement")
            return False

        logger.info(f"Restoring {model_name} with BlockSwap to {_device_str(target_device)} ({reason or 'inference'})")

        # Restore blocks to their configured devices
        if hasattr(model, "blocks") and hasattr(model, "blocks_to_swap"):
            offload_device = model._block_swap_config.get("offload_device")
            if not offload_device:
                raise ValueError("BlockSwap config missing offload_device")

            for b, block in enumerate(model.blocks):
                if b > model.blocks_to_swap:
                    block.to(target_device)
                else:
                    block.to(offload_device)

            # Handle I/O components
            if not model._block_swap_config.get("swap_io_components", False):
                for name, module in model.named_children():
                    if name != "blocks":
                        module.to(target_device)
            else:
                for name, module in model.named_children():
                    if name != "blocks":
                        module.to(offload_device)

        # Reactivate BlockSwap
        model._blockswap_active = True

        # Disable bypass, re-enable protection
        set_blockswap_bypass(model, bypass=False)

        logger.info(f"BlockSwap model {model_name} restored")
        return True


def _standard_model_movement(
    model: torch.nn.Module,
    current_device: torch.device,
    target_device: torch.device,
    target_type: str,
    model_name: str,
    reason: str | None = None,
) -> bool:
    """Handle standard (non-BlockSwap) model movement."""
    if current_device.type == 'meta':
        logger.info(f"{model_name} is on meta device - skipping movement")
        return False

    reason = reason or "inference requirement"
    logger.info(f"Moving {model_name} from {_device_str(current_device)} to {_device_str(target_device)} ({reason})")

    model.to(target_device)
    model.zero_grad(set_to_none=True)

    # Clear VAE memory buffers when moving to CPU
    if target_type == 'cpu' and model_name == "VAE":
        cleared_count = 0
        for module in model.modules():
            if hasattr(module, 'memory') and module.memory is not None and torch.is_tensor(module.memory) and module.memory.is_cuda:
                module.memory = None
                cleared_count += 1
        if cleared_count > 0:
            logger.info(f"Cleared {cleared_count} VAE memory buffers")

    return True


# ---------------------------------------------------------------------------
# Tensor memory management
# ---------------------------------------------------------------------------

def release_tensor_memory(tensor: torch.Tensor | None) -> None:
    """Release tensor memory from any device (CPU/CUDA)"""
    if tensor is not None and torch.is_tensor(tensor):
        if tensor.numel() > 0:
            tensor.data.set_()
        tensor.grad = None


def release_model_memory(model: torch.nn.Module | None) -> None:
    """
    Release all GPU memory from model in-place without CPU transfer.
    """
    if model is None:
        return

    try:
        model.zero_grad(set_to_none=True)

        released_params = 0
        released_buffers = 0

        for param in model.parameters():
            if param.is_cuda:
                if param.numel() > 0:
                    param.data.set_()
                    released_params += 1
                param.grad = None

        for buffer in model.buffers():
            if buffer.is_cuda and buffer.numel() > 0:
                buffer.data.set_()
                released_buffers += 1

        if released_params > 0 or released_buffers > 0:
            logger.info(f"Released memory from {released_params} params and {released_buffers} buffers")

    except (AttributeError, RuntimeError) as e:
        logger.warning(f"Failed to release model memory: {e}")


def clear_rope_lru_caches(model: torch.nn.Module | None) -> int:
    """
    Clear ALL LRU caches from RoPE modules.

    Returns:
        Number of caches cleared
    """
    if model is None:
        return 0

    cleared_count = 0
    try:
        for name, module in model.named_modules():
            if hasattr(module, 'get_axial_freqs') and hasattr(module.get_axial_freqs, 'cache_clear'):
                try:
                    module.get_axial_freqs.cache_clear()
                    cleared_count += 1
                except Exception as e:
                    logger.warning(f"Failed to clear RoPE LRU cache for module {name}: {e}")
    except (AttributeError, RuntimeError) as e:
        logger.warning(f"Failed to iterate model modules for RoPE LRU cache clearing: {e}")

    return cleared_count

"""
BlockSwap Module for SeedVR2

Implements dynamic block swapping between GPU and CPU memory
to enable running large models on limited VRAM systems (e.g., RTX 5070 Ti 12GB).

Key Features:
- Dynamic transformer block offloading during inference
- Non-blocking GPU transfers for optimal performance
- RoPE computation fallback to CPU on OOM
- I/O component offloading for maximum memory savings
- Model protection against unintended full device movement

Adapted from ComfyUI-SeedVR2_VideoUpscaler, with ComfyUI dependencies removed.
"""

import logging
import time
import types
import weakref
from typing import Any

import torch

from bin.integrated_app.optimization.cache_manager import (
    TensorCacheManager,
    get_cache_manager,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Simple logging helpers (replaces ComfyUI Debug class)
# ---------------------------------------------------------------------------

def _log_info(msg: str):
    logger.info(msg)


def _log_warning(msg: str):
    logger.warning(msg)


def _log_error(msg: str):
    logger.error(msg)


# ---------------------------------------------------------------------------
# BlockSwap configuration helpers
# ---------------------------------------------------------------------------

def is_blockswap_enabled(config: dict[str, Any] | None) -> bool:
    """
    Check if BlockSwap configuration indicates BlockSwap should be enabled.

    BlockSwap is enabled if either blocks_to_swap > 0 OR swap_io_components is True.

    Args:
        config: BlockSwap configuration dictionary with optional keys:
            - blocks_to_swap: Number of blocks to offload (0 = disabled)
            - swap_io_components: Whether to offload I/O components

    Returns:
        True if BlockSwap should be active, False otherwise
    """
    if not config:
        return False

    blocks_to_swap = config.get("blocks_to_swap", 0)
    swap_io_components = config.get("swap_io_components", False)

    return blocks_to_swap > 0 or swap_io_components


# ---------------------------------------------------------------------------
# Timing helpers (excluded from torch.compile tracing)
# ---------------------------------------------------------------------------

@torch._dynamo.disable
def _get_swap_start_time(enabled: bool) -> float | None:
    """Get start time for swap operation."""
    return time.time() if enabled else None


@torch._dynamo.disable
def _log_swap_timing(t_start: float | None, component_id, component_type: str) -> None:
    """Log swap timing if start time was captured."""
    if t_start is not None:
        duration = time.time() - t_start
        logger.debug(f"BlockSwap {component_type} #{component_id}: {duration*1000:.1f}ms")


# ---------------------------------------------------------------------------
# Memory measurement
# ---------------------------------------------------------------------------

def get_module_memory_mb(module: torch.nn.Module) -> float:
    """
    Calculate memory usage of a module in MB.

    Args:
        module: PyTorch module to measure

    Returns:
        Memory usage in megabytes
    """
    total_bytes = sum(
        param.nelement() * param.element_size()
        for param in module.parameters()
        if param.data is not None
    )
    return total_bytes / (1024 * 1024)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def apply_block_swap_to_dit(
    model: torch.nn.Module,
    blocks_to_swap: int = 0,
    swap_io_components: bool = True,
    main_device: str = "cuda",
    offload_device: str = "cpu",
    debug: bool = False,
) -> None:
    """
    Apply block swapping configuration to a DiT model.

    This is the main entry point for configuring block swapping on a model.
    Handles block selection, I/O component offloading, device placement, and
    forward method wrapping for dynamic memory management.

    Args:
        model: DiT model (NaDiT instance) containing 'blocks' attribute
        blocks_to_swap: Number of blocks to swap (from the start, 0 = disabled)
        swap_io_components: Whether to offload I/O components (embeddings, norms, etc.)
        main_device: Main computation device (typically 'cuda' or 'cuda:0')
        offload_device: Device to offload to (typically 'cpu')
        debug: Whether to enable debug logging
    """
    # Early return if BlockSwap not enabled
    if blocks_to_swap <= 0 and not swap_io_components:
        return

    # Validate model structure
    if not hasattr(model, "blocks"):
        _log_error("Model doesn't have 'blocks' attribute for BlockSwap")
        return

    # Convert string devices to torch.device
    if isinstance(main_device, str):
        main_device = torch.device(main_device)
    if isinstance(offload_device, str):
        offload_device = torch.device(offload_device)

    total_blocks = len(model.blocks)

    # Clamp blocks_to_swap to available blocks
    effective_blocks = min(blocks_to_swap, total_blocks) if blocks_to_swap > 0 else 0

    # Log configuration
    block_text = "block" if effective_blocks <= 1 else "blocks"
    if effective_blocks > 0 and swap_io_components:
        _log_info(f"BlockSwap: {effective_blocks}/{total_blocks} transformer {block_text} + I/O components offloaded to {offload_device}")
    elif effective_blocks > 0:
        _log_info(f"BlockSwap: {effective_blocks}/{total_blocks} transformer {block_text} offloaded to {offload_device}")
    elif swap_io_components:
        _log_info(f"BlockSwap: I/O components offloaded to {offload_device} (0/{total_blocks} blocks swapped)")

    # Configure model with blockswap attributes
    if blocks_to_swap > 0:
        model.blocks_to_swap = effective_blocks - 1  # Convert to 0-indexed inclusive bound
    else:
        model.blocks_to_swap = -1  # No block swapping

    model.main_device = main_device
    model.offload_device = offload_device

    # Configure I/O components
    io_config = _configure_io_components(model, main_device, offload_device, swap_io_components)

    # Configure blocks
    memory_stats = _configure_blocks(model, main_device, offload_device)

    # Log memory summary
    _log_memory_summary(memory_stats, io_config, offload_device, main_device, swap_io_components)

    # Wrap block forward methods for dynamic swapping (only if blocks_to_swap > 0)
    if blocks_to_swap > 0:
        for b, block in enumerate(model.blocks):
            if b <= model.blocks_to_swap:
                _wrap_block_forward(block, b, model)

    # Patch RoPE modules for robust error handling
    _patch_rope_for_blockswap(model)

    # Mark BlockSwap as active on the model
    model._blockswap_active = True

    # Store configuration for debugging and cleanup
    model._block_swap_config = {
        "blocks_swapped": effective_blocks,
        "swap_io_components": swap_io_components,
        "total_blocks": total_blocks,
        "offload_device": offload_device,
        "main_device": main_device,
        "offload_memory": memory_stats['offload_memory'],
        "main_memory": memory_stats['main_memory'],
    }

    # Protect model from being moved entirely
    _protect_model_from_move(model)

    _log_info("BlockSwap configuration complete")


# ---------------------------------------------------------------------------
# I/O component configuration
# ---------------------------------------------------------------------------

def _configure_io_components(
    model: torch.nn.Module,
    device: torch.device,
    offload_device: torch.device,
    swap_io_components: bool,
) -> dict[str, Any]:
    """
    Configure I/O component placement and wrapping with memory tracking.

    Handles all non-block modules (embeddings, normalization layers, etc.) by
    either keeping them on GPU or offloading them with dynamic swapping wrappers.

    Returns:
        Dictionary containing component names and memory statistics
    """
    io_components_offloaded = []
    io_components_on_gpu = []
    io_memory_mb = 0.0
    io_gpu_memory_mb = 0.0

    for name, module in model.named_children():
        if name != "blocks":
            module_memory = get_module_memory_mb(module)

            if swap_io_components:
                module.to(offload_device)
                _wrap_io_forward(module, name, model)
                io_components_offloaded.append(name)
                io_memory_mb += module_memory
                _log_info(f"  {name} -> {offload_device} ({module_memory:.2f}MB, dynamic swapping)")
            else:
                module.to(device)
                io_components_on_gpu.append(name)
                io_gpu_memory_mb += module_memory
                _log_info(f"  {name} -> {device} ({module_memory:.2f}MB)")

    return {
        'components': io_components_offloaded,
        'memory_mb': io_memory_mb,
        'gpu_components': io_components_on_gpu,
        'gpu_memory_mb': io_gpu_memory_mb,
    }


# ---------------------------------------------------------------------------
# Block configuration
# ---------------------------------------------------------------------------

def _configure_blocks(
    model: torch.nn.Module,
    device: torch.device,
    offload_device: torch.device,
) -> dict[str, float]:
    """
    Configure transformer block placement and calculate memory statistics.

    Moves blocks to their designated devices based on model.blocks_to_swap
    attribute. Blocks with index <= blocks_to_swap go to offload device,
    others stay on main device.

    Returns:
        Dictionary containing offload_memory and main_memory in MB
    """
    total_offload_memory = 0.0
    total_main_memory = 0.0

    for b, block in enumerate(model.blocks):
        block_memory = get_module_memory_mb(block)

        if b > model.blocks_to_swap:
            block.to(device)
            total_main_memory += block_memory
        else:
            block.to(offload_device, non_blocking=False)
            total_offload_memory += block_memory

    # Ensure all buffers match their containing module's device
    for b, block in enumerate(model.blocks):
        target_device = device if b > model.blocks_to_swap else offload_device
        for _name, buffer in block.named_buffers():
            if buffer.device != torch.device(target_device):
                buffer.data = buffer.data.to(target_device, non_blocking=False)

    return {
        "offload_memory": total_offload_memory,
        "main_memory": total_main_memory,
    }


# ---------------------------------------------------------------------------
# Memory summary logging
# ---------------------------------------------------------------------------

def _log_memory_summary(
    memory_stats: dict[str, float],
    io_config: dict[str, Any],
    offload_device: torch.device,
    device: torch.device,
    swap_io_components: bool,
) -> None:
    """Log comprehensive memory usage summary for BlockSwap configuration."""
    _log_info("BlockSwap memory configuration:")

    blocks_offloaded = memory_stats['offload_memory']
    blocks_on_gpu = memory_stats['main_memory']

    if blocks_on_gpu == 0:
        _log_info(f"  Transformer blocks: {blocks_offloaded:.2f}MB on {offload_device} (dynamic swapping)")
    else:
        _log_info(f"  Transformer blocks: {blocks_on_gpu:.2f}MB on {device}, {blocks_offloaded:.2f}MB on {offload_device}")

    io_memory = io_config.get('memory_mb', 0.0)
    io_gpu_memory = io_config.get('gpu_memory_mb', 0.0)

    if swap_io_components and io_memory > 0:
        io_components = io_config.get('components', [])
        _log_info(f"  I/O components: {io_memory:.2f}MB on {offload_device} (dynamic swapping)")
        _log_info(f"    {', '.join(io_components)}")
    elif io_gpu_memory > 0:
        io_gpu_components = io_config.get('gpu_components', [])
        _log_info(f"  I/O components: {io_gpu_memory:.2f}MB on {device}")
        _log_info(f"    {', '.join(io_gpu_components)}")

    total_offloaded = blocks_offloaded + (io_memory if swap_io_components else 0)
    if total_offloaded > 0:
        _log_info(f"  Total VRAM saved: {total_offloaded:.2f}MB (~{total_offloaded/1024:.2f}GB)")


# ---------------------------------------------------------------------------
# Block forward wrapping
# ---------------------------------------------------------------------------

def _wrap_block_forward(
    block: torch.nn.Module,
    block_idx: int,
    model: torch.nn.Module,
) -> None:
    """
    Wrap individual transformer block forward for dynamic device swapping.

    Creates a wrapped forward method that automatically:
    1. Moves block to GPU before computation
    2. Executes original forward pass
    3. Moves block back to offload device after computation
    4. Manages memory pressure

    Uses weak references to prevent memory leaks from closure retention.
    """
    if hasattr(block, '_original_forward'):
        return  # Already wrapped

    # Store original forward method
    original_forward = block.forward

    # Create weak references
    model_ref = weakref.ref(model)

    # Store block_idx on the block itself to avoid closure issues
    block._block_idx = block_idx

    def wrapped_forward(self, *args, **kwargs):
        # Retrieve weak reference
        model = model_ref()

        if not model:
            # Model has been garbage collected, fall back to original
            return original_forward(*args, **kwargs)

        # Check if block swap is active for this block
        if hasattr(model, 'blocks_to_swap') and self._block_idx <= model.blocks_to_swap:
            t_start = _get_swap_start_time(True)

            # Only move to GPU if necessary
            current_device = next(self.parameters()).device
            target_device = torch.device(model.main_device)

            if current_device != target_device:
                self.to(model.main_device, non_blocking=False)

            # Execute forward pass
            output = original_forward(*args, **kwargs)

            # Auto-cache output to CPU if VRAM is low (RVRT-inspired CPU caching)
            cache_manager = _get_cache_manager_for_blockswap(model)
            if cache_manager is not None and isinstance(output, torch.Tensor) and output.is_cuda:
                cache_manager.maybe_cache_tensor(
                    output, f"block_{self._block_idx}_output"
                )

            # Move block back to offload device
            self.to(model.offload_device, non_blocking=False)

            # Log timing
            _log_swap_timing(t_start, self._block_idx, "block")

            # Clear cache under memory pressure
            _clear_memory_if_needed()
        else:
            output = original_forward(*args, **kwargs)

        return output

    # Bind the wrapped function as a method to the block
    block.forward = types.MethodType(wrapped_forward, block)

    # Store reference to original forward for cleanup
    block._original_forward = original_forward


def _get_cache_manager_for_blockswap(model: torch.nn.Module) -> TensorCacheManager | None:
    """Get or create a TensorCacheManager attached to the model.

    Attaches a cache manager to the model if one doesn't exist yet,
    allowing per-model tensor caching during BlockSwap inference.
    """
    if not hasattr(model, '_tensor_cache_manager'):
        try:
            model._tensor_cache_manager = get_cache_manager()
        except Exception:
            return None
    return getattr(model, '_tensor_cache_manager', None)


# ---------------------------------------------------------------------------
# I/O component forward wrapping
# ---------------------------------------------------------------------------

def _wrap_io_forward(
    module: torch.nn.Module,
    module_name: str,
    model: torch.nn.Module,
) -> None:
    """
    Wrap I/O component forward for dynamic device swapping.

    Similar to _wrap_block_forward but for I/O components (embeddings,
    normalization layers, etc.).
    """
    if hasattr(module, '_is_io_wrapped') and module._is_io_wrapped:
        return  # Already wrapped

    # Store original forward method
    original_forward = module.forward

    # Create weak references
    model_ref = weakref.ref(model)

    # Store module name on the module itself
    module._module_name = module_name
    module._original_forward = original_forward

    def wrapped_io_forward(self, *args, **kwargs):
        # Retrieve weak reference
        model = model_ref()

        if not model:
            return self._original_forward(*args, **kwargs)

        t_start = _get_swap_start_time(True)

        # Check current device to avoid unnecessary moves
        current_device = next(self.parameters()).device
        target_device = torch.device(model.main_device)

        # Move to GPU for computation if needed
        if current_device != target_device:
            self.to(model.main_device, non_blocking=False)

        # Execute forward pass
        output = self._original_forward(*args, **kwargs)

        # Move back to offload device
        self.to(model.offload_device, non_blocking=False)

        # Log timing
        _log_swap_timing(t_start, self._module_name, "I/O")

        # Clear cache under memory pressure
        _clear_memory_if_needed()

        return output

    # Bind as a method
    module.forward = types.MethodType(wrapped_io_forward, module)
    module._is_io_wrapped = True

    # Store module reference for restoration
    if not hasattr(model, '_io_swappers'):
        model._io_swappers = []
    model._io_swappers.append((module, module_name))


# ---------------------------------------------------------------------------
# RoPE patching for BlockSwap
# ---------------------------------------------------------------------------

def _patch_rope_for_blockswap(model: torch.nn.Module) -> None:
    """
    Patch RoPE (Rotary Position Embedding) modules for device-aware fallback.

    Adds CPU fallback logic to RoPE modules to handle device mismatch errors
    that can occur during BlockSwap operations.
    """
    rope_patches = []

    for name, module in model.named_modules():
        if "rope" in name.lower() and hasattr(module, "get_axial_freqs"):
            # Skip if already wrapped by blockswap
            if hasattr(module, '_blockswap_wrapped') and module._blockswap_wrapped:
                continue

            # Get current method (might be stability-wrapped)
            current_method = module.get_axial_freqs

            # Create device-aware wrapper with proper closure handling
            def make_device_aware_wrapper(module_name, current_fn):
                def device_aware_rope_wrapper(self, *args, **kwargs):
                    try:
                        # Try current method (original or stability-wrapped)
                        return current_fn(*args, **kwargs)
                    except (RuntimeError, torch.cuda.OutOfMemoryError) as e:
                        error_msg = str(e).lower()
                        # Only handle device/memory specific errors
                        if any(x in error_msg for x in ["device", "memory", "allocation"]):
                            _log_warning(f"RoPE OOM for {module_name}, falling back to CPU")

                            # Get current device from parameters
                            try:
                                current_device = next(self.parameters()).device
                            except StopIteration:
                                if hasattr(model, 'main_device'):
                                    current_device = torch.device(model.main_device)
                                elif hasattr(model, 'offload_device'):
                                    current_device = torch.device(model.offload_device)

                            # Try clearing cache first (non-invasive fix)
                            if hasattr(current_fn, 'cache_clear'):
                                current_fn.cache_clear()
                                try:
                                    return current_fn(*args, **kwargs)
                                except Exception:
                                    _log_warning(f"Cache clear insufficient for {module_name}, falling back to CPU")

                            # Fallback to CPU computation
                            self.cpu()

                            try:
                                # Call with autocast disabled for stability
                                original_fn = getattr(self, '_original_get_axial_freqs', current_fn)
                                with torch.cuda.amp.autocast(enabled=False):
                                    result = original_fn(*args, **kwargs)

                                # Move module back to original device
                                self.to(current_device)

                                # Move result to appropriate device if it's a tensor
                                if hasattr(result, 'to'):
                                    target_device = args[0].device if len(args) > 0 and hasattr(args[0], 'device') else current_device
                                    return result.to(target_device)
                                return result

                            except Exception as cpu_error:
                                # Always restore device even on error
                                self.to(current_device)
                                raise cpu_error
                        else:
                            # Not a device error, let it bubble up
                            raise

                return device_aware_rope_wrapper

            # Apply wrapper
            module.get_axial_freqs = types.MethodType(
                make_device_aware_wrapper(name, current_method),
                module
            )
            module._blockswap_wrapped = True

            # Store for cleanup (use original or previously stored)
            original_method = getattr(module, '_original_get_axial_freqs', current_method)
            rope_patches.append((module, original_method))

    if rope_patches:
        model._rope_patches = rope_patches
        _log_info(f"Patched {len(rope_patches)} RoPE modules with device handling")


# ---------------------------------------------------------------------------
# Model protection
# ---------------------------------------------------------------------------

def _protect_model_from_move(model: torch.nn.Module) -> None:
    """
    Protect model from unintended full device movement during BlockSwap.

    Wraps model.to() method to prevent other code from accidentally moving
    the entire model to GPU, which would defeat BlockSwap's memory savings.
    Allows movement only when explicitly bypassed via model flag.
    """
    if not hasattr(model, '_original_to'):
        model._original_to = model.to

        def protected_model_to(self, device, *args, **kwargs):
            # Check if protection is temporarily bypassed for offloading
            if getattr(self, "_blockswap_bypass_protection", False) and hasattr(self, '_original_to'):
                return self._original_to(device, *args, **kwargs)

            # Get configured offload device directly from model
            blockswap_offload_device = "cpu"  # default
            if hasattr(self, "_block_swap_config"):
                blockswap_offload_device = self._block_swap_config.get("offload_device", "cpu")

            # Check if BlockSwap is currently active
            blockswap_is_active = getattr(self, '_blockswap_active', False)

            # Block attempts to move model away from configured offload device when active
            if blockswap_is_active and str(device) != str(blockswap_offload_device):
                _log_warning(f"Blocked attempt to move BlockSwap model from {blockswap_offload_device} to {device}")
                return self

            # Allow movement (either bypass is enabled or target is offload device)
            if hasattr(self, '_original_to'):
                return self._original_to(device, *args, **kwargs)
            else:
                return super(type(self), self).to(device, *args, **kwargs)

        # Bind as a method to the model instance
        model.to = types.MethodType(protected_model_to, model)


# ---------------------------------------------------------------------------
# Bypass control
# ---------------------------------------------------------------------------

def set_blockswap_bypass(model: torch.nn.Module, bypass: bool) -> None:
    """
    Set or unset bypass flag for BlockSwap protection.
    Used for offloading to temporarily allow model movement.

    Args:
        model: DiT model with BlockSwap
        bypass: True to bypass protection, False to enforce it
    """
    if not getattr(model, '_blockswap_active', False):
        return

    model._blockswap_bypass_protection = bypass

    if bypass:
        _log_info("BlockSwap protection disabled to allow model offloading")
    else:
        _log_info("BlockSwap protection re-enabled")


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def cleanup_blockswap(model: torch.nn.Module) -> None:
    """
    Clean up BlockSwap configuration from a model.

    Restores all original forward methods, RoPE patches, and model.to().

    Args:
        model: DiT model to clean up
    """
    if not getattr(model, '_blockswap_active', False) and not hasattr(model, '_block_swap_config'):
        return

    _log_info("Starting BlockSwap cleanup")

    # 1. Restore block forward methods
    if hasattr(model, 'blocks'):
        restored_count = 0
        for block in model.blocks:
            if hasattr(block, '_original_forward'):
                block.forward = block._original_forward
                delattr(block, '_original_forward')
                restored_count += 1

                for attr in ['_block_idx', '_blockswap_wrapped']:
                    if hasattr(block, attr):
                        delattr(block, attr)

        if restored_count > 0:
            _log_info(f"Restored {restored_count} block forward methods")

    # 2. Restore RoPE patches
    if hasattr(model, '_rope_patches'):
        for module, original_method in model._rope_patches:
            module.get_axial_freqs = original_method
            for attr in ['_rope_wrapped', '_original_get_axial_freqs', '_blockswap_wrapped']:
                if hasattr(module, attr):
                    delattr(module, attr)
        _log_info(f"Restored {len(model._rope_patches)} RoPE methods")
        delattr(model, '_rope_patches')

    # 3. Restore I/O component forward methods
    if hasattr(model, '_io_swappers'):
        for module, _module_name in model._io_swappers:
            if hasattr(module, '_original_forward'):
                module.forward = module._original_forward
                for attr in ['_original_forward', '_module_name', '_is_io_wrapped']:
                    if hasattr(module, attr):
                        delattr(module, attr)
        _log_info(f"Restored {len(model._io_swappers)} I/O components")
        delattr(model, '_io_swappers')

    # Move all IO components to offload device during cleanup
    if hasattr(model, 'offload_device'):
        offload_device = model.offload_device
        moved_count = 0
        for name, module in model.named_children():
            if name != "blocks":
                module.to(offload_device)
                moved_count += 1
        if moved_count > 0:
            _log_info(f"Moved {moved_count} IO components to offload device")

    # 4. Restore original .to() method
    if hasattr(model, '_original_to'):
        model.to = model._original_to
        delattr(model, '_original_to')
        _log_info("Restored original .to() method")

    # 5. Clean up BlockSwap-specific attributes
    for attr in ['_blockswap_active', 'blocks_to_swap', 'main_device',
                 'offload_device', '_block_swap_config', '_blockswap_bypass_protection']:
        if hasattr(model, attr):
            delattr(model, attr)

    # 6. Clear tensor cache if attached
    if hasattr(model, '_tensor_cache_manager'):
        cache_mgr = model._tensor_cache_manager
        if cache_mgr is not None and cache_mgr.cache_size > 0:
            _log_info(f"Clearing {cache_mgr.cache_size} cached tensors from CPU cache")
            cache_mgr.clear()
        delattr(model, '_tensor_cache_manager')

    _log_info("BlockSwap cleanup complete")


# ---------------------------------------------------------------------------
# Memory management helpers
# ---------------------------------------------------------------------------

def _clear_memory_if_needed() -> None:
    """Clear GPU cache only when memory pressure is high."""
    try:
        if torch.cuda.is_available():
            free_mem, total_mem = torch.cuda.mem_get_info()
            free_ratio = free_mem / total_mem if total_mem > 0 else 1.0
            if free_ratio < 0.05:
                torch.cuda.empty_cache()
    except Exception:
        pass

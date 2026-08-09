"""BlockSwap 动态块交换模块 - SeedVR2 视频修复项目

本模块实现 GPU/CPU 之间的动态 Transformer 块交换技术，使得在显存有限的 GPU
（如 RTX 5070 Ti 12GB）上也能运行大参数量模型。通过推理时按需将 Transformer 块
从 CPU 加载到 GPU 计算、计算完立即卸载回 CPU，实现以时间换空间的显存优化。

所属项目: SeedVR2 (基于 ComfyUI-SeedVR2_VideoUpscaler 独立重构，已移除 ComfyUI 依赖)
核心技术栈: PyTorch, 动态前向钩子, weakref, types.MethodType, Tensor 缓存

核心功能:
    - 推理时动态 Transformer 块卸载/加载（GPU ↔ CPU）
    - 非阻塞 GPU 传输优化（当前使用同步传输保证稳定性）
    - RoPE（旋转位置编码）OOM 时 CPU 回退计算
    - I/O 组件（embedding、norm 等）可选卸载，最大化显存节省
    - 模型保护机制：防止外部代码意外将整个模型移回 GPU 破坏 BlockSwap 配置
    - 与 cache_manager 集成：VRAM 低时自动缓存中间张量到 CPU
    - 完整的清理/回滚机制：可恢复模型原始状态

工作原理:
    1. 初始化时：前 N 个 Transformer 块放在 CPU，其余块留在 GPU
    2. 推理时：每个块的 forward 被包装，执行前自动将块移到 GPU
    3. 计算后：立即将块移回 CPU，释放显存供下一个块使用
    4. I/O 组件：同理可包装为动态加载/卸载
    5. 保护机制：model.to() 被劫持，阻止意外整体迁移

显存节省估算:
    - 28 个 DiT blocks，交换前 N 个 blocks 可节省约 N/28 的模型参数量显存
    - 例如 7B 模型交换 14 个 blocks 可节省约 8GB 显存
"""

import logging
import threading
import time
import types
import weakref
from typing import Any

import torch

from bin.integrated_app.optimization.gpu.cache_manager import (
    TensorCacheManager,
    get_cache_manager,
)

logger = logging.getLogger(__name__)

_BLOCKSWAP_LOCK = threading.RLock()
_MEMORY_CHECK_INTERVAL_BLOCKS = 4
_MEMORY_CHECK_INTERVAL_MS = 100
_last_memory_check_time = 0.0
_memory_check_block_counter = 0


# ===========================================================================
# BlockSwap 配置辅助函数
# ===========================================================================


def is_blockswap_enabled(config: dict[str, Any] | None) -> bool:
    """检查 BlockSwap 配置是否表示应启用 BlockSwap

    BlockSwap 启用条件（满足任一即可）：
        - blocks_to_swap > 0（需要交换部分 Transformer 块）
        - swap_io_components = True（需要卸载 I/O 组件）

    Args:
        config: BlockSwap 配置字典，可包含以下键：
            - blocks_to_swap (int): 要卸载的块数量（0 表示禁用块交换）
            - swap_io_components (bool): 是否卸载 I/O 组件

    Returns:
        bool: 应启用 BlockSwap 返回 True，否则返回 False
    """
    if not config:
        return False

    blocks_to_swap = config.get("blocks_to_swap", 0)
    swap_io_components = config.get("swap_io_components", False)

    return blocks_to_swap > 0 or swap_io_components


# ===========================================================================
# 计时辅助函数（被 @torch._dynamo.disable 装饰，排除在 torch.compile 追踪外）
# ===========================================================================


@torch._dynamo.disable
def _get_swap_start_time(enabled: bool) -> float | None:
    """获取交换操作开始时间（不被 torch.compile 追踪）

    Args:
        enabled: 是否启用计时

    Returns:
        float | None: 当前时间戳（秒）；enabled=False 时返回 None
    """
    return time.time() if enabled else None


@torch._dynamo.disable
def _log_swap_timing(t_start: float | None, component_id, component_type: str) -> None:
    """记录交换操作耗时（如果 t_start 不为 None）

    Args:
        t_start: 操作开始时间戳，None 时跳过日志
        component_id: 组件标识（块索引或组件名）
        component_type: 组件类型描述（"block" / "I/O"）
    """
    if t_start is not None:
        duration = time.time() - t_start
        logger.debug(f"BlockSwap {component_type} #{component_id}: {duration*1000:.1f}ms")


# ===========================================================================
# 内存测量
# ===========================================================================


def get_module_memory_mb(module: torch.nn.Module | None) -> float:
    """计算 PyTorch 模块的显存/内存占用（MB）

    遍历模块所有参数，计算参数元素数 × 元素字节数的总和。
    不包含缓冲区（buffers）和中间激活。

    Args:
        module: 要测量的 PyTorch 模块，允许为 None

    Returns:
        float: 模块参数占用的内存大小（MB）；module 为 None 时返回 0.0
    """
    if module is None or not isinstance(module, torch.nn.Module):
        return 0.0

    total_bytes = 0
    for param in module.parameters():
        if param is not None and param.data is not None:
            try:
                total_bytes += param.nelement() * param.element_size()
            except Exception:
                continue
    return total_bytes / (1024 * 1024)


# ===========================================================================
# 主入口函数
# ===========================================================================


def apply_block_swap_to_dit(
    model: torch.nn.Module,
    blocks_to_swap: int = 0,
    swap_io_components: bool = True,
    main_device: str = "cuda",
    offload_device: str = "cpu",
    debug: bool = False,
) -> None:
    """为 DiT 模型应用 BlockSwap 配置

    这是 BlockSwap 的主入口函数，负责块选择、I/O 组件卸载配置、设备放置、
    前向方法包装和模型保护等完整初始化流程。

    执行流程：
        1. 验证模型结构（必须有 blocks 属性）
        2. 转换设备字符串为 torch.device
        3. 配置 blocks_to_swap（0-indexed 边界）
        4. 配置 I/O 组件设备放置和动态包装
        5. 配置 Transformer blocks 初始设备放置
        6. 输出显存节省日志
        7. 包装每个需交换 block 的 forward 方法
        8. 为 RoPE 模块打补丁（OOM CPU 回退）
        9. 标记 BlockSwap 激活
        10. 保护模型防止意外整体迁移

    Args:
        model: DiT 模型（NaDiT 实例），必须包含 'blocks' 属性（nn.ModuleList）
        blocks_to_swap: 要交换的块数量（从头开始计数），0 表示禁用块交换
        swap_io_components: 是否卸载 I/O 组件（embedding、norm 等）
        main_device: 主计算设备（通常为 "cuda" 或 "cuda:0"）
        offload_device: 卸载目标设备（通常为 "cpu"）
        debug: 是否启用调试日志（当前未使用，保留参数）
    """
    with _BLOCKSWAP_LOCK:
        if blocks_to_swap <= 0 and not swap_io_components:
            return

        if not hasattr(model, "blocks"):
            logger.error("Model doesn't have 'blocks' attribute for BlockSwap")
            return

        if isinstance(main_device, str):
            main_device = torch.device(main_device)
        if isinstance(offload_device, str):
            offload_device = torch.device(offload_device)

        total_blocks = len(model.blocks)

        effective_blocks = min(blocks_to_swap, total_blocks) if blocks_to_swap > 0 else 0

        block_text = "block" if effective_blocks <= 1 else "blocks"
        if effective_blocks > 0 and swap_io_components:
            logger.info(
                f"BlockSwap: {effective_blocks}/{total_blocks} transformer {block_text} + I/O components offloaded to {offload_device}"
            )
        elif effective_blocks > 0:
            logger.info(
                f"BlockSwap: {effective_blocks}/{total_blocks} transformer {block_text} offloaded to {offload_device}"
            )
        elif swap_io_components:
            logger.info(f"BlockSwap: I/O components offloaded to {offload_device} (0/{total_blocks} blocks swapped)")

        if blocks_to_swap > 0:
            model.blocks_to_swap = effective_blocks - 1
        else:
            model.blocks_to_swap = -1

        model.main_device = main_device
        model.offload_device = offload_device

        io_config = _configure_io_components(model, main_device, offload_device, swap_io_components)

        memory_stats = _configure_blocks(model, main_device, offload_device)

        _log_memory_summary(memory_stats, io_config, offload_device, main_device, swap_io_components)

        if blocks_to_swap > 0:
            for b, block in enumerate(model.blocks):
                if b <= model.blocks_to_swap:
                    _wrap_block_forward(block, b, model)

        _patch_rope_for_blockswap(model)

        model._blockswap_active = True

        model._block_swap_config = {
            "blocks_swapped": effective_blocks,
            "swap_io_components": swap_io_components,
            "total_blocks": total_blocks,
            "offload_device": offload_device,
            "main_device": main_device,
            "offload_memory": memory_stats["offload_memory"],
            "main_memory": memory_stats["main_memory"],
        }

        _protect_model_from_move(model)

        logger.info("BlockSwap configuration complete")


# ===========================================================================
# I/O 组件配置
# ===========================================================================


def _configure_io_components(
    model: torch.nn.Module,
    device: torch.device,
    offload_device: torch.device,
    swap_io_components: bool,
) -> dict[str, Any]:
    """配置 I/O 组件的设备放置和动态包装，并统计内存

    处理所有非 blocks 子模块（embeddings、normalization layers 等）：
        - swap_io_components=True：移到卸载设备并包装 forward 为动态加载
        - swap_io_components=False：保持在主计算设备（GPU）

    Args:
        model: DiT 模型
        device: 主计算设备
        offload_device: 卸载设备
        swap_io_components: 是否卸载 I/O 组件

    Returns:
        dict: 组件名称和内存统计字典，包含：
            - components (list[str]): 卸载的组件名列表
            - memory_mb (float): 卸载到 CPU 的 I/O 内存（MB）
            - gpu_components (list[str]): 保留在 GPU 的组件名列表
            - gpu_memory_mb (float): 保留在 GPU 的 I/O 内存（MB）
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
                logger.info(f"  {name} -> {offload_device} ({module_memory:.2f}MB, dynamic swapping)")
            else:
                module.to(device)
                io_components_on_gpu.append(name)
                io_gpu_memory_mb += module_memory
                logger.info(f"  {name} -> {device} ({module_memory:.2f}MB)")

    return {
        "components": io_components_offloaded,
        "memory_mb": io_memory_mb,
        "gpu_components": io_components_on_gpu,
        "gpu_memory_mb": io_gpu_memory_mb,
    }


# ===========================================================================
# Block 配置
# ===========================================================================


def _configure_blocks(
    model: torch.nn.Module,
    device: torch.device,
    offload_device: torch.device,
) -> dict[str, float]:
    """配置 Transformer blocks 的初始设备放置并计算内存统计

    设备放置策略：
        - blocks 索引 > blocks_to_swap：放到主设备（GPU）
        - blocks 索引 <= blocks_to_swap：放到卸载设备（CPU）
    同时确保所有 buffers 与其所在模块的设备一致。

    Args:
        model: DiT 模型
        device: 主计算设备
        offload_device: 卸载设备

    Returns:
        dict: 内存统计字典，包含：
            - offload_memory (float): 卸载到 CPU 的 blocks 显存（MB）
            - main_memory (float): 保留在 GPU 的 blocks 显存（MB）
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

    for b, block in enumerate(model.blocks):
        target_device = device if b > model.blocks_to_swap else offload_device
        for _name, buffer in block.named_buffers():
            if buffer is not None and buffer.device != torch.device(target_device):
                buffer.data = buffer.data.to(target_device, non_blocking=False)

    return {
        "offload_memory": total_offload_memory,
        "main_memory": total_main_memory,
    }


# ===========================================================================
# 内存汇总日志
# ===========================================================================


def _log_memory_summary(
    memory_stats: dict[str, float],
    io_config: dict[str, Any],
    offload_device: torch.device,
    device: torch.device,
    swap_io_components: bool,
) -> None:
    """输出 BlockSwap 配置后的完整显存使用汇总日志

    Args:
        memory_stats: blocks 内存统计（来自 _configure_blocks）
        io_config: I/O 组件配置（来自 _configure_io_components）
        offload_device: 卸载设备
        device: 主计算设备
        swap_io_components: 是否卸载了 I/O 组件
    """
    logger.info("BlockSwap memory configuration:")

    blocks_offloaded = memory_stats["offload_memory"]
    blocks_on_gpu = memory_stats["main_memory"]

    if blocks_on_gpu == 0:
        logger.info(f"  Transformer blocks: {blocks_offloaded:.2f}MB on {offload_device} (dynamic swapping)")
    else:
        logger.info(
            f"  Transformer blocks: {blocks_on_gpu:.2f}MB on {device}, {blocks_offloaded:.2f}MB on {offload_device}"
        )

    io_memory = io_config.get("memory_mb", 0.0)
    io_gpu_memory = io_config.get("gpu_memory_mb", 0.0)

    if swap_io_components and io_memory > 0:
        io_components = io_config.get("components", [])
        logger.info(f"  I/O components: {io_memory:.2f}MB on {offload_device} (dynamic swapping)")
        logger.info(f"    {', '.join(io_components)}")
    elif io_gpu_memory > 0:
        io_gpu_components = io_config.get("gpu_components", [])
        logger.info(f"  I/O components: {io_gpu_memory:.2f}MB on {device}")
        logger.info(f"    {', '.join(io_gpu_components)}")

    total_offloaded = blocks_offloaded + (io_memory if swap_io_components else 0)
    if total_offloaded > 0:
        logger.info(f"  Total VRAM saved: {total_offloaded:.2f}MB (~{total_offloaded/1024:.2f}GB)")


# ===========================================================================
# Block forward 包装
# ===========================================================================


def _wrap_block_forward(
    block: torch.nn.Module,
    block_idx: int,
    model: torch.nn.Module,
) -> None:
    """包装单个 Transformer block 的 forward 方法实现动态设备交换

    包装后的 forward 自动执行以下流程：
        1. 检查是否需要交换（当前块索引 <= blocks_to_swap）
        2. 如块在 CPU，先移动到 GPU
        3. 执行原始 forward 计算
        4. （可选）VRAM 低时缓存输出到 CPU
        5. 将块移回卸载设备（CPU）
        6. 记录交换耗时
        7. 内存压力高时清理缓存（限频调用）

    使用 weakref 避免闭包持有 model 强引用导致内存泄漏。

    Args:
        block: 要包装的 Transformer block
        block_idx: block 在 model.blocks 中的索引
        model: 父 DiT 模型引用
    """
    if hasattr(block, "_original_forward"):
        return

    original_forward = block.forward
    model_ref = weakref.ref(model)
    block._block_idx = block_idx

    def wrapped_forward(self, *args, **kwargs):
        model = model_ref()

        if not model:
            return original_forward(*args, **kwargs)

        if hasattr(model, "blocks_to_swap") and self._block_idx <= model.blocks_to_swap:
            t_start = _get_swap_start_time(True)

            current_device = next(self.parameters()).device
            target_device = torch.device(model.main_device)

            if current_device != target_device:
                self.to(model.main_device, non_blocking=False)

            output = original_forward(*args, **kwargs)

            cache_manager = _get_cache_manager_for_blockswap(model)
            if cache_manager is not None and isinstance(output, torch.Tensor) and output.is_cuda:
                cache_manager.maybe_cache_tensor(output, f"block_{self._block_idx}_output")

            self.to(model.offload_device, non_blocking=False)

            _log_swap_timing(t_start, self._block_idx, "block")

            _clear_memory_if_needed()
        else:
            output = original_forward(*args, **kwargs)

        return output

    block.forward = types.MethodType(wrapped_forward, block)
    block._original_forward = original_forward


def _get_cache_manager_for_blockswap(model: torch.nn.Module) -> TensorCacheManager | None:
    """获取或创建附加到模型的 TensorCacheManager

    懒加载方式附加缓存管理器到模型，避免无 BlockSwap 时的初始化开销。

    Args:
        model: DiT 模型

    Returns:
        TensorCacheManager | None: 缓存管理器实例；失败时返回 None
    """
    with _BLOCKSWAP_LOCK:
        if not hasattr(model, "_tensor_cache_manager"):
            try:
                model._tensor_cache_manager = get_cache_manager()
            except Exception:
                return None
        return getattr(model, "_tensor_cache_manager", None)


# ===========================================================================
# I/O 组件 forward 包装
# ===========================================================================


def _wrap_io_forward(
    module: torch.nn.Module,
    module_name: str,
    model: torch.nn.Module,
) -> None:
    """包装 I/O 组件的 forward 方法实现动态设备交换

    与 _wrap_block_forward 类似，但用于 I/O 组件（embeddings、normalization layers 等）：
        1. 执行前将模块移到 GPU
        2. 执行原始 forward
        3. 执行后移回 CPU
        4. 记录耗时和清理缓存

    Args:
        module: 要包装的 I/O 模块
        module_name: 模块名称（用于日志）
        model: 父 DiT 模型引用
    """
    if hasattr(module, "_is_io_wrapped") and module._is_io_wrapped:
        return

    original_forward = module.forward
    model_ref = weakref.ref(model)

    module._module_name = module_name
    module._original_forward = original_forward

    def wrapped_io_forward(self, *args, **kwargs):
        model = model_ref()

        if not model:
            return self._original_forward(*args, **kwargs)

        t_start = _get_swap_start_time(True)

        current_device = next(self.parameters()).device
        target_device = torch.device(model.main_device)

        if current_device != target_device:
            self.to(model.main_device, non_blocking=False)

        output = self._original_forward(*args, **kwargs)

        self.to(model.offload_device, non_blocking=False)

        _log_swap_timing(t_start, self._module_name, "I/O")

        _clear_memory_if_needed()

        return output

    module.forward = types.MethodType(wrapped_io_forward, module)
    module._is_io_wrapped = True

    with _BLOCKSWAP_LOCK:
        if not hasattr(model, "_io_swappers"):
            model._io_swappers = []
        model._io_swappers.append((module, module_name))


# ===========================================================================
# RoPE 补丁（BlockSwap 设备感知回退）
# ===========================================================================


def _patch_rope_for_blockswap(model: torch.nn.Module) -> None:
    """为 RoPE（旋转位置编码）模块打补丁以支持设备感知回退

    在 BlockSwap 操作期间，RoPE 模块可能遇到设备不匹配或 OOM 错误。
    此补丁添加 CPU 回退逻辑：
        1. 首先尝试在当前设备（GPU）计算
        2. 如果遇到 device/memory 错误：
           a. 先尝试清除 LRU 缓存重试
           b. 仍失败则将模块移到 CPU 计算
           c. 计算后将模块移回原设备
           d. 结果张量移到正确设备

    Args:
        model: DiT 模型
    """
    rope_patches = []
    model_ref = weakref.ref(model)

    for name, module in model.named_modules():
        if "rope" in name.lower() and hasattr(module, "get_axial_freqs"):
            if hasattr(module, "_blockswap_wrapped") and module._blockswap_wrapped:
                continue

            current_method = module.get_axial_freqs

            def make_device_aware_wrapper(module_name, current_fn):
                def device_aware_rope_wrapper(self, *args, **kwargs):
                    try:
                        return current_fn(*args, **kwargs)
                    except (RuntimeError, torch.cuda.OutOfMemoryError) as e:
                        error_msg = str(e).lower()
                        if any(x in error_msg for x in ["device", "memory", "allocation"]):
                            logger.warning(f"RoPE OOM for {module_name}, falling back to CPU")

                            try:
                                current_device = next(self.parameters()).device
                            except StopIteration:
                                m = model_ref()
                                if m is not None and hasattr(m, "main_device"):
                                    current_device = torch.device(m.main_device)
                                elif m is not None and hasattr(m, "offload_device"):
                                    current_device = torch.device(m.offload_device)
                                else:
                                    current_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

                            if hasattr(current_fn, "cache_clear"):
                                current_fn.cache_clear()
                                try:
                                    return current_fn(*args, **kwargs)
                                except Exception:
                                    logger.warning(f"Cache clear insufficient for {module_name}, falling back to CPU")

                            self.cpu()

                            try:
                                original_fn = getattr(self, "_original_get_axial_freqs", current_fn)
                                with torch.cuda.amp.autocast(enabled=False):
                                    result = original_fn(*args, **kwargs)

                                self.to(current_device)

                                if hasattr(result, "to"):
                                    target_device = (
                                        args[0].device
                                        if len(args) > 0 and hasattr(args[0], "device")
                                        else current_device
                                    )
                                    return result.to(target_device)
                                return result

                            except Exception as cpu_error:
                                self.to(current_device)
                                raise cpu_error
                        else:
                            raise

                return device_aware_rope_wrapper

            module.get_axial_freqs = types.MethodType(make_device_aware_wrapper(name, current_method), module)
            module._blockswap_wrapped = True

            original_method = getattr(module, "_original_get_axial_freqs", current_method)
            rope_patches.append((module, original_method))

    if rope_patches:
        with _BLOCKSWAP_LOCK:
            model._rope_patches = rope_patches
        logger.info(f"Patched {len(rope_patches)} RoPE modules with device handling")


# ===========================================================================
# 模型保护
# ===========================================================================


def _protect_model_from_move(model: torch.nn.Module) -> None:
    """保护 BlockSwap 模型防止意外整体设备迁移

    包装 model.to() 方法，阻止外部代码意外将整个模型移到 GPU 而破坏
    BlockSwap 的显存节省配置。仅在显式 bypass 标志启用时允许迁移。

    保护逻辑：
        - 如果 _blockswap_bypass_protection=True：允许迁移（用于卸载操作）
        - 如果目标是 offload_device（CPU）：允许迁移
        - 如果 BlockSwap 激活且目标不是卸载设备：阻止并记录警告

    Args:
        model: 要保护的 DiT 模型
    """
    if not hasattr(model, "_original_to"):
        model._original_to = model.to

        def protected_model_to(self, device, *args, **kwargs):
            if getattr(self, "_blockswap_bypass_protection", False) and hasattr(self, "_original_to"):
                return self._original_to(device, *args, **kwargs)

            blockswap_offload_device = "cpu"
            if hasattr(self, "_block_swap_config"):
                blockswap_offload_device = self._block_swap_config.get("offload_device", "cpu")

            blockswap_is_active = getattr(self, "_blockswap_active", False)

            if blockswap_is_active and str(device) != str(blockswap_offload_device):
                logger.warning(f"Blocked attempt to move BlockSwap model from {blockswap_offload_device} to {device}")
                return self

            if hasattr(self, "_original_to"):
                return self._original_to(device, *args, **kwargs)
            else:
                return super(type(self), self).to(device, *args, **kwargs)

        model.to = types.MethodType(protected_model_to, model)


# ===========================================================================
# Bypass 控制
# ===========================================================================


def set_blockswap_bypass(model: torch.nn.Module, bypass: bool) -> None:
    """设置或取消 BlockSwap 保护 bypass 标志

    用于模型卸载等场景临时允许整体模型移动。

    Args:
        model: 启用了 BlockSwap 的 DiT 模型
        bypass: True 绕过保护（允许迁移），False 启用保护
    """
    if not getattr(model, "_blockswap_active", False):
        return

    with _BLOCKSWAP_LOCK:
        model._blockswap_bypass_protection = bypass

    if bypass:
        logger.info("BlockSwap protection disabled to allow model offloading")
    else:
        logger.info("BlockSwap protection re-enabled")


# ===========================================================================
# 清理
# ===========================================================================


def cleanup_blockswap(model: torch.nn.Module) -> None:
    """从模型清理 BlockSwap 配置，恢复原始状态

    执行完整清理流程：
        1. 恢复所有 block 的原始 forward 方法
        2. 恢复 RoPE 模块的原始方法
        3. 恢复 I/O 组件的原始 forward 方法
        4. 将 I/O 组件移到卸载设备
        5. 恢复原始 model.to() 方法
        6. 删除所有 BlockSwap 相关属性
        7. 清除附加的 tensor 缓存

    Args:
        model: 要清理的 DiT 模型
    """
    with _BLOCKSWAP_LOCK:
        if not getattr(model, "_blockswap_active", False) and not hasattr(model, "_block_swap_config"):
            return

        logger.info("Starting BlockSwap cleanup")

        if hasattr(model, "blocks"):
            restored_count = 0
            for block in model.blocks:
                if hasattr(block, "_original_forward"):
                    block.forward = block._original_forward
                    delattr(block, "_original_forward")
                    restored_count += 1

                    for attr in ["_block_idx", "_blockswap_wrapped"]:
                        if hasattr(block, attr):
                            delattr(block, attr)

            if restored_count > 0:
                logger.info(f"Restored {restored_count} block forward methods")

        if hasattr(model, "_rope_patches"):
            for module, original_method in model._rope_patches:
                module.get_axial_freqs = original_method
                for attr in ["_rope_wrapped", "_original_get_axial_freqs", "_blockswap_wrapped"]:
                    if hasattr(module, attr):
                        delattr(module, attr)
            logger.info(f"Restored {len(model._rope_patches)} RoPE methods")
            delattr(model, "_rope_patches")

        if hasattr(model, "_io_swappers"):
            for module, _module_name in model._io_swappers:
                if hasattr(module, "_original_forward"):
                    module.forward = module._original_forward
                    for attr in ["_original_forward", "_module_name", "_is_io_wrapped"]:
                        if hasattr(module, attr):
                            delattr(module, attr)
            logger.info(f"Restored {len(model._io_swappers)} I/O components")
            delattr(model, "_io_swappers")

        if hasattr(model, "offload_device"):
            offload_device = model.offload_device
            moved_count = 0
            for name, module in model.named_children():
                if name != "blocks":
                    module.to(offload_device)
                    moved_count += 1
            if moved_count > 0:
                logger.info(f"Moved {moved_count} IO components to offload device")

        if hasattr(model, "_original_to"):
            model.to = model._original_to
            delattr(model, "_original_to")
            logger.info("Restored original .to() method")

        for attr in [
            "_blockswap_active",
            "blocks_to_swap",
            "main_device",
            "offload_device",
            "_block_swap_config",
            "_blockswap_bypass_protection",
        ]:
            if hasattr(model, attr):
                delattr(model, attr)

        if hasattr(model, "_tensor_cache_manager"):
            cache_mgr = model._tensor_cache_manager
            if cache_mgr is not None and cache_mgr.cache_size > 0:
                logger.info(f"Clearing {cache_mgr.cache_size} cached tensors from CPU cache")
                cache_mgr.clear()
            delattr(model, "_tensor_cache_manager")

        logger.info("BlockSwap cleanup complete")


# ===========================================================================
# 内存管理辅助函数（限频调用）
# ===========================================================================


def _clear_memory_if_needed() -> None:
    """仅在显存压力高时清理 GPU 缓存（空闲 < 5%）

    带调用频率限制：
        - 每 _MEMORY_CHECK_INTERVAL_BLOCKS 个块检查一次
        - 或至少间隔 _MEMORY_CHECK_INTERVAL_MS 毫秒
    避免在每次块交换后都执行 empty_cache() 带来性能开销。
    """
    global _last_memory_check_time, _memory_check_block_counter

    with _BLOCKSWAP_LOCK:
        _memory_check_block_counter += 1
        current_time = time.time()
        time_elapsed_ms = (current_time - _last_memory_check_time) * 1000

        if _memory_check_block_counter < _MEMORY_CHECK_INTERVAL_BLOCKS and time_elapsed_ms < _MEMORY_CHECK_INTERVAL_MS:
            return

        _memory_check_block_counter = 0
        _last_memory_check_time = current_time

    try:
        if torch.cuda.is_available():
            free_mem, total_mem = torch.cuda.mem_get_info()
            free_ratio = free_mem / total_mem if total_mem > 0 else 1.0
            if free_ratio < 0.05:
                torch.cuda.empty_cache()
    except Exception:
        pass

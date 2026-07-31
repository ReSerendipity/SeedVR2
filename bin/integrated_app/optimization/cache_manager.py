"""CPU 张量缓存管理器模块 - SeedVR2 视频修复项目

本模块实现推理过程中中间激活张量的自动 CPU 缓存机制，以降低 VRAM 压力。
当 GPU 显存紧张时，临时将中间激活张量迁移到 CPU RAM；需要后续计算时再恢复到 GPU。

所属项目: SeedVR2 (基于 ComfyUI-SeedVR2_VideoUpscaler 独立重构)
核心技术栈: PyTorch, threading (线程安全), OrderedDict (LRU 缓存)

参考实现:
    - RVRT 的 cpu_cache_length 概念，针对 SeedVR2 的 DiT 架构做了适配

核心功能:
    - 自动 VRAM 压力检测，可配置触发/恢复阈值
    - 线程安全的张量缓存/恢复操作（threading.Lock 保护）
    - 可配置的 CPU 缓存预算，防止 RAM 耗尽
    - 与 BlockSwap 模块无缝集成
    - 支持嵌套张量缓存上下文管理器

约束合规:
    - 模型权重（I/O 组件）按要求保留在 GPU 上
    - 仅中间激活张量缓存到 CPU
    - VRAM 压力缓解后自动清除缓存
"""

import logging
import threading
import time
from collections import OrderedDict
from typing import Any

import torch

logger = logging.getLogger(__name__)

VRAM_CACHE_TRIGGER_RATIO: float = 0.10
"""触发缓存的 VRAM 空闲比例阈值（默认: 10% 空闲）

当 GPU 空闲显存比例低于此值时，开始将张量缓存到 CPU。
"""

VRAM_RESTORE_RATIO: float = 0.20
"""恢复缓存的 VRAM 空闲比例阈值（默认: 20% 空闲）

当 GPU 空闲显存比例高于此值时，将缓存的张量恢复到 GPU。
"""

DEFAULT_CPU_CACHE_BUDGET_MB: int = 4096
"""CPU 张量缓存的最大内存预算，单位 MB（默认: 4GB）"""

DEFAULT_MAX_CACHED_TENSORS: int = 128
"""最大缓存张量数量（默认: 128 个）"""

_VRAM_INFO_CACHE_TTL: float = 0.1
"""VRAM 信息缓存有效期（秒），0.1 秒内复用查询结果"""

_vram_info_lock = threading.Lock()
"""VRAM 信息缓存的线程锁"""

_vram_free_ratio_cache: float = 1.0
"""缓存的 VRAM 空闲比例"""

_vram_cache_timestamp: float = 0.0
"""上次更新 VRAM 缓存的时间戳"""


def _get_vram_free_ratio() -> float:
    """获取 GPU 空闲显存占总显存的比例（内部函数，带 0.1 秒缓存）

    Returns:
        float: 0.0 到 1.0 之间的浮点数；CUDA 不可用时返回 1.0
    """
    global _vram_free_ratio_cache, _vram_cache_timestamp
    now = time.monotonic()
    with _vram_info_lock:
        if now - _vram_cache_timestamp < _VRAM_INFO_CACHE_TTL:
            return _vram_free_ratio_cache
        try:
            if torch.cuda.is_available():
                free_mem, total_mem = torch.cuda.mem_get_info()
                ratio = free_mem / total_mem if total_mem > 0 else 1.0
            else:
                ratio = 1.0
        except Exception:
            ratio = 1.0
        _vram_free_ratio_cache = ratio
        _vram_cache_timestamp = now
        return ratio


def _get_vram_usage_gb() -> float:
    """获取当前 VRAM 已使用量（GB，内部函数）

    Returns:
        float: 已分配 VRAM 大小，单位 GB；CUDA 不可用时返回 0.0
    """
    try:
        if torch.cuda.is_available():
            return torch.cuda.memory_allocated(0) / (1024 ** 3)
    except Exception:
        pass
    return 0.0


def _get_ram_usage_gb() -> float:
    """获取当前进程 RAM 使用量（GB，内部函数）

    通过 psutil 查询当前进程的常驻内存集（RSS）大小。

    Returns:
        float: 当前进程 RAM 使用量，单位 GB；psutil 不可用时返回 0.0
    """
    try:
        import psutil
        process = psutil.Process()
        return process.memory_info().rss / (1024 ** 3)
    except Exception:
        pass
    return 0.0


class CachedTensor:
    """CPU 缓存张量包装器

    轻量级容器，跟踪张量的原始设备（device）和数据类型（dtype），
    支持 CPU-GPU 之间的无缝迁移用于缓存目的。

    张量在初始化时立即移动到 CPU，释放对应的 GPU 显存；
    需要使用时通过 to_device() 方法恢复到目标设备。

    Attributes:
        name: 张量名称（用于日志/调试）
        original_dtype: 原始数据类型
        original_device: 原始设备
        shape: 张量形状
        numel: 张量元素总数
        size_mb: 张量大小，单位 MB

    Usage:
        cached = CachedTensor(gpu_tensor, name="layer_activations")
        # 张量现在在 CPU 上
        del gpu_tensor

        # 显存充足后需要使用时:
        restored = cached.to_device("cuda")
        # 张量回到 GPU
    """

    def __init__(self, tensor: torch.Tensor, name: str = ""):
        """初始化并缓存张量到 CPU

        Args:
            tensor: 要缓存的张量（将被迁移到 CPU）
            name: 可选名称，用于日志和调试
        """
        self.name = name
        self.original_dtype = tensor.dtype
        self.original_device = tensor.device
        self.shape = tensor.shape
        self.numel = tensor.numel()
        self.size_mb = tensor.numel() * tensor.element_size() / (1024 ** 2)

        # 主动迁移到 CPU（非阻塞不必要，此处为有意同步迁移）
        self._cpu_data = tensor.detach().cpu()
        self._is_on_device = False

    def to_device(self, device: torch.device | str) -> torch.Tensor:
        """将张量恢复到指定设备

        Args:
            device: 目标设备（通常是 'cuda' 或 'cuda:0'）

        Returns:
            torch.Tensor: 恢复到指定设备、保持原始 dtype 的张量
        """
        return self._cpu_data.to(device=device, dtype=self.original_dtype)

    @property
    def device(self) -> torch.device:
        """获取当前实际所在设备（属性）

        Returns:
            torch.device: 当前设备（始终是 CPU）
        """
        return self._cpu_data.device

    def __repr__(self) -> str:
        """对象字符串表示

        Returns:
            str: 包含名称、形状、dtype、大小的调试字符串
        """
        return (f"CachedTensor(name='{self.name}', shape={self.shape}, "
                f"dtype={self.original_dtype}, size={self.size_mb:.2f}MB)")


class TensorCacheManager:
    """推理中间张量的自动 CPU 缓存管理器

    监控 VRAM 压力，自动在 GPU 和 CPU RAM 之间缓存/恢复张量，
    防止长视频处理过程中出现 OOM（显存不足）错误。

    设计要点:
    - 使用 threading.Lock 保证线程安全
    - 基于 OrderedDict 实现 LRU（最近最少使用）淘汰
    - 与 BlockSwap 基础设施无缝集成
    - 可作为上下文管理器使用，退出时自动清理缓存

    缓存策略:
    - VRAM 空闲比例 < trigger_ratio 时: 开始缓存新张量
    - VRAM 空闲比例 > restore_ratio 时: 可恢复已缓存张量
    - CPU 缓存总大小超过 cpu_budget_mb 时: 停止缓存新张量
    - 缓存张量数超过 max_cached 时: 停止缓存新张量

    Usage:
        cache = TensorCacheManager(
            trigger_ratio=0.10,  # 空闲 < 10% 时缓存
            restore_ratio=0.20,  # 空闲 > 20% 时恢复
            cpu_budget_mb=4096,  # 最多 4GB CPU 缓存
        )

        # 推理过程中显存紧张时:
        cache.maybe_cache_tensor(activations, "layer_5_activations")

        # 后续需要使用时:
        restored = cache.restore_tensor("layer_5_activations", "cuda")

        # 或作为上下文管理器:
        with TensorCacheManager() as cache:
            ...
    """

    def __init__(
        self,
        trigger_ratio: float = VRAM_CACHE_TRIGGER_RATIO,
        restore_ratio: float = VRAM_RESTORE_RATIO,
        cpu_budget_mb: float = DEFAULT_CPU_CACHE_BUDGET_MB,
        max_cached: int = DEFAULT_MAX_CACHED_TENSORS,
    ):
        """初始化张量缓存管理器

        Args:
            trigger_ratio: 空闲 VRAM 比例低于此值时触发缓存（默认 0.10 = 10%）
            restore_ratio: 空闲 VRAM 比例高于此值时允许恢复（默认 0.20 = 20%）
            cpu_budget_mb: CPU 缓存张量的最大内存预算，单位 MB（默认 4096）
            max_cached: 最大缓存张量数量（默认 128）
        """
        self.trigger_ratio = trigger_ratio
        self.restore_ratio = restore_ratio
        self.cpu_budget_mb = cpu_budget_mb
        self.max_cached = max_cached

        self._cache: OrderedDict[str, CachedTensor] = OrderedDict()
        self._lock = threading.Lock()
        self._stats: dict[str, Any] = {
            "total_cached": 0,
            "total_restored": 0,
            "total_evicted": 0,
            "total_cache_mb": 0.0,
            "peak_cache_mb": 0.0,
        }

        logger.info(f"TensorCacheManager 初始化: trigger={trigger_ratio:.0%}, "
                     f"restore={restore_ratio:.0%}, budget={cpu_budget_mb}MB")

    def should_cache(self) -> bool:
        """检查当前 VRAM 压力是否需要缓存张量

        Returns:
            bool: 空闲 VRAM 低于触发阈值返回 True
        """
        return _get_vram_free_ratio() < self.trigger_ratio

    def should_restore(self) -> bool:
        """检查 VRAM 压力是否缓解到可以恢复缓存张量

        Returns:
            bool: 空闲 VRAM 高于恢复阈值返回 True
        """
        return _get_vram_free_ratio() > self.restore_ratio

    def maybe_cache_tensor(
        self,
        tensor: torch.Tensor,
        name: str,
    ) -> bool:
        """当 VRAM 压力较高时，有条件地将张量缓存到 CPU

        执行以下检查:
        1. VRAM 压力是否达到触发阈值
        2. 缓存数量是否达到上限
        3. CPU 缓存预算是否会超限

        通过所有检查后才实际执行缓存操作。

        Args:
            tensor: 可能需要缓存的张量
            name: 张量的唯一名称（用于检索）

        Returns:
            bool: 张量被缓存返回 True；跳过返回 False
        """
        if not self.should_cache():
            return False

        tensor_size_mb = tensor.numel() * tensor.element_size() / (1024 ** 2)

        with self._lock:
            if len(self._cache) >= self.max_cached:
                logger.debug(f"缓存已满 ({len(self._cache)}/{self.max_cached}), "
                             f"跳过缓存 '{name}'")
                return False

            current_cache_mb = self._stats["total_cache_mb"]
            if current_cache_mb + tensor_size_mb > self.cpu_budget_mb:
                logger.debug(f"CPU 缓存预算超出 ({current_cache_mb:.0f}MB + "
                             f"{tensor_size_mb:.0f}MB > {self.cpu_budget_mb}MB), "
                             f"跳过缓存 '{name}'")
                return False

            cached = CachedTensor(tensor, name)
            self._cache[name] = cached
            self._stats["total_cached"] += 1
            self._stats["total_cache_mb"] += tensor_size_mb
            self._stats["peak_cache_mb"] = max(
                self._stats["peak_cache_mb"],
                self._stats["total_cache_mb"]
            )

            logger.debug(f"已缓存张量 '{name}' 到 CPU: {cached} "
                         f"(VRAM 空闲: {_get_vram_free_ratio():.0%})")
            return True

    def restore_tensor(
        self,
        name: str,
        device: torch.device | str = "cuda",
    ) -> torch.Tensor | None:
        """将指定名称的缓存张量恢复到目标设备

        从缓存中移除并返回张量，更新统计信息。

        Args:
            name: 要恢复的缓存张量名称
            device: 目标设备（默认 'cuda'）

        Returns:
            torch.Tensor | None: 恢复后的张量；名称不在缓存中返回 None
        """
        with self._lock:
            if name not in self._cache:
                return None

            cached = self._cache.pop(name)
            self._stats["total_restored"] += 1
            self._stats["total_cache_mb"] -= cached.size_mb

            logger.debug(f"已将张量 '{name}' 从 CPU 恢复到 {device}")

            return cached.to_device(device)

    def restore_all(self, device: torch.device | str = "cuda") -> dict[str, torch.Tensor]:
        """将所有缓存张量恢复到指定设备

        Args:
            device: 目标设备（默认 'cuda'）

        Returns:
            dict[str, torch.Tensor]: 名称→恢复后张量的映射字典
        """
        result: dict[str, torch.Tensor] = {}
        with self._lock:
            names = list(self._cache.keys())

        for name in names:
            restored = self.restore_tensor(name, device)
            if restored is not None:
                result[name] = restored

        return result

    def evict_oldest(self, count: int = 1) -> int:
        """淘汰最旧的缓存张量以释放 CPU 内存

        使用 LRU（最近最少使用）策略，淘汰最早添加的张量。

        Args:
            count: 要淘汰的张量数量

        Returns:
            int: 实际淘汰的张量数量
        """
        evicted = 0
        with self._lock:
            for _ in range(min(count, len(self._cache))):
                name, cached = self._cache.popitem(last=False)
                self._stats["total_evicted"] += 1
                self._stats["total_cache_mb"] -= cached.size_mb
                evicted += 1
                logger.debug(f"已淘汰缓存张量 '{name}'")

        return evicted

    def clear(self) -> None:
        """清除所有缓存张量"""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._stats["total_cache_mb"] = 0.0
            if count > 0:
                logger.info(f"已从 CPU 缓存清除 {count} 个张量")

    @property
    def cache_size(self) -> int:
        """当前缓存的张量数量（属性）

        Returns:
            int: 当前缓存张量数
        """
        with self._lock:
            return len(self._cache)

    @property
    def cache_memory_mb(self) -> float:
        """缓存张量占用的总 CPU 内存，单位 MB（属性）

        Returns:
            float: 缓存占用内存，单位 MB
        """
        with self._lock:
            return self._stats["total_cache_mb"]

    def get_stats(self) -> dict[str, Any]:
        """获取缓存统计信息

        Returns:
            dict: 包含以下字段的统计字典:
                - total_cached (int): 累计缓存次数
                - total_restored (int): 累计恢复次数
                - total_evicted (int): 累计淘汰次数
                - total_cache_mb (float): 当前缓存总大小（MB）
                - peak_cache_mb (float): 峰值缓存大小（MB）
                - current_cached (int): 当前缓存张量数
                - vram_free_ratio (float): 当前 VRAM 空闲比例
                - vram_usage_gb (float): 当前 VRAM 使用量（GB）
                - ram_usage_gb (float): 当前进程 RAM 使用量（GB）
        """
        with self._lock:
            return {
                **self._stats,
                "current_cached": len(self._cache),
                "vram_free_ratio": _get_vram_free_ratio(),
                "vram_usage_gb": _get_vram_usage_gb(),
                "ram_usage_gb": _get_ram_usage_gb(),
            }

    def __enter__(self) -> "TensorCacheManager":
        """上下文管理器入口

        Returns:
            TensorCacheManager: 自身实例
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """上下文管理器退出，自动清除所有缓存

        Args:
            exc_type: 异常类型
            exc_val: 异常值
            exc_tb: 异常回溯

        Returns:
            bool: 始终返回 False（不抑制异常）
        """
        self.clear()
        return False


class cached_activation:
    """VRAM 感知的自动张量缓存上下文管理器

    封装 TensorCacheManager，提供更简洁的 API 用于推理阶段的激活缓存。
    退出上下文时，如果 VRAM 压力缓解，自动恢复所有缓存的张量。

    Usage:
        with cached_activation(cache_manager) as cache:
            # 前向传播产生中间张量
            x = model.layer1(input)
            cache.maybe_cache(x, "layer1_out")  # VRAM 紧张时自动缓存

            # ... 后续层 ...

            # 需要时恢复
            x_restored = cache.restore_tensor("layer1_out", "cuda")
            output = model.layer5(x_restored)

        # 退出时自动清理或恢复
    """

    def __init__(self, manager: TensorCacheManager | None = None):
        """初始化激活缓存上下文

        Args:
            manager: 张量缓存管理器实例；None 时创建新实例
        """
        self.manager = manager or TensorCacheManager()

    def __enter__(self) -> TensorCacheManager:
        """上下文管理器入口

        Returns:
            TensorCacheManager: 缓存管理器实例
        """
        return self.manager

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """上下文管理器退出

        如果 VRAM 压力已缓解且有缓存张量，自动恢复所有缓存；
        否则保留缓存（可由外部代码继续管理）。

        Args:
            exc_type: 异常类型
            exc_val: 异常值
            exc_tb: 异常回溯

        Returns:
            bool: 始终返回 False（不抑制异常）
        """
        if self.manager.should_restore() and self.manager.cache_size > 0:
            logger.info(f"VRAM 压力缓解，自动恢复 {self.manager.cache_size} 个缓存张量 "
                        f"(VRAM 空闲: {_get_vram_free_ratio():.0%})")
            self.manager.restore_all()
        return False


_global_cache_manager: TensorCacheManager | None = None
"""全局单例缓存管理器实例"""

_global_cache_lock = threading.Lock()
"""全局单例的线程锁（双重检查锁定需要）"""


def get_cache_manager() -> TensorCacheManager:
    """获取或创建全局张量缓存管理器单例

    使用双重检查锁定（double-checked locking）模式保证线程安全的单例创建。

    Returns:
        TensorCacheManager: 全局单例实例
    """
    global _global_cache_manager
    if _global_cache_manager is None:
        with _global_cache_lock:
            if _global_cache_manager is None:
                _global_cache_manager = TensorCacheManager()
    return _global_cache_manager


def clear_global_cache() -> None:
    """清除全局张量缓存

    便捷函数，获取全局管理器并调用 clear()。
    """
    manager = get_cache_manager()
    manager.clear()

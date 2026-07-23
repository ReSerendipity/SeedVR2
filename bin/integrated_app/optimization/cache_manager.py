"""
CPU Tensor Cache Manager for SeedVR2

Implements automatic CPU caching of intermediate tensors to reduce VRAM pressure
during inference. When GPU memory is low, activation tensors are temporarily moved
to CPU RAM and restored when needed for subsequent computation.

Adapted from RVRT's cpu_cache_length concept, modified for SeedVR2's DiT architecture.

Key Features:
- Automatic VRAM pressure detection with configurable thresholds
- Thread-safe tensor caching/un-caching operations
- Configurable CPU cache budget to prevent RAM exhaustion
- Seamless integration with BlockSwap module
- Support for nested tensor cache contexts

Constraint Compliance:
- Model weights (I/O components) remain on GPU as required
- Only intermediate activation tensors are cached to CPU
- Cache is automatically cleared when VRAM pressure subsides
"""

import logging
import threading
from collections import OrderedDict
from typing import Any

import torch

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

# VRAM free ratio below which caching is triggered (default: 10% free)
VRAM_CACHE_TRIGGER_RATIO = 0.10

# VRAM free ratio above which cached tensors are restored (default: 20% free)
VRAM_RESTORE_RATIO = 0.20

# Maximum CPU memory budget for tensor cache in MB (default: 4GB)
DEFAULT_CPU_CACHE_BUDGET_MB = 4096

# Maximum number of cached tensors
DEFAULT_MAX_CACHED_TENSORS = 128


# ---------------------------------------------------------------------------
# VRAM monitoring
# ---------------------------------------------------------------------------

def _get_vram_free_ratio() -> float:
    """Get the ratio of free VRAM to total VRAM.

    Returns:
        Float between 0.0 and 1.0, or 1.0 if CUDA is unavailable.
    """
    try:
        if torch.cuda.is_available():
            free_mem, total_mem = torch.cuda.mem_get_info()
            return free_mem / total_mem if total_mem > 0 else 1.0
    except Exception:
        pass
    return 1.0


def _get_vram_usage_gb() -> float:
    """Get current VRAM usage in GB."""
    try:
        if torch.cuda.is_available():
            return torch.cuda.memory_allocated(0) / (1024 ** 3)
    except Exception:
        pass
    return 0.0


def _get_ram_usage_gb() -> float:
    """Get current process RAM usage in GB."""
    try:
        import psutil
        process = psutil.Process()
        return process.memory_info().rss / (1024 ** 3)
    except Exception:
        pass
    return 0.0


# ---------------------------------------------------------------------------
# Cached tensor wrapper
# ---------------------------------------------------------------------------

class CachedTensor:
    """A wrapper that stores a tensor on CPU and can restore it to GPU.

    This is a lightweight container that tracks the original device and dtype
    of a tensor, allowing seamless CPU-GPU transfers for caching purposes.

    Example:
        cached = CachedTensor(gpu_tensor)
        # Tensor is now on CPU
        del gpu_tensor  # Free VRAM

        # Later, when VRAM is available:
        restored = cached.to_device(target_device)
        # Tensor is back on GPU
    """

    def __init__(self, tensor: torch.Tensor, name: str = ""):
        """Cache a tensor to CPU.

        Args:
            tensor: The tensor to cache (will be moved to CPU)
            name: Optional name for logging/debugging
        """
        self.name = name
        self.original_dtype = tensor.dtype
        self.original_device = tensor.device
        self.shape = tensor.shape
        self.numel = tensor.numel()
        self.size_mb = tensor.numel() * tensor.element_size() / (1024 ** 2)

        # Move to CPU (non-blocking not needed here, this is intentional)
        self._cpu_data = tensor.detach().cpu()
        self._is_on_device = False

    def to_device(self, device: torch.device | str) -> torch.Tensor:
        """Restore tensor to the specified device.

        Args:
            device: Target device (typically 'cuda' or 'cuda:0')

        Returns:
            Tensor restored to the specified device with original dtype
        """
        if not self._is_on_device:
            return self._cpu_data.to(device=device, dtype=self.original_dtype)
        return self._cpu_data.to(device=device, dtype=self.original_dtype)

    @property
    def device(self) -> torch.device:
        """Return the current effective device."""
        return self._cpu_data.device

    def __repr__(self) -> str:
        return (f"CachedTensor(name='{self.name}', shape={self.shape}, "
                f"dtype={self.original_dtype}, size={self.size_mb:.2f}MB)")


# ---------------------------------------------------------------------------
# Tensor Cache Manager
# ---------------------------------------------------------------------------

class TensorCacheManager:
    """Manages automatic CPU caching of intermediate tensors during inference.

    This manager monitors VRAM pressure and automatically caches/restores
    tensors to/from CPU RAM to prevent OOM errors during long video processing.

    The manager is designed to be thread-safe and integrates with the existing
    BlockSwap infrastructure.

    Usage:
        cache = TensorCacheManager(
            trigger_ratio=0.10,  # Cache when < 10% VRAM free
            restore_ratio=0.20,  # Restore when > 20% VRAM free
            cpu_budget_mb=4096,  # Max 4GB CPU cache
        )

        # During inference, when VRAM is low:
        cache.maybe_cache_tensor(activations, "layer_5_activations")

        # Later, when needed:
        restored = cache.restore_tensor("layer_5_activations", "cuda")
    """

    def __init__(
        self,
        trigger_ratio: float = VRAM_CACHE_TRIGGER_RATIO,
        restore_ratio: float = VRAM_RESTORE_RATIO,
        cpu_budget_mb: float = DEFAULT_CPU_CACHE_BUDGET_MB,
        max_cached: int = DEFAULT_MAX_CACHED_TENSORS,
    ):
        """Initialize the tensor cache manager.

        Args:
            trigger_ratio: Cache tensors when free VRAM ratio drops below this
            restore_ratio: Restore tensors when free VRAM ratio exceeds this
            cpu_budget_mb: Maximum CPU memory (MB) for cached tensors
            max_cached: Maximum number of tensors to cache
        """
        self.trigger_ratio = trigger_ratio
        self.restore_ratio = restore_ratio
        self.cpu_budget_mb = cpu_budget_mb
        self.max_cached = max_cached

        self._cache: OrderedDict[str, CachedTensor] = OrderedDict()
        self._lock = threading.Lock()
        self._stats = {
            "total_cached": 0,
            "total_restored": 0,
            "total_evicted": 0,
            "total_cache_mb": 0.0,
            "peak_cache_mb": 0.0,
        }

        logger.info(f"TensorCacheManager initialized: trigger={trigger_ratio:.0%}, "
                     f"restore={restore_ratio:.0%}, budget={cpu_budget_mb}MB")

    def should_cache(self) -> bool:
        """Check if VRAM pressure warrants caching tensors.

        Returns:
            True if free VRAM is below the trigger threshold
        """
        return _get_vram_free_ratio() < self.trigger_ratio

    def should_restore(self) -> bool:
        """Check if VRAM pressure has subsided enough to restore cached tensors.

        Returns:
            True if free VRAM exceeds the restore threshold
        """
        return _get_vram_free_ratio() > self.restore_ratio

    def maybe_cache_tensor(
        self,
        tensor: torch.Tensor,
        name: str,
    ) -> bool:
        """Conditionally cache a tensor to CPU if VRAM pressure is high.

        Args:
            tensor: Tensor to potentially cache
            name: Unique name for the tensor (used for retrieval)

        Returns:
            True if tensor was cached, False if skipped
        """
        if not self.should_cache():
            return False

        # Check budget constraints
        tensor_size_mb = tensor.numel() * tensor.element_size() / (1024 ** 2)

        with self._lock:
            if len(self._cache) >= self.max_cached:
                logger.debug(f"Cache full ({len(self._cache)}/{self.max_cached}), "
                             f"skipping cache for '{name}'")
                return False

            current_cache_mb = self._stats["total_cache_mb"]
            if current_cache_mb + tensor_size_mb > self.cpu_budget_mb:
                logger.debug(f"CPU cache budget exceeded ({current_cache_mb:.0f}MB + "
                             f"{tensor_size_mb:.0f}MB > {self.cpu_budget_mb}MB), "
                             f"skipping cache for '{name}'")
                return False

            # Perform the cache
            cached = CachedTensor(tensor, name)
            self._cache[name] = cached
            self._stats["total_cached"] += 1
            self._stats["total_cache_mb"] += tensor_size_mb
            self._stats["peak_cache_mb"] = max(
                self._stats["peak_cache_mb"],
                self._stats["total_cache_mb"]
            )

            logger.info(f"Cached tensor '{name}' to CPU: {cached} "
                         f"(VRAM free: {_get_vram_free_ratio():.0%})")
            return True

    def restore_tensor(
        self,
        name: str,
        device: torch.device | str = "cuda",
    ) -> torch.Tensor | None:
        """Restore a cached tensor to the specified device.

        Args:
            name: Name of the cached tensor to restore
            device: Target device (default: 'cuda')

        Returns:
            Restored tensor, or None if not found in cache
        """
        with self._lock:
            if name not in self._cache:
                return None

            cached = self._cache.pop(name)
            self._stats["total_restored"] += 1
            self._stats["total_cache_mb"] -= cached.size_mb

            logger.debug(f"Restored tensor '{name}' from CPU to {device}")

            return cached.to_device(device)

    def restore_all(self, device: torch.device | str = "cuda") -> dict[str, torch.Tensor]:
        """Restore all cached tensors to the specified device.

        Args:
            device: Target device (default: 'cuda')

        Returns:
            Dictionary mapping tensor names to restored tensors
        """
        result = {}
        with self._lock:
            names = list(self._cache.keys())

        for name in names:
            restored = self.restore_tensor(name, device)
            if restored is not None:
                result[name] = restored

        return result

    def evict_oldest(self, count: int = 1) -> int:
        """Evict the oldest cached tensors to free CPU memory.

        Args:
            count: Number of tensors to evict

        Returns:
            Number of tensors actually evicted
        """
        evicted = 0
        with self._lock:
            for _ in range(min(count, len(self._cache))):
                name, cached = self._cache.popitem(last=False)
                self._stats["total_evicted"] += 1
                self._stats["total_cache_mb"] -= cached.size_mb
                evicted += 1
                logger.debug(f"Evicted cached tensor '{name}'")

        return evicted

    def clear(self) -> None:
        """Clear all cached tensors."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._stats["total_cache_mb"] = 0.0
            if count > 0:
                logger.info(f"Cleared {count} cached tensors from CPU cache")

    @property
    def cache_size(self) -> int:
        """Number of currently cached tensors."""
        with self._lock:
            return len(self._cache)

    @property
    def cache_memory_mb(self) -> float:
        """Total CPU memory used by cached tensors in MB."""
        return self._stats["total_cache_mb"]

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            return {
                **self._stats,
                "current_cached": len(self._cache),
                "vram_free_ratio": _get_vram_free_ratio(),
                "vram_usage_gb": _get_vram_usage_gb(),
                "ram_usage_gb": _get_ram_usage_gb(),
            }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.clear()
        return False


# ---------------------------------------------------------------------------
# Context manager for automatic cache restore
# ---------------------------------------------------------------------------

class cached_activation:
    """Context manager for automatic VRAM-aware tensor caching.

    Usage:
        with cached_activation(cache_manager) as cache:
            # Forward pass produces intermediate tensor
            x = model.layer1(input)
            cache.maybe_cache(x, "layer1_out")  # Auto-cached if VRAM low

            # ... later layers ...

            # Restore when needed
            x_restored = cache.restore_tensor("layer1_out", "cuda")
            output = model.layer5(x_restored)
    """

    def __init__(self, manager: TensorCacheManager | None = None):
        self.manager = manager or TensorCacheManager()

    def __enter__(self) -> TensorCacheManager:
        return self.manager

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Auto-restore cached tensors if VRAM pressure has subsided
        if self.manager.should_restore() and self.manager.cache_size > 0:
            logger.info(f"Auto-restoring {self.manager.cache_size} cached tensors "
                        f"(VRAM free: {_get_vram_free_ratio():.0%})")
            self.manager.restore_all()
        return False


# ---------------------------------------------------------------------------
# Global singleton for easy access
# ---------------------------------------------------------------------------

_global_cache_manager: TensorCacheManager | None = None
_global_cache_lock = threading.Lock()


def get_cache_manager() -> TensorCacheManager:
    """Get or create the global tensor cache manager singleton.

    Returns:
        The global TensorCacheManager instance
    """
    global _global_cache_manager
    if _global_cache_manager is None:
        with _global_cache_lock:
            if _global_cache_manager is None:
                _global_cache_manager = TensorCacheManager()
    return _global_cache_manager


def clear_global_cache() -> None:
    """Clear the global tensor cache."""
    manager = get_cache_manager()
    manager.clear()

"""GPU 后端抽象层 - 仅支持 NVIDIA CUDA

使用 Strategy 模式实现后端分发，避免 if/elif 链。
支持的后端:
- CUDA (NVIDIA GPUs)

注意: SeedVR2 模型仅官方支持 NVIDIA GPU，不支持 CPU 推理。
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class GPUBackend(Enum):
    """支持的 GPU 后端"""
    CUDA = "cuda"              # NVIDIA GPUs
    UNAVAILABLE = "unavailable"  # 未检测到可用 GPU（降级模式）


@dataclass
class GPUInfo:
    """GPU 信息"""
    backend: GPUBackend
    name: str
    total_vram_mb: int
    available_vram_mb: int
    utilization_pct: float
    driver_version: str = ""
    cuda_version: str = ""


# ---------------------------------------------------------------------------
# Strategy 抽象基类与具体策略
# ---------------------------------------------------------------------------

class _GPUStrategy(ABC):
    """GPU 后端策略抽象基类"""

    @abstractmethod
    def detect(self) -> bool:
        """检测此后端是否可用"""
        ...

    @abstractmethod
    def device_str(self) -> str:
        """返回 torch 设备字符串"""
        ...

    @abstractmethod
    def get_info(self) -> dict:
        """获取 GPU 信息字典"""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """检查此后端当前是否可用"""
        ...

    def synchronize(self) -> None:
        """同步设备"""
        raise NotImplementedError

    def get_process_group_backend(self) -> str:
        """获取分布式训练进程组后端（默认 gloo）"""
        return "gloo"


class _CUDAStrategy(_GPUStrategy):
    """NVIDIA CUDA 后端策略"""

    def detect(self) -> bool:
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False

    def device_str(self) -> str:
        return "cuda"

    def get_info(self) -> dict:
        import torch
        name = torch.cuda.get_device_name(0)
        total_vram = torch.cuda.get_device_properties(0).total_memory
        free_memory, total_memory = torch.cuda.mem_get_info(0)
        used = total_memory - free_memory
        available_vram_mb = free_memory // (1024 * 1024)
        utilization = (used / total_memory) * 100 if total_memory > 0 else 0
        cuda_version = torch.version.cuda or ""
        return {
            'name': name,
            'total_vram': total_vram,
            'available_vram_mb': available_vram_mb,
            'utilization': utilization,
            'cuda_version': cuda_version,
        }

    def is_available(self) -> bool:
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False

    def synchronize(self) -> None:
        import torch
        torch.cuda.synchronize()

    def get_process_group_backend(self) -> str:
        return "nccl"


# ---------------------------------------------------------------------------
# 策略映射与检测优先级
# ---------------------------------------------------------------------------

_STRATEGY_MAP: dict[GPUBackend, _GPUStrategy] = {
    GPUBackend.CUDA: _CUDAStrategy(),
}

# 检测优先级: 仅 NVIDIA CUDA
_DETECTION_ORDER = [
    GPUBackend.CUDA,
]


# ---------------------------------------------------------------------------
# GPUBackendManager - 统一 GPU 后端管理器
# ---------------------------------------------------------------------------

class GPUBackendManager:
    """GPU 后端管理器

    使用 Strategy 模式实现后端分发，自动检测可用 GPU 后端并提供统一 API。
    仅支持 NVIDIA CUDA，不支持 CPU 推理。

    Usage:
        manager = GPUBackendManager()
        backend = manager.backend
        device = manager.device_str
        info = manager.get_gpu_info()
    """

    def __init__(self):
        self._backend: GPUBackend | None = None
        self._strategy: _GPUStrategy | None = None
        self._device_name: str = ""
        self._total_vram: int = 0
        self._detect_backend()

    def _detect_backend(self):
        """自动检测可用的 NVIDIA GPU 后端

        按优先级顺序遍历策略，选择第一个检测成功的后端。
        如果未检测到 NVIDIA GPU，直接抛出异常。
        """
        for backend_type in _DETECTION_ORDER:
            strategy = _STRATEGY_MAP[backend_type]
            try:
                if strategy.detect():
                    self._backend = backend_type
                    self._strategy = strategy
                    try:
                        info = strategy.get_info()
                        self._device_name = info.get('name', str(backend_type.value))
                        self._total_vram = info.get('total_vram', 0)
                    except Exception as e:
                        logger.debug(f"获取 {backend_type.name} 信息失败: {e}")
                        self._device_name = str(backend_type.value)
                        self._total_vram = 0
                    logger.info(f"检测到 {backend_type.name} 后端: {self._device_name}")
                    return
            except Exception as e:
                logger.debug(f"检测 {backend_type.name} 后端失败: {e}")
                continue

        # 未检测到 NVIDIA GPU，进入降级模式
        self._backend = GPUBackend.UNAVAILABLE
        self._strategy = None
        self._device_name = "未检测到 NVIDIA GPU"
        self._total_vram = 0
        logger.warning(
            "未检测到 NVIDIA GPU。应用将以降级模式启动，推理功能不可用。"
            "SeedVR2 模型仅支持 NVIDIA CUDA GPU 推理。"
        )

    @property
    def backend(self) -> GPUBackend:
        return self._backend

    @property
    def device_name(self) -> str:
        return self._device_name

    @property
    def is_gpu_available(self) -> bool:
        return self._backend == GPUBackend.CUDA

    @property
    def device_str(self) -> str:
        """返回 torch 设备字符串"""
        if self._strategy is not None:
            return self._strategy.device_str()
        return "cuda"

    def get_gpu_info(self) -> GPUInfo:
        """获取当前 GPU 信息"""
        if self._strategy is not None and self._backend != GPUBackend.UNAVAILABLE:
            try:
                info = self._strategy.get_info()
                return GPUInfo(
                    backend=self._backend,
                    name=info.get('name', self._device_name),
                    total_vram_mb=info.get('total_vram', self._total_vram) // (1024 * 1024),
                    available_vram_mb=info.get('available_vram_mb', 0),
                    utilization_pct=info.get('utilization', 0.0),
                    driver_version="",
                    cuda_version=info.get('cuda_version', ""),
                )
            except Exception as e:
                logger.error(f"获取 GPU 信息失败: {e}")

        # 降级模式：返回 UNAVAILABLE 信息
        return GPUInfo(
            backend=self._backend,
            name=self._device_name,
            total_vram_mb=0,
            available_vram_mb=0,
            utilization_pct=0.0,
        )

    def can_load_model(self, required_vram_mb: int) -> bool:
        """检查是否有足够显存加载模型"""
        if self._backend == GPUBackend.UNAVAILABLE:
            return False
        info = self.get_gpu_info()
        return info.available_vram_mb >= required_vram_mb

    def get_recommended_model_size(self) -> str:
        """根据显存推荐模型大小"""
        info = self.get_gpu_info()
        if info.total_vram_mb >= 24000:  # 24GB+
            return "7b"
        elif info.total_vram_mb >= 16000:  # 16GB+
            return "3b"
        else:
            return "3b"  # 显存不足也推荐3b，但会警告

    def get_device(self) -> str:
        """获取 torch.device"""
        return self.device_str

    def synchronize(self) -> None:
        """同步当前设备"""
        if self._strategy is not None:
            self._strategy.synchronize()

    def get_process_group_backend(self) -> str:
        """获取分布式训练进程组后端"""
        if self._strategy is not None:
            return self._strategy.get_process_group_backend()
        return "gloo"


# 全局实例
gpu_manager = GPUBackendManager()

"""GPU 后端抽象层模块 - SeedVR2 视频修复项目

本模块提供 GPU 后端的抽象与统一管理接口，采用 Strategy 设计模式实现后端分发，
避免冗长的 if/elif 条件链。当前仅支持 NVIDIA CUDA GPU 后端，未检测到可用 GPU 时
进入降级模式（推理功能不可用）。

所属项目: SeedVR2 (基于 ComfyUI-SeedVR2_VideoUpscaler 独立重构)
核心技术栈: PyTorch, CUDA, Strategy Pattern, ABC 抽象基类

注意事项:
    - SeedVR2 模型官方仅支持 NVIDIA CUDA GPU 推理，不支持 CPU/MPS 推理
    - 启动时自动检测可用 GPU 后端，检测失败时记录警告并进入降级模式
    - 全局单例 `gpu_manager` 供应用各模块统一调用
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

_GPU_INFO_CACHE_TTL = 0.5
_MODEL_LOAD_CACHE_TTL = 0.5
_VRAM_SAFETY_MARGIN = 1.1


class GPUBackend(Enum):
    """支持的 GPU 后端类型枚举

    Attributes:
        CUDA: NVIDIA CUDA 后端（主力计算后端）
        UNAVAILABLE: 未检测到可用 GPU（降级模式，推理不可用）
    """

    CUDA = "cuda"  # NVIDIA GPUs
    UNAVAILABLE = "unavailable"  # 未检测到可用 GPU（降级模式）


@dataclass
class GPUInfo:
    """GPU 硬件信息数据类

    存储 GPU 设备的完整硬件信息，包括显存、利用率、驱动版本等，
    用于系统状态展示、模型加载预检和兼容性判断。

    Attributes:
        backend: GPU 后端类型
        name: GPU 设备名称（如 "NVIDIA GeForce RTX 4090"）
        total_vram_mb: 总显存大小（MB）
        available_vram_mb: 当前可用显存（MB）
        utilization_pct: 当前显存利用率百分比（0-100）
        driver_version: NVIDIA 驱动版本号（暂未实现）
        cuda_version: CUDA 运行时版本号
    """

    backend: GPUBackend
    name: str
    total_vram_mb: int
    available_vram_mb: int
    utilization_pct: float
    driver_version: str = ""
    cuda_version: str = ""


class _GPUStrategy(ABC):
    """GPU 后端策略抽象基类

    定义所有 GPU 后端策略必须实现的统一接口，遵循 Strategy 设计模式。
    每个具体后端（如 CUDA）需继承此类并实现所有抽象方法。

    Note:
        这是内部抽象基类，不应直接实例化，应通过 GPUBackendManager 使用。
    """

    @abstractmethod
    def detect(self) -> bool:
        """检测此后端在当前系统中是否可用

        Returns:
            bool: 后端可用返回 True，否则返回 False
        """
        ...

    @abstractmethod
    def device_str(self) -> str:
        """返回 PyTorch 设备字符串标识

        Returns:
            str: PyTorch 设备字符串，如 "cuda"、"cpu"
        """
        ...

    @abstractmethod
    def get_info(self) -> dict:
        """获取 GPU 硬件详细信息字典

        Returns:
            dict: 包含设备名称、显存、CUDA版本等信息的字典
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """检查此后端当前是否可用（运行时检查）

        Returns:
            bool: 当前可用返回 True，否则返回 False
        """
        ...

    def synchronize(self) -> None:
        """同步当前设备，等待所有 GPU 操作完成

        Raises:
            NotImplementedError: 默认实现抛出异常，子类需覆盖
        """
        raise NotImplementedError

    def get_process_group_backend(self) -> str:
        """获取分布式训练进程组通信后端

        Returns:
            str: 进程组后端名称，默认返回 "gloo"（CPU 通信后端）
        """
        return "gloo"


class _CUDAStrategy(_GPUStrategy):
    """NVIDIA CUDA 后端具体策略实现

    实现 NVIDIA CUDA GPU 的检测、设备管理和信息查询功能。
    使用 PyTorch CUDA API 与 GPU 交互。
    """

    def detect(self) -> bool:
        """检测 CUDA 后端是否可用

        尝试导入 torch 并调用 torch.cuda.is_available() 检测。

        Returns:
            bool: CUDA 可用返回 True，torch 未安装或 CUDA 不可用返回 False
        """
        try:
            import torch

            return torch.cuda.is_available()
        except ImportError:
            return False

    def device_str(self) -> str:
        """返回 CUDA 设备字符串

        Returns:
            str: 固定返回 "cuda"
        """
        return "cuda"

    def get_info(self) -> dict:
        """获取 CUDA GPU 详细硬件信息

        使用 PyTorch CUDA API 查询设备 0 的显存、名称、利用率等信息。

        Returns:
            dict: 包含以下键的字典:
                - name (str): GPU 设备名称
                - total_vram (int): 总显存（字节）
                - available_vram_mb (int): 可用显存（MB）
                - utilization (float): 显存利用率百分比
                - cuda_version (str): CUDA 版本字符串

        Raises:
            ImportError: PyTorch 未安装
            RuntimeError: CUDA 运行时错误或设备不可访问
            AssertionError: CUDA 设备断言失败
        """
        try:
            import torch
        except ImportError as e:
            logger.error(f"PyTorch 未安装，无法获取 CUDA 信息: {e}")
            raise

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA 当前不可用")

        try:
            name = torch.cuda.get_device_name(0)
        except RuntimeError as e:
            logger.error(f"获取 CUDA 设备名称失败: {e}")
            raise RuntimeError(f"无法获取 GPU 设备名称: {e}") from e

        try:
            props = torch.cuda.get_device_properties(0)
            total_vram = props.total_memory
        except RuntimeError as e:
            logger.error(f"获取 CUDA 设备属性失败: {e}")
            raise RuntimeError(f"无法获取 GPU 设备属性: {e}") from e

        try:
            free_memory, total_memory = torch.cuda.mem_get_info(0)
        except RuntimeError as e:
            logger.error(f"获取 CUDA 显存信息失败: {e}")
            raise RuntimeError(f"无法获取 GPU 显存信息: {e}") from e

        used = total_memory - free_memory
        available_vram_mb = free_memory // (1024 * 1024)
        utilization = (used / total_memory) * 100 if total_memory > 0 else 0
        cuda_version = torch.version.cuda or ""

        return {
            "name": name,
            "total_vram": total_vram,
            "available_vram_mb": available_vram_mb,
            "utilization": utilization,
            "cuda_version": cuda_version,
        }

    def is_available(self) -> bool:
        """运行时检查 CUDA 是否可用

        Returns:
            bool: CUDA 当前可用返回 True
        """
        try:
            import torch

            return torch.cuda.is_available()
        except ImportError:
            return False

    def synchronize(self) -> None:
        """同步 CUDA 设备，阻塞等待所有 GPU 操作完成

        用于计时或确保内存操作完成的精确同步点。
        """
        import torch

        torch.cuda.synchronize()

    def get_process_group_backend(self) -> str:
        """获取 CUDA 对应的分布式进程组后端

        Returns:
            str: 返回 "nccl"（NVIDIA Collective Communications Library）
        """
        return "nccl"


# 策略映射表：后端类型 -> 策略实例
_STRATEGY_MAP: dict[GPUBackend, _GPUStrategy] = {
    GPUBackend.CUDA: _CUDAStrategy(),
}

# 后端检测优先级顺序：当前仅检测 NVIDIA CUDA
_DETECTION_ORDER = [
    GPUBackend.CUDA,
]


class GPUBackendManager:
    """GPU 后端统一管理器

    使用 Strategy 模式自动检测可用 GPU 后端并提供统一 API，
    封装不同后端的差异，为上层应用提供一致的 GPU 访问接口。

    仅支持 NVIDIA CUDA，不支持 CPU 推理。未检测到 GPU 时进入降级模式。

    Usage:
        manager = GPUBackendManager()
        if manager.is_gpu_available:
            backend = manager.backend
            device = manager.device_str
            info = manager.get_gpu_info()
            can_load = manager.can_load_model(required_vram_mb=8000)
    """

    def __init__(self):
        """初始化 GPU 后端管理器并自动检测可用后端"""
        # _detect_backend() 在构造末尾必定赋值；初始值用 UNAVAILABLE 而非 None，
        # 保证 backend 始终为非空枚举。
        self._backend: GPUBackend = GPUBackend.UNAVAILABLE
        self._strategy: _GPUStrategy | None = None
        self._device_name: str = ""
        self._total_vram: int = 0
        self._gpu_info_cache: GPUInfo | None = None
        self._gpu_info_cache_time: float = 0.0
        self._can_load_cache: dict[int, tuple[float, bool]] = {}
        self._detect_backend()

    def _detect_backend(self):
        """自动检测可用的 NVIDIA GPU 后端

        按 `_DETECTION_ORDER` 优先级顺序遍历策略，选择第一个检测成功的后端。
        如果未检测到 NVIDIA GPU，设置为 UNAVAILABLE 降级模式并记录警告。

        检测流程：
            1. 按优先级尝试每个后端策略的 detect() 方法
            2. 检测成功后获取 GPU 信息（名称、显存）
            3. 信息获取失败时使用默认值但继续使用该后端
            4. 全部失败则进入降级模式
        """
        for backend_type in _DETECTION_ORDER:
            strategy = _STRATEGY_MAP[backend_type]
            try:
                if strategy.detect():
                    self._backend = backend_type
                    self._strategy = strategy
                    try:
                        info = strategy.get_info()
                        self._device_name = info.get("name", str(backend_type.value))
                        self._total_vram = info.get("total_vram", 0)
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
            "未检测到 NVIDIA GPU。应用将以降级模式启动，推理功能不可用。" "SeedVR2 模型仅支持 NVIDIA CUDA GPU 推理。"
        )

    @property
    def backend(self) -> GPUBackend:
        """获取当前 GPU 后端类型

        Returns:
            GPUBackend: 当前后端枚举值（CUDA 或 UNAVAILABLE）
        """
        return self._backend

    @property
    def device_name(self) -> str:
        """获取 GPU 设备名称

        Returns:
            str: GPU 设备名称字符串，降级模式下返回提示信息
        """
        return self._device_name

    @property
    def is_gpu_available(self) -> bool:
        """检查 GPU 是否可用（CUDA 后端已激活）

        Returns:
            bool: GPU 可用返回 True，降级模式返回 False
        """
        return self._backend == GPUBackend.CUDA

    @property
    def device_str(self) -> str:
        """返回 PyTorch 设备字符串

        Returns:
            str: 可用时返回策略对应的设备字符串（如 "cuda"），降级时返回 "cpu" 并记录警告
        """
        if self._strategy is not None:
            return self._strategy.device_str()
        logger.warning(
            "GPU 不可用，device_str 返回 'cpu'。" "SeedVR2 模型仅支持 CUDA GPU 推理，CPU 模式下推理功能不可用。"
        )
        return "cpu"

    def get_gpu_info(self) -> GPUInfo:
        """获取当前 GPU 完整硬件信息

        优先从策略获取实时信息，失败或降级模式下返回已缓存的信息或空信息。
        查询结果会缓存 0.5 秒，避免频繁调用 CUDA API 造成开销。

        Returns:
            GPUInfo: 包含设备名称、显存、利用率、CUDA版本等的数据类实例
        """
        current_time = time.time()
        if self._gpu_info_cache is not None and current_time - self._gpu_info_cache_time < _GPU_INFO_CACHE_TTL:
            return self._gpu_info_cache

        result: GPUInfo
        if self._strategy is not None and self._backend != GPUBackend.UNAVAILABLE:
            try:
                info = self._strategy.get_info()
                result = GPUInfo(
                    backend=self._backend,
                    name=info.get("name", self._device_name),
                    total_vram_mb=info.get("total_vram", self._total_vram) // (1024 * 1024),
                    available_vram_mb=info.get("available_vram_mb", 0),
                    utilization_pct=info.get("utilization", 0.0),
                    driver_version="",
                    cuda_version=info.get("cuda_version", ""),
                )
            except ImportError as e:
                logger.error(f"PyTorch 未安装，无法获取 GPU 信息: {e}")
                result = self._get_unavailable_info()
            except RuntimeError as e:
                logger.error(f"CUDA 运行时错误，无法获取 GPU 信息: {e}")
                result = self._get_unavailable_info()
            except Exception as e:
                logger.error(f"获取 GPU 信息时发生未知错误: {e}", exc_info=True)
                result = self._get_unavailable_info()
        else:
            result = self._get_unavailable_info()

        self._gpu_info_cache = result
        self._gpu_info_cache_time = current_time
        return result

    def _get_unavailable_info(self) -> GPUInfo:
        """返回降级模式下的 GPU 信息

        Returns:
            GPUInfo: 降级模式信息对象
        """
        return GPUInfo(
            backend=self._backend,
            name=self._device_name,
            total_vram_mb=self._total_vram // (1024 * 1024) if self._total_vram else 0,
            available_vram_mb=0,
            utilization_pct=0.0,
        )

    def can_load_model(self, required_vram_mb: int) -> bool:
        """检查当前 GPU 是否有足够显存加载指定大小的模型

        模型加载预检：在实际加载模型前检查可用显存，避免 OOM。
        查询结果会缓存 0.5 秒，并要求可用显存比需求多 10% 作为安全边际，
        防止刚好卡阈值导致运行时 OOM。

        Args:
            required_vram_mb: 模型所需显存大小（MB）

        Returns:
            bool: 可用显存 >= 所需显存 * 1.1 返回 True，否则返回 False；
                  GPU 不可用时始终返回 False
        """
        if self._backend == GPUBackend.UNAVAILABLE:
            return False

        current_time = time.time()
        cache_entry = self._can_load_cache.get(required_vram_mb)
        if cache_entry is not None:
            cache_time, cache_result = cache_entry
            if current_time - cache_time < _MODEL_LOAD_CACHE_TTL:
                return cache_result

        info = self.get_gpu_info()
        required_with_margin = int(required_vram_mb * _VRAM_SAFETY_MARGIN)
        result = info.available_vram_mb >= required_with_margin

        self._can_load_cache[required_vram_mb] = (current_time, result)

        if len(self._can_load_cache) > 32:
            oldest_key = min(self._can_load_cache.keys(), key=lambda k: self._can_load_cache[k][0])
            del self._can_load_cache[oldest_key]

        return result

    def get_recommended_model_size(self) -> str:
        """根据当前 GPU 显存大小推荐合适的模型规格

        推荐策略：
            - 24GB+ 显存：推荐 7B 模型
            - 16GB+ 显存：推荐 3B 模型
            - 低于 16GB：仍推荐 3B 模型但需配合 BlockSwap 等优化

        Returns:
            str: 推荐模型大小标识（"3b" 或 "7b"）
        """
        info = self.get_gpu_info()
        if info.total_vram_mb >= 24000:  # 24GB+
            return "7b"
        elif info.total_vram_mb >= 16000:  # 16GB+
            return "3b"
        else:
            return "3b"  # 显存不足也推荐3b，但会警告

    def get_device(self) -> str:
        """获取 PyTorch 设备字符串（同 device_str 属性）

        Returns:
            str: PyTorch 设备字符串
        """
        return self.device_str

    def synchronize(self) -> None:
        """同步当前 GPU 设备，等待所有操作完成

        GPU 可用时调用策略的 synchronize() 方法，降级模式下无操作。
        """
        if self._strategy is not None:
            self._strategy.synchronize()

    def get_process_group_backend(self) -> str:
        """获取分布式训练进程组通信后端

        Returns:
            str: CUDA 返回 "nccl"，降级模式返回 "gloo"
        """
        if self._strategy is not None:
            return self._strategy.get_process_group_backend()
        return "gloo"


# 全局单例实例：应用启动时自动创建，各模块通过此实例访问 GPU 功能
gpu_manager = GPUBackendManager()

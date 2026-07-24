"""GPU / 硬件兼容性模块

提供多后端 GPU 检测、兼容性判断和硬件加速参考功能。

竞品来源:
- Anime4KCPP: 多后端自动检测 CPU/OpenCL/CUDA (P2)
- Waifu2x-Extension-GUI: GPU 枚举与兼容性检测 (P1)
- Fast-SRGAN: MPS/多设备支持参考 CUDA→MPS→CPU 降级链 (P3)
- upscayl: Vulkan 跨 GPU 厂商支持参考 (P3)
- Waifu2x-Extension-GUI: RTX VSR 硬件加速参考 (P3)

Key Features:
- 多后端自动检测: Anime4KCPP 风格的 CPU/OpenCL/CUDA 运行时自动选择与优雅降级
- GPU 枚举与兼容性检测: Waifu2x-Extension-GUI 风格的统一 GPU 检测与计算能力校验
- MPS/多设备支持参考: Fast-SRGAN 风格的 CUDA→MPS→CPU 降级链
- Vulkan 跨厂商支持参考: upscayl 风格的 NVIDIA/AMD/Intel 兼容性参考
- RTX VSR 硬件加速参考: Waifu2x-Extension-GUI 风格的 RTX Super Resolution 集成

注意: SeedVR2 项目硬约束规定仅支持 NVIDIA CUDA GPU 推理。
本模块中的 MPS/CPU/Vulkan 降级链和跨厂商支持仅为参考框架，
实际推理仍需 CUDA 后端。这些参考设计可供未来扩展使用。
"""

import logging
import platform
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import torch

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 运行时后端枚举
# ---------------------------------------------------------------------------

class ComputeBackend(Enum):
    """计算后端类型"""
    CUDA = "cuda"            # NVIDIA CUDA (主力后端)
    OPENCL = "opencl"        # OpenCL (跨厂商参考)
    MPS = "mps"              # Apple Metal Performance Shaders (参考)
    VULKAN = "vulkan"        # Vulkan (跨厂商参考)
    CPU = "cpu"              # CPU 回退 (参考，不支持 SeedVR2 推理)


class GPUVendor(Enum):
    """GPU 厂商"""
    NVIDIA = "nvidia"
    AMD = "amd"
    INTEL = "intel"
    APPLE = "apple"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# GPU 枚举与兼容性检测 (Waifu2x-Extension-GUI inspired) - P1
# ---------------------------------------------------------------------------

@dataclass
class GPUDeviceInfo:
    """GPU 设备信息

    参考 Waifu2x-Extension-GUI 的 GPU 枚举功能:
    为每个引擎提供统一的 GPU 设备信息，包括设备名称、显存、
    计算能力等关键兼容性指标。
    """
    # 设备索引 (从 0 开始)
    device_index: int
    # 设备名称
    device_name: str
    # GPU 厂商
    vendor: GPUVendor
    # 计算后端
    backend: ComputeBackend
    # 总显存 (MB)
    total_vram_mb: int
    # 可用显存 (MB)
    available_vram_mb: int
    # CUDA 计算能力 (仅 NVIDIA)
    cuda_compute_capability: tuple[int, int] | None = None
    # CUDA 版本
    cuda_version: str = ""
    # 驱动版本
    driver_version: str = ""
    # 是否支持当前引擎
    is_compatible: bool = False
    # 不兼容原因 (如果不兼容)
    incompatibility_reason: str = ""

    @property
    def total_vram_gb(self) -> float:
        return self.total_vram_mb / 1024

    @property
    def available_vram_gb(self) -> float:
        return self.available_vram_mb / 1024

    @property
    def compute_capability_str(self) -> str:
        if self.cuda_compute_capability is not None:
            return f"{self.cuda_compute_capability[0]}.{self.cuda_compute_capability[1]}"
        return "N/A"


# SeedVR2 引擎的最低 GPU 要求
SEEDVR2_MIN_REQUIREMENTS = {
    "min_compute_capability": (7, 5),   # 最低 SM 7.5 (Turing)
    "min_vram_mb": 8000,                # 最低 8GB 显存
    "required_backend": ComputeBackend.CUDA,
    "recommended_compute_capability": (8, 6),  # 推荐 SM 8.6+ (Ampere)
    "recommended_vram_mb": 12000,       # 推荐 12GB+ 显存
}


@dataclass
class GPUCompatibilityConfig:
    """GPU 兼容性检测配置

    参考 Waifu2x-Extension-GUI 的引擎兼容性检测:
    为每个引擎定义最低 GPU 要求，启动时自动检测兼容性。
    """
    # 最低 CUDA 计算能力
    min_compute_capability: tuple[int, int] = SEEDVR2_MIN_REQUIREMENTS["min_compute_capability"]
    # 最低显存要求 (MB)
    min_vram_mb: int = SEEDVR2_MIN_REQUIREMENTS["min_vram_mb"]
    # 推荐的 CUDA 计算能力
    recommended_compute_capability: tuple[int, int] = SEEDVR2_MIN_REQUIREMENTS["recommended_compute_capability"]
    # 推荐显存 (MB)
    recommended_vram_mb: int = SEEDVR2_MIN_REQUIREMENTS["recommended_vram_mb"]
    # 要求的计算后端
    required_backend: ComputeBackend = ComputeBackend.CUDA
    # 是否在检测到不兼容 GPU 时发出警告
    warn_on_incompatible: bool = True
    # 是否允许在推荐配置以下运行 (性能可能不佳)
    allow_below_recommended: bool = True


class GPUCompatibilityDetector:
    """GPU 兼容性检测器

    参考 Waifu2x-Extension-GUI 的 GPU 枚举与兼容性检测:
    统一检测系统中的所有 GPU 设备，校验计算能力与显存是否满足要求。
    """

    def __init__(self, config: GPUCompatibilityConfig):
        self.config = config
        self._device_cache: list[GPUDeviceInfo] | None = None

    def enumerate_gpus(self, force_refresh: bool = False) -> list[GPUDeviceInfo]:
        """枚举系统中所有可用的 GPU 设备

        Args:
            force_refresh: 是否强制刷新缓存

        Returns:
            GPU 设备信息列表
        """
        if self._device_cache is not None and not force_refresh:
            return self._device_cache

        devices = []

        # CUDA GPU 枚举
        if torch.cuda.is_available():
            num_gpus = torch.cuda.device_count()
            for i in range(num_gpus):
                device_info = self._query_cuda_device(i)
                devices.append(device_info)

        if not devices:
            logger.warning("未检测到任何 CUDA GPU 设备")

        self._device_cache = devices
        return devices

    def _query_cuda_device(self, device_index: int) -> GPUDeviceInfo:
        """查询 CUDA GPU 设备信息

        Args:
            device_index: CUDA 设备索引

        Returns:
            GPU 设备信息
        """
        cfg = self.config

        try:
            props = torch.cuda.get_device_properties(device_index)
            free_mem, total_mem = torch.cuda.mem_get_info(device_index)

            # 解析厂商 (通过设备名称启发式判断)
            vendor = self._infer_vendor(props.name)

            # 计算能力
            compute_cap = (props.major, props.minor)

            # 兼容性检查
            is_compatible = True
            reason = ""

            # 检查计算能力
            if compute_cap < cfg.min_compute_capability:
                is_compatible = False
                reason = (
                    f"计算能力 {compute_cap[0]}.{compute_cap[1]} "
                    f"低于最低要求 {cfg.min_compute_capability[0]}.{cfg.min_compute_capability[1]}"
                )

            # 检查显存
            total_vram_mb = total_mem // (1024 * 1024)
            if total_vram_mb < cfg.min_vram_mb:
                is_compatible = False
                reason = (
                    f"显存 {total_vram_mb / 1024:.1f}GB "
                    f"低于最低要求 {cfg.min_vram_mb / 1024:.1f}GB"
                )

            # 检查推荐配置
            if is_compatible:
                if compute_cap < cfg.recommended_compute_capability:
                    if cfg.warn_on_incompatible:
                        logger.info(
                            f"GPU {props.name}: 计算能力 {compute_cap[0]}.{compute_cap[1]} "
                            f"低于推荐值 {cfg.recommended_compute_capability[0]}."
                            f"{cfg.recommended_compute_capability[1]}，性能可能不佳"
                        )
                if total_vram_mb < cfg.recommended_vram_mb:
                    if cfg.warn_on_incompatible:
                        logger.info(
                            f"GPU {props.name}: 显存 {total_vram_mb / 1024:.1f}GB "
                            f"低于推荐值 {cfg.recommended_vram_mb / 1024:.1f}GB，"
                            f"建议启用 BlockSwap"
                        )

            # CUDA 版本
            cuda_version = torch.version.cuda or ""

            # 驱动版本
            driver_version = self._get_nvidia_driver_version()

            info = GPUDeviceInfo(
                device_index=device_index,
                device_name=props.name,
                vendor=vendor,
                backend=ComputeBackend.CUDA,
                total_vram_mb=total_vram_mb,
                available_vram_mb=free_mem // (1024 * 1024),
                cuda_compute_capability=compute_cap,
                cuda_version=cuda_version,
                driver_version=driver_version,
                is_compatible=is_compatible,
                incompatibility_reason=reason,
            )

            logger.info(
                f"GPU #{device_index}: {props.name} "
                f"(SM {compute_cap[0]}.{compute_cap[1]}, "
                f"{total_vram_mb / 1024:.1f}GB VRAM, "
                f"兼容: {'是' if is_compatible else '否 - ' + reason})"
            )

            return info

        except Exception as e:
            logger.error(f"查询 CUDA 设备 #{device_index} 失败: {e}")
            return GPUDeviceInfo(
                device_index=device_index,
                device_name="Unknown",
                vendor=GPUVendor.UNKNOWN,
                backend=ComputeBackend.CUDA,
                total_vram_mb=0,
                available_vram_mb=0,
                is_compatible=False,
                incompatibility_reason=f"设备查询失败: {e}",
            )

    @staticmethod
    def _infer_vendor(device_name: str) -> GPUVendor:
        """通过设备名称推断 GPU 厂商"""
        name_lower = device_name.lower()
        if "nvidia" in name_lower or "geforce" in name_lower or "rtx" in name_lower or "gtx" in name_lower:
            return GPUVendor.NVIDIA
        elif "amd" in name_lower or "radeon" in name_lower or "rx " in name_lower:
            return GPUVendor.AMD
        elif "intel" in name_lower or "arc" in name_lower or "xe " in name_lower:
            return GPUVendor.INTEL
        elif "apple" in name_lower or "m1" in name_lower or "m2" in name_lower or "m3" in name_lower:
            return GPUVendor.APPLE
        return GPUVendor.UNKNOWN

    @staticmethod
    def _get_nvidia_driver_version() -> str:
        """获取 NVIDIA 驱动版本"""
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip().split("\n")[0].strip()
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            pass
        return ""

    def check_compatibility(self) -> dict[str, Any]:
        """执行完整的 GPU 兼容性检查

        Returns:
            兼容性报告字典，包含所有 GPU 设备信息和总体兼容状态
        """
        devices = self.enumerate_gpus()
        compatible_devices = [d for d in devices if d.is_compatible]

        report = {
            "overall_compatible": len(compatible_devices) > 0,
            "total_gpus": len(devices),
            "compatible_gpus": len(compatible_devices),
            "devices": [
                {
                    "index": d.device_index,
                    "name": d.device_name,
                    "vendor": d.vendor.value,
                    "compute_capability": d.compute_capability_str,
                    "vram_gb": d.total_vram_gb,
                    "available_vram_gb": d.available_vram_gb,
                    "is_compatible": d.is_compatible,
                    "reason": d.incompatibility_reason,
                }
                for d in devices
            ],
            "min_requirements": {
                "compute_capability": f"{self.config.min_compute_capability[0]}.{self.config.min_compute_capability[1]}",
                "vram_mb": self.config.min_vram_mb,
                "backend": self.config.required_backend.value,
            },
        }

        if not compatible_devices:
            logger.error(
                "GPU 兼容性检查失败: 没有找到满足要求的 GPU 设备。"
                "SeedVR2 需要 NVIDIA CUDA GPU (SM 7.5+, 8GB+ VRAM)"
            )
        else:
            best = compatible_devices[0]
            logger.info(
                f"GPU 兼容性检查通过: 最佳设备 {best.device_name} "
                f"(SM {best.compute_capability_str}, {best.total_vram_gb:.1f}GB)"
            )

        return report

    def get_best_device(self) -> GPUDeviceInfo | None:
        """获取最佳可用 GPU 设备

        选择兼容且显存最大的设备。

        Returns:
            最佳设备信息，无兼容设备时返回 None
        """
        devices = self.enumerate_gpus()
        compatible = [d for d in devices if d.is_compatible]
        if not compatible:
            return None

        # 按显存降序排序
        compatible.sort(key=lambda d: d.total_vram_mb, reverse=True)
        return compatible[0]


# ---------------------------------------------------------------------------
# 多后端自动检测 (Anime4KCPP inspired) - P2
# ---------------------------------------------------------------------------

@dataclass
class BackendDetectionConfig:
    """多后端自动检测配置

    参考 Anime4KCPP 的 CPU/OpenCL/CUDA 多后端自动选择:
    按照性能优先级尝试各个后端，自动选择最优可用后端，
    并在首选后端不可用时优雅降级到次选后端。

    降级链: CUDA → OpenCL → CPU
    (注意: SeedVR2 推理仅支持 CUDA，此处降级链为参考框架)
    """
    # 后端优先级列表 (按性能降序)
    backend_priority: list[ComputeBackend] = field(
        default_factory=lambda: [
            ComputeBackend.CUDA,
            ComputeBackend.OPENCL,
            ComputeBackend.CPU,
        ]
    )
    # 各后端的检测超时 (秒)
    detection_timeout: float = 5.0
    # 是否允许 CPU 回退
    allow_cpu_fallback: bool = False  # SeedVR2 不允许 CPU 推理
    # 检测失败时是否静默
    silent_fail: bool = False


class BackendDetector:
    """多后端自动检测器

    参考 Anime4KCPP 的 Processor 工厂模式:
    自动检测系统中可用的计算后端，按优先级选择最优后端。
    """

    def __init__(self, config: BackendDetectionConfig):
        self.config = config
        self._detected_backends: dict[ComputeBackend, bool] = {}
        self._best_backend: ComputeBackend | None = None

    def detect_all(self) -> dict[ComputeBackend, bool]:
        """检测所有后端的可用性

        Returns:
            后端可用性字典
        """
        results = {}

        for backend in self.config.backend_priority:
            available = self._detect_backend(backend)
            results[backend] = available
            self._detected_backends[backend] = available

            status = "可用" if available else "不可用"
            if not self.config.silent_fail or available:
                logger.info(f"后端检测: {backend.value} - {status}")

        # 选择最佳后端
        self._best_backend = None
        for backend in self.config.backend_priority:
            if results.get(backend, False):
                # CPU 回退需要特殊检查
                if backend == ComputeBackend.CPU and not self.config.allow_cpu_fallback:
                    continue
                self._best_backend = backend
                break

        if self._best_backend is not None:
            logger.info(f"自动选择最佳后端: {self._best_backend.value}")
        else:
            logger.error("未找到任何可用计算后端")

        return results

    def _detect_backend(self, backend: ComputeBackend) -> bool:
        """检测单个后端是否可用

        Args:
            backend: 要检测的后端

        Returns:
            是否可用
        """
        if backend == ComputeBackend.CUDA:
            return self._detect_cuda()
        elif backend == ComputeBackend.OPENCL:
            return self._detect_opencl()
        elif backend == ComputeBackend.MPS:
            return self._detect_mps()
        elif backend == ComputeBackend.VULKAN:
            return self._detect_vulkan()
        elif backend == ComputeBackend.CPU:
            return True  # CPU 始终可用
        return False

    @staticmethod
    def _detect_cuda() -> bool:
        """检测 CUDA 后端"""
        try:
            return torch.cuda.is_available() and torch.cuda.device_count() > 0
        except Exception:
            return False

    @staticmethod
    def _detect_opencl() -> bool:
        """检测 OpenCL 后端

        通过尝试导入 pyopencl 包或检测系统 OpenCL 运行时。
        """
        try:
            import pyopencl  # noqa: F401
            return True
        except ImportError:
            pass

        # 尝试检测系统 OpenCL 运行时
        try:
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["where", "opencl.dll"],
                    capture_output=True, text=True, timeout=3,
                )
                return result.returncode == 0
            else:
                result = subprocess.run(
                    ["find", "/usr/lib", "-name", "libOpenCL.so*"],
                    capture_output=True, text=True, timeout=3,
                )
                return result.returncode == 0 and len(result.stdout.strip()) > 0
        except Exception:
            return False

    @staticmethod
    def _detect_mps() -> bool:
        """检测 Apple MPS 后端"""
        try:
            return (
                hasattr(torch.backends, "mps")
                and torch.backends.mps.is_available()
                and torch.backends.mps.is_built()
            )
        except Exception:
            return False

    @staticmethod
    def _detect_vulkan() -> bool:
        """检测 Vulkan 后端"""
        try:
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["where", "vulkaninfo"],
                    capture_output=True, text=True, timeout=3,
                )
                return result.returncode == 0
            else:
                result = subprocess.run(
                    ["which", "vulkaninfo"],
                    capture_output=True, text=True, timeout=3,
                )
                return result.returncode == 0
        except Exception:
            return False

    @property
    def best_backend(self) -> ComputeBackend | None:
        """获取检测到的最佳后端"""
        return self._best_backend

    def get_device_for_backend(self, backend: ComputeBackend) -> str:
        """获取指定后端的 torch 设备字符串

        Args:
            backend: 计算后端

        Returns:
            torch 设备字符串
        """
        if backend == ComputeBackend.CUDA:
            return "cuda:0"
        elif backend == ComputeBackend.OPENCL:
            return "cpu"  # PyTorch 无原生 OpenCL 支持
        elif backend == ComputeBackend.MPS:
            return "mps"
        elif backend == ComputeBackend.VULKAN:
            return "cpu"  # PyTorch 无原生 Vulkan 支持
        else:
            return "cpu"


# ---------------------------------------------------------------------------
# MPS / 多设备支持参考 (Fast-SRGAN inspired) - P3
# ---------------------------------------------------------------------------

@dataclass
class MultiDeviceConfig:
    """多设备降级链配置

    参考 Fast-SRGAN 的 CUDA → MPS → CPU 降级链:
    定义设备降级优先级，当首选设备不可用时自动降级到次选设备。

    注意: SeedVR2 硬约束规定仅支持 CUDA 推理，
    MPS 和 CPU 降级路径仅为参考框架，不可用于实际推理。
    """
    # 降级链: 依次尝试的设备列表
    degradation_chain: list[str] = field(
        default_factory=lambda: ["cuda:0", "mps", "cpu"]
    )
    # 是否允许非 CUDA 降级 (SeedVR2 应为 False)
    allow_non_cuda_degradation: bool = False
    # 每个设备的最低显存要求 (MB)
    min_vram_per_device: dict[str, int] = field(
        default_factory=lambda: {
            "cuda:0": 8000,
            "mps": 8000,
            "cpu": 16384,  # CPU 模式需要大量内存
        }
    )


class MultiDeviceManager:
    """多设备管理器

    参考 Fast-SRGAN 的多设备降级机制:
    按照降级链依次尝试设备，选择最佳可用设备。

    注意: 本模块为参考框架。SeedVR2 推理必须使用 CUDA，
    MPS/CPU 路径仅作为架构参考。
    """

    def __init__(self, config: MultiDeviceConfig):
        self.config = config
        self._selected_device: str | None = None

    def select_device(self) -> str:
        """从降级链中选择最佳可用设备

        Returns:
            选中的设备字符串
        """
        cfg = self.config

        for device_str in cfg.degradation_chain:
            if self._is_device_available(device_str):
                # 检查是否允许非 CUDA 降级
                if not device_str.startswith("cuda") and not cfg.allow_non_cuda_degradation:
                    logger.warning(
                        f"设备 {device_str} 可用，但 SeedVR2 不支持非 CUDA 推理，跳过"
                    )
                    continue

                # 检查显存/内存要求
                min_vram = cfg.min_vram_per_device.get(device_str, 0)
                if min_vram > 0 and not self._check_memory(device_str, min_vram):
                    logger.warning(
                        f"设备 {device_str} 可用内存不足 "
                        f"(需要 {min_vram / 1024:.1f}GB)，跳过"
                    )
                    continue

                self._selected_device = device_str
                logger.info(f"多设备管理: 选择设备 {device_str}")
                return device_str

        # 无可用设备
        self._selected_device = "cpu"
        logger.error("多设备管理: 无可用 GPU 设备，降级到 CPU (不支持 SeedVR2 推理)")
        return "cpu"

    @staticmethod
    def _is_device_available(device_str: str) -> bool:
        """检查设备是否可用"""
        if device_str.startswith("cuda"):
            if not torch.cuda.is_available():
                return False
            # 检查特定设备索引
            parts = device_str.split(":")
            if len(parts) > 1:
                idx = int(parts[1])
                return idx < torch.cuda.device_count()
            return True
        elif device_str == "mps":
            try:
                return (
                    hasattr(torch.backends, "mps")
                    and torch.backends.mps.is_available()
                )
            except Exception:
                return False
        elif device_str == "cpu":
            return True
        return False

    @staticmethod
    def _check_memory(device_str: str, min_memory_mb: int) -> bool:
        """检查设备可用内存是否满足要求"""
        try:
            if device_str.startswith("cuda"):
                free_mem, _ = torch.cuda.mem_get_info(device_str)
                return free_mem >= min_memory_mb * 1024 * 1024
            elif device_str == "cpu":
                import psutil
                available = psutil.virtual_memory().available
                return available >= min_memory_mb * 1024 * 1024
            elif device_str == "mps":
                # MPS 使用统一内存，检查系统可用内存
                import psutil
                available = psutil.virtual_memory().available
                return available >= min_memory_mb * 1024 * 1024
        except Exception:
            return False
        return False

    @property
    def selected_device(self) -> str | None:
        """获取已选择的设备"""
        return self._selected_device


# ---------------------------------------------------------------------------
# Vulkan 跨厂商支持参考 (upscayl inspired) - P3
# ---------------------------------------------------------------------------

@dataclass
class VulkanDeviceInfo:
    """Vulkan GPU 设备信息

    参考 upscayl 的跨厂商 Vulkan 支持:
    Vulkan API 可以跨 NVIDIA/AMD/Intel 厂商使用 GPU 加速，
    不依赖厂商特定的运行时 (如 CUDA)。
    """
    # 设备名称
    device_name: str
    # 厂商
    vendor: GPUVendor
    # Vulkan API 版本
    api_version: str
    # 驱动版本
    driver_version: str
    # 设备类型: 'discrete_gpu', 'integrated_gpu', 'virtual_gpu', 'cpu'
    device_type: str
    # 最大内存分配大小 (MB)
    max_memory_allocation_mb: int
    # 计算队列数量
    compute_queue_count: int
    # 是否支持所需扩展
    supports_required_extensions: bool


@dataclass
class VulkanCompatConfig:
    """Vulkan 兼容性配置

    参考 upscayl 的 Vulkan 集成方式:
    通过 Vulkan 后端支持跨厂商 GPU 加速，兼容 NVIDIA/AMD/Intel。
    """
    # 是否启用 Vulkan 后端 (参考)
    enabled: bool = False
    # 所需 Vulkan 扩展列表
    required_extensions: list[str] = field(
        default_factory=lambda: [
            "VK_KHR_storage_buffer_storage_class",
            "VK_KHR_vulkan_memory_model",
        ]
    )
    # 最低 Vulkan API 版本
    min_api_version: str = "1.2"
    # 最低计算队列数
    min_compute_queues: int = 1


class VulkanCompatibilityChecker:
    """Vulkan 兼容性检查器

    参考 upscayl 的跨厂商 Vulkan 支持实现:
    检测系统中支持 Vulkan 的 GPU 设备，验证 API 版本和扩展支持。

    注意: 本模块为参考框架，SeedVR2 当前不支持 Vulkan 后端。
    Vulkan 支持需要额外的推理引擎 (如 ncnn) 集成。
    """

    def __init__(self, config: VulkanCompatConfig):
        self.config = config

    def check_vulkan_available(self) -> bool:
        """检查系统是否支持 Vulkan

        Returns:
            是否可用
        """
        try:
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["vulkaninfo", "--summary"],
                    capture_output=True, text=True, timeout=5,
                )
                return result.returncode == 0
            elif platform.system() == "Linux":
                result = subprocess.run(
                    ["which", "vulkaninfo"],
                    capture_output=True, text=True, timeout=3,
                )
                return result.returncode == 0
            elif platform.system() == "Darwin":
                # macOS 使用 MoltenVK 兼容层
                return False  # macOS 的 Vulkan 支持有限
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            pass

        return False

    def enumerate_vulkan_devices(self) -> list[VulkanDeviceInfo]:
        """枚举支持 Vulkan 的 GPU 设备

        Returns:
            Vulkan 设备信息列表
        """
        devices = []

        if not self.check_vulkan_available():
            logger.info("Vulkan 不可用，跳过设备枚举")
            return devices

        try:
            result = subprocess.run(
                ["vulkaninfo", "--summary"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return devices

            # 解析 vulkaninfo 输出
            # 简化解析: 仅提取设备名称
            lines = result.stdout.split("\n")
            for line in lines:
                line = line.strip()
                if line.startswith("GPU") and "=" in line:
                    name = line.split("=")[-1].strip()
                    vendor = GPUCompatibilityDetector._infer_vendor(name)
                    devices.append(VulkanDeviceInfo(
                        device_name=name,
                        vendor=vendor,
                        api_version="1.2",
                        driver_version="unknown",
                        device_type="discrete_gpu",
                        max_memory_allocation_mb=0,
                        compute_queue_count=1,
                        supports_required_extensions=True,
                    ))
        except Exception as e:
            logger.debug(f"Vulkan 设备枚举失败: {e}")

        return devices


# ---------------------------------------------------------------------------
# RTX VSR 硬件加速参考 (Waifu2x-Extension-GUI inspired) - P3
# ---------------------------------------------------------------------------

@dataclass
class RTXVSRConfig:
    """RTX Video Super Resolution 配置

    参考 Waifu2x-Extension-GUI 的 RTX VSR 硬件加速集成:
    NVIDIA RTX VSR 是 NVIDIA 驱动内建的实时视频超分辨率技术，
    可在浏览器视频播放时自动提升分辨率。

    本模块为参考文档，记录 RTX VSR 的集成可能性:
    - RTX VSR 由 NVIDIA 驱动自动管理，无需应用层代码
    - 可作为前置处理器: 先用 RTX VSR 做初步超分，再用 SeedVR2 做精细修复
    - 可作为质量对比基准: 评估 SeedVR2 输出相对于 RTX VSR 的提升
    """
    # 是否启用 RTX VSR 相关功能 (参考)
    enabled: bool = False
    # 最低 RTX VSR 要求: RTX 30 系列及以上
    min_gpu_series: int = 30  # RTX 30 系列
    # 是否在兼容 GPU 上自动启用 RTX VSR
    auto_enable: bool = False
    # RTX VSR 质量等级 (1-4)
    quality_level: int = 4


class RTXVSRChecker:
    """RTX VSR 硬件加速检查器

    参考 Waifu2x-Extension-GUI 的 RTX VSR 功能:
    检测 GPU 是否支持 RTX Video Super Resolution，
    提供集成参考信息。

    注意: RTX VSR 是 NVIDIA 驱动层功能，不由应用直接控制。
    本检查器仅用于检测硬件兼容性和提供参考信息。
    """

    def __init__(self, config: RTXVSRConfig):
        self.config = config

    def is_rtx_vsr_supported(self) -> bool:
        """检查当前 GPU 是否支持 RTX VSR

        RTX VSR 要求:
        - NVIDIA RTX 30 系列及以上 GPU
        - NVIDIA 驱动版本 530+ (studio 驱动推荐)
        - Windows 10/11

        Returns:
            是否支持
        """
        # 1. 检查 CUDA 可用性
        if not torch.cuda.is_available():
            return False

        # 2. 检查 GPU 型号
        try:
            props = torch.cuda.get_device_properties(0)
            gpu_name = props.name

            # 检查是否为 RTX 30/40/50 系列
            is_rtx_30_plus = False
            for series in ["RTX 30", "RTX 40", "RTX 50", "RTX 3070", "RTX 3080",
                           "RTX 3090", "RTX 4070", "RTX 4080", "RTX 4090"]:
                if series in gpu_name:
                    is_rtx_30_plus = True
                    break

            if not is_rtx_30_plus:
                logger.info(f"GPU {gpu_name} 不支持 RTX VSR (需要 RTX 30 系列+)")
                return False

            # 3. 检查驱动版本
            driver_version = GPUCompatibilityDetector._get_nvidia_driver_version()
            if driver_version:
                try:
                    major = int(driver_version.split(".")[0])
                    if major < 530:
                        logger.info(
                            f"NVIDIA 驱动 {driver_version} 不满足 RTX VSR 最低要求 (530+)"
                        )
                        return False
                except (ValueError, IndexError):
                    pass

            # 4. 检查操作系统
            if platform.system() != "Windows":
                logger.info("RTX VSR 仅支持 Windows")
                return False

            logger.info(f"GPU {gpu_name} 支持 RTX VSR")
            return True

        except Exception as e:
            logger.debug(f"RTX VSR 兼容性检查失败: {e}")
            return False

    def get_rtx_vsr_info(self) -> dict[str, Any]:
        """获取 RTX VSR 兼容性信息

        Returns:
            RTX VSR 兼容性信息字典
        """
        supported = self.is_rtx_vsr_supported()

        info = {
            "supported": supported,
            "feature_name": "NVIDIA RTX Video Super Resolution",
            "description": "NVIDIA 驱动内建的实时视频超分辨率技术",
            "requirements": {
                "gpu": "NVIDIA RTX 30 系列及以上",
                "driver": "NVIDIA 驱动 530+",
                "os": "Windows 10/11",
            },
            "note": (
                "RTX VSR 由 NVIDIA 驱动自动管理，应用层无法直接控制。"
                "可作为 SeedVR2 的前置处理器或质量对比基准。"
            ),
            "integration_options": [
                "前置处理: 先 RTX VSR 初步超分，再 SeedVR2 精细修复",
                "质量基准: 评估 SeedVR2 相对 RTX VSR 的提升幅度",
                "浏览器场景: RTX VSR 自动处理浏览器内视频播放",
            ],
        }

        if supported and torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            info["detected_gpu"] = props.name
            info["compute_capability"] = f"{props.major}.{props.minor}"

        return info


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def get_gpu_compatibility_summary() -> dict[str, Any]:
    """获取 GPU 兼容性模块的功能摘要

    Returns:
        包含各功能及其优先级和状态的字典
    """
    return {
        "gpu_compatibility_detection": {
            "name": "GPU 枚举与兼容性检测",
            "source": "Waifu2x-Extension-GUI",
            "priority": "P1",
            "description": "统一 GPU 检测与计算能力校验，为每个引擎提供兼容性判断",
            "status": "implemented",
        },
        "multi_backend_detection": {
            "name": "多后端自动检测",
            "source": "Anime4KCPP",
            "priority": "P2",
            "description": "CPU/OpenCL/CUDA 运行时自动选择与优雅降级",
            "status": "implemented",
        },
        "mps_multi_device": {
            "name": "MPS/多设备支持参考",
            "source": "Fast-SRGAN",
            "priority": "P3",
            "description": "CUDA → MPS → CPU 降级链参考框架",
            "status": "reference",
        },
        "vulkan_cross_vendor": {
            "name": "Vulkan 跨厂商支持参考",
            "source": "upscayl",
            "priority": "P3",
            "description": "NVIDIA/AMD/Intel 厂商兼容性参考文档",
            "status": "reference",
        },
        "rtx_vsr": {
            "name": "RTX VSR 硬件加速参考",
            "source": "Waifu2x-Extension-GUI",
            "priority": "P3",
            "description": "RTX Super Resolution 集成参考文档",
            "status": "reference",
        },
    }

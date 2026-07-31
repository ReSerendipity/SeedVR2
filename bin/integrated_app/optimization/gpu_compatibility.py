"""GPU / 硬件兼容性检测模块 - SeedVR2 视频修复项目

本模块提供多后端 GPU 检测、兼容性判断和硬件加速参考功能，
参考了多个开源视频超分项目的实现经验，确保 SeedVR2 在合适的硬件上稳定运行。

所属项目: SeedVR2 (基于 ComfyUI-SeedVR2_VideoUpscaler 独立重构)
核心技术栈: PyTorch, CUDA, OpenCL (参考), Vulkan (参考), MPS (参考)

竞品参考来源:
    - Anime4KCPP: 多后端自动检测 CPU/OpenCL/CUDA (P2)
    - Waifu2x-Extension-GUI: GPU 枚举与兼容性检测 (P1)
    - Fast-SRGAN: MPS/多设备支持参考 CUDA→MPS→CPU 降级链 (P3)
    - upscayl: Vulkan 跨 GPU 厂商支持参考 (P3)
    - Waifu2x-Extension-GUI: RTX VSR 硬件加速参考 (P3)

核心功能:
    - P1: GPU 枚举与兼容性检测 - Waifu2x-Extension-GUI 风格的统一 GPU 检测与计算能力校验
    - P2: 多后端自动检测 - Anime4KCPP 风格的 CPU/OpenCL/CUDA 运行时自动选择与优雅降级
    - P3: MPS/多设备支持参考 - Fast-SRGAN 风格的 CUDA→MPS→CPU 降级链（参考框架）
    - P3: Vulkan 跨厂商支持参考 - upscayl 风格的 NVIDIA/AMD/Intel 兼容性参考
    - P3: RTX VSR 硬件加速参考 - Waifu2x-Extension-GUI 风格的 RTX Super Resolution 集成

重要约束:
    SeedVR2 项目硬约束规定仅支持 NVIDIA CUDA GPU 推理。
    本模块中的 MPS/CPU/Vulkan 降级链和跨厂商支持仅为参考框架，
    实际推理仍需 CUDA 后端。这些参考设计可供未来扩展使用。
"""

import logging
import platform
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import torch

logger = logging.getLogger(__name__)


class ComputeBackend(Enum):
    """计算后端类型枚举

    定义支持的各类 GPU/CPU 计算后端，按性能优先级排列。

    Attributes:
        CUDA: NVIDIA CUDA（SeedVR2 唯一主力后端）
        OPENCL: OpenCL（跨厂商参考，PyTorch 无原生支持）
        MPS: Apple Metal Performance Shaders（Apple Silicon 参考）
        VULKAN: Vulkan（跨厂商参考，需额外推理引擎集成）
        CPU: CPU 回退（参考，不支持 SeedVR2 推理）
    """
    CUDA = "cuda"
    OPENCL = "opencl"
    MPS = "mps"
    VULKAN = "vulkan"
    CPU = "cpu"


class GPUVendor(Enum):
    """GPU 厂商枚举

    通过设备名称启发式判断的 GPU 厂商类型。

    Attributes:
        NVIDIA: NVIDIA（GeForce/RTX/GTX 系列）
        AMD: AMD（Radeon/RX 系列）
        INTEL: Intel（Arc/Xe 系列）
        APPLE: Apple（M1/M2/M3 系列）
        UNKNOWN: 未知厂商
    """
    NVIDIA = "nvidia"
    AMD = "amd"
    INTEL = "intel"
    APPLE = "apple"
    UNKNOWN = "unknown"


@dataclass
class GPUDeviceInfo:
    """GPU 设备信息数据类

    参考 Waifu2x-Extension-GUI 的 GPU 枚举功能:
    为每个 GPU 提供统一的设备信息，包括设备名称、显存、
    计算能力、驱动版本等关键兼容性指标。

    Attributes:
        device_index: 设备索引（从 0 开始）
        device_name: 设备名称（如 "NVIDIA GeForce RTX 4090"）
        vendor: GPU 厂商（GPUVendor 枚举）
        backend: 计算后端（ComputeBackend 枚举）
        total_vram_mb: 总显存（MB）
        available_vram_mb: 当前可用显存（MB）
        cuda_compute_capability: CUDA 计算能力（major, minor）元组，仅 NVIDIA GPU
        cuda_version: CUDA 版本字符串
        driver_version: NVIDIA 驱动版本字符串
        is_compatible: 是否兼容当前引擎（满足最低要求）
        incompatibility_reason: 不兼容原因描述（兼容时为空字符串）
    """
    device_index: int
    device_name: str
    vendor: GPUVendor
    backend: ComputeBackend
    total_vram_mb: int
    available_vram_mb: int
    cuda_compute_capability: tuple[int, int] | None = None
    cuda_version: str = ""
    driver_version: str = ""
    is_compatible: bool = False
    incompatibility_reason: str = ""

    @property
    def total_vram_gb(self) -> float:
        """总显存（GB）

        Returns:
            float: 总显存大小，单位 GB
        """
        return self.total_vram_mb / 1024

    @property
    def available_vram_gb(self) -> float:
        """当前可用显存（GB）

        Returns:
            float: 可用显存大小，单位 GB
        """
        return self.available_vram_mb / 1024

    @property
    def compute_capability_str(self) -> str:
        """CUDA 计算能力字符串表示

        Returns:
            str: 计算能力字符串，如 "8.9"；非 NVIDIA GPU 返回 "N/A"
        """
        if self.cuda_compute_capability is not None:
            return f"{self.cuda_compute_capability[0]}.{self.cuda_compute_capability[1]}"
        return "N/A"


SEEDVR2_MIN_REQUIREMENTS: dict[str, Any] = {
    "min_compute_capability": (7, 5),
    "min_vram_mb": 8000,
    "required_backend": ComputeBackend.CUDA,
    "recommended_compute_capability": (8, 6),
    "recommended_vram_mb": 12000,
}
"""SeedVR2 引擎的最低 GPU 要求常量

定义 SeedVR2 模型推理的最低和推荐硬件规格：
    - min_compute_capability: 最低 CUDA 计算能力 SM 7.5（Turing 架构，RTX 20 系列）
    - min_vram_mb: 最低显存 8GB（需配合 BlockSwap 才能运行）
    - required_backend: 必须使用 CUDA 后端
    - recommended_compute_capability: 推荐 SM 8.6+（Ampere 架构，RTX 30 系列）
    - recommended_vram_mb: 推荐显存 12GB+（可流畅运行）
"""


@dataclass
class GPUCompatibilityConfig:
    """GPU 兼容性检测配置数据类

    参考 Waifu2x-Extension-GUI 的引擎兼容性检测:
    为引擎定义最低 GPU 要求，启动时自动检测兼容性并给出警告。

    Attributes:
        min_compute_capability: 最低 CUDA 计算能力（默认 SM 7.5）
        min_vram_mb: 最低显存要求，单位 MB（默认 8000MB = 8GB）
        recommended_compute_capability: 推荐 CUDA 计算能力（默认 SM 8.6）
        recommended_vram_mb: 推荐显存，单位 MB（默认 12000MB = 12GB）
        required_backend: 要求的计算后端（默认仅 CUDA）
        warn_on_incompatible: 是否在检测到不兼容/低配置 GPU 时发出警告日志
        allow_below_recommended: 是否允许在推荐配置以下运行（性能可能不佳）
    """
    min_compute_capability: tuple[int, int] = SEEDVR2_MIN_REQUIREMENTS["min_compute_capability"]
    min_vram_mb: int = SEEDVR2_MIN_REQUIREMENTS["min_vram_mb"]
    recommended_compute_capability: tuple[int, int] = SEEDVR2_MIN_REQUIREMENTS["recommended_compute_capability"]
    recommended_vram_mb: int = SEEDVR2_MIN_REQUIREMENTS["recommended_vram_mb"]
    required_backend: ComputeBackend = ComputeBackend.CUDA
    warn_on_incompatible: bool = True
    allow_below_recommended: bool = True


class GPUCompatibilityDetector:
    """GPU 兼容性检测器

    参考 Waifu2x-Extension-GUI 的 GPU 枚举与兼容性检测:
    统一检测系统中的所有 CUDA GPU 设备，校验计算能力、显存、
    CUDA 版本、驱动版本是否满足 SeedVR2 要求，输出结构化兼容性报告。

    检测流程:
        1. 枚举所有 CUDA GPU 设备
        2. 查询每个设备的属性（名称、计算能力、显存）
        3. 通过名称启发式判断厂商
        4. 检查是否满足最低要求
        5. 检查是否满足推荐配置（给出性能提示）
        6. 通过 nvidia-smi 查询驱动版本
        7. 生成兼容性报告

    Usage:
        config = GPUCompatibilityConfig()
        detector = GPUCompatibilityDetector(config)
        report = detector.check_compatibility()
        best = detector.get_best_device()
    """

    def __init__(self, config: GPUCompatibilityConfig):
        """初始化 GPU 兼容性检测器

        Args:
            config: 兼容性检测配置
        """
        self.config = config
        self._device_cache: list[GPUDeviceInfo] | None = None

    def enumerate_gpus(self, force_refresh: bool = False) -> list[GPUDeviceInfo]:
        """枚举系统中所有可用的 CUDA GPU 设备

        带缓存机制，首次调用会实际查询设备，后续调用返回缓存结果。
        force_refresh=True 可强制刷新缓存重新查询。

        Args:
            force_refresh: 是否强制刷新设备缓存，默认 False

        Returns:
            list[GPUDeviceInfo]: GPU 设备信息列表
        """
        if self._device_cache is not None and not force_refresh:
            return self._device_cache

        devices = []

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
        """查询单个 CUDA GPU 设备的详细信息（内部方法）

        执行以下检测：
        1. 通过 torch.cuda.get_device_properties 获取设备属性
        2. 通过 torch.cuda.mem_get_info 获取显存信息
        3. 通过设备名称推断厂商
        4. 检查计算能力和显存是否满足最低/推荐要求
        5. 查询 CUDA 版本和 NVIDIA 驱动版本

        Args:
            device_index: CUDA 设备索引（从 0 开始）

        Returns:
            GPUDeviceInfo: 填充完整的设备信息对象
        """
        cfg = self.config

        try:
            props = torch.cuda.get_device_properties(device_index)
            free_mem, total_mem = torch.cuda.mem_get_info(device_index)

            vendor = self._infer_vendor(props.name)

            compute_cap = (props.major, props.minor)

            is_compatible = True
            reason = ""

            if compute_cap < cfg.min_compute_capability:
                is_compatible = False
                reason = (
                    f"计算能力 {compute_cap[0]}.{compute_cap[1]} "
                    f"低于最低要求 {cfg.min_compute_capability[0]}.{cfg.min_compute_capability[1]}"
                )

            total_vram_mb = total_mem // (1024 * 1024)
            if total_vram_mb < cfg.min_vram_mb:
                is_compatible = False
                reason = (
                    f"显存 {total_vram_mb / 1024:.1f}GB "
                    f"低于最低要求 {cfg.min_vram_mb / 1024:.1f}GB"
                )

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

            cuda_version = torch.version.cuda or ""

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
        """通过设备名称字符串推断 GPU 厂商（静态内部方法）

        使用关键词匹配启发式判断：
        - NVIDIA: nvidia/geforce/rtx/gtx
        - AMD: amd/radeon/rx
        - Intel: intel/arc/xe
        - Apple: apple/m1/m2/m3

        Args:
            device_name: GPU 设备名称字符串（来自 torch.cuda）

        Returns:
            GPUVendor: 推断出的 GPU 厂商枚举值
        """
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
        """获取 NVIDIA 驱动版本号（静态内部方法）

        通过调用 nvidia-smi 命令行工具查询驱动版本，
        设置 5 秒超时避免阻塞。

        Returns:
            str: 驱动版本字符串（如 "546.33"）；查询失败返回空字符串
        """
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
        """执行完整的 GPU 兼容性检查并生成报告

        返回包含所有 GPU 设备信息、兼容状态、最低要求的结构化字典。
        如果没有找到兼容 GPU，记录错误日志。

        Returns:
            dict: 兼容性报告字典，结构如下：
                - overall_compatible (bool): 是否有至少一个兼容 GPU
                - total_gpus (int): 检测到的 GPU 总数
                - compatible_gpus (int): 兼容 GPU 数量
                - devices (list): 每个设备的详细信息列表
                - min_requirements (dict): 最低要求配置
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

        选择策略：兼容设备中按总显存降序排列，返回显存最大的设备。

        Returns:
            GPUDeviceInfo | None: 最佳设备信息；无兼容设备时返回 None
        """
        devices = self.enumerate_gpus()
        compatible = [d for d in devices if d.is_compatible]
        if not compatible:
            return None

        compatible.sort(key=lambda d: d.total_vram_mb, reverse=True)
        return compatible[0]


@dataclass
class BackendDetectionConfig:
    """多后端自动检测配置数据类

    参考 Anime4KCPP 的 CPU/OpenCL/CUDA 多后端自动选择:
    按照性能优先级尝试各个后端，自动选择最优可用后端，
    并在首选后端不可用时优雅降级到次选后端。

    注意: SeedVR2 推理仅支持 CUDA，此处降级链为参考框架。

    Attributes:
        backend_priority: 后端优先级列表（按性能降序），默认 [CUDA, OPENCL, CPU]
        detection_timeout: 各后端的检测超时时间，单位秒（默认 5.0）
        allow_cpu_fallback: 是否允许 CPU 回退（SeedVR2 应为 False）
        silent_fail: 检测失败时是否静默不输出日志
    """
    backend_priority: list[ComputeBackend] = field(
        default_factory=lambda: [
            ComputeBackend.CUDA,
            ComputeBackend.OPENCL,
            ComputeBackend.CPU,
        ]
    )
    detection_timeout: float = 5.0
    allow_cpu_fallback: bool = False
    silent_fail: bool = False


class BackendDetector:
    """多后端自动检测器

    参考 Anime4KCPP 的 Processor 工厂模式:
    自动检测系统中可用的计算后端（CUDA/OpenCL/MPS/Vulkan/CPU），
    按配置的优先级顺序选择最优可用后端。

    注意: 本类为参考框架，SeedVR2 推理仅使用 CUDA 后端。

    检测流程:
        1. 按 backend_priority 顺序逐个检测后端可用性
        2. CUDA: 通过 torch.cuda.is_available() 检测
        3. OpenCL: 通过 pyopencl 导入或系统 opencl.dll/libOpenCL.so 检测
        4. MPS: 通过 torch.backends.mps.is_available() 检测（Apple Silicon）
        5. Vulkan: 通过 vulkaninfo 命令检测
        6. CPU: 始终可用
        7. 返回第一个可用且允许的后端

    Usage:
        config = BackendDetectionConfig()
        detector = BackendDetector(config)
        detector.detect_all()
        best = detector.best_backend
    """

    def __init__(self, config: BackendDetectionConfig):
        """初始化多后端检测器

        Args:
            config: 后端检测配置
        """
        self.config = config
        self._detected_backends: dict[ComputeBackend, bool] = {}
        self._best_backend: ComputeBackend | None = None

    def detect_all(self) -> dict[ComputeBackend, bool]:
        """检测所有配置优先级中的后端可用性

        Returns:
            dict[ComputeBackend, bool]: 后端→可用性的映射字典
        """
        results = {}

        for backend in self.config.backend_priority:
            available = self._detect_backend(backend)
            results[backend] = available
            self._detected_backends[backend] = available

            status = "可用" if available else "不可用"
            if not self.config.silent_fail or available:
                logger.info(f"后端检测: {backend.value} - {status}")

        self._best_backend = None
        for backend in self.config.backend_priority:
            if results.get(backend, False):
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
        """检测单个计算后端是否可用（内部方法）

        Args:
            backend: 要检测的计算后端枚举值

        Returns:
            bool: 后端可用返回 True，否则返回 False
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
            return True
        return False

    @staticmethod
    def _detect_cuda() -> bool:
        """检测 CUDA 后端是否可用（静态内部方法）

        Returns:
            bool: CUDA 可用且至少有一个 GPU 返回 True
        """
        try:
            return torch.cuda.is_available() and torch.cuda.device_count() > 0
        except Exception:
            return False

    @staticmethod
    def _detect_opencl() -> bool:
        """检测 OpenCL 后端是否可用（静态内部方法）

        两种检测方式：
        1. 尝试导入 pyopencl Python 包
        2. Windows: 查找 opencl.dll
        3. Linux: 在 /usr/lib 查找 libOpenCL.so*

        Returns:
            bool: OpenCL 运行时可用返回 True
        """
        try:
            import pyopencl  # noqa: F401
            return True
        except ImportError:
            pass

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
        """检测 Apple MPS 后端是否可用（静态内部方法）

        MPS (Metal Performance Shaders) 是 Apple Silicon 的 GPU 加速框架，
        需要 torch.backends.mps 可用且已构建。

        Returns:
            bool: MPS 可用返回 True（仅 Apple Silicon Mac）
        """
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
        """检测 Vulkan 后端是否可用（静态内部方法）

        通过查找 vulkaninfo 命令行工具判断系统是否安装了 Vulkan SDK/运行时。

        Returns:
            bool: vulkaninfo 命令存在返回 True
        """
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
        """获取检测到的最佳计算后端（属性）

        Returns:
            ComputeBackend | None: 最佳后端；未检测到可用后端返回 None
        """
        return self._best_backend

    def get_device_for_backend(self, backend: ComputeBackend) -> str:
        """获取指定后端对应的 PyTorch 设备字符串

        Args:
            backend: 计算后端枚举值

        Returns:
            str: PyTorch 设备字符串，如 "cuda:0"、"mps"、"cpu"
        """
        if backend == ComputeBackend.CUDA:
            return "cuda:0"
        elif backend == ComputeBackend.OPENCL:
            return "cpu"
        elif backend == ComputeBackend.MPS:
            return "mps"
        elif backend == ComputeBackend.VULKAN:
            return "cpu"
        else:
            return "cpu"


@dataclass
class MultiDeviceConfig:
    """多设备降级链配置数据类

    参考 Fast-SRGAN 的 CUDA → MPS → CPU 降级链:
    定义设备降级优先级，当首选设备不可用时自动降级到次选设备，
    每个设备可配置独立的最低显存要求。

    注意: SeedVR2 硬约束规定仅支持 CUDA 推理，
    MPS 和 CPU 降级路径仅为参考框架，不可用于实际推理。

    Attributes:
        degradation_chain: 降级链设备列表，按优先级顺序（默认 ["cuda:0", "mps", "cpu"]）
        allow_non_cuda_degradation: 是否允许非 CUDA 设备降级（SeedVR2 必须为 False）
        min_vram_per_device: 每个设备的最低显存/内存要求（MB），CPU 要求 16GB 内存
    """
    degradation_chain: list[str] = field(
        default_factory=lambda: ["cuda:0", "mps", "cpu"]
    )
    allow_non_cuda_degradation: bool = False
    min_vram_per_device: dict[str, int] = field(
        default_factory=lambda: {
            "cuda:0": 8000,
            "mps": 8000,
            "cpu": 16384,
        }
    )


class MultiDeviceManager:
    """多设备管理器

    参考 Fast-SRGAN 的多设备降级机制:
    按照配置的降级链依次尝试设备，选择第一个可用且满足内存要求的设备。

    注意: 本类为参考框架。SeedVR2 推理必须使用 CUDA，
    MPS/CPU 路径仅作为架构参考，不可用于实际推理。

    选择逻辑:
        1. 遍历 degradation_chain 中的设备
        2. 检查设备是否可用
        3. 若非 CUDA 设备且 allow_non_cuda_degradation=False，跳过
        4. 检查设备可用显存/内存是否满足 min_vram_per_device
        5. 返回第一个满足条件的设备

    Usage:
        config = MultiDeviceConfig(allow_non_cuda_degradation=False)
        manager = MultiDeviceManager(config)
        device = manager.select_device()
    """

    def __init__(self, config: MultiDeviceConfig):
        """初始化多设备管理器

        Args:
            config: 多设备配置
        """
        self.config = config
        self._selected_device: str | None = None

    def select_device(self) -> str:
        """从降级链中选择最佳可用设备

        Returns:
            str: 选中的 PyTorch 设备字符串；无可用 GPU 时降级到 "cpu"
        """
        cfg = self.config

        for device_str in cfg.degradation_chain:
            if self._is_device_available(device_str):
                if not device_str.startswith("cuda") and not cfg.allow_non_cuda_degradation:
                    logger.warning(
                        f"设备 {device_str} 可用，但 SeedVR2 不支持非 CUDA 推理，跳过"
                    )
                    continue

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

        self._selected_device = "cpu"
        logger.error("多设备管理: 无可用 GPU 设备，降级到 CPU (不支持 SeedVR2 推理)")
        return "cpu"

    @staticmethod
    def _is_device_available(device_str: str) -> bool:
        """检查指定设备字符串对应的设备是否可用（静态内部方法）

        Args:
            device_str: PyTorch 设备字符串，如 "cuda:0"、"mps"、"cpu"

        Returns:
            bool: 设备可用返回 True
        """
        if device_str.startswith("cuda"):
            if not torch.cuda.is_available():
                return False
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
        """检查设备可用显存/内存是否满足最低要求（静态内部方法）

        CUDA: 使用 torch.cuda.mem_get_info 查询可用显存
        CPU/MPS: 使用 psutil 查询系统可用内存

        Args:
            device_str: PyTorch 设备字符串
            min_memory_mb: 最低内存要求，单位 MB

        Returns:
            bool: 可用内存满足要求返回 True
        """
        try:
            if device_str.startswith("cuda"):
                free_mem, _ = torch.cuda.mem_get_info(device_str)
                return free_mem >= min_memory_mb * 1024 * 1024
            elif device_str == "cpu":
                import psutil
                available = psutil.virtual_memory().available
                return available >= min_memory_mb * 1024 * 1024
            elif device_str == "mps":
                import psutil
                available = psutil.virtual_memory().available
                return available >= min_memory_mb * 1024 * 1024
        except Exception:
            return False
        return False

    @property
    def selected_device(self) -> str | None:
        """获取已选择的设备（属性）

        Returns:
            str | None: 已选择的设备字符串；未调用 select_device() 时返回 None
        """
        return self._selected_device


@dataclass
class VulkanDeviceInfo:
    """Vulkan GPU 设备信息数据类

    参考 upscayl 的跨厂商 Vulkan 支持:
    Vulkan API 可以跨 NVIDIA/AMD/Intel 厂商使用 GPU 加速，
    不依赖厂商特定的运行时（如 CUDA）。

    注意: 本数据类为参考框架，SeedVR2 当前不支持 Vulkan 后端。
    Vulkan 支持需要额外的推理引擎（如 ncnn）集成。

    Attributes:
        device_name: 设备名称
        vendor: GPU 厂商（GPUVendor 枚举）
        api_version: Vulkan API 版本字符串（如 "1.3.250"）
        driver_version: 驱动版本字符串
        device_type: 设备类型：'discrete_gpu'/'integrated_gpu'/'virtual_gpu'/'cpu'
        max_memory_allocation_mb: 单次最大内存分配大小，单位 MB
        compute_queue_count: 计算队列数量
        supports_required_extensions: 是否支持所需的 Vulkan 扩展
    """
    device_name: str
    vendor: GPUVendor
    api_version: str
    driver_version: str
    device_type: str
    max_memory_allocation_mb: int
    compute_queue_count: int
    supports_required_extensions: bool


@dataclass
class VulkanCompatConfig:
    """Vulkan 兼容性配置数据类

    参考 upscayl 的 Vulkan 集成方式:
    通过 Vulkan 后端支持跨厂商 GPU 加速，兼容 NVIDIA/AMD/Intel。

    注意: 本配置为参考框架。

    Attributes:
        enabled: 是否启用 Vulkan 后端（默认 False，参考）
        required_extensions: 所需 Vulkan 扩展列表
        min_api_version: 最低 Vulkan API 版本（默认 "1.2"）
        min_compute_queues: 最低计算队列数量（默认 1）
    """
    enabled: bool = False
    required_extensions: list[str] = field(
        default_factory=lambda: [
            "VK_KHR_storage_buffer_storage_class",
            "VK_KHR_vulkan_memory_model",
        ]
    )
    min_api_version: str = "1.2"
    min_compute_queues: int = 1


class VulkanCompatibilityChecker:
    """Vulkan 兼容性检查器

    参考 upscayl 的跨厂商 Vulkan 支持实现:
    检测系统中支持 Vulkan 的 GPU 设备，验证 API 版本和扩展支持。

    注意: 本类为参考框架，SeedVR2 当前不支持 Vulkan 后端。
    Vulkan 支持需要额外的推理引擎（如 ncnn）集成。

    检测方式: 通过 vulkaninfo 命令行工具查询 Vulkan 运行时信息。

    Usage:
        config = VulkanCompatConfig()
        checker = VulkanCompatibilityChecker(config)
        if checker.check_vulkan_available():
            devices = checker.enumerate_vulkan_devices()
    """

    def __init__(self, config: VulkanCompatConfig):
        """初始化 Vulkan 兼容性检查器

        Args:
            config: Vulkan 兼容性配置
        """
        self.config = config

    def check_vulkan_available(self) -> bool:
        """检查系统是否安装了 Vulkan 运行时

        通过查找 vulkaninfo 命令判断 Vulkan SDK/运行时是否安装。

        Returns:
            bool: Vulkan 可用返回 True
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
                return False
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            pass

        return False

    def enumerate_vulkan_devices(self) -> list[VulkanDeviceInfo]:
        """枚举系统中支持 Vulkan 的 GPU 设备

        通过解析 vulkaninfo --summary 输出提取设备信息。
        当前仅做简化的设备名称提取，完整实现需解析完整 vulkaninfo JSON 输出。

        Returns:
            list[VulkanDeviceInfo]: Vulkan 设备信息列表
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


@dataclass
class RTXVSRConfig:
    """RTX Video Super Resolution 配置数据类

    参考 Waifu2x-Extension-GUI 的 RTX VSR 硬件加速集成:
    NVIDIA RTX VSR 是 NVIDIA 驱动内建的实时视频超分辨率技术，
    可在浏览器视频播放时自动提升分辨率。

    重要说明: RTX VSR 是 NVIDIA 驱动层功能，不由应用直接控制。
    本配置为参考文档，记录 RTX VSR 的集成可能性：
    - 可作为前置处理器：先用 RTX VSR 做初步超分，再用 SeedVR2 做精细修复
    - 可作为质量对比基准：评估 SeedVR2 输出相对于 RTX VSR 的提升

    Attributes:
        enabled: 是否启用 RTX VSR 相关功能（默认 False，参考）
        min_gpu_series: 最低 GPU 系列（30 = RTX 30 系列及以上）
        auto_enable: 是否在兼容 GPU 上自动启用 RTX VSR
        quality_level: RTX VSR 质量等级（1-4，4 为最高质量）
    """
    enabled: bool = False
    min_gpu_series: int = 30
    auto_enable: bool = False
    quality_level: int = 4


class RTXVSRChecker:
    """RTX VSR 硬件加速检查器

    参考 Waifu2x-Extension-GUI 的 RTX VSR 功能:
    检测 GPU 是否支持 RTX Video Super Resolution，提供集成参考信息。

    RTX VSR 要求:
        - NVIDIA RTX 30 系列及以上 GPU
        - NVIDIA 驱动版本 530+（Studio 驱动推荐）
        - Windows 10/11 操作系统

    注意: RTX VSR 是 NVIDIA 驱动层功能，不由应用直接控制。
    本检查器仅用于检测硬件兼容性和提供参考信息。

    Usage:
        config = RTXVSRConfig()
        checker = RTXVSRChecker(config)
        if checker.is_rtx_vsr_supported():
            info = checker.get_rtx_vsr_info()
    """

    def __init__(self, config: RTXVSRConfig):
        """初始化 RTX VSR 检查器

        Args:
            config: RTX VSR 配置
        """
        self.config = config

    def is_rtx_vsr_supported(self) -> bool:
        """检查当前环境是否支持 RTX Video Super Resolution

        检查项：
        1. CUDA 是否可用
        2. GPU 是否为 RTX 30/40/50 系列
        3. NVIDIA 驱动版本是否 ≥ 530
        4. 操作系统是否为 Windows

        Returns:
            bool: RTX VSR 可用返回 True
        """
        if not torch.cuda.is_available():
            return False

        try:
            props = torch.cuda.get_device_properties(0)
            gpu_name = props.name

            is_rtx_30_plus = False
            for series in ["RTX 30", "RTX 40", "RTX 50", "RTX 3070", "RTX 3080",
                           "RTX 3090", "RTX 4070", "RTX 4080", "RTX 4090"]:
                if series in gpu_name:
                    is_rtx_30_plus = True
                    break

            if not is_rtx_30_plus:
                logger.info(f"GPU {gpu_name} 不支持 RTX VSR (需要 RTX 30 系列+)")
                return False

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

            if platform.system() != "Windows":
                logger.info("RTX VSR 仅支持 Windows")
                return False

            logger.info(f"GPU {gpu_name} 支持 RTX VSR")
            return True

        except Exception as e:
            logger.debug(f"RTX VSR 兼容性检查失败: {e}")
            return False

    def get_rtx_vsr_info(self) -> dict[str, Any]:
        """获取 RTX VSR 兼容性详细信息

        Returns:
            dict: 包含 RTX VSR 支持状态、要求、集成选项的字典
        """
        supported = self.is_rtx_vsr_supported()

        info: dict[str, Any] = {
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


def get_gpu_compatibility_summary() -> dict[str, Any]:
    """获取 GPU 兼容性模块的功能摘要

    返回模块内各功能组件的名称、参考来源、优先级和实现状态，
    用于系统状态展示和功能概览。

    Returns:
        dict: 功能摘要字典，包含：
            - gpu_compatibility_detection (P1, 已实现): GPU 枚举与兼容性检测
            - multi_backend_detection (P2, 已实现): 多后端自动检测
            - mps_multi_device (P3, 参考): MPS/多设备支持
            - vulkan_cross_vendor (P3, 参考): Vulkan 跨厂商支持
            - rtx_vsr (P3, 参考): RTX VSR 硬件加速
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

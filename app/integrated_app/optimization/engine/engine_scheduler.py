"""多引擎架构 / 引擎调度框架模块

所属项目: SeedVR2 (SeedVR2 视频/图像修复应用)
核心技术栈: Python, PyTorch, ThreadPoolExecutor, ABC抽象基类

本模块实现 SeedVR2 的多引擎调度框架，参考 Waifu2x-Extension-GUI 十余种引擎的
进程级管理 + 线程池模式，提供统一的引擎注册、调度、兼容性检测和多后端支持。

主要功能:
- EngineRegistry: 基于装饰器模式的引擎自动注册机制
- EngineScheduler: 多引擎任务调度器，支持线程池并发管理
- Upscaler 抽象体系: 统一的放大/修复引擎基类接口
- ProcessorFactory: Anime4KCPP 风格多后端 (CPU/OpenCL/CUDA) 处理器工厂
- ArchRegistry: BasicSR 风格模型架构注册管理
- MultiGPUDispatcher: Real-CUGAN 风格多 GPU 多线程调度
- SubprocessEngineWrapper: upscayl 风格子进程引擎隔离调用
- RestorePipeline: DiffBIR 风格修复流水线继承体系

参考竞品与设计来源:
- Waifu2x-Extension-GUI (多引擎调度框架) - P0
- Waifu2x-Extension-GUI (引擎兼容性检测) - P1
- Anime4KCPP (多后端 Processor 工厂模式) - P2
- BasicSR (@ARCH_REGISTRY.register() 装饰器) - P2
- DiffBIR (Pipeline 继承体系) - P2
- clarity-upscaler (Upscaler 抽象体系) - P1
- Real-CUGAN (多 GPU 多线程调度) - P2
- upscayl (子进程引擎调用) - P2
"""

import logging
import os
import subprocess
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import torch

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Engine Status Enum
# ---------------------------------------------------------------------------


class EngineStatus(Enum):
    """引擎运行状态枚举。

    定义引擎在生命周期中可能处于的各种状态，用于调度器判断引擎可用性
    和任务执行状态。

    Attributes:
        UNAVAILABLE: 依赖缺失或GPU不兼容，引擎不可用
        AVAILABLE: 引擎可用但尚未加载到内存
        LOADING: 引擎正在加载模型权重
        READY: 引擎已加载完成，可以接收推理任务
        RUNNING: 引擎正在执行推理任务
        ERROR: 引擎加载或推理过程中发生错误
    """

    UNAVAILABLE = "unavailable"
    AVAILABLE = "available"
    LOADING = "loading"
    READY = "ready"
    RUNNING = "running"
    ERROR = "error"


class EngineCapability(Enum):
    """引擎能力类型枚举。

    定义引擎支持的功能能力类型，用于引擎能力声明和任务-引擎匹配。
    调度器根据任务所需能力自动选择合适的引擎。

    Attributes:
        IMAGE_UPSCALE: 图像超分辨率放大
        VIDEO_UPSCALE: 视频超分辨率放大
        IMAGE_RESTORE: 图像修复（去噪、去模糊、去压缩等）
        VIDEO_RESTORE: 视频修复
        FACE_RESTORE: 人脸专门修复
        COLOR_FIX: 颜色校正/上色
        FRAME_INTERPOLATE: 视频帧插值
    """

    IMAGE_UPSCALE = "image_upscale"
    VIDEO_UPSCALE = "video_upscale"
    IMAGE_RESTORE = "image_restore"
    VIDEO_RESTORE = "video_restore"
    FACE_RESTORE = "face_restore"
    COLOR_FIX = "color_fix"
    FRAME_INTERPOLATE = "frame_interpolate"


# ---------------------------------------------------------------------------
# Upscaler 抽象体系 (clarity-upscaler inspired) - P1
# ---------------------------------------------------------------------------


@dataclass
class UpscaleResult:
    """引擎推理/放大操作的结果数据类。

    统一封装所有引擎执行结果，包含成功标志、输出路径/张量、错误信息、
    处理时间和元数据，供调度器和上层调用方统一处理。

    Attributes:
        success: 操作是否成功完成
        output_path: 输出文件路径（文件输出模式）
        output_tensor: 输出张量（内存模式）
        error: 错误信息（失败时）
        processing_time: 处理耗时（秒）
        metadata: 额外元数据字典（如引擎信息、参数、帧数等）
    """

    success: bool
    output_path: str | None = None
    output_tensor: torch.Tensor | None = None
    error: str | None = None
    processing_time: float = 0.0
    metadata: dict = field(default_factory=dict)


class Upscaler(ABC):
    """Upscaler 抽象基类

    参考 clarity-upscaler 的 Upscaler 基类 + do_upscale() 接口，
    定义所有引擎的统一契约。

    所有 Upscaler 子类必须实现:
    - do_upscale(): 核心放大逻辑
    - is_available(): 检查引擎是否可用
    - get_info(): 获取引擎信息
    """

    # 子类通过类属性声明引擎元信息
    engine_name: str = "unknown"
    engine_version: str = "0.0"
    capabilities: list[EngineCapability] = []
    requires_gpu: bool = True
    requires_cuda: bool = False  # True 表示必须 NVIDIA CUDA

    @abstractmethod
    def do_upscale(self, input_path: str, output_path: str, **kwargs) -> UpscaleResult:
        """核心放大逻辑

        Args:
            input_path: 输入文件路径
            output_path: 输出文件路径
            **kwargs: 引擎特定参数

        Returns:
            UpscaleResult
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查引擎是否可用 (依赖是否满足、GPU 是否兼容)"""
        pass

    @abstractmethod
    def get_info(self) -> dict:
        """获取引擎信息"""
        pass

    def upscale(self, input_path: str, output_path: str, **kwargs) -> UpscaleResult:
        """放大入口 (带错误处理和日志)

        Args:
            input_path: 输入文件路径
            output_path: 输出文件路径
            **kwargs: 引擎特定参数

        Returns:
            UpscaleResult
        """
        if not self.is_available():
            return UpscaleResult(success=False, error=f"引擎 {self.engine_name} 不可用")

        try:
            result = self.do_upscale(input_path, output_path, **kwargs)
            return result
        except Exception as e:
            logger.error(f"引擎 {self.engine_name} 放大失败: {e}")
            return UpscaleResult(success=False, error=str(e), metadata={"engine": self.engine_name})


# ---------------------------------------------------------------------------
# EngineRegistry (BasicSR @ARCH_REGISTRY inspired) - P2
# ---------------------------------------------------------------------------


class EngineRegistry:
    """引擎注册表

    参考 BasicSR 的 @ARCH_REGISTRY.register() 装饰器自动注册模式。
    所有 Upscaler 子类通过装饰器自动注册到此全局注册表。

    Usage:
        @EngineRegistry.register()
        class SeedVR2Upscaler(Upscaler):
            ...

        # 获取所有可用引擎
        available = EngineRegistry.get_available_engines()

        # 通过名称获取引擎
        engine = EngineRegistry.get_engine("seedvr2")
    """

    _registry: dict[str, type[Upscaler]] = {}
    _instances: dict[str, Upscaler] = {}

    @classmethod
    def register(cls, name: str | None = None):
        """注册装饰器

        Args:
            name: 注册名称，None 时使用类名
        """

        def decorator(upscaler_cls: type[Upscaler]):
            reg_name = name or upscaler_cls.engine_name or upscaler_cls.__name__.lower()
            cls._registry[reg_name] = upscaler_cls
            logger.info(f"引擎注册: {reg_name} -> {upscaler_cls.__name__}")
            return upscaler_cls

        return decorator

    @classmethod
    def get_engine(cls, name: str, **kwargs) -> Upscaler | None:
        """获取引擎实例

        Args:
            name: 引擎名称
            **kwargs: 引擎初始化参数

        Returns:
            Upscaler 实例，或 None
        """
        if name not in cls._registry:
            logger.warning(f"未注册的引擎: {name}")
            return None

        # 缓存实例
        if name not in cls._instances:
            cls._instances[name] = cls._registry[name](**kwargs)

        return cls._instances[name]

    @classmethod
    def get_available_engines(cls) -> list[str]:
        """获取所有可用引擎名称"""
        available = []
        for name, _upscaler_cls in cls._registry.items():
            try:
                instance = cls.get_engine(name)
                if instance and instance.is_available():
                    available.append(name)
            except Exception:
                pass
        return available

    @classmethod
    def get_all_registered(cls) -> dict[str, type[Upscaler]]:
        """获取所有注册的引擎类"""
        return dict(cls._registry)

    @classmethod
    def clear(cls):
        """清除所有注册和实例"""
        cls._registry.clear()
        cls._instances.clear()


# ---------------------------------------------------------------------------
# EngineScheduler (Waifu2x-Extension-GUI inspired) - P0
# ---------------------------------------------------------------------------


@dataclass
class ScheduledTask:
    """调度任务数据类。

    表示引擎调度器中的一个推理任务，包含任务标识、引擎选择、
    输入输出路径、参数和执行状态。

    Attributes:
        task_id: 任务唯一标识符（UUID前缀）
        engine_name: 执行任务的引擎名称
        input_path: 输入文件路径
        output_path: 输出文件路径
        kwargs: 引擎特定参数字典
        status: 任务状态（pending/running/completed/error）
        result: 任务执行结果（完成后填充）
        error: 错误信息（失败时填充）
    """

    task_id: str
    engine_name: str
    input_path: str
    output_path: str
    kwargs: dict = field(default_factory=dict)
    status: str = "pending"
    result: UpscaleResult | None = None
    error: str | None = None


class EngineScheduler:
    """多引擎调度框架

    参考 Waifu2x-Extension-GUI 的十余种引擎进程级管理 + 线程池:
    - 根据任务类型自动选择最合适的引擎
    - 支持进程级引擎隔离 (避免 GPU 资源冲突)
    - 线程池管理并发推理
    - 自动检测引擎兼容性

    Usage:
        scheduler = EngineScheduler(max_workers=1)

        # 添加任务
        task_id = scheduler.submit(
            engine_name="seedvr2",
            input_path="input.jpg",
            output_path="output.jpg",
            resolution=2048,
        )

        # 获取结果
        result = scheduler.get_result(task_id)
    """

    def __init__(self, max_workers: int = 1):
        """初始化调度器

        Args:
            max_workers: 最大并发工作线程数 (默认 1，避免 GPU OOM)
        """
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._tasks: dict[str, ScheduledTask] = {}
        self._lock = threading.Lock()
        self._running = False
        self._engine_preferences: dict[EngineCapability, list[str]] = {
            EngineCapability.IMAGE_RESTORE: ["seedvr2"],
            EngineCapability.VIDEO_RESTORE: ["seedvr2"],
            EngineCapability.IMAGE_UPSCALE: ["seedvr2"],
            EngineCapability.VIDEO_UPSCALE: ["seedvr2"],
            EngineCapability.FACE_RESTORE: ["codeformer"],
            EngineCapability.COLOR_FIX: ["seedvr2"],
            EngineCapability.FRAME_INTERPOLATE: ["rife"],
        }

        logger.info(f"引擎调度器初始化: max_workers={max_workers}")

    def detect_available_engines(self) -> dict[str, EngineStatus]:
        """检测所有注册引擎的可用性

        Returns:
            {engine_name: status} 字典
        """
        results = {}
        for name in EngineRegistry.get_all_registered():
            engine = EngineRegistry.get_engine(name)
            if engine:
                if engine.is_available():
                    results[name] = EngineStatus.AVAILABLE
                else:
                    results[name] = EngineStatus.UNAVAILABLE
            else:
                results[name] = EngineStatus.UNAVAILABLE

        logger.info(f"引擎兼容性检测: {results}")
        return results

    def submit(
        self,
        engine_name: str | None = None,
        input_path: str = "",
        output_path: str = "",
        capability: EngineCapability | None = None,
        **kwargs,
    ) -> str:
        """提交推理任务

        Args:
            engine_name: 指定引擎名称，None 时根据 capability 自动选择
            input_path: 输入文件路径
            output_path: 输出文件路径
            capability: 任务能力类型 (用于自动选择引擎)
            **kwargs: 引擎特定参数

        Returns:
            task_id
        """
        import uuid

        task_id = str(uuid.uuid4())[:8]

        # 自动选择引擎
        if engine_name is None:
            if capability and capability in self._engine_preferences:
                for preferred in self._engine_preferences[capability]:
                    engine = EngineRegistry.get_engine(preferred)
                    if engine and engine.is_available():
                        engine_name = preferred
                        break

            if engine_name is None:
                available = EngineRegistry.get_available_engines()
                if available:
                    engine_name = available[0]
                else:
                    raise RuntimeError("没有可用的引擎")

        task = ScheduledTask(
            task_id=task_id,
            engine_name=engine_name,
            input_path=input_path,
            output_path=output_path,
            kwargs=kwargs,
        )

        with self._lock:
            self._tasks[task_id] = task

        # 提交到线程池
        self._executor.submit(self._execute_task, task)

        return task_id

    def _execute_task(self, task: ScheduledTask) -> None:
        """执行任务 (在工作线程中)"""
        task.status = "running"

        engine = EngineRegistry.get_engine(task.engine_name)
        if engine is None:
            task.status = "error"
            task.error = f"引擎 {task.engine_name} 不存在"
            return

        try:
            result = engine.upscale(
                task.input_path,
                task.output_path,
                **task.kwargs,
            )
            task.result = result
            task.status = "completed" if result.success else "error"
        except Exception as e:
            task.status = "error"
            task.error = str(e)
            logger.error(f"任务 {task.task_id} 执行失败: {e}")

    def get_result(self, task_id: str) -> UpscaleResult | None:
        """获取任务结果"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                return task.result
        return None

    def get_task_status(self, task_id: str) -> str:
        """获取任务状态"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                return task.status
        return "unknown"

    def shutdown(self) -> None:
        """关闭调度器"""
        self._executor.shutdown(wait=True)
        self._running = False
        logger.info("引擎调度器已关闭")


# ---------------------------------------------------------------------------
# SeedVR2 Upscaler 实现 (将现有引擎接入抽象体系)
# ---------------------------------------------------------------------------


@EngineRegistry.register("seedvr2")
class SeedVR2Upscaler(Upscaler):
    """SeedVR2 Upscaler - 接入统一抽象体系"""

    engine_name = "seedvr2"
    engine_version = "1.0"
    capabilities = [
        EngineCapability.IMAGE_UPSCALE,
        EngineCapability.VIDEO_UPSCALE,
        EngineCapability.IMAGE_RESTORE,
        EngineCapability.VIDEO_RESTORE,
        EngineCapability.COLOR_FIX,
    ]
    requires_gpu = True
    requires_cuda = True

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self._engine = None

    def is_available(self) -> bool:
        """检查 SeedVR2 引擎是否可用"""
        return torch.cuda.is_available()

    def get_info(self) -> dict:
        """获取引擎信息"""
        info = {
            "name": self.engine_name,
            "version": self.engine_version,
            "capabilities": [c.value for c in self.capabilities],
            "requires_cuda": self.requires_cuda,
            "cuda_available": torch.cuda.is_available(),
        }
        if torch.cuda.is_available():
            info["gpu_name"] = torch.cuda.get_device_name(0)
            info["gpu_memory_gb"] = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        return info

    def do_upscale(self, input_path: str, output_path: str, **kwargs) -> UpscaleResult:
        """核心放大逻辑 - 调用 SeedVR2Engine"""
        # SeedVR2Engine 是异步接口，这里提供同步包装
        # 实际推理由 task_queue 调度，此处仅提供框架
        import asyncio

        async def _run():
            from app.integrated_app.engines.seedvr2_engine import SeedVR2Engine

            engine = SeedVR2Engine(self.config)
            await engine.load_model()

            if input_path.endswith((".mp4", ".avi", ".mkv", ".mov", ".webm")):
                result = await engine.infer_video(input_path, os.path.dirname(output_path), **kwargs)
            else:
                result = await engine.infer_image(input_path, os.path.dirname(output_path), **kwargs)

            await engine.unload_model()
            return result

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 在已有事件循环中运行
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, _run())
                    restore_result = future.result(timeout=600)
            else:
                restore_result = loop.run_until_complete(_run())

            return UpscaleResult(
                success=restore_result.success,
                output_path=restore_result.output_path,
                error=restore_result.error,
                processing_time=restore_result.processing_time,
                metadata=restore_result.metadata,
            )
        except Exception as e:
            return UpscaleResult(success=False, error=str(e))


# ---------------------------------------------------------------------------
# Pipeline 继承体系 (DiffBIR inspired) - P2
# ---------------------------------------------------------------------------


class RestorePipeline(ABC):
    """修复流水线抽象基类。

    参考 DiffBIR 的 Pipeline 子类覆写模式，定义统一的多阶段推理流水线接口。
    子类通过覆写抽象方法实现不同的修复流水线（如粗修复→精修复、预处理→修复→后处理等）。

    流水线标准执行流程:
        1. set_output_size: 设置目标输出分辨率
        2. apply_cleaner: 预处理/清洁步骤
        3. apply_restoration: 核心修复步骤
        4. run: 串联执行完整流水线
    """

    def __init__(self, config: dict):
        """初始化修复流水线。

        Args:
            config: 流水线配置字典
        """
        self.config = config

    @abstractmethod
    def set_output_size(self, size: int) -> None:
        """设置输出目标尺寸。

        在流水线执行前调用，配置输出分辨率。子类应根据size调整
        内部处理参数（如缩放因子、分块大小等）。

        Args:
            size: 输出目标尺寸（长边像素数）
        """
        pass

    @abstractmethod
    def apply_cleaner(self, image: torch.Tensor, **kwargs) -> torch.Tensor:
        """应用清洁/预处理步骤。

        对输入图像进行预处理，如去噪、颜色空间转换、归一化等。
        这是流水线的第一阶段处理。

        Args:
            image: 输入图像张量 (B, C, H, W)
            **kwargs: 额外预处理参数

        Returns:
            预处理后的图像张量
        """
        pass

    @abstractmethod
    def apply_restoration(self, image: torch.Tensor, **kwargs) -> torch.Tensor:
        """应用核心修复步骤。

        执行主要的修复/超分推理，这是流水线的核心处理阶段。
        输入应为apply_cleaner处理后的结果。

        Args:
            image: 预处理后的图像张量 (B, C, H, W)
            **kwargs: 额外修复参数

        Returns:
            修复后的图像张量
        """
        pass

    def run(self, input: torch.Tensor, **kwargs) -> torch.Tensor:
        """运行完整修复流水线。

        按顺序执行预处理→修复的完整流程。子类可覆写此方法以添加
        后处理步骤或自定义流水线逻辑。

        Args:
            input: 输入图像张量 (B, C, H, W)
            **kwargs: 传递给各阶段的参数

        Returns:
            流水线最终输出张量
        """
        cleaned = self.apply_cleaner(input, **kwargs)
        restored = self.apply_restoration(cleaned, **kwargs)
        return restored


# ---------------------------------------------------------------------------
# 多后端 Processor 工厂模式 (Anime4KCPP inspired) - P2
# ---------------------------------------------------------------------------


class ProcessorBackend(Enum):
    """处理器计算后端类型枚举。

    参考 Anime4KCPP 的 CPU/OpenCL/CUDA 三后端支持模式。
    同一算法可在不同计算后端上运行，ProcessorFactory根据硬件可用性
    自动选择最优后端。

    Attributes:
        CPU: 通用CPU后端，始终可用
        OPENCL: OpenCL跨平台GPU计算后端
        CUDA: NVIDIA CUDA GPU计算后端（性能最优）
    """

    CPU = "cpu"
    OPENCL = "opencl"
    CUDA = "cuda"


@dataclass
class ProcessorFactoryConfig:
    """Processor 工厂配置

    参考 Anime4KCPP 的多后端 Processor 工厂模式:
    支持 CPU/OpenCL/CUDA 三种后端，自动检测可用后端并选择最优。

    Attributes:
        preferred_backend: 首选后端 (None 时自动检测)
        fallback_order: 后端回退顺序 (当首选不可用时依次尝试)
        enable_auto_detect: 是否启用自动检测
        opencl_device_index: OpenCL 设备索引
        cuda_device_index: CUDA 设备索引
    """

    preferred_backend: ProcessorBackend | None = None
    fallback_order: list[ProcessorBackend] = field(
        default_factory=lambda: [ProcessorBackend.CUDA, ProcessorBackend.OPENCL, ProcessorBackend.CPU]
    )
    enable_auto_detect: bool = True
    opencl_device_index: int = 0
    cuda_device_index: int = 0


class ProcessorFactory:
    """多后端 Processor 工厂

    参考 Anime4KCPP 的 CPU/OpenCL/CUDA 三后端自动切换模式:
    根据硬件可用性自动检测并选择最优计算后端，
    同一算法在不同后端上提供统一的 Processor 接口。

    用法:
        factory = ProcessorFactory(config)
        processor = factory.create_processor()  # 自动选择最优后端
        processor = factory.create_processor(backend=ProcessorBackend.CUDA)  # 指定后端
    """

    def __init__(self, config: ProcessorFactoryConfig | None = None):
        self.config = config or ProcessorFactoryConfig()
        self._available_backends: dict[ProcessorBackend, bool] = {}
        self._detect_available_backends()

    def _detect_available_backends(self) -> None:
        """检测所有可用后端"""
        # CUDA 检测
        self._available_backends[ProcessorBackend.CUDA] = torch.cuda.is_available()

        # OpenCL 检测 (尝试导入 pyopencl)
        try:
            import pyopencl  # noqa: F401

            self._available_backends[ProcessorBackend.OPENCL] = True
        except ImportError:
            self._available_backends[ProcessorBackend.OPENCL] = False

        # CPU 始终可用
        self._available_backends[ProcessorBackend.CPU] = True

        available = [b.value for b, ok in self._available_backends.items() if ok]
        logger.info(f"Processor 工厂后端检测: 可用={available}")

    def get_best_backend(self) -> ProcessorBackend:
        """获取最优可用后端

        优先级顺序: CUDA > OpenCL > CPU

        Returns:
            最优可用后端
        """
        # 如果指定了首选后端且可用，直接使用
        if self.config.preferred_backend is not None and self._available_backends.get(
            self.config.preferred_backend, False
        ):
            return self.config.preferred_backend

        # 按回退顺序查找
        for backend in self.config.fallback_order:
            if self._available_backends.get(backend, False):
                return backend

        # 默认 CPU
        return ProcessorBackend.CPU

    def create_processor(
        self,
        backend: ProcessorBackend | None = None,
        **kwargs,
    ) -> dict:
        """创建指定后端的 Processor

        参考 Anime4KCPP 的 Processor 工厂:
        根据后端类型创建对应的 Processor 实例，
        返回包含后端信息和处理配置的字典。

        Args:
            backend: 目标后端，None 时自动选择最优
            **kwargs: Processor 初始化参数

        Returns:
            Processor 配置字典，包含 backend, device 等信息
        """
        if backend is None:
            backend = self.get_best_backend()

        if not self._available_backends.get(backend, False):
            logger.warning(f"后端 {backend.value} 不可用，回退到最优后端")
            backend = self.get_best_backend()

        processor_config = {
            "backend": backend.value,
            "available": True,
            **kwargs,
        }

        if backend == ProcessorBackend.CUDA:
            device_idx = self.config.cuda_device_index
            processor_config["device"] = f"cuda:{device_idx}"
            processor_config["device_name"] = torch.cuda.get_device_name(device_idx)
            processor_config["vram_gb"] = torch.cuda.get_device_properties(device_idx).total_memory / (1024**3)
        elif backend == ProcessorBackend.OPENCL:
            processor_config["device"] = f"opencl:{self.config.opencl_device_index}"
            processor_config["device_name"] = "OpenCL Device"
        else:
            processor_config["device"] = "cpu"

        logger.info(f"Processor 工厂创建: backend={backend.value}, device={processor_config['device']}")
        return processor_config

    def list_available_backends(self) -> list[ProcessorBackend]:
        """列出所有可用后端"""
        return [b for b, ok in self._available_backends.items() if ok]


# ---------------------------------------------------------------------------
# Registry 模式 - 模型架构注册 (BasicSR @ARCH_REGISTRY inspired) - P2
# ---------------------------------------------------------------------------


@dataclass
class ArchRegistryConfig:
    """架构注册表配置

    参考 BasicSR 的 @ARCH_REGISTRY.register() 装饰器:
    自动注册模型架构类，支持按类别 (backbone, neck, head, loss) 管理和查询。

    Attributes:
        allow_override: 是否允许同名覆盖注册
        strict_category: 是否严格类别校验
    """

    allow_override: bool = False
    strict_category: bool = True


class ArchRegistry:
    """模型架构注册表

    参考 BasicSR 的 @ARCH_REGISTRY.register() 装饰器自动注册模式:
    与 EngineRegistry 不同，ArchRegistry 专注于模型架构 (Architecture) 的注册，
    支持 backbone/neck/head/loss 等细粒度分类管理和查询。

    用法:
        @ArchRegistry.register_arch(category="backbone")
        class UNetBackbone(nn.Module):
            ...

        # 按类别查询
        backbones = ArchRegistry.get_by_category("backbone")

        # 按名称获取
        arch_cls = ArchRegistry.get_arch("UNetBackbone")
    """

    _registry: dict[str, dict[str, Any]] = {}
    _config = ArchRegistryConfig()

    @classmethod
    def configure(cls, config: ArchRegistryConfig) -> None:
        """配置注册表行为

        Args:
            config: 注册表配置
        """
        cls._config = config

    @classmethod
    def register_arch(cls, category: str = "backbone", name: str | None = None):
        """架构注册装饰器

        参考 BasicSR 的 @ARCH_REGISTRY.register() 装饰器:
        将模型架构类注册到指定类别下。

        Args:
            category: 架构类别 ('backbone', 'neck', 'head', 'loss')
            name: 注册名称，None 时使用类名

        Returns:
            装饰器函数
        """
        valid_categories = {"backbone", "neck", "head", "loss"}

        if cls._config.strict_category and category not in valid_categories:
            raise ValueError(f"无效的架构类别: {category}，有效值为: {valid_categories}")

        def decorator(arch_cls: type):
            reg_name = name or arch_cls.__name__

            if reg_name in cls._registry and not cls._config.allow_override:
                logger.warning(f"架构 {reg_name} 已注册，跳过覆盖")
                return arch_cls

            cls._registry[reg_name] = {
                "class": arch_cls,
                "category": category,
                "name": reg_name,
            }
            logger.info(f"架构注册: {reg_name} (category={category})")
            return arch_cls

        return decorator

    @classmethod
    def get_arch(cls, name: str) -> type | None:
        """按名称获取架构类

        Args:
            name: 架构名称

        Returns:
            架构类，或 None
        """
        entry = cls._registry.get(name)
        return entry["class"] if entry else None

    @classmethod
    def get_by_category(cls, category: str) -> dict[str, type]:
        """按类别查询所有架构

        Args:
            category: 架构类别

        Returns:
            {name: class} 字典
        """
        return {name: entry["class"] for name, entry in cls._registry.items() if entry["category"] == category}

    @classmethod
    def list_all(cls) -> dict[str, dict[str, Any]]:
        """列出所有已注册架构"""
        return dict(cls._registry)

    @classmethod
    def clear(cls) -> None:
        """清除所有注册"""
        cls._registry.clear()


# ---------------------------------------------------------------------------
# 多 GPU 多线程调度 (Real-CUGAN inspired) - P2
# ---------------------------------------------------------------------------


@dataclass
class MultiGPUConfig:
    """多 GPU 调度配置

    参考 bilibili-ailab (Real-CUGAN) 的 VideoRealWaFuUpScaler 队列式并行:
    支持多 GPU 设备列表，队列式任务分配到不同 GPU，使用 ThreadPoolExecutor 管理多线程。

    Attributes:
        gpu_ids: GPU 设备 ID 列表
        max_workers_per_gpu: 每个 GPU 的最大工作线程数
        queue_timeout: 队列等待超时 (秒)
        balance_strategy: 负载均衡策略 ('round_robin', 'least_loaded', 'memory_aware')
    """

    gpu_ids: list[int] = field(default_factory=lambda: [0])
    max_workers_per_gpu: int = 1
    queue_timeout: float = 300.0
    balance_strategy: str = "round_robin"


class MultiGPUDispatcher:
    """多 GPU 多线程调度器

    参考 bilibili-ailab (Real-CUGAN) 的 VideoRealWaFuUpScaler 队列式并行:
    将推理任务队列式分配到不同 GPU，每个 GPU 独立线程执行，
    实现多 GPU 并行推理，提升吞吐量。

    核心设计:
    - 队列式任务分配: 任务入队后自动分配到最空闲的 GPU
    - ThreadPoolExecutor: 每个 GPU 对应独立线程池
    - 负载均衡: round_robin / least_loaded / memory_aware 三种策略
    - GPU 显存感知: memory_aware 策略下优先分配到显存充裕的 GPU

    用法:
        dispatcher = MultiGPUDispatcher(config)
        task_id = dispatcher.submit(my_func, arg1, arg2)
        result = dispatcher.get_result(task_id)
    """

    def __init__(self, config: MultiGPUConfig | None = None):
        self.config = config or MultiGPUConfig()
        self._executors: dict[int, ThreadPoolExecutor] = {}
        self._task_counter: int = 0
        self._lock = threading.Lock()
        self._results: dict[str, Any] = {}
        self._gpu_loads: dict[int, int] = dict.fromkeys(self.config.gpu_ids, 0)

        # 验证 GPU 可用性
        available_gpus = []
        for gpu_id in self.config.gpu_ids:
            if gpu_id < torch.cuda.device_count():
                available_gpus.append(gpu_id)
                self._executors[gpu_id] = ThreadPoolExecutor(
                    max_workers=self.config.max_workers_per_gpu,
                )
            else:
                logger.warning(f"GPU {gpu_id} 不存在，跳过")

        self._available_gpus = available_gpus
        self._round_robin_idx = 0

        logger.info(f"多 GPU 调度器初始化: gpus={available_gpus}, " f"strategy={self.config.balance_strategy}")

    def _select_gpu(self) -> int | None:
        """根据负载均衡策略选择 GPU

        Returns:
            选中的 GPU ID，或 None (无可用 GPU)
        """
        if not self._available_gpus:
            return None

        strategy = self.config.balance_strategy

        if strategy == "round_robin":
            gpu_id = self._available_gpus[self._round_robin_idx % len(self._available_gpus)]
            self._round_robin_idx += 1
            return gpu_id

        elif strategy == "least_loaded":
            return min(self._gpu_loads, key=self._gpu_loads.get)

        elif strategy == "memory_aware":
            # 优先选择显存充裕的 GPU
            best_gpu = None
            best_free = -1
            for gpu_id in self._available_gpus:
                try:
                    free_mem = torch.cuda.mem_get_info(gpu_id)[0]
                    if free_mem > best_free:
                        best_free = free_mem
                        best_gpu = gpu_id
                except RuntimeError:
                    continue
            return best_gpu or self._available_gpus[0]

        return self._available_gpus[0]

    def submit(self, fn: Callable, *args, **kwargs) -> str:
        """提交任务到多 GPU 调度

        Args:
            fn: 要执行的函数
            *args: 函数位置参数
            **kwargs: 函数关键字参数

        Returns:
            task_id
        """
        import uuid

        task_id = str(uuid.uuid4())[:8]

        gpu_id = self._select_gpu()
        if gpu_id is None:
            raise RuntimeError("没有可用的 GPU")

        with self._lock:
            self._gpu_loads[gpu_id] += 1

        def _wrapper():
            try:
                # 设置当前 CUDA 设备
                torch.cuda.set_device(gpu_id)
                result = fn(*args, **kwargs)
                with self._lock:
                    self._results[task_id] = result
                    self._gpu_loads[gpu_id] -= 1
                return result
            except Exception as e:
                with self._lock:
                    self._results[task_id] = e
                    self._gpu_loads[gpu_id] -= 1
                logger.error(f"GPU {gpu_id} 任务 {task_id} 失败: {e}")
                raise

        self._executors[gpu_id].submit(_wrapper)
        logger.debug(f"任务 {task_id} 分配到 GPU {gpu_id}")
        return task_id

    def get_result(self, task_id: str) -> Any:
        """获取任务结果

        Args:
            task_id: 任务 ID

        Returns:
            任务结果
        """
        with self._lock:
            return self._results.get(task_id)

    def get_gpu_loads(self) -> dict[int, int]:
        """获取各 GPU 当前负载"""
        return dict(self._gpu_loads)

    def shutdown(self) -> None:
        """关闭所有线程池"""
        for gpu_id, executor in self._executors.items():
            executor.shutdown(wait=True)
            logger.debug(f"GPU {gpu_id} 线程池已关闭")
        logger.info("多 GPU 调度器已关闭")


# ---------------------------------------------------------------------------
# 子进程引擎调用 (upscayl spawnUpscayl() inspired) - P2
# ---------------------------------------------------------------------------


@dataclass
class SubprocessEngineConfig:
    """子进程引擎配置

    参考 upscayl 的 spawnUpscayl() 进程封装模式:
    使用子进程封装外部引擎调用，隔离进程空间，避免 GPU 资源冲突。

    注意: upscayl 使用 GPL-3.0 许可证，此处仅借鉴设计模式，不复制代码。

    Attributes:
        engine_command: 外部引擎可执行文件路径
        args: 引擎命令行参数模板
        timeout: 单次推理超时 (秒)
        poll_interval: 进程状态轮询间隔 (秒)
        max_retries: 最大重试次数
        encoding: 子进程输出编码
    """

    engine_command: str = ""
    args: list[str] = field(default_factory=list)
    timeout: float = 600.0
    poll_interval: float = 1.0
    max_retries: int = 2
    encoding: str = "utf-8"


class SubprocessEngineWrapper:
    """子进程引擎封装

    参考 upscayl 的 spawnUpscayl() 进程封装模式:
    使用 subprocess.Popen 封装外部引擎调用，支持 stdin/stdout/stderr 通信，
    提供进程状态监控和超时控制。

    核心设计:
    - 子进程隔离: 每次推理在独立子进程中执行，避免 GPU 资源冲突
    - stdin/stdout 通信: 支持通过管道向引擎传递参数和接收结果
    - 进程状态监控: 轮询检测进程是否存活和是否超时
    - 超时控制: 超时后自动终止子进程

    注意: upscayl 使用 GPL-3.0 许可证，此处仅借鉴设计模式，不复制代码。

    用法:
        config = SubprocessEngineConfig(
            engine_command="realesrgan-ncnn-vulkan",
            args=["-i", "{input}", "-o", "{output}", "-s", "{scale}"],
        )
        wrapper = SubprocessEngineWrapper(config)
        result = wrapper.run(input="input.jpg", output="output.jpg", scale=4)
    """

    def __init__(self, config: SubprocessEngineConfig | None = None):
        self.config = config or SubprocessEngineConfig()
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def _build_command(self, **kwargs) -> list[str]:
        """构建命令行参数

        Args:
            **kwargs: 模板变量 (如 input, output, scale)

        Returns:
            完整命令行列表
        """
        cmd = [self.config.engine_command]
        for arg in self.config.args:
            try:
                cmd.append(arg.format(**kwargs))
            except KeyError:
                cmd.append(arg)
        return cmd

    def run(self, **kwargs) -> dict[str, Any]:
        """执行子进程引擎调用

        Args:
            **kwargs: 模板变量和引擎参数

        Returns:
            执行结果字典，包含 returncode, stdout, stderr, timed_out
        """
        cmd = self._build_command(**kwargs)
        logger.info(f"子进程引擎调用: {' '.join(cmd)}")

        result = {
            "returncode": -1,
            "stdout": "",
            "stderr": "",
            "timed_out": False,
        }

        for attempt in range(self.config.max_retries + 1):
            try:
                process = subprocess.Popen(  # nosemgrep: python36-compatibility-Popen2 - 项目目标 Python 3.10+，py3.6 兼容规则误触发
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    encoding=self.config.encoding,
                )

                with self._lock:
                    self._process = process

                try:
                    stdout, stderr = process.communicate(timeout=self.config.timeout)
                    result["returncode"] = process.returncode
                    result["stdout"] = stdout
                    result["stderr"] = stderr

                    if process.returncode == 0:
                        logger.info("子进程引擎完成: returncode=0")
                        return result
                    else:
                        logger.warning(
                            f"子进程引擎返回非零: returncode={process.returncode}, " f"stderr={stderr[:200]}"
                        )

                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    result["timed_out"] = True
                    logger.error(
                        f"子进程引擎超时 ({self.config.timeout}s)，" f"尝试 {attempt + 1}/{self.config.max_retries + 1}"
                    )

            except FileNotFoundError:
                result["stderr"] = f"引擎命令不存在: {self.config.engine_command}"
                logger.error(result["stderr"])
                break

            except Exception as e:
                result["stderr"] = str(e)
                logger.error(f"子进程引擎异常: {e}")

            finally:
                with self._lock:
                    self._process = None

        return result

    def is_running(self) -> bool:
        """检查子进程是否正在运行"""
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def terminate(self) -> None:
        """终止当前子进程"""
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
                logger.info("子进程引擎已终止")

    def kill(self) -> None:
        """强制杀死当前子进程"""
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                self._process.kill()
                logger.warning("子进程引擎已强制终止")

"""SeedVR2 视频/图像修复引擎抽象接口模块 —— 基于 Python Protocol 的三层解耦架构。

本模块定义了 SeedVR2 项目中所有修复引擎必须遵循的统一契约，
是引擎层与应用层之间的抽象接口层（借鉴 TTS_MultiModel 的 Protocol 化设计）。

架构分层：
    Routes / TaskQueue（应用层）
        ↓ 调用
    Protocol 协议层（本模块：RestoreEngine / BatchRestoreEngine / EngineRegistry）
        ↓ 运行时动态发现/注册/切换
    Concrete Engines（具体引擎实现，如 engines/seedvr2_engine.py）

三层 Protocol 设计：
    1. RestoreEngine — 基础修复引擎协议：所有引擎必须实现的最小能力
       （加载/卸载/单图修复/单视频修复/状态查询）
    2. BatchRestoreEngine(RestoreEngine) — 进阶批量修复协议：扩展批量处理能力
       （批量修复 + 进度回调）
    3. EngineRegistry — 引擎注册器协议：引擎发现与实例化管理契约
       （注册/获取/列表）

使用 @runtime_checkable 装饰器，支持 isinstance() 运行时协议类型检查，
实现类型安全的鸭子类型（structural subtyping）。

所属项目: SeedVR2 - SeedVR2 视频修复独立应用
核心技术栈: Python 3.10+, typing.Protocol, dataclasses
"""

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class RestoreResult:
    """修复任务执行结果数据类

    统一封装单张图片、单个视频或批量任务中单个条目的修复结果，
    包含成功状态、输出路径、错误信息、处理耗时和元数据。

    Attributes:
        success: 修复是否成功完成
        output_path: 修复后输出文件的绝对路径，失败时为 None
        error: 错误信息字符串，成功时为 None
        processing_time: 处理耗时，单位为秒
        metadata: 附加元数据字典，可包含模型大小、精度、分辨率、帧数等信息

    Example:
        >>> result = RestoreResult(success=True, output_path="/path/to/output.png", processing_time=10.5)
        >>> if result.success:
        ...     print(f"输出文件: {result.output_path}")
    """

    success: bool
    output_path: str | None = None
    error: str | None = None
    processing_time: float = 0.0
    metadata: dict = field(default_factory=dict)


# ===========================================================================
# 第一层：基础修复引擎协议
# ===========================================================================

@runtime_checkable
class RestoreEngine(Protocol):
    """基础修复引擎协议：所有修复引擎必须实现的最小能力。

    定义了引擎生命周期管理（加载/卸载）、推理接口（图像/视频）
    和状态查询的统一契约。使用 @runtime_checkable 支持 isinstance() 检查。

    典型实现类：
        - SeedVR2Engine（engines.seedvr2_engine）：SeedVR2 核心修复引擎

    Note:
        - 模型加载应是幂等的：重复加载相同配置应直接返回成功
        - 卸载模型应释放所有 GPU/CPU 资源
        - 所有推理方法必须是异步的，避免阻塞事件循环
    """

    def is_loaded(self) -> bool:
        """检查模型是否已成功加载。

        Returns:
            bool: 模型已加载并可用于推理返回 True，否则返回 False
        """
        ...

    def get_model_info(self) -> dict:
        """获取当前已加载模型的详细信息。

        Returns:
            dict: 模型信息字典，应包含至少以下键:
                - loaded: bool - 模型是否已加载
                - model_size: str - 模型大小标识 (如 "3b", "7b")
                - precision: str - 模型精度 (如 "fp16", "fp8")
                - device: str - 推理设备 (如 "cuda", "cpu")
                - model_name: str - 人类可读的模型名称
        """
        ...

    async def load_model(
        self, model_size: str = "3b", device: str = "auto", precision: str | None = None
    ) -> bool:
        """加载修复模型到内存/GPU。

        初始化模型结构、加载权重、配置推理组件。
        实现类应支持延迟加载策略（启动时只加载配置，推理时按需加载大模型）。

        Args:
            model_size: 模型大小标识，如 "3b"、"7b"，具体值由实现类定义
            device: 推理设备，"auto" 表示自动选择，"cuda" 表示使用 GPU
            precision: 模型精度，如 "fp16"、"fp8"，None 表示使用默认精度

        Returns:
            bool: 加载成功返回 True，失败返回 False

        Raises:
            RuntimeError: GPU 不可用（如仅支持 CUDA 但未检测到 NVIDIA GPU）
            FileNotFoundError: 模型权重文件不存在
            ValueError: 不支持的 model_size 或 precision
            MemoryError: GPU/CPU 内存不足无法加载模型
        """
        ...

    async def unload_model(self) -> bool:
        """卸载模型并释放所有 GPU/CPU 资源。

        卸载模型权重、销毁模型实例、清空 CUDA 缓存、触发垃圾回收。
        卸载后调用 is_loaded() 应返回 False。

        Returns:
            bool: 卸载成功返回 True，失败返回 False
        """
        ...

    async def infer_image(self, image_path: str, output_dir: str, **kwargs: Any) -> RestoreResult:
        """执行单张图像修复推理。

        读取输入图像、执行 VAE 编码、DiT 采样、VAE 解码、后处理，
        输出修复后的图像文件。

        Args:
            image_path: 输入图像文件的绝对路径
            output_dir: 输出目录路径，不存在时会自动创建
            **kwargs: 额外推理参数，可包含:
                - resolution: 目标分辨率（长边像素）
                - seed: 随机种子，-1 表示随机
                - color_fix: 颜色校正方法 ("lab"/"wavelet"/"none")

        Returns:
            RestoreResult: 修复结果对象，包含输出路径和元数据

        Raises:
            RuntimeError: 模型未加载或推理过程出错
            FileNotFoundError: 输入图像文件不存在
            MemoryError: 推理过程中内存不足
        """
        ...

    async def infer_video(self, video_path: str, output_dir: str, **kwargs: Any) -> RestoreResult:
        """执行视频修复推理。

        读取输入视频、分阶段执行 VAE 编码、DiT 采样、VAE 解码、后处理，
        输出修复后的视频文件。支持长视频分段处理、时间一致性增强等高级特性。

        Args:
            video_path: 输入视频文件的绝对路径
            output_dir: 输出目录路径，不存在时会自动创建
            **kwargs: 额外推理参数

        Returns:
            RestoreResult: 修复结果对象，包含输出路径和元数据

        Raises:
            RuntimeError: 模型未加载或推理过程出错
            FileNotFoundError: 输入视频文件不存在
            MemoryError: 推理过程中内存不足
        """
        ...

    def estimate_vram_required(self, model_size: str, resolution: tuple) -> int:
        """估算指定配置下推理所需的显存大小。

        根据模型大小和输入分辨率估算峰值显存占用，
        用于模型加载前的显存预检，避免 OOM。

        Args:
            model_size: 模型大小标识
            resolution: 输入分辨率元组 (height, width)，单位为像素

        Returns:
            int: 估算所需显存，单位为 MB
        """
        ...


# ===========================================================================
# 第二层：进阶批量修复引擎协议
# ===========================================================================

@runtime_checkable
class BatchRestoreEngine(RestoreEngine, Protocol):
    """进阶批量修复引擎协议：扩展批量处理能力。

    继承 RestoreEngine 的所有基础能力，额外定义批量修复接口。
    路由层应先通过 isinstance(engine, BatchRestoreEngine) 检查引擎能力
    后再调用本协议方法，避免 AttributeError。

    扩展能力包括：
        - 批量图像修复：扫描目录下所有图像，逐张/并行处理
        - 进度回调：通过 on_progress 回调实时报告处理进度
    """

    async def infer_batch(
        self,
        input_dir: str,
        output_dir: str,
        **kwargs: Any,
    ) -> list[RestoreResult]:
        """批量图像修复推理。

        扫描输入目录中的所有支持格式的图像文件，逐张执行修复。

        Args:
            input_dir: 输入图像目录路径
            output_dir: 输出目录路径，不存在时会自动创建
            **kwargs: 传递给 infer_image 的额外参数，可包含:
                - on_progress: 可选的进度回调函数 Callable[[int, int, float], None]
                  签名为 (current_index, total_count, progress_pct)

        Returns:
            list[RestoreResult]: 每张图像的修复结果列表，顺序与文件排序一致

        Note:
            - 默认实现不支持并行处理以避免 GPU OOM
            - 单张图片失败不影响其他图片处理
        """
        ...


# ===========================================================================
# 第三层：引擎注册器协议
# ===========================================================================

@runtime_checkable
class EngineRegistry(Protocol):
    """引擎注册器协议：定义引擎发现与实例化管理的最小契约。

    路由层通过本协议查询可用引擎列表与获取引擎类引用，
    与具体的注册表实现（内存注册表、磁盘注册表等）解耦。

    典型实现类：
        - _ModelRegistry（model_registry.py）：全局模型状态注册中心
    """

    def register(self, name: str, engine_class: type) -> None:
        """注册一个引擎类到注册表。

        Args:
            name: 引擎名称（如 "seedvr2"）
            engine_class: 引擎类（实现 RestoreEngine 协议的类）
        """
        ...

    def get(self, name: str) -> type | None:
        """从注册表获取引擎类。

        Args:
            name: 引擎名称

        Returns:
            type | None: 引擎类，未注册时返回 None
        """
        ...

    def list_engines(self) -> list[str]:
        """列出所有已注册的引擎名称。

        Returns:
            list[str]: 引擎名称列表
        """
        ...

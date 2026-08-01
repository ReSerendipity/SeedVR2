"""SeedVR2 视频/图像修复引擎抽象接口模块

本模块定义了 SeedVR2 项目中所有修复引擎必须遵循的统一契约，
是引擎层与应用层之间的抽象接口层。

所属项目: SeedVR2 - SeedVR2 视频修复独立应用
核心技术栈: Python 3.10+, ABC 抽象基类, dataclasses

模块职责:
- 定义 RestoreResult 数据类，统一封装修复任务的执行结果
- 定义 RestoreEngine 抽象基类 (ABC)，规范所有修复引擎必须实现的接口方法
- 提供默认的批量处理实现，子类可覆盖以优化批量性能

设计原则:
- 依赖倒置: 上层模块依赖抽象接口而非具体实现
- 开闭原则: 新增引擎类型只需继承 RestoreEngine 并实现抽象方法
- 接口隔离: 按功能拆分方法（加载/卸载、图像/视频/批量推理、状态查询）
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


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


class RestoreEngine(ABC):
    """修复引擎抽象基类

    所有视频/图像修复引擎必须继承此类并实现所有 abstractmethod。
    定义了引擎生命周期管理（加载/卸载）、推理接口（图像/视频/批量）
    和状态查询的统一契约。

    实现类示例:
        class MyEngine(RestoreEngine):
            async def load_model(self, model_size="3b", device="auto", precision=None):
                # 实现模型加载逻辑
                return True

            async def infer_image(self, image_path, output_dir, **kwargs):
                # 实现图像修复逻辑
                return RestoreResult(success=True, output_path=output_path)

    Note:
        - 模型加载应是幂等的：重复加载相同配置应直接返回成功
        - 卸载模型应释放所有 GPU/CPU 资源
        - 所有推理方法必须是异步的，避免阻塞事件循环
        - 批量处理默认实现为逐张调用 infer_image，子类可覆盖以优化性能
    """

    @abstractmethod
    async def load_model(self, model_size: str = "3b", device: str = "auto", precision: str | None = None) -> bool:
        """加载修复模型到内存/GPU

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
        pass

    @abstractmethod
    async def unload_model(self) -> bool:
        """卸载模型并释放所有 GPU/CPU 资源

        卸载模型权重、销毁模型实例、清空 CUDA 缓存、触发垃圾回收。
        卸载后调用 is_loaded() 应返回 False。

        Returns:
            bool: 卸载成功返回 True，失败返回 False
        """
        pass

    @abstractmethod
    async def infer_video(self, video_path: str, output_dir: str, **kwargs) -> RestoreResult:
        """执行视频修复推理

        读取输入视频、分阶段执行 VAE 编码、DiT 采样、VAE 解码、后处理，
        输出修复后的视频文件。支持长视频分段处理、时间一致性增强等高级特性。

        Args:
            video_path: 输入视频文件的绝对路径
            output_dir: 输出目录路径，不存在时会自动创建
            **kwargs: 额外推理参数，可包含:
                - resolution: 目标分辨率（长边像素）
                - seed: 随机种子，-1 表示随机
                - cfg_scale: Classifier-Free Guidance 缩放系数
                - sample_steps: 采样步数
                - color_fix: 颜色校正方法 ("lab"/"wavelet"/"none")
                - out_fps: 输出帧率，None 表示与输入相同

        Returns:
            RestoreResult: 修复结果对象，包含输出路径和元数据

        Raises:
            RuntimeError: 模型未加载或推理过程出错
            FileNotFoundError: 输入视频文件不存在
            MemoryError: 推理过程中内存不足
            InferenceCancelledError: 推理被用户或超时取消
        """
        pass

    @abstractmethod
    async def infer_image(self, image_path: str, output_dir: str, **kwargs) -> RestoreResult:
        """执行单张图像修复推理

        读取输入图像、执行 VAE 编码、DiT 采样、VAE 解码、后处理，
        输出修复后的图像文件。

        Args:
            image_path: 输入图像文件的绝对路径
            output_dir: 输出目录路径，不存在时会自动创建
            **kwargs: 额外推理参数，可包含:
                - resolution: 目标分辨率（长边像素）
                - seed: 随机种子，-1 表示随机
                - cfg_scale: Classifier-Free Guidance 缩放系数
                - sample_steps: 采样步数
                - color_fix: 颜色校正方法 ("lab"/"wavelet"/"none")

        Returns:
            RestoreResult: 修复结果对象，包含输出路径和元数据

        Raises:
            RuntimeError: 模型未加载或推理过程出错
            FileNotFoundError: 输入图像文件不存在
            MemoryError: 推理过程中内存不足
            InferenceCancelledError: 推理被用户或超时取消
        """
        pass

    async def infer_batch(self, input_dir: str, output_dir: str, **kwargs) -> list[RestoreResult]:
        """批量图像修复推理

        扫描输入目录中的所有支持格式的图像文件，逐张执行修复。
        默认实现为串行调用 infer_image，子类可覆盖以实现并行批处理优化。

        Args:
            input_dir: 输入图像目录路径
            output_dir: 输出目录路径，不存在时会自动创建
            **kwargs: 传递给 infer_image 的额外参数

        Returns:
            list[RestoreResult]: 每张图像的修复结果列表，顺序与文件排序一致

        Note:
            - 默认实现不支持并行处理以避免 GPU OOM
            - 单张图片失败不影响其他图片处理
            - 子类覆盖时应保持相同的错误容忍行为
        """
        return [RestoreResult(success=False, error="批量处理未实现")]

    @abstractmethod
    def is_loaded(self) -> bool:
        """检查模型是否已成功加载

        Returns:
            bool: 模型已加载并可用于推理返回 True，否则返回 False
        """
        pass

    @abstractmethod
    def get_model_info(self) -> dict:
        """获取当前已加载模型的详细信息

        Returns:
            dict: 模型信息字典，应包含至少以下键:
                - loaded: bool - 模型是否已加载
                - model_size: str - 模型大小标识 (如 "3b", "7b")
                - precision: str - 模型精度 (如 "fp16", "fp8")
                - device: str - 推理设备 (如 "cuda", "cpu")
                - model_name: str - 人类可读的模型名称
        """
        pass

    @abstractmethod
    def estimate_vram_required(self, model_size: str, resolution: tuple) -> int:
        """估算指定配置下推理所需的显存大小

        根据模型大小和输入分辨率估算峰值显存占用，
        用于模型加载前的显存预检，避免 OOM。

        Args:
            model_size: 模型大小标识
            resolution: 输入分辨率元组 (height, width)，单位为像素

        Returns:
            int: 估算所需显存，单位为 MB
        """
        pass

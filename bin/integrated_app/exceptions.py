"""SeedVR2 统一异常层次结构

所有业务异常均继承自 RestoreError，提供统一的 code / detail / http_status 接口，
便于 FastAPI 错误处理器自动映射为结构化 JSON 响应。
"""


class RestoreError(Exception):
    """视频修复系统基础异常

    Attributes:
        code: 错误码字符串，如 "INSUFFICIENT_VRAM"
        detail: 结构化上下文字典，用于前端展示或日志记录
    """

    code: str = "RESTORE_ERROR"

    def __init__(self, message: str = "视频修复操作失败", *, code: str | None = None, detail: dict | None = None):
        """初始化基础异常。

        Args:
            message: 人类可读的错误消息。
            code: 可选的错误码，覆盖类级别的 code 属性。
            detail: 可选的结构化上下文字典，用于前端展示或日志记录。
        """
        self.message = message
        if code is not None:
            self.code = code
        self.detail = detail or {}
        super().__init__(message)

    @classmethod
    def http_status(cls) -> int:
        """返回该异常对应的 HTTP 状态码，子类可覆盖"""
        return 500

    def to_dict(self) -> dict:
        """将异常转换为字典格式"""
        return {
            "code": self.code,
            "message": self.message,
            "detail": self.detail,
        }


class ModelLoadError(RestoreError):
    """模型加载失败

    当模型权重文件损坏、格式不兼容或加载过程中发生 I/O 错误时抛出。
    HTTP 状态码 503（Service Unavailable）。
    """

    code = "MODEL_LOAD_FAILED"

    def __init__(self, message: str = "模型加载失败", *, detail: dict | None = None):
        """初始化模型加载失败异常。

        Args:
            message: 错误消息。
            detail: 结构化上下文信息。
        """
        super().__init__(message, detail=detail)

    @classmethod
    def http_status(cls) -> int:
        return 503


class ModelUnloadError(RestoreError):
    """模型卸载失败

    当模型卸载过程中发生错误（如 GPU 资源释放失败）时抛出。
    HTTP 状态码 503（Service Unavailable）。
    """

    code = "MODEL_UNLOAD_FAILED"

    def __init__(self, message: str = "模型卸载失败", *, detail: dict | None = None):
        """初始化模型卸载失败异常。

        Args:
            message: 错误消息。
            detail: 结构化上下文信息。
        """
        super().__init__(message, detail=detail)

    @classmethod
    def http_status(cls) -> int:
        return 503


class InsufficientVRAMError(RestoreError):
    """GPU 显存不足

    当推理所需 GPU 显存超过可用显存时抛出，与系统内存不足区分。
    HTTP 状态码 422（Unprocessable Entity）。
    """

    code = "INSUFFICIENT_VRAM"

    def __init__(self, message: str = "GPU 显存不足", *, detail: dict | None = None):
        """初始化 GPU 显存不足异常。

        Args:
            message: 错误消息。
            detail: 结构化上下文信息（如需要多少显存、可用多少）。
        """
        super().__init__(message, detail=detail)

    @classmethod
    def http_status(cls) -> int:
        return 422


class InsufficientRAMError(RestoreError):
    """系统内存不足

    当推理所需系统内存超过可用内存时抛出，与 GPU 显存不足区分。
    HTTP 状态码 422（Unprocessable Entity）。
    """

    code = "INSUFFICIENT_RAM"

    def __init__(self, message: str = "系统内存不足", *, detail: dict | None = None):
        """初始化系统内存不足异常。

        Args:
            message: 错误消息。
            detail: 结构化上下文信息。
        """
        super().__init__(message, detail=detail)

    @classmethod
    def http_status(cls) -> int:
        return 422


class InferenceError(RestoreError):
    """推理执行失败

    当模型推理过程中发生运行时错误（如 CUDA 错误、张量维度不匹配）时抛出。
    HTTP 状态码 500（Internal Server Error）。
    """

    code = "INFERENCE_FAILED"

    def __init__(self, message: str = "推理执行失败", *, detail: dict | None = None):
        """初始化推理执行失败异常。

        Args:
            message: 错误消息。
            detail: 结构化上下文信息。
        """
        super().__init__(message, detail=detail)

    @classmethod
    def http_status(cls) -> int:
        return 500


class BlockSwapError(RestoreError):
    """BlockSwap 优化失败

    当 BlockSwap 显存优化策略执行失败（如块交换调度错误）时抛出。
    HTTP 状态码 500（Internal Server Error）。
    """

    code = "BLOCK_SWAP_FAILED"

    def __init__(self, message: str = "BlockSwap 优化失败", *, detail: dict | None = None):
        """初始化 BlockSwap 优化失败异常。

        Args:
            message: 错误消息。
            detail: 结构化上下文信息。
        """
        super().__init__(message, detail=detail)

    @classmethod
    def http_status(cls) -> int:
        return 500


class VAEDecodeError(RestoreError):
    """VAE 解码失败

    当 VAE 解码潜空间表示为像素图像时发生错误抛出。
    HTTP 状态码 500（Internal Server Error）。
    """

    code = "VAE_DECODE_FAILED"

    def __init__(self, message: str = "VAE 解码失败", *, detail: dict | None = None):
        """初始化 VAE 解码失败异常。

        Args:
            message: 错误消息。
            detail: 结构化上下文信息。
        """
        super().__init__(message, detail=detail)

    @classmethod
    def http_status(cls) -> int:
        return 500


class VAEEncodeError(RestoreError):
    """VAE 编码失败

    当 VAE 编码像素图像为潜空间表示时发生错误抛出。
    HTTP 状态码 500（Internal Server Error）。
    """

    code = "VAE_ENCODE_FAILED"

    def __init__(self, message: str = "VAE 编码失败", *, detail: dict | None = None):
        """初始化 VAE 编码失败异常。

        Args:
            message: 错误消息。
            detail: 结构化上下文信息。
        """
        super().__init__(message, detail=detail)

    @classmethod
    def http_status(cls) -> int:
        return 500


class ConfigError(RestoreError):
    """配置验证失败

    当应用配置项缺失、类型错误或值不合法时抛出。
    HTTP 状态码 400（Bad Request）。
    """

    code = "CONFIG_ERROR"

    def __init__(self, message: str = "配置验证失败", *, detail: dict | None = None):
        """初始化配置验证失败异常。

        Args:
            message: 错误消息。
            detail: 结构化上下文信息（如哪个配置项出错）。
        """
        super().__init__(message, detail=detail)

    @classmethod
    def http_status(cls) -> int:
        return 400


class ModelFileNotFoundError(RestoreError):
    """模型文件未找到

    当指定的模型权重文件或配置文件在磁盘上不存在时抛出。
    HTTP 状态码 404（Not Found）。
    """

    code = "MODEL_FILE_NOT_FOUND"

    def __init__(self, message: str = "模型文件未找到", *, detail: dict | None = None):
        """初始化模型文件未找到异常。

        Args:
            message: 错误消息。
            detail: 结构化上下文信息（如期望的文件路径）。
        """
        super().__init__(message, detail=detail)

    @classmethod
    def http_status(cls) -> int:
        return 404


# REFACTOR [E4-1]: 新增推理取消异常，用于 CancellationToken 机制
# 原实现 task_queue 超时后调用 asyncio.wait_for 取消 asyncio.Task，
# 但底层 asyncio.to_thread 包装的推理线程无法被 cancel，GPU 资源持续占用
# 新增此异常 + CancellationToken，让推理线程在阶段切换点主动检查并退出

class InferenceCancelledError(RestoreError):
    """推理被取消

    当任务队列超时或用户主动取消时，引擎通过 CancellationToken
    在阶段切换点检测到取消信号后抛出此异常。

    与 asyncio.CancelledError 的区别:
    - asyncio.CancelledError: 协程级取消，无法中断 to_thread 中的同步代码
    - InferenceCancelledError: 引擎主动检查 cancel event 后抛出，
      可在同步推理代码中触发，确保 GPU 资源及时释放

    HTTP 状态码 400（Bad Request，语义上类似 499 Client Closed Request）。
    """

    code = "INFERENCE_CANCELLED"

    def __init__(self, message: str = "推理已被取消", *, detail: dict | None = None):
        """初始化推理取消异常。

        Args:
            message: 错误消息。
            detail: 结构化上下文信息。
        """
        super().__init__(message, detail=detail)

    @classmethod
    def http_status(cls) -> int:
        # 客户端可视为 499（Client Closed Request）的语义，但保持 499 非标准
        # 这里返回 400 以兼容标准 HTTP 状态码
        return 400

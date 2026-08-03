#!/usr/bin/env python3
"""
SeedVR2 - 配置数据模型定义模块

所属项目：SeedVR2 (AI-powered video & image super-resolution toolkit)
核心功能：
    - 使用 Pydantic BaseModel 定义完整的应用配置层次结构
    - 自动类型转换与强制（ConfigDict 配置）
    - 字段范围校验（field_validator 装饰器）
    - 未知字段自动过滤（extra="ignore"）
    - 默认值管理与嵌套模型组合
    - 请求参数模型（图像/视频修复参数）定义

核心技术栈：
    - Pydantic 2.x 用于数据验证和模型定义
    - Field 用于字段默认值、范围约束和元数据
    - field_validator 用于自定义字段校验逻辑
    - ConfigDict 配置模型行为（如忽略未知字段）

配置模型层次结构：
    AppConfig (根)
    ├── ServerConfig          # HTTP 服务器配置
    ├── ModelConfig           # 模型加载配置
    │   └── ModelEntryConfig  # 单个模型条目配置
    ├── RestoreConfig         # 修复算法参数
    ├── GpuConfig             # GPU 后端配置
    ├── HistoryConfig         # 历史记录数据库配置
    ├── I18nConfig            # 国际化配置
    ├── LoggingConfig         # 日志配置
    ├── CacheConfig           # 文件缓存配置
    ├── InferenceConfig       # 推理优化配置
    ├── RuntimeConfig         # 运行时参数（替代硬编码）
    │   ├── RuntimeSseConfig       # SSE 推送配置
    │   ├── RuntimeBatchConfig     # 批量任务配置
    │   ├── RuntimeTaskConfig      # 任务队列配置
    │   ├── RuntimeUploadConfig    # 上传配置
    │   └── RuntimeSecurityConfig  # 安全配置
    └── user_preferences      # 用户偏好设置（前端管理）
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ServerConfig(BaseModel):
    """HTTP 服务器配置模型。

    定义 FastAPI/Uvicorn 服务器监听地址、端口、调试模式等参数。

    Attributes:
        host: 监听地址，默认仅本地访问（127.0.0.1）。
        port: 监听端口，默认 7870，必须在 1-65535 范围内。
        debug: 是否启用调试模式（热重载、详细错误）。
        auto_open_browser: 启动后是否自动打开浏览器访问应用。
        allowed_origins: CORS 允许的源列表，用于跨域请求控制。
    """

    model_config = ConfigDict(extra="ignore")
    host: str = "127.0.0.1"
    port: int = 7870
    debug: bool = False
    auto_open_browser: bool = True
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:7870", "http://localhost:7870"])

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """验证端口号是否在合法范围内。

        Args:
            v: 待验证的端口号。

        Returns:
            int: 验证通过的端口号。

        Raises:
            ValueError: 端口号不在 1-65535 范围内时抛出。
        """
        if not (1 <= v <= 65535):
            raise ValueError(f"port 必须在 1-65535 范围内，当前值: {v}")
        return v


class ModelEntryConfig(BaseModel):
    """单个模型条目配置模型。

    定义一个可加载模型的完整路径和资源需求信息，
    用于模型管理器根据可用显存自动选择合适的模型版本。

    Attributes:
        name: 模型显示名称。
        config_dir: 模型配置文件目录路径。
        checkpoint_fp16: FP16 精度检查点文件路径。
        checkpoint_fp8: FP8 精度检查点文件路径（显存需求更低）。
        vae_checkpoint: VAE 模型检查点路径。
        pos_emb: 正面提示词嵌入路径。
        neg_emb: 负面提示词嵌入路径。
        min_vram_fp16_gb: 加载 FP16 版本所需最小显存（GB）。
        min_vram_fp8_gb: 加载 FP8 版本所需最小显存（GB）。
        num_blocks: Transformer 块数量，用于 BlockSwap 策略。
    """

    model_config = ConfigDict(extra="ignore")
    name: str = ""
    config_dir: str = ""
    checkpoint_fp16: str = ""
    checkpoint_fp8: str = ""
    vae_checkpoint: str = ""
    pos_emb: str = ""
    neg_emb: str = ""
    min_vram_fp16_gb: int = 16
    min_vram_fp8_gb: int = 8
    num_blocks: int = 36


class ModelConfig(BaseModel):
    """模型加载与管理配置模型。

    定义默认模型大小、精度、预训练目录、自动加载等参数，
    以及所有可用模型的配置字典。

    Attributes:
        default_size: 默认模型大小标识（如 "3b" 表示 30 亿参数）。
        default_precision: 默认推理精度，"fp16" 或 "fp8"。
        pretrained_dir: 预训练模型文件根目录。
        auto_load: 应用启动时是否自动加载默认模型。
        device: 模型加载设备，"auto" 自动选择，或指定 "cuda:0"。
        models: 模型名称到 ModelEntryConfig 的映射字典。
    """

    model_config = ConfigDict(extra="ignore")
    default_size: str = "3b"
    default_precision: str = "fp16"
    pretrained_dir: str = "."
    auto_load: bool = True
    device: str = "auto"
    models: dict[str, ModelEntryConfig] = Field(default_factory=dict)


class RestoreConfig(BaseModel):
    """视频/图像修复算法默认参数配置模型。

    定义修复任务的默认分辨率、缩放因子、时序一致性等参数，
    视频修复时统一从此读取而非前端表单控制。

    Attributes:
        default_resolution_h: 默认输出高度（像素）。
        default_resolution_w: 默认输出宽度（像素）。
        default_scale_factor: 默认放大倍数，1.0-4.0 范围内。
        temporal_consistency: 时序一致性权重，0-1 之间，值越高帧间越稳定但可能模糊。
        detail_enhancement: 细节增强模式，如 "cinematic"（电影质感）。
        seed: 默认随机种子，用于可复现结果。
        sp_size: 时空处理块大小。
    """

    model_config = ConfigDict(extra="ignore")
    default_resolution_h: int = 1080
    default_resolution_w: int = 1920
    default_scale_factor: float = 2.0
    temporal_consistency: float = 0.8
    detail_enhancement: str = "cinematic"
    seed: int = 42
    sp_size: int = 1

    @field_validator("default_scale_factor")
    @classmethod
    def validate_scale_factor(cls, v: float) -> float:
        """验证缩放因子是否在合法范围内。

        Args:
            v: 待验证的缩放因子。

        Returns:
            float: 验证通过的缩放因子。

        Raises:
            ValueError: 缩放因子不在 1.0-4.0 范围内时抛出。
        """
        if not (1.0 <= v <= 4.0):
            raise ValueError(f"default_scale_factor 必须在 1.0-4.0 范围内，当前值: {v}")
        return v


class GpuConfig(BaseModel):
    """GPU 后端配置模型。

    Attributes:
        backend: GPU 后端类型，"auto" 自动检测，或指定 "cuda"。
    """

    model_config = ConfigDict(extra="ignore")
    backend: str = "auto"


class HistoryConfig(BaseModel):
    """历史记录数据库配置模型。

    定义 SQLite 历史记录数据库路径和最大记录数限制。

    Attributes:
        db_path: SQLite 数据库文件路径，相对于项目根目录。
        max_records: 最大历史记录条数，1-100000 范围内，超出自动清理旧记录。
    """

    model_config = ConfigDict(extra="ignore")
    db_path: str = "data/history.db"
    max_records: int = 10000

    @field_validator("max_records")
    @classmethod
    def validate_max_records(cls, v: int) -> int:
        """验证最大记录数是否在合法范围内。

        Args:
            v: 待验证的最大记录数。

        Returns:
            int: 验证通过的最大记录数。

        Raises:
            ValueError: 记录数不在 1-100000 范围内时抛出。
        """
        if not (1 <= v <= 100000):
            raise ValueError(f"max_records 必须在 1-100000 范围内，当前值: {v}")
        return v


class I18nConfig(BaseModel):
    """国际化（i18n）配置模型。

    定义默认语言和可用语言列表，翻译文件位于 locales/ 目录。

    Attributes:
        default_locale: 默认语言代码，"zh"（中文）、"en"（英文）、"ja"（日文）、"fr"（法文）。
        available_locales: 可用语言代码列表。
    """

    model_config = ConfigDict(extra="ignore")
    default_locale: str = "zh"
    available_locales: list[str] = Field(default_factory=lambda: ["zh", "en", "ja", "fr"])


class LoggingConfig(BaseModel):
    """日志系统配置模型。

    定义日志级别、日志文件路径和滚动日志参数。

    Attributes:
        level: 日志级别，"DEBUG"、"INFO"、"WARNING"、"ERROR"、"CRITICAL"。
        file: 日志文件路径，相对于项目根目录。
        max_size_mb: 单个日志文件最大大小（MB），超出自动滚动。
        backup_count: 保留的历史日志文件数量。
    """

    model_config = ConfigDict(extra="ignore")
    level: str = "INFO"
    file: str = "logs/app.log"
    max_size_mb: int = 50
    backup_count: int = 3


class CacheConfig(BaseModel):
    """文件缓存配置模型。

    定义上传文件缓存的过期时间和最大大小限制。

    Attributes:
        ttl: 缓存文件存活时间（秒），默认 86400 秒（1天）。
        max_size_mb: 缓存目录最大大小（MB），超出自动清理最旧文件。
    """

    model_config = ConfigDict(extra="ignore")
    ttl: int = 86400
    max_size_mb: int = 500


class InferenceConfig(BaseModel):
    """推理优化配置模型。

    定义推理时的各种性能优化参数，字段名与默认值对齐
    seedvr2_engine._get_inference_config() 实际读取逻辑。

    Attributes:
        blocks_to_swap: BlockSwap 换出到 CPU 的 Transformer 块数量，0 表示不启用。
        swap_io_components: 是否将输入/输出组件卸载到 CPU。
        offload_device: 卸载目标设备，"cpu" 或其他设备。
        attention_mode: 注意力计算模式，"sdpa"（PyTorch 内置缩放点积注意力）。
        inference_mode: 推理模式，"distilled"（蒸馏模式，速度更快）。
        resolution: 推理分辨率。
        max_resolution: 最大分辨率限制，0 表示不限制。
        batch_size: 批处理大小。
        uniform_batch_size: 是否强制所有批次使用相同大小。
        temporal_overlap: 时序片段重叠帧数。
        prepend_frames: 段首预填充帧数（用于保持时序连续性）。
        temporal_segment_size: 时序分段大小，0 表示不分段。
        temporal_segment_overlap: 时序分段重叠帧数。
        input_noise_scale: 输入噪声缩放因子，0 表示不加噪声。
        latent_noise_scale: 潜空间噪声缩放因子。
        restoration_guidance_scale: 修复引导强度。
        color_correction: 色彩校正方法，"lab" 使用 LAB 颜色空间匹配。
        seed: 随机种子，-1 表示随机。
        enable_debug: 是否启用调试输出。
        fp8_enabled: 是否启用 FP8 推理（兼容字段，引擎通过原始字典读取）。
        distilled_mode: 是否使用蒸馏模式（兼容字段）。
        vae_tile_size: VAE 分块编码/解码的瓦片大小。
        vae_overlap: VAE 瓦片重叠像素数，消除拼接边界。
    """

    model_config = ConfigDict(extra="ignore")
    blocks_to_swap: int = 0
    swap_io_components: bool = False
    offload_device: str = "cpu"
    attention_mode: str = "sdpa"
    inference_mode: str = "distilled"
    resolution: int = 2048
    max_resolution: int = 0
    batch_size: int = 1
    uniform_batch_size: bool = False
    temporal_overlap: int = 0
    prepend_frames: int = 0
    temporal_segment_size: int = 0
    temporal_segment_overlap: int = 8
    input_noise_scale: float = 0.0
    latent_noise_scale: float = 0.0
    restoration_guidance_scale: float = 1.0
    color_correction: str = "lab"
    seed: int = -1
    enable_debug: bool = False
    fp8_enabled: bool = False
    distilled_mode: bool = False
    vae_tile_size: int = 1024
    vae_overlap: int = 512
    cache_model: bool = False
    torch_compile: dict[str, Any] = Field(default_factory=dict)


class RuntimeSseConfig(BaseModel):
    """SSE（Server-Sent Events）进度推送运行时参数配置模型。

    替代源码中硬编码的 SSE 超时和心跳间隔。

    Attributes:
        max_duration_seconds: 单个 SSE 连接最大持续时间（秒），10-86400 范围。
        heartbeat_interval_seconds: SSE 心跳发送间隔（秒），5-600 范围，防止代理超时断开。
        poll_interval_seconds: 事件轮询间隔（秒），0.1-10.0 范围，平衡实时性和 CPU 占用。
    """

    model_config = ConfigDict(extra="ignore")
    max_duration_seconds: int = Field(300, ge=10, le=86400)
    heartbeat_interval_seconds: int = Field(30, ge=5, le=600)
    poll_interval_seconds: float = Field(0.5, ge=0.1, le=10.0)


class RuntimeBatchConfig(BaseModel):
    """批量任务运行时参数配置模型。

    定义批量处理时的重试策略，使用指数退避算法。

    Attributes:
        max_retries: 单个任务最大重试次数，0-10 范围。
        retry_base_delay_seconds: 重试基础延迟（秒），0.1-60.0 范围，实际延迟为 base * 2^attempt。
        retry_max_delay_seconds: 重试最大延迟（秒），1.0-600.0 范围，防止指数退避无限增长。
    """

    model_config = ConfigDict(extra="ignore")
    max_retries: int = Field(2, ge=0, le=10)
    retry_base_delay_seconds: float = Field(1.0, ge=0.1, le=60.0)
    retry_max_delay_seconds: float = Field(30.0, ge=1.0, le=600.0)


class RuntimeTaskConfig(BaseModel):
    """任务队列运行时参数配置模型。

    定义任务队列容量、超时和 ID 长度等参数。

    Attributes:
        id_length: 任务 ID 字符串长度，8-32 字符范围。
        max_timeout_seconds: 单个任务最大执行时间（秒），60-86400 范围，防止卡死任务阻塞队列。
        queue_maxsize: 任务队列最大容量，1-10000 范围，超出时新任务提交会拒绝。
        auto_recover: 启动时是否自动恢复未完成任务并继续推理，默认关闭。
    """

    model_config = ConfigDict(extra="ignore")
    id_length: int = Field(16, ge=8, le=32)
    max_timeout_seconds: int = Field(3600, ge=60, le=86400)
    queue_maxsize: int = Field(100, ge=1, le=10000)
    auto_recover: bool = Field(
        False,
        description="启动时是否自动恢复数据库中未完成的修复任务并重新推理",
    )


class RuntimeUploadConfig(BaseModel):
    """文件上传运行时参数配置模型。

    定义大文件分片上传参数。

    Attributes:
        large_file_threshold_mb: 大文件阈值（MB），1-1024 范围，超过此大小使用分片上传。
        chunk_size_bytes: 分片大小（字节），1KB-1MB 范围。
    """

    model_config = ConfigDict(extra="ignore")
    large_file_threshold_mb: int = Field(10, ge=1, le=1024)
    chunk_size_bytes: int = Field(8192, ge=1024, le=1024 * 1024)


class RuntimeSecurityConfig(BaseModel):
    """安全运行时参数配置模型。

    定义路径白名单和速率限制等安全策略。

    Attributes:
        allowed_base_dirs: 允许文件系统访问的基础目录白名单，path_guard 使用此列表防止目录遍历。
        rate_limit_per_minute: 每分钟请求速率限制，1-10000 范围，防止 API 滥用。
    """

    model_config = ConfigDict(extra="ignore")
    allowed_base_dirs: list[str] = Field(default_factory=lambda: ["outputs/", "data/uploads/"])
    rate_limit_per_minute: int = Field(30, ge=1, le=10000)


class RuntimeConfig(BaseModel):
    """运行时配置根模型。

    聚合所有运行时参数子配置，替代源码中散落的硬编码常量。
    通过 config.yaml 的 runtime 节统一配置。

    Attributes:
        sse: SSE 进度推送配置。
        batch: 批量任务重试配置。
        task: 任务队列配置。
        upload: 文件上传配置。
        security: 安全策略配置。
    """

    model_config = ConfigDict(extra="ignore")
    sse: RuntimeSseConfig = Field(default_factory=RuntimeSseConfig)
    batch: RuntimeBatchConfig = Field(default_factory=RuntimeBatchConfig)
    task: RuntimeTaskConfig = Field(default_factory=RuntimeTaskConfig)
    upload: RuntimeUploadConfig = Field(default_factory=RuntimeUploadConfig)
    security: RuntimeSecurityConfig = Field(default_factory=RuntimeSecurityConfig)


class ImageRestoreParams(BaseModel):
    """图像修复请求参数模型。

    定义图像修复 API 接受的完整参数集，包括 DiT 模型配置、VAE 配置、
    输出配置等，用于参数验证和默认值填充。

    Attributes:
        dit_model: DiT 模型版本标识，如 "3b_fp16"。
        dit_device: DiT 推理设备，如 "cuda:0"。
        blocks_to_swap: BlockSwap 换出块数，0-36 范围。
        swap_io_components: 是否卸载 I/O 组件到 CPU。
        dit_offload_device: DiT 卸载目标设备。
        dit_cache_model: 是否缓存 DiT 模型避免重复加载。
        attention_mode: 注意力计算模式。
        vae_model: VAE 模型版本标识，如 "ema_vae_fp16"。
        vae_device: VAE 推理设备。
        encode_tiled: VAE 编码是否启用分块处理（高分辨率必需）。
        encode_tile_size: VAE 编码瓦片大小，>=64。
        encode_tile_overlap: VAE 编码瓦片重叠像素，>=0。
        decode_tiled: VAE 解码是否启用分块处理。
        decode_tile_size: VAE 解码瓦片大小，>=64。
        decode_tile_overlap: VAE 解码瓦片重叠像素，>=0。
        tile_debug: 是否显示瓦片边界调试信息，"true"/"false"。
        vae_offload_device: VAE 卸载目标设备。
        vae_cache_model: 是否缓存 VAE 模型。
        seed: 随机种子。
        resolution: 输出分辨率（长边像素），>=1。
        max_resolution: 最大分辨率限制，0 表示不限制，>=0。
        batch_size: 批处理大小，>=1。
        uniform_batch_size: 是否强制统一批次大小。
        color_correction: 色彩校正方法。
        temporal_overlap: 时序重叠帧数（视频用），>=0。
        prepend_frames: 段首预填充帧数，>=0。
        input_noise_scale: 输入噪声缩放，>=0.0。
        latent_noise_scale: 潜空间噪声缩放，>=0.0。
        offload_device: 默认卸载设备。
        enable_debug: 是否启用调试输出。
    """

    model_config = ConfigDict(extra="ignore")

    dit_model: str = "3b_fp16"
    dit_device: str = "cuda:0"
    blocks_to_swap: int = Field(32, ge=0, le=36)
    swap_io_components: bool = True
    dit_offload_device: str = "cpu"
    dit_cache_model: bool = True
    attention_mode: str = "sdpa"

    vae_model: str = "ema_vae_fp16"
    vae_device: str = "cuda:0"
    encode_tiled: bool = True
    encode_tile_size: int = Field(1024, ge=64)
    encode_tile_overlap: int = Field(512, ge=0)
    decode_tiled: bool = True
    decode_tile_size: int = Field(1024, ge=64)
    decode_tile_overlap: int = Field(512, ge=0)
    tile_debug: str = "false"
    vae_offload_device: str = "cpu"
    vae_cache_model: bool = True

    seed: int = 1373201197
    resolution: int = Field(2160, ge=1)
    max_resolution: int = Field(0, ge=0)
    batch_size: int = Field(1, ge=1)
    uniform_batch_size: bool = False
    color_correction: str = "lab"
    temporal_overlap: int = Field(0, ge=0)
    prepend_frames: int = Field(0, ge=0)
    input_noise_scale: float = Field(0.0, ge=0.0)
    latent_noise_scale: float = Field(0.0, ge=0.0)
    offload_device: str = "cpu"
    enable_debug: bool = False


class UnifiedRestoreParams(ImageRestoreParams):
    """统一修复参数模型。

    继承自 ImageRestoreParams，增加 task_type 字段用于区分修复任务类型，
    作为 parse_unified_params 函数的返回值类型。

    Attributes:
        task_type: 任务类型，"auto" 自动检测、"video" 视频、"image" 图像。
    """

    task_type: str = "auto"


class VideoRestoreParams(BaseModel):
    """视频修复请求参数模型。

    分辨率语义与图片一致 (SideResize): 短边=resolution, 长边<=max_resolution，
    0/缺失时回退 config.yaml restore 节 (default_resolution_h/w)。

    Attributes:
        seed: 随机种子，用于可复现的视频修复结果。
        resolution: 短边目标像素，0 表示不指定。
        max_resolution: 长边像素上限，0 表示不限制。
        cache_model: 是否缓存 DiT/VAE 模型跨任务复用。
    """

    model_config = ConfigDict(extra="ignore")

    seed: int = 1373201197
    resolution: int = 0
    max_resolution: int = 0
    cache_model: bool = False


class AppConfig(BaseModel):
    """根应用配置模型。

    聚合所有配置子模型，对应 config.yaml 的根结构。
    所有配置项都有合理默认值，缺失字段自动填充默认。
    extra="ignore" 自动忽略 config.yaml 中未定义的字段，
    保证配置文件向前兼容。

    Attributes:
        server: HTTP 服务器配置。
        model: 模型加载配置。
        restore: 修复算法默认参数。
        gpu: GPU 后端配置。
        history: 历史记录数据库配置。
        i18n: 国际化配置。
        logging: 日志配置。
        cache: 文件缓存配置。
        inference: 推理优化配置。
        runtime: 运行时参数（替代硬编码常量）。
        user_preferences: 用户偏好字典，前端 WebUI 通过 SettingsPersistence 独立管理，
                         此处仅保留字段防止 model_dump() 序列化时丢失。
    """

    model_config = ConfigDict(extra="ignore")
    server: ServerConfig = Field(default_factory=ServerConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    restore: RestoreConfig = Field(default_factory=RestoreConfig)
    gpu: GpuConfig = Field(default_factory=GpuConfig)
    history: HistoryConfig = Field(default_factory=HistoryConfig)
    i18n: I18nConfig = Field(default_factory=I18nConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    inference: InferenceConfig = Field(default_factory=InferenceConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    user_preferences: dict[str, Any] = Field(default_factory=dict)


def load_validated_config(config_path: str) -> AppConfig:
    """加载 YAML 配置文件并通过 AppConfig Pydantic 模型验证。

    便捷函数，用于需要直接从文件路径加载并验证配置的场景。

    Args:
        config_path: YAML 配置文件的绝对或相对路径。

    Returns:
        AppConfig: 验证后的配置模型实例。

    Raises:
        FileNotFoundError: 配置文件不存在时抛出。
        pydantic.ValidationError: 配置内容不符合模型定义时抛出。
        yaml.YAMLError: YAML 解析错误时抛出。
    """
    import yaml

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return AppConfig(**raw)

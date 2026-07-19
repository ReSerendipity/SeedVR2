#!/usr/bin/env python3
"""SeedVR2 工具箱 - 配置数据模型

使用 Pydantic 进行配置验证，支持:
- ConfigDict(extra="ignore") 自动过滤未知 YAML 字段
- field_validator 范围校验
- 完整的应用配置模型
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    host: str = "127.0.0.1"
    port: int = 7870
    debug: bool = False
    # REFACTOR: 外置原本硬编码的 auto_open_browser，便于生产环境关闭
    auto_open_browser: bool = True
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:7870", "http://localhost:7870"])

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError(f"port 必须在 1-65535 范围内，当前值: {v}")
        return v


class ModelEntryConfig(BaseModel):
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
    model_config = ConfigDict(extra="ignore")
    default_size: str = "3b"
    default_precision: str = "fp16"
    pretrained_dir: str = "."
    auto_load: bool = True
    device: str = "auto"
    models: dict[str, ModelEntryConfig] = Field(default_factory=dict)


class RestoreConfig(BaseModel):
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
        if not (1.0 <= v <= 4.0):
            raise ValueError(f"default_scale_factor 必须在 1.0-4.0 范围内，当前值: {v}")
        return v


class GpuConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    backend: str = "auto"
    memory_strategy: str = "balanced"
    enable_fp16: bool = True


class HistoryConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    db_path: str = "data/history.db"
    max_records: int = 10000

    @field_validator("max_records")
    @classmethod
    def validate_max_records(cls, v: int) -> int:
        if not (1 <= v <= 100000):
            raise ValueError(f"max_records 必须在 1-100000 范围内，当前值: {v}")
        return v


class I18nConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    default_locale: str = "zh"
    available_locales: list[str] = Field(default_factory=lambda: ["zh", "en"])


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    level: str = "INFO"
    file: str = "logs/app.log"
    max_size_mb: int = 50
    backup_count: int = 3


class CacheConfig(BaseModel):
    """缓存配置"""
    model_config = ConfigDict(extra="ignore")
    ttl: int = 86400
    max_size_mb: int = 500


class InferenceConfig(BaseModel):
    """推理优化配置"""
    model_config = ConfigDict(extra="ignore")
    blocks_to_swap: int = 0
    swap_io_components: bool = False
    vae_tile_size: int = 1024
    vae_overlap: int = 512
    fp8_enabled: bool = False
    distilled_mode: bool = False


# ---------------------------------------------------------------------------
# REFACTOR: 运行时配置 - 替代源码中的硬编码（SSE 超时、重试间隔、队列上限等）
# ---------------------------------------------------------------------------

class RuntimeSseConfig(BaseModel):
    """SSE 进度推送运行时参数"""
    model_config = ConfigDict(extra="ignore")
    max_duration_seconds: int = Field(300, ge=10, le=86400)
    heartbeat_interval_seconds: int = Field(30, ge=5, le=600)
    poll_interval_seconds: float = Field(0.5, ge=0.1, le=10.0)


class RuntimeBatchConfig(BaseModel):
    """批量任务运行时参数"""
    model_config = ConfigDict(extra="ignore")
    max_retries: int = Field(2, ge=0, le=10)
    retry_base_delay_seconds: float = Field(1.0, ge=0.1, le=60.0)
    retry_max_delay_seconds: float = Field(30.0, ge=1.0, le=600.0)


class RuntimeTaskConfig(BaseModel):
    """任务队列运行时参数"""
    model_config = ConfigDict(extra="ignore")
    id_length: int = Field(16, ge=8, le=32)
    max_timeout_seconds: int = Field(3600, ge=60, le=86400)
    queue_maxsize: int = Field(100, ge=1, le=10000)


class RuntimeUploadConfig(BaseModel):
    """上传运行时参数"""
    model_config = ConfigDict(extra="ignore")
    large_file_threshold_mb: int = Field(10, ge=1, le=1024)
    chunk_size_bytes: int = Field(8192, ge=1024, le=1024 * 1024)


class RuntimeSecurityConfig(BaseModel):
    """安全运行时参数"""
    model_config = ConfigDict(extra="ignore")
    allowed_base_dirs: list[str] = Field(
        default_factory=lambda: ["outputs/", "data/uploads/"]
    )
    rate_limit_per_minute: int = Field(30, ge=1, le=10000)


class RuntimeConfig(BaseModel):
    """运行时配置根模型"""
    model_config = ConfigDict(extra="ignore")
    sse: RuntimeSseConfig = Field(default_factory=RuntimeSseConfig)
    batch: RuntimeBatchConfig = Field(default_factory=RuntimeBatchConfig)
    task: RuntimeTaskConfig = Field(default_factory=RuntimeTaskConfig)
    upload: RuntimeUploadConfig = Field(default_factory=RuntimeUploadConfig)
    security: RuntimeSecurityConfig = Field(default_factory=RuntimeSecurityConfig)


class ImageRestoreParams(BaseModel):
    """图像修复请求参数模型"""
    model_config = ConfigDict(extra="ignore")

    # DiT 配置
    dit_model: str = "3b_fp16"
    dit_device: str = "cuda:0"
    blocks_to_swap: int = Field(32, ge=0, le=36)
    swap_io_components: bool = True
    dit_offload_device: str = "cpu"
    dit_cache_model: bool = True
    attention_mode: str = "sdpa"

    # VAE 配置
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

    # 放大/输出配置
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
    """统一修复参数 - 用于 parse_unified_params 返回值

    在 ImageRestoreParams 基础上增加 task_type 字段。
    """
    task_type: str = "auto"


class VideoRestoreParams(BaseModel):
    """视频修复请求参数模型

    视频输出分辨率不再由前端表单控制，统一从 config.yaml 的
    restore.default_resolution_h / default_resolution_w 读取。
    此处仅保留 seed，以兼容历史记录反序列化。
    """
    model_config = ConfigDict(extra="ignore")

    seed: int = 1373201197


class AppConfig(BaseModel):
    """根应用配置模型"""
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
    # REFACTOR: 注册运行时配置，替代源码中散落的硬编码（SSE/重试/队列/上传/安全）
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)


def load_validated_config(config_path: str) -> AppConfig:
    """加载 YAML 配置文件并通过 AppConfig 验证

    Args:
        config_path: 配置文件路径

    Returns:
        验证后的 AppConfig 实例
    """
    import yaml

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return AppConfig(**raw)

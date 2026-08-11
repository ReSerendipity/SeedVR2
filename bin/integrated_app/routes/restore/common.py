#!/usr/bin/env python3
"""修复路由公共工具模块。

提取图像/视频修复路由的公共状态管理、常量定义与工具函数，
供 upload/batch/task/scan/recovery 等子路由模块复用。

主要功能：
- 支持的媒体文件扩展名常量定义
- 文件大小限制常量
- 统一修复参数解析（表单到 Pydantic 模型）
- 模型尺寸推断与媒体类型检测
- 任务状态管理（代理到 TaskStateStore，单真源）
- 批量任务项创建工具
- TaskStateStoreProxy 兼容类（保持原 dict-like 接口）

API 路由前缀：/api/restore（由子模块注册）
所属项目：SeedVR2 (SeedVR2 视频/图像修复工具)
"""

import logging
import os

from fastapi import Form

from bin.integrated_app.config_models import UnifiedRestoreParams
from bin.integrated_app.history_db import HistoryDB
from bin.integrated_app.model_registry import model_registry
from bin.integrated_app.services.task_state import task_state_store

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff", ".tif"}

VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv"}

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff"}

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".wmv"}

MAX_IMAGE_SIZE = 50 * 1024 * 1024
MAX_VIDEO_SIZE = 500 * 1024 * 1024

MAX_RETRIES = 2


def model_size_from_dit_model(dit_model: str) -> str:
    """根据 dit_model 参数确定使用的模型尺寸。

    解析模型名称字符串，提取模型尺寸标识。对于 sharp 变体保留 "size_sharp" 格式，
    其他模型只返回尺寸前缀。如参数为空则返回当前已加载模型尺寸或默认 "3b"。

    Args:
        dit_model: DiT 模型名称字符串，如 "3b_fp16"、"7b_sharp_fp16"。

    Returns:
        模型尺寸字符串，如 "3b"、"7b_sharp"。
    """
    if dit_model:
        parts = dit_model.split("_")
        if len(parts) >= 3 and parts[1] in ("sharp",):
            return f"{parts[0]}_{parts[1]}"
        return parts[0]
    return model_registry.current_model_size or "3b"


def detect_media_type(file_ext: str) -> str | None:
    """根据文件扩展名判断媒体类型。

    Args:
        file_ext: 文件扩展名（含点号，大小写不敏感），如 ".png"、".MP4"。

    Returns:
        "image" 表示图片，"video" 表示视频；不支持的扩展名返回 None。
    """
    ext = file_ext.lower()
    if ext in ALLOWED_IMAGE_EXTENSIONS:
        return "image"
    if ext in ALLOWED_VIDEO_EXTENSIONS:
        return "video"
    return None


def parse_unified_params(
    task_type: str = Form("auto"),
    dit_model: str = Form("3b_fp16"),
    dit_device: str = Form("cuda:0"),
    blocks_to_swap: int = Form(32),
    swap_io_components: bool = Form(True),
    dit_offload_device: str = Form("cpu"),
    dit_cache_model: bool = Form(True),
    attention_mode: str = Form("sdpa"),
    vae_model: str = Form("ema_vae_fp16"),
    vae_device: str = Form("cuda:0"),
    encode_tiled: bool = Form(True),
    encode_tile_size: int = Form(1024),
    encode_tile_overlap: int = Form(512),
    decode_tiled: bool = Form(True),
    decode_tile_size: int = Form(1024),
    decode_tile_overlap: int = Form(512),
    tile_debug: str = Form("false"),
    vae_offload_device: str = Form("cpu"),
    vae_cache_model: bool = Form(True),
    seed: int = Form(1373201197),
    resolution: int = Form(2160),
    max_resolution: int = Form(0),
    batch_size: int = Form(5),
    uniform_batch_size: bool = Form(True),
    color_correction: str = Form("lab"),
    temporal_overlap: int = Form(2),
    prepend_frames: int = Form(0),
    input_noise_scale: float = Form(0.0),
    latent_noise_scale: float = Form(0.0),
    offload_device: str = Form("cpu"),
    enable_debug: bool = Form(False),
    double_res: bool = Form(False),
) -> UnifiedRestoreParams:
    """解析统一修复表单参数，返回结构化 Pydantic 模型。

    作为 FastAPI Dependency 使用，从 multipart/form-data 中提取所有修复参数
    并构造 UnifiedRestoreParams 实例，供后续按任务类型（图像/视频）提取对应字段。

    Args:
        task_type: 任务类型，"auto"/"image"/"video"，默认 "auto"。
        dit_model: DiT 模型名称，默认 "3b_fp16"。
        dit_device: DiT 推理设备，默认 "cuda:0"。
        blocks_to_swap: 交换到 CPU 的 transformer 块数量，默认 32。
        swap_io_components: 是否交换 I/O 组件，默认 True。
        dit_offload_device: DiT 卸载设备，默认 "cpu"。
        dit_cache_model: 是否缓存 DiT 模型，默认 True。
        attention_mode: 注意力实现模式，默认 "sdpa"。
        vae_model: VAE 模型名称，默认 "ema_vae_fp16"。
        vae_device: VAE 推理设备，默认 "cuda:0"。
        encode_tiled: 是否使用分块 VAE 编码，默认 True。
        encode_tile_size: VAE 编码分块大小，默认 1024。
        encode_tile_overlap: VAE 编码分块重叠，默认 512。
        decode_tiled: 是否使用分块 VAE 解码，默认 True。
        decode_tile_size: VAE 解码分块大小，默认 1024。
        decode_tile_overlap: VAE 解码分块重叠，默认 512。
        tile_debug: 分块调试模式，默认 "false"。
        vae_offload_device: VAE 卸载设备，默认 "cpu"。
        vae_cache_model: 是否缓存 VAE 模型，默认 True。
        seed: 随机种子，默认 1373201197。
        resolution: 输出分辨率，默认 2160。
        max_resolution: 最大分辨率限制，0 表示不限制，默认 0。
        batch_size: 批处理大小（需满足 4n+1，非法值自动修正），默认 5。
        uniform_batch_size: 是否统一批处理大小，默认 True。
        color_correction: 颜色校正模式，默认 "lab"。
        temporal_overlap: 视频帧时序重叠数，默认 0。
        prepend_frames: 前置参考帧数，默认 0。
        input_noise_scale: 输入噪声缩放，默认 0.0。
        latent_noise_scale: 隐空间噪声缩放，默认 0.0。
        offload_device: 通用卸载设备，默认 "cpu"。
        enable_debug: 是否启用调试模式，默认 False。

    Returns:
        构造完成的 UnifiedRestoreParams 实例。
    """
    if batch_size < 1:
        batch_size = 1
    elif (batch_size - 1) % 4 != 0:
        batch_size = max(1, 4 * max(0, round((batch_size - 1) / 4)) + 1)
    return UnifiedRestoreParams(
        task_type=task_type,
        dit_model=dit_model,
        dit_device=dit_device,
        blocks_to_swap=blocks_to_swap,
        swap_io_components=swap_io_components,
        dit_offload_device=dit_offload_device,
        dit_cache_model=dit_cache_model,
        attention_mode=attention_mode,
        vae_model=vae_model,
        vae_device=vae_device,
        encode_tiled=encode_tiled,
        encode_tile_size=encode_tile_size,
        encode_tile_overlap=encode_tile_overlap,
        decode_tiled=decode_tiled,
        decode_tile_size=decode_tile_size,
        decode_tile_overlap=decode_tile_overlap,
        tile_debug=tile_debug,
        vae_offload_device=vae_offload_device,
        vae_cache_model=vae_cache_model,
        seed=seed,
        resolution=resolution,
        max_resolution=max_resolution,
        batch_size=batch_size,
        uniform_batch_size=uniform_batch_size,
        color_correction=color_correction,
        temporal_overlap=temporal_overlap,
        prepend_frames=prepend_frames,
        input_noise_scale=input_noise_scale,
        latent_noise_scale=latent_noise_scale,
        offload_device=offload_device,
        enable_debug=enable_debug,
        double_res=double_res,
    )


logger = logging.getLogger(__name__)


def enforce_double_resolution_if_enabled(
    raw_params: UnifiedRestoreParams,
    detected_type: str | None,
    input_path: str | None,
) -> None:
    """两倍模式后端强制校验 —— 就地修改 raw_params.resolution。

    规则（互斥保证）：
    1. 仅当 raw_params.double_res 为 True 且 detected_type == "image" 时生效；
    2. 使用 Pillow 重新读取 input_path 指向的真实图片宽高；
    3. 将 raw_params.resolution 覆写为 short_edge × 2，无论客户端表单传入什么；
    4. 若图片无法解析，记录 warning 并保持客户端传来的 resolution（fail-safe，不中断用户）；
    5. 视频文件 / folder_path 场景若传入了非图片类型 → 即使 double_res=True 也不覆写，仅记录 info 日志。

    Args:
        raw_params: parse_unified_params 返回的 UnifiedRestoreParams 实例，函数内就地修改其 resolution。
        detected_type: 媒体检测结果，"image"/"video"/None。
        input_path: 已保存到磁盘的上传文件路径（或本地文件夹模式首个媒体路径）。
    """
    if not raw_params.double_res:
        return

    if not input_path or not os.path.isfile(input_path):
        logger.warning("[double_res] 开关开启但输入路径无效，跳过强制覆写: %s", input_path)
        return

    if detected_type != "image":
        logger.info(
            "[double_res] 开关开启但当前文件非图片类型 (%s)，保留原分辨率 %d (path=%s)",
            detected_type,
            raw_params.resolution,
            input_path,
        )
        return

    try:
        # 延迟导入 — 只有开关打开时才触发，避免极少数环境缺失 Pillow
        from PIL import Image  # type: ignore
    except ImportError as e:
        logger.warning("[double_res] 开关开启但 Pillow 不可用，无法读取真实宽高: %s", e)
        return

    try:
        with Image.open(input_path) as im:  # noqa: S311 — 魔数校验已在上游 validate_upload_magic 完成
            width, height = im.size
    except Exception as e:  # noqa: BLE001 — 任何解码失败都 fail-safe
        logger.warning("[double_res] 图片解析失败，保留原分辨率: path=%s error=%s", input_path, e)
        return

    if width <= 0 or height <= 0:
        logger.warning(
            "[double_res] 图片宽高非法 (%dx%d)，保留原分辨率 %d (path=%s)",
            width,
            height,
            raw_params.resolution,
            input_path,
        )
        return

    short_edge = min(width, height)
    target_res = short_edge * 2
    original_res = raw_params.resolution
    raw_params.resolution = target_res

    # 同步覆写 4 个 VAE tile 参数，与前端自动填值规则保持一致：
    #   tile_size = short_edge × 100%    (向下取整到整数，且不小于 64)
    #   tile_overlap = short_edge × 50%  (且必须 ≤ tile_size // 2，避免 VAE 分块重叠越界)
    safe_tile_size = max(64, int(short_edge))
    safe_tile_overlap = max(0, min(int(short_edge * 0.5), safe_tile_size // 2))
    original_encode_tile_size = raw_params.encode_tile_size
    original_encode_tile_overlap = raw_params.encode_tile_overlap
    original_decode_tile_size = raw_params.decode_tile_size
    original_decode_tile_overlap = raw_params.decode_tile_overlap
    raw_params.encode_tile_size = safe_tile_size
    raw_params.encode_tile_overlap = safe_tile_overlap
    raw_params.decode_tile_size = safe_tile_size
    raw_params.decode_tile_overlap = safe_tile_overlap

    logger.info(
        "[double_res] 已按「短边×2」强制设置分辨率 & tile 参数: "
        "图片尺寸 %dx%d -> 短边 %d -> 分辨率 %d (原 %d 丢弃), "
        "encode_tile %d/%d (原 %d/%d 丢弃), "
        "decode_tile %d/%d (原 %d/%d 丢弃)",
        width,
        height,
        short_edge,
        target_res,
        original_res,
        safe_tile_size,
        safe_tile_overlap,
        original_encode_tile_size,
        original_encode_tile_overlap,
        safe_tile_size,
        safe_tile_overlap,
        original_decode_tile_size,
        original_decode_tile_overlap,
    )


async def create_task_state(task_id: str, record_id: int, history_db: HistoryDB, task_type: str = "single") -> dict:
    """在数据库与内存缓存中创建任务初始状态。

    Args:
        task_id: 任务唯一标识。
        record_id: 历史记录数据库 ID。
        history_db: 历史记录数据库实例。
        task_type: 任务类型，"single"/"batch"，默认 "single"。

    Returns:
        创建的初始任务状态字典。
    """
    return await task_state_store.create(task_id, record_id, history_db, task_type=task_type)


async def get_task_state(task_id: str, history_db: HistoryDB) -> dict | None:
    """获取任务状态；优先读内存缓存，缓存未命中则回源数据库。

    Args:
        task_id: 任务唯一标识。
        history_db: 历史记录数据库实例。

    Returns:
        任务状态字典；任务不存在返回 None。
    """
    return await task_state_store.get(task_id, history_db)


async def update_task_state(task_id: str, history_db: HistoryDB, **kwargs) -> dict:
    """更新数据库任务状态并同步到内存缓存。

    Args:
        task_id: 任务唯一标识。
        history_db: 历史记录数据库实例。
        **kwargs: 要更新的状态字段（如 status, progress, error_message 等）。

    Returns:
        更新后的任务状态字典。
    """
    return await task_state_store.update(task_id, history_db, **kwargs)


def get_task_cache() -> "TaskStateStoreProxy":
    """返回任务状态存储代理（供批量任务/重试等操作使用）。

    返回的 TaskStateStoreProxy 实例包装了全局 task_state_store，
    提供与原 OrderedDict 类似的 dict-like 接口（__getitem__/get/__setitem__/__contains__/update），
    确保线程安全与单一数据源。

    注意：__getitem__/get 返回的是浅拷贝，顶层字段直接修改不会生效，
    需要修改时必须通过 update() 方法写回。嵌套 list/dict（如 results）仍为引用共享，
    修改其中元素会直接影响缓存。

    Returns:
        TaskStateStoreProxy 实例。
    """
    return TaskStateStoreProxy(task_state_store)


def get_cached_or_create(task_id: str, template: dict | None = None) -> dict:
    """从缓存获取任务状态，不存在则用 template 创建并写入缓存。

    Args:
        task_id: 任务唯一标识。
        template: 用于初始化的模板字典，可选；默认为空字典。

    Returns:
        任务状态字典（浅拷贝）。
    """
    return task_state_store.get_cached_or_create(task_id, template=template)


class TaskStateStoreProxy:
    """任务状态存储代理类 - 兼容原 OrderedDict 接口。

    包装 task_state_store，提供 dict-like 接口，使原有代码中
    `common.get_task_cache()[task_id]` 和 `common.get_task_cache().get(task_id)`
    等调用无需大规模修改即可迁移到新的 TaskStateStore。

    重要差异：
    - __getitem__/get 返回的是浅拷贝而非引用，调用方直接修改返回值不会影响缓存
    - 需要修改缓存内容时必须使用 update() 或重新 __setitem__

    Attributes:
        _store: 被包装的 TaskStateStore 实例。
    """

    def __init__(self, store):
        """初始化 TaskStateStoreProxy。

        Args:
            store: TaskStateStore 实例。
        """
        self._store = store

    def __getitem__(self, task_id: str) -> dict:
        """获取任务状态（浅拷贝）。不存在则抛出 KeyError。

        Args:
            task_id: 任务唯一标识。

        Returns:
            任务状态字典（浅拷贝）。

        Raises:
            KeyError: 任务不存在时抛出。
        """
        cached = self._store.get_cached(task_id)
        if cached is None:
            raise KeyError(task_id)
        return cached

    def __setitem__(self, task_id: str, value: dict) -> None:
        """设置任务状态（覆盖式写入缓存）。

        通过 update_cached 一次性写入所有字段，避免部分写入导致状态不一致。

        Args:
            task_id: 任务唯一标识。
            value: 完整任务状态字典。
        """
        self._store.update_cached(task_id, **value)

    def __contains__(self, task_id: str) -> bool:
        """检查任务是否存在于缓存中。

        Args:
            task_id: 任务唯一标识。

        Returns:
            存在返回 True，否则返回 False。
        """
        return self._store.get_cached(task_id) is not None

    def get(self, task_id: str, default: dict | None = None) -> dict | None:
        """获取任务状态（浅拷贝）。不存在则返回 default。

        Args:
            task_id: 任务唯一标识。
            default: 任务不存在时返回的默认值，默认 None。

        Returns:
            任务状态字典（浅拷贝）；不存在返回 default。
        """
        cached = self._store.get_cached(task_id)
        return cached if cached is not None else default

    def update(self, task_id: str, **kwargs) -> dict | None:
        """更新缓存中的任务字段（代理到 task_state_store.update_cached）。

        Args:
            task_id: 任务唯一标识。
            **kwargs: 要更新的字段键值对。

        Returns:
            更新后的完整任务状态字典；任务不存在返回 None。
        """
        return self._store.update_cached(task_id, **kwargs)


def create_batch_item(path: str) -> dict:
    """创建批量任务中的单文件项结构。

    Args:
        path: 文件的绝对路径。

    Returns:
        批量任务项字典，包含 path/name/status/output_path/error/processing_time/retry_count 字段。
    """
    return {
        "path": path,
        "name": os.path.basename(path),
        "status": "pending",
        "output_path": None,
        "error": None,
        "processing_time": None,
        "retry_count": 0,
    }

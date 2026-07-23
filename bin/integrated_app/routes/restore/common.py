#!/usr/bin/env python3
"""Klar - 修复路由公共模块

提取图像/视频修复路由的公共状态管理、常量与工具函数，
供 upload/batch/task/scan/recovery 子路由复用。

REFACTOR [B2-1]: 收敛任务状态真源
- 原实现保留模块级全局 OrderedDict (_task_cache) 与 services.task_state.task_state_store
  并存，导致双真源漂移：路由层直接修改 _task_cache 引用，TaskStateStore 不感知；
  批量任务的临时字段（current_index/results 等）绕过 DB 写入，但 DB 状态仍由
  TaskStateStore 管理，两者状态可能不一致
- 本次将 create_task_state / get_task_state / update_task_state / get_task_cache
  全部代理到 task_state_store，删除模块级 _task_cache
- 批量任务的临时字段通过 task_state_store.update_cached 写入缓存（不持久化），
  确保所有任务状态统一由 TaskStateStore 管理

REFACTOR [B1-1]: 从 unified.py 移入 parse_unified_params / model_size_from_dit_model /
detect_media_type 等共享函数，使 unified.py 仅作为路由聚合入口 (B1/SRP)。
"""
import os

from fastapi import Form

from bin.integrated_app.config_models import UnifiedRestoreParams
from bin.integrated_app.history_db import HistoryDB
from bin.integrated_app.model_registry import model_registry
from bin.integrated_app.services.task_state import task_state_store

# 支持的扩展名
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff", ".tif"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv"}

# 允许上传的扩展名（不含 .tif，仅用于扫描）
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".wmv"}

# 文件大小限制
MAX_IMAGE_SIZE = 50 * 1024 * 1024       # 50MB
MAX_VIDEO_SIZE = 500 * 1024 * 1024      # 500MB

# 最大重试次数
MAX_RETRIES = 2


# ---------------------------------------------------------------------------
# REFACTOR: 从 unified.py 移入的共享工具函数 (B1/SRP)
# ---------------------------------------------------------------------------

def model_size_from_dit_model(dit_model: str) -> str:
    """根据 dit_model 参数确定使用的模型尺寸"""
    if dit_model:
        parts = dit_model.split("_")
        if len(parts) >= 3 and parts[1] in ("sharp",):
            return f"{parts[0]}_{parts[1]}"
        return parts[0]
    return model_registry.current_model_size or "3b"


def detect_media_type(file_ext: str) -> str | None:
    """根据扩展名判断媒体类型"""
    ext = file_ext.lower()
    if ext in ALLOWED_IMAGE_EXTENSIONS:
        return "image"
    if ext in ALLOWED_VIDEO_EXTENSIONS:
        return "video"
    return None


def parse_unified_params(
    # 通用
    task_type: str = Form("auto"),
    # DiT / 图像参数
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
    batch_size: int = Form(1),
    uniform_batch_size: bool = Form(False),
    color_correction: str = Form("lab"),
    temporal_overlap: int = Form(0),
    prepend_frames: int = Form(0),
    input_noise_scale: float = Form(0.0),
    latent_noise_scale: float = Form(0.0),
    offload_device: str = Form("cpu"),
    enable_debug: bool = Form(False),
) -> UnifiedRestoreParams:
    """解析统一修复表单参数，返回结构化模型供后续按类型构建"""
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
    )


# ---------------------------------------------------------------------------
# 任务状态管理（统一代理到 services.task_state.task_state_store）
# REFACTOR [B2-1]: 删除模块级 _task_cache OrderedDict，全部走 task_state_store
# ---------------------------------------------------------------------------

async def create_task_state(task_id: str, record_id: int, history_db: HistoryDB, task_type: str = "single") -> dict:
    """在数据库与内存缓存中创建任务初始状态

    REFACTOR [B2-1]: 代理到 task_state_store.create，消除模块级全局缓存。
    """
    return await task_state_store.create(task_id, record_id, history_db, task_type=task_type)


async def get_task_state(task_id: str, history_db: HistoryDB) -> dict | None:
    """获取任务状态；优先读缓存，回源数据库

    REFACTOR [B2-1]: 代理到 task_state_store.get，消除模块级全局缓存。
    """
    return await task_state_store.get(task_id, history_db)


async def update_task_state(task_id: str, history_db: HistoryDB, **kwargs) -> dict:
    """更新数据库任务状态并同步缓存

    REFACTOR [B2-1]: 代理到 task_state_store.update，消除模块级全局缓存。
    """
    return await task_state_store.update(task_id, history_db, **kwargs)


def get_task_cache() -> "TaskStateStoreProxy":
    """返回任务状态存储代理（供批量任务/重试使用）

    REFACTOR [B2-1]:
    - 原实现返回模块级 OrderedDict，调用方直接 _task_cache[task_id] = {...} 或
      _task_cache.get(task_id) 操作，绕过 task_state_store 的锁保护
    - 改为返回 TaskStateStoreProxy，所有操作代理到 task_state_store，
      确保线程安全与单真源
    - 兼容原 _task_cache 的 dict-like 接口（__getitem__ / get / __setitem__ / __contains__），
      降低调用方迁移成本

    Returns:
        TaskStateStoreProxy 实例（包装 task_state_store）
    """
    return TaskStateStoreProxy(task_state_store)


def get_cached_or_create(task_id: str, template: dict | None = None) -> dict:
    """从缓存获取任务状态，不存在则用 template 创建并写入缓存。

    REFACTOR [B2-1]: 代理到 task_state_store.get_cached_or_create，
    替代 batch.py 中 `cached = get_task_cache().get(id); if cached is None: ...; get_task_cache()[id] = cached` 模式。

    注意: 返回的是浅拷贝，顶层字段修改不会影响缓存，需通过 get_task_cache().update() 写回。
    但嵌套 list/dict（如 results）仍为引用共享，修改其中的 dict 元素会直接影响缓存。
    """
    return task_state_store.get_cached_or_create(task_id, template=template)


class TaskStateStoreProxy:
    """任务状态存储代理 - 兼容原 OrderedDict 接口

    REFACTOR [B2-1]: 包装 task_state_store，提供 dict-like 接口，
    使 batch.py / upload.py 中 `common.get_task_cache()[task_id]` 和
    `common.get_task_cache().get(task_id)` 的调用无需大改即可迁移到 task_state_store。

    重要差异:
    - __getitem__ / get 返回的是拷贝而非引用，调用方修改不会影响缓存
    - 需要修改缓存内容时必须用 update_cached 或重新 __setitem__
    """

    def __init__(self, store):
        self._store = store

    def __getitem__(self, task_id: str) -> dict:
        """获取任务状态（拷贝）。不存在则抛出 KeyError。"""
        cached = self._store.get_cached(task_id)
        if cached is None:
            raise KeyError(task_id)
        return cached

    def __setitem__(self, task_id: str, value: dict) -> None:
        """设置任务状态（覆盖式写入缓存）。

        ROBUSTNESS: 通过 update_cached 一次性写入所有字段，避免部分写入导致状态不一致。
        """
        self._store.update_cached(task_id, **value)

    def __contains__(self, task_id: str) -> bool:
        return self._store.get_cached(task_id) is not None

    def get(self, task_id: str, default: dict | None = None) -> dict | None:
        """获取任务状态（拷贝）。不存在则返回 default。"""
        cached = self._store.get_cached(task_id)
        return cached if cached is not None else default

    def update(self, task_id: str, **kwargs) -> dict | None:
        """更新缓存中的任务字段（代理到 task_state_store.update_cached）"""
        return self._store.update_cached(task_id, **kwargs)


def create_batch_item(path: str) -> dict:
    """创建批量任务中的单文件项结构"""
    return {
        "path": path,
        "name": os.path.basename(path),
        "status": "pending",
        "output_path": None,
        "error": None,
        "processing_time": None,
        "retry_count": 0,
    }

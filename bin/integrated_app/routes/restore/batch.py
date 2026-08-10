#!/usr/bin/env python3
"""批量修复路由模块。

提供文件夹批量媒体修复功能，支持自动指数退避重试失败任务。
批量任务在后台单 worker 队列中顺序执行，避免并发推理导致 GPU OOM。

API 端点：
- POST /api/restore/batch: 创建批量修复任务
- GET /api/restore/batch/{batch_id}/progress: 查询批量任务进度
- POST /api/restore/batch/{batch_id}/retry: 重试批量任务中失败的文件

所属项目：SeedVR2 (SeedVR2 视频/图像修复工具)
"""

import asyncio
import contextlib
import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException

from bin.integrated_app.checkpoint import TaskCheckpoint, _file_fingerprint
from bin.integrated_app.config_models import (
    ImageRestoreParams,
    UnifiedRestoreParams,
    VideoRestoreParams,
)
from bin.integrated_app.dependencies import (
    get_config,
    get_history_db,
    get_task_queue,
)
from bin.integrated_app.engines.seedvr2_engine import ImageInferenceConfig
from bin.integrated_app.gpu_backend import gpu_manager
from bin.integrated_app.history_db import HistoryDB, HistoryRecord
from bin.integrated_app.model_registry import model_registry
from bin.integrated_app.routes.restore import common
from bin.integrated_app.task_queue import TaskQueue
from bin.integrated_app.utils.response import respond_success
from bin.integrated_app.utils.retry import exponential_backoff_with_jitter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/restore", tags=["修复"])


@router.post("/batch")
async def batch_restore_from_folder(
    folder_path: str = Form(...),
    task_type: str = Form("auto"),
    raw_params: UnifiedRestoreParams = Depends(common.parse_unified_params),
    config: dict = Depends(get_config),
    history_db: HistoryDB = Depends(get_history_db),
    task_queue: TaskQueue = Depends(get_task_queue),
):
    """批量处理文件夹中的媒体文件（后台异步，逐个顺序执行）。

    API 端点：POST /api/restore/batch

    请求参数（multipart/form-data）：
    - folder_path (required): 要处理的文件夹绝对路径
    - task_type (optional): "auto"/"image"/"video"，默认 "auto" 自动检测
    - 其他修复参数（dit_model, seed 等，详见 common.parse_unified_params）

    返回格式（JSON，统一包装 {success, data, error}）：
    {
        "success": true,
        "data": {
            "batch_id": str,      // 批量任务 ID
            "total": int,         // 待处理文件总数
            "media_type": "image"|"video",
            "status": "processing"
        }
    }

    错误响应：
    - 400: 参数错误（文件夹不存在、无可处理文件等）
    - 503: GPU 不可用或模型未加载

    Args:
        folder_path: 目标文件夹路径。
        task_type: 任务类型过滤。
        raw_params: 解析后的修复参数。
        config: 应用配置。
        history_db: 历史数据库实例。
        task_queue: 任务队列实例。

    Returns:
        包含 batch_id 的 JSON 响应。

    Raises:
        HTTPException: 校验失败或服务不可用时抛出。
    """
    if not gpu_manager.is_gpu_available:
        raise HTTPException(
            status_code=503,
            detail="SeedVR2 仅支持 NVIDIA GPU 推理，当前未检测到 NVIDIA GPU。请安装 NVIDIA GPU 并配置 CUDA 驱动。",
        )

    if not model_registry.model_loaded:
        raise HTTPException(status_code=503, detail="模型未加载，请先加载模型")

    folder = Path(folder_path.strip())
    if not await asyncio.to_thread(folder.exists) or not await asyncio.to_thread(folder.is_dir):
        raise HTTPException(status_code=400, detail=f"文件夹不存在: {folder_path}")

    media_files = []
    for root, _dirs, files in await asyncio.to_thread(lambda: list(os.walk(folder))):
        for fname in sorted(files):
            ext = os.path.splitext(fname)[1].lower()
            detected = common.detect_media_type(ext)
            if detected:
                media_files.append((os.path.join(root, fname), detected))

    if task_type != "auto":
        media_files = [(p, t) for p, t in media_files if t == task_type]

    if not media_files:
        raise HTTPException(status_code=400, detail=f"文件夹中未找到可处理文件: {folder_path}")

    actual_type = task_type if task_type != "auto" else media_files[0][1]

    dit_model = raw_params.dit_model
    use_model_size = common.model_size_from_dit_model(dit_model)
    params: ImageRestoreParams | VideoRestoreParams
    if actual_type == "image":
        image_fields = {k: v for k, v in raw_params.model_dump().items() if k in ImageRestoreParams.model_fields}
        params = ImageRestoreParams(**image_fields)
        task_config = params.model_dump()
    else:
        params = VideoRestoreParams(
            seed=raw_params.seed,
            resolution=raw_params.resolution,
            max_resolution=raw_params.max_resolution,
            cache_model=raw_params.dit_cache_model,
        )
        task_config = {
            "resolution": params.resolution,
            "max_resolution": params.max_resolution,
            "cache_model": params.cache_model,
            "seed": params.seed,
        }

    batch_id = uuid.uuid4().hex[: config.get("runtime", {}).get("task", {}).get("id_length", 16)]

    batch_results = [common.create_batch_item(path) for path, _ in media_files]
    await common.create_task_state(batch_id, 0, history_db, task_type="batch")
    common.get_task_cache().update(
        batch_id,
        **{
            "type": "batch",
            "media_type": actual_type,
            "total": len(media_files),
            "completed": 0,
            "failed": 0,
            "current_index": -1,
            "current_file": "",
            "results": batch_results,
            "config": task_config,
            "use_model_size": use_model_size,
        },
    )
    await common.update_task_state(batch_id, history_db, status="processing")

    engine = model_registry.get_engine()
    on_cancel = engine.request_cancel if engine else None
    paths_only = [p for p, _ in media_files]
    await task_queue.submit(
        batch_id,
        lambda: _process_batch_background(
            batch_id, paths_only, actual_type, task_config, use_model_size, history_db, task_queue, config
        ),
        on_cancel=on_cancel,
    )

    return respond_success(
        {
            "batch_id": batch_id,
            "total": len(media_files),
            "media_type": actual_type,
            "status": "processing",
        }
    )


async def _process_batch_background(
    batch_id: str,
    media_files: list,
    media_type: str,
    config: dict,
    use_model_size: str,
    history_db: HistoryDB,
    task_queue: TaskQueue,
    app_config: dict,
    results_to_update: list | None = None,
):
    """后台逐个处理批量任务（含自动重试 + 断点续跑）（内部函数）。

    顺序处理媒体文件列表，每个文件失败后使用指数退避+抖动自动重试，
    重试次数和间隔从配置读取。处理过程中实时更新缓存和数据库状态。
    支持断点续跑：每个文件处理完成后保存 checkpoint，崩溃重启后可恢复。

    Args:
        batch_id: 批量任务 ID。
        media_files: 待处理文件路径列表。
        media_type: 媒体类型 "image"/"video"。
        config: 推理参数配置。
        use_model_size: 模型尺寸标识。
        history_db: 历史数据库实例。
        task_queue: 任务队列实例。
        app_config: 应用全局配置。
        results_to_update: 重试时传入的已有结果项列表（复用原结构），可选。
    """
    task_state = await common.get_task_state(batch_id, history_db)
    if task_state is None:
        return

    # 初始化断点续跑管理器
    task_cfg = app_config.get("runtime", {}).get("task", {})
    checkpoint_dir = task_cfg.get("checkpoint_dir", "data/checkpoints")
    checkpoint_every = task_cfg.get("checkpoint_every", 1)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    checkpoint_mgr = TaskCheckpoint(os.path.join(project_root, checkpoint_dir))

    # 加载已有 checkpoint，跳过已完成的文件
    completed_fingerprints = checkpoint_mgr.get_completed_fingerprints(batch_id)
    completed_files_list: list[dict] = []
    if completed_fingerprints:
        # 从 checkpoint 恢复已完成文件列表
        ckpt_data = checkpoint_mgr.load_checkpoint(batch_id)
        if ckpt_data:
            completed_files_list = ckpt_data.get("completed_files", [])
        logger.info(f"批量任务 {batch_id} 从断点恢复: 已完成 {len(completed_fingerprints)} 个文件")

    cached = common.get_cached_or_create(
        batch_id,
        template={
            "task_id": batch_id,
            "type": "batch",
            "media_type": media_type,
            "total": len(media_files),
            "completed": 0,
            "failed": 0,
            "current_index": -1,
            "current_file": "",
            "results": [],
            "config": config,
            "use_model_size": use_model_size,
        },
    )

    results = cached["results"]
    completed = 0
    failed = 0
    engine = model_registry.get_engine()

    if engine is None:
        await common.update_task_state(
            batch_id,
            history_db,
            status="failed",
            error_message="引擎实例不可用",
        )
        return

    records_to_insert: list[HistoryRecord] = []
    output_subdir = "image" if media_type == "image" else "video"

    batch_cfg = app_config.get("runtime", {}).get("batch", {})
    max_retries = batch_cfg.get("max_retries", 2)
    retry_base = batch_cfg.get("retry_base_delay_seconds", 1.0)
    retry_max = batch_cfg.get("retry_max_delay_seconds", 30.0)

    for i, media_path in enumerate(media_files):
        # 断点续跑：跳过已完成的文件
        if media_path in completed_fingerprints:
            fp = completed_fingerprints[media_path]
            # 验证文件指纹（大小 + 修改时间）是否一致
            current_fp = _file_fingerprint(media_path)
            if fp.get("size", 0) == current_fp.get("size", 0) and fp.get("mtime", 0) == current_fp.get("mtime", 0):
                logger.debug(f"断点续跑: 跳过已完成文件 {media_path}")
                completed += 1
                common.get_task_cache().update(batch_id, completed=completed)
                # 为跳过的文件创建结果项
                task_item = common.create_batch_item(media_path)
                task_item["status"] = "completed"
                task_item["output_path"] = fp.get("output_path", "")
                results.append(task_item)
                records_to_insert.append(
                    HistoryRecord(
                        task_type=media_type,
                        input_file=media_path,
                        model_size=use_model_size,
                        status="completed",
                        output_file=fp.get("output_path", ""),
                    )
                )
                continue
            else:
                logger.warning(f"断点续跑: 文件指纹不匹配，重新处理 {media_path}")

        if task_queue.is_cancelled(batch_id):
            for remaining in media_files[i:]:
                records_to_insert.append(
                    HistoryRecord(
                        task_type=media_type,
                        input_file=remaining,
                        model_size=use_model_size,
                        status="cancelled",
                        error_message="批量任务被取消",
                    )
                )
            break

        if results_to_update is not None and i < len(results_to_update):
            task_item = results_to_update[i]
            task_item["status"] = "processing"
            task_item["retry_count"] = 0
        else:
            task_item = common.create_batch_item(media_path)
            task_item["status"] = "processing"
            results.append(task_item)
        current_filename = os.path.basename(media_path)
        common.get_task_cache().update(batch_id, current_index=i, current_file=current_filename)

        last_error = None

        for attempt in range(max_retries + 1):
            task_item["retry_count"] = attempt
            try:
                output_dir = os.path.join(os.getcwd(), "outputs", output_subdir)
                await asyncio.to_thread(os.makedirs, output_dir, exist_ok=True)

                if media_type == "image":
                    image_config = ImageInferenceConfig(
                        **{k: v for k, v in config.items() if k in ImageInferenceConfig.__dataclass_fields__}
                    )
                    result = await engine.infer_image(
                        image_path=media_path,
                        output_dir=output_dir,
                        config=image_config,
                    )
                else:
                    # 批量任务的进度回调（同步函数 - 推理在工作线程同步执行）
                    # 注意：使用默认参数捕获 i，避免闭包延迟绑定问题
                    def progress_callback(current_frame: int, total_frames: int, progress: float, _i=i, **kwargs):
                        common.get_task_cache().update(
                            batch_id,
                            current_index=_i,
                            current_progress=round(progress, 1),
                        )

                    engine.set_progress_callback(progress_callback)
                    result = await engine.infer_video(
                        video_path=media_path,
                        output_dir=output_dir,
                        resolution=config["resolution"],
                        max_resolution=config["max_resolution"],
                        cache_model=config["cache_model"],
                        seed=config["seed"],
                    )

                if result.success:
                    task_item["status"] = "completed"
                    task_item["output_path"] = result.output_path
                    task_item["processing_time"] = result.processing_time
                    task_item["error"] = None
                    completed += 1
                    common.get_task_cache().update(batch_id, completed=completed)

                    # 断点续跑：保存 checkpoint
                    completed_files_list.append({**_file_fingerprint(media_path), "output_path": result.output_path})
                    remaining_files = media_files[i + 1 :]
                    if checkpoint_mgr.should_checkpoint(completed, checkpoint_every):
                        checkpoint_mgr.save_checkpoint(
                            batch_id,
                            total=len(media_files),
                            completed_files=completed_files_list,
                            remaining=remaining_files,
                            config=config,
                            media_type=media_type,
                            use_model_size=use_model_size,
                        )
                    break
                else:
                    last_error = result.error or "未知错误"
                    if attempt < max_retries:
                        task_item["status"] = "retrying"
                        logger.warning(
                            f"批量处理 {media_type} {i+1}/{len(media_files)} 第{attempt+1}次失败，重试中: {media_path}, {last_error}"
                        )
                        await exponential_backoff_with_jitter(attempt, base=retry_base, max_delay=retry_max)
                    else:
                        task_item["status"] = "failed"
                        task_item["error"] = last_error
                        failed += 1
                        common.get_task_cache().update(batch_id, failed=failed)

            except asyncio.CancelledError:
                task_item["status"] = "cancelled"
                task_item["error"] = "用户取消"
                raise
            except Exception as e:
                last_error = str(e)
                if attempt < max_retries:
                    task_item["status"] = "retrying"
                    logger.warning(
                        f"批量处理 {media_type} {i+1}/{len(media_files)} 第{attempt+1}次异常，重试中: {media_path}, {e}"
                    )
                    await exponential_backoff_with_jitter(attempt, base=retry_base, max_delay=retry_max)
                else:
                    task_item["status"] = "failed"
                    task_item["error"] = last_error
                    failed += 1
                    common.get_task_cache().update(batch_id, failed=failed)
                    logger.error(f"批量处理 {media_type} {i+1}/{len(media_files)} 最终失败: {media_path}, {e}")

        records_to_insert.append(
            HistoryRecord(
                task_type=media_type,
                input_file=media_path,
                model_size=use_model_size,
                status=task_item["status"],
                output_file=task_item.get("output_path"),
                processing_time=task_item.get("processing_time"),
                error_message=task_item.get("error"),
            )
        )

        progress = round(((i + 1) / len(media_files)) * 100, 1)
        await common.update_task_state(batch_id, history_db, progress=progress)

    try:
        await history_db.add_records(records_to_insert)
    except Exception:
        for record in records_to_insert:
            with contextlib.suppress(Exception):
                await history_db.add_record(record)

    final_status = "cancelled" if task_queue.is_cancelled(batch_id) else "completed"
    final_cached = common.get_task_cache().get(batch_id, {})
    assert final_cached is not None
    await common.update_task_state(
        batch_id,
        history_db,
        status=final_status,
        progress=100.0 if final_status == "completed" else final_cached.get("progress", 0),
    )

    # 批量任务完成后清理 checkpoint
    if final_status == "completed":
        checkpoint_mgr.remove_checkpoint(batch_id)
        logger.info(f"批量任务 {batch_id} checkpoint 已清理")

    logger.info(f"批量任务 {batch_id} 完成: {completed} 成功, {failed} 失败")


@router.get("/batch/{batch_id}/progress")
async def get_batch_progress(batch_id: str, history_db: HistoryDB = Depends(get_history_db)):
    """获取批量处理任务进度。

    API 端点：GET /api/restore/batch/{batch_id}/progress

    路径参数：
    - batch_id: 批量任务 ID

    返回格式（JSON）：
    {
        "success": true,
        "data": {
            "batch_id": str,
            "status": "pending"|"processing"|"completed"|"failed"|"cancelled",
            "progress": float,     // 0-100
            "total": int,
            "completed": int,
            "failed": int,
            "current_index": int,
            "results": [ ... ],    // 每个文件的详细状态
            "media_type": "image"|"video"
        }
    }

    错误响应：
    - 404: 批量任务不存在

    Args:
        batch_id: 批量任务 ID。
        history_db: 历史数据库实例。

    Returns:
        批量任务进度详情。

    Raises:
        HTTPException: 任务不存在时抛出。
    """
    task = await common.get_task_state(batch_id, history_db)
    if not task:
        raise HTTPException(status_code=404, detail="批量任务不存在")

    cached = common.get_task_cache().get(batch_id, {})
    assert cached is not None
    return respond_success(
        {
            "batch_id": batch_id,
            "status": task.get("status", "unknown"),
            "progress": task.get("progress", 0),
            "total": cached.get("total", 0),
            "completed": cached.get("completed", 0),
            "failed": cached.get("failed", 0),
            "current_index": cached.get("current_index", -1),
            "current_file": cached.get("current_file", ""),
            "results": cached.get("results", []),
            "media_type": cached.get("media_type", "image"),
        }
    )


@router.post("/batch/{batch_id}/retry")
async def retry_failed_batch(
    batch_id: str,
    history_db: HistoryDB = Depends(get_history_db),
    task_queue: TaskQueue = Depends(get_task_queue),
    config: dict = Depends(get_config),
):
    """重试批量任务中失败的文件。

    API 端点：POST /api/restore/batch/{batch_id}/retry

    路径参数：
    - batch_id: 批量任务 ID

    返回格式（JSON）：
    {
        "success": true,
        "data": {
            "message": str,
            "retry_count": int  // 本次重试的文件数
        }
    }

    错误响应：
    - 404: 批量任务不存在
    - 400: 任务未完成或详情丢失

    Args:
        batch_id: 批量任务 ID。
        history_db: 历史数据库实例。
        task_queue: 任务队列实例。
        config: 应用配置。

    Returns:
        重试操作结果。

    Raises:
        HTTPException: 任务不存在或状态不合法时抛出。
    """
    task = await common.get_task_state(batch_id, history_db)
    if not task:
        raise HTTPException(status_code=404, detail="批量任务不存在")

    cached = common.get_task_cache().get(batch_id)
    if not cached or "results" not in cached:
        raise HTTPException(status_code=400, detail="任务详情已丢失，无法重试")

    if cached["status"] != "completed":
        raise HTTPException(status_code=400, detail="任务尚未完成，无法重试")

    failed_items = [(i, r) for i, r in enumerate(cached["results"]) if r["status"] == "failed"]
    if not failed_items:
        return respond_success({"message": "没有失败的文件需要重试"})

    for _i, r in failed_items:
        r["status"] = "pending"
        r["error"] = None
        r["retry_count"] = 0

    common.get_task_cache().update(batch_id, status="processing", failed=0, current_index=-1)

    retry_files = [r["path"] for _, r in failed_items]
    retry_results = [r for _, r in failed_items]
    task_config = cached.get("config", {})
    use_model_size = cached.get("use_model_size", "3b")
    media_type = cached.get("media_type", "image")

    engine = model_registry.get_engine()
    on_cancel = engine.request_cancel if engine else None
    await task_queue.submit(
        batch_id,
        lambda: _process_batch_background(
            batch_id,
            retry_files,
            media_type,
            task_config,
            use_model_size,
            history_db,
            task_queue,
            config,
            results_to_update=retry_results,
        ),
        on_cancel=on_cancel,
    )

    return respond_success(
        {
            "message": f"开始重试 {len(retry_files)} 个失败文件",
            "retry_count": len(retry_files),
        }
    )

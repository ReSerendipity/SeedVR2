#!/usr/bin/env python3
"""Klar - 批量修复路由

批量处理文件夹中的媒体文件，支持自动重试。

REFACTOR 改进:
- 从 unified.py 拆分，职责单一化 (B1/SRP)
- 重试间隔使用 exponential_backoff_with_jitter 替代固定 sleep (E5)
- 最大重试次数从 config.runtime.batch 读取 (F1)
- 统一响应包装 {success, data, error} (G1)
"""
import asyncio
import contextlib
import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException

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
router = APIRouter()


@router.post("/batch")
async def batch_restore_from_folder(
    folder_path: str = Form(...),
    task_type: str = Form("auto"),
    raw_params: UnifiedRestoreParams = Depends(common.parse_unified_params),
    config: dict = Depends(get_config),
    history_db: HistoryDB = Depends(get_history_db),
    task_queue: TaskQueue = Depends(get_task_queue),
):
    """批量处理文件夹中的媒体文件（后台异步，逐个顺序处理）"""
    # GPU 可用性检查：SeedVR2 仅支持 NVIDIA GPU 推理
    if not gpu_manager.is_gpu_available:
        raise HTTPException(
            status_code=503,
            detail="SeedVR2 仅支持 NVIDIA GPU 推理，当前未检测到 NVIDIA GPU。请安装 NVIDIA GPU 并配置 CUDA 驱动。"
        )

    if not model_registry.model_loaded:
        raise HTTPException(status_code=503, detail="模型未加载，请先加载模型")

    folder = Path(folder_path.strip())
    if not await asyncio.to_thread(folder.exists) or not await asyncio.to_thread(folder.is_dir):
        raise HTTPException(status_code=400, detail=f"文件夹不存在: {folder_path}")

    # 扫描文件并确定类型
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

    # 使用第一个文件决定统一类型（auto 模式下）
    actual_type = task_type if task_type != "auto" else media_files[0][1]

    # 构建参数
    dit_model = raw_params.dit_model
    use_model_size = common.model_size_from_dit_model(dit_model)
    if actual_type == "image":
        image_fields = {k: v for k, v in raw_params.model_dump().items() if k in ImageRestoreParams.model_fields}
        params = ImageRestoreParams(**image_fields)
        task_config = params.model_dump()
    else:
        params = VideoRestoreParams(seed=raw_params.seed)
        restore_cfg = config.get("restore", {})
        task_config = {
            "resolution_h": restore_cfg.get("default_resolution_h", 1080),
            "resolution_w": restore_cfg.get("default_resolution_w", 1920),
            "seed": params.seed,
        }

    batch_id = uuid.uuid4().hex[: config.get("runtime", {}).get("task", {}).get("id_length", 16)]

    # 初始化批量任务状态
    # REFACTOR [B2-1]: 临时字段（results/current_index 等）仅写缓存，不持久化到 DB
    # 原实现 `cached = common.get_task_cache()[batch_id]; cached.update({...})` 因 __getitem__
    # 返回浅拷贝，cached.update 不影响缓存；改为通过 update() 一次性写入所有字段
    batch_results = [common.create_batch_item(path) for path, _ in media_files]
    await common.create_task_state(batch_id, 0, history_db, task_type="batch")
    common.get_task_cache().update(batch_id, **{
        "type": "batch",
        "media_type": actual_type,
        "total": len(media_files),
        "completed": 0,
        "failed": 0,
        "current_index": -1,
        "results": batch_results,
        "config": task_config,
        "use_model_size": use_model_size,
    })
    await common.update_task_state(batch_id, history_db, status="processing")

    # REFACTOR [E4-1]: 注入 on_cancel 回调，超时/取消时通知引擎停止 GPU 推理
    # 原实现仅依靠 asyncio.Task.cancel，对 to_thread 包装的同步推理无效，GPU 资源持续占用
    engine = model_registry.get_engine()
    on_cancel = engine.request_cancel if engine else None
    paths_only = [p for p, _ in media_files]
    await task_queue.submit(
        batch_id,
        lambda: _process_batch_background(batch_id, paths_only, actual_type, task_config, use_model_size, history_db, task_queue, config),
        on_cancel=on_cancel,
    )

    return respond_success({
        "batch_id": batch_id,
        "total": len(media_files),
        "media_type": actual_type,
        "status": "processing",
    })


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
    """后台逐个处理批量任务（含自动重试）。

    REFACTOR: 重试间隔使用 exponential_backoff_with_jitter，替代固定 sleep(1/2) (E5)。
    最大重试次数从 config.runtime.batch.max_retries 读取 (F1)。
    """
    task_state = await common.get_task_state(batch_id, history_db)
    if task_state is None:
        return

    # REFACTOR [B2-1]: 使用 get_cached_or_create 替代手动 get + set
    # 原实现 `cached = common.get_task_cache().get(batch_id); if cached is None: ...; common.get_task_cache()[batch_id] = cached`
    # 因 get() 返回浅拷贝，[batch_id] = cached 通过 update_cached 写入，但后续 cached["current_index"] = i
    # 等顶层字段修改不影响缓存；改为 get_cached_or_create 一次性创建并写入缓存
    cached = common.get_cached_or_create(batch_id, template={
        "task_id": batch_id,
        "type": "batch",
        "media_type": media_type,
        "total": len(media_files),
        "completed": 0,
        "failed": 0,
        "current_index": -1,
        "results": [],
        "config": config,
        "use_model_size": use_model_size,
    })

    # results 是 list 引用，append/修改 task_item 会直接影响缓存中的 list
    results = cached["results"]
    completed = 0
    failed = 0
    engine = model_registry.get_engine()

    if engine is None:
        await common.update_task_state(
            batch_id, history_db,
            status="failed",
            error_message="引擎实例不可用",
        )
        return

    records_to_insert: list[HistoryRecord] = []
    output_subdir = "image" if media_type == "image" else "video"

    # OPTIMIZE: 从配置读取重试参数 (F1)
    batch_cfg = app_config.get("runtime", {}).get("batch", {})
    max_retries = batch_cfg.get("max_retries", 2)
    retry_base = batch_cfg.get("retry_base_delay_seconds", 1.0)
    retry_max = batch_cfg.get("retry_max_delay_seconds", 30.0)

    for i, media_path in enumerate(media_files):
        if task_queue.is_cancelled(batch_id):
            for remaining in media_files[i:]:
                records_to_insert.append(HistoryRecord(
                    task_type=media_type,
                    input_file=remaining,
                    model_size=use_model_size,
                    status="cancelled",
                    error_message="批量任务被取消",
                ))
            break

        if results_to_update is not None and i < len(results_to_update):
            task_item = results_to_update[i]
            task_item["status"] = "processing"
            task_item["retry_count"] = 0
        else:
            task_item = common.create_batch_item(media_path)
            task_item["status"] = "processing"
            results.append(task_item)
        # REFACTOR [B2-1]: 顶层字段通过 update 写回缓存（浅拷贝下直接赋值不生效）
        common.get_task_cache().update(batch_id, current_index=i)

        last_error = None

        for attempt in range(max_retries + 1):
            task_item["retry_count"] = attempt
            try:
                output_dir = os.path.join(os.getcwd(), "outputs", output_subdir, batch_id)
                await asyncio.to_thread(os.makedirs, output_dir, exist_ok=True)

                if media_type == "image":
                    image_config = ImageInferenceConfig(**{
                        k: v for k, v in config.items()
                        if k in ImageInferenceConfig.__dataclass_fields__
                    })
                    result = await engine.infer_image(
                        image_path=media_path,
                        output_dir=output_dir,
                        config=image_config,
                    )
                else:
                    async def progress_callback(_current_frame: int, _total_frames: int, _progress: float):
                        pass

                    engine.set_progress_callback(progress_callback)
                    result = await engine.infer_video(
                        video_path=media_path,
                        output_dir=output_dir,
                        res_h=config["resolution_h"],
                        res_w=config["resolution_w"],
                        seed=config["seed"],
                    )

                if result.success:
                    task_item["status"] = "completed"
                    task_item["output_path"] = result.output_path
                    task_item["processing_time"] = result.processing_time
                    task_item["error"] = None
                    completed += 1
                    # REFACTOR [B2-1]: 顶层字段写回缓存
                    common.get_task_cache().update(batch_id, completed=completed)
                    break
                else:
                    last_error = result.error or "未知错误"
                    if attempt < max_retries:
                        task_item["status"] = "retrying"
                        logger.warning(f"批量处理 {media_type} {i+1}/{len(media_files)} 第{attempt+1}次失败，重试中: {media_path}, {last_error}")
                        # E5: 指数退避 + 抖动，替代固定 sleep
                        await exponential_backoff_with_jitter(
                            attempt, base=retry_base, max_delay=retry_max
                        )
                    else:
                        task_item["status"] = "failed"
                        task_item["error"] = last_error
                        failed += 1
                        # REFACTOR [B2-1]: 顶层字段写回缓存
                        common.get_task_cache().update(batch_id, failed=failed)

            except asyncio.CancelledError:
                task_item["status"] = "cancelled"
                task_item["error"] = "用户取消"
                raise
            except Exception as e:
                last_error = str(e)
                if attempt < max_retries:
                    task_item["status"] = "retrying"
                    logger.warning(f"批量处理 {media_type} {i+1}/{len(media_files)} 第{attempt+1}次异常，重试中: {media_path}, {e}")
                    # E5: 指数退避 + 抖动
                    await exponential_backoff_with_jitter(
                        attempt, base=retry_base, max_delay=retry_max
                    )
                else:
                    task_item["status"] = "failed"
                    task_item["error"] = last_error
                    failed += 1
                    # REFACTOR [B2-1]: 顶层字段写回缓存
                    common.get_task_cache().update(batch_id, failed=failed)
                    logger.error(f"批量处理 {media_type} {i+1}/{len(media_files)} 最终失败: {media_path}, {e}")

        records_to_insert.append(HistoryRecord(
            task_type=media_type,
            input_file=media_path,
            model_size=use_model_size,
            status=task_item["status"],
            output_file=task_item.get("output_path"),
            processing_time=task_item.get("processing_time"),
            error_message=task_item.get("error"),
        ))

        progress = round(((i + 1) / len(media_files)) * 100, 1)
        await common.update_task_state(batch_id, history_db, progress=progress)

    try:
        await history_db.add_records(records_to_insert)
    except Exception:
        for record in records_to_insert:
            with contextlib.suppress(Exception):
                await history_db.add_record(record)

    final_status = "cancelled" if task_queue.is_cancelled(batch_id) else "completed"
    # REFACTOR [B2-1]: 重新读取缓存获取最新 progress（cached 变量是循环前的旧拷贝）
    final_cached = common.get_task_cache().get(batch_id, {})
    await common.update_task_state(
        batch_id, history_db,
        status=final_status,
        progress=100.0 if final_status == "completed" else final_cached.get("progress", 0),
    )
    logger.info(f"批量任务 {batch_id} 完成: {completed} 成功, {failed} 失败")


@router.get("/batch/{batch_id}/progress")
async def get_batch_progress(batch_id: str, history_db: HistoryDB = Depends(get_history_db)):
    """获取批量处理进度"""
    task = await common.get_task_state(batch_id, history_db)
    if not task:
        raise HTTPException(status_code=404, detail="批量任务不存在")

    cached = common.get_task_cache().get(batch_id, {})
    return respond_success({
        "batch_id": batch_id,
        "status": task.get("status", "unknown"),
        "progress": task.get("progress", 0),
        "total": cached.get("total", 0),
        "completed": cached.get("completed", 0),
        "failed": cached.get("failed", 0),
        "current_index": cached.get("current_index", -1),
        "results": cached.get("results", []),
        "media_type": cached.get("media_type", "image"),
    })


@router.post("/batch/{batch_id}/retry")
async def retry_failed_batch(
    batch_id: str,
    history_db: HistoryDB = Depends(get_history_db),
    task_queue: TaskQueue = Depends(get_task_queue),
    config: dict = Depends(get_config),
):
    """重试批量任务中失败的文件"""
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

    # r 是 results list 中 dict 的引用，修改直接影响缓存中的 task_item
    for _i, r in failed_items:
        r["status"] = "pending"
        r["error"] = None
        r["retry_count"] = 0

    # REFACTOR [B2-1]: 顶层字段通过 update 写回缓存（浅拷贝下直接赋值不生效）
    common.get_task_cache().update(batch_id, status="processing", failed=0, current_index=-1)

    retry_files = [r["path"] for _, r in failed_items]
    retry_results = [r for _, r in failed_items]
    task_config = cached.get("config", {})
    use_model_size = cached.get("use_model_size", "3b")
    media_type = cached.get("media_type", "image")

    # REFACTOR [E4-1]: 注入 on_cancel 回调，超时/取消时通知引擎停止 GPU 推理
    engine = model_registry.get_engine()
    on_cancel = engine.request_cancel if engine else None
    await task_queue.submit(
        batch_id,
        lambda: _process_batch_background(
            batch_id, retry_files, media_type, task_config, use_model_size, history_db, task_queue, config,
            results_to_update=retry_results,
        ),
        on_cancel=on_cancel,
    )

    return respond_success({
        "message": f"开始重试 {len(retry_files)} 个失败文件",
        "retry_count": len(retry_files),
    })

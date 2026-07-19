#!/usr/bin/env python3
"""SeedVR2 工具箱 - 上传与修复路由

处理文件上传、任务创建、后台推理执行。

REFACTOR 改进:
- 从 unified.py 拆分，职责单一化 (B1/SRP)
- 统一响应包装 {success, data, error} (G1)
- 使用 common.model_size_from_dit_model / common.detect_media_type 消除重复 (A5/DRY)
"""
import asyncio
import logging
import os
import uuid
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from bin.integrated_app.cache import FileCache
from bin.integrated_app.config_models import (
    ImageRestoreParams,
    UnifiedRestoreParams,
    VideoRestoreParams,
)
from bin.integrated_app.dependencies import (
    get_config,
    get_file_cache,
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

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/")
async def upload_and_restore(
    request: Request,
    file: UploadFile | None = File(None),
    folder_path: str | None = Form(None),
    raw_params: UnifiedRestoreParams = Depends(common.parse_unified_params),
    history_db: HistoryDB = Depends(get_history_db),
    file_cache: FileCache = Depends(get_file_cache),
    task_queue: TaskQueue = Depends(get_task_queue),
    config: dict = Depends(get_config),
):
    """上传文件并创建修复任务（立即返回 task_id，后台排队执行）"""
    # REFACTOR: 输入校验前置 — 用户应先修正输入，再关注基础设施可用性 (G3/A10)
    # 先校验输入源是否存在
    if not (file and file.filename) and not (folder_path and folder_path.strip()):
        raise HTTPException(status_code=400, detail="请上传文件或指定文件夹路径")

    # GPU 可用性检查：SeedVR2 仅支持 NVIDIA GPU 推理
    if not gpu_manager.is_gpu_available:
        raise HTTPException(
            status_code=503,
            detail="SeedVR2 仅支持 NVIDIA GPU 推理，当前未检测到 NVIDIA GPU。请安装 NVIDIA GPU 并配置 CUDA 驱动。"
        )

    if not model_registry.model_loaded:
        raise HTTPException(status_code=503, detail="模型未加载，请先加载模型")

    # 确定输入源与任务类型
    input_path: str
    detected_type: str | None = None

    if file and file.filename:
        file_ext = os.path.splitext(file.filename)[1].lower()
        detected_type = common.detect_media_type(file_ext)
        if detected_type is None:
            raise HTTPException(status_code=400, detail=f"不支持的文件格式: {file_ext}")

        if detected_type == "image":
            if file_ext not in common.ALLOWED_IMAGE_EXTENSIONS:
                raise HTTPException(status_code=400, detail=f"不支持的图片格式: {file_ext}")
            contents = await file.read()
            if len(contents) > common.MAX_IMAGE_SIZE:
                raise HTTPException(status_code=400, detail=f"图片文件大小超过限制（最大 {common.MAX_IMAGE_SIZE // (1024*1024)}MB）")
            await file.seek(0)
            _, input_path = await file_cache.save_upload_file(file, sub_dir="image")
        else:
            if file_ext not in common.ALLOWED_VIDEO_EXTENSIONS:
                raise HTTPException(status_code=400, detail=f"不支持的视频格式: {file_ext}")
            contents = await file.read()
            if len(contents) > common.MAX_VIDEO_SIZE:
                raise HTTPException(status_code=400, detail=f"视频文件大小超过限制（最大 {common.MAX_VIDEO_SIZE // (1024*1024)}MB）")
            await file.seek(0)
            _, input_path = await file_cache.save_upload_file(file, sub_dir="video")

    elif folder_path and folder_path.strip():
        folder = Path(folder_path.strip())
        if not await asyncio.to_thread(folder.exists) or not await asyncio.to_thread(folder.is_dir):
            raise HTTPException(status_code=400, detail=f"文件夹不存在: {folder_path}")

        media_files = []
        for root, _dirs, files in await asyncio.to_thread(lambda: list(os.walk(folder))):
            for fname in sorted(files):
                ext = os.path.splitext(fname)[1].lower()
                if ext in common.IMAGE_EXTENSIONS or ext in common.VIDEO_EXTENSIONS:
                    media_files.append((os.path.join(root, fname), ext))
        if not media_files:
            raise HTTPException(status_code=400, detail=f"文件夹中未找到图片或视频: {folder_path}")
        input_path, file_ext = media_files[0]
        detected_type = common.detect_media_type(file_ext)

    # 决定最终任务类型
    task_type = raw_params.task_type
    if task_type == "auto":
        task_type = detected_type or "image"
    elif task_type not in ("image", "video"):
        raise HTTPException(status_code=400, detail=f"无效的任务类型: {task_type}")

    # 构建对应参数模型
    dit_model = raw_params.dit_model
    use_model_size = common.model_size_from_dit_model(dit_model)
    if task_type == "image":
        image_fields = {k: v for k, v in raw_params.model_dump().items() if k in ImageRestoreParams.model_fields}
        params = ImageRestoreParams(**image_fields)
    else:
        video_fields = {"seed": raw_params.seed}
        params = VideoRestoreParams(**video_fields)

    # 生成任务 ID（长度可配）
    task_id = uuid.uuid4().hex[: config.get("runtime", {}).get("task", {}).get("id_length", 16)]

    # 创建历史记录
    record = HistoryRecord(
        task_type=task_type,
        input_file=input_path,
        model_size=use_model_size,
        status="pending",
        parameters=params.model_dump_json(),
    )
    record_id = await history_db.add_record(record)

    # 持久化任务状态
    await common.create_task_state(task_id, record_id, history_db, task_type=task_type)

    # 提交到任务队列
    # REFACTOR [E4-1]: 注入 on_cancel 回调，超时/取消时通知引擎停止 GPU 推理
    # 原实现仅依靠 asyncio.Task.cancel，对 to_thread 包装的同步推理无效，GPU 资源持续占用
    engine = model_registry.get_engine()
    on_cancel = engine.request_cancel if engine else None

    if task_type == "image":
        await task_queue.submit(
            task_id,
            lambda: _process_image_task(task_id, record_id, input_path, params, history_db, task_queue),
            on_cancel=on_cancel,
        )
    else:
        await task_queue.submit(
            task_id,
            lambda: _process_video_task(task_id, record_id, input_path, use_model_size, params, config, history_db, task_queue),
            on_cancel=on_cancel,
        )

    return respond_success({
        "task_id": task_id,
        "record_id": record_id,
        "task_type": task_type,
        "status": "pending",
        "message": "修复任务已创建并加入队列",
    })


async def _run_task_with_state(
    task_id: str,
    record_id: int,
    task_fn: Callable,
    history_db: HistoryDB,
    task_queue: TaskQueue,
):
    """公共任务执行模板 - 统一状态管理和异常处理"""
    try:
        await common.update_task_state(task_id, history_db, status="processing")
        await history_db.update_record(record_id, status="processing")

        if task_queue.is_cancelled(task_id):
            raise asyncio.CancelledError()

        engine = model_registry.get_engine()
        if engine is None:
            raise RuntimeError("引擎实例不可用")

        result = await task_fn(engine)

        if task_queue.is_cancelled(task_id):
            raise asyncio.CancelledError()

        if result.success:
            await common.update_task_state(
                task_id, history_db,
                status="completed", progress=100.0,
                output_path=result.output_path,
            )
            await history_db.update_record(
                record_id,
                status="completed",
                output_file=result.output_path,
                processing_time=result.processing_time,
            )
            logger.info(f"任务完成: {task_id}, 耗时 {result.processing_time:.1f}s")
        else:
            error = result.error or "未知错误"
            await common.update_task_state(task_id, history_db, status="failed", error_message=error)
            await history_db.update_record(record_id, status="failed", error_message=error)
            logger.error(f"任务失败: {task_id}, 错误: {result.error}")

    except asyncio.CancelledError:
        await common.update_task_state(task_id, history_db, status="cancelled", error_message="用户取消")
        await history_db.update_record(record_id, status="cancelled", error_message="用户取消")
        logger.info(f"任务已取消: {task_id}")
        raise
    except Exception as e:
        logger.error(f"任务异常: {task_id}, {e}")
        await common.update_task_state(task_id, history_db, status="failed", error_message=str(e))
        await history_db.update_record(record_id, status="failed", error_message=str(e))


async def _process_image_task(
    task_id: str,
    record_id: int,
    input_path: str,
    params: ImageRestoreParams,
    history_db: HistoryDB,
    task_queue: TaskQueue,
):
    """后台单张图像修复任务"""
    async def _do_infer(engine):
        output_dir = os.path.join(os.getcwd(), "outputs", "image", task_id)
        # 从 params 字典构建 ImageInferenceConfig，只保留 dataclass 识别的字段
        image_config = ImageInferenceConfig(**{
            k: v for k, v in params.model_dump().items()
            if k in ImageInferenceConfig.__dataclass_fields__
        })
        return await engine.infer_image(
            image_path=input_path,
            output_dir=output_dir,
            config=image_config,
        )

    await _run_task_with_state(task_id, record_id, _do_infer, history_db, task_queue)


async def _process_video_task(
    task_id: str,
    record_id: int,
    input_path: str,
    model_size: str,
    params: VideoRestoreParams,
    config: dict,
    history_db: HistoryDB,
    task_queue: TaskQueue,
):
    """后台单视频修复任务"""
    async def _do_infer(engine):
        async def progress_callback(current_frame: int, total_frames: int, progress: float):
            # REFACTOR [B2-1]: 顶层字段通过 update 写回缓存
            # 原实现 `cached = common.get_task_cache().get(task_id); cached["current_frame"] = ...`
            # 因 get() 返回浅拷贝，直接赋值不影响缓存；改为通过 update() 写入
            common.get_task_cache().update(
                task_id,
                current_frame=current_frame,
                total_frames=total_frames,
                progress=round(progress, 1),
            )
            await common.update_task_state(task_id, history_db, progress=round(progress, 1))

        engine.set_progress_callback(progress_callback)

        output_dir = os.path.join(os.getcwd(), "outputs", "video", task_id)
        restore_cfg = config.get("restore", {})
        return await engine.infer_video(
            video_path=input_path,
            output_dir=output_dir,
            res_h=restore_cfg.get("default_resolution_h", 1080),
            res_w=restore_cfg.get("default_resolution_w", 1920),
            seed=params.seed,
        )

    await _run_task_with_state(task_id, record_id, _do_infer, history_db, task_queue)

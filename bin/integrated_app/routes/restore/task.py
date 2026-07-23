#!/usr/bin/env python3
"""Klar - 任务状态操作路由

提供任务进度推送（SSE）、取消、结果查询、结果下载端点。

REFACTOR 改进:
- SSE 超时/心跳参数从 config.runtime.sse 读取，替代硬编码 (F1)
- download_result 使用 PathGuard 白名单保护，防止路径遍历 (D7)
- 统一响应包装 {success, data, error} (G1)
"""
import asyncio
import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from bin.integrated_app.dependencies import get_config, get_history_db, get_task_queue
from bin.integrated_app.history_db import HistoryDB
from bin.integrated_app.routes.restore import common
from bin.integrated_app.security.path_guard import build_default_path_guard
from bin.integrated_app.task_queue import TaskQueue
from bin.integrated_app.utils.response import respond_success

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/{task_id}/progress")
async def get_progress(
    task_id: str,
    history_db: HistoryDB = Depends(get_history_db),
    config: dict = Depends(get_config),
):
    """SSE 进度推送。

    REFACTOR: max_duration / heartbeat_interval 从 config.runtime.sse 读取 (F1)，
    替代原硬编码 300/30。
    """
    task = await common.get_task_state(task_id, history_db)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    sse_cfg = config.get("runtime", {}).get("sse", {})
    max_duration = sse_cfg.get("max_duration_seconds", 300)
    heartbeat_interval = sse_cfg.get("heartbeat_interval_seconds", 30)
    poll_interval = sse_cfg.get("poll_interval_seconds", 0.5)

    async def event_generator():
        start_time = asyncio.get_event_loop().time()
        last_heartbeat = start_time

        while True:
            now = asyncio.get_event_loop().time()
            if now - start_time > max_duration:
                yield f"data: {json.dumps({'task_id': task_id, 'status': 'timeout', 'message': '连接超时'})}\n\n"
                break

            task = await common.get_task_state(task_id, history_db)
            if not task:
                yield f"data: {json.dumps({'error': '任务不存在'})}\n\n"
                break

            data = {
                "task_id": task["task_id"],
                "status": task["status"],
                "progress": task.get("progress", 0),
                "current_frame": task.get("current_frame", 0),
                "total_frames": task.get("total_frames", 0),
                "task_type": task.get("task_type", "image"),
            }
            yield f"data: {json.dumps(data)}\n\n"

            if task["status"] in ("completed", "failed", "cancelled"):
                break

            if now - last_heartbeat >= heartbeat_interval:
                yield ": heartbeat\n\n"
                last_heartbeat = now

            await asyncio.sleep(poll_interval)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    history_db: HistoryDB = Depends(get_history_db),
    task_queue: TaskQueue = Depends(get_task_queue),
):
    """取消进行中的修复任务"""
    task = await common.get_task_state(task_id, history_db)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task["status"] not in ("pending", "processing"):
        raise HTTPException(status_code=400, detail=f"任务状态为 {task['status']}，无法取消")

    task_queue.request_cancel(task_id)
    await common.update_task_state(task_id, history_db, status="cancelled", error_message="用户取消")
    await history_db.update_record(task["record_id"], status="cancelled", error_message="用户取消")
    return respond_success({"task_id": task_id, "status": "cancelled", "message": "任务已取消"})


@router.get("/{task_id}/result")
async def get_result(task_id: str, history_db: HistoryDB = Depends(get_history_db)):
    """获取修复结果"""
    task = await common.get_task_state(task_id, history_db)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    status = task["status"]
    if status in ("pending", "processing"):
        return respond_success({
            "task_id": task_id,
            "status": status,
            "progress": task.get("progress", 0),
        })

    if status == "failed":
        return respond_success({
            "task_id": task_id,
            "status": "failed",
            "error": task.get("error"),
        })

    if status == "cancelled":
        return respond_success({
            "task_id": task_id,
            "status": "cancelled",
            "error": task.get("error"),
        })

    output_path = task.get("output_path")
    if not output_path or not await asyncio.to_thread(os.path.exists, output_path):
        return respond_success({
            "task_id": task_id,
            "status": "completed",
            "output_path": output_path,
            "warning": "输出文件不存在",
        })

    return respond_success({
        "task_id": task_id,
        "status": "completed",
        "output_path": output_path,
        "file_size": await asyncio.to_thread(os.path.getsize, output_path),
    })


@router.get("/{task_id}/download")
async def download_result(
    task_id: str,
    history_db: HistoryDB = Depends(get_history_db),
    config: dict = Depends(get_config),
):
    """下载修复结果。

    SECURITY: 使用 PathGuard 白名单保护，只允许下载 outputs/ 目录下的文件 (D7)。
    原实现无路径校验，可通过构造 task_id 关联的 output_path 读取任意文件。
    """
    task = await common.get_task_state(task_id, history_db)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail="任务尚未完成")

    output_path = task.get("output_path")
    if not output_path or not await asyncio.to_thread(os.path.exists, output_path):
        raise HTTPException(status_code=404, detail="输出文件不存在")

    # SECURITY: 路径白名单校验，防止路径遍历 (D7)
    allowed_dirs = config.get("runtime", {}).get("security", {}).get(
        "allowed_base_dirs", ["outputs/", "data/uploads/"]
    )
    path_guard = build_default_path_guard(os.getcwd(), allowed_dirs)
    if not path_guard.is_safe_path(output_path):
        logger.warning(f"下载路径不在允许范围: {output_path}")
        raise HTTPException(status_code=403, detail="不允许下载该路径")

    filename = os.path.basename(output_path)
    ext = os.path.splitext(filename)[1].lower()

    if task.get("task_type") == "video" or ext in common.ALLOWED_VIDEO_EXTENSIONS:
        media_type = "video/mp4"
    else:
        media_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".bmp": "image/bmp",
            ".webp": "image/webp",
        }
        media_type = media_types.get(ext, "image/png")

    return FileResponse(
        path=output_path,
        filename=filename,
        media_type=media_type,
    )

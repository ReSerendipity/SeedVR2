#!/usr/bin/env python3
"""任务状态操作路由模块。

提供单个修复任务的进度查询（SSE）、取消、结果查询、结果下载等端点。
下载端点使用 PathGuard 白名单保护，防止路径遍历攻击。

API 端点：
- GET /api/restore/{task_id}/progress: SSE 实时进度推送
- POST /api/restore/{task_id}/cancel: 取消进行中的任务
- GET /api/restore/{task_id}/result: 获取任务结果信息
- GET /api/restore/{task_id}/download: 下载修复结果文件

所属项目：SeedVR2 (SeedVR2 视频/图像修复工具)
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
    """SSE 实时进度推送端点。

    API 端点：GET /api/restore/{task_id}/progress

    路径参数：
    - task_id: 任务 ID

    查询参数：无

    返回：Server-Sent Events 流，Content-Type: text/event-stream

    SSE 事件数据格式（JSON）：
    {
        "task_id": str,
        "status": "pending"|"processing"|"completed"|"failed"|"cancelled"|"timeout",
        "progress": float,       // 0-100
        "current_frame": int,    // 视频任务当前帧（仅视频）
        "total_frames": int,     // 视频任务总帧数（仅视频）
        "task_type": "image"|"video"
    }

    心跳：每 30 秒发送一次 ": heartbeat" 注释保活。
    超时：默认 300 秒后发送 timeout 事件并断开。

    Args:
        task_id: 任务 ID。
        history_db: 历史数据库实例。
        config: 应用配置。

    Returns:
        StreamingResponse (text/event-stream)。

    Raises:
        HTTPException: 任务不存在时抛出 404。
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
    """取消进行中的修复任务。

    API 端点：POST /api/restore/{task_id}/cancel

    路径参数：
    - task_id: 任务 ID

    请求体：无

    返回格式（JSON）：
    {
        "success": true,
        "data": {
            "task_id": str,
            "status": "cancelled",
            "message": "任务已取消"
        }
    }

    错误响应：
    - 404: 任务不存在
    - 400: 任务状态不允许取消（已完成/失败/已取消）

    Args:
        task_id: 任务 ID。
        history_db: 历史数据库实例。
        task_queue: 任务队列实例。

    Returns:
        取消操作结果。

    Raises:
        HTTPException: 任务不存在或状态不合法时抛出。
    """
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
    """获取修复任务结果信息。

    API 端点：GET /api/restore/{task_id}/result

    路径参数：
    - task_id: 任务 ID

    返回格式（JSON，根据任务状态不同返回不同字段）：
    - pending/processing: {task_id, status, progress}
    - failed: {task_id, status, error}
    - cancelled: {task_id, status, error}
    - completed: {task_id, status, output_path, file_size, warning?}

    错误响应：
    - 404: 任务不存在

    Args:
        task_id: 任务 ID。
        history_db: 历史数据库实例。

    Returns:
        任务结果信息。

    Raises:
        HTTPException: 任务不存在时抛出。
    """
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
    """下载修复结果文件。

    API 端点：GET /api/restore/{task_id}/download

    路径参数：
    - task_id: 任务 ID

    安全措施：使用 PathGuard 白名单校验，仅允许下载 outputs/ 和 data/uploads/ 目录下的文件，
    防止路径遍历攻击读取任意文件。

    返回：文件流响应，自动设置正确的 Content-Type（image/png, image/jpeg, video/mp4 等）。

    错误响应：
    - 404: 任务不存在或输出文件不存在
    - 400: 任务尚未完成
    - 403: 路径不在允许范围内

    Args:
        task_id: 任务 ID。
        history_db: 历史数据库实例。
        config: 应用配置。

    Returns:
        FileResponse 文件下载响应。

    Raises:
        HTTPException: 任务不存在、未完成、文件不存在或路径非法时抛出。
    """
    task = await common.get_task_state(task_id, history_db)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail="任务尚未完成")

    output_path = task.get("output_path")
    if not output_path or not await asyncio.to_thread(os.path.exists, output_path):
        raise HTTPException(status_code=404, detail="输出文件不存在")

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

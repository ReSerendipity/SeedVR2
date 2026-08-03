#!/usr/bin/env python3
"""启动任务恢复模块。

服务启动时从数据库恢复未完成的修复任务，重新加入任务队列继续执行。
使用批量查询优化，避免 N+1 数据库查询问题。

主要功能：
- 查询数据库中所有未完成（pending/processing）的任务
- 批量获取关联的历史记录
- 根据任务类型（图像/视频）重新提交到任务队列
- 处理参数解析失败等异常情况

所属项目：SeedVR2 (SeedVR2 视频/图像修复工具)
"""

import logging
from typing import Any

from bin.integrated_app.config_models import ImageRestoreParams, VideoRestoreParams
from bin.integrated_app.history_db import HistoryDB
from bin.integrated_app.model_registry import model_registry
from bin.integrated_app.routes.restore import common
from bin.integrated_app.routes.restore.upload import _process_image_task, _process_video_task
from bin.integrated_app.task_queue import TaskQueue

logger = logging.getLogger(__name__)


async def recover_tasks(
    history_db: HistoryDB,
    task_queue: TaskQueue,
    config: dict | None = None,
) -> int:
    """服务启动时从数据库恢复未完成的修复任务。

    查询数据库中所有状态为 pending 或 processing 的任务，
    解析其参数并重新提交到任务队列继续执行。使用批量 IN 查询
    一次性获取所有关联历史记录，避免原实现的 N+1 查询问题。

    Args:
        history_db: 历史记录数据库实例。
        task_queue: 任务队列实例。
        config: 应用配置字典（预留，当前视频分辨率来自记录参数）。

    Returns:
        成功恢复并重新入队的任务数量。

    Note:
        参数解析失败的任务会被标记为 failed，不会中断其他任务恢复。
    """
    incomplete = await history_db.get_incomplete_tasks()
    if not incomplete:
        return 0

    record_ids = [t.record_id for t in incomplete]
    records_list = await history_db.get_records_by_ids(record_ids)
    records_map: dict[int, Any] = {r.id: r for r in records_list if r.id is not None}

    recovered = 0
    for task_record in incomplete:
        record = records_map.get(task_record.record_id)
        if not record or record.task_type not in ("image", "video"):
            continue

        await common.update_task_state(task_record.task_id, history_db, status="pending", progress=0.0)
        await history_db.update_record(record.id, status="pending", error_message="")

        try:
            params: ImageRestoreParams | VideoRestoreParams
            if record.task_type == "image":
                params = ImageRestoreParams.model_validate_json(record.parameters or "{}")
            else:
                params = VideoRestoreParams.model_validate_json(record.parameters or "{}")
        except Exception:
            logger.warning(f"恢复任务 {task_record.task_id} 时参数解析失败，跳过")
            await common.update_task_state(
                task_record.task_id, history_db, status="failed", error_message="参数解析失败"
            )
            await history_db.update_record(record.id, status="failed", error_message="参数解析失败")
            continue

        use_model_size = record.model_size or model_registry.current_model_size or "3b"
        if record.task_type == "image":
            p_img: ImageRestoreParams = params  # type: ignore[assignment]
            image_task = (  # type: ignore[misc]  # mypy cannot infer lambda type with complex defaults  # noqa: E731
                lambda t=task_record, r=record, p=p_img: _process_image_task(
                    t.task_id, r.id, r.input_file, p, history_db, task_queue
                )
            )
            await task_queue.submit(task_record.task_id, image_task)
        else:
            p_vid: VideoRestoreParams = params  # type: ignore[assignment]
            video_task = (  # type: ignore[misc]  # mypy cannot infer lambda type with complex defaults  # noqa: E731
                lambda t=task_record, r=record, p=p_vid, m=use_model_size, h=history_db, q=task_queue: _process_video_task(
                    t.task_id, r.id, r.input_file, m, p, h, q
                )
            )
            await task_queue.submit(task_record.task_id, video_task)
        recovered += 1
    return recovered

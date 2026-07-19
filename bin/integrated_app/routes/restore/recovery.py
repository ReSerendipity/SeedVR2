#!/usr/bin/env python3
"""SeedVR2 工具箱 - 启动恢复路由

服务启动时从数据库恢复未完成的修复任务。

REFACTOR 改进:
- 使用 get_records_by_ids 批量查询，修复原 N+1 查询问题 (C3)
  原实现循环调用 get_record(record_id)，N 条任务产生 N 次 DB 查询；
  改为一次 IN 查询获取所有记录。
"""
import logging

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

    OPTIMIZE: 使用 get_records_by_ids 批量查询，修复 N+1 (C3)。
    原实现循环调用 get_record(task_record.record_id) 逐条查询，
    N 条未完成任务产生 N+1 次 DB 查询；改为 1 次批量 IN 查询。
    """
    incomplete = await history_db.get_incomplete_tasks()
    if not incomplete:
        return 0

    # C3: 批量查询所有关联的历史记录，替代循环逐条查询
    record_ids = [t.record_id for t in incomplete]
    records_list = await history_db.get_records_by_ids(record_ids)
    records_map: dict[int, any] = {r.id: r for r in records_list}

    recovered = 0
    for task_record in incomplete:
        record = records_map.get(task_record.record_id)
        if not record or record.task_type not in ("image", "video"):
            continue

        await common.update_task_state(task_record.task_id, history_db, status="pending", progress=0.0)
        await history_db.update_record(record.id, status="pending", error_message="")

        try:
            if record.task_type == "image":
                params = ImageRestoreParams.model_validate_json(record.parameters or "{}")
            else:
                params = VideoRestoreParams.model_validate_json(record.parameters or "{}")
        except Exception:
            logger.warning(f"恢复任务 {task_record.task_id} 时参数解析失败，跳过")
            await common.update_task_state(task_record.task_id, history_db, status="failed", error_message="参数解析失败")
            await history_db.update_record(record.id, status="failed", error_message="参数解析失败")
            continue

        use_model_size = record.model_size or model_registry.current_model_size or "3b"
        if record.task_type == "image":
            await task_queue.submit(
                task_record.task_id,
                lambda t=task_record, r=record, p=params: _process_image_task(
                    t.task_id, r.id, r.input_file, p, history_db, task_queue
                ),
            )
        else:
            await task_queue.submit(
                task_record.task_id,
                lambda t=task_record, r=record, p=params, m=use_model_size, c=config: _process_video_task(
                    t.task_id, r.id, r.input_file, m, p, c, history_db, task_queue
                ),
            )
        recovered += 1
    return recovered

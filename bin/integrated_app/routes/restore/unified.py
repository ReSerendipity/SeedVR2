#!/usr/bin/env python3
"""SeedVR2 工具箱 - 统一修复路由（聚合入口）

同时处理图像与视频修复请求，根据文件类型或显式 task_type 自动分发。
旧的 /api/restore/image 与 /api/restore/video 由本模块统一接管。

REFACTOR: 将原 966 行单文件拆分为职责单一的子模块 (B1/SRP):
- scan.py:       文件夹扫描
- upload.py:     上传与单文件修复
- batch.py:      批量修复
- task.py:       任务状态操作（进度/取消/结果/下载）
- recovery.py:   启动恢复
- common.py:     共享工具与状态管理

本文件仅作为路由聚合入口，通过 include_router 合并所有子路由。
"""
import logging

from fastapi import APIRouter

from bin.integrated_app.routes.restore.batch import router as batch_router
from bin.integrated_app.routes.restore.recovery import recover_tasks
from bin.integrated_app.routes.restore.scan import router as scan_router
from bin.integrated_app.routes.restore.task import router as task_router
from bin.integrated_app.routes.restore.upload import router as upload_router

logger = logging.getLogger(__name__)

# 聚合路由：所有子路由在此合并
router = APIRouter()

# 注意：注册顺序影响路由匹配优先级
# 1. scan-folder（GET /scan-folder）必须先于 /{task_id}/* 注册，否则会被 {task_id} 捕获
# 2. batch（POST /batch, GET /batch/{batch_id}/progress, POST /batch/{batch_id}/retry）
# 3. upload（POST ""）
# 4. task（GET /{task_id}/progress, POST /{task_id}/cancel, GET /{task_id}/result, GET /{task_id}/download）
router.include_router(scan_router)
router.include_router(batch_router)
router.include_router(upload_router)
router.include_router(task_router)


__all__ = ["router", "recover_tasks"]

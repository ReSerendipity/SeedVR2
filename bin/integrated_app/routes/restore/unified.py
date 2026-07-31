#!/usr/bin/env python3
"""修复路由统一聚合入口模块。

本文件作为 /api/restore 路由的聚合入口，负责将职责拆分后的子模块路由
统一注册到一个 APIRouter 实例中。子模块按单一职责原则拆分如下：
- scan.py: 文件夹扫描端点
- upload.py: 单文件上传与修复端点
- batch.py: 批量文件夹修复端点
- task.py: 任务状态操作端点（进度/取消/结果/下载）
- recovery.py: 启动时任务恢复逻辑（非路由模块，导出 recover_tasks 函数）
- common.py: 公共工具函数与状态管理

路由注册顺序影响匹配优先级：
1. /scan-folder (GET) 必须先于 /{task_id}/* 注册，避免被路径参数捕获
2. /batch (POST), /batch/{batch_id}/progress, /batch/{batch_id}/retry
3. / (POST) - 上传入口
4. /{task_id}/progress, /{task_id}/cancel, /{task_id}/result, /{task_id}/download

API 路由前缀：/api/restore
所属项目：SeedVR2 (SeedVR2 视频/图像修复工具)
"""
import logging

from fastapi import APIRouter

from bin.integrated_app.routes.restore.batch import router as batch_router
from bin.integrated_app.routes.restore.recovery import recover_tasks
from bin.integrated_app.routes.restore.scan import router as scan_router
from bin.integrated_app.routes.restore.task import router as task_router
from bin.integrated_app.routes.restore.upload import router as upload_router

logger = logging.getLogger(__name__)

router = APIRouter()

router.include_router(scan_router)
router.include_router(batch_router)
router.include_router(upload_router)
router.include_router(task_router)


__all__ = ["router", "recover_tasks"]

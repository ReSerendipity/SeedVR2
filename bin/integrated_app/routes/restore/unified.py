#!/usr/bin/env python3
"""修复路由统一聚合入口模块。

本模块原为路由聚合入口，现已改为仅导出非路由工具函数。
各子模块（scan.py、batch.py、upload.py、task.py）的路由由
routes/__init__.py 的 auto_discover_routes() 通过 pkgutil 自动发现并注册。

子模块按单一职责拆分如下：
- scan.py: 文件夹扫描端点（router 自动发现注册）
- upload.py: 单文件上传与修复端点（router 自动发现注册）
- batch.py: 批量文件夹修复端点（router 自动发现注册）
- task.py: 任务状态操作端点（router 自动发现注册）
- recovery.py: 启动时任务恢复逻辑（非路由模块，导出 recover_tasks 函数）
- common.py: 公共工具函数与状态管理

API 路由前缀：/api/restore
所属项目：SeedVR2 (SeedVR2 视频/图像修复工具)
"""

from bin.integrated_app.routes.restore.recovery import cleanup_stale_tasks, recover_tasks

__all__ = ["recover_tasks", "cleanup_stale_tasks"]

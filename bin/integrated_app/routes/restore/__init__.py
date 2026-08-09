#!/usr/bin/env python3
"""图像与视频修复路由包。

本包包含 SeedVR2 项目的修复功能路由模块，按职责拆分为子模块：
- unified.py: 路由聚合入口，统一注册所有修复相关子路由
- scan.py: 文件夹扫描端点
- upload.py: 单文件上传与修复
- batch.py: 批量文件夹修复
- task.py: 任务状态查询、取消、结果下载
- recovery.py: 服务启动时恢复未完成任务
- common.py: 公共工具函数与状态管理

API 路由前缀：/api/restore
所属项目：SeedVR2 (SeedVR2 视频/图像修复工具)
"""

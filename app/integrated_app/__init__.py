#!/usr/bin/env python3
"""SeedVR2 集成应用包

SeedVR2 视频修复桌面应用的核心集成层，提供独立于 ComfyUI 的完整应用服务。

本包包含以下核心模块:
- app_server: FastAPI 应用创建与生命周期管理
- config / config_models: 配置加载与 Pydantic 校验
- engines: 推理引擎抽象与 SeedVR2 具体实现
- model_manager / model_registry: 模型加载、卸载、状态管理
- task_queue: 单 Worker 串行任务队列，避免并发 OOM
- history_db: SQLite 历史记录与任务状态持久化
- cache: 上传文件缓存与 LRU/自适应 LRU 内存缓存
- video_processor: FFmpeg 封装与视频分帧/合帧
- color_fix: LAB/HSV/小波等多种颜色校正后处理算法
- i18n: 多语言国际化支持（中/英/日/法）
- progress: 多阶段推理进度追踪与 SSE 通知
- exceptions: 统一异常层次结构
- routes: API 路由（修复路由、系统路由、SSE）
- services: 任务状态双层存储、事件总线等服务
- middleware: CSRF 保护、统一错误处理等中间件
- security: 路径白名单守卫等安全模块
- optimization: 显存管理、BlockSwap 等优化策略
- utils: 通用工具函数（响应包装、重试、全文检索等）

启动链路: start.bat -> app/clean_launch.py -> app_server.py
默认监听地址: 127.0.0.1:7870
"""

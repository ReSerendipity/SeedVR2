#!/usr/bin/env python3
"""
SeedVR2 - FastAPI 依赖注入模块

所属项目：SeedVR2 (AI-powered video & image super-resolution toolkit)
核心功能：
    - 提供基于 Request.app.state 的可复用依赖函数
    - 供路由函数通过 FastAPI 的 Depends() 机制注入核心组件
    - 统一组件获取入口，避免路由直接访问 app.state 内部结构
    - 支持类型提示，便于 IDE 自动补全和静态类型检查

核心技术栈：
    - FastAPI 依赖注入系统（Depends）
    - Starlette Request 对象状态传递
    - 类型注解支持（typing 模块）

使用示例：
    >>> from fastapi import Depends
    >>>
    >>> @app.get("/api/tasks")
    >>> async def list_tasks(
    ...     task_queue: TaskQueue = Depends(get_task_queue),
    ...     history_db: HistoryDB = Depends(get_history_db),
    ... ):
    ...     tasks = await task_queue.list_tasks()
    ...     return {"success": True, "data": tasks}
"""

from typing import Any

from fastapi import Request

from bin.integrated_app.cache import FileCache
from bin.integrated_app.gpu_backend import GPUBackendManager
from bin.integrated_app.history_db import HistoryDB
from bin.integrated_app.i18n import I18n
from bin.integrated_app.model_manager import ModelManager
from bin.integrated_app.task_queue import TaskQueue


def get_history_db(request: Request) -> HistoryDB:
    """从请求状态中获取历史记录数据库实例。

    Args:
        request: FastAPI/Starlette 请求对象，通过 app.state 访问已初始化组件。

    Returns:
        HistoryDB: 历史记录数据库实例，用于任务记录的增删改查操作。

    Note:
        HistoryDB 在 create_app() 中初始化并挂载到 app.state.history_db，
        应用生命周期内为单例。
    """
    return request.app.state.history_db


def get_task_queue(request: Request) -> TaskQueue:
    """从请求状态中获取异步任务队列实例。

    Args:
        request: FastAPI/Starlette 请求对象。

    Returns:
        TaskQueue: 单 worker 异步任务队列实例，用于提交和查询修复任务。

    Note:
        TaskQueue 在 lifespan 启动阶段启动，关闭阶段优雅停止，
        串行执行推理任务避免并发 OOM。
    """
    return request.app.state.task_queue


def get_model_manager(request: Request) -> ModelManager:
    """从请求状态中获取模型管理器实例。

    Args:
        request: FastAPI/Starlette 请求对象。

    Returns:
        ModelManager: 模型管理器实例，负责模型加载、卸载、切换和状态查询。
    """
    return request.app.state.model_manager


def get_config(request: Request) -> dict:
    """从请求状态中获取应用配置字典。

    Args:
        request: FastAPI/Starlette 请求对象。

    Returns:
        dict: 应用配置字典，包含 server、model、restore 等所有配置节。

    Note:
        返回原始字典格式以保持向后兼容，新代码如需类型安全可使用
        get_app_config() 函数获取 Pydantic AppConfig 实例。
    """
    return request.app.state.config


def get_file_cache(request: Request) -> FileCache:
    """从请求状态中获取文件缓存实例。

    Args:
        request: FastAPI/Starlette 请求对象。

    Returns:
        FileCache: 上传文件缓存管理器，负责临时文件存储和过期清理。
    """
    return request.app.state.file_cache


def get_i18n(request: Request) -> I18n:
    """从请求状态中获取国际化实例。

    Args:
        request: FastAPI/Starlette 请求对象。

    Returns:
        I18n: 国际化管理器，支持中/英/日/法四语言，根据 Accept-Language 头
              或用户偏好返回对应翻译文本。
    """
    return request.app.state.i18n


def get_gpu_backend(request: Request) -> GPUBackendManager:
    """从请求状态中获取 GPU 后端管理器实例。

    Args:
        request: FastAPI/Starlette 请求对象。

    Returns:
        GPUBackendManager: GPU 后端管理器，提供 GPU 可用性检测、设备信息查询、
                          显存管理等功能。
    """
    return request.app.state.gpu_backend


def get_jinja_env(request: Request) -> Any:
    """从请求状态中获取 Jinja2 模板环境实例。

    Args:
        request: FastAPI/Starlette 请求对象。

    Returns:
        jinja2.Environment: Jinja2 模板环境，用于渲染 HTML 页面模板。

    Note:
        返回类型标注为 Any 是为了避免强制依赖 jinja2 类型存根，
        实际类型为 jinja2.Environment。
    """
    return request.app.state.jinja_env


def get_event_bus(request: Request) -> Any:
    """从请求状态中获取 SSE 事件总线实例。

    Args:
        request: FastAPI/Starlette 请求对象。

    Returns:
        EventBus | None: SSE 事件总线实例，用于发布进度事件推送给前端。
                         如果事件总线未注册则返回 None（向后兼容）。

    Note:
        事件总线用于跨线程发布任务进度事件，SSE 端点订阅此总线实时推送
        进度更新给前端。使用 getattr 安全访问确保未注册时不抛出异常。
    """
    return getattr(request.app.state, "event_bus", None)

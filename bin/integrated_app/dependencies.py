#!/usr/bin/env python3
"""SeedVR2 工具箱 - FastAPI 依赖注入

提供基于 Request.app.state 的可复用依赖函数，供路由通过 Depends 注入使用。
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
    """获取历史记录数据库实例"""
    return request.app.state.history_db


def get_task_queue(request: Request) -> TaskQueue:
    """获取任务队列实例"""
    return request.app.state.task_queue


def get_model_manager(request: Request) -> ModelManager:
    """获取模型管理器实例"""
    return request.app.state.model_manager


def get_config(request: Request) -> dict:
    """获取应用配置字典"""
    return request.app.state.config


def get_file_cache(request: Request) -> FileCache:
    """获取文件缓存实例"""
    return request.app.state.file_cache


def get_i18n(request: Request) -> I18n:
    """获取国际化实例"""
    return request.app.state.i18n


def get_gpu_backend(request: Request) -> GPUBackendManager:
    """获取 GPU 后端实例"""
    return request.app.state.gpu_backend


def get_jinja_env(request: Request) -> Any:
    """获取 Jinja2 模板环境"""
    return request.app.state.jinja_env


def get_event_bus(request: Request) -> Any:
    """获取 SSE 事件总线实例（如已注册）"""
    return getattr(request.app.state, "event_bus", None)

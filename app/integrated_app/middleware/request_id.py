"""请求 ID 中间件 — 为每个入站 HTTP 请求分配全局唯一标识符。

架构角色：
    本模块实现 ASGI 全局请求 ID 中间件，为每个入站请求分配 UUID4（16 hex）
    request_id，并完成三件事：
      1. 将 request_id 注入 Python logging 上下文（通过 ContextVar + 线程本地镜像）
         使整条链路（middleware → route → model_manager → SSE 事件）的日志都能
         自动携带 request_id，用于 ELK/EFK 日志聚合与分布式链路追踪。
      2. 在响应中写入 ``X-Request-ID`` 头，供前端 / 反向代理关联。
      3. 对外暴露 ``get_request_id`` / ``set_request_id`` 工具函数，供后台线程
         （如模型加载）主动发布其关联 ID。

中间件注册位置：
    在 ``app_server.create_app()`` 中被注册为 **第一个** 中间件。
    Why：后续 CSRF / Auth / error_handler 等所有中间件与路由 handler 的
    logger 输出均需要 request_id 做链路追踪，因此必须最先注入上下文。
"""

from __future__ import annotations

import contextvars
import logging
import re
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")

_REQUEST_ID_SANITIZER = re.compile(r"[^A-Za-z0-9_\-]")
_MAX_REQUEST_ID_LEN: int = 64

logger = logging.getLogger("seedvr2.request_id")

_request_id_local = threading.local()


def get_request_id() -> str:
    """从异步上下文（ContextVar）获取当前 request_id。

    Returns:
        当前上下文关联的 request_id 字符串；若未设置则返回空字符串。
    """
    return _request_id_var.get()


def set_request_id(request_id: str) -> None:
    """发布 request_id 到 ContextVar 与线程本地镜像。

    用于后台线程（如模型加载），使得其日志记录携带相同的关联 ID。

    Args:
        request_id: 需要发布的请求 ID 字符串。
    """
    _request_id_var.set(request_id)
    _request_id_local.request_id = request_id


def _sanitize_request_id(raw: str) -> str:
    """清理入站 X-Request-ID，防止日志注入。

    Args:
        raw: 原始入站 header 值。

    Returns:
        清理后的字符串。为空或全部非法字符时返回空串。
    """
    if not raw:
        return ""
    return _REQUEST_ID_SANITIZER.sub("", raw)[:_MAX_REQUEST_ID_LEN]


class RequestIDMiddleware(BaseHTTPMiddleware):
    """为每个 HTTP 请求-响应循环附加全局唯一 request_id。"""

    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID") -> None:
        super().__init__(app)
        self._header_name: str = header_name

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        raw_id = request.headers.get(self._header_name, "")
        sanitized = _sanitize_request_id(raw_id)

        request_id: str
        if sanitized:
            request_id = sanitized
        else:
            try:
                request_id = uuid.uuid4().hex[:16]
            except (ValueError, TypeError):
                logger.debug("uuid.uuid4() 生成失败，使用时间戳回退")
                request_id = f"req-{time.time_ns()}"

        token = _request_id_var.set(request_id)
        _request_id_local.request_id = request_id
        try:
            request.state.request_id = request_id
            response = await call_next(request)
            if self._header_name not in response.headers:
                response.headers[self._header_name] = request_id
            return response
        finally:
            try:
                _request_id_var.reset(token)
            except (ValueError, LookupError):
                logger.debug("ContextVar token 已被重置，跳过")
            _request_id_local.request_id = "-"

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Any],
        send: Callable[[Any], Awaitable[None]],
    ) -> None:
        await super().__call__(scope, receive, send)


class RequestIDLogFilter(logging.Filter):
    """日志过滤器，将当前 request_id 注入每条 LogRecord。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            rid = _request_id_var.get("")
            if not rid:
                rid = getattr(_request_id_local, "request_id", "-")
            record.request_id = rid
        return True

#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2024-2026 ReSerendipity
# SPDX-License-Identifier: Apache-2.0
"""SeedVR2 - 请求速率限制中间件。

对上传 / 推理类端点按客户端 IP 做内存滑动窗口限流，
防止单 IP 高频请求耗尽 GPU/队列资源 (CWE-770)。

限流对象 (POST 端点):
    - /api/restore/                  单文件上传 + 修复任务创建
    - /api/restore/batch             批量上传
    - /api/restore/batch/{id}/retry  批量失败重试
    - /api/engine/submit             引擎推理任务提交
进度查询 / 下载 / SSE 等只读 GET 端点不在限流范围，
避免误伤前端轮询。

配置 (config.yaml):
    runtime:
      security:
        rate_limit_per_minute: 30   # 每分钟每 IP 允许的请求数 (默认 30)

IP 识别策略 (重要):
    - 默认使用直连 IP (request.client.host)，**不信任 X-Forwarded-For**。
      直连部署时 XFF 完全可由客户端伪造，盲信会导致限流被绕过。
    - 仅在反向代理部署且显式设置环境变量 ``SEEDVR2_TRUST_PROXY=1`` 时，
      才解析 XFF 并取最左侧地址 (原始客户端 IP)；代理自身必须负责
      覆写/剥离客户端传入的 XFF，否则该模式仍可被伪造。

实现说明:
    - 内存滑动窗口: 每 IP 维护一个时间戳 deque，窗口期内计数超限返回 429
      + ``Retry-After`` 头 (RFC 7231)。
    - 运行在 asyncio 事件循环内 (BaseHTTPMiddleware.dispatch)，单循环下
      dict + deque 操作天然串行，无需额外加锁。
    - 内存护栏: 跟踪 IP 数超过阈值时清理过期条目，防止无界增长。
    - 多 worker / 多进程部署时窗口为进程内状态，各进程独立计数；
      如需全局精确限流应在反向代理层 (nginx limit_req) 或共享存储实现。

响应格式与 error_handler.py 的统一结构保持一致:
    {"error": {"code": "RATE_LIMITED", "message": ..., "detail": {...}}}
"""

import logging
import math
import os
import re
import time
from collections import deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# 单测可替换的单调时钟 (滑动窗口时间基准)
_monotonic = time.monotonic

# 滑动窗口时长 (秒)，与 rate_limit_per_minute 的 "每分钟" 语义对应
_WINDOW_SECONDS = 60.0

# 内存护栏：跟踪的 IP 条目上限，超过后触发过期条目清理
_MAX_TRACKED_IPS = 1024

# 限流的端点路径模式 (均为 POST 上传/推理类端点)
_RATE_LIMITED_PATH_PATTERNS = (
    re.compile(r"^/api/restore/?$"),  # 单文件上传+修复
    re.compile(r"^/api/restore/batch/?$"),  # 批量上传
    re.compile(r"^/api/restore/batch/[^/]+/retry$"),  # 批量失败重试
    re.compile(r"^/api/engine/submit$"),  # 引擎推理任务提交
)

# 信任 X-Forwarded-For 的环境变量开关 (反向代理部署时显式开启)
_TRUST_PROXY_ENV = "SEEDVR2_TRUST_PROXY"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """基于内存滑动窗口的每 IP 请求速率限制中间件。

    对匹配的上传/推理 POST 端点按客户端 IP 计数：
    窗口期内请求数 >= rate_limit_per_minute 时返回 429，
    并携带 Retry-After 头告知客户端等待秒数。

    Attributes:
        WINDOW_SECONDS: 滑动窗口时长（秒），默认 60（与配置的"每分钟"语义一致）。
    """

    WINDOW_SECONDS = _WINDOW_SECONDS

    def __init__(
        self,
        app,
        rate_limit_per_minute: int = 30,
        window_seconds: float = _WINDOW_SECONDS,
        trust_proxy: bool = False,
    ):
        """初始化速率限制中间件。

        Args:
            app: ASGI 应用实例。
            rate_limit_per_minute: 每分钟每 IP 允许的请求数，<=0 表示禁用。
            window_seconds: 滑动窗口时长（秒），测试可注入小窗口。
            trust_proxy: 是否信任 X-Forwarded-For 头（默认 False）。
                也可通过环境变量 SEEDVR2_TRUST_PROXY=1 开启。
        """
        super().__init__(app)
        self._limit = int(rate_limit_per_minute)
        self._window_seconds = float(window_seconds)
        env_trust = os.environ.get(_TRUST_PROXY_ENV, "").strip().lower() in ("1", "true", "yes")
        self._trust_proxy = trust_proxy or env_trust
        # IP -> 窗口内请求时间戳队列（单调时钟）
        self._hits: dict[str, deque[float]] = {}

    @staticmethod
    def _matches_path(path: str) -> bool:
        """判断路径是否属于限流范围的上传/推理端点。"""
        return any(p.match(path) for p in _RATE_LIMITED_PATH_PATTERNS)

    def _client_ip(self, request: Request) -> str:
        """提取客户端 IP。

        默认以直连 IP (request.client.host) 为准，不信任 X-Forwarded-For；
        仅当显式开启 trust_proxy 时取 XFF 最左侧地址（原始客户端 IP），
        且要求反向代理自行覆写 XFF，否则该头可被伪造绕过限流。

        Args:
            request: Starlette 请求对象。

        Returns:
            str: 客户端 IP 字符串；无直连信息时返回 "unknown"。
        """
        direct_ip = request.client.host if request.client else "unknown"
        if self._trust_proxy:
            forwarded = request.headers.get("x-forwarded-for", "")
            if forwarded:
                first = forwarded.split(",")[0].strip()
                if first:
                    return first
        return direct_ip

    def _sweep(self, now: float) -> None:
        """内存护栏：IP 条目超过阈值时清理窗口外过期条目。

        仅在条目数超限时执行，避免每次请求都遍历全表。

        Args:
            now: 当前单调时钟时间。
        """
        if len(self._hits) <= _MAX_TRACKED_IPS:
            return
        cutoff = now - self._window_seconds
        stale = [ip for ip, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for ip in stale:
            del self._hits[ip]

    def _allow(self, client_ip: str) -> int:
        """滑动窗口计数：记录一次请求并返回剩余配额。

        窗口内已有请求数达到上限时返回 -1（拒绝且不记录本次）。

        Args:
            client_ip: 客户端 IP。

        Returns:
            int: 剩余可用配额（>=0），或 -1 表示超限应返回 429。
        """
        if self._limit <= 0:
            return 1  # limit<=0 表示禁用限流，永远放行
        now = _monotonic()
        hits = self._hits.setdefault(client_ip, deque())
        # 清理窗口外的过期时间戳 (滑动窗口)
        while hits and now - hits[0] > self._window_seconds:
            hits.popleft()
        if len(hits) >= self._limit:
            self._sweep(now)
            return -1
        hits.append(now)
        self._sweep(now)
        return self._limit - len(hits)

    def _retry_after_seconds(self, client_ip: str) -> int:
        """计算该 IP 最早请求过期还需等待的秒数（向上取整，最小 1）。"""
        hits = self._hits.get(client_ip)
        if not hits:
            return 1
        wait = self._window_seconds - (_monotonic() - hits[0])
        return max(1, int(math.ceil(wait)))

    async def dispatch(self, request: Request, call_next):
        """中间件分发方法：仅对限流范围内的 POST 上传/推理端点计数。"""
        if self._limit > 0 and request.method == "POST" and self._matches_path(request.url.path):
            client_ip = self._client_ip(request)
            if self._allow(client_ip) < 0:
                retry_after = self._retry_after_seconds(client_ip)
                logger.warning(
                    f"速率限制触发: {request.method} {request.url.path} from {client_ip} "
                    f"(limit={self._limit}/min)"
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "code": "RATE_LIMITED",
                            "message": "请求过于频繁，请稍后重试",
                            "detail": {"retry_after_seconds": retry_after},
                        }
                    },
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(self._limit),
                        "X-RateLimit-Remaining": "0",
                    },
                )
        return await call_next(request)

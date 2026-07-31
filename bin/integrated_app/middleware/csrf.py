#!/usr/bin/env python3
"""SeedVR2 - CSRF 保护中间件。

基于 Double Submit Cookie 模式实现跨站请求伪造防护。

安全策略:
    - 安全方法 (GET/HEAD/OPTIONS)：自动生成并设置 CSRF token cookie
    - 非安全方法 (POST/PUT/DELETE/PATCH)：验证 cookie 与 X-CSRF-Token header 匹配
    - SameSite=Strict：彻底阻断跨站请求携带 cookie
    - Secure 标志：根据请求协议自动启用（HTTPS 或 X-Forwarded-Proto=https）
    - Path=/：确保全路径覆盖，避免子路径隔离问题
    - secrets.compare_digest：使用常量时间比较，防止时序攻击

白名单机制:
    - 文档路径 (/docs, /openapi.json, /redoc) 和静态文件 (/static/) 跳过检查
    - SSE 进度推送和文件夹扫描等 GET 端点安全放行（只读操作）

设计模式:
    - 采用 Starlette BaseHTTPMiddleware 实现请求/响应拦截
    - 静态方法处理路径匹配与协议检测，便于单元测试
"""
import logging
import re
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

_SAFE_GET_PATH_PATTERNS = (
    re.compile(r"^/api/restore/[^/]+/progress$"),
    re.compile(r"^/api/restore/batch/[^/]+/progress$"),
    re.compile(r"^/api/restore/scan-folder$"),
)


class CSRFMiddleware(BaseHTTPMiddleware):
    """CSRF 保护中间件。

    实现 Double Submit Cookie 防护模式：
    1. 首次 GET 请求时服务端生成随机 token 写入 cookie
    2. 前端读取 cookie 中的 token，在非安全请求时通过 X-CSRF-Token header 回传
    3. 服务端比较 cookie 与 header 中的 token 是否一致

    Attributes:
        SAFE_METHODS: 不需要 CSRF 验证的 HTTP 方法集合
        CSRF_COOKIE_NAME: CSRF token 的 cookie 名称
        CSRF_HEADER_NAME: CSRF token 的 HTTP header 名称
        SKIP_PATHS: 跳过 CSRF 检查的路径前缀元组
    """

    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    CSRF_COOKIE_NAME = "csrf_token"
    CSRF_HEADER_NAME = "X-CSRF-Token"

    SKIP_PATHS = ("/docs", "/openapi.json", "/redoc", "/static/")

    @staticmethod
    def _is_safe_get_path(path: str) -> bool:
        """判断 GET 请求路径是否属于安全的进度/扫描端点。

        SSE 进度推送和文件夹扫描等端点为只读操作，无需 CSRF 验证。

        Args:
            path: 请求 URL 路径

        Returns:
            bool: 路径匹配安全模式时返回 True
        """
        return any(p.match(path) for p in _SAFE_GET_PATH_PATTERNS)

    @staticmethod
    def _is_secure_request(request: Request) -> bool:
        """判断请求是否通过 HTTPS 传输（含反向代理场景）。

        Secure cookie 仅在 HTTPS 下设置，否则浏览器会拒绝。
        支持通过 X-Forwarded-Proto 头识别反向代理后的真实协议。

        Args:
            request: Starlette 请求对象

        Returns:
            bool: 请求为安全传输时返回 True
        """
        if request.url.scheme == "https":
            return True
        forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
        return "https" in forwarded_proto

    async def dispatch(self, request: Request, call_next) -> Response:
        """中间件核心处理逻辑，按请求类型分别处理。

        处理流程：
        1. 安全方法：正常处理请求，若 cookie 中无 token 则生成并设置
        2. 白名单路径：直接放行（文档、静态文件）
        3. 非安全方法：验证 cookie 与 header 中 token 一致性，失败返回 403

        Args:
            request: 传入的 HTTP 请求对象
            call_next: 调用下一个中间件或路由处理函数的异步可调用对象

        Returns:
            Response: HTTP 响应对象，可能包含新设置的 CSRF cookie 或 403 错误
        """
        if request.method in self.SAFE_METHODS:
            response: Response = await call_next(request)
            if self.CSRF_COOKIE_NAME not in request.cookies:
                token = secrets.token_hex(32)
                response.set_cookie(
                    self.CSRF_COOKIE_NAME,
                    token,
                    httponly=False,
                    samesite="strict",
                    secure=self._is_secure_request(request),
                    path="/",
                )
            return response

        if any(request.url.path.startswith(prefix) for prefix in self.SKIP_PATHS):
            return await call_next(request)

        cookie_token = request.cookies.get(self.CSRF_COOKIE_NAME)
        header_token = request.headers.get(self.CSRF_HEADER_NAME)

        if cookie_token and header_token and secrets.compare_digest(cookie_token, header_token):
            return await call_next(request)

        logger.warning(f"CSRF 验证失败: {request.method} {request.url.path}")
        return JSONResponse(
            status_code=403,
            content={"error": "CSRF token 验证失败"},
        )

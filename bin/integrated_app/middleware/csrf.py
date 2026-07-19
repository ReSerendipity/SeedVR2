#!/usr/bin/env python3
"""SeedVR2 工具箱 - CSRF 保护中间件"""
import logging
import re
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# GET 请求中安全跳过 CSRF 的路径模式（SSE 进度推送、批量进度、文件夹扫描）
_SAFE_GET_PATH_PATTERNS = (
    re.compile(r"^/api/restore/[^/]+/progress$"),       # /api/restore/{task_id}/progress
    re.compile(r"^/api/restore/batch/[^/]+/progress$"),  # /api/restore/batch/{batch_id}/progress
    re.compile(r"^/api/restore/scan-folder$"),            # /api/restore/scan-folder
)


class CSRFMiddleware(BaseHTTPMiddleware):
    """CSRF 保护中间件

    - GET/HEAD/OPTIONS 请求：自动设置 CSRF token cookie
    - POST/PUT/DELETE 等请求：验证 cookie 与 header 中的 token 是否匹配
    - API 端点现在需要 CSRF token（不再跳过 /api/）
    - 仅对文档路径和静态文件前缀跳过非安全方法的 CSRF 检查
    - GET 请求的 SSE/进度/扫描端点安全放行

    SECURITY 改进 (D3):
    - samesite 从 lax 提升为 strict，彻底阻断跨站请求携带 cookie
    - secure 标志根据请求协议自动启用（HTTPS 或 X-Forwarded-Proto=https）
    - 显式设置 path="/" 确保全路径覆盖
    """

    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    CSRF_COOKIE_NAME = "csrf_token"
    CSRF_HEADER_NAME = "X-CSRF-Token"

    # 仅对非安全方法跳过 CSRF 检查的路径前缀（文档、静态文件）
    SKIP_PATHS = ("/docs", "/openapi.json", "/redoc", "/static/")

    @staticmethod
    def _is_safe_get_path(path: str) -> bool:
        """判断 GET 请求路径是否属于安全的进度/扫描端点"""
        return any(p.match(path) for p in _SAFE_GET_PATH_PATTERNS)

    @staticmethod
    def _is_secure_request(request: Request) -> bool:
        """判断请求是否为 HTTPS（含反向代理场景）

        SECURITY: secure cookie 仅在 HTTPS 下设置，否则浏览器会拒绝。
        支持通过 X-Forwarded-Proto 识别反向代理后的真实协议。
        """
        if request.url.scheme == "https":
            return True
        # 反向代理场景：信任 X-Forwarded-Proto 头
        forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
        return "https" in forwarded_proto

    async def dispatch(self, request: Request, call_next):
        # 为安全方法设置 CSRF token
        if request.method in self.SAFE_METHODS:
            response: Response = await call_next(request)
            if self.CSRF_COOKIE_NAME not in request.cookies:
                token = secrets.token_hex(32)
                # D3: samesite=strict + secure 自动检测 + path=/ 全覆盖
                response.set_cookie(
                    self.CSRF_COOKIE_NAME,
                    token,
                    httponly=False,
                    samesite="strict",
                    secure=self._is_secure_request(request),
                    path="/",
                )
            return response

        # 非安全方法：跳过文档和静态文件路径
        if any(request.url.path.startswith(prefix) for prefix in self.SKIP_PATHS):
            return await call_next(request)

        # 对不安全方法验证 CSRF token
        cookie_token = request.cookies.get(self.CSRF_COOKIE_NAME)
        header_token = request.headers.get(self.CSRF_HEADER_NAME)

        if cookie_token and header_token and secrets.compare_digest(cookie_token, header_token):
            return await call_next(request)

        logger.warning(f"CSRF 验证失败: {request.method} {request.url.path}")
        return JSONResponse(
            status_code=403,
            content={"error": "CSRF token 验证失败"},
        )

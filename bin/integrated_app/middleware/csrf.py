#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2024-2026 ReSerendipity
# SPDX-License-Identifier: Apache-2.0
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

import hashlib
import hmac
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

# 对非安全方法 (POST/PUT/DELETE) 的豁免路径 —— 这些端点本身不涉及敏感操作
# 或使用了其他认证方式，CSRF 攻击无实际危害
_EXEMPT_POST_PATH_PATTERNS = (re.compile(r"^/api/system/locale$"),)  # 语言切换：仅修改用户偏好显示语言


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

    @staticmethod
    def _generate_signed_token() -> str:
        """生成 HMAC 签名的 CSRF token。

        token 格式: nonce.hmac_signature
        - nonce: 32 字节随机数的 hex 表示
        - hmac_signature: HMAC-SHA256(secret_key, nonce) 的 hex 表示

        绑定服务端密钥，攻击者无法伪造合法 token。
        密钥持久化到 data/.seedvr2_secret，重启后仍可验证。

        Returns:
            HMAC 签名的 CSRF token 字符串。
        """
        from bin.integrated_app.security.secret_key import get_secret_key

        secret = get_secret_key()
        nonce = secrets.token_hex(32)
        signature = hmac.new(secret, nonce.encode(), hashlib.sha256).hexdigest()
        return f"{nonce}.{signature}"

    def _set_csrf_cookie(self, response: Response, request: Request) -> None:
        """在响应上补发（或修复）一个有效的 csrf_token cookie。

        关键自愈点：只要请求携带的 cookie 缺失或签名无效，就在响应里重种一个
        有效 token。这样浏览器中残留的「旧/坏」token 会被替换，避免因某个失效
        cookie 存在而永久 403 自锁（正常 GET 只会种一次，不会因误判断跳过修复）。
        """
        token = self._generate_signed_token()
        response.set_cookie(
            self.CSRF_COOKIE_NAME,
            token,
            httponly=False,
            samesite="strict",
            secure=self._is_secure_request(request),
            path="/",
        )

    def _has_valid_cookie(self, request: Request) -> bool:
        """判断请求携带的 csrf_token cookie 是否存在且签名合法。

        Args:
            request: Starlette 请求对象

        Returns:
            bool: cookie 存在且签名有效时返回 True。
        """
        cookie_token = request.cookies.get(self.CSRF_COOKIE_NAME)
        return bool(cookie_token) and self._verify_signed_token(cookie_token)

    @staticmethod
    def _verify_signed_token(token: str) -> bool:
        """验证 HMAC 签名的 CSRF token 是否合法。

        使用常量时间比较防止时序攻击。

        Args:
            token: 待验证的 token 字符串。

        Returns:
            bool: token 签名合法时返回 True。
        """
        from bin.integrated_app.security.secret_key import get_secret_key

        if not token or "." not in token:
            return False
        nonce, signature = token.rsplit(".", 1)
        secret = get_secret_key()
        expected = hmac.new(secret, nonce.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)

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
            if not self._has_valid_cookie(request):
                # cookie 缺失或签名过期时补发有效 token，自愈浏览器里的坏 cookie
                self._set_csrf_cookie(response, request)
            return response

        if any(request.url.path.startswith(prefix) for prefix in self.SKIP_PATHS):
            return await call_next(request)

        # 豁免非安全方法中低风险的端点
        if any(p.match(request.url.path) for p in _EXEMPT_POST_PATH_PATTERNS):
            return await call_next(request)

        cookie_token = request.cookies.get(self.CSRF_COOKIE_NAME)
        header_token = request.headers.get(self.CSRF_HEADER_NAME)

        # 先验证 cookie 中的 token 签名合法（服务端签名）
        if (
            self._has_valid_cookie(request)
            and header_token
            and secrets.compare_digest(cookie_token, header_token)
        ):
            return await call_next(request)

        logger.warning(f"CSRF 验证失败: {request.method} {request.url.path}")
        response = JSONResponse(
            status_code=403,
            content={"error": "CSRF token 验证失败"},
        )
        # 失败也补发有效 token：替换浏览器里的失效 cookie，下一次请求即可自愈
        self._set_csrf_cookie(response, request)
        return response

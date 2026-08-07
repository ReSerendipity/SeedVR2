# SPDX-FileCopyrightText: Copyright (c) 2024-2026 ReSerendipity
# SPDX-License-Identifier: Apache-2.0
"""HTTP Basic Auth 中间件

为 SeedVR2 提供 HTTP Basic Authentication 保护，
防止公网部署时的未授权访问 (CWE-306)。

启用方式 (config.yaml):
    security:
      auth:
        enable: true          # 启用 Basic Auth
        username: admin       # 用户名
        password: 'your-password'  # 明文密码 (建议使用环境变量注入)
        realm: SeedVR2        # WWW-Authenticate realm

安全建议:
    - 仅在 server.host 非 127.0.0.1 时启用 (公网/局域网部署)
    - 密码应通过环境变量 SEEDVR2_AUTH_PASSWORD 注入，避免明文存配置
    - 生产环境建议配合 HTTPS 使用 (Basic Auth 明文传输 Base64)
    - 静态资源 (CSS/JS/图片) 也受保护，浏览器会缓存凭据
"""

import base64
import hashlib
import hmac
import logging
import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """HTTP Basic Auth 中间件

    在 FastAPI 应用上注册后，所有请求需携带正确的
    Authorization: Basic <base64(username:password)> 头。

    安全特性:
        - 使用 hmac.compare_digest 常量时间比较，防止时序攻击
        - 密码可通过环境变量 SEEDVR2_AUTH_PASSWORD 覆盖配置文件值
        - 401 响应包含 WWW-Authenticate 头，触发浏览器凭据对话框
    """

    def __init__(self, app, username: str, password: str, realm: str = "SeedVR2"):
        """初始化 Basic Auth 中间件。

        Args:
            app: ASGI 应用实例。
            username: 允许访问的用户名。
            password: 允许访问的密码。
            realm: WWW-Authenticate realm 值，用于浏览器对话框标题。
        """
        super().__init__(app)
        self._username = username
        # 环境变量优先级高于配置文件 (避免密码明文存配置)
        self._password = os.environ.get("SEEDVR2_AUTH_PASSWORD", password)
        self._realm = realm
        # 预计算期望的 Authorization 头值 (常量时间比较的基准)
        expected = f"{username}:{self._password}"
        self._expected_b64 = base64.b64encode(expected.encode("utf-8")).decode("ascii")
        logger.info(f"Basic Auth 已启用 (realm={realm}, user={username})")

    async def dispatch(self, request: Request, call_next):
        """中间件分发方法，验证每个请求的 Authorization 头。

        Args:
            request: Starlette 请求对象。
            call_next: 下一个中间件/路由处理函数。

        Returns:
            Response: 验证通过则继续处理，否则返回 401 Unauthorized。
        """
        # 提取 Authorization 头
        auth_header = request.headers.get("Authorization", "")

        if auth_header.startswith("Basic "):
            # 提取 Base64 编码的凭据
            provided_b64 = auth_header[6:]
            # 常量时间比较，防止时序攻击
            if hmac.compare_digest(provided_b64, self._expected_b64):
                return await call_next(request)

        # 验证失败，返回 401
        logger.warning(f"未授权访问: {request.method} {request.url.path} from {request.client.host if request.client else 'unknown'}")
        return Response(
            content="401 Unauthorized\n\nSeedVR2 requires authentication.",
            status_code=401,
            headers={"WWW-Authenticate": f'Basic realm="{self._realm}"'},
            media_type="text/plain",
        )


def should_enable_auth(config: dict) -> bool:
    """根据配置判断是否应启用 Basic Auth。

    启用条件:
        1. config.security.auth.enable == True
        2. 用户名和密码均非空

    Args:
        config: 应用配置字典。

    Returns:
        bool: True 表示应启用 Basic Auth。
    """
    auth_cfg = config.get("security", {}).get("auth", {})
    if not auth_cfg.get("enable", False):
        return False

    username = auth_cfg.get("username", "")
    # 环境变量优先
    password = os.environ.get("SEEDVR2_AUTH_PASSWORD", auth_cfg.get("password", ""))

    if not username or not password:
        logger.warning("Basic Auth 已配置 enable=true 但用户名或密码为空，跳过启用")
        return False

    return True


def create_auth_middleware(config: dict):
    """根据配置创建 BasicAuthMiddleware 实例（工厂函数）。

    Args:
        config: 应用配置字典。

    Returns:
        BasicAuthMiddleware | None: 配置启用时返回中间件类，否则 None。
    """
    if not should_enable_auth(config):
        return None

    auth_cfg = config.get("security", {}).get("auth", {})
    return BasicAuthMiddleware(
        app=None,  # 由 add_middleware 填充
        username=auth_cfg.get("username", "admin"),
        password=os.environ.get("SEEDVR2_AUTH_PASSWORD", auth_cfg.get("password", "")),
        realm=auth_cfg.get("realm", "SeedVR2"),
    )

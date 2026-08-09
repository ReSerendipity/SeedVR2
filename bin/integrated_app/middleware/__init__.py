#!/usr/bin/env python3
"""SeedVR2 - FastAPI/Starlette 中间件包。

本模块包含应用级 HTTP 中间件，按职责分层处理请求与响应：

- CSRFMiddleware: 跨站请求伪造保护，基于 Double Submit Cookie 模式实现
- ErrorHandler: 全局异常捕获与统一 JSON 响应格式化，区分普通 API 与 HTMX 请求

中间件按注册顺序执行，CSRF 保护优先于异常处理，确保所有写操作经过安全校验。
"""

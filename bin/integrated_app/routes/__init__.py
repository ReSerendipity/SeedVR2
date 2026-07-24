#!/usr/bin/env python3
"""Klar - 路由注册与自动发现"""
import importlib
import logging

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger(__name__)

# 路由模块注册表：(模块路径, URL 前缀, 标签)
ROUTE_MODULES = [
    ("bin.integrated_app.routes.restore.unified", "/api/restore", "修复"),
    ("bin.integrated_app.routes.system.health", "/api/system", "系统状态"),
    ("bin.integrated_app.routes.system.gpu", "/api/system", "GPU信息"),
    ("bin.integrated_app.routes.system.settings", "/api/system", "设置"),
    ("bin.integrated_app.routes.system.history", "/api/system", "历史记录"),
    ("bin.integrated_app.routes.system.sse", "", "SSE事件流"),
    ("bin.integrated_app.routes.ui.parameters", "/api/ui", "UI参数与偏好"),
]


def auto_discover_routes(app: FastAPI):
    """自动发现并注册所有路由模块"""
    for module_path, prefix, tag in ROUTE_MODULES:
        try:
            module = importlib.import_module(module_path)
            router = getattr(module, "router", None)
            if router is not None:
                app.include_router(router, prefix=prefix, tags=[tag])
                logger.info(f"已注册路由: {prefix} [{tag}]")
            else:
                logger.warning(f"模块 {module_path} 没有 router 对象")
        except ImportError as e:
            logger.warning(f"无法导入路由模块 {module_path}: {e}")
        except Exception as e:
            logger.error(f"注册路由失败 {module_path}: {e}")


def _render_template(request: Request, template_name: str, context: dict = None) -> HTMLResponse:
    """使用 Jinja2 Environment 渲染模板"""
    env = request.app.state.jinja_env
    template = env.get_template(template_name)
    i18n = request.app.state.i18n
    ctx = {
        "request": request,
        "t": i18n.t,  # 注入翻译函数到模板
    }
    if context:
        ctx.update(context)
    html = template.render(**ctx)
    return HTMLResponse(content=html)


def render_page(request: Request, template_name: str, active_page: str = "", **ctx) -> HTMLResponse:
    """渲染页面模板，自动注入 active_page、current_locale、locale_name、locales、t 等通用上下文"""
    i18n = request.app.state.i18n
    locales = [{"code": code, "name": i18n.get_locale_name(code)} for code in i18n.available_locales]
    page_ctx = {
        "request": request,
        "t": i18n.t,
        "active_page": active_page,
        "current_locale": i18n.current_locale,
        "locale_name": i18n.get_locale_name(i18n.current_locale),
        "locales": locales,
    }
    page_ctx.update(ctx)

    env = request.app.state.jinja_env
    template = env.get_template(template_name)
    html = template.render(**page_ctx)
    return HTMLResponse(content=html)


def register_page_routes(app: FastAPI):
    """注册页面路由"""

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return render_page(request, "index.html", active_page="index")

    @app.get("/restore", response_class=HTMLResponse)
    async def restore_page(request: Request):
        return render_page(request, "restore.html", active_page="restore")

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        return render_page(request, "settings.html", active_page="settings")

    @app.get("/history", response_class=HTMLResponse)
    async def history_page(request: Request):
        return render_page(request, "history.html", active_page="history")

    @app.get("/system-status", response_class=HTMLResponse)
    async def system_status_page(request: Request):
        # 系统状态已并入首页，保留路由做兼容重定向
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/", status_code=302)

    # 404 catch-all route
    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        """Handle 404 errors by redirecting to home or showing error page"""
        # For API routes, return JSON
        if request.url.path.startswith("/api/"):
            return JSONResponse(
                status_code=404,
                content={"error": "API endpoint not found", "path": request.url.path}
            )
        # For page routes, redirect to home
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/", status_code=302)

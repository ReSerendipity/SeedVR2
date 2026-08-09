#!/usr/bin/env python3
"""SeedVR2 路由注册与模板渲染模块。

本模块负责：
- 自动发现并注册所有 API 路由模块（修复、系统、UI）
- 提供 Jinja2 模板渲染工具函数
- 注册页面路由（首页、修复页、设置页、历史页等）
- 处理 404 错误响应

所属项目：SeedVR2 (SeedVR2 视频/图像修复工具)
API 路由前缀：
- /api/restore: 修复相关 API
- /api/system: 系统状态相关 API
- /api/ui: UI 参数与偏好 API
- /api/sse/events: SSE 事件流端点
页面路由：/, /restore, /settings, /history
"""

import importlib
import logging
import pkgutil
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger(__name__)


def _auto_discover_routers(routes_package: Any, prefix: str = "") -> list[Any]:
    """递归发现并收集路由包中所有带有 router 属性的模块。

    使用 pkgutil.iter_modules 遍历当前包下的所有模块和子包。
    每个模块如果有 router 属性（即 APIRouter 实例），则加入列表。
    子包会递归进入扫描。

    Args:
        routes_package: 要扫描的路由包（必须有 __path__ 属性）。
        prefix: 当前导入前缀（用于嵌套包的递归调用）。

    Returns:
        发现的 APIRouter 实例列表。
    """
    routers: list[Any] = []
    if not hasattr(routes_package, "__path__"):
        return routers

    for _importer, modname, ispkg in pkgutil.iter_modules(routes_package.__path__):
        full_name = f"{routes_package.__name__}.{modname}"
        try:
            mod = importlib.import_module(full_name)
            if hasattr(mod, "router"):
                routers.append(mod.router)
                prefix_info = getattr(mod.router, "prefix", "")
                logger.info(f"自动发现路由: {full_name} (prefix={prefix_info})")
        except Exception as e:
            logger.warning(f"导入路由模块失败 {full_name}: {e}")

        if ispkg:
            try:
                subpkg = importlib.import_module(full_name)
                routers.extend(_auto_discover_routers(subpkg))
            except Exception as e:
                logger.warning(f"递归扫描子包失败 {full_name}: {e}")

    return routers


def auto_discover_routes(app: FastAPI):
    """自动发现并注册所有路由模块。

    使用 pkgutil 递归扫描 routes 包下的所有模块，
    发现带有 router 属性的模块并注册到 FastAPI 应用。
    新增路由文件只需放入 routes/ 目录（或子目录）并定义 router = APIRouter(...)，
    无需修改任何其他代码即可自动生效。

    Args:
        app: FastAPI 应用实例，路由将被注册到此应用。
    """
    from bin.integrated_app import routes as routes_pkg

    discovered_routers = _auto_discover_routers(routes_pkg)
    for router in discovered_routers:
        app.include_router(router)

    logger.info(f"自动发现并注册 {len(discovered_routers)} 个路由模块")


def _render_template(request: Request, template_name: str, context: dict | None = None) -> HTMLResponse:
    """使用 Jinja2 Environment 渲染模板（内部工具函数）。

    Args:
        request: FastAPI 请求对象，用于获取 app.state 中的 jinja_env 和 i18n。
        template_name: Jinja2 模板文件名（相对于 templates 目录）。
        context: 模板上下文变量字典，可选。

    Returns:
        渲染后的 HTML 响应。
    """
    env = request.app.state.jinja_env
    template = env.get_template(template_name)
    i18n = request.app.state.i18n
    ctx = {
        "request": request,
        "t": i18n.t,
    }
    if context:
        ctx.update(context)
    html = template.render(**ctx)
    return HTMLResponse(content=html)


def render_page(request: Request, template_name: str, active_page: str = "", **ctx) -> HTMLResponse:
    """渲染页面模板，自动注入通用上下文变量。

    自动注入的上下文变量包括：
    - request: 请求对象
    - t: 国际化翻译函数
    - active_page: 当前激活页面标识
    - current_locale: 当前语言代码
    - locale_name: 当前语言名称
    - locales: 可用语言列表

    Args:
        request: FastAPI 请求对象。
        template_name: Jinja2 模板文件名。
        active_page: 当前激活页面标识，用于导航栏高亮。
        **ctx: 额外的模板上下文变量。

    Returns:
        渲染后的 HTML 响应。
    """
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
    """注册所有页面路由。

    注册的页面路由包括：
    - GET /: 首页/修复页
    - GET /restore: 修复页
    - GET /settings: 设置页
    - GET /history: 历史记录页
    - GET /system-status: 系统状态页（重定向到首页）
    以及 Vite 开发服务器相关的占位路由（用于生产环境屏蔽）和 404 处理。

    Args:
        app: FastAPI 应用实例。

    Returns:
        None
    """

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        """GET / - 首页/修复页面。

        Args:
            request: FastAPI 请求对象。

        Returns:
            渲染后的 index.html 页面。
        """
        return render_page(request, "index.html", active_page="index")

    @app.get("/restore", response_class=HTMLResponse)
    async def restore_page(request: Request):
        """GET /restore - 修复页面。

        Args:
            request: FastAPI 请求对象。

        Returns:
            渲染后的 restore.html 页面。
        """
        return render_page(request, "restore.html", active_page="restore")

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        """GET /settings - 设置页面。

        Args:
            request: FastAPI 请求对象。

        Returns:
            渲染后的 settings.html 页面。
        """
        return render_page(request, "settings.html", active_page="settings")

    @app.get("/history", response_class=HTMLResponse)
    async def history_page(request: Request):
        """GET /history - 历史记录页面。

        Args:
            request: FastAPI 请求对象。

        Returns:
            渲染后的 history.html 页面。
        """
        return render_page(request, "history.html", active_page="history")

    @app.get("/system-status", response_class=HTMLResponse)
    async def system_status_page(request: Request):
        """GET /system-status - 系统状态页面。

        显示独立的系统状态监控页面，包含GPU信息、模型状态、内存使用、运行时间等。

        Args:
            request: FastAPI 请求对象。

        Returns:
            渲染后的 system_status.html 页面。
        """
        return render_page(request, "system_status.html", active_page="system")

    from fastapi.responses import Response as EmptyResponse

    @app.api_route("/@vite/client", methods=["GET", "HEAD", "POST"])
    async def vite_client():
        """Vite HMR 客户端占位路由（生产环境屏蔽）。

        Returns:
            204 No Content 响应。
        """
        return EmptyResponse(status_code=204)

    @app.api_route("/@vite/{path:path}", methods=["GET", "HEAD", "POST"])
    async def vite_all(path: str):
        """Vite 开发服务器资源占位路由（生产环境屏蔽）。

        Args:
            path: Vite 资源路径。

        Returns:
            204 No Content 响应。
        """
        return EmptyResponse(status_code=204)

    @app.api_route("/__vite_ping", methods=["GET", "HEAD"])
    async def vite_ping():
        """Vite 健康检查占位路由（生产环境屏蔽）。

        Returns:
            204 No Content 响应。
        """
        return EmptyResponse(status_code=204)

    @app.api_route("/@react-refresh", methods=["GET", "HEAD"])
    async def react_refresh():
        """React Refresh 占位路由（生产环境屏蔽）。

        Returns:
            204 No Content 响应。
        """
        return EmptyResponse(status_code=204)

    @app.api_route("/.well-known/appspecific/com.chrome.devtools.json", methods=["GET"])
    async def chrome_devtools():
        """Chrome DevTools 配置文件占位路由。

        Returns:
            204 No Content 响应。
        """
        return EmptyResponse(status_code=204)

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        """404 错误处理器。

        对于 API 路由（/api/ 开头）返回 JSON 格式的 404 响应；
        对于页面路由重定向到首页。

        Args:
            request: FastAPI 请求对象。
            exc: 异常对象。

        Returns:
            API 请求返回 JSON 错误响应；页面请求返回重定向响应。
        """
        if request.url.path.startswith("/api/"):
            return JSONResponse(status_code=404, content={"error": "API endpoint not found", "path": request.url.path})
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url="/", status_code=302)

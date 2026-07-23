#!/usr/bin/env python3
"""Klar - 应用服务器入口"""
import asyncio
import logging
import os
import sys
import webbrowser
from contextlib import asynccontextmanager

# 修复 Windows 上 OMP 库重复加载问题（numpy 和 torch 各自带一份 libiomp5md.dll）
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

# 在 torch 导入前设置 CUDA 内存分配器，启用 expandable_segments 避免显存碎片化 OOM
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")

# 确保项目根目录在路径中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.responses import Response  # noqa: E402

from bin.integrated_app.cache import FileCache  # noqa: E402
from bin.integrated_app.config import load_config  # noqa: E402
from bin.integrated_app.gpu_backend import gpu_manager  # noqa: E402
from bin.integrated_app.history_db import HistoryDB  # noqa: E402
from bin.integrated_app.i18n import I18n  # noqa: E402
from bin.integrated_app.middleware.csrf import CSRFMiddleware  # noqa: E402
from bin.integrated_app.model_manager import ModelManager  # noqa: E402
from bin.integrated_app.model_registry import model_registry  # noqa: E402
from bin.integrated_app.routes.system.sse import event_bus  # noqa: E402
from bin.integrated_app.task_queue import TaskQueue  # noqa: E402

logger = logging.getLogger(__name__)


def _bridge_model_status_to_sse(event_name: str, payload: dict) -> None:
    """将 model_registry 状态变更桥接到 SSE 事件总线 (B5)

    作为 model_registry 的观察者监听器，在模型状态变更时通过 event_bus 广播，
    使 SSE 客户端能实时收到 model_status 事件。
    解耦 model_registry 与 event_bus 的直接依赖（观察者模式）。
    """
    event_bus.publish(event_name, payload)


class VersionedStaticFiles(StaticFiles):
    """带版本控制的静态文件处理

    为 .css 和 .js 文件添加长期缓存头，配合 base.html 中的查询字符串版本号
    实现静态资源更新后客户端强制刷新。
    """

    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        if self.directory and args and str(args[0]).endswith((".css", ".js")):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # ---- Startup ----
    config = app.state.config

    # 初始化数据库
    history_db: HistoryDB = app.state.history_db
    await history_db.initialize()
    logger.info("历史数据库已初始化")

    # 启动任务队列
    task_queue: TaskQueue = app.state.task_queue
    await task_queue.start()
    logger.info("任务队列已启动")

    # B5: 注册 model_registry → SSE event_bus 桥接监听器
    # model_registry 状态变更时自动通过 event_bus 广播 model_status 事件，
    # 替代原 model_registry 直接 import event_bus 的耦合方式
    model_registry.add_listener(_bridge_model_status_to_sse)
    logger.info("已注册模型状态 SSE 桥接监听器")

    # 恢复数据库中未完成的任务
    try:
        from bin.integrated_app.routes.restore import unified as unified_routes
        recovered_count = await unified_routes.recover_tasks(history_db, task_queue, config)
        if recovered_count:
            logger.info(f"已从数据库恢复 {recovered_count} 个未完成任务")
    except Exception as e:
        logger.warning(f"恢复未完成任务失败: {e}")

    # 启动缓存清理任务
    file_cache: FileCache = app.state.file_cache
    file_cache.start_cleanup_task(interval=3600)

    # GPU 后端在模块导入时已自动检测
    backend_value = gpu_manager.backend.value if gpu_manager.backend else 'unavailable'
    logger.info(f"GPU 后端: {backend_value}, 设备: {gpu_manager.device_name}")

    # 后台模型预加载（仅在有 GPU 时执行）
    if gpu_manager.is_gpu_available and config.get("model", {}).get("auto_load", True):
        try:
            model_manager: ModelManager = app.state.model_manager
            await model_manager.load_model()
            logger.info("模型自动加载完成")
        except Exception as e:
            logger.warning(f"自动加载模型失败: {e}")
    elif not gpu_manager.is_gpu_available:
        logger.warning("未检测到 NVIDIA GPU，跳过模型自动加载（降级模式）")

    # 自动打开浏览器
    host = config.get("server", {}).get("host", "127.0.0.1")
    port = config.get("server", {}).get("port", 7870)
    if config.get("server", {}).get("auto_open_browser", True):
        url = f"http://{host}:{port}"
        asyncio.get_event_loop().call_later(1.5, lambda: webbrowser.open(url))
        logger.info(f"将在浏览器中打开: {url}")

    logger.info(f"Klar已启动: http://{host}:{port}")

    yield

    # ---- Shutdown ----
    # I4: 优雅关闭 — 移除监听器、停止后台任务、等待资源释放

    # B5: 移除 model_registry 监听器，避免关闭过程中触发无效通知
    model_registry.remove_listener(_bridge_model_status_to_sse)

    # 停止缓存清理任务
    file_cache.stop_cleanup_task()

    # 停止任务队列（优雅关闭，最多等待 30 秒）
    # I4: 设置超时防止卡死的任务阻塞关闭流程，uvicorn SIGTERM 后强制退出
    task_queue: TaskQueue = app.state.task_queue
    try:
        await asyncio.wait_for(task_queue.stop(), timeout=30.0)
        logger.info("任务队列已优雅停止")
    except asyncio.TimeoutError:
        logger.warning("任务队列停止超时（30s），强制退出")

    # 卸载模型
    model_manager = app.state.model_manager
    await model_manager.unload_model()

    # 关闭数据库连接
    history_db = app.state.history_db
    await history_db.close()

    logger.info("Klar已关闭")


def create_app(config: dict = None) -> FastAPI:
    """创建 FastAPI 应用实例"""
    if config is None:
        config = load_config()

    app = FastAPI(
        title="Klar",
        description="Klar - AI-powered video & image super-resolution toolkit",
        version="1.0.0",
        lifespan=lifespan,
    )

    # ---- 中间件 ----
    # CORS
    allowed_origins = config.get("server", {}).get(
        "allowed_origins", ["http://127.0.0.1:7870", "http://localhost:7870"]
    )
    # 当 origins 为通配符 "*" 时，不允许 credentials（浏览器安全策略）
    allow_credentials = "*" not in allowed_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # CSRF 保护
    app.add_middleware(CSRFMiddleware)

    # 注册全局异常处理器
    from bin.integrated_app.middleware.error_handler import register_error_handlers
    register_error_handlers(app)

    # ---- 初始化核心组件 ----
    app.state.config = config
    app.state.model_manager = ModelManager(config)
    app.state.gpu_backend = gpu_manager
    app.state.history_db = HistoryDB(
        db_path=config.get("history", {}).get("db_path", "data/history.db"),
    )
    # F1: TaskQueue 参数从 config.runtime.task 注入，替代硬编码默认值
    _runtime_task_cfg = config.get("runtime", {}).get("task", {})
    app.state.task_queue = TaskQueue(
        maxsize=_runtime_task_cfg.get("queue_maxsize", 100),
        task_timeout_seconds=_runtime_task_cfg.get("max_timeout_seconds", 3600),
    )
    # 注册 SSE 事件总线到 app.state，供 get_event_bus 依赖注入使用
    app.state.event_bus = event_bus
    app.state.i18n = I18n(
        locales_dir=os.path.join(os.path.dirname(__file__), "locales"),
        default_locale=config.get("i18n", {}).get("default_locale", "zh"),
    )
    app.state.file_cache = FileCache(
        cache_dir="data/uploads",
        ttl=config.get("cache", {}).get("ttl", 86400),
    )

    # ---- 静态文件和模板 ----
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    templates_dir = os.path.join(os.path.dirname(__file__), "templates")

    if os.path.exists(static_dir):
        app.mount("/static", VersionedStaticFiles(directory=static_dir), name="static")

    # 使用 Jinja2 Environment 直接创建，避免 Starlette 1.0 兼容性问题
    import jinja2
    if os.path.exists(templates_dir):
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(templates_dir),
            autoescape=jinja2.select_autoescape(["html", "xml"]),
        )
        app.state.jinja_env = env
    else:
        logger.warning(f"模板目录不存在: {templates_dir}")
        os.makedirs(templates_dir, exist_ok=True)
        app.state.jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(templates_dir),
            autoescape=jinja2.select_autoescape(["html", "xml"]),
        )

    # ---- 注册路由 ----
    from bin.integrated_app.routes import auto_discover_routes, register_page_routes

    # 自动发现并注册 API 路由
    auto_discover_routes(app)

    # 注册页面路由
    register_page_routes(app)

    return app


def _kill_port_process(port: int) -> bool:
    """尝试终止占用指定端口的进程（仅 Windows）"""
    import subprocess
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                pid = int(parts[-1])
                logger.warning(f"端口 {port} 被进程 PID={pid} 占用，尝试终止...")
                subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                               capture_output=True, timeout=5)
                import time
                time.sleep(1)
                return True
    except Exception as e:
        logger.warning(f"终止端口占用进程失败: {e}")
    return False


def main():
    """启动 FastAPI 应用服务器"""
    import uvicorn

    config = load_config()
    app = create_app(config)

    log_level = config.get("logging", {}).get("level", "INFO")
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    host = config.get("server", {}).get("host", "127.0.0.1")
    port = config.get("server", {}).get("port", 7870)
    debug = config.get("server", {}).get("debug", False)

    logger.info(f"Klar启动中... http://{host}:{port}")
    try:
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level=log_level.lower(),
            reload=debug,
        )
    except OSError as e:
        if "10048" in str(e) or "already in use" in str(e).lower():
            logger.warning(f"端口 {port} 已被占用，尝试自动终止占用进程...")
            if _kill_port_process(port):
                logger.info(f"端口 {port} 已释放，重新启动服务器...")
                uvicorn.run(
                    app,
                    host=host,
                    port=port,
                    log_level=log_level.lower(),
                    reload=debug,
                )
            else:
                logger.error(f"无法释放端口 {port}，请手动终止占用进程后重试")
                raise
        else:
            raise


if __name__ == "__main__":
    main()

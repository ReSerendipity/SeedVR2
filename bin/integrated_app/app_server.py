#!/usr/bin/env python3
"""
SeedVR2 - 应用服务器入口模块

所属项目：SeedVR2 (AI-powered video & image super-resolution toolkit)
核心功能：
    - FastAPI 应用创建与配置
    - 应用生命周期管理（启动初始化、优雅关闭）
    - 核心组件初始化与依赖注入
    - 中间件注册（CORS、CSRF、错误处理）
    - 静态文件服务与模板引擎配置
    - 路由自动发现与注册
    - 端口冲突自动处理与服务器启动

核心技术栈：
    - FastAPI 0.100+ 作为 Web 框架
    - Uvicorn 作为 ASGI 服务器
    - Pydantic 用于配置验证
    - Jinja2 用于模板渲染
    - 观察者模式实现模型状态到 SSE 的桥接
"""

import asyncio
import logging
import os
import sys
import webbrowser
from contextlib import asynccontextmanager

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")


os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")


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
    """将 model_registry 状态变更桥接到 SSE 事件总线。

    作为 model_registry 的观察者监听器，在模型状态变更时通过 event_bus 广播，
    使 SSE 客户端能实时收到 model_status 事件。
    使用观察者模式解耦 model_registry 与 event_bus 的直接依赖。

    Args:
        event_name: 事件名称，如 'model_loading'、'model_loaded'、'model_unloaded'。
        payload: 事件数据字典，包含模型状态详情。
    """
    event_bus.publish(event_name, payload)


class VersionedStaticFiles(StaticFiles):
    """带版本控制的静态文件处理类。

    继承自 FastAPI StaticFiles，为不同类型的静态资源设置差异化的 Cache-Control 头：
    - CSS/JS 文件：长期缓存（1年）+ immutable，配合查询字符串版本号实现强缓存
    - 字体文件（woff2/woff/ttf/eot/otf）：中期缓存（30天）
    - 图片资源（png/jpg/jpeg/gif/svg/ico/webp）：短期缓存（1天）

    缓存策略说明：
        前端模板 base.html 中为静态资源添加版本号查询参数（如 ?v=xxx），
        当静态文件更新时版本号变化，客户端会自动请求新版本，无需担心缓存过期。
    """

    def file_response(self, *args, **kwargs) -> Response:
        """重写 file_response 方法，为不同文件类型添加缓存头。

        Args:
            *args: 位置参数，第一个参数为文件路径。
            **kwargs: 关键字参数。

        Returns:
            Response: 添加了 Cache-Control 头的 HTTP 响应。
        """
        response = super().file_response(*args, **kwargs)
        if args:
            file_path = str(args[0])
            if file_path.endswith((".css", ".js")):
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            elif file_path.endswith((".woff2", ".woff", ".ttf", ".eot", ".otf")):
                response.headers["Cache-Control"] = "public, max-age=2592000"
            elif file_path.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp")):
                response.headers["Cache-Control"] = "public, max-age=86400"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 应用生命周期管理上下文管理器。

    处理应用启动和关闭时的资源初始化与清理：

    启动阶段（yield 前）：
        1. 初始化历史记录数据库
        2. 启动异步任务队列
        3. 注册模型状态到 SSE 的桥接监听器
        4. 恢复数据库中未完成的任务
        5. 启动缓存定期清理任务
        6. 检测 GPU 后端与兼容性
        7. 可选自动加载模型（GPU 可用且配置启用时）
        8. 可选自动打开浏览器访问应用

    关闭阶段（yield 后）：
        1. 移除模型状态监听器
        2. 停止缓存清理任务
        3. 优雅停止任务队列（最多等待30秒）
        4. 卸载模型释放 GPU 显存
        5. 关闭数据库连接

    Args:
        app: FastAPI 应用实例，通过 app.state 访问已初始化的组件。

    Yields:
        None:  yield 点分隔启动和关闭阶段，应用在此期间运行。
    """
    config = app.state.config

    history_db: HistoryDB = app.state.history_db
    await history_db.initialize()
    logger.info("历史数据库已初始化")

    task_queue: TaskQueue = app.state.task_queue
    await task_queue.start()
    logger.info("任务队列已启动")

    model_registry.add_listener(_bridge_model_status_to_sse)
    logger.info("已注册模型状态 SSE 桥接监听器")

    try:
        from bin.integrated_app.routes.restore import unified as unified_routes

        auto_recover = config.get("runtime", {}).get("task", {}).get("auto_recover", False)
        if auto_recover:
            recovered_count = await unified_routes.recover_tasks(history_db, task_queue, config)
            if recovered_count:
                logger.info(f"已从数据库恢复 {recovered_count} 个未完成任务")
        else:
            logger.info("启动任务自动恢复已关闭 (runtime.task.auto_recover=false)")
    except Exception as e:
        logger.warning(f"恢复未完成任务失败: {e}")

    file_cache: FileCache = app.state.file_cache
    file_cache.start_cleanup_task(interval=3600)

    backend_value = gpu_manager.backend.value if gpu_manager.backend else "unavailable"
    logger.info(f"GPU 后端: {backend_value}, 设备: {gpu_manager.device_name}")

    if gpu_manager.is_gpu_available and config.get("model", {}).get("auto_load", True):
        try:
            model_manager: ModelManager = app.state.model_manager
            await model_manager.load_model()
            logger.info("模型自动加载完成")
        except Exception as e:
            logger.warning(f"自动加载模型失败: {e}")
    elif not gpu_manager.is_gpu_available:
        logger.warning("未检测到 NVIDIA GPU，跳过模型自动加载（降级模式）")

    host = config.get("server", {}).get("host", "127.0.0.1")
    port = config.get("server", {}).get("port", 7870)
    if config.get("server", {}).get("auto_open_browser", True):
        url = f"http://{host}:{port}"
        asyncio.get_running_loop().call_later(1.5, lambda: webbrowser.open(url))
        logger.info(f"将在浏览器中打开: {url}")

    logger.info(f"SeedVR2已启动: http://{host}:{port}")

    yield

    model_registry.remove_listener(_bridge_model_status_to_sse)

    file_cache.stop_cleanup_task()

    task_queue = app.state.task_queue
    try:
        await asyncio.wait_for(task_queue.stop(), timeout=30.0)
        logger.info("任务队列已优雅停止")
    except TimeoutError:
        logger.warning("任务队列停止超时（30s），强制退出")

    model_manager = app.state.model_manager
    await model_manager.unload_model()

    history_db = app.state.history_db
    await history_db.close()

    logger.info("SeedVR2已关闭")


def create_app(config: dict | None = None) -> FastAPI:
    """创建并配置 FastAPI 应用实例。

    完整的应用构建流程：
    1. 加载配置（未提供时从 config.yaml 加载）
    2. 创建 FastAPI 实例，配置标题、描述、版本和生命周期
    3. 注册中间件（CORS、CSRF、全局错误处理）
    4. 初始化所有核心组件并挂载到 app.state：
       - config: 应用配置字典
       - model_manager: 模型加载/卸载/切换管理器
       - gpu_backend: GPU 后端管理器
       - history_db: SQLite 历史记录数据库
       - task_queue: 单 worker 异步任务队列
       - event_bus: SSE 事件总线
       - i18n: 国际化支持
       - file_cache: 上传文件缓存
       - jinja_env: Jinja2 模板环境
    5. 挂载版本化静态文件目录
    6. 自动发现并注册所有 API 路由和页面路由
    7. 可选初始化多引擎调度器和专用引擎

    Args:
        config: 应用配置字典，为 None 时自动从 config.yaml 加载。

    Returns:
        FastAPI: 配置完成的 FastAPI 应用实例，可直接传入 uvicorn.run()。
    """
    if config is None:
        config = load_config()

    app = FastAPI(
        title="SeedVR2",
        description="SeedVR2 - AI-powered video & image super-resolution toolkit",
        version="1.0.0",
        lifespan=lifespan,
    )

    allowed_origins = config.get("server", {}).get(
        "allowed_origins", ["http://127.0.0.1:7870", "http://localhost:7870"]
    )
    allow_credentials = "*" not in allowed_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(CSRFMiddleware)

    from bin.integrated_app.middleware.error_handler import register_error_handlers

    register_error_handlers(app)

    app.state.config = config
    app.state.model_manager = ModelManager(config)
    app.state.gpu_backend = gpu_manager
    app.state.history_db = HistoryDB(
        db_path=config.get("history", {}).get("db_path", "data/history.db"),
    )
    _runtime_task_cfg = config.get("runtime", {}).get("task", {})
    app.state.task_queue = TaskQueue(
        maxsize=_runtime_task_cfg.get("queue_maxsize", 100),
        task_timeout_seconds=_runtime_task_cfg.get("max_timeout_seconds", 3600),
    )
    app.state.event_bus = event_bus
    app.state.i18n = I18n(
        locales_dir=os.path.join(os.path.dirname(__file__), "locales"),
        default_locale=config.get("i18n", {}).get("default_locale", "zh"),
    )
    app.state.file_cache = FileCache(
        cache_dir="data/uploads",
        ttl=config.get("cache", {}).get("ttl", 86400),
    )

    static_dir = os.path.join(os.path.dirname(__file__), "static")
    templates_dir = os.path.join(os.path.dirname(__file__), "templates")

    if os.path.exists(static_dir):
        app.mount("/static", VersionedStaticFiles(directory=static_dir), name="static")

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

    from bin.integrated_app.routes import auto_discover_routes, register_page_routes

    auto_discover_routes(app)

    register_page_routes(app)

    try:
        from bin.integrated_app.optimization.engine.engine_scheduler import EngineScheduler

        _engine_scheduler = EngineScheduler()
        logger.info("Engine Scheduler initialized")
    except Exception as e:
        _engine_scheduler = None
        logger.debug(f"Engine Scheduler not available: {e}")

    if _engine_scheduler is not None:
        from fastapi import APIRouter

        engine_router = APIRouter(prefix="/api/engine", tags=["engine"])

        @engine_router.get("/list")
        async def list_engines():
            """列出所有已注册的推理引擎。

            Returns:
                dict: 统一响应格式，包含所有引擎名称列表和当前可用引擎列表。
            """
            from bin.integrated_app.optimization.engine.engine_scheduler import EngineRegistry

            all_engines = EngineRegistry.get_all_registered()
            available_engines = EngineRegistry.get_available_engines()
            return {
                "success": True,
                "data": {
                    "engines": list(all_engines.keys()),
                    "available": available_engines,
                },
            }

        @engine_router.get("/detect")
        async def detect_engines():
            """检测所有推理引擎的可用性状态。

            Returns:
                dict: 统一响应格式，包含各引擎名称到可用性状态的映射。

            Raises:
                Exception: 检测过程出错时返回错误信息。
            """
            try:
                status = _engine_scheduler.detect_available_engines()
                return {"success": True, "data": {k: v.value for k, v in status.items()}}
            except Exception as e:
                return {"success": False, "error": str(e)}

        @engine_router.post("/submit")
        async def submit_task(
            engine_name: str | None = None,
            input_path: str = "",
            output_path: str = "",
        ):
            """向指定引擎提交推理任务。

            Args:
                engine_name: 引擎名称，为 None 时自动选择。
                input_path: 输入文件路径。
                output_path: 输出文件路径。

            Returns:
                dict: 统一响应格式，成功时包含 task_id，失败时包含错误信息。

            Raises:
                Exception: 任务提交失败时返回错误信息。
            """
            try:
                task_id = _engine_scheduler.submit(
                    engine_name=engine_name,
                    input_path=input_path,
                    output_path=output_path,
                )
                return {"success": True, "data": {"task_id": task_id}}
            except Exception as e:
                return {"success": False, "error": str(e)}

        @engine_router.get("/task/{task_id}")
        async def get_task_status(task_id: str):
            """查询任务状态和结果。

            Args:
                task_id: 任务唯一标识符。

            Returns:
                dict: 统一响应格式，包含任务状态和结果数据（如已完成）。
            """
            status = _engine_scheduler.get_task_status(task_id)
            result = _engine_scheduler.get_result(task_id)
            return {
                "success": True,
                "data": {
                    "task_id": task_id,
                    "status": status,
                    "result": result.__dict__ if result else None,
                },
            }

        app.include_router(engine_router)
        logger.info("Engine Scheduler API routes registered")

    try:
        from bin.integrated_app.optimization.webui_enhancement import FileListManager, SettingsPersistence

        _file_list_manager = FileListManager()
        _settings_persistence = SettingsPersistence()
        logger.info("WebUI Enhancement modules loaded")
    except Exception as e:
        _file_list_manager = None
        _settings_persistence = None
        logger.debug(f"WebUI Enhancement not available: {e}")

    return app


def _kill_port_process(port: int) -> bool:
    """尝试终止占用指定端口的进程（Windows 平台专用）。

    使用 netstat 命令查找 LISTENING 状态占用指定端口的进程 PID，
    然后使用 taskkill /F 强制终止该进程。

    Args:
        port: 要释放的端口号，如 7870。

    Returns:
        bool: 成功找到并终止进程返回 True，未找到或终止失败返回 False。

    Note:
        - 仅在 Windows 平台有效，依赖 netstat 和 taskkill 系统命令
        - 终止后等待1秒让端口释放
        - 此函数仅在端口被占用且需要自动释放时调用
    """
    import subprocess

    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                pid = int(parts[-1])
                logger.warning(f"端口 {port} 被进程 PID={pid} 占用，尝试终止...")
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=5)
                import time

                time.sleep(1)
                return True
    except Exception as e:
        logger.warning(f"终止端口占用进程失败: {e}")
    return False


def main() -> None:
    """启动 SeedVR2 FastAPI 应用服务器。

    完整启动流程：
    1. 加载配置文件
    2. 创建 FastAPI 应用实例
    3. 配置日志级别和格式
    4. 尝试启动 Uvicorn 服务器
    5. 如果端口被占用（OSError 10048），自动尝试终止占用进程后重试

    服务器配置：
    - 默认监听地址：127.0.0.1
    - 默认端口：7870
    - debug 模式下启用热重载（从配置读取）

    Raises:
        OSError: 端口被占用且自动释放失败时重新抛出异常。
        SystemExit: Uvicorn 运行出错时可能触发。
    """
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

    logger.info(f"SeedVR2启动中... http://{host}:{port}")
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

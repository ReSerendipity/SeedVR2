#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2024-2026 ReSerendipity
# SPDX-License-Identifier: Apache-2.0
"""
SeedVR2 - 搴旂敤鏈嶅姟鍣ㄥ叆鍙ｆā鍧?

鎵€灞為」鐩細SeedVR2 (AI-powered video & image super-resolution toolkit)
鏍稿績鍔熻兘锛?
    - FastAPI 搴旂敤鍒涘缓涓庨厤缃?
    - 搴旂敤鐢熷懡鍛ㄦ湡绠＄悊锛堝惎鍔ㄥ垵濮嬪寲銆佷紭闆呭叧闂級
    - 鏍稿績缁勪欢鍒濆鍖栦笌渚濊禆娉ㄥ叆
    - 涓棿浠舵敞鍐岋紙CORS銆丆SRF銆侀敊璇鐞嗭級
    - 闈欐€佹枃浠舵湇鍔′笌妯℃澘寮曟搸閰嶇疆
    - 璺敱鑷姩鍙戠幇涓庢敞鍐?
    - 绔彛鍐茬獊鑷姩澶勭悊涓庢湇鍔″櫒鍚姩

鏍稿績鎶€鏈爤锛?
    - FastAPI 0.100+ 浣滀负 Web 妗嗘灦
    - Uvicorn 浣滀负 ASGI 鏈嶅姟鍣?
    - Pydantic 鐢ㄤ簬閰嶇疆楠岃瘉
    - Jinja2 鐢ㄤ簬妯℃澘娓叉煋
    - 瑙傚療鑰呮ā寮忓疄鐜版ā鍨嬬姸鎬佸埌 SSE 鐨勬ˉ鎺?
"""

import asyncio
import logging
import os
import sys
import webbrowser
from contextlib import asynccontextmanager, suppress

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
    """灏?model_registry 鐘舵€佸彉鏇存ˉ鎺ュ埌 SSE 浜嬩欢鎬荤嚎銆?

    浣滀负 model_registry 鐨勮瀵熻€呯洃鍚櫒锛屽湪妯″瀷鐘舵€佸彉鏇存椂閫氳繃 event_bus 骞挎挱锛?
    浣?SSE 瀹㈡埛绔兘瀹炴椂鏀跺埌 model_status 浜嬩欢銆?
    浣跨敤瑙傚療鑰呮ā寮忚В鑰?model_registry 涓?event_bus 鐨勭洿鎺ヤ緷璧栥€?

    Args:
        event_name: 浜嬩欢鍚嶇О锛屽 'model_loading'銆?model_loaded'銆?model_unloaded'銆?
        payload: 浜嬩欢鏁版嵁瀛楀吀锛屽寘鍚ā鍨嬬姸鎬佽鎯呫€?
    """
    event_bus.publish(event_name, payload)


class VersionedStaticFiles(StaticFiles):
    """甯︾増鏈帶鍒剁殑闈欐€佹枃浠跺鐞嗙被銆?

    缁ф壙鑷?FastAPI StaticFiles锛屼负涓嶅悓绫诲瀷鐨勯潤鎬佽祫婧愯缃樊寮傚寲鐨?Cache-Control 澶达細
    - CSS/JS 鏂囦欢锛氫笉缂撳瓨锛屾瘡娆″埛鏂拌幏鍙栨渶鏂扮増鏈?
    - 瀛椾綋鏂囦欢锛坵off2/woff/ttf/eot/otf锛夛細涓湡缂撳瓨锛?0澶╋級
    - 鍥剧墖璧勬簮锛坧ng/jpg/jpeg/gif/svg/ico/webp锛夛細鐭湡缂撳瓨锛?澶╋級
    """

    def file_response(self, *args, **kwargs) -> Response:
        """閲嶅啓 file_response 鏂规硶锛屼负涓嶅悓鏂囦欢绫诲瀷娣诲姞缂撳瓨澶淬€?

        Args:
            *args: 浣嶇疆鍙傛暟锛岀涓€涓弬鏁颁负鏂囦欢璺緞銆?
            **kwargs: 鍏抽敭瀛楀弬鏁般€?

        Returns:
            Response: 娣诲姞浜?Cache-Control 澶寸殑 HTTP 鍝嶅簲銆?
        """
        response = super().file_response(*args, **kwargs)
        if args:
            file_path = str(args[0])
            if file_path.endswith((".css", ".js")):
                response.headers["Cache-Control"] = "no-cache, must-revalidate"
                response.headers["Pragma"] = "no-cache"
            elif file_path.endswith((".woff2", ".woff", ".ttf", ".eot", ".otf")):
                response.headers["Cache-Control"] = "public, max-age=2592000"
            elif file_path.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp")):
                response.headers["Cache-Control"] = "public, max-age=86400"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 搴旂敤鐢熷懡鍛ㄦ湡绠＄悊涓婁笅鏂囩鐞嗗櫒銆?

    澶勭悊搴旂敤鍚姩鍜屽叧闂椂鐨勮祫婧愬垵濮嬪寲涓庢竻鐞嗭細

    鍚姩闃舵锛坹ield 鍓嶏級锛?
        1. 鍒濆鍖栧巻鍙茶褰曟暟鎹簱
        2. 鍚姩寮傛浠诲姟闃熷垪
        3. 娉ㄥ唽妯″瀷鐘舵€佸埌 SSE 鐨勬ˉ鎺ョ洃鍚櫒
        4. 鎭㈠鏁版嵁搴撲腑鏈畬鎴愮殑浠诲姟
        5. 鍚姩缂撳瓨瀹氭湡娓呯悊浠诲姟
        6. 妫€娴?GPU 鍚庣涓庡吋瀹规€?
        7. 鍙€夎嚜鍔ㄥ姞杞芥ā鍨嬶紙GPU 鍙敤涓旈厤缃惎鐢ㄦ椂锛?
        8. 鍙€夎嚜鍔ㄦ墦寮€娴忚鍣ㄨ闂簲鐢?

    鍏抽棴闃舵锛坹ield 鍚庯級锛?
        1. 绉婚櫎妯″瀷鐘舵€佺洃鍚櫒
        2. 鍋滄缂撳瓨娓呯悊浠诲姟
        3. 浼橀泤鍋滄浠诲姟闃熷垪锛堟渶澶氱瓑寰?0绉掞級
        4. 鍗歌浇妯″瀷閲婃斁 GPU 鏄惧瓨
        5. 鍏抽棴鏁版嵁搴撹繛鎺?

    Args:
        app: FastAPI 搴旂敤瀹炰緥锛岄€氳繃 app.state 璁块棶宸插垵濮嬪寲鐨勭粍浠躲€?

    Yields:
        None:  yield 鐐瑰垎闅斿惎鍔ㄥ拰鍏抽棴闃舵锛屽簲鐢ㄥ湪姝ゆ湡闂磋繍琛屻€?
    """
    config = app.state.config

    # 鏍稿績妯″潡瀹屾暣鎬ц嚜妫€ (CWE-912 闃插尽)
    try:
        from bin.integrated_app.security.integrity_selfcheck import run_startup_selfcheck

        selfcheck = run_startup_selfcheck()
        if selfcheck["failed"] > 0:
            logger.error(
                "=" * 60 + "\n"
                "[SECURITY] 鈿狅笍  鍚姩鏃舵牳蹇冩ā鍧楀畬鏁存€ц嚜妫€澶辫触锛乗n"
                f"    澶辫触鏂囦欢: {', '.join(selfcheck['failed_files'])}\n"
                "    璇锋鏌ヤ唬鐮佹槸鍚﹁绡℃敼鎴栭噸鏂扮敓鎴愭竻鍗曘€俓n" + "=" * 60
            )
    except Exception as e:
        logger.debug(f"鏍稿績妯″潡瀹屾暣鎬ц嚜妫€璺宠繃: {e}")

    history_db: HistoryDB = app.state.history_db
    await history_db.initialize()
    logger.info("鍘嗗彶鏁版嵁搴撳凡鍒濆鍖?)

    task_queue: TaskQueue = app.state.task_queue
    await task_queue.start()
    logger.info("浠诲姟闃熷垪宸插惎鍔?)

    model_registry.add_listener(_bridge_model_status_to_sse)
    logger.info("宸叉敞鍐屾ā鍨嬬姸鎬?SSE 妗ユ帴鐩戝惉鍣?)

    try:
        from bin.integrated_app.routes.restore import unified as unified_routes

        # 鍏堟竻鐞嗗崱姝荤殑 processing 浠诲姟锛屽啀鎭㈠鍙仮澶嶇殑浠诲姟
        cleaned_count = await unified_routes.cleanup_stale_tasks(history_db)
        if cleaned_count:
            logger.info(f"宸叉竻鐞?{cleaned_count} 涓崱姝荤殑 processing 浠诲姟")

        auto_recover = config.get("runtime", {}).get("task", {}).get("auto_recover", False)
        if auto_recover:
            recovered_count = await unified_routes.recover_tasks(history_db, task_queue, config)
            if recovered_count:
                logger.info(f"宸蹭粠鏁版嵁搴撴仮澶?{recovered_count} 涓湭瀹屾垚浠诲姟")
        else:
            logger.info("鍚姩浠诲姟鑷姩鎭㈠宸插叧闂?(runtime.task.auto_recover=false)")
    except Exception as e:
        logger.warning(f"鎭㈠鏈畬鎴愪换鍔″け璐? {e}")

    # 鍒濆鍖栨柇鐐圭画璺戠鐞嗗櫒骞舵壂鎻忓緟鎭㈠鐨?checkpoint
    try:
        from bin.integrated_app.checkpoint import TaskCheckpoint

        task_cfg = config.get("runtime", {}).get("task", {})
        ckpt_dir = task_cfg.get("checkpoint_dir", "data/checkpoints")
        project_root_for_ckpt = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        checkpoint_mgr = TaskCheckpoint(os.path.join(project_root_for_ckpt, ckpt_dir))
        pending_checkpoints = checkpoint_mgr.list_checkpoints()
        if pending_checkpoints:
            logger.info(f"鍙戠幇 {len(pending_checkpoints)} 涓緟鎭㈠鐨勬壒閲忎换鍔?checkpoint")
        app.state.checkpoint_mgr = checkpoint_mgr
    except Exception as e:
        logger.warning(f"鍒濆鍖栨柇鐐圭画璺戠鐞嗗櫒澶辫触: {e}")
        app.state.checkpoint_mgr = None

    file_cache: FileCache = app.state.file_cache
    file_cache.start_cleanup_task(interval=3600)

    # 鍚姩瀹氭湡娓呯悊鍗℃浠诲姟鐨勫悗鍙颁换鍔★紙姣?鍒嗛挓妫€鏌ヤ竴娆★級
    async def _periodic_stale_cleanup():
        while True:
            try:
                await asyncio.sleep(300)  # 姣?鍒嗛挓
                cleaned = await unified_routes.cleanup_stale_tasks(history_db)
                if cleaned:
                    logger.info(f"瀹氭湡娓呯悊锛氬凡娓呯悊 {cleaned} 涓崱姝荤殑 processing 浠诲姟")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"瀹氭湡娓呯悊鍗℃浠诲姟澶辫触: {e}")

    stale_cleanup_task = asyncio.create_task(_periodic_stale_cleanup())
    app.state.stale_cleanup_task = stale_cleanup_task

    backend_value = gpu_manager.backend.value if gpu_manager.backend else "unavailable"
    logger.info(f"GPU 鍚庣: {backend_value}, 璁惧: {gpu_manager.device_name}")

    if gpu_manager.is_gpu_available and config.get("model", {}).get("auto_load", True):
        try:
            model_manager: ModelManager = app.state.model_manager
            await model_manager.load_model()
            logger.info("妯″瀷鑷姩鍔犺浇瀹屾垚")
        except Exception as e:
            logger.warning(f"鑷姩鍔犺浇妯″瀷澶辫触: {e}")
    elif not gpu_manager.is_gpu_available:
        logger.warning("鏈娴嬪埌 NVIDIA GPU锛岃烦杩囨ā鍨嬭嚜鍔ㄥ姞杞斤紙闄嶇骇妯″紡锛?)

    host = config.get("server", {}).get("host", "127.0.0.1")
    port = config.get("server", {}).get("port", 7870)
    if config.get("server", {}).get("auto_open_browser", True):
        url = f"http://{host}:{port}"
        asyncio.get_running_loop().call_later(1.5, lambda: webbrowser.open(url))
        logger.info(f"灏嗗湪娴忚鍣ㄤ腑鎵撳紑: {url}")

    logger.info(f"SeedVR2宸插惎鍔? http://{host}:{port}")

    yield

    model_registry.remove_listener(_bridge_model_status_to_sse)

    file_cache.stop_cleanup_task()

    # 鍋滄瀹氭湡娓呯悊鍗℃浠诲姟鐨勫悗鍙颁换鍔?
    stale_cleanup = getattr(app.state, "stale_cleanup_task", None)
    if stale_cleanup:
        stale_cleanup.cancel()
        with suppress(asyncio.CancelledError):
            await stale_cleanup

    task_queue = app.state.task_queue
    try:
        await asyncio.wait_for(task_queue.stop(), timeout=30.0)
        logger.info("浠诲姟闃熷垪宸蹭紭闆呭仠姝?)
    except TimeoutError:
        logger.warning("浠诲姟闃熷垪鍋滄瓒呮椂锛?0s锛夛紝寮哄埗閫€鍑?)

    model_manager = app.state.model_manager
    await model_manager.unload_model()

    history_db = app.state.history_db
    await history_db.close()

    logger.info("SeedVR2宸插叧闂?)


def create_app(config: dict | None = None) -> FastAPI:
    """鍒涘缓骞堕厤缃?FastAPI 搴旂敤瀹炰緥銆?

    瀹屾暣鐨勫簲鐢ㄦ瀯寤烘祦绋嬶細
    1. 鍔犺浇閰嶇疆锛堟湭鎻愪緵鏃朵粠 config.yaml 鍔犺浇锛?
    2. 鍒涘缓 FastAPI 瀹炰緥锛岄厤缃爣棰樸€佹弿杩般€佺増鏈拰鐢熷懡鍛ㄦ湡
    3. 娉ㄥ唽涓棿浠讹紙CORS銆丆SRF銆佸叏灞€閿欒澶勭悊锛?
    4. 鍒濆鍖栨墍鏈夋牳蹇冪粍浠跺苟鎸傝浇鍒?app.state锛?
       - config: 搴旂敤閰嶇疆瀛楀吀
       - model_manager: 妯″瀷鍔犺浇/鍗歌浇/鍒囨崲绠＄悊鍣?
       - gpu_backend: GPU 鍚庣绠＄悊鍣?
       - history_db: SQLite 鍘嗗彶璁板綍鏁版嵁搴?
       - task_queue: 鍗?worker 寮傛浠诲姟闃熷垪
       - event_bus: SSE 浜嬩欢鎬荤嚎
       - i18n: 鍥介檯鍖栨敮鎸?
       - file_cache: 涓婁紶鏂囦欢缂撳瓨
       - jinja_env: Jinja2 妯℃澘鐜
    5. 鎸傝浇鐗堟湰鍖栭潤鎬佹枃浠剁洰褰?
    6. 鑷姩鍙戠幇骞舵敞鍐屾墍鏈?API 璺敱鍜岄〉闈㈣矾鐢?
    7. 鍙€夊垵濮嬪寲澶氬紩鎿庤皟搴﹀櫒鍜屼笓鐢ㄥ紩鎿?

    Args:
        config: 搴旂敤閰嶇疆瀛楀吀锛屼负 None 鏃惰嚜鍔ㄤ粠 config.yaml 鍔犺浇銆?

    Returns:
        FastAPI: 閰嶇疆瀹屾垚鐨?FastAPI 搴旂敤瀹炰緥锛屽彲鐩存帴浼犲叆 uvicorn.run()銆?
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

    # Basic Auth 涓棿浠?(鍏綉閮ㄧ讲淇濇姢, CWE-306 闃插尽)
    from bin.integrated_app.middleware.basic_auth import should_enable_auth

    if should_enable_auth(config):
        from bin.integrated_app.middleware.basic_auth import BasicAuthMiddleware

        auth_cfg = config.get("security", {}).get("auth", {})
        import os as _os

        app.add_middleware(
            BasicAuthMiddleware,
            username=auth_cfg.get("username", "admin"),
            password=_os.environ.get("SEEDVR2_AUTH_PASSWORD", auth_cfg.get("password", "")),
            realm=auth_cfg.get("realm", "SeedVR2"),
        )
        logger.info("Basic Auth 涓棿浠跺凡娉ㄥ唽")

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
        logger.warning(f"妯℃澘鐩綍涓嶅瓨鍦? {templates_dir}")
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
            """鍒楀嚭鎵€鏈夊凡娉ㄥ唽鐨勬帹鐞嗗紩鎿庛€?

            Returns:
                dict: 缁熶竴鍝嶅簲鏍煎紡锛屽寘鍚墍鏈夊紩鎿庡悕绉板垪琛ㄥ拰褰撳墠鍙敤寮曟搸鍒楄〃銆?
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
            """妫€娴嬫墍鏈夋帹鐞嗗紩鎿庣殑鍙敤鎬х姸鎬併€?

            Returns:
                dict: 缁熶竴鍝嶅簲鏍煎紡锛屽寘鍚悇寮曟搸鍚嶇О鍒板彲鐢ㄦ€х姸鎬佺殑鏄犲皠銆?

            Raises:
                Exception: 妫€娴嬭繃绋嬪嚭閿欐椂杩斿洖閿欒淇℃伅銆?
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
            """鍚戞寚瀹氬紩鎿庢彁浜ゆ帹鐞嗕换鍔°€?

            Args:
                engine_name: 寮曟搸鍚嶇О锛屼负 None 鏃惰嚜鍔ㄩ€夋嫨銆?
                input_path: 杈撳叆鏂囦欢璺緞銆?
                output_path: 杈撳嚭鏂囦欢璺緞銆?

            Returns:
                dict: 缁熶竴鍝嶅簲鏍煎紡锛屾垚鍔熸椂鍖呭惈 task_id锛屽け璐ユ椂鍖呭惈閿欒淇℃伅銆?

            Raises:
                Exception: 浠诲姟鎻愪氦澶辫触鏃惰繑鍥為敊璇俊鎭€?
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
            """鏌ヨ浠诲姟鐘舵€佸拰缁撴灉銆?

            Args:
                task_id: 浠诲姟鍞竴鏍囪瘑绗︺€?

            Returns:
                dict: 缁熶竴鍝嶅簲鏍煎紡锛屽寘鍚换鍔＄姸鎬佸拰缁撴灉鏁版嵁锛堝宸插畬鎴愶級銆?
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
    """灏濊瘯缁堟鍗犵敤鎸囧畾绔彛鐨勮繘绋嬶紙Windows 骞冲彴涓撶敤锛夈€?

    浣跨敤 netstat 鍛戒护鏌ユ壘 LISTENING 鐘舵€佸崰鐢ㄦ寚瀹氱鍙ｇ殑杩涚▼ PID锛?
    鐒跺悗浣跨敤 taskkill /F 寮哄埗缁堟璇ヨ繘绋嬨€?

    Args:
        port: 瑕侀噴鏀剧殑绔彛鍙凤紝濡?7870銆?

    Returns:
        bool: 鎴愬姛鎵惧埌骞剁粓姝㈣繘绋嬭繑鍥?True锛屾湭鎵惧埌鎴栫粓姝㈠け璐ヨ繑鍥?False銆?

    Note:
        - 浠呭湪 Windows 骞冲彴鏈夋晥锛屼緷璧?netstat 鍜?taskkill 绯荤粺鍛戒护
        - 缁堟鍚庣瓑寰?绉掕绔彛閲婃斁
        - 姝ゅ嚱鏁颁粎鍦ㄧ鍙ｈ鍗犵敤涓旈渶瑕佽嚜鍔ㄩ噴鏀炬椂璋冪敤
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
                logger.warning(f"绔彛 {port} 琚繘绋?PID={pid} 鍗犵敤锛屽皾璇曠粓姝?..")
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=5)
                import time

                time.sleep(1)
                return True
    except Exception as e:
        logger.warning(f"缁堟绔彛鍗犵敤杩涚▼澶辫触: {e}")
    return False


def main() -> None:
    """鍚姩 SeedVR2 FastAPI 搴旂敤鏈嶅姟鍣ㄣ€?

    瀹屾暣鍚姩娴佺▼锛?
    1. 鍔犺浇閰嶇疆鏂囦欢
    2. 鍒涘缓 FastAPI 搴旂敤瀹炰緥
    3. 閰嶇疆鏃ュ織绾у埆鍜屾牸寮?
    4. 灏濊瘯鍚姩 Uvicorn 鏈嶅姟鍣?
    5. 濡傛灉绔彛琚崰鐢紙OSError 10048锛夛紝鑷姩灏濊瘯缁堟鍗犵敤杩涚▼鍚庨噸璇?

    鏈嶅姟鍣ㄩ厤缃細
    - 榛樿鐩戝惉鍦板潃锛?27.0.0.1
    - 榛樿绔彛锛?870
    - debug 妯″紡涓嬪惎鐢ㄧ儹閲嶈浇锛堜粠閰嶇疆璇诲彇锛?

    Raises:
        OSError: 绔彛琚崰鐢ㄤ笖鑷姩閲婃斁澶辫触鏃堕噸鏂版姏鍑哄紓甯搞€?
        SystemExit: Uvicorn 杩愯鍑洪敊鏃跺彲鑳借Е鍙戙€?
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

    logger.info(f"SeedVR2鍚姩涓?.. http://{host}:{port}")
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
            logger.warning(f"绔彛 {port} 宸茶鍗犵敤锛屽皾璇曡嚜鍔ㄧ粓姝㈠崰鐢ㄨ繘绋?..")
            if _kill_port_process(port):
                logger.info(f"绔彛 {port} 宸查噴鏀撅紝閲嶆柊鍚姩鏈嶅姟鍣?..")
                uvicorn.run(
                    app,
                    host=host,
                    port=port,
                    log_level=log_level.lower(),
                    reload=debug,
                )
            else:
                logger.error(f"鏃犳硶閲婃斁绔彛 {port}锛岃鎵嬪姩缁堟鍗犵敤杩涚▼鍚庨噸璇?)
                raise
        else:
            raise


if __name__ == "__main__":
    main()

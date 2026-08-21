# launcher/bootstrap_server.py
"""SeedVR2 启动器 - 引导页本地服务（localhost:7871）。

仅用 stdlib http.server，轮询式 JSON API：
  GET  /                          -> static/index.html
  GET  /static/*                  -> static 静态资源
  GET  /api/status                -> 总状态（环境/torch/模型/冒烟/状态文件）
  POST /api/env-check             -> 运行环境检测
  POST /api/torch/install         -> 后台线程安装 torch 家族（可带 index_key）
  GET  /api/torch/status          -> 安装进度（idle/running/done/error + log）
  POST /api/models/check          -> 模型校验
  GET  /api/models/recommend      -> 按显存推荐主模型
  POST /api/smoke-test            -> 启动冒烟测试（后台线程）
  GET  /api/smoke-test/status     -> 冒烟进度
  GET  /api/app/health            -> 应用 7870 是否已就绪
  POST /api/app/start             -> 拉起应用（clean_launch.py）
  POST /api/app/open              -> 用浏览器打开应用地址
"""
from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from launcher.dependency_check import TORCH_INDEXES, check_torch, torch_install_cmd
from launcher.env_check import check_env
from launcher.model_check import check_models, recommend_main_model
from launcher.setup_state import SetupState
from launcher.smoke_test import run_smoke_test

APP_PORT = 7870
APP_BASE = f"http://127.0.0.1:{APP_PORT}"


class Router:
    """极简路由 + 分发逻辑：method + 前缀匹配。dispatch() 为纯逻辑，可单测。"""

    def __init__(self, static_dir: Path) -> None:
        self._routes: list[tuple[str, str, callable]] = []
        self.static_dir = Path(static_dir)
        self._last_body: dict = {}

    def get(self, path: str, fn: callable) -> None:
        self._routes.append(("GET", path, fn))

    def post(self, path: str, fn: callable) -> None:
        self._routes.append(("POST", path, fn))

    def match(self, method: str, path: str):
        for m, p, fn in self._routes:
            if m == method and path.startswith(p):
                return fn
        return None

    def dispatch(self, method: str, path: str, body_bytes: bytes = b"") -> tuple[int, bytes, str]:
        """路由分发，返回 (status_code, payload_bytes, content_type)。"""
        parsed = path.split("?", 1)[0]
        if parsed == "/":
            idx = self.static_dir / "index.html"
            if idx.exists():
                return 200, idx.read_bytes(), "text/html; charset=utf-8"
            return 404, b'{"error":"index.html missing"}', "application/json; charset=utf-8"
        if parsed.startswith("/static/"):
            rel = parsed[len("/static/"):]
            fp = (self.static_dir / rel).resolve()
            if str(fp).startswith(str(self.static_dir.resolve())) and fp.exists():
                ctype = "text/css; charset=utf-8" if fp.suffix == ".css" else "application/javascript; charset=utf-8"
                return 200, fp.read_bytes(), ctype
            return 404, b'{"error":"asset not found"}', "application/json; charset=utf-8"
        fn = self.match(method, parsed)
        if fn is None:
            return 404, b'{"error":"not found"}', "application/json; charset=utf-8"
        if method == "POST" and body_bytes:
            try:
                self._last_body.update(json.loads(body_bytes.decode("utf-8")))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        try:
            result = fn()
            if result is None:
                result = {"ok": True}
            return 200, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8"
        except Exception as exc:
            return 500, json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8"

    def register_api(self, install_dir: Path, model_dir: Path,
                     state: SetupState, python_exe: str, shutdown_fn: callable | None = None) -> None:
        """注册全部引导 API。闭包共享安装环境信息。"""
        env_result = {"checked": False, "data": None}
        torch_state = {"status": "idle", "log": "", "index": "pytorch-cu128", "error": None}
        smoke_state = {"status": "idle", "result": None}
        app_proc: dict = {"proc": None}

        self.get("/api/status", lambda: {
            "env": env_result["data"],
            "torch_ready": state.torch_ready,
            "smoke_test_passed": state.get("smoke_test_passed", False),
            "models": check_models(model_dir).to_dict(),
        })

        # 环境检测
        self.post("/api/env-check", lambda: self._run_env(env_result, install_dir))
        self.get("/api/env-check", lambda: env_result)

        # torch 安装
        self.post("/api/torch/install", lambda: self._start_torch_install(torch_state, python_exe, state))
        self.get("/api/torch/status", lambda: torch_state)
        self.post("/api/torch/mirror", lambda: self._set_mirror(torch_state, self._last_body))
        self.post("/api/torch/skip", lambda: self._skip_torch(python_exe, state))

        # 模型
        self.get("/api/models/check", lambda: check_models(model_dir).to_dict())
        self.get("/api/models/recommend", lambda: self._recommend(env_result))

        # 冒烟测试
        self.post("/api/smoke-test", lambda: self._start_smoke(smoke_state, install_dir, state))
        self.get("/api/smoke-test/status", lambda: smoke_state)

        # 应用
        self.get("/api/app/health", lambda: {"up": self._app_health()})
        self.post("/api/app/start", lambda: self._start_app(app_proc, python_exe, install_dir))
        self.post("/api/app/open", lambda: self._open_app())

        # 退出启动器（应用已独立运行时调用）
        self.post("/api/shutdown", lambda: self._shutdown(shutdown_fn))

    # ---- 内部实现 ----
    def _shutdown(self, shutdown_fn: callable | None) -> dict:
        if shutdown_fn is not None:
            shutdown_fn()
        return {"ok": True, "shutdown": True}

    def _run_env(self, env_result: dict, install_dir: Path):
        env_result["data"] = check_env(install_dir).to_dict()
        env_result["checked"] = True
        return env_result

    def _recommend(self, env_result: dict) -> dict:
        vram = (env_result.get("data") or {}).get("vram_gb") or 24
        return {"vram_gb": vram, "recommended": recommend_main_model(vram)}

    def _start_torch_install(self, torch_state: dict, python_exe: str, state: SetupState):
        if torch_state["status"] == "running":
            return {"error": "torch 正在安装中"}
        torch_state["status"] = "running"
        torch_state["error"] = None
        torch_state["log"] = ""

        def worker():
            index = torch_state["index"]
            cmd = torch_install_cmd(python_exe, index)
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    torch_state["log"] += line
                    if len(torch_state["log"]) > 8000:
                        torch_state["log"] = torch_state["log"][-8000:]
                proc.wait()
                if proc.returncode == 0:
                    torch_state["status"] = "done"
                    state.set("torch_installed", True)
                else:
                    torch_state["status"] = "error"
                    torch_state["error"] = f"pip 安装退出码 {proc.returncode}"
            except Exception as exc:
                torch_state["status"] = "error"
                torch_state["error"] = str(exc)

        threading.Thread(target=worker, daemon=True).start()
        return {"started": True}

    def _set_mirror(self, torch_state: dict, last_body: dict) -> dict:
        index = (last_body or {}).get("index")
        if index in TORCH_INDEXES:
            torch_state["index"] = index
        return {"ok": True, "index": torch_state["index"]}

    def _skip_torch(self, python_exe: str, state: SetupState) -> dict:
        """跳过 torch 安装：先复核是否已可用，可用则标记就绪，否则拒绝跳过。"""
        res = check_torch(python_exe)
        if res.installed:
            state.set("torch_installed", True)
            state.set("torch_verified", True)
            return {"ok": True, "message": "检测到已可用的 torch 环境，已跳过安装"}
        return {
            "ok": False,
            "message": f"未检测到可用的 torch 环境。探测详情：{res.message}",
        }

    def _start_smoke(self, smoke_state: dict, install_dir: Path, state: SetupState):
        if smoke_state["status"] == "running":
            return {"error": "冒烟测试进行中"}
        test_image = install_dir / "launcher" / "test-assets" / "test-input.jpg"

        def worker():
            smoke_state["status"] = "running"
            res = run_smoke_test(APP_BASE, test_image)
            smoke_state["result"] = {"success": res.success, "message": res.message, "output_path": res.output_path}
            smoke_state["status"] = "done"
            if res.success:
                state.set("smoke_test_passed", True)

        threading.Thread(target=worker, daemon=True).start()
        return {"started": True}

    def _app_health(self) -> bool:
        try:
            import urllib.request
            with urllib.request.urlopen(f"{APP_BASE}/api/system/health", timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _start_app(self, app_proc: dict, python_exe: str, install_dir: Path):
        if app_proc["proc"] is not None and app_proc["proc"].poll() is None:
            return {"started": True}
        proc = subprocess.Popen(
            [python_exe, str(install_dir / "app" / "clean_launch.py")],
            cwd=str(install_dir),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        app_proc["proc"] = proc
        return {"started": True}

    def _open_app(self):
        import webbrowser
        webbrowser.open(APP_BASE)
        return {"opened": True}


def make_handler(router: Router):
    """返回一个 BaseHTTPRequestHandler 子类，转发给 router.dispatch()。"""

    class Handler(BaseHTTPRequestHandler):
        def _dispatch(self):
            body = b""
            if self.command == "POST" and self.headers.get("Content-Length"):
                body = self.rfile.read(int(self.headers["Content-Length"]))
            code, payload, ctype = router.dispatch(self.command, self.path, body)
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            self._dispatch()

        def do_POST(self):
            self._dispatch()

        def log_message(self, *args):
            pass

    return Handler


def start_server(router: Router, port: int = 7871):
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(router))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread

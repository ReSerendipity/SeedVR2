# launcher/launcher_main.py
"""SeedVR2 启动器 - PyInstaller 窗口入口（无控制台）。

职责：起引导服务（localhost:7871）→ 浏览器打开 8 步向导页 → 保持运行。
开发模式（未打包）时用仓库根目录；打包后用 exe 所在目录作为安装目录。
"""
from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

from launcher.bootstrap_server import Router, start_server
from launcher.setup_state import SetupState

BOOTSTRAP_PORT = 7871


def install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def find_portable_python(root: Path) -> Path:
    cand = root / "WPy64-312101" / "python" / "python.exe"
    if cand.exists():
        return cand
    for wp in root.glob("WPy64-*"):
        p = wp / "python" / "python.exe"
        if p.exists():
            return p
    return cand  # 返回默认路径，供报错信息使用


def find_free_port(start: int = BOOTSTRAP_PORT, tries: int = 10) -> int:
    import socket
    for port in range(start, start + tries):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def main() -> int:
    root = install_dir()
    python_exe = str(find_portable_python(root))
    static_dir = root / "launcher" / "static"
    model_dir = root / "model"
    state = SetupState(root / ".setup_state.json")

    router = Router(static_dir)
    shutdown_fn = None  # 由下方闭包赋值，注册 API 时传入

    def _shutdown():
        if shutdown_fn is not None:
            shutdown_fn()

    router.register_api(root, model_dir, state, python_exe, shutdown_fn=_shutdown)

    port = find_free_port()
    server, _thread = start_server(router, port=port)
    shutdown_fn = server.shutdown

    url = f"http://127.0.0.1:{port}"
    print(f"[SeedVR2] 引导页: {url}")
    webbrowser.open(url)

    # 保持运行：收到 /api/shutdown 后 serve_forever 返回
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())

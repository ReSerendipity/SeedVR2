# launcher/launcher_main.py
"""SeedVR2 启动器 - PyInstaller 窗口入口（无控制台）。

职责：起引导服务（localhost:7871）→ 浏览器打开 8 步向导页 → 保持运行。
开发模式（未打包）时用仓库根目录；打包后用 exe 所在目录作为安装目录。
"""
from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

# 开发模式直接运行脚本（python launcher/launcher_main.py）时，脚本所在目录会被设为
# sys.path[0]，项目根不在路径中，导致 `from launcher.*` 导入失败；这里显式补上项目根。
# 打包后（PyInstaller）依赖内置于 exe，此插入无害。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from launcher.bootstrap_server import Router, start_server
from launcher.setup_state import SetupState

BOOTSTRAP_PORT = 7871


def install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def find_portable_python(root: Path) -> Path:
    """定位便携 Python（优先项目虚拟环境，兼容 WinPython 多种目录结构）。

    优先级（对齐 start.bat）：
    0. {root}/.venv/Scripts/python.exe（开发模式/用户已用 uv 装好依赖时直接复用）
    1. WPy64-312101/python/python.exe（标准布局）
    2. WPy64-*/python/python.exe
    3. WPy64-*/python-*.amd64/python.exe（WinPython dot 变体布局）
    4. 递归兜底搜索任一 python.exe
    找不到时返回默认路径（供报错信息使用）。
    """
    venv = root / ".venv" / "Scripts" / "python.exe"
    if venv.exists():
        return venv

    bases: list[Path] = []
    wp = root / "WPy64-312101"
    if wp.is_dir():
        bases.append(wp)
    bases.extend(sorted(root.glob("WPy64-*")))
    bases.extend(sorted(root.glob("WinPython64-*")))

    for base in bases:
        p = base / "python" / "python.exe"
        if p.exists():
            return p
        for pd in base.glob("python-*.amd64"):
            p = pd / "python.exe"
            if p.exists():
                return p

    for base in bases:
        found = list(base.rglob("python.exe"))
        if found:
            return found[0]

    return root / "WPy64-312101" / "python" / "python.exe"


def static_dir(root: Path) -> Path:
    """定位引导页静态资源目录。

    打包后优先用 PyInstaller 内置副本（--add-data 打入 exe），否则用安装目录旁的文件。
    """
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", root))
        p = meipass / "launcher" / "static"
        if p.is_dir():
            return p
    return root / "launcher" / "static"


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
    static = static_dir(root)
    model_dir = root / "model"
    state = SetupState(root / ".setup_state.json")

    router = Router(static)
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

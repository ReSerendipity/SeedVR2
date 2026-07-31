#!/usr/bin/env python3
"""
SeedVR2 - 清理缓存启动脚本

所属项目：SeedVR2 (AI-powered video & image super-resolution toolkit)
核心功能：
    - 环境隔离：优先使用项目自带 WinPython，排除系统/用户 Python 干扰
    - 缓存清理：仅清理项目源码的 __pycache__，跳过第三方依赖目录
    - CUDA 检测：启动前检查 GPU 可用性，输出硬件信息
    - 应用启动：完成环境准备后启动 integrated_app 应用服务器

核心技术栈：
    - Python 3.12 (WinPython 内置)
    - PyTorch (CUDA) 用于 GPU 推理
    - FastAPI + Uvicorn 作为 Web 服务器
"""
import sys
import os
from pathlib import Path


os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")


def find_winpython_python() -> str | None:
    """查找项目目录内 WinPython 中的 Python 可执行文件。

    按优先级搜索多个可能的 WinPython 安装位置，确保使用项目自带 Python 环境，
    避免与系统 Python 或用户安装的 Python 产生依赖冲突。

    Returns:
        str | None: 找到的 python.exe 绝对路径，未找到时返回 None。

    搜索顺序：
        1. WPy64-312101/ - WinPython64-3.12.10.1dot 标准解压目录
        2. WinPython64-*/ - 计划书原始命名格式目录
        3. WinPython/ - 通用命名目录
        4. WPy64-*/ - 所有 WPy64 前缀目录递归搜索
        5. WinPython*/ - 所有 WinPython 前缀目录递归搜索
    """
    project_root = Path(__file__).parent.parent

    wp_dir = project_root / "WPy64-312101"
    if wp_dir.exists():
        python_exe = wp_dir / "python" / "python.exe"
        if python_exe.exists():
            return str(python_exe)
        for python_dir in wp_dir.iterdir():
            if python_dir.is_dir() and python_dir.name.startswith("python-"):
                python_exe = python_dir / "python.exe"
                if python_exe.exists():
                    return str(python_exe)

    for item in project_root.iterdir():
        if item.is_dir() and item.name.startswith("WinPython64-"):
            for python_dir in item.iterdir():
                if python_dir.is_dir() and python_dir.name.startswith("python-"):
                    python_exe = python_dir / "python.exe"
                    if python_exe.exists():
                        return str(python_exe)

    winpython_dir = project_root / "WinPython"
    if winpython_dir.exists():
        python_exe = winpython_dir / "python" / "python.exe"
        if python_exe.exists():
            return str(python_exe)
        for python_dir in winpython_dir.iterdir():
            if python_dir.is_dir() and python_dir.name.startswith("python"):
                python_exe = python_dir / "python.exe"
                if python_exe.exists():
                    return str(python_exe)

    for item in project_root.iterdir():
        if item.is_dir() and item.name.startswith("WPy64-"):
            for root, dirs, files in os.walk(str(item)):
                for f in files:
                    if f == "python.exe":
                        return os.path.join(root, f)

    for item in project_root.iterdir():
        if item.is_dir() and item.name.startswith("WinPython"):
            for root, dirs, files in os.walk(str(item)):
                for f in files:
                    if f == "python.exe":
                        return os.path.join(root, f)

    return None


def setup_isolated_env() -> None:
    """设置完全隔离的 Python 运行环境。

    配置环境变量和 sys.path，确保：
    - PYTHONPATH 仅包含项目根目录
    - 清除 PYTHONHOME、PYTHONSTARTUP 等可能干扰的环境变量
    - 从 sys.path 中移除系统/用户 Python 包路径
    - 项目根目录始终在 sys.path 最前端

    此函数防止项目依赖加载系统中已安装的不兼容包版本。
    """
    project_root = str(Path(__file__).parent.parent)

    os.environ["PYTHONPATH"] = project_root

    for var in ["PYTHONHOME", "PYTHONSTARTUP", "PYTHONIOENCODING"]:
        os.environ.pop(var, None)

    sys.path = [p for p in sys.path if not any(
        exclude in p.lower() for exclude in [
            "\\appdata\\",
            "\\program files\\",
            "\\programdata\\",
        ]
    )]

    if project_root not in sys.path:
        sys.path.insert(0, project_root)


def main() -> int | None:
    """SeedVR2 应用启动主入口函数。

    执行完整的启动流程：
    1. 设置项目根目录并切换工作目录
    2. 配置隔离环境
    3. 检测 CUDA GPU 可用性并输出硬件信息
    4. 检测 WinPython 环境
    5. 验证环境隔离效果，泄露路径时输出警告
    6. 智能清理项目源码 __pycache__（跳过第三方依赖）
    7. 导入并启动应用服务器主函数

    Returns:
        int | None: 应用退出码，None 表示正常退出（返回 0）。

    Note:
        - __pycache__ 清理采用白名单跳过策略，避免清理 WinPython/site-packages
          下数千个 .pyc 文件导致下次启动重新编译第三方库拖慢速度
        - CUDA 不可用时应用仍可启动，但推理功能将降级不可用
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, project_root)
    os.chdir(project_root)

    setup_isolated_env()

    try:
        import torch
        has_cuda = torch.cuda.is_available()
        if has_cuda:
            gpu_name = torch.cuda.get_device_name(0)
            vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            print(f"[CUDA] GPU: {gpu_name}, VRAM: {vram_gb:.1f}GB")
            print(f"[CUDA] PyTorch {torch.__version__} (CUDA {torch.version.cuda})")
        else:
            print("[WARN] CUDA 不可用！应用将以降级模式启动（推理功能不可用）。")
            print("[WARN] SeedVR2 模型仅支持 NVIDIA GPU 推理，不支持 CPU。")
            print("[WARN] 请安装 NVIDIA GPU 并配置 CUDA 驱动以启用推理功能。")
            print(f"[WARN] 当前 PyTorch 版本: {torch.__version__}")
    except ImportError:
        print("[WARN] 未安装 PyTorch。应用将以降级模式启动（推理功能不可用）。")
        print("[WARN] 请运行 install.bat 安装 CUDA 版本的 PyTorch 以启用推理功能。")

    wp_python = find_winpython_python()
    if wp_python:
        print(f"[WinPython] 检测到 WinPython: {wp_python}")
    else:
        print("[系统] 使用当前 Python 环境运行")

    leaked = [p for p in sys.path if any(
        exclude in p.lower() for exclude in [
            "\\appdata\\",
            "\\program files\\",
            "\\programdata\\",
        ]
    )]
    if leaked:
        print(f"[WARN] 检测到系统 Python 路径泄露: {leaked}")

    _SKIP_CLEAN_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__"}
    _SKIP_CLEAN_PREFIXES = ("WPy64-", "WinPython64-", "WinPython")

    def _should_skip_dir(name: str) -> bool:
        """判断目录是否应跳过 __pycache__ 清理。

        Args:
            name: 目录名称（不含路径）。

        Returns:
            bool: 应跳过时返回 True，否则返回 False。
        """
        if name in _SKIP_CLEAN_DIRS:
            return True
        return any(name.startswith(p) for p in _SKIP_CLEAN_PREFIXES)

    cleaned_count = 0
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if not _should_skip_dir(d)]
        if "__pycache__" in dirs:
            cache_dir = os.path.join(root, "__pycache__")
            try:
                import shutil
                shutil.rmtree(cache_dir, ignore_errors=True)
                cleaned_count += 1
            except Exception:
                pass
    if cleaned_count:
        print(f"[清理] 已清理 {cleaned_count} 个项目源码 __pycache__ 目录")

    from bin.integrated_app.app_server import main as app_main
    app_main()


if __name__ == "__main__":
    sys.exit(main() or 0)

#!/usr/bin/env python3
"""SeedVR2 工具箱 - 清理缓存启动脚本（仅使用项目自带 WinPython，完全隔离）"""
import sys
import os
from pathlib import Path

# 修复 Windows 上 OMP 库重复加载问题（numpy 和 torch 各自带一份 libiomp5md.dll）
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")


def find_winpython_python():
    """查找 WinPython 中的 Python 可执行文件（仅搜索项目目录内）"""
    project_root = Path(__file__).parent.parent

    # 1. 检查 WPy64-312101 标准位置（WinPython64-3.12.10.1dot 解压后的目录名）
    wp_dir = project_root / "WPy64-312101"
    if wp_dir.exists():
        # WPy64 结构: WPy64-312101/python/python.exe
        python_exe = wp_dir / "python" / "python.exe"
        if python_exe.exists():
            return str(python_exe)
        # 备选: 搜索 python-3.x.x.amd64 子目录
        for python_dir in wp_dir.iterdir():
            if python_dir.is_dir() and python_dir.name.startswith("python-"):
                python_exe = python_dir / "python.exe"
                if python_exe.exists():
                    return str(python_exe)

    # 2. 检查 WinPython64-* 目录（计划书原始命名）
    for item in project_root.iterdir():
        if item.is_dir() and item.name.startswith("WinPython64-"):
            for python_dir in item.iterdir():
                if python_dir.is_dir() and python_dir.name.startswith("python-"):
                    python_exe = python_dir / "python.exe"
                    if python_exe.exists():
                        return str(python_exe)

    # 3. 检查通用 WinPython 目录
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

    # 4. 搜索所有 WPy64-* 目录
    for item in project_root.iterdir():
        if item.is_dir() and item.name.startswith("WPy64-"):
            for root, dirs, files in os.walk(str(item)):
                for f in files:
                    if f == "python.exe":
                        return os.path.join(root, f)

    # 5. 搜索所有 WinPython* 目录
    for item in project_root.iterdir():
        if item.is_dir() and item.name.startswith("WinPython"):
            for root, dirs, files in os.walk(str(item)):
                for f in files:
                    if f == "python.exe":
                        return os.path.join(root, f)

    return None


def setup_isolated_env():
    """设置完全隔离的环境变量，排除系统/用户 Python 干扰"""
    project_root = str(Path(__file__).parent.parent)

    # 设置 PYTHONPATH 仅包含项目目录
    os.environ["PYTHONPATH"] = project_root

    # 清除可能干扰的 Python 相关环境变量
    for var in ["PYTHONHOME", "PYTHONSTARTUP", "PYTHONIOENCODING"]:
        os.environ.pop(var, None)

    # 确保 sys.path 不包含系统/用户 Python 路径
    sys.path = [p for p in sys.path if not any(
        exclude in p.lower() for exclude in [
            "\\appdata\\",           # 用户安装的 Python 包
            "\\program files\\",     # 系统 Python
            "\\programdata\\",       # 系统 Python
        ]
    )]

    # 确保项目根目录在 sys.path 最前面
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


def main():
    # 确保项目根目录在路径中
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, project_root)
    os.chdir(project_root)

    # 设置隔离环境
    setup_isolated_env()

    # 检查当前 Python 是否有 CUDA（SeedVR2 仅支持 NVIDIA GPU）
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

    # WinPython 环境检测
    wp_python = find_winpython_python()
    if wp_python:
        print(f"[WinPython] 检测到 WinPython: {wp_python}")
    else:
        print("[系统] 使用当前 Python 环境运行")

    # 验证环境隔离
    leaked = [p for p in sys.path if any(
        exclude in p.lower() for exclude in [
            "\\appdata\\",
            "\\program files\\",
            "\\programdata\\",
        ]
    )]
    if leaked:
        print(f"[WARN] 检测到系统 Python 路径泄露: {leaked}")

    # 清理 Python 缓存（仅清理项目源码，跳过 WinPython/node_modules/.git 等）
    # PERFORMANCE (C3): 原实现遍历整个项目根目录，会删除 WPy64-*/python/Lib/site-packages
    # 下的数千个 .pyc 文件，导致下次启动时 Python 需要重新编译所有第三方库，严重拖慢启动。
    _SKIP_CLEAN_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__"}
    _SKIP_CLEAN_PREFIXES = ("WPy64-", "WinPython64-", "WinPython")

    def _should_skip_dir(name: str) -> bool:
        """判断目录是否应跳过 __pycache__ 清理"""
        if name in _SKIP_CLEAN_DIRS:
            return True
        return any(name.startswith(p) for p in _SKIP_CLEAN_PREFIXES)

    cleaned_count = 0
    for root, dirs, files in os.walk(project_root):
        # 原地修改 dirs 以跳过第三方目录，避免 os.walk 递归进入（C3 性能优化）
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

    # 启动应用
    from bin.integrated_app.app_server import main as app_main
    app_main()


if __name__ == "__main__":
    sys.exit(main() or 0)

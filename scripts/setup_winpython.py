#!/usr/bin/env python3
"""WinPython 环境检测与自动下载脚本"""
import os
import sys
import urllib.request
import logging
import platform
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent

# WinPython 目录（支持多种命名格式）
WINPYTHON_DIRS = [
    PROJECT_ROOT / "WPy64-312101",           # WinPython64-3.12.10.1dot 解压后的实际目录名
    PROJECT_ROOT / "WinPython64-3.12.10.1dot",  # 计划书原始命名
    PROJECT_ROOT / "WinPython",               # 旧版目录名
]

WINPYTHON_DOWNLOAD_URL = "https://github.com/winpython/winpython/releases/download/8.2.20240618/Winpython64-3.12.4.1.exe"


def find_winpython() -> str:
    """查找 WinPython Python 可执行文件"""
    # 1. 按优先级检查已知目录
    for wp_dir in WINPYTHON_DIRS:
        if wp_dir.exists():
            # WPy64 结构: WPy64-312101/python/python.exe
            python_exe = wp_dir / "python" / "python.exe"
            if python_exe.exists():
                return str(python_exe)

            # WinPython64 结构: WinPython64-*/python-3.x.x.amd64/python.exe
            for python_dir in wp_dir.iterdir():
                if python_dir.is_dir() and python_dir.name.startswith("python"):
                    python_exe = python_dir / "python.exe"
                    if python_exe.exists():
                        return str(python_exe)

            # 检查嵌套结构
            import os as _os
            for root, dirs, files in _os.walk(str(wp_dir)):
                for f in files:
                    if f == "python.exe":
                        return _os.path.join(root, f)

    # 2. 搜索所有 WPy64-* 和 WinPython* 目录
    for item in PROJECT_ROOT.iterdir():
        if item.is_dir() and (item.name.startswith("WPy64-") or item.name.startswith("WinPython")):
            for root, dirs, files in os.walk(str(item)):
                for f in files:
                    if f == "python.exe":
                        return os.path.join(root, f)

    # 3. 检查系统 Python
    return sys.executable


def is_winpython(python_path: str) -> bool:
    """检查是否为 WinPython 环境"""
    return "WinPython" in python_path or "WPy" in python_path


def download_winpython(target_dir: str = None) -> str:
    """下载 WinPython"""
    target_dir = target_dir or str(WINPYTHON_DIRS[0])
    os.makedirs(target_dir, exist_ok=True)

    installer_path = os.path.join(target_dir, "WinPython_installer.exe")

    if os.path.exists(installer_path):
        logger.info(f"安装包已存在: {installer_path}")
        return installer_path

    logger.info(f"正在下载 WinPython 到 {installer_path}...")
    logger.info(f"下载地址: {WINPYTHON_DOWNLOAD_URL}")

    try:
        urllib.request.urlretrieve(WINPYTHON_DOWNLOAD_URL, installer_path)
        logger.info("下载完成")
        return installer_path
    except Exception as e:
        logger.error(f"下载失败: {e}")
        logger.info("请手动下载 WinPython 并解压到项目目录下")
        logger.info(f"下载地址: {WINPYTHON_DOWNLOAD_URL}")
        return ""


def setup_environment():
    """设置运行环境"""
    python_path = find_winpython()

    print(f"Python 路径: {python_path}")
    print(f"Python 版本: {platform.python_version()}")
    print(f"是否 WinPython: {is_winpython(python_path)}")

    # 检查依赖
    requirements_path = PROJECT_ROOT / "requirements.txt"
    if requirements_path.exists():
        print(f"\n安装依赖: {requirements_path}")
        import subprocess
        result = subprocess.run(
            [python_path, "-m", "pip", "install", "-r", str(requirements_path)],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print("依赖安装完成")
        else:
            print(f"依赖安装失败: {result.stderr}")

    # 创建必要目录
    for dir_name in ["data/uploads", "outputs", "logs", "pretrained_models"]:
        dir_path = PROJECT_ROOT / dir_name
        dir_path.mkdir(parents=True, exist_ok=True)
        print(f"目录已创建: {dir_path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    setup_environment()

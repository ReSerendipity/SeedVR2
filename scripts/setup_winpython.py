#!/usr/bin/env python3
"""SeedVR2 WinPython 环境检测与自动安装脚本。

本模块用于在 Windows 平台上检测、定位并自动下载配置 WinPython 便携 Python 环境，
确保 SeedVR2 项目使用独立的 Python 运行时，避免与系统 Python 环境冲突。
同时完成项目依赖安装和必要目录结构创建。

核心技术栈:
    - Python 3.12+
    - urllib.request (HTTP 下载)
    - pathlib (路径处理)
    - subprocess (pip 依赖安装)
"""

import logging
import os
import platform
import sys
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent

# WinPython 目录（支持多种命名格式）
WINPYTHON_DIRS = [
    PROJECT_ROOT / "WPy64-312101",  # WinPython64-3.12.10.1dot 解压后的实际目录名
    PROJECT_ROOT / "WinPython64-3.12.10.1dot",  # 计划书原始命名
    PROJECT_ROOT / "WinPython",  # 旧版目录名
]

# WinPython 3.12.10.1 dot 变体（GitHub Release 资产，已验证可下载）
WINPYTHON_DOWNLOAD_URL = (
    "https://github.com/winpython/winpython/releases/download/16.5.20250614/Winpython64-3.12.10.1dotb4.exe"
)


def find_winpython() -> str:
    """查找 WinPython Python 可执行文件路径。

    按优先级顺序搜索 WinPython 安装目录：
    1. 检查预定义的已知目录名（支持 WPy64 和 WinPython64 两种目录结构）
    2. 递归搜索项目根目录下所有 WPy64-* 和 WinPython* 开头的目录
    3. 若未找到则回退到当前系统 Python 解释器

    Returns:
        str: Python 可执行文件的绝对路径。
            找到 WinPython 时返回其 python.exe 路径，否则返回 sys.executable。
    """
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

            for root, _dirs, files in _os.walk(str(wp_dir)):
                for f in files:
                    if f == "python.exe":
                        return _os.path.join(root, f)

    # 2. 搜索所有 WPy64-* 和 WinPython* 目录
    for item in PROJECT_ROOT.iterdir():
        if item.is_dir() and (item.name.startswith("WPy64-") or item.name.startswith("WinPython")):
            for root, _dirs, files in os.walk(str(item)):
                for f in files:
                    if f == "python.exe":
                        return os.path.join(root, f)

    # 3. 检查系统 Python
    return sys.executable


def is_winpython(python_path: str) -> bool:
    """检查指定路径是否为 WinPython 环境。

    Args:
        python_path: Python 可执行文件的路径字符串。

    Returns:
        bool: 如果路径中包含 "WinPython" 或 "WPy" 则返回 True，否则返回 False。
    """
    return "WinPython" in python_path or "WPy" in python_path


def download_winpython(target_dir: str = None) -> str:
    """下载 WinPython 安装包到指定目录。

    若安装包已存在则直接返回路径，避免重复下载。下载失败时记录错误日志并提示用户手动下载。

    Args:
        target_dir: 安装包保存的目标目录路径。默认为 None 时使用 WINPYTHON_DIRS[0]。

    Returns:
        str: 下载成功时返回安装包的完整路径；下载失败时返回空字符串。

    Raises:
        OSError: 目标目录创建失败时可能抛出（由 os.makedirs 触发）。
    """
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


def setup_environment() -> None:
    """设置 SeedVR2 项目运行环境。

    执行以下初始化步骤：
    1. 定位 Python 解释器并打印版本信息
    2. 检测是否为 WinPython 环境
    3. 若 requirements.txt 存在则自动安装项目依赖
    4. 创建 data/uploads、outputs、logs、model 等必要目录

    Returns:
        None
    """
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
            [python_path, "-m", "pip", "install", "-r", str(requirements_path)], capture_output=True, text=True
        )
        if result.returncode == 0:
            print("依赖安装完成")
        else:
            print(f"依赖安装失败: {result.stderr}")

    # 创建必要目录
    for dir_name in ["data/uploads", "outputs", "logs", "model"]:
        dir_path = PROJECT_ROOT / dir_name
        dir_path.mkdir(parents=True, exist_ok=True)
        print(f"目录已创建: {dir_path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    setup_environment()

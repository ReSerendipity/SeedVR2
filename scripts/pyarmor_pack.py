# SPDX-FileCopyrightText: Copyright (c) 2024-2026 ReSerendipity
# SPDX-License-Identifier: Apache-2.0
"""PyArmor 混淆评估与实施脚本 (P3 长期方案)

PyArmor 是商业 Python 代码混淆工具，对纯 Python 模块做字节码混淆，
对抗新手级逆向工程。本脚本提供评估和混淆打包的自动化流程。

适用模块 (非性能关键的编排层):
    - app_server.py        (应用入口)
    - model_manager.py     (模型管理)
    - config.py            (配置加载)
    - routes/              (API 路由)

不适用模块 (GPU/数值计算密集):
    - models/              (PyTorch C++ 扩展，PyArmor 无效)
    - common/diffusion/    (数值计算，混淆可能影响性能)

评估清单:
    1. [✓] 安全性: PyArmor 8.x 使用 AES 加密字节码 + 运行时解密
    2. [✓] 兼容性: 支持 Python 3.12 (需 PyArmor 8.5+)
    3. [⚠] 性能: 首次导入略慢 (~100ms), 运行时无影响
    4. [⚠] 成本: 商业许可 ($95/年 个人, $395/年 团队)
    5. [⚠] 局限: 可被高级逆向工程师脱壳 (与 Cython 配合使用效果更好)
    6. [✓] 部署: 生成混淆后的 .pyc + 运行时库, 不影响现有 import

使用方式:
    # 安装 PyArmor
    pip install pyarmor

    # 混淆指定模块
    python scripts/pyarmor_pack.py --targets app_server.py model_manager.py config.py

    # 混淆整个目录
    python scripts/pyarmor_pack.py --dir bin/integrated_app/routes

注意:
    - PyArmor 为商业工具，需购买许可证
    - 混淆后的代码仍可被脱壳，应与 Cython 编译配合使用
    - 本脚本仅提供自动化流程，不包含 PyArmor 许可证
"""

import argparse
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent

# 适合混淆的模块 (编排层, 非性能关键)
_DEFAULT_TARGETS = [
    "bin/integrated_app/app_server.py",
    "bin/integrated_app/model_manager.py",
    "bin/integrated_app/config.py",
    "bin/integrated_app/config_models.py",
    "bin/integrated_app/history_db.py",
    "bin/integrated_app/task_queue.py",
]


def check_pyarmor() -> bool:
    """检查 PyArmor 是否已安装。"""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pyarmor", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def obfuscate(targets: list[str], output_dir: str = "dist/obfuscated") -> None:
    """混淆指定模块。

    Args:
        targets: 待混淆的文件路径列表。
        output_dir: 输出目录。
    """
    if not check_pyarmor():
        logger.error("PyArmor 未安装。请运行: pip install pyarmor")
        sys.exit(1)

    output_path = PROJECT_ROOT / output_dir
    output_path.mkdir(parents=True, exist_ok=True)

    for target in targets:
        target_path = PROJECT_ROOT / target
        if not target_path.exists():
            logger.warning(f"文件不存在: {target_path}")
            continue

        logger.info(f"正在混淆: {target}")
        result = subprocess.run(
            [
                sys.executable, "-m", "pyarmor", "gen",
                "--output", str(output_path),
                str(target_path),
            ],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        if result.returncode == 0:
            logger.info(f"✓ 混淆完成: {target}")
        else:
            logger.error(f"✗ 混淆失败: {target}\n  {result.stderr}")


def main():
    parser = argparse.ArgumentParser(description="SeedVR2 PyArmor 混淆工具")
    parser.add_argument("--targets", nargs="+", default=_DEFAULT_TARGETS, help="待混淆文件")
    parser.add_argument("--dir", help="混淆整个目录")
    parser.add_argument("--output", default="dist/obfuscated", help="输出目录")
    parser.add_argument("--check", action="store_true", help="仅检查 PyArmor 可用性")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.check:
        if check_pyarmor():
            logger.info("✓ PyArmor 已安装")
        else:
            logger.error("✗ PyArmor 未安装")
        return

    targets = args.targets
    if args.dir:
        dir_path = PROJECT_ROOT / args.dir
        targets = [str(f.relative_to(PROJECT_ROOT)) for f in dir_path.glob("*.py")]

    obfuscate(targets, args.output)


if __name__ == "__main__":
    main()

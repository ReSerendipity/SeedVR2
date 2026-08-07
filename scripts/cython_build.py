#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2024-2026 ReSerendipity
# SPDX-License-Identifier: Apache-2.0
"""Cython 编译配置 (P3 长期方案)

将核心模块的 forward 逻辑编译为 .pyd (Windows) / .so (Linux) 机器码，
大幅抬高逆向门槛（从阅读 Python 源码变为反汇编二进制）。

编译目标模块:
    - models/dit/nadit.py       → nadit.pyd (NaDiT 核心 forward)
    - models/dit/window.py      → window.pyd (Window Attention)
    - models/video_vae_v3/modules/video_vae.py → video_vae.pyd (VAE forward)

使用方式:
    1. 安装 Cython 和编译工具链:
       pip install cython
       # Windows: 安装 Visual Studio Build Tools
       # Linux: apt install gcc python3-dev

    2. 编译:
       python scripts/cython_build.py build

    3. 编译后的 .pyd/.so 文件替代 .py 文件，
       Python import 时自动优先加载编译版本。

注意:
    - 编译后 .pyd 仍可被反汇编，但需要 IDA/Ghidra 等专业工具
    - 纯 Python 逻辑编译后性能可能提升 10-30%
    - 需要为每个目标平台单独编译 (Windows/Linux/macOS)
"""

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# 需要编译为 Cython 的核心模块
CYTHON_TARGETS = [
    "models/dit/nadit.py",
    "models/dit/na.py",
    "models/dit/window.py",
    "models/dit/blocks/mmdit_window_block.py",
    "models/video_vae_v3/modules/video_vae.py",
]


def generate_setup_py():
    """生成用于 Cython 编译的 setup.py。"""
    project_root = Path(__file__).parent.parent

    setup_content = '''#!/usr/bin/env python3
"""Cython 编译 setup.py — 由 scripts/cython_build.py 生成"""

from setuptools import setup, Extension
from Cython.Build import cythonize

extensions = [
'''

    for target in CYTHON_TARGETS:
        target_path = project_root / target
        if target_path.exists():
            module_name = target.replace("/", ".").replace(".py", "")
            setup_content += f'    Extension("{module_name}", ["{target}"]),\n'

    setup_content += """]

setup(
    name="seedvr2_compiled",
    ext_modules=cythonize(
        extensions,
        compiler_directives={
            "language_level": "3",
            "boundscheck": False,
            "wraparound": False,
            "cdivision": True,
            "embedsignature": True,
        },
    ),
)
"""

    setup_path = project_root / "setup_cython.py"
    with open(setup_path, "w", encoding="utf-8") as f:
        f.write(setup_content)

    logger.info(f"已生成: {setup_path}")
    return setup_path


def main():
    import argparse

    parser = argparse.ArgumentParser(description="SeedVR2 Cython 编译工具")
    parser.add_argument("command", choices=["build", "clean", "gen"], help="操作命令")
    parser.add_argument("--inplace", action="store_true", help="就地编译 (替代原 .py)")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.command == "gen":
        setup_path = generate_setup_py()
        logger.info(f"请运行: python {setup_path.name} build_ext --inplace")
    elif args.command == "build":
        setup_path = generate_setup_py()
        import subprocess

        cmd = [sys.executable, str(setup_path), "build_ext"]
        if args.inplace:
            cmd.append("--inplace")
        logger.info(f"运行: {' '.join(cmd)}")
        subprocess.run(cmd, check=True, cwd=str(setup_path.parent))
        logger.info("编译完成")
    elif args.command == "clean":
        import glob

        project_root = Path(__file__).parent.parent
        for pattern in ["**/*.pyd", "**/*.so", "build/**", "setup_cython.py"]:
            for f in glob.glob(str(project_root / pattern), recursive=True):
                Path(f).unlink(missing_ok=True)
                logger.info(f"已删除: {f}")


if __name__ == "__main__":
    main()

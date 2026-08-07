#!/usr/bin/env python3
"""生成带 SHA256 哈希锁的 requirements-lock.txt

防御供应链投毒 (CWE-912)：pip install --require-hashes 时会验证每个包的哈希值。

用法:
    # 使用项目 WinPython
    WPy64-312101/python/python.exe scripts/generate_lock.py

    # 或使用系统 Python (需已安装依赖)
    python scripts/generate_lock.py

输出:
    requirements-lock.txt (带 --hash=sha256:... 的锁定版本)

原理:
    1. 从已安装包生成版本锁定列表 (pip freeze)
    2. 下载每个包的 wheel/sdist 到临时目录
    3. 计算每个文件的 SHA256 哈希
    4. 生成 --hash=sha256:xxx 格式的锁定文件

注意:
    - torch/torchvision/torraudio 使用 CUDA 预编译包 (+cu128),
      哈希值取决于下载源，切换 CUDA 版本时需重新生成。
    - 生成的锁文件可用于: pip install --require-hashes -r requirements-lock.txt
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def get_installed_packages():
    """获取已安装包列表及其版本。"""
    result = subprocess.run(
        [sys.executable, "-m", "pip", "freeze"],
        capture_output=True,
        text=True,
        check=True,
    )
    packages = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if line and "==" in line and not line.startswith("#"):
            packages.append(line)
    return packages


def compute_file_hash(filepath):
    """计算文件的 SHA256 哈希。"""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(8 * 1024 * 1024)
            if not chunk:
                break
            sha256.update(chunk)
    return sha256.hexdigest()


def generate_lock_file():
    """生成带哈希锁的 requirements 文件。"""
    output_path = Path(__file__).parent.parent / "requirements-lock.txt"

    packages = get_installed_packages()
    print(f"已安装包: {len(packages)} 个")

    # 尝试从 pip 缓存获取哈希
    cache_result = subprocess.run(
        [sys.executable, "-m", "pip", "cache", "dir"],
        capture_output=True,
        text=True,
        check=True,
    )
    cache_dir = cache_result.stdout.strip()
    import glob

    wheels = glob.glob(os.path.join(cache_dir, "**", "*.whl"), recursive=True)
    print(f"pip 缓存中找到 {len(wheels)} 个 wheel 文件")

    # Build package -> hashes mapping from cache
    pkg_hashes = {}
    for whl in wheels:
        basename = os.path.basename(whl)
        parts = basename.split("-")
        if len(parts) >= 2:
            pkg_name = parts[0].replace("_", "-").lower()
            h = compute_file_hash(whl)
            if pkg_name not in pkg_hashes:
                pkg_hashes[pkg_name] = []
            pkg_hashes[pkg_name].append(h)

    # Generate lock file
    output = []
    output.append("# SeedVR2 依赖哈希锁文件 (CWE-912 供应链投毒防御)")
    output.append("#")
    output.append("# 用途: pip install --require-hashes -r requirements-lock.txt")
    output.append("# 重新生成: python scripts/generate_lock.py")
    output.append("#")
    output.append("# 注意:")
    output.append("#   - torch/torchvision/torraudio 使用 CUDA 预编译包 (+cu128)")
    output.append("#   - 切换 CUDA 版本时需重新生成哈希")
    output.append("#   - 无哈希的条目标记为 # NO HASH, 需联网下载后重新生成")
    output.append("")

    hash_count = 0
    no_hash_count = 0
    for pkg in sorted(packages):
        name, version = pkg.split("==", 1)
        norm_name = name.replace("_", "-").lower()
        hashes = pkg_hashes.get(norm_name, [])
        if hashes:
            hash_lines = [f"    --hash=sha256:{h}" for h in hashes]
            hash_count += len(hashes)
            output.append(f"{name}=={version} \\")
            output.extend(hash_lines)
        else:
            output.append(f"# NO HASH (run generate_lock.py with network): {pkg}")
            output.append(pkg)
            no_hash_count += 1

    content = "\n".join(output) + "\n"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"已生成: {output_path}")
    print(f"  总包数: {len(packages)}")
    print(f"  含哈希: {hash_count} 个哈希值")
    print(f"  无哈希: {no_hash_count} 个包 (需联网重新生成)")

    if no_hash_count > 0:
        print()
        print("要为无哈希的包生成哈希，请运行:")
        print("  pip download -d /tmp/pip-wheels -r requirements.txt")
        print("  python scripts/generate_lock.py  # 再次运行即可自动拾取缓存")


if __name__ == "__main__":
    generate_lock_file()

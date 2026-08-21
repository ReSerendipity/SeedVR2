# launcher/env_check.py
"""SeedVR2 启动器 - 环境检测（第 2 步）。

用 nvidia-smi 检测 NVIDIA GPU 与驱动/CUDA 版本（torch 未安装前也能用），
并检查安装磁盘剩余空间。纯 stdlib，可单测（mock 子进程输出）。
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

MIN_DISK_GB = 20


@dataclass
class EnvCheckResult:
    gpu_found: bool
    gpu_name: str | None
    driver_version: str | None
    cuda_version: str | None
    vram_gb: float | None
    disk_free_gb: float
    disk_ok: bool
    message: str

    def to_dict(self) -> dict:
        return {
            "gpu_found": self.gpu_found,
            "gpu_name": self.gpu_name,
            "driver_version": self.driver_version,
            "cuda_version": self.cuda_version,
            "vram_gb": self.vram_gb,
            "disk_free_gb": round(self.disk_free_gb, 1),
            "disk_ok": self.disk_ok,
            "message": self.message,
        }


def _run_nvidia_smi() -> str:
    try:
        proc = subprocess.run(
            ["nvidia-smi"], capture_output=True, text=True, timeout=15,
        )
        return proc.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _run_nvidia_mem() -> str:
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15,
        )
        return proc.stdout.strip() or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _parse_nvidia_mem(output: str) -> float | None:
    """解析显存总量（MiB → GB）。"""
    import re
    m = re.search(r"([\d.]+)\s*MiB", output)
    if not m:
        return None
    return round(float(m.group(1)) / 1024, 1)


def _parse_nvidia_smi(output: str) -> dict:
    """从 nvidia-smi 输出解析 GPU 名称与驱动/CUDA 版本。

    兼容新旧两种驱动头格式：
    - 旧：Driver Version: 572.83   CUDA Version: 13.3
    - 新：Driver Version: 572.83   CUDA UMD Version: 13.3
    """
    result = {"gpu_found": False, "gpu_name": None, "driver_version": None, "cuda_version": None}
    drv = re.search(r"Driver Version:\s*([\d.]+)", output)
    if drv:
        result["driver_version"] = drv.group(1)
    cuda = re.search(r"CUDA\s+(?:UMD\s+)?Version:\s*([\d.]+)", output)
    if cuda:
        result["cuda_version"] = cuda.group(1)
    # 真实 nvidia-smi 的 GPU 行形如 "|   0  NVIDIA GeForce RTX 3060        On  | ..."，
    # 百分比（如 30%）在名称行的下一行；名称后跟多空格列分隔或行尾。
    # 排除头部 "NVIDIA-SMI" 行（避免误把头部当 GPU 名）。
    m = re.search(r"\|\s*\d*\s*(NVIDIA(?!-SMI)(?:\s+\S+)*?)(?=\s{2,}|\s*$)", output)
    if m:
        result["gpu_found"] = True
        result["gpu_name"] = m.group(1).strip()
    return result


def _check_disk_space(path: Path) -> bool:
    usage = shutil.disk_usage(path)
    return (usage[2] / (1024**3)) >= MIN_DISK_GB


def _disk_free_gb(path: Path) -> float:
    """取磁盘剩余空间（GB）。安装目录未创建时回退到所在盘符根目录（Windows 需真实路径）。"""
    try:
        return shutil.disk_usage(path)[2] / (1024**3)
    except OSError:
        return shutil.disk_usage(path.anchor)[2] / (1024**3)


def check_env(install_dir: Path) -> EnvCheckResult:
    info = _parse_nvidia_smi(_run_nvidia_smi())
    vram_gb = _parse_nvidia_mem(_run_nvidia_mem())
    free_gb = _disk_free_gb(install_dir)
    disk_ok = free_gb >= MIN_DISK_GB

    if info["gpu_found"]:
        vram_txt = f" / 显存 {vram_gb}GB" if vram_gb else ""
        msg = f"检测到 GPU: {info['gpu_name']}{vram_txt}（驱动 {info['driver_version']} / CUDA {info['cuda_version']}）"
    else:
        msg = "未检测到 NVIDIA GPU。SeedVR2 仅支持 NVIDIA CUDA 推理，可继续但推理不可用。"

    return EnvCheckResult(
        gpu_found=info["gpu_found"],
        gpu_name=info["gpu_name"],
        driver_version=info["driver_version"],
        cuda_version=info["cuda_version"],
        vram_gb=vram_gb,
        disk_free_gb=free_gb,
        disk_ok=disk_ok,
        message=msg,
    )

"""SeedVR2 启动器 - torch 家族安装检测与校验（第 3/4 步）。

用子进程在自带 Python 中探测 torch/torchvision/torchaudio 是否可导入、
版本号与 CUDA 是否可用。torch 家族必须同源同装（同一 index），
避免 torchvision 与 torch 版本不匹配。
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

TORCH_PACKAGES = ["torch", "torchvision", "torchaudio"]

# 可切换的 PyTorch 安装源（前端镜像选择器用）
TORCH_INDEXES = {
    "pytorch-cu128": "https://download.pytorch.org/whl/cu128",
    "aliyun-cu128": "https://mirrors.aliyun.com/pytorch-wheels/cu128",
}

_PROBE_CODE = (
    "import json, importlib.util as u;"
    "r={};"
    "for p in ['torch','torchvision','torchaudio']:"
    "  r[p] = getattr(__import__(p), '__version__', None) if u.find_spec(p) else None;"
    "print(json.dumps(r))"
)
_CUDA_CODE = "import torch; print(torch.cuda.is_available())"


@dataclass
class TorchCheckResult:
    installed: bool
    versions: dict
    cuda_available: bool
    message: str


def run_python_code(python_exe: str, code: str, timeout: int = 120) -> tuple[int, str]:
    """在指定 Python 中执行代码，返回 (exit_code, stdout.strip())。"""
    try:
        proc = subprocess.run(
            [python_exe, "-c", code], capture_output=True, text=True, timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def check_torch(python_exe: str) -> TorchCheckResult:
    exit_code, out = run_python_code(python_exe, _PROBE_CODE)
    versions: dict = {}
    if exit_code == 0 and out:
        try:
            versions = json.loads(out.splitlines()[-1])
        except json.JSONDecodeError:
            versions = {}
    installed = bool(versions.get("torch"))

    cuda = False
    if installed:
        _, cuda_out = run_python_code(python_exe, _CUDA_CODE)
        cuda = cuda_out == "True"

    if installed:
        msg = f"torch {versions.get('torch')} / torchvision {versions.get('torchvision')} / torchaudio {versions.get('torchaudio')}"
        if not cuda:
            msg += "（警告：CUDA 不可用）"
    else:
        msg = "torch 未安装"
    return TorchCheckResult(installed=installed, versions=versions, cuda_available=cuda, message=msg)


def torch_install_cmd(python_exe: str, index_key: str = "pytorch-cu128") -> list[str]:
    index = TORCH_INDEXES.get(index_key, TORCH_INDEXES["pytorch-cu128"])
    return [
        python_exe, "-m", "pip", "install", "torch", "torchvision", "torchaudio",
        "--index-url", index, "--timeout", "1200", "--retries", "10",
    ]

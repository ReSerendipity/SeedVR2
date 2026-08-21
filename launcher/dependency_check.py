"""SeedVR2 启动器 - torch 家族安装检测与校验（第 3/4 步）。

用子进程在自带 Python 中探测 torch/torchvision/torchaudio 是否可导入、
版本号与 CUDA 是否可用。torch 家族必须同源同装（同一 index），
避免 torchvision 与 torch 版本不匹配。
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass

TORCH_PACKAGES = ["torch", "torchvision", "torchaudio"]

# 可切换的 PyTorch 安装源（前端镜像选择器用）
TORCH_INDEXES = {
    "pytorch-cu128": "https://download.pytorch.org/whl/cu128",
    "aliyun-cu128": "https://mirrors.aliyun.com/pytorch-wheels/cu128",
}

# 逐包 try/except：单个包（如 torch DLL）导入失败不会拖垮整个探测，
# 其它包仍能正常上报。注意必须用真实换行（-c 支持多行脚本），
# 单行里不允许 for:try: 这种复合语句嵌套。
_PROBE_CODE = "\n".join([
    "import json, importlib.util as u",
    "r = {}",
    "for p in ['torch', 'torchvision', 'torchaudio']:",
    "    try:",
    "        m = __import__(p) if u.find_spec(p) else None",
    "        r[p] = getattr(m, '__version__', None) if m else None",
    "    except Exception:",
    "        r[p] = None",
    "print(json.dumps(r))",
])
_CUDA_CODE = "import torch; print(torch.cuda.is_available())"


@dataclass
class TorchCheckResult:
    installed: bool
    versions: dict
    cuda_available: bool
    message: str


def run_python_code(python_exe: str, code: str, timeout: int = 120) -> tuple[int, str]:
    """在指定 Python 中执行代码，返回 (exit_code, 输出文本)。

    stdout 为空时回退显示 stderr，便于诊断子进程内的导入错误。
    """
    try:
        proc = subprocess.run(
            [python_exe, "-c", code],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        out = (proc.stdout or proc.stderr or "").strip()
        return proc.returncode, out
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def check_torch(python_exe: str) -> TorchCheckResult:
    """探测 torch 家族安装状态。Windows 下 torch 子进程导入偶发失败，重试 3 次。"""
    versions: dict = {}
    last_out = ""
    for _ in range(3):
        exit_code, out = run_python_code(python_exe, _PROBE_CODE)
        last_out = out
        if exit_code == 0 and out:
            try:
                parsed = json.loads(out.splitlines()[-1])
                if isinstance(parsed, dict):
                    versions = parsed
                    break
            except json.JSONDecodeError:
                versions = {}
        time.sleep(1)

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
        msg = f"torch 未安装（探测输出: {last_out[:120] or '无'}）"
    return TorchCheckResult(installed=installed, versions=versions, cuda_available=cuda, message=msg)


def torch_install_cmd(python_exe: str, index_key: str = "pytorch-cu128") -> list[str]:
    index = TORCH_INDEXES.get(index_key, TORCH_INDEXES["pytorch-cu128"])
    return [
        python_exe, "-m", "pip", "install", "torch", "torchvision", "torchaudio",
        "--index-url", index, "--timeout", "1200", "--retries", "10",
    ]

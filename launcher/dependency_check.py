"""SeedVR2 启动器 - torch 家族安装检测与校验（第 3/4 步）。

用子进程在自带 Python 中探测 torch/torchvision/torchaudio 是否可导入、
版本号与 CUDA 是否可用。torch 家族必须同源同装（同一 index），
避免 torchvision 与 torch 版本不匹配。

安装源说明（2026-08）：CUDA wheel 镜像（阿里云/清华等）的目录文件名采用
URL 编码（如 %2Bcu128），pip 的 --index-url（PEP 503 简单索引）无法把 %2B
还原成 '+cu128' 本地版本号，导致 "No matching distribution"，但文件本身可
用。因此：
  - 官方源  用 --index-url  （真实 '+cu128'，简单索引可正常解析）
  - 国内镜像 用 --find-links（直接浏览目录列出具体 WHL，绕过简单索引解析）
同时显式带 torch==x.y.z+cu123 版本约束，避免目录里同时含 CPU 版时误选。
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass

TORCH_PACKAGES = ["torch", "torchvision", "torchaudio"]

# 各 CUDA 档位的 torch 家族精确版本（三元组，每个档位显式写死，不推导）。
# 重要：同一 torch 版本在不同 cuXXX 源里配套的 torchvision 版本可能不同
#（cu128 源 wheel 发布批次更旧，torch 2.11.0 在 cu128 只配套 torchvision 0.26.0，
#  而在 cu126 配套 0.28.0）。因此必须按 (档位) 整体锁定，避免 "No matching distribution"。
# 这些数据来自 download.pytorch.org 各 cuXXX 源的实测版本列表。
TORCH_CUDA_VERSIONS = {
    "cu118": {"torch": "2.4.1", "torchvision": "0.19.1", "torchaudio": "2.4.1"},
    "cu121": {"torch": "2.5.1", "torchvision": "0.20.1", "torchaudio": "2.5.1"},
    "cu126": {"torch": "2.11.0", "torchvision": "0.28.0", "torchaudio": "2.11.0"},
    "cu128": {"torch": "2.11.0", "torchvision": "0.26.0", "torchaudio": "2.11.0"},
}

# 可切换的 PyTorch 安装源（前端镜像选择器用）。
# 结构：{ key: {"label": 展示名, "cuda": cuXXX, "index": 官方 index-url 或 None,
#               "find_links": 镜像目录或 None} }
# cuda 字段决定附加到 torch 的版本约束后缀（--find-links 模式下区分 CUDA/CPU 版用）。
TORCH_INDEXES = {
    "pytorch-cu128": {
        "label": "PyTorch 官方（CUDA 12.8）",
        "cuda": "cu128",
        "index": "https://download.pytorch.org/whl/cu128",
        "find_links": None,
    },
    "aliyun-cu128": {
        "label": "阿里云镜像（CUDA 12.8，国内更快）",
        "cuda": "cu128",
        "index": None,
        "find_links": "https://mirrors.aliyun.com/pytorch-wheels/cu128",
    },
    "aliyun-cu126": {
        "label": "阿里云镜像（CUDA 12.6）",
        "cuda": "cu126",
        "index": None,
        "find_links": "https://mirrors.aliyun.com/pytorch-wheels/cu126",
    },
    "aliyun-cu121": {
        "label": "阿里云镜像（CUDA 12.1）",
        "cuda": "cu121",
        "index": None,
        "find_links": "https://mirrors.aliyun.com/pytorch-wheels/cu121",
    },
    "aliyun-cu118": {
        "label": "阿里云镜像（CUDA 11.8，旧驱动）",
        "cuda": "cu118",
        "index": None,
        "find_links": "https://mirrors.aliyun.com/pytorch-wheels/cu118",
    },
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


def _parse_cuda_from_driver(cuda_version: str | None) -> str:
    """把 nvidia-smi 报的 CUDA 版本号映射到可用的 cuXXX 档位。

    选驱动宣称 CUDA 版本支持的最高可用档位（向下兼容旧驱动）；未识别时回退 cu128。
    返回一个 TORCH_INDEXES 中存在的 key 后缀（如 'cu128'）。
    """
    if not cuda_version:
        return "cu128"
    m = re.search(r"(\d+)\.(\d+)", cuda_version)
    if not m:
        return "cu128"
    major, minor = int(m.group(1)), int(m.group(2))
    if major >= 13 or (major >= 12 and minor >= 8):
        return "cu128"
    if major >= 12 and minor >= 6:
        return "cu126"
    if major >= 12 and minor >= 1:
        return "cu121"
    return "cu118"


def _versioned_pkg_specs(cuda: str) -> list[str]:
    """构造带 CUDA 版本约束的 torch 家族包名（避免 --find-links 误选 CPU 版）。

    版本三件套来自 TORCH_CUDA_VERSIONS（显式锁定，不推导）。
    """
    ver = TORCH_CUDA_VERSIONS.get(cuda)
    if not ver:
        return list(TORCH_PACKAGES)  # 未知档位：退回不带约束，让 pip 按兼容规则选
    return [
        f"torch=={ver['torch']}+{cuda}",
        f"torchvision=={ver['torchvision']}+{cuda}",
        f"torchaudio=={ver['torchaudio']}+{cuda}",
    ]


def recommend_cuda_index(cuda_version: str | None) -> str:
    """按驱动 CUDA 版本推荐镜像 key（前端默认选这个）。拍照 unset 走 cu128。"""
    cuda = _parse_cuda_from_driver(cuda_version)
    return f"aliyun-{cuda}"


def torch_install_cmd(python_exe: str, index_key: str = "pytorch-cu128") -> list[str]:
    cfg = TORCH_INDEXES.get(index_key, TORCH_INDEXES["pytorch-cu128"])
    cuda = cfg.get("cuda", "cu128")
    specs = _versioned_pkg_specs(cuda)

    cmd = [python_exe, "-m", "pip", "install", *specs,
           "--timeout", "1200", "--retries", "10"]
    if cfg.get("find_links"):
        cmd += ["--find-links", cfg["find_links"], "--no-index"]
    elif cfg.get("index"):
        cmd += ["--index-url", cfg["index"]]
    else:  # 兜底官方
        cmd += ["--index-url", "https://download.pytorch.org/whl/cu128"]
    return cmd

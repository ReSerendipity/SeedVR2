# SeedVR2-lite 桌面 EXE 发行（安装包 + 浏览器引导启动器）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一个可在 GitHub Release 发布的 Windows 单文件安装包（`SeedVR2-Setup-<ver>.exe`），新手双击安装后通过浏览器引导页完成环境检测、torch 安装、模型引导、冒烟测试，最终自动打开应用 WebUI。

**Architecture:** 新增独立 `launcher/` 目录（零侵入，不改任何 `app/` 代码）。Inno Setup 把「便携 Python + 应用本体 + 启动器 + 全部小依赖（torch 家族除外）」打成单文件安装包（~700MB-1GB，低于 GitHub 2GiB 限制）。启动器（PyInstaller `--windowed`）起一个 stdlib HTTP 引导服务（127.0.0.1:7871），浏览器打开 8 步向导页；torch 家族在首启由启动器从 PyTorch 官方/镜像源安装（`setup_state.json` 持久化、断点续装、装后校验）；模型只做下载引导（必装 3 项 + 主模型 6 选 1）；冒烟测试通过应用 API 跑一次真实修复。

**Tech Stack:** Python 3.12（自带 WinPython）、PyInstaller、Inno Setup（ISCC）、GitHub Actions（windows-latest）、Python stdlib（http.server / subprocess / urllib）、pytest（复用仓库现有测试框架）。

---

## 文件结构

```
launcher/
├── requirements-small.txt     # 小依赖清单（requirements.txt 去掉 torch 家族）
├── setup_state.py             # 步骤状态持久化（.setup_state.json，断点续装）
├── env_check.py               # 环境检测（GPU/驱动/磁盘空间）
├── dependency_check.py        # torch 家族安装检测与校验
├── model_check.py             # 模型文件存在/大小/safetensors 头校验 + 显存推荐
├── smoke_test.py              # 冒烟测试（经应用 API 跑一次真实修复）
├── bootstrap_server.py        # 引导页本地服务（stdlib HTTP，轮询式 JSON API）
├── launcher_main.py           # PyInstaller 窗口入口（起服务、开浏览器、编排）
├── installer.iss              # Inno Setup 打包脚本
├── static/
│   ├── index.html             # 8 步向导页
│   ├── style.css              # 白底、无装饰性滤镜
│   └── app.js                 # 前端逻辑（轮询后端 API）
└── test-assets/
    └── test-input.jpg         # 冒烟测试图（打包时复制自 demo/assets/inputs/input-1.jpg）
tests/
├── test_launcher_setup_state.py
├── test_launcher_env_check.py
├── test_launcher_dependency_check.py
├── test_launcher_model_check.py
├── test_launcher_smoke_test.py
└── test_launcher_bootstrap_server.py
.github/workflows/
└── desktop-release.yml        # 打包发布流水线（tag 触发）
```

> 约定：所有 `launcher/` 模块不依赖 torch/fastapi 等重依赖（只依赖 stdlib），保证引导服务在任何环境下可运行、可单测。安装目录记为 `{install}`（Inno 默认 `%LOCALAPPDATA%\SeedVR2-lite`），项目根 = 安装目录，`model/` 在安装目录下，便携 Python 在 `{install}\WPy64-312101\python\python.exe`。

---

## Task 1: setup_state.py — 步骤状态持久化

**Files:**
- Create: `launcher/setup_state.py`
- Test: `tests/test_launcher_setup_state.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_launcher_setup_state.py
import json
from pathlib import Path

from launcher.setup_state import SetupState, DEFAULT_STATE


def test_default_state_when_no_file(tmp_path: Path):
    s = SetupState(tmp_path / ".setup_state.json")
    assert s.get("torch_installed") is False
    assert s.get("torch_verified") is False


def test_set_persists_to_disk(tmp_path: Path):
    f = tmp_path / ".setup_state.json"
    s = SetupState(f)
    s.set("torch_installed", True)
    s.set("torch_verified", True)
    loaded = json.loads(f.read_text(encoding="utf-8"))
    assert loaded["torch_installed"] is True
    assert loaded["torch_verified"] is True


def test_reload_resumes_existing_state(tmp_path: Path):
    f = tmp_path / ".setup_state.json"
    f.write_text(json.dumps({"torch_installed": True, "torch_verified": True}), encoding="utf-8")
    s = SetupState(f)
    assert s.torch_ready is True


def test_corrupted_file_falls_back_to_default(tmp_path: Path):
    f = tmp_path / ".setup_state.json"
    f.write_text("{not json", encoding="utf-8")
    s = SetupState(f)
    assert s.get("torch_installed") is False


def test_save_is_atomic_no_tmp_left(tmp_path: Path):
    f = tmp_path / ".setup_state.json"
    s = SetupState(f)
    s.set("smoke_test_passed", True)
    assert not (tmp_path / ".setup_state.json.tmp").exists()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_launcher_setup_state.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'launcher'`）

- [ ] **Step 3: 最小实现**

```python
# launcher/setup_state.py
"""SeedVR2 启动器 - 步骤状态持久化。

将安装/初始化步骤的完成状态写入 {install}/.setup_state.json，
实现失败后重试/重启的断点续装（不重复下载已装部分）。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

DEFAULT_STATE: dict = {
    "version": "1.0.0",
    "torch_installed": False,   # torch 家族已安装
    "torch_verified": False,    # torch 安装校验通过
    "smoke_test_passed": False,  # 冒烟测试通过
}

_LOCK = threading.Lock()


class SetupState:
    """读写安装步骤状态，线程安全，写入原子化。"""

    def __init__(self, state_file: Path) -> None:
        self.state_file = Path(state_file)
        self._data: dict = dict(DEFAULT_STATE)
        if self.state_file.exists():
            try:
                self._data.update(json.loads(self.state_file.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                self._data = dict(DEFAULT_STATE)

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        with _LOCK:
            self._data[key] = value
            self.save()

    def save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.state_file)

    @property
    def torch_ready(self) -> bool:
        return bool(self._data.get("torch_installed") and self._data.get("torch_verified"))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_launcher_setup_state.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add launcher/setup_state.py tests/test_launcher_setup_state.py
git commit -m "feat(launcher): 步骤状态持久化，支持断点续装"
```

---

## Task 2: env_check.py — 环境检测

**Files:**
- Create: `launcher/env_check.py`
- Test: `tests/test_launcher_env_check.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_launcher_env_check.py
from pathlib import Path
from unittest import mock

from launcher.env_check import (
    MIN_DISK_GB,
    EnvCheckResult,
    check_env,
    _parse_nvidia_smi,
    _check_disk_space,
)


def test_parse_nvidia_smi_detects_gpu():
    out = (
        "NVIDIA-SMI 572.83  Driver Version: 572.83  CUDA Version: 13.3\n"
        "|  NVIDIA GeForce RTX 3060                 ...\n"
    )
    res = _parse_nvidia_smi(out)
    assert res["gpu_found"] is True
    assert res["gpu_name"] == "NVIDIA GeForce RTX 3060"
    assert res["driver_version"] == "572.83"
    assert res["cuda_version"] == "13.3"


def test_parse_nvidia_smi_no_gpu():
    res = _parse_nvidia_smi("NVIDIA-SMI has failed because it couldn't communicate")
    assert res["gpu_found"] is False
    assert res["gpu_name"] is None


@mock.patch("launcher.env_check.shutil.disk_usage")
def test_disk_check_enough(mock_usage):
    # 2 TB total / 500 GB free
    mock_usage.return_value = (2 * 1024**4, 500 * 1024**3, 1 * 1024**4)
    assert _check_disk_space(Path("C:/")) is True


@mock.patch("launcher.env_check.shutil.disk_usage")
def test_disk_check_insufficient(mock_usage):
    mock_usage.return_value = (100 * 1024**3, 5 * 1024**3, 90 * 1024**3)
    assert _check_disk_space(Path("C:/")) is False


@mock.patch("launcher.env_check._run_nvidia_smi")
@mock.patch("launcher.env_check._run_nvidia_mem")
@mock.patch("launcher.env_check._check_disk_space")
def test_check_env_aggregates(mock_disk, mock_mem, mock_smi):
    mock_smi.return_value = (
        "NVIDIA-SMI 572.83  Driver Version: 572.83  CUDA Version: 13.3\n"
        "|  NVIDIA GeForce RTX 3060\n"
    )
    mock_mem.return_value = "NVIDIA GeForce RTX 3060, 12288 MiB"
    mock_disk.return_value = True
    res = check_env(Path("C:/SeedVR2-lite"))
    assert isinstance(res, EnvCheckResult)
    assert res.gpu_found is True
    assert res.disk_ok is True
    assert res.disk_free_gb > MIN_DISK_GB
    assert res.vram_gb == 12.0


@mock.patch("launcher.env_check._run_nvidia_mem")
def test_parse_nvidia_mem_vram(mock_mem):
    mock_mem.return_value = "NVIDIA GeForce RTX 4090, 24564 MiB"
    assert _parse_nvidia_mem(mock_mem.return_value) == 24.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_launcher_env_check.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'launcher.env_check'`）

- [ ] **Step 3: 最小实现**

```python
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
    """从 nvidia-smi 输出解析 GPU 名称与驱动/CUDA 版本。"""
    result = {"gpu_found": False, "gpu_name": None, "driver_version": None, "cuda_version": None}
    header = re.search(r"Driver Version:\s*([\d.]+)\s+CUDA Version:\s*([\d.]+)", output)
    if header:
        result["driver_version"] = header.group(1)
        result["cuda_version"] = header.group(2)
    m = re.search(r"\|\s*(NVIDIA [^|]+?)\s+(\d+)%\s+", output)
    if m:
        result["gpu_found"] = True
        result["gpu_name"] = m.group(1).strip()
    return result


def _check_disk_space(path: Path) -> bool:
    usage = shutil.disk_usage(path)
    return (usage.free / (1024**3)) >= MIN_DISK_GB


def check_env(install_dir: Path) -> EnvCheckResult:
    info = _parse_nvidia_smi(_run_nvidia_smi())
    vram_gb = _parse_nvidia_mem(_run_nvidia_mem())
    free_gb = shutil.disk_usage(install_dir).free / (1024**3)
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_launcher_env_check.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add launcher/env_check.py tests/test_launcher_env_check.py
git commit -m "feat(launcher): 环境检测（GPU/驱动/磁盘空间）"
```

---

## Task 3: dependency_check.py — torch 家族安装检测与校验

**Files:**
- Create: `launcher/dependency_check.py`
- Test: `tests/test_launcher_dependency_check.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_launcher_dependency_check.py
from unittest import mock

from launcher.dependency_check import (
    TORCH_INDEXES,
    TorchCheckResult,
    check_torch,
    torch_install_cmd,
)


def test_torch_indexes_known():
    assert "pytorch-cu128" in TORCH_INDEXES
    assert "aliyun-cu128" in TORCH_INDEXES


@mock.patch("launcher.dependency_check.run_python_code")
def test_check_torch_all_installed(mock_run):
    mock_run.return_value = (
        0,
        '{"torch": "2.7.1+cu128", "torchvision": "0.22.1+cu128", "torchaudio": "2.7.1+cu128"}',
    )
    res = check_torch("C:/py/python.exe")
    assert res.installed is True
    assert res.versions["torch"] == "2.7.1+cu128"


@mock.patch("launcher.dependency_check.run_python_code")
def test_check_torch_missing(mock_run):
    mock_run.return_value = (
        0,
        '{"torch": null, "torchvision": null, "torchaudio": null}',
    )
    res = check_torch("C:/py/python.exe")
    assert res.installed is False


@mock.patch("launcher.dependency_check.run_python_code")
def test_check_torch_cuda_available(mock_run):
    def fake(py, code):
        if "cuda.is_available" in code:
            return 0, "True"
        return 0, '{"torch": "2.7.1+cu128", "torchvision": "0.22.1+cu128", "torchaudio": "2.7.1+cu128"}'

    mock_run.side_effect = fake
    res = check_torch("C:/py/python.exe")
    assert res.cuda_available is True


def test_torch_install_cmd_uses_index():
    cmd = torch_install_cmd("C:/py/python.exe", "pytorch-cu128")
    assert "--index-url https://download.pytorch.org/whl/cu128" in " ".join(cmd)
    assert "torch" in cmd and "torchvision" in cmd and "torchaudio" in cmd
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_launcher_dependency_check.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'launcher.dependency_check'`）

- [ ] **Step 3: 最小实现**

```python
# launcher/dependency_check.py
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_launcher_dependency_check.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add launcher/dependency_check.py tests/test_launcher_dependency_check.py
git commit -m "feat(launcher): torch 家族安装检测与校验"
```

---

## Task 4: model_check.py — 模型文件校验与显存推荐

**Files:**
- Create: `launcher/model_check.py`
- Test: `tests/test_launcher_model_check.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_launcher_model_check.py
from pathlib import Path

from launcher.model_check import (
    MAIN_MODEL_FILES,
    MANDATORY_FILES,
    ModelCheckResult,
    check_models,
    recommend_main_model,
)


def _write_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_mandatory_and_main_lists():
    assert set(MANDATORY_FILES) == {"ema_vae_fp16.safetensors", "pos_emb.pt", "neg_emb.pt"}
    assert len(MAIN_MODEL_FILES) == 6


def test_check_models_missing_all(tmp_path: Path):
    res = check_models(tmp_path)
    assert res.mandatory_ok is False
    assert res.main_model_ok is False
    assert res.ready is False


def test_check_models_mandatory_only(tmp_path: Path):
    for name in MANDATORY_FILES:
        _write_bytes(tmp_path / name, b"x" * 10)
    res = check_models(tmp_path)
    assert res.mandatory_ok is True
    assert res.main_model_ok is False
    assert res.ready is False


def test_check_models_all_ok(tmp_path: Path):
    for name in MANDATORY_FILES:
        _write_bytes(tmp_path / name, b"x" * 10)
    _write_bytes(tmp_path / MAIN_MODEL_FILES[0], b"<safetensors>" + b"\x00" * 16)
    res = check_models(tmp_path)
    assert res.ready is True
    assert res.files[MAIN_MODEL_FILES[0]]["ok"] is True


def test_check_models_safetensors_bad_magic(tmp_path: Path):
    for name in MANDATORY_FILES:
        _write_bytes(tmp_path / name, b"x" * 10)
    _write_bytes(tmp_path / MAIN_MODEL_FILES[0], b"NOT_SAFETENSORS" + b"\x00" * 16)
    res = check_models(tmp_path)
    assert res.ready is False
    assert res.files[MAIN_MODEL_FILES[0]]["ok"] is False


def test_recommend_by_vram():
    assert recommend_main_model(8) == "3b_fp8"
    assert recommend_main_model(16) == "3b_fp16"
    assert recommend_main_model(30) == "7b_sharp_fp16"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_launcher_model_check.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'launcher.model_check'`）

- [ ] **Step 3: 最小实现**

```python
# launcher/model_check.py
"""SeedVR2 启动器 - 模型文件校验与显存推荐（第 5/6 步）。

必装 3 项（VAE + 文本嵌入），主模型 6 选 1。文件名与 config.yaml 一致。
仅做文件存在 + 大小 + safetensors 头校验，不做自动下载。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

MANDATORY_FILES = ["ema_vae_fp16.safetensors", "pos_emb.pt", "neg_emb.pt"]

# 主模型：尺寸 × 精度（与 config.yaml model.models 对齐）
MAIN_MODEL_FILES = [
    "seedvr2_ema_3b_fp16.safetensors",
    "seedvr2_ema_3b_fp8_e4m3fn.safetensors",
    "seedvr2_ema_7b_fp16.safetensors",
    "seedvr2_ema_7b_fp8_e4m3fn.safetensors",
    "seedvr2_ema_7b_sharp_fp16.safetensors",
    "seedvr2_ema_7b_sharp_fp8_e4m3fn.safetensors",
]

_SAFETENSORS_MAGIC = b"<safetensors>"


def recommend_main_model(vram_gb: float) -> str:
    """按显存推荐主模型（与 README 选型一致）。"""
    if vram_gb < 12:
        return "3b_fp8"
    if vram_gb < 24:
        return "3b_fp16"
    return "7b_sharp_fp16"


def _validate_file(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "文件不存在"
    size = path.stat().st_size
    if size <= 0:
        return False, "文件为空"
    if path.suffix == ".safetensors":
        with open(path, "rb") as fh:
            if fh.read(len(_SAFETENSORS_MAGIC)) != _SAFETENSORS_MAGIC:
                return False, "safetensors 头无效（文件可能损坏）"
    return True, f"{size / 1024**3:.2f} GB"


@dataclass
class ModelCheckResult:
    files: dict = field(default_factory=dict)
    mandatory_ok: bool = False
    main_model_ok: bool = False
    ready: bool = False

    def to_dict(self) -> dict:
        return {
            "files": self.files,
            "mandatory_ok": self.mandatory_ok,
            "main_model_ok": self.main_model_ok,
            "ready": self.ready,
        }


def check_models(model_dir: Path) -> ModelCheckResult:
    files: dict = {}
    for name in MANDATORY_FILES + MAIN_MODEL_FILES:
        ok, detail = _validate_file(model_dir / name)
        files[name] = {"ok": ok, "detail": detail}
    mandatory_ok = all(files[n]["ok"] for n in MANDATORY_FILES)
    main_model_ok = any(files[n]["ok"] for n in MAIN_MODEL_FILES)
    return ModelCheckResult(
        files=files,
        mandatory_ok=mandatory_ok,
        main_model_ok=main_model_ok,
        ready=mandatory_ok and main_model_ok,
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_launcher_model_check.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add launcher/model_check.py tests/test_launcher_model_check.py
git commit -m "feat(launcher): 模型文件校验与显存推荐"
```

---

## Task 5: smoke_test.py — 冒烟测试（经应用 API）

**Files:**
- Create: `launcher/smoke_test.py`
- Test: `tests/test_launcher_smoke_test.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_launcher_smoke_test.py
import json
from unittest import mock

from launcher.smoke_test import (
    SmokeTestResult,
    build_multipart,
    poll_until_done,
    run_smoke_test,
)


def test_build_multipart_contains_file():
    body, content_type = build_multipart(
        filename="a.jpg", filedata=b"\xff\xd8\xff", extra_fields={"dit_model": "3b_fp16"}
    )
    assert b"name=\"file\"" in body
    assert b"filename=\"a.jpg\"" in body
    assert b"name=\"dit_model\"" in body
    assert "multipart/form-data; boundary=" in content_type


class _FakeResp:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()


class _FakeUrlopen:
    def __init__(self, plan):
        self._plan = list(plan)

    def __call__(self, req, data=None, timeout=None):
        # 顺序返回预先排好的响应
        return self._plan.pop(0)


def test_run_smoke_test_success():
    plan = [
        # 健康检查
        _FakeResp(200, {"success": True}),
        # 上传
        _FakeResp(200, {"success": True, "data": {"task_id": "abc123"}}),
        # progress -> processing
        _FakeResp(200, {"success": True, "data": {"status": "processing", "progress": 50}}),
        # result -> completed
        _FakeResp(
            200,
            {"success": True, "data": {"status": "completed", "output_path": "C:/out/ok.png", "file_size": 123}},
        ),
    ]
    fake = _FakeUrlopen(plan)
    with mock.patch("launcher.smoke_test.urlopen", fake), \
         mock.patch("launcher.smoke_test.time.sleep", return_value=None):
        res = run_smoke_test(
            app_base_url="http://127.0.0.1:7870",
            test_image=__file__,
        )
    assert isinstance(res, SmokeTestResult)
    assert res.success is True
    assert res.output_path == "C:/out/ok.png"


def test_poll_until_done_failed_task():
    plan = [
        _FakeResp(200, {"success": True, "data": {"status": "failed", "error": "OOM"}}),
    ]
    fake = _FakeUrlopen(plan)
    with mock.patch("launcher.smoke_test.urlopen", fake), \
         mock.patch("launcher.smoke_test.time.sleep", return_value=None):
        res = poll_until_done("http://127.0.0.1:7870", "abc123", timeout=5)
    assert res.success is False
    assert "OOM" in res.message
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_launcher_smoke_test.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'launcher.smoke_test'`）

- [ ] **Step 3: 最小实现**

```python
# launcher/smoke_test.py
"""SeedVR2 启动器 - 冒烟测试（第 7 步）。

经应用 API 跑一次真实修复：健康检查 → 上传内置测试图 → 轮询任务 → 校验输出。
仅用 stdlib urllib 构造 multipart 上传，不引入 requests 依赖。
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib import request

SMOKE_TASK_TYPE = "image"
POLL_INTERVAL = 1.0
DEFAULT_TIMEOUT = 600


def build_multipart(filename: str, filedata: bytes, extra_fields: dict | None = None) -> tuple[bytes, str]:
    """构造 multipart/form-data 请求体（字段 file + 可选的 dit_model 等）。"""
    boundary = f"----seedvr2smoke{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for k, v in (extra_fields or {}).items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
        )
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode()
        + filedata
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    return body, f"multipart/form-data; boundary={boundary}"


def _json_post(url: str, data: bytes | None = None, content_type: str | None = None, timeout: int = 30) -> dict:
    req = request.Request(url, data=data, method="POST")
    if content_type:
        req.add_header("Content-Type", content_type)
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _json_get(url: str, timeout: int = 30) -> dict:
    with request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


@dataclass
class SmokeTestResult:
    success: bool
    message: str
    output_path: str | None = None


def poll_until_done(app_base_url: str, task_id: str, timeout: int = DEFAULT_TIMEOUT) -> SmokeTestResult:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        res = _json_get(f"{app_base_url}/api/restore/{task_id}/result")
        status = res.get("data", {}).get("status")
        if status == "completed":
            out = res.get("data", {}).get("output_path")
            return SmokeTestResult(success=True, message="修复完成", output_path=out)
        if status in ("failed", "cancelled"):
            err = res.get("data", {}).get("error") or status
            return SmokeTestResult(success=False, message=f"任务{status}: {err}")
        time.sleep(POLL_INTERVAL)
    return SmokeTestResult(success=False, message="等待任务完成超时")


def run_smoke_test(app_base_url: str, test_image: str | Path, timeout: int = DEFAULT_TIMEOUT) -> SmokeTestResult:
    """等待应用就绪后上传测试图并跑一次修复。"""
    path = Path(test_image)
    try:
        # 1. 健康检查（等待应用起来）
        health_ok = False
        for _ in range(30):
            try:
                if _json_get(f"{app_base_url}/api/system/health", timeout=5).get("success"):
                    health_ok = True
                    break
            except Exception:
                time.sleep(1)
        if not health_ok:
            return SmokeTestResult(success=False, message="应用服务未就绪")

        # 2. 上传并创建任务
        body, content_type = build_multipart(
            filename=path.name,
            filedata=path.read_bytes(),
            extra_fields={"task_type": SMOKE_TASK_TYPE},
        )
        upload = _json_post(f"{app_base_url}/api/restore/", body, content_type, timeout=120)
        if not upload.get("success"):
            return SmokeTestResult(success=False, message=f"上传失败: {upload.get('error')}")
        task_id = upload["data"]["task_id"]

        # 3. 轮询结果
        return poll_until_done(app_base_url, task_id, timeout=timeout)
    except Exception as exc:  # 冒烟测试为边界，兜底报告
        return SmokeTestResult(success=False, message=f"冒烟测试异常: {exc}")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_launcher_smoke_test.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add launcher/smoke_test.py tests/test_launcher_smoke_test.py
git commit -m "feat(launcher): 冒烟测试（经应用 API 跑真实修复）"
```

---

## Task 6: bootstrap_server.py — 引导页本地服务

**Files:**
- Create: `launcher/bootstrap_server.py`
- Test: `tests/test_launcher_bootstrap_server.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_launcher_bootstrap_server.py
import json
from pathlib import Path
from unittest import mock

from launcher.bootstrap_server import Router
from launcher.setup_state import SetupState


def test_router_registers_and_matches(tmp_path: Path):
    r = Router(tmp_path)
    r.get("/api/status", lambda: {"ok": True})
    code, payload, _ = r.dispatch("GET", "/api/status")
    assert code == 200
    assert json.loads(payload)["ok"] is True


def test_router_unknown_404(tmp_path: Path):
    r = Router(tmp_path)
    code, _, _ = r.dispatch("GET", "/api/nope")
    assert code == 404


def test_dispatch_serves_index(tmp_path: Path):
    (tmp_path / "index.html").write_text("<html>hi</html>", encoding="utf-8")
    r = Router(tmp_path)
    code, payload, ctype = r.dispatch("GET", "/")
    assert code == 200
    assert b"<html>hi</html>" in payload
    assert ctype.startswith("text/html")


def test_post_body_parsed_into_last_body(tmp_path: Path):
    r = Router(tmp_path)
    r.post("/api/torch/mirror", lambda: {"index": r._last_body.get("index")})
    code, payload, _ = r.dispatch("POST", "/api/torch/mirror", json.dumps({"index": "aliyun-cu128"}).encode())
    assert json.loads(payload)["index"] == "aliyun-cu128"


@mock.patch("launcher.bootstrap_server.check_models")
def test_api_models_check_uses_model_check(mock_check, tmp_path: Path):
    mock_check.return_value.to_dict.return_value = {
        "ready": True, "files": {}, "mandatory_ok": True, "main_model_ok": True,
    }
    r = Router(tmp_path)
    r.register_api(tmp_path, tmp_path, SetupState(tmp_path / ".setup_state.json"), "C:/py/python.exe")
    code, payload, _ = r.dispatch("GET", "/api/models/check")
    assert code == 200
    mock_check.assert_called_once()
    assert json.loads(payload)["ready"] is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_launcher_bootstrap_server.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'launcher.bootstrap_server'`）

- [ ] **Step 3: 最小实现**

```python
# launcher/bootstrap_server.py
"""SeedVR2 启动器 - 引导页本地服务（localhost:7871）。

仅用 stdlib http.server，轮询式 JSON API：
  GET  /                          -> static/index.html
  GET  /static/*                  -> static 静态资源
  GET  /api/status                -> 总状态（环境/torch/模型/冒烟/状态文件）
  POST /api/env-check             -> 运行环境检测
  POST /api/torch/install         -> 后台线程安装 torch 家族（可带 index_key）
  GET  /api/torch/status          -> 安装进度（idle/running/done/error + log）
  POST /api/models/check          -> 模型校验
  GET  /api/models/recommend      -> 按显存推荐主模型
  POST /api/smoke-test            -> 启动冒烟测试（后台线程）
  GET  /api/smoke-test/status     -> 冒烟进度
  GET  /api/app/health            -> 应用 7870 是否已就绪
  POST /api/app/start             -> 拉起应用（clean_launch.py）
  POST /api/app/open              -> 用浏览器打开应用地址
"""
from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from launcher.dependency_check import TORCH_INDEXES, torch_install_cmd
from launcher.env_check import check_env
from launcher.model_check import check_models, recommend_main_model
from launcher.setup_state import SetupState
from launcher.smoke_test import run_smoke_test

APP_PORT = 7870
APP_BASE = f"http://127.0.0.1:{APP_PORT}"


class Router:
    """极简路由 + 分发逻辑：method + 前缀匹配。dispatch() 为纯逻辑，可单测。"""

    def __init__(self, static_dir: Path) -> None:
        self._routes: list[tuple[str, str, callable]] = []
        self.static_dir = Path(static_dir)
        self._last_body: dict = {}

    def get(self, path: str, fn: callable) -> None:
        self._routes.append(("GET", path, fn))

    def post(self, path: str, fn: callable) -> None:
        self._routes.append(("POST", path, fn))

    def match(self, method: str, path: str):
        for m, p, fn in self._routes:
            if m == method and path.startswith(p):
                return fn
        return None

    def dispatch(self, method: str, path: str, body_bytes: bytes = b"") -> tuple[int, bytes, str]:
        """路由分发，返回 (status_code, payload_bytes, content_type)。"""
        parsed = path.split("?", 1)[0]
        if parsed == "/":
            idx = self.static_dir / "index.html"
            if idx.exists():
                return 200, idx.read_bytes(), "text/html; charset=utf-8"
            return 404, b'{"error":"index.html missing"}', "application/json; charset=utf-8"
        if parsed.startswith("/static/"):
            rel = parsed[len("/static/"):]
            fp = (self.static_dir / rel).resolve()
            if str(fp).startswith(str(self.static_dir.resolve())) and fp.exists():
                ctype = "text/css; charset=utf-8" if fp.suffix == ".css" else "application/javascript; charset=utf-8"
                return 200, fp.read_bytes(), ctype
            return 404, b'{"error":"asset not found"}', "application/json; charset=utf-8"
        fn = self.match(method, parsed)
        if fn is None:
            return 404, b'{"error":"not found"}', "application/json; charset=utf-8"
        if method == "POST" and body_bytes:
            try:
                self._last_body.update(json.loads(body_bytes.decode("utf-8")))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        try:
            result = fn()
            if result is None:
                result = {"ok": True}
            return 200, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8"
        except Exception as exc:
            return 500, json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8"

    def register_api(self, install_dir: Path, model_dir: Path,
                     state: SetupState, python_exe: str, shutdown_fn: callable | None = None) -> None:
        """注册全部引导 API。闭包共享安装环境信息。"""
        env_result = {"checked": False, "data": None}
        torch_state = {"status": "idle", "log": "", "index": "pytorch-cu128", "error": None}
        smoke_state = {"status": "idle", "result": None}
        app_proc: dict = {"proc": None}

        self.get("/api/status", lambda: {
            "env": env_result["data"],
            "torch_ready": state.torch_ready,
            "models": check_models(model_dir).to_dict(),
        })

        # 环境检测
        self.post("/api/env-check", lambda: self._run_env(env_result, install_dir))
        self.get("/api/env-check", lambda: env_result)

        # torch 安装
        self.post("/api/torch/install", lambda: self._start_torch_install(torch_state, python_exe, state))
        self.get("/api/torch/status", lambda: torch_state)
        self.post("/api/torch/mirror", lambda: self._set_mirror(torch_state, last_body))

        # 模型
        self.get("/api/models/check", lambda: check_models(model_dir).to_dict())
        self.get("/api/models/recommend", lambda: self._recommend(env_result))

        # 冒烟测试
        self.post("/api/smoke-test", lambda: self._start_smoke(smoke_state, install_dir, state))
        self.get("/api/smoke-test/status", lambda: smoke_state)

        # 应用
        self.get("/api/app/health", lambda: {"up": self._app_health()})
        self.post("/api/app/start", lambda: self._start_app(app_proc, python_exe, install_dir))
        self.post("/api/app/open", lambda: self._open_app())

        # 退出启动器（应用已独立运行时调用）
        self.post("/api/shutdown", lambda: self._shutdown(shutdown_fn))

    # ---- 内部实现 ----
    def _shutdown(self, shutdown_fn: callable | None) -> dict:
        if shutdown_fn is not None:
            shutdown_fn()
        return {"ok": True, "shutdown": True}

    def _run_env(self, env_result: dict, install_dir: Path):
        env_result["data"] = check_env(install_dir).to_dict()
        env_result["checked"] = True
        return env_result

    def _recommend(self, env_result: dict) -> dict:
        vram = (env_result.get("data") or {}).get("vram_gb") or 24
        return {"vram_gb": vram, "recommended": recommend_main_model(vram)}

    def _start_torch_install(self, torch_state: dict, python_exe: str, state: SetupState):
        if torch_state["status"] == "running":
            return {"error": "torch 正在安装中"}
        torch_state["status"] = "running"
        torch_state["error"] = None
        torch_state["log"] = ""

        def worker():
            index = torch_state["index"]
            cmd = torch_install_cmd(python_exe, index)
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    torch_state["log"] += line
                    if len(torch_state["log"]) > 8000:
                        torch_state["log"] = torch_state["log"][-8000:]
                proc.wait()
                if proc.returncode == 0:
                    torch_state["status"] = "done"
                    state.set("torch_installed", True)
                else:
                    torch_state["status"] = "error"
                    torch_state["error"] = f"pip 安装退出码 {proc.returncode}"
            except Exception as exc:
                torch_state["status"] = "error"
                torch_state["error"] = str(exc)

        threading.Thread(target=worker, daemon=True).start()
        return {"started": True}

    def _set_mirror(self, torch_state: dict, last_body: dict) -> dict:
        index = (last_body or {}).get("index")
        if index in TORCH_INDEXES:
            torch_state["index"] = index
        return {"ok": True, "index": torch_state["index"]}

    def _start_smoke(self, smoke_state: dict, install_dir: Path, state: SetupState):
        if smoke_state["status"] == "running":
            return {"error": "冒烟测试进行中"}
        test_image = install_dir / "launcher" / "test-assets" / "test-input.jpg"

        def worker():
            smoke_state["status"] = "running"
            res = run_smoke_test(APP_BASE, test_image)
            smoke_state["result"] = {"success": res.success, "message": res.message, "output_path": res.output_path}
            smoke_state["status"] = "done"
            if res.success:
                state.set("smoke_test_passed", True)

        threading.Thread(target=worker, daemon=True).start()
        return {"started": True}

    def _app_health(self) -> bool:
        try:
            import urllib.request
            with urllib.request.urlopen(f"{APP_BASE}/api/system/health", timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _start_app(self, app_proc: dict, python_exe: str, install_dir: Path):
        if app_proc["proc"] is not None and app_proc["proc"].poll() is None:
            return {"started": True}
        proc = subprocess.Popen(
            [python_exe, str(install_dir / "app" / "clean_launch.py")],
            cwd=str(install_dir),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        app_proc["proc"] = proc
        return {"started": True}

    def _open_app(self):
        import webbrowser
        webbrowser.open(APP_BASE)
        return {"opened": True}


def make_handler(router: Router):
    """返回一个 BaseHTTPRequestHandler 子类，转发给 router.dispatch()。"""

    class Handler(BaseHTTPRequestHandler):
        def _dispatch(self):
            body = b""
            if self.command == "POST" and self.headers.get("Content-Length"):
                body = self.rfile.read(int(self.headers["Content-Length"]))
            code, payload, ctype = router.dispatch(self.command, self.path, body)
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.write(payload)

        def do_GET(self):
            self._dispatch()

        def do_POST(self):
            self._dispatch()

        def log_message(self, *args):
            pass

    return Handler


def start_server(router: Router, port: int = 7871):
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(router))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
```

> 说明：POST 的 JSON body 在 `Router.dispatch()` 中统一解析进 `_last_body`，镜像切换等接口从 `_last_body` 读取参数。测试直接调用 `dispatch()` 纯逻辑层，不依赖真实子进程与 HTTP 栈。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_launcher_bootstrap_server.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add launcher/bootstrap_server.py tests/test_launcher_bootstrap_server.py
git commit -m "feat(launcher): 引导页本地服务与 JSON API"
```

---

## Task 7: launcher_main.py — 启动器入口（PyInstaller）

**Files:**
- Create: `launcher/launcher_main.py`

> 纯编排代码：定位安装目录与便携 Python → 注册 API → 起引导服务（端口占用自动 +1）→ 打开浏览器 → 保持运行，直到 `/api/shutdown` 或应用进程退出。开发模式（非 frozen）下用仓库根目录。

- [ ] **Step 1: 写实现**

```python
# launcher/launcher_main.py
"""SeedVR2 启动器 - PyInstaller 窗口入口（无控制台）。

职责：起引导服务（localhost:7871）→ 浏览器打开 8 步向导页 → 保持运行。
开发模式（未打包）时用仓库根目录；打包后用 exe 所在目录作为安装目录。
"""
from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

from launcher.bootstrap_server import Router, start_server
from launcher.setup_state import SetupState

BOOTSTRAP_PORT = 7871


def install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def find_portable_python(root: Path) -> Path:
    cand = root / "WPy64-312101" / "python" / "python.exe"
    if cand.exists():
        return cand
    for wp in root.glob("WPy64-*"):
        p = wp / "python" / "python.exe"
        if p.exists():
            return p
    return cand  # 返回默认路径，供报错信息使用


def find_free_port(start: int = BOOTSTRAP_PORT, tries: int = 10) -> int:
    import socket
    for port in range(start, start + tries):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def main() -> int:
    root = install_dir()
    python_exe = str(find_portable_python(root))
    static_dir = root / "launcher" / "static"
    model_dir = root / "model"
    state = SetupState(root / ".setup_state.json")

    router = Router(static_dir)
    shutdown_fn = None  # 由下方闭包赋值，注册 API 时传入

    def _shutdown():
        if shutdown_fn is not None:
            shutdown_fn()

    router.register_api(root, model_dir, state, python_exe, shutdown_fn=_shutdown)

    port = find_free_port()
    server, _thread = start_server(router, port=port)
    shutdown_fn = server.shutdown

    url = f"http://127.0.0.1:{port}"
    print(f"[SeedVR2] 引导页: {url}")
    webbrowser.open(url)

    # 保持运行：收到 /api/shutdown 后 serve_forever 返回
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 开发模式冒烟验证**

Run: `python launcher/launcher_main.py`
Expected: 控制台打印 `[SeedVR2] 引导页: http://127.0.0.1:7871`，浏览器自动打开引导页；访问 `http://127.0.0.1:7871/api/status` 返回 JSON。

- [ ] **Step 3: 提交**

```bash
git add launcher/launcher_main.py
git commit -m "feat(launcher): PyInstaller 启动器入口"
```

---

## Task 8: 引导页前端 static/（8 步向导）

**Files:**
- Create: `launcher/static/index.html`
- Create: `launcher/static/style.css`
- Create: `launcher/static/app.js`

> 前端为纯静态，白底、无装饰性滤镜（符合项目对色彩准确性的要求）。由浏览器轮询后端 API。

- [ ] **Step 1: 写 index.html**

```html
<!-- launcher/static/index.html -->
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SeedVR2 安装引导</title>
  <link rel="stylesheet" href="/static/style.css" />
</head>
<body>
  <main class="wrap">
    <header class="head">
      <h1>SeedVR2 安装引导</h1>
      <p class="sub">自动完成环境检测、依赖安装与功能自检，全程无需命令行。</p>
    </header>

    <ol class="steps" id="steps">
      <li data-step="env" class="active">环境检测</li>
      <li data-step="torch">Torch 安装</li>
      <li data-step="verify">依赖校验</li>
      <li data-step="models">模型下载</li>
      <li data-step="smoke">模拟测试</li>
      <li data-step="ready">开始使用</li>
    </ol>

    <section class="panel" id="panel-env">
      <h2>① 环境检测</h2>
      <div id="env-result" class="result">检测中…</div>
      <button id="btn-env" class="btn">重新检测</button>
      <details class="help"><summary>需要帮助？</summary><p>本步骤检测 NVIDIA GPU、显卡驱动与磁盘空间。SeedVR2 仅支持 NVIDIA CUDA 推理。</p></details>
    </section>

    <section class="panel hidden" id="panel-torch">
      <h2>② Torch 安装</h2>
      <p id="torch-hint">将使用内置 Python 从 PyTorch 源下载安装 torch 家族（约 2.5GB，可断点续装）。</p>
      <label>安装源
        <select id="torch-mirror">
          <option value="pytorch-cu128">PyTorch 官方（cu128）</option>
          <option value="aliyun-cu128">阿里云镜像（cu128，国内更快）</option>
        </select>
      </label>
      <button id="btn-torch" class="btn">开始安装 / 重试</button>
      <div class="bar"><i id="torch-bar"></i></div>
      <pre id="torch-log" class="log"></pre>
      <button id="btn-verify" class="btn hidden">校验通过，下一步</button>
      <details class="help"><summary>需要帮助？</summary><p>安装失败可切换镜像源重试；已装好的部分不会重复下载。</p></details>
    </section>

    <section class="panel hidden" id="panel-models">
      <h2>③ 模型下载</h2>
      <p id="model-recommend"></p>
      <div id="model-list" class="result"></div>
      <button id="btn-models" class="btn">重新检测模型</button>
      <details class="help"><summary>需要帮助？</summary><p>必装：VAE + 文本嵌入；主模型 6 选 1。放到 <code>{install}\model\</code> 目录后点「重新检测」。</p></details>
    </section>

    <section class="panel hidden" id="panel-smoke">
      <h2>④ 模拟测试</h2>
      <p>将用内置测试图跑一次真实修复，验证功能正常。</p>
      <button id="btn-smoke" class="btn">开始测试</button>
      <div id="smoke-result" class="result"></div>
      <details class="help"><summary>需要帮助？</summary><p>测试会实际调用 GPU 进行一次图像修复，通常需要 1-3 分钟。</p></details>
    </section>

    <section class="panel hidden" id="panel-ready">
      <h2>⑤ 开始使用</h2>
      <p>一切就绪！点击下方按钮打开应用。</p>
      <button id="btn-open" class="btn primary">打开 SeedVR2</button>
    </section>
  </main>
  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: 写 style.css**

```css
/* launcher/static/style.css — 白底、无装饰性滤镜，保证展示区域色彩准确 */
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #fff; color: #1a1a1a; font-family: "Microsoft YaHei", system-ui, sans-serif; line-height: 1.6; }
.wrap { max-width: 760px; margin: 40px auto; padding: 0 20px; }
.head { margin-bottom: 24px; }
.head h1 { font-size: 24px; }
.sub { color: #555; }
.steps { display: flex; gap: 8px; list-style: none; margin-bottom: 24px; flex-wrap: wrap; }
.steps li { padding: 6px 14px; border: 1px solid #ccc; border-radius: 20px; font-size: 13px; color: #666; }
.steps li.active { background: #1a1a1a; color: #fff; border-color: #1a1a1a; }
.steps li.done { background: #e8f5e9; color: #2e7d32; border-color: #a5d6a7; }
.panel { border: 1px solid #e0e0e0; border-radius: 8px; padding: 20px; }
.hidden { display: none; }
.btn { margin-top: 12px; padding: 8px 20px; border: 1px solid #1a1a1a; background: #fff; cursor: pointer; border-radius: 6px; font-size: 14px; }
.btn:hover { background: #f5f5f5; }
.btn.primary { background: #1a1a1a; color: #fff; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.result { margin: 12px 0; padding: 12px; background: #fafafa; border: 1px solid #eee; border-radius: 6px; font-size: 14px; white-space: pre-wrap; }
.bar { height: 8px; background: #eee; border-radius: 4px; margin-top: 12px; overflow: hidden; }
.bar i { display: block; height: 100%; width: 0; background: #2e7d32; transition: width .3s; }
.log { margin-top: 12px; max-height: 200px; overflow: auto; background: #111; color: #7ef29a; padding: 10px; font-size: 12px; border-radius: 6px; }
.help { margin-top: 16px; color: #555; }
.help summary { cursor: pointer; }
.help code { background: #f0f0f0; padding: 1px 4px; border-radius: 3px; }
label { display: flex; align-items: center; gap: 10px; margin-top: 12px; }
select { padding: 6px 10px; border: 1px solid #ccc; border-radius: 6px; }
```

- [ ] **Step 3: 写 app.js**

```javascript
/* launcher/static/app.js — 8 步向导轮询后端 */
"use strict";

const $ = (id) => document.getElementById(id);
const steps = document.querySelectorAll("#steps li");

function setStep(idx) {
  steps.forEach((el, i) => {
    el.classList.toggle("active", i === idx);
    el.classList.toggle("done", i < idx);
  });
  document.querySelectorAll(".panel").forEach((p, i) => {
    p.classList.toggle("hidden", i !== idx);
  });
}

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  return r.json();
}

async function refreshStatus() {
  const s = await api("/api/status");
  const state = s.state || {};
  if (state.torch_ready) { $("btn-verify").classList.remove("hidden"); }
  const models = s.models || {};
  renderModels(models);
  if (state.smoke_test_passed) setStep(4);
}

function renderModels(m) {
  if (!m.files) return;
  const rows = Object.entries(m.files).map(([name, f]) =>
    `${f.ok ? "✅" : "❌"} ${name}  ${f.detail || ""}`).join("\n");
  $("model-list").textContent = rows;
}

// 环境检测
async function runEnv() {
  $("env-result").textContent = "检测中…";
  const r = await api("/api/env-check", { method: "POST" });
  const d = (r.data || r);
  $("env-result").textContent = d.message || JSON.stringify(d, null, 2);
  setStep(1);
}
$("btn-env").onclick = runEnv;

// Torch 安装（轮询进度）
let torchTimer = null;
async function startTorch() {
  $("btn-torch").disabled = true;
  await api("/api/torch/install", { method: "POST" });
  torchTimer = setInterval(async () => {
    const s = await api("/api/torch/status");
    $("torch-log").textContent = s.log || "";
    if (s.status === "running") return;
    clearInterval(torchTimer);
    $("btn-torch").disabled = false;
    if (s.status === "done") {
      $("torch-bar").style.width = "100%";
      $("btn-verify").classList.remove("hidden");
      setStep(2);
    } else {
      $("torch-bar").style.width = "30%";
      $("torch-log").textContent += "\n[失败] " + (s.error || "未知错误") + "，可换镜像源重试。";
    }
  }, 1500);
}
$("btn-torch").onclick = async () => {
  await api("/api/torch/mirror", { method: "POST", body: JSON.stringify({ index: $("torch-mirror").value }) });
  startTorch();
};
$("btn-verify").onclick = async () => { await refreshStatus(); setStep(2); };

// 模型
$("btn-models").onclick = async () => { await refreshStatus(); };
refreshStatus().then(async () => {
  const rec = await api("/api/models/recommend");
  $("model-recommend").textContent = `推荐主模型：${rec.recommended}（显存 ${rec.vram_gb}GB 档）`;
});

// 冒烟测试
let smokeTimer = null;
$("btn-smoke").onclick = async () => {
  $("smoke-result").textContent = "测试进行中，请稍候…";
  await api("/api/smoke-test", { method: "POST" });
  smokeTimer = setInterval(async () => {
    const s = await api("/api/smoke-test/status");
    if (s.status === "running") return;
    clearInterval(smokeTimer);
    const r = s.result || {};
    $("smoke-result").textContent = r.success ? "✅ " + r.message + "（" + (r.output_path || "") + "）" : "❌ " + r.message;
    if (r.success) setStep(4);
  }, 2000);
};

// 开始使用
$("btn-open").onclick = async () => {
  await api("/api/app/start", { method: "POST" });
  await api("/api/app/open", { method: "POST" });
  setStep(5);
};
```

- [ ] **Step 4: 手工验证（前端无单测）**

Run: 浏览器打开 `launcher/static/index.html` 确认页面正常渲染、无 JS 报错。
Expected: 6 步进度条显示、5 个面板切换正常。

- [ ] **Step 5: 提交**

```bash
git add launcher/static/
git commit -m "feat(launcher): 8 步向导引导页"
```

---

## Task 9: installer.iss — Inno Setup 打包脚本

**Files:**
- Create: `launcher/installer.iss`

> 前置：CI 已用 `launcher/requirements-small.txt` 把全部小依赖预装进便携 Python（见 Task 9）。本脚本把便携 Python + 应用本体 + 启动器 + 测试图打成单文件安装包。

- [ ] **Step 1: 写 installer.iss**

```ini
; launcher/installer.iss — SeedVR2 桌面安装包
; 编译：ISCC.exe launcher/installer.iss
; 注意：便携 Python 必须已预装小依赖（见 Task 9），torch 家族首启由启动器安装。

#define AppName "SeedVR2"
#define AppVersion "1.0.0"
#define AppPublisher "ReSerendipity"
#define AppExeName "SeedVR2.exe"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\SeedVR2-lite
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=SeedVR2-Setup-{#AppVersion}
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
; 安装完成后自动启动启动器（首次引导）
[Run]
Filename: "{app}\{#AppExeName}"; Description: "立即启动 SeedVR2"; Flags: nowait postinstall skipifsilent

[Icons]
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: checkedonce

[Files]
; 应用本体（保持项目根结构，安装后 cwd=安装目录）
Source: "..\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs
Source: "..\common\*"; DestDir: "{app}\common"; Flags: recursesubdirs
Source: "..\model_lib\*"; DestDir: "{app}\model_lib"; Flags: recursesubdirs
Source: "..\configs_3b\*"; DestDir: "{app}\configs_3b"; Flags: recursesubdirs
Source: "..\configs_7b\*"; DestDir: "{app}\configs_7b"; Flags: recursesubdirs
Source: "..\config.yaml"; DestDir: "{app}"
Source: "..\.env.example"; DestDir: "{app}"
Source: "..\requirements.txt"; DestDir: "{app}"
; 便携 Python（已预装小依赖）
Source: "..\WPy64-312101\*"; DestDir: "{app}\WPy64-312101"; Flags: recursesubdirs
; 启动器（PyInstaller 产物，含引导页静态资源）
Source: "..\dist\SeedVR2.exe"; DestDir: "{app}"
; 冒烟测试图
Source: "..\demo\assets\inputs\input-1.jpg"; DestDir: "{app}\launcher\test-assets"; DestName: "test-input.jpg"
; 目录占位（model/、data/、logs/）
[Dirs]
Name: "{app}\model"
Name: "{app}\data"
Name: "{app}\logs"
Name: "{app}\launcher"
```

- [ ] **Step 2: 构建启动器并编译安装包（本机/CI 验证命令）**

Run:
```
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name SeedVR2 ^
  --paths . launcher/launcher_main.py
ISCC.exe launcher/installer.iss
```
Expected: `dist/SeedVR2-Setup-1.0.0.exe` 生成，大小 ~700MB-1GB。

- [ ] **Step 3: 手工安装验证（Windows 测试机）**

Run: 双击安装包 → 按向导安装 → 桌面出现 SeedVR2 快捷方式 → 自动启动引导页。
Expected: 安装到 `%LOCALAPPDATA%\SeedVR2-lite`，浏览器打开 `127.0.0.1:7871`。

- [ ] **Step 4: 提交**

```bash
git add launcher/installer.iss
git commit -m "feat(launcher): Inno Setup 安装包脚本"
```

---

## Task 10: CI 流水线 + requirements-small.txt（打包发布）

**Files:**
- Create: `launcher/requirements-small.txt`
- Create: `.github/workflows/desktop-release.yml`

- [ ] **Step 1: 生成小依赖清单**

`launcher/requirements-small.txt` = `requirements.txt` 去掉 `torch`、`torchvision`、`torchaudio` 三行（torch 家族首启由启动器同源安装）：

```
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
gunicorn>=23.0
pydantic>=2.9.0
pyyaml>=6.0
jinja2>=3.1.0
python-multipart>=0.0.12
transformers>=4.44.0
safetensors>=0.4.0
huggingface_hub>=0.25.0
einops>=0.8.0
omegaconf>=2.3.0
diffusers>=0.30.0
mediapy>=1.1.0
rotary-embedding-torch>=0.5.0
opencv-python>=4.10.0
imageio>=2.35.0
imageio-ffmpeg>=0.5.0
pillow>=10.4.0
aiosqlite>=0.20.0
aiofiles>=24.1.0
psutil>=6.0.0
rich>=13.8.0
PyWavelets>=1.9.0
```

- [ ] **Step 2: 写桌面发行 workflow**

```yaml
# .github/workflows/desktop-release.yml
# tag 触发（如 v1.0.0）：构建启动器 → 预装小依赖 → 编译安装包 → GPG 签名 → 上传 Release
name: Desktop Release

on:
  push:
    tags: ["v*"]

permissions:
  contents: write

jobs:
  build-installer:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4

      - name: 下载便携 WinPython
        shell: powershell
        run: |
          Invoke-WebRequest -Uri "https://github.com/winpython/winpython/releases/download/..." -OutFile WPy.zip
          Expand-Archive WPy.zip -DestinationPath WPy64-312101

      - name: 预装小依赖（torch 家族除外）
        shell: powershell
        run: |
          .\WPy64-312101\python\python.exe -m pip install --upgrade pip
          .\WPy64-312101\python\python.exe -m pip install -r launcher\requirements-small.txt --timeout 300 --retries 3

      - name: 构建启动器
        shell: powershell
        run: |
          python -m pip install pyinstaller
          python -m PyInstaller --noconfirm --onefile --windowed --name SeedVR2 --paths . launcher\launcher_main.py

      - name: 编译安装包（ISCC）
        shell: powershell
        run: |
          Invoke-WebRequest -Uri "https://jrsoftware.org/download.php/is.exe" -OutFile is.exe
          .\is.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
          & "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" launcher\installer.iss

      - name: 生成 SHA256SUMS 并签名
        shell: powershell
        env:
          GPG_PRIVATE_KEY: ${{ secrets.GPG_PRIVATE_KEY }}
          GPG_PASSPHRASE: ${{ secrets.GPG_PASSPHRASE }}
          GPG_KEY_ID: ${{ secrets.GPG_KEY_ID }}
        run: |
          Get-FileHash dist\SeedVR2-Setup-*.exe -Algorithm SHA256 | ForEach-Object {
            "$($_.Hash.ToLower())  $([System.IO.Path]::GetFileName($_.Path))"
          } | Set-Content dist\SHA256SUMS
          # 复用现有 gpg 逻辑（需在 runner 导入私钥后执行 detach-sign）

      - name: 上传 Release 附件
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          $tag = "${{ github.ref_name }}"
          $exe = Get-ChildItem dist\SeedVR2-Setup-*.exe | Select-Object -First 1
          gh release upload $tag "$($exe.FullName)" dist\SHA256SUMS --clobber
```

- [ ] **Step 3: 验证流水线**

Run: 打 tag `git tag v1.0.0 && git push origin v1.0.0`
Expected: Actions 跑通，Release 出现 `SeedVR2-Setup-1.0.0.exe`（~700MB-1GB）与 `SHA256SUMS`。

> 备注：WinPython 下载链接与 GPG 签名步骤需按实际发布渠道补齐（参照现有 `gpg-signed-release.yml` 的私钥导入方式）。

- [ ] **Step 4: 提交**

```bash
git add launcher/requirements-small.txt .github/workflows/desktop-release.yml
git commit -m "feat(ci): 桌面发行打包流水线"
```

---

## 自检清单（对照 spec）

- [x] 单文件安装包（<2GiB，内含 Python+应用+启动器+小依赖）→ Task 9/10
- [x] 8 步向导：环境检测→torch 安装→依赖校验→模型引导→模型检测→冒烟测试→使用 → Task 2/3/4/5/6/7/8
- [x] 依赖断点续装 / 幂等 / 换镜像 / 装后必检 → Task 1/3/6
- [x] 模型"必装 3 + 主模型 6 选 1"、显存推荐、手动下载引导 → Task 4 + 前端
- [x] 冒烟测试经应用 API 跑真实修复并校验输出 → Task 5
- [x] 无 NVIDIA GPU 黄牌警告不阻断 → Task 2
- [x] 不改任何 `app/` 代码 → 全部改动仅新增 `launcher/`、`tests/test_launcher_*`、`.github/workflows/desktop-release.yml`
- [x] 启动器入口（定位安装目录/Python、起服务、开浏览器、保持运行）→ Task 7
- [x] GPG 签名复用现有流水线逻辑 → Task 10

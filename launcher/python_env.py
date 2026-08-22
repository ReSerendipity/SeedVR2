"""SeedVR2 启动器 - Python 运行环境探测（供用户三选一）。

探测三类可用 Python 环境，供引导页运行环境选择：
  1. 项目虚拟环境   {root}/.venv/Scripts/python.exe
  2. 系统 Python    PATH 里可用的 python.exe（排除项目 .venv/WinPython 自身）
  3. 内置 WinPython {root}/WPy64-*/ 下找到的 python.exe

纯 stdlib，可单测（mock 子进程输出）。
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from launcher.setup_state import SetupState


@dataclass
class PyEnv:
    """一个可选的 Python 运行环境。"""
    id: str          # ".venv" / "system" / "winpython"
    label: str       # 展示名
    path: str        # python.exe 绝对路径
    detect_msg: str  # 探测过程信息（版本等），无用时为空串

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "path": self.path, "detect_msg": self.detect_msg}


def _has_venv_python(root: Path) -> Path | None:
    p = root / ".venv" / "Scripts" / "python.exe"
    return p if p.exists() else None


def _winpython_python(root: Path) -> Path | None:
    for base in [root / "WPy64-312101", *sorted(root.glob("WPy64-*")), *sorted(root.glob("WinPython64-*"))]:
        for cand in [
            base / "python" / "python.exe",
            *[pd / "python.exe" for pd in base.glob("python-*.amd64")],
        ]:
            if cand.exists():
                return cand
    return None


def _system_python(root: Path) -> Path | None:
    """探测 PATH 里的系统 Python（排除项目自身的 .venv / WinPython）。"""
    try:
        proc = subprocess.run(
            ["where", "python"], capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        cand = line.strip()
        if not cand or not cand.lower().endswith("python.exe"):
            continue
        low = cand.lower()
        if ".venv" in low or "wpy" in low or "winpython" in low:
            continue  # 排除项目自身的便携/虚拟环境
        return Path(cand)
    return None


def _python_version(python_exe: Path) -> str:
    try:
        proc = subprocess.run(
            [str(python_exe), "--version"], capture_output=True, text=True, timeout=10,
        )
        out = (proc.stdout or proc.stderr or "").strip()
        return out if out else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def detect_python_envs(root: Path, state: SetupState) -> list[PyEnv]:
    """返回当前可选的运行环境列表（按探测到的顺序）。包内含 torch 与否不在此判断。"""
    envs: list[PyEnv] = []

    venv = _has_venv_python(root)
    if venv:
        envs.append(PyEnv(".venv", "项目虚拟环境（.venv）", str(venv),
                          f"版本 {_python_version(venv)}" if _python_version(venv) else ""))
    else:
        envs.append(PyEnv(".venv", "项目虚拟环境（.venv）", str(root / ".venv" / "Scripts" / "python.exe"),
                          "未检测到 .venv，将自动创建并安装依赖"))

    syspy = _system_python(root)
    if syspy:
        envs.append(PyEnv("system", "系统 Python", str(syspy),
                          f"版本 {_python_version(syspy)}" if _python_version(syspy) else ""))

    wpy = _winpython_python(root)
    if wpy:
        envs.append(PyEnv("winpython", "内置 WinPython", str(wpy),
                          f"版本 {_python_version(wpy)}" if _python_version(wpy) else ""))

    return envs


def chosen_python(envs: list[PyEnv], state: SetupState) -> PyEnv | None:
    """读取用户选择的运行环境；未选择或选择失效时回退到第一个可用。"""
    chosen_id = state.get("python_env_id")
    if chosen_id:
        for env in envs:
            if env.id == chosen_id:
                return env
    return envs[0] if envs else None
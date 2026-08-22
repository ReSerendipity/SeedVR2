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
    "python_env_id": None,       # 用户选择的运行环境（.venv / system / winpython）
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

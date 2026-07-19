#!/usr/bin/env python3
"""SeedVR2 进度追踪模块

追踪推理管线各阶段的进度：
  VAE Encode → DiT Sampling → VAE Decode → Post-process

支持单段和多段（批量）模式，线程安全，可通知 SSE 监听器。
"""

import contextlib
import threading
import time
from collections.abc import Callable

# 默认推理阶段定义
DEFAULT_STAGES = [
    "VAE Encode",
    "DiT Sampling",
    "VAE Decode",
    "Post-process",
]

# 阶段状态常量
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


class StageInfo:
    """单个阶段的状态信息。"""

    __slots__ = ("name", "status", "progress", "message", "started_at", "finished_at")

    def __init__(self, name: str):
        self.name = name
        self.status = STATUS_PENDING
        self.progress = 0
        self.message = ""
        self.started_at: float | None = None
        self.finished_at: float | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class ProgressTracker:
    """SeedVR2 推理进度追踪器。

    线程安全地追踪多阶段推理进度，支持多段（批量）模式，
    并在进度变化时通知 SSE 监听器。

    Usage::

        tracker = ProgressTracker()
        tracker.add_listener(some_callback)
        tracker.start_stage("VAE Encode")
        tracker.update_stage("VAE Encode", 50, "编码中...")
        tracker.complete_stage("VAE Encode")
        ...
    """

    def __init__(self, stages: list[str] | None = None):
        self._lock = threading.RLock()
        self._stages: dict[str, StageInfo] = {}
        self._listeners: list[Callable] = []
        self._total_segments = 1
        self._current_segment = 0
        self._is_active = False
        self._started_at: float | None = None

        stage_names = stages or DEFAULT_STAGES
        for name in stage_names:
            self._stages[name] = StageInfo(name)

    # ---- 监听器管理 ----

    def add_listener(self, callback: Callable):
        """添加进度变化监听器。

        Args:
            callback: 无参回调函数，在进度变化时调用。
        """
        with self._lock:
            self._listeners.append(callback)

    def _notify_listeners(self):
        """通知所有监听器。"""
        callbacks = []
        with self._lock:
            callbacks = list(self._listeners)
        for cb in callbacks:
            with contextlib.suppress(Exception):
                cb()

    def _notify_sse(self):
        """通知 SSE 事件总线状态已变化。"""
        try:
            from .routes.system.sse import event_bus
            event_bus.publish("progress", self.get_progress())
        except Exception:
            pass
        self._notify_listeners()

    # ---- 阶段控制 ----

    def start_stage(self, stage_name: str):
        """将指定阶段标记为运行中。

        Args:
            stage_name: 阶段名称，必须在初始化阶段列表中。
        """
        with self._lock:
            stage = self._stages.get(stage_name)
            if stage is None:
                return
            stage.status = STATUS_RUNNING
            stage.progress = 0
            stage.message = ""
            stage.started_at = time.time()
            stage.finished_at = None
            self._is_active = True
            if self._started_at is None:
                self._started_at = time.time()
        self._notify_sse()

    def update_stage(self, stage_name: str, progress: int, message: str | None = None):
        """更新指定阶段的进度。

        Args:
            stage_name: 阶段名称。
            progress: 进度值 (0-100)。
            message: 可选的状态消息。
        """
        with self._lock:
            stage = self._stages.get(stage_name)
            if stage is None:
                return
            stage.progress = max(0, min(100, progress))
            if message is not None:
                stage.message = message
        self._notify_sse()

    def complete_stage(self, stage_name: str):
        """将指定阶段标记为已完成。

        Args:
            stage_name: 阶段名称。
        """
        with self._lock:
            stage = self._stages.get(stage_name)
            if stage is None:
                return
            stage.status = STATUS_COMPLETED
            stage.progress = 100
            stage.finished_at = time.time()
        self._notify_sse()

    def fail_stage(self, stage_name: str, error: str):
        """将指定阶段标记为失败。

        Args:
            stage_name: 阶段名称。
            error: 错误信息。
        """
        with self._lock:
            stage = self._stages.get(stage_name)
            if stage is None:
                return
            stage.status = STATUS_FAILED
            stage.message = error
            stage.finished_at = time.time()
        self._notify_sse()

    # ---- 整体进度查询 ----

    def get_progress(self) -> dict:
        """获取完整进度信息字典。

        Returns:
            包含所有阶段状态、整体进度百分比、段信息等的字典。
        """
        with self._lock:
            stages_dict = {name: s.to_dict() for name, s in self._stages.items()}
            total_progress = self._calculate_overall_progress()
            current_stage = None
            for s in self._stages.values():
                if s.status == STATUS_RUNNING:
                    current_stage = s.name
                    break

            return {
                "stages": stages_dict,
                "overall_progress": total_progress,
                "current_stage": current_stage,
                "is_active": self._is_active,
                "total_segments": self._total_segments,
                "current_segment": self._current_segment,
                "started_at": self._started_at,
            }

    def _calculate_overall_progress(self) -> int:
        """计算整体进度百分比（所有阶段的加权平均）。"""
        if not self._stages:
            return 0
        total = sum(s.progress for s in self._stages.values())
        return int(total / len(self._stages))

    # ---- 多段（批量）模式 ----

    def set_total_segments(self, total: int):
        """设置总段数（用于批量处理模式）。

        Args:
            total: 总段数。
        """
        with self._lock:
            self._total_segments = max(1, total)
            self._current_segment = 0
        self._notify_sse()

    def advance_segment(self):
        """推进到下一段。"""
        with self._lock:
            self._current_segment += 1
        self._notify_sse()

    # ---- 重置 ----

    def reset(self):
        """重置所有进度状态。"""
        with self._lock:
            for stage in self._stages.values():
                stage.status = STATUS_PENDING
                stage.progress = 0
                stage.message = ""
                stage.started_at = None
                stage.finished_at = None
            self._total_segments = 1
            self._current_segment = 0
            self._is_active = False
            self._started_at = None
        self._notify_sse()


# 全局单例
progress_tracker = ProgressTracker()

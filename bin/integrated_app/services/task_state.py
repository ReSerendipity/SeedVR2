"""SeedVR2 工具箱 - 任务状态管理服务

封装内存缓存 + 数据库持久化的双层任务状态管理。
替代 routes/restore/common.py 中的全局 OrderedDict（无锁保护，C8 内存泄漏风险）。

设计要点:
- 线程安全：使用 threading.Lock 保护内存缓存 (C8)
- 双层存储：内存缓存加速读取，数据库为唯一可信源
- FIFO 淘汰：超过上限时淘汰最早写入的条目
- 异步友好：所有 DB 操作为 async，内存操作为同步

REFACTOR [B2-1] (本版本增强): 收敛任务状态真源
- 原 common._task_cache 与本类 (task_state_store) 并存，导致双真源漂移
- 本次将 common.py 中的 create/get/update/get_cache 全部代理到本类，
  消除模块级全局 OrderedDict，统一由本类管理内存缓存
- 新增 update_cached / get_cached_or_create / snapshot 方法，
  覆盖批量任务（batch.py）对原 _task_cache 的直接读写场景
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from typing import Any

from ..history_db import HistoryDB, TaskRecord

logger = logging.getLogger(__name__)

# 内存缓存上限，超过时 FIFO 淘汰
_DEFAULT_MAX_CACHE_SIZE = 1000


class TaskStateStore:
    """任务状态存储 - 内存缓存 + 数据库持久化。

    线程安全设计:
    - _lock 保护 _cache 的所有读写 (C8)
    - DB 操作通过 HistoryDB 的 async 方法完成，无需额外锁

    单真源原则 [B2-1]:
    - 所有任务状态（含批量任务的临时字段 current_index/results 等）
      统一由本类管理，路由层不再持有模块级 OrderedDict
    """

    def __init__(self, max_cache_size: int = _DEFAULT_MAX_CACHE_SIZE):
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()
        self._max_size = max(10, max_cache_size)

    def _evict_if_needed(self) -> None:
        """缓存超过上限时淘汰最早写入的条目（FIFO）。必须在 _lock 保护下调用。"""
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    async def create(
        self,
        task_id: str,
        record_id: int,
        history_db: HistoryDB,
        task_type: str = "single",
    ) -> dict:
        """在数据库与内存缓存中创建任务初始状态。

        Args:
            task_id: 任务唯一标识
            record_id: 关联的历史记录 ID
            history_db: 历史数据库实例
            task_type: 任务类型（single / batch）

        Returns:
            初始任务状态字典（拷贝，调用方可安全修改但不会影响缓存）
        """
        record = TaskRecord(
            task_id=task_id,
            record_id=record_id,
            status="pending",
            progress=0.0,
        )
        await history_db.create_task(record)
        state = {
            "task_id": task_id,
            "record_id": record_id,
            "status": "pending",
            "progress": 0.0,
            "error": None,
            "output_path": None,
            "current_frame": 0,
            "total_frames": 0,
            "task_type": task_type,
        }
        with self._lock:
            self._cache[task_id] = state
            self._evict_if_needed()
        # ROBUSTNESS [B2-1]: 返回拷贝，避免调用方直接修改缓存导致状态漂移
        return dict(state)

    async def get(self, task_id: str, history_db: HistoryDB) -> dict | None:
        """获取任务状态；优先读缓存，回源数据库。

        Args:
            task_id: 任务唯一标识
            history_db: 历史数据库实例

        Returns:
            任务状态字典（拷贝），不存在则返回 None
        """
        # 快速路径：缓存命中
        with self._lock:
            cached = self._cache.get(task_id)
            if cached is not None:
                return dict(cached)

        # 回源数据库
        record = await history_db.get_task(task_id)
        if record is None:
            return None

        state = {
            "task_id": record.task_id,
            "record_id": record.record_id,
            "status": record.status,
            "progress": record.progress,
            "error": record.error_message or None,
            "output_path": record.output_path or None,
            "current_frame": 0,
            "total_frames": 0,
            "task_type": "single",
        }
        with self._lock:
            # 双检：可能在 await 期间被其他协程写入
            if task_id not in self._cache:
                self._cache[task_id] = state
                self._evict_if_needed()
            return dict(self._cache[task_id])

    async def update(self, task_id: str, history_db: HistoryDB, **kwargs: Any) -> dict:
        """更新数据库任务状态并同步缓存。

        支持的 DB 字段：status, progress, output_path, error_message
        其他字段（如 current_frame, total_frames）仅更新缓存。

        Args:
            task_id: 任务唯一标识
            history_db: 历史数据库实例
            **kwargs: 要更新的字段

        Returns:
            更新后的任务状态字典（拷贝）
        """
        # DB 字段白名单
        db_allowed = {"status", "progress", "output_path", "error_message"}
        db_kwargs = {k: v for k, v in kwargs.items() if k in db_allowed}
        if db_kwargs:
            await history_db.update_task(task_id, **db_kwargs)

        with self._lock:
            cached = self._cache.setdefault(task_id, {"task_id": task_id})
            self._evict_if_needed()
            for key, value in kwargs.items():
                if key == "status":
                    cached["status"] = value
                elif key == "progress":
                    cached["progress"] = value
                elif key == "output_path":
                    cached["output_path"] = value
                elif key == "error_message":
                    cached["error"] = value
                else:
                    # 透传非 DB 字段到缓存（如 current_frame, total_frames）
                    cached[key] = value
            return dict(cached)

    def update_cached(self, task_id: str, **kwargs: Any) -> dict | None:
        """仅更新内存缓存中的任务字段（同步，不写 DB）。

        REFACTOR [B2-1]: 替代原 batch.py 中 `common.get_task_cache()[batch_id].update({...})`
        的直接缓存操作模式。批量任务的临时字段（current_index/results/completed/failed
        等）无需持久化，仅写缓存即可。

        Args:
            task_id: 任务唯一标识
            **kwargs: 要更新的字段

        Returns:
            更新后的任务状态字典（拷贝），任务不在缓存中则返回 None
        """
        with self._lock:
            cached = self._cache.get(task_id)
            if cached is None:
                return None
            cached.update(kwargs)
            return dict(cached)

    def get_cached(self, task_id: str) -> dict | None:
        """仅从内存缓存获取状态（同步，不回源 DB）。

        适用于高频读取场景（如 SSE 进度推送），避免每次都访问数据库。
        """
        with self._lock:
            cached = self._cache.get(task_id)
            return dict(cached) if cached is not None else None

    def get_cached_or_create(self, task_id: str, template: dict | None = None) -> dict:
        """从缓存获取状态，不存在则用 template 创建并写入缓存。

        REFACTOR [B2-1]: 替代原 batch.py 中 `_process_batch_background` 的
        `cached = common.get_task_cache().get(batch_id); if cached is None: cached = {...}; common.get_task_cache()[batch_id] = cached`
        模式，消除模块级全局缓存的直接写入。

        Args:
            task_id: 任务唯一标识
            template: 创建新条目时使用的初始字典

        Returns:
            任务状态字典（拷贝）
        """
        with self._lock:
            cached = self._cache.get(task_id)
            if cached is None:
                cached = dict(template) if template else {"task_id": task_id}
                cached.setdefault("task_id", task_id)
                self._cache[task_id] = cached
                self._evict_if_needed()
            return dict(cached)

    def snapshot(self) -> dict[str, dict]:
        """返回当前缓存的快照（同步，仅用于测试与诊断）。

        ROBUSTNESS: 返回深拷贝，避免外部修改影响缓存内部状态。
        """
        import copy
        with self._lock:
            return copy.deepcopy(self._cache)

    def remove(self, task_id: str) -> None:
        """从内存缓存中移除任务（不影响数据库）。"""
        with self._lock:
            self._cache.pop(task_id, None)

    def clear(self) -> None:
        """清空内存缓存（不影响数据库）。"""
        with self._lock:
            self._cache.clear()

    @property
    def cache_size(self) -> int:
        """当前内存缓存中的任务数"""
        with self._lock:
            return len(self._cache)


# 全局单例
task_state_store = TaskStateStore()

"""SeedVR2 - 任务状态管理服务。

封装内存缓存 + SQLite 数据库持久化的双层任务状态管理，是系统任务状态的唯一可信源。
替代原 routes/restore/common.py 中无锁保护的全局 OrderedDict（存在 C8 内存泄漏风险和竞态条件）。

性能优化:
    - 读写分离：高频读取走内存缓存 O(1)，持久化操作异步写 DB
    - FIFO 淘汰：内存缓存超过上限时淘汰最早写入的条目，防止内存无限增长
    - 双检锁模式：缓存 miss 回源 DB 时，await 期间再次检查缓存，避免重复写入

设计模式:
    - 缓存 Aside 模式 (Cache-Aside)：读取时先查缓存，miss 再查 DB 并回填
    - 单例模式：全局 task_state_store 单例，统一状态入口
    - 线程安全：threading.Lock 保护内存缓存的所有读写操作
    - 防御性拷贝：所有返回给调用方的状态都是深/浅拷贝，防止外部直接修改内部状态

重构说明 [B2-1]:
    - 原 common._task_cache 与本类并存导致双真源状态漂移问题已解决
    - common.py 中的 create/get/update/get_cache 全部代理到本类
    - 新增 update_cached / get_cached_or_create / snapshot 方法，
        覆盖批量任务（batch.py）对原 _task_cache 的直接读写场景

双层存储架构:
    ┌─────────────────────────────────────────────────┐
    │  调用方                                          │
    └─────────┬───────────────────────────────────────┘
              │
    ┌─────────▼───────────────────────────────────────┐
    │  内存缓存 (OrderedDict, 线程安全)                 │  ← 高频读写，快速路径
    │  - LRU/FIFO 淘汰，max_size=1000                  │
    │  - 包含临时字段：current_frame, total_frames 等  │
    └─────────┬───────────────────────────────────────┘
              │ miss
    ┌─────────▼───────────────────────────────────────┐
    │  SQLite 数据库 (history_db)                      │  ← 唯一可信源，持久化
    │  - 持久字段：task_id, status, progress, error... │
    │  - 支持重启恢复、历史查询                        │
    └─────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from typing import Any

from ..history_db import HistoryDB, TaskRecord

logger = logging.getLogger(__name__)

_DEFAULT_MAX_CACHE_SIZE = 1000


class TaskStateStore:
    """任务状态存储 - 内存缓存 + 数据库持久化的双层存储。

    线程安全设计：
        - _lock (threading.Lock) 保护 _cache OrderedDict 的所有读写操作
        - DB 操作通过 HistoryDB 的 async 方法完成，无需额外锁（SQLite 已做连接隔离）
        - 所有返回给调用方的字典都是拷贝，防止外部修改污染内部状态

    单真源原则 [B2-1]:
        - 所有任务状态（含批量任务的临时字段 current_index/results 等）
            统一由本类管理，路由层不再持有模块级全局变量
        - 数据库字段白名单机制：显式指定哪些字段需要持久化，其他仅存缓存
    """

    def __init__(self, max_cache_size: int = _DEFAULT_MAX_CACHE_SIZE):
        """初始化任务状态存储。

        Args:
            max_cache_size: 内存缓存最大条目数，默认 1000；
                超过时按 FIFO 策略淘汰最早写入的条目；
                最小值为 10，防止配置过小导致缓存命中率过低
        """
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()
        self._max_size = max(10, max_cache_size)

    def _evict_if_needed(self) -> None:
        """缓存超过上限时按 FIFO 策略淘汰最早写入的条目。

        注意：此方法必须在 self._lock 保护下调用，否则存在竞态条件。
        """
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

        任务入队时调用，先持久化到 DB 再写入缓存，保证即使崩溃重启
        也能从 DB 恢复 pending 状态的任务。

        Args:
            task_id: 任务唯一标识（UUID 字符串）
            record_id: 关联的历史记录 ID（HistoryDB 返回的主键）
            history_db: 历史数据库实例，由依赖注入提供
            task_type: 任务类型，"single" 单文件 / "batch" 批量

        Returns:
            dict: 初始任务状态字典（浅拷贝，调用方可安全修改但不会影响缓存）
                包含字段：task_id, record_id, status, progress, error,
                output_path, current_frame, total_frames, task_type
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
        return dict(state)

    async def get(self, task_id: str, history_db: HistoryDB) -> dict | None:
        """获取任务状态；优先读缓存，缓存 miss 时回源数据库。

        使用双检锁 (Double-Checked Locking) 模式：await DB 操作期间
        可能有其他协程已写入缓存，因此 DB 返回后再次检查避免重复写入。

        Args:
            task_id: 任务唯一标识
            history_db: 历史数据库实例

        Returns:
            dict | None: 任务状态字典（浅拷贝），任务不存在返回 None
        """
        with self._lock:
            cached = self._cache.get(task_id)
            if cached is not None:
                return dict(cached)

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
            if task_id not in self._cache:
                self._cache[task_id] = state
                self._evict_if_needed()
            return dict(self._cache[task_id])

    async def update(self, task_id: str, history_db: HistoryDB, **kwargs: Any) -> dict:
        """更新数据库任务状态并同步缓存。

        持久化字段白名单：status, progress, output_path, error_message（映射为 error）
        其他字段（如 current_frame, total_frames, batch 相关字段）仅更新缓存不写 DB。

        Args:
            task_id: 任务唯一标识
            history_db: 历史数据库实例
            **kwargs: 要更新的字段键值对

        Returns:
            dict: 更新后的完整任务状态字典（浅拷贝）
        """
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
                    cached[key] = value
            return dict(cached)

    def update_cached(self, task_id: str, **kwargs: Any) -> dict | None:
        """仅更新内存缓存中的任务字段（同步方法，不写数据库）。

        用于高频、临时状态更新，如批量任务的 current_index、实时帧数等
        不需要持久化的字段，避免频繁写 DB 造成性能瓶颈。

        重构说明 [B2-1]:
            替代原 batch.py 中 `common.get_task_cache()[batch_id].update({...})`
            的直接缓存操作模式，保证所有缓存访问都经过锁保护。

        Args:
            task_id: 任务唯一标识
            **kwargs: 要更新的字段键值对

        Returns:
            dict | None: 更新后的任务状态字典（浅拷贝），任务不在缓存中返回 None
        """
        with self._lock:
            cached = self._cache.get(task_id)
            if cached is None:
                return None
            cached.update(kwargs)
            return dict(cached)

    def get_cached(self, task_id: str) -> dict | None:
        """仅从内存缓存获取状态（同步方法，不回源数据库）。

        适用于高频读取场景（如 SSE 进度推送、实时统计），
        完全在内存中完成，避免每次都访问数据库造成 I/O 压力。

        Args:
            task_id: 任务唯一标识

        Returns:
            dict | None: 任务状态字典（浅拷贝），缓存中不存在返回 None
        """
        with self._lock:
            cached = self._cache.get(task_id)
            return dict(cached) if cached is not None else None

    def get_cached_or_create(self, task_id: str, template: dict | None = None) -> dict:
        """从缓存获取状态，不存在则用 template 初始化并写入缓存。

        同步方法，不访问数据库，适用于批量任务初始化等场景。

        重构说明 [B2-1]:
            替代原 batch.py 中 _process_batch_background 的模式：
            ```
            cached = common.get_task_cache().get(batch_id)
            if cached is None:
                cached = {...}
                common.get_task_cache()[batch_id] = cached
            ```
            消除模块级全局缓存的直接读写，统一锁保护。

        Args:
            task_id: 任务唯一标识
            template: 创建新条目时使用的初始字典，为 None 时仅含 task_id

        Returns:
            dict: 任务状态字典（浅拷贝）
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
        """返回当前内存缓存的完整快照（同步方法，仅用于测试与诊断）。

        返回深拷贝，外部修改不会影响缓存内部状态，保证诊断安全。

        Returns:
            dict[str, dict]: task_id -> 状态字典的映射（深拷贝）
        """
        import copy

        with self._lock:
            return copy.deepcopy(self._cache)

    def remove(self, task_id: str) -> None:
        """从内存缓存中移除指定任务（不影响数据库中的记录）。

        任务完成后清理缓存或显式删除时调用。DB 中的历史记录保留用于查询。

        Args:
            task_id: 任务唯一标识
        """
        with self._lock:
            self._cache.pop(task_id, None)

    def clear(self) -> None:
        """清空整个内存缓存（不影响数据库）。

        主要用于测试环境或紧急内存释放，生产环境慎用。
        """
        with self._lock:
            self._cache.clear()

    @property
    def cache_size(self) -> int:
        """当前内存缓存中的任务数量。

        Returns:
            int: 缓存条目数
        """
        with self._lock:
            return len(self._cache)


task_state_store = TaskStateStore()
"""全局单例 - 任务状态存储实例。

应用启动时创建，整个生命周期复用，是任务状态的唯一访问入口。
路由和服务层应直接导入此单例使用，不要自行创建 TaskStateStore 实例，
避免出现多个状态存储导致数据不一致。
"""

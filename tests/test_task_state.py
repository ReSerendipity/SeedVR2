"""测试 TaskStateStore 任务状态存储服务

覆盖:
- C8: 线程安全（threading.Lock 保护 OrderedDict）
- FIFO 淘汰策略（超过 max_cache_size 时）
- 双层存储（内存缓存 + DB 回源）
- 缓存命中/未命中、update 字段透传、get_cached 同步读取
"""

from __future__ import annotations

import threading
from unittest.mock import AsyncMock

import pytest

from app.integrated_app.history_db import HistoryDB, TaskRecord
from app.integrated_app.services.task_state import TaskStateStore


@pytest.fixture
def mock_db():
    """Mock HistoryDB，仅模拟异步接口"""
    db = AsyncMock(spec=HistoryDB)
    db.create_task = AsyncMock(return_value=True)
    db.update_task = AsyncMock(return_value=True)
    db.get_task = AsyncMock(return_value=None)
    return db


@pytest.fixture
def store():
    return TaskStateStore(max_cache_size=10)


class TestCreate:
    """create 行为"""

    @pytest.mark.asyncio
    async def test_create_initializes_state(self, store, mock_db):
        state = await store.create("t1", record_id=100, history_db=mock_db, task_type="single")
        assert state["task_id"] == "t1"
        assert state["record_id"] == 100
        assert state["status"] == "pending"
        assert state["progress"] == 0.0
        assert state["error"] is None
        assert state["output_path"] is None
        assert state["task_type"] == "single"
        # DB 应被调用
        mock_db.create_task.assert_awaited_once()
        # 缓存应写入
        assert store.cache_size == 1
        assert store.get_cached("t1") is not None

    @pytest.mark.asyncio
    async def test_create_default_task_type(self, store, mock_db):
        state = await store.create("t2", record_id=1, history_db=mock_db)
        assert state["task_type"] == "single"

    @pytest.mark.asyncio
    async def test_create_passes_task_record_to_db(self, store, mock_db):
        await store.create("t-rec", record_id=42, history_db=mock_db)
        call_args = mock_db.create_task.call_args
        record: TaskRecord = call_args[0][0]
        assert record.task_id == "t-rec"
        assert record.record_id == 42
        assert record.status == "pending"
        assert record.progress == 0.0


class TestGet:
    """get 缓存命中与回源"""

    @pytest.mark.asyncio
    async def test_get_cache_hit(self, store, mock_db):
        await store.create("cached", record_id=1, history_db=mock_db)
        # 第二次 get 应命中缓存，不查 DB
        mock_db.get_task.reset_mock()
        result = await store.get("cached", mock_db)
        assert result is not None
        assert result["task_id"] == "cached"
        mock_db.get_task.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_cache_miss_queries_db(self, store, mock_db):
        # DB 中存在但缓存未命中
        mock_db.get_task.return_value = TaskRecord(
            task_id="db-only",
            record_id=5,
            status="completed",
            progress=1.0,
            output_path="/out/x.png",
            error_message="",
            updated_at="2026-01-01",
        )
        result = await store.get("db-only", mock_db)
        assert result is not None
        assert result["task_id"] == "db-only"
        assert result["status"] == "completed"
        assert result["progress"] == 1.0
        # 应写入缓存
        assert store.get_cached("db-only") is not None

    @pytest.mark.asyncio
    async def test_get_returns_none_when_not_found(self, store, mock_db):
        mock_db.get_task.return_value = None
        result = await store.get("nonexistent", mock_db)
        assert result is None


class TestUpdate:
    """update 字段更新与缓存同步"""

    @pytest.mark.asyncio
    async def test_update_db_fields(self, store, mock_db):
        await store.create("t-up", record_id=1, history_db=mock_db)
        result = await store.update(
            "t-up",
            mock_db,
            status="processing",
            progress=0.5,
            output_path="/out/r.png",
            error_message=None,
        )
        assert result["status"] == "processing"
        assert result["progress"] == 0.5
        assert result["output_path"] == "/out/r.png"
        # DB 应被调用（仅 db_allowed 字段）
        mock_db.update_task.assert_awaited_once()
        call_kwargs = mock_db.update_task.call_args[1]
        assert call_kwargs["status"] == "processing"
        assert call_kwargs["progress"] == 0.5
        assert call_kwargs["output_path"] == "/out/r.png"

    @pytest.mark.asyncio
    async def test_update_error_message_mapped_to_error(self, store, mock_db):
        await store.create("t-err", record_id=1, history_db=mock_db)
        result = await store.update("t-err", mock_db, error_message="boom")
        # error_message 在缓存中映射为 error 字段
        assert result["error"] == "boom"

    @pytest.mark.asyncio
    async def test_update_non_db_field_only_cached(self, store, mock_db):
        """非 DB 字段（如 current_frame）仅更新缓存，不写 DB"""
        await store.create("t-frame", record_id=1, history_db=mock_db)
        mock_db.update_task.reset_mock()
        result = await store.update(
            "t-frame",
            mock_db,
            current_frame=42,
            total_frames=100,
        )
        assert result["current_frame"] == 42
        assert result["total_frames"] == 100
        # DB 不应被调用
        mock_db.update_task.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_creates_cache_entry_if_missing(self, store, mock_db):
        """update 一个缓存中不存在的任务时，应创建缓存条目"""
        result = await store.update("ghost", mock_db, status="processing")
        assert result["task_id"] == "ghost"
        assert result["status"] == "processing"


class TestGetCached:
    """同步缓存读取"""

    def test_get_cached_returns_none_for_missing(self, store):
        assert store.get_cached("missing") is None

    def test_get_cached_returns_copy(self, store, mock_db):
        # 同步插入缓存项
        with store._lock:
            store._cache["t1"] = {"task_id": "t1", "status": "pending"}
        cached = store.get_cached("t1")
        assert cached == {"task_id": "t1", "status": "pending"}
        # 修改返回值不应影响内部缓存
        cached["status"] = "modified"
        assert store.get_cached("t1")["status"] == "pending"


class TestEvictionAndRemove:
    """FIFO 淘汰与显式移除"""

    def test_fifo_eviction_when_exceeding_max_size(self):
        """max_cache_size 被钳制为最小 10，需插入 >10 项触发淘汰"""
        store = TaskStateStore(max_cache_size=10)
        # 直接写入缓存绕过 DB
        with store._lock:
            for i in range(15):
                store._cache[f"t{i}"] = {"task_id": f"t{i}"}
                store._evict_if_needed()
        # 应只剩最后 10 个
        assert store.cache_size == 10
        # 前 5 个应被淘汰
        for i in range(5):
            assert store.get_cached(f"t{i}") is None
        # 后 10 个应保留
        for i in range(5, 15):
            assert store.get_cached(f"t{i}") is not None

    def test_remove_clears_cache_only(self, store, mock_db):
        # 写入缓存
        with store._lock:
            store._cache["t-rm"] = {"task_id": "t-rm"}
        store.remove("t-rm")
        assert store.get_cached("t-rm") is None
        # remove 不影响 DB
        assert mock_db.delete_task.call_count == 0

    def test_remove_nonexistent_silent(self, store):
        # 不抛异常
        store.remove("ghost")

    def test_clear_empties_cache(self, store):
        with store._lock:
            store._cache["t1"] = {"task_id": "t1"}
            store._cache["t2"] = {"task_id": "t2"}
        store.clear()
        assert store.cache_size == 0


class TestThreadSafety:
    """C8: threading.Lock 保护"""

    def test_concurrent_writes_no_corruption(self, store):
        """多线程并发写入不应导致缓存损坏或丢条目"""
        n_writers = 50
        threads = []

        def writer(idx: int):
            with store._lock:
                store._cache[f"t{idx}"] = {"task_id": f"t{idx}"}
                store._evict_if_needed()

        for i in range(n_writers):
            threads.append(threading.Thread(target=writer, args=(i,)))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # max_cache_size=10 会淘汰前 40 个
        assert store.cache_size <= 10  # 不超过上限
        # 最后写入的几个应在
        assert store.get_cached(f"t{n_writers - 1}") is not None

    def test_max_cache_size_minimum_10(self):
        """max_cache_size < 10 时被钳制为 10"""
        store = TaskStateStore(max_cache_size=1)
        assert store._max_size == 10

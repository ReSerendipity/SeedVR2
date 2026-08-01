"""测试 HistoryDB 历史记录数据库

覆盖:
- E7: async context manager 协议（__aenter__/__aexit__）
- C3: get_records_by_ids 批量查询（修复 N+1）
- SECURITY: FTS5 查询转义（通过 escape_fts_query）
- D2: SQL 注入防护（列名白名单、参数化）
- E2: 异常粒度（aiosqlite.Error, sqlite3.Error, OSError）
- 基础 CRUD、批量插入、任务状态持久化
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import aiosqlite
import pytest

from bin.integrated_app.history_db import HistoryDB, HistoryRecord, TaskRecord


@pytest.fixture
async def db(tmp_path):
    """临时数据库 fixture，自动初始化与关闭"""
    db_path = tmp_path / "test_history.db"
    instance = HistoryDB(db_path=str(db_path))
    await instance.initialize()
    try:
        yield instance
    finally:
        await instance.close()


async def _add_sample(db: HistoryDB, **kwargs) -> int:
    """辅助：插入一条记录并返回 ID"""
    defaults = {
        "task_type": "video",
        "input_file": "/in/test.mp4",
        "output_file": "/out/test.mp4",
        "model_size": "3b",
        "status": "completed",
        "parameters": "{}",
        "processing_time": 10.5,
    }
    defaults.update(kwargs)
    return await db.add_record(HistoryRecord(**defaults))


class TestAsyncContextManager:
    """E7: async context manager 协议"""

    @pytest.mark.asyncio
    async def test_aenter_returns_self(self, tmp_path):
        db_path = tmp_path / "ctx.db"
        db = HistoryDB(db_path=str(db_path))
        async with db as ctx:
            assert ctx is db
            assert db._initialized is True
        # 退出后应已关闭
        assert db._initialized is False
        assert db._db is None

    @pytest.mark.asyncio
    async def test_aexit_closes_even_on_exception(self, tmp_path):
        db_path = tmp_path / "ctx_err.db"
        db = HistoryDB(db_path=str(db_path))
        with pytest.raises(RuntimeError):
            async with db:
                raise RuntimeError("boom")
        assert db._initialized is False
        assert db._db is None


class TestInitialize:
    """初始化与表结构"""

    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self, tmp_path):
        db_path = tmp_path / "init.db"
        db = HistoryDB(db_path=str(db_path))
        await db.initialize()
        # 直接通过底层连接验证表存在
        async with aiosqlite.connect(str(db_path)) as conn:
            cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in await cursor.fetchall()}
        assert "history" in tables
        assert "tasks" in tables
        assert "history_fts" in tables  # FTS5 虚拟表
        await db.close()

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, tmp_path):
        db = HistoryDB(db_path=str(tmp_path / "idem.db"))
        await db.initialize()
        first_db = db._db
        await db.initialize()  # 重复调用不应重新创建连接
        assert db._db is first_db
        await db.close()

    @pytest.mark.asyncio
    async def test_initialize_creates_parent_dir(self, tmp_path):
        db_path = tmp_path / "nested" / "deep" / "x.db"
        db = HistoryDB(db_path=str(db_path))
        await db.initialize()
        assert db_path.parent.exists()
        await db.close()


class TestAddAndGetMapping:
    """基础 CRUD"""

    @pytest.mark.asyncio
    async def test_add_record_returns_id(self, db):
        rid = await _add_sample(db)
        assert isinstance(rid, int)
        assert rid > 0

    @pytest.mark.asyncio
    async def test_get_record_by_id(self, db):
        rid = await _add_sample(db, input_file="/in/a.mp4")
        record = await db.get_record(rid)
        assert record is not None
        assert record.id == rid
        assert record.input_file == "/in/a.mp4"

    @pytest.mark.asyncio
    async def test_get_nonexistent_record_returns_none(self, db):
        assert await db.get_record(99999) is None

    @pytest.mark.asyncio
    async def test_update_record_whitelist(self, db):
        rid = await _add_sample(db, status="pending")
        ok = await db.update_record(rid, status="completed", processing_time=20.0)
        assert ok is True
        record = await db.get_record(rid)
        assert record.status == "completed"
        assert record.processing_time == 20.0

    @pytest.mark.asyncio
    async def test_update_record_rejects_unknown_column(self, db):
        rid = await _add_sample(db)
        with pytest.raises(ValueError):
            await db.update_record(rid, evil_column="hack")

    @pytest.mark.asyncio
    async def test_delete_record(self, db):
        rid = await _add_sample(db)
        assert await db.delete_record(rid) is True
        assert await db.get_record(rid) is None


class TestBatchAddAndQuery:
    """C3: 批量查询（修复 N+1）"""

    @pytest.mark.asyncio
    async def test_add_records_batch(self, db):
        records = [HistoryRecord(task_type="video", input_file=f"/in/{i}.mp4", status="completed") for i in range(5)]
        ids = await db.add_records(records)
        assert len(ids) == 5
        # 每个 ID 都应能查到
        for rid in ids:
            assert await db.get_record(rid) is not None

    @pytest.mark.asyncio
    async def test_add_records_empty_list(self, db):
        assert await db.add_records([]) == []

    @pytest.mark.asyncio
    async def test_get_records_by_ids_batch(self, db):
        """批量查询应一次 SQL 完成，不产生 N+1"""
        ids = []
        for i in range(10):
            ids.append(await _add_sample(db, input_file=f"/in/{i}.mp4"))

        # 取部分 ID 批量查询
        target_ids = ids[2:7]
        records = await db.get_records_by_ids(target_ids)
        assert len(records) == 5
        returned_ids = {r.id for r in records}
        assert returned_ids == set(target_ids)

    @pytest.mark.asyncio
    async def test_get_records_by_ids_empty_input(self, db):
        """空输入返回空列表，不构造 IN() 子句"""
        assert await db.get_records_by_ids([]) == []

    @pytest.mark.asyncio
    async def test_get_records_by_ids_with_nonexistent(self, db):
        rid = await _add_sample(db)
        # 混入不存在的 ID
        records = await db.get_records_by_ids([rid, 99998, 99999])
        assert len(records) == 1
        assert records[0].id == rid

    @pytest.mark.asyncio
    async def test_get_records_by_ids_dedup(self, db):
        """重复 ID 应被参数化为多次 ?，但数据库去重后返回唯一行"""
        rid = await _add_sample(db)
        records = await db.get_records_by_ids([rid, rid, rid])
        # SQLite IN() 重复参数只返回一行
        assert len(records) == 1


class TestFtsSearch:
    """SECURITY: FTS5 查询转义与搜索"""

    @pytest.mark.asyncio
    async def test_search_basic_match(self, db):
        await _add_sample(db, input_file="/in/awesome_video.mp4", status="completed")
        await _add_sample(db, input_file="/in/boring_clip.mp4", status="completed")
        records, total = await db.search_records("awesome")
        assert total >= 1
        assert any("awesome" in r.input_file for r in records)

    @pytest.mark.asyncio
    async def test_search_empty_query_returns_all(self, db):
        await _add_sample(db)
        await _add_sample(db)
        records, total = await db.search_records("   ")
        assert total >= 2

    @pytest.mark.asyncio
    async def test_search_with_fts5_injection_attempt(self, db):
        """注入尝试应被 escape_fts_query 中和，不抛 FTS5 语法错误"""
        await _add_sample(db, input_file="/in/normal.mp4", status="completed")
        # 各种 FTS5 特殊字符注入
        for evil in [
            "normal*",
            "normal OR 1=1",
            'normal" OR "injection',
            "normal()",
            "normal:input_file",
        ]:
            # 不抛异常即通过
            records, total = await db.search_records(evil)
            assert isinstance(records, list)
            assert isinstance(total, int)

    @pytest.mark.asyncio
    async def test_search_pagination(self, db):
        for i in range(5):
            await _add_sample(db, input_file=f"/in/page_{i}.mp4")
        records, total = await db.search_records("page", limit=2, offset=0)
        assert len(records) == 2
        assert total >= 5


class TestTaskPersistence:
    """任务状态持久化"""

    @pytest.mark.asyncio
    async def test_create_and_get_task(self, db):
        rid = await _add_sample(db)
        record = TaskRecord(
            task_id="task-1",
            record_id=rid,
            status="pending",
            progress=0.0,
        )
        assert await db.create_task(record) is True
        fetched = await db.get_task("task-1")
        assert fetched is not None
        assert fetched.task_id == "task-1"
        assert fetched.status == "pending"

    @pytest.mark.asyncio
    async def test_update_task_whitelist(self, db):
        rid = await _add_sample(db)
        await db.create_task(TaskRecord(task_id="t-up", record_id=rid, status="pending"))
        await db.update_task("t-up", status="processing", progress=0.5)
        fetched = await db.get_task("t-up")
        assert fetched.status == "processing"
        assert fetched.progress == 0.5

    @pytest.mark.asyncio
    async def test_update_task_rejects_unknown_column(self, db):
        rid = await _add_sample(db)
        await db.create_task(TaskRecord(task_id="t-x", record_id=rid))
        with pytest.raises(ValueError):
            await db.update_task("t-x", evil="hack")

    @pytest.mark.asyncio
    async def test_get_incomplete_tasks(self, db):
        rid = await _add_sample(db)
        await db.create_task(TaskRecord(task_id="pending-1", record_id=rid, status="pending"))
        await db.create_task(TaskRecord(task_id="processing-1", record_id=rid, status="processing"))
        await db.create_task(TaskRecord(task_id="done-1", record_id=rid, status="completed"))
        incomplete = await db.get_incomplete_tasks()
        ids = {t.task_id for t in incomplete}
        assert "pending-1" in ids
        assert "processing-1" in ids
        assert "done-1" not in ids

    @pytest.mark.asyncio
    async def test_delete_task(self, db):
        rid = await _add_sample(db)
        await db.create_task(TaskRecord(task_id="t-del", record_id=rid))
        assert await db.delete_task("t-del") is True
        assert await db.get_task("t-del") is None


class TestCloseRobustness:
    """E7: close 异常安全"""

    @pytest.mark.asyncio
    async def test_close_resets_state_even_on_error(self, tmp_path):
        db = HistoryDB(db_path=str(tmp_path / "robust.db"))
        await db.initialize()
        # 保留真实连接引用，避免被替换后孤立导致后台线程残留
        real_conn = db._db
        # 模拟 close 抛异常
        db._db = type("BadConn", (), {"close": AsyncMock(side_effect=aiosqlite.Error("boom"))})()
        # 不应抛异常
        await db.close()
        assert db._db is None
        assert db._initialized is False
        # 正确关闭被替换掉的真实连接，停止其 aiosqlite 工作线程
        await real_conn.close()

    @pytest.mark.asyncio
    async def test_close_idempotent(self, tmp_path):
        db = HistoryDB(db_path=str(tmp_path / "idem_close.db"))
        await db.initialize()
        await db.close()
        # 再次 close 不抛异常
        await db.close()
        assert db._db is None


class TestConnectionTimeout:
    """连接超时与 busy_timeout 健壮性配置"""

    def test_default_timeout(self):
        """默认 timeout 为 30 秒"""
        db = HistoryDB(db_path="data/history.db")
        assert db.timeout == 30.0

    def test_custom_timeout_stored(self):
        """自定义 timeout 被保留"""
        db = HistoryDB(db_path="data/history.db", timeout=5.0)
        assert db.timeout == 5.0

    @pytest.mark.asyncio
    async def test_busy_timeout_pragma_applied(self, tmp_path):
        """initialize 后 busy_timeout PRAGMA 与 timeout 对齐（毫秒）"""
        db = HistoryDB(db_path=str(tmp_path / "timeout.db"), timeout=7.0)
        await db.initialize()
        try:
            async with db._db.execute("PRAGMA busy_timeout") as cursor:
                row = await cursor.fetchone()
            assert row[0] == 7000
        finally:
            await db.close()

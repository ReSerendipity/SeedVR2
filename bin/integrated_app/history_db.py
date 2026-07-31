"""SQLite 历史记录与任务状态持久化模块

使用 aiosqlite 提供异步 SQLite 数据库访问，管理两类数据:
1. HistoryRecord: 修复任务历史记录（视频/图像），支持全文搜索（FTS5）
2. TaskRecord: 后台运行任务的实时状态持久化，用于崩溃恢复

数据库特性:
- WAL 模式: 启用 Write-Ahead Logging 提升并发读写性能
- FTS5 全文搜索: 对输入/输出文件名、模型大小、状态建立全文索引
- 自动触发器: INSERT/UPDATE/DELETE 时自动同步 FTS 索引
- 异步上下文管理器: 支持 async with 语法，确保连接正确释放
- 白名单列验证: UPDATE 操作验证列名，防止 SQL 注入
- 批量插入降级: 批量插入失败时自动回退到逐条插入，保证鲁棒性
"""
from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import aiosqlite

from .utils.fts import escape_fts_query

logger = logging.getLogger(__name__)


@dataclass
class HistoryRecord:
    """修复任务历史记录数据类。

    存储单次视频/图像修复任务的完整元信息，用于历史页面展示和统计。

    Attributes:
        id: 数据库自增主键，None 表示新记录尚未插入。
        task_type: 任务类型，"video" 或 "image"。
        input_file: 输入文件路径。
        output_file: 输出文件路径。
        model_size: 使用的模型大小/版本标识。
        status: 任务状态: pending / processing / completed / failed / cancelled。
        parameters: 任务参数 JSON 字符串。
        processing_time: 处理耗时（秒）。
        created_at: 记录创建时间（ISO 格式字符串）。
        error_message: 失败时的错误信息。
    """

    id: int | None = None
    task_type: str = ""
    input_file: str = ""
    output_file: str = ""
    model_size: str = ""
    status: str = ""
    parameters: str = ""
    processing_time: float = 0.0
    created_at: str = ""
    error_message: str = ""


@dataclass
class TaskRecord:
    """后台任务实时状态记录数据类。

    持久化运行中任务的状态，用于应用重启后恢复未完成任务。

    Attributes:
        task_id: 任务唯一标识符（UUID）。
        record_id: 关联的 HistoryRecord 主键 ID。
        status: 任务状态: pending / processing / completed / failed / cancelled。
        progress: 任务进度（0.0 ~ 100.0）。
        output_path: 输出文件路径（任务完成后填充）。
        error_message: 失败时的错误信息。
        updated_at: 最后更新时间（ISO 格式字符串）。
    """

    task_id: str = ""
    record_id: int = 0
    status: str = ""
    progress: float = 0.0
    output_path: str = ""
    error_message: str = ""
    updated_at: str = ""


class HistoryDB:
    """历史记录与任务状态异步数据库管理器。

    提供历史记录 CRUD、全文搜索、统计，以及任务状态持久化接口。
    支持异步上下文管理器协议（async with），确保异常路径下数据库连接也能正确释放。

    Attributes:
        db_path: SQLite 数据库文件路径。
        _initialized: 数据库是否已初始化（表结构已创建）。
        _db: aiosqlite 持久连接对象，None 表示未连接。
    """

    def __init__(self, db_path: str = "data/history.db"):
        """初始化历史数据库管理器。

        Args:
            db_path: SQLite 数据库文件路径，默认 "data/history.db"。
                路径所在目录不存在时会在 initialize() 中自动创建。
        """
        self.db_path = db_path
        self._initialized = False
        self._db: aiosqlite.Connection | None = None

    # REFACTOR: 支持异步上下文管理器协议，确保异常路径下连接也能被释放 (E7)
    async def __aenter__(self) -> HistoryDB:
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def initialize(self):
        """初始化数据库，创建表结构"""
        if self._initialized:
            return

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        self._db = await aiosqlite.connect(self.db_path)
        db = self._db

        # 启用 WAL 模式以提升并发读写性能
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL,
                input_file TEXT NOT NULL,
                output_file TEXT DEFAULT '',
                model_size TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                parameters TEXT DEFAULT '{}',
                processing_time REAL DEFAULT 0.0,
                created_at TEXT NOT NULL,
                error_message TEXT DEFAULT ''
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                record_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                progress REAL DEFAULT 0.0,
                output_path TEXT DEFAULT '',
                error_message TEXT DEFAULT '',
                updated_at TEXT NOT NULL
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_record_id ON tasks(record_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")

        # 创建全文搜索虚拟表
        await db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS history_fts
            USING fts5(id, input_file, output_file, model_size, status, content=history, content_rowid=id)
        """)

        # 创建触发器保持 FTS 索引同步
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS history_ai AFTER INSERT ON history BEGIN
                INSERT INTO history_fts(rowid, id, input_file, output_file, model_size, status)
                VALUES (new.id, new.id, new.input_file, new.output_file, new.model_size, new.status);
            END
        """)

        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS history_ad AFTER DELETE ON history BEGIN
                INSERT INTO history_fts(history_fts, rowid, id, input_file, output_file, model_size, status)
                VALUES ('delete', old.id, old.id, old.input_file, old.output_file, old.model_size, old.status);
            END
        """)

        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS history_au AFTER UPDATE ON history BEGIN
                INSERT INTO history_fts(history_fts, rowid, id, input_file, output_file, model_size, status)
                VALUES ('delete', old.id, old.id, old.input_file, old.output_file, old.model_size, old.status);
                INSERT INTO history_fts(rowid, id, input_file, output_file, model_size, status)
                VALUES (new.id, new.id, new.input_file, new.output_file, new.model_size, new.status);
            END
        """)

        # 创建索引
        await db.execute("CREATE INDEX IF NOT EXISTS idx_history_type ON history(task_type)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_history_status ON history(status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_history_created ON history(created_at)")

        await db.commit()

        self._initialized = True
        logger.info(f"历史数据库已初始化: {self.db_path}")

    # ==================== 私有辅助方法 ====================

    async def _execute_write(self, sql: str, params: tuple | list = (), *, many: bool = False) -> int:
        """统一写入入口（INSERT/UPDATE/DELETE），自动提交。
        使用持久连接；若未初始化则先初始化。

        Args:
            sql: SQL 语句
            params: 单条参数 tuple 或批量参数 list[tuple]（需配合 many=True）
            many: True 时使用 executemany 批量执行

        Returns:
            lastrowid（INSERT）或 rowcount（UPDATE/DELETE）。
        """
        if not self._initialized:
            await self.initialize()
        assert self._db is not None
        if many:
            cursor = await self._db.executemany(sql, params)
        else:
            cursor = await self._db.execute(sql, params)
        await self._db.commit()
        return cursor.lastrowid if cursor.lastrowid is not None else cursor.rowcount

    async def _fetch_one(self, sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
        """执行查询并返回单行结果，行以 sqlite3.Row 形式返回。
        使用持久连接；若未初始化则先初始化。"""
        if not self._initialized:
            await self.initialize()
        assert self._db is not None
        self._db.row_factory = sqlite3.Row
        cursor = await self._db.execute(sql, params)
        return await cursor.fetchone()

    async def _fetch_all(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        """执行查询并返回所有结果行，行以 sqlite3.Row 形式返回。
        使用持久连接；若未初始化则先初始化。"""
        if not self._initialized:
            await self.initialize()
        assert self._db is not None
        self._db.row_factory = sqlite3.Row
        cursor = await self._db.execute(sql, params)
        return await cursor.fetchall()

    # ==================== 历史记录管理 ====================

    async def add_record(self, record: HistoryRecord) -> int:
        """添加历史记录，返回记录 ID"""
        if not record.created_at:
            record.created_at = datetime.now().isoformat()

        return await self._execute_write(
            """INSERT INTO history (task_type, input_file, output_file, model_size, status, parameters, processing_time, created_at, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (record.task_type, record.input_file, record.output_file, record.model_size,
             record.status, record.parameters, record.processing_time, record.created_at, record.error_message)
        )

    async def add_records(self, records: list[HistoryRecord]) -> list[int]:
        """批量添加历史记录，通过 _execute_write 统一入口写入，失败回退到逐条插入"""
        if not records:
            return []

        now = datetime.now().isoformat()
        rows = []
        for record in records:
            if not record.created_at:
                record.created_at = now
            rows.append((
                record.task_type, record.input_file, record.output_file, record.model_size,
                record.status, record.parameters, record.processing_time, record.created_at, record.error_message
            ))

        sql = """INSERT INTO history (task_type, input_file, output_file, model_size, status, parameters, processing_time, created_at, error_message)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""

        try:
            last_id = await self._execute_write(sql, rows, many=True)
            if last_id is None:
                last_id = (await self._fetch_one("SELECT last_insert_rowid()"))[0]
        except (aiosqlite.Error, sqlite3.Error, OSError) as e:
            # ROBUSTNESS: 批量插入失败时降级为逐条插入；仅捕获 DB/IO 异常，
            # 不吞掉 KeyboardInterrupt 等系统级异常 (E2)
            logger.warning(f"批量插入失败，回退到逐条插入: {type(e).__name__}: {e}")
            last_id = None
            for row in rows:
                try:
                    await self._execute_write(sql, row)
                except (aiosqlite.Error, sqlite3.Error, OSError) as row_err:
                    logger.error(f"单条插入失败，跳过: {row_err}")
                    continue
            if last_id is None:
                result = await self._fetch_one("SELECT last_insert_rowid()")
                last_id = result[0] if result else None
            if last_id is None:
                return []

        return list(range(last_id - len(rows) + 1, last_id + 1))

    async def update_record(self, record_id: int, **kwargs) -> bool:
        """更新历史记录"""
        if not kwargs:
            return False

        # 列名白名单验证，防止 SQL 注入；SET 子句中的列名来自白名单，不存在注入风险
        allowed_columns = {"status", "output_file", "processing_time", "error_message", "parameters"}
        invalid_keys = set(kwargs.keys()) - allowed_columns
        if invalid_keys:
            raise ValueError(f"不允许更新的列: {invalid_keys}，允许的列: {allowed_columns}")

        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [record_id]

        await self._execute_write(f"UPDATE history SET {set_clause} WHERE id = ?", values)
        return True

    async def get_record(self, record_id: int) -> HistoryRecord | None:
        """获取单条记录"""
        row = await self._fetch_one("SELECT * FROM history WHERE id = ?", (record_id,))
        if row:
            return self._row_to_record(row)
        return None

    # OPTIMIZE: 批量查询接口，修复 recover_tasks 中的 N+1 查询 (C3)
    # 原实现循环调用 get_record(record_id)，N 条任务产生 N 次 DB 查询
    async def get_records_by_ids(self, record_ids: Sequence[int]) -> list[HistoryRecord]:
        """根据多个 ID 批量查询历史记录。

        Args:
            record_ids: 历史记录 ID 序列（允许重复与空）

        Returns:
            命中的 HistoryRecord 列表（顺序以数据库返回为准，不保证与输入顺序一致）。
            空输入返回空列表，避免在 SQL 中构造空 IN() 子句。
        """
        ids = [int(rid) for rid in record_ids if rid is not None]
        if not ids:
            return []
        placeholders = ", ".join("?" for _ in ids)
        rows = await self._fetch_all(
            f"SELECT * FROM history WHERE id IN ({placeholders})",
            tuple(ids),
        )
        return [self._row_to_record(row) for row in rows]

    async def get_records(
        self,
        task_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
        order_by: str = "created_at",
        order_dir: str = "DESC"
    ) -> tuple[list[HistoryRecord], int]:
        """获取记录列表（分页）"""
        conditions = []
        params: list = []

        if task_type:
            conditions.append("task_type = ?")
            params.append(task_type)
        if status:
            conditions.append("status = ?")
            params.append(status)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # 获取分页数据
        valid_orders = {"created_at", "id", "task_type", "status", "processing_time"}
        if order_by not in valid_orders:
            order_by = "created_at"
        if order_dir not in ("ASC", "DESC"):
            order_dir = "DESC"

        # 获取总数
        count_row = await self._fetch_one(f"SELECT COUNT(*) FROM history WHERE {where_clause}", params)
        total = count_row[0] if count_row else 0

        rows = await self._fetch_all(
            f"SELECT * FROM history WHERE {where_clause} ORDER BY {order_by} {order_dir} LIMIT ? OFFSET ?",
            params + [limit, offset]
        )
        records = [self._row_to_record(row) for row in rows]
        return records, total

    async def search_records(
        self,
        query: str,
        limit: int = 50,
        offset: int = 0
    ) -> tuple[list[HistoryRecord], int]:
        """全文搜索记录"""
        if not query.strip():
            return await self.get_records(limit=limit, offset=offset)

        # SECURITY: FTS5 查询转义，防止用户输入注入 FTS5 操作符（*, OR, AND, NOT, "", (), :, ^, -）
        # 原实现直接把 query 传给 MATCH，可被构造恶意查询导致语法错误或绕过预期行为
        safe_query = escape_fts_query(query)

        # 使用 FTS5 搜索
        rows = await self._fetch_all(
            """SELECT h.* FROM history h
               JOIN history_fts fts ON h.id = fts.id
               WHERE history_fts MATCH ?
               ORDER BY h.created_at DESC
               LIMIT ? OFFSET ?""",
            (safe_query, limit, offset)
        )
        records = [self._row_to_record(row) for row in rows]

        # 获取搜索结果总数
        count_row = await self._fetch_one(
            "SELECT COUNT(*) FROM history_fts WHERE history_fts MATCH ?",
            (safe_query,)
        )
        total = count_row[0] if count_row else 0

        return records, total

    async def delete_record(self, record_id: int) -> bool:
        """删除记录"""
        await self._execute_write("DELETE FROM history WHERE id = ?", (record_id,))
        return True

    async def clear_records(self, before_date: str | None = None) -> int:
        """清除记录"""
        if before_date:
            return await self._execute_write(
                "DELETE FROM history WHERE created_at < ?", (before_date,)
            )
        return await self._execute_write("DELETE FROM history")

    # ==================== 任务状态持久化 ====================

    async def create_task(self, record: TaskRecord) -> bool:
        """创建任务记录"""
        if not record.updated_at:
            record.updated_at = datetime.now().isoformat()

        await self._execute_write(
            """INSERT INTO tasks (task_id, record_id, status, progress, output_path, error_message, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (record.task_id, record.record_id, record.status, record.progress,
             record.output_path, record.error_message, record.updated_at)
        )
        return True

    async def update_task(self, task_id: str, **kwargs) -> bool:
        """更新任务记录"""
        if not kwargs:
            return False

        # 列名白名单验证，防止 SQL 注入；SET 子句中的列名来自白名单，不存在注入风险
        allowed_columns = {"record_id", "status", "progress", "output_path", "error_message"}
        invalid_keys = set(kwargs.keys()) - allowed_columns
        if invalid_keys:
            raise ValueError(f"不允许更新的列: {invalid_keys}，允许的列: {allowed_columns}")

        set_clause = ", ".join(f"{k} = ?" for k in kwargs)

        await self._execute_write(
            f"UPDATE tasks SET {set_clause}, updated_at = ? WHERE task_id = ?",
            list(kwargs.values()) + [datetime.now().isoformat(), task_id]
        )
        return True

    async def get_task(self, task_id: str) -> TaskRecord | None:
        """获取单条任务记录"""
        row = await self._fetch_one("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
        if row:
            return self._row_to_task_record(row)
        return None

    async def get_task_by_record_id(self, record_id: int) -> TaskRecord | None:
        """通过历史记录 ID 获取关联任务"""
        row = await self._fetch_one(
            "SELECT * FROM tasks WHERE record_id = ? ORDER BY updated_at DESC LIMIT 1",
            (record_id,)
        )
        if row:
            return self._row_to_task_record(row)
        return None

    async def get_tasks_by_status(self, status) -> list[TaskRecord]:
        """根据状态获取任务列表；status 可以是单个状态字符串或状态集合"""
        statuses = {status} if isinstance(status, str) else set(status)
        placeholders = ", ".join("?" for _ in statuses)
        params = list(statuses)

        rows = await self._fetch_all(
            f"SELECT * FROM tasks WHERE status IN ({placeholders}) ORDER BY updated_at DESC",
            params
        )
        return [self._row_to_task_record(row) for row in rows]

    async def delete_task(self, task_id: str) -> bool:
        """删除任务记录"""
        await self._execute_write("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        return True

    async def get_incomplete_tasks(self) -> list[TaskRecord]:
        """获取未完成的任务（pending / processing）"""
        return await self.get_tasks_by_status({"pending", "processing"})

    async def get_statistics(self) -> dict:
        """获取统计信息"""
        # 总记录数
        total_row = await self._fetch_one("SELECT COUNT(*) FROM history")
        total = total_row[0] if total_row else 0

        # 按类型统计
        type_rows = await self._fetch_all(
            "SELECT task_type, COUNT(*) as cnt FROM history GROUP BY task_type"
        )
        by_type = dict(type_rows)

        # 按状态统计
        status_rows = await self._fetch_all(
            "SELECT status, COUNT(*) as cnt FROM history GROUP BY status"
        )
        by_status = dict(status_rows)

        # 平均处理时间
        avg_row = await self._fetch_one(
            "SELECT AVG(processing_time) FROM history WHERE status = 'completed'"
        )
        avg_time = avg_row[0] if avg_row and avg_row[0] else 0

        return {
            "total_records": total,
            "by_type": by_type,
            "by_status": by_status,
            "avg_processing_time": round(avg_time, 2),
        }

    async def close(self):
        """关闭持久数据库连接"""
        if self._db is not None:
            # ROBUSTNESS: 即使 close() 抛异常，也要确保内部状态被重置 (E7)
            try:
                await self._db.close()
            except (aiosqlite.Error, sqlite3.Error) as e:
                logger.warning(f"关闭数据库连接时出现异常（已忽略）: {e}")
            finally:
                self._db = None
                self._initialized = False
                logger.info(f"历史数据库连接已关闭: {self.db_path}")

    def _row_to_record(self, row: sqlite3.Row) -> HistoryRecord:
        """将数据库行转换为 HistoryRecord"""
        return HistoryRecord(
            id=row["id"],
            task_type=row["task_type"],
            input_file=row["input_file"],
            output_file=row["output_file"],
            model_size=row["model_size"],
            status=row["status"],
            parameters=row["parameters"],
            processing_time=row["processing_time"],
            created_at=row["created_at"],
            error_message=row["error_message"],
        )

    def _row_to_task_record(self, row: sqlite3.Row) -> TaskRecord:
        """将数据库行转换为 TaskRecord"""
        return TaskRecord(
            task_id=row["task_id"],
            record_id=row["record_id"],
            status=row["status"],
            progress=row["progress"],
            output_path=row["output_path"],
            error_message=row["error_message"],
            updated_at=row["updated_at"],
        )

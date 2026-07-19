"""测试 TaskQueue 单 worker 任务队列

ROBUSTNESS: 覆盖任务超时（asyncio.wait_for）、worker 异常自动重启、
           队列 maxsize 限制、取消机制、哨兵优雅退出等关键路径。
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from bin.integrated_app.task_queue import (
    DEFAULT_QUEUE_MAXSIZE,
    DEFAULT_TASK_TIMEOUT_SECONDS,
    MAX_WORKER_RESTARTS,
    TaskQueue,
)


@pytest.fixture
async def started_queue():
    """启动并自动停止的 TaskQueue fixture"""
    q = TaskQueue(maxsize=10, task_timeout_seconds=5)
    await q.start()
    try:
        yield q
    finally:
        await q.stop()


class TestTaskQueueInit:
    """初始化参数与默认值"""

    def test_default_values(self):
        q = TaskQueue()
        assert q.queue_size == 0
        assert q.current_task_id is None

    def test_custom_maxsize(self):
        q = TaskQueue(maxsize=42)
        assert q.queue_size == 0

    def test_negative_maxsize_normalized_to_zero(self):
        # max(0, -1) = 0 表示无界队列
        q = TaskQueue(maxsize=-1)
        assert q.queue_size == 0

    def test_task_timeout_minimum_one_second(self):
        # max(1, 0) = 1，防止 0 或负数导致 wait_for 立即超时
        q = TaskQueue(task_timeout_seconds=0)
        assert q._task_timeout == 1

    def test_default_constants(self):
        assert DEFAULT_QUEUE_MAXSIZE == 100
        assert DEFAULT_TASK_TIMEOUT_SECONDS == 3600
        assert MAX_WORKER_RESTARTS == 3


class TestTaskQueueSubmitAndExecute:
    """提交与执行"""

    @pytest.mark.asyncio
    async def test_submit_executes_task(self, started_queue):
        executed = asyncio.Event()

        async def task():
            executed.set()

        await started_queue.submit("t1", task)
        await asyncio.wait_for(executed.wait(), timeout=2.0)
        assert executed.is_set()

    @pytest.mark.asyncio
    async def test_tasks_executed_sequentially(self, started_queue):
        """单 worker 保证串行执行"""
        order: list[str] = []

        def make(name: str):
            async def task():
                order.append(f"start-{name}")
                await asyncio.sleep(0.05)
                order.append(f"end-{name}")

            return task

        await started_queue.submit("a", make("a"))
        await started_queue.submit("b", make("b"))
        # 等待两个任务都完成
        await asyncio.sleep(0.3)
        # 串行：a 完全结束后 b 才开始
        assert order == ["start-a", "end-a", "start-b", "end-b"]

    @pytest.mark.asyncio
    async def test_current_task_id_during_execution(self, started_queue):
        captured: list[str | None] = []
        in_task = asyncio.Event()

        async def task():
            captured.append(started_queue.current_task_id)
            in_task.set()

        await started_queue.submit("running-task", task)
        await asyncio.wait_for(in_task.wait(), timeout=2.0)
        await asyncio.sleep(0.05)
        # 任务结束后 current_task_id 被清空
        assert captured == ["running-task"]
        assert started_queue.current_task_id is None


class TestTaskQueueCancel:
    """取消机制"""

    @pytest.mark.asyncio
    async def test_cancel_running_task(self, started_queue):
        cancelled = asyncio.Event()

        async def task():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        await started_queue.submit("cancellable", task)
        await asyncio.sleep(0.05)  # 等任务进入运行
        assert started_queue.request_cancel("cancellable") is True
        assert started_queue.is_cancelled("cancellable") is True
        await asyncio.wait_for(cancelled.wait(), timeout=2.0)
        assert cancelled.is_set()

    @pytest.mark.asyncio
    async def test_cancel_queued_task_skips_execution(self, started_queue):
        """队列中的任务被取消后，worker 取出时跳过"""
        executed = asyncio.Event()

        async def blocker():
            await asyncio.sleep(0.2)

        async def victim():
            executed.set()

        await started_queue.submit("blocker", blocker)
        await started_queue.submit("victim", victim)
        # victim 在队列中时取消
        assert started_queue.request_cancel("victim") is True
        await asyncio.sleep(0.4)
        # victim 应被跳过，未执行
        assert executed.is_set() is False

    def test_cancel_unknown_task_returns_true(self):
        q = TaskQueue()
        # 即使任务不存在，标记取消也返回 True（幂等）
        assert q.request_cancel("nonexistent") is True
        assert q.is_cancelled("nonexistent") is True


class TestTaskQueueTimeout:
    """E6: 任务级超时"""

    @pytest.mark.asyncio
    async def test_task_timeout_cancels_hanging_task(self):
        q = TaskQueue(maxsize=5, task_timeout_seconds=1)
        await q.start()
        try:
            timed_out = asyncio.Event()

            async def hanging_task():
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    timed_out.set()
                    raise

            await q.submit("hanging", hanging_task)
            await asyncio.wait_for(timed_out.wait(), timeout=3.0)
            assert timed_out.is_set()
        finally:
            await q.stop()


class TestTaskQueueWorkerRestart:
    """E4: worker 异常自动重启

    注：task 自身的异常由 _worker 内部 except Exception 捕获，不会传播到
    _worker_guarded。_worker_guarded 的重启机制仅针对 _worker() 自身的
    未预期崩溃（如 asyncio 内部错误、_queue.get 异常等基础设施级故障）。
    """

    @pytest.mark.asyncio
    async def test_task_exception_does_not_crash_worker(self, started_queue):
        """任务抛出未预期异常时，worker 应继续处理后续任务（异常被内部捕获）"""
        normal_executed = asyncio.Event()

        async def crashing():
            raise RuntimeError("任务内部异常")

        async def normal():
            normal_executed.set()

        await started_queue.submit("crash", crashing)
        await asyncio.sleep(0.1)
        # worker 应仍存活，能处理后续任务
        await started_queue.submit("normal", normal)
        await asyncio.wait_for(normal_executed.wait(), timeout=2.0)
        assert normal_executed.is_set()
        # 任务异常不应触发 worker 重启
        assert started_queue._restart_count == 0

    @pytest.mark.asyncio
    async def test_worker_guarded_restarts_on_worker_crash(self):
        """_worker() 自身崩溃时，_worker_guarded 应重启并增加计数"""
        q = TaskQueue(maxsize=10, task_timeout_seconds=5)
        await q.start()
        try:
            original_worker = q._worker
            call_count = 0

            async def crashing_worker():
                nonlocal call_count
                call_count += 1
                if call_count <= 2:
                    raise RuntimeError(f"_worker 内部崩溃 #{call_count}")
                # 第三次正常退出（收到哨兵）
                await original_worker()

            # 替换 _worker 为会崩溃的版本
            q._worker = crashing_worker
            # 重新启动 guarded 循环
            q._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await q._worker_task
            q._worker_task = asyncio.create_task(q._worker_guarded())

            # 触发 worker 运行：submit 一个任务，再 stop
            async def noop():
                pass

            await q.submit("trigger", noop)
            await asyncio.sleep(0.3)
            # _worker 崩溃后应重启，restart_count 增加
            assert q._restart_count >= 1
        finally:
            await q.stop()

    @pytest.mark.asyncio
    async def test_worker_guarded_gives_up_after_max_restarts(self, monkeypatch):
        """连续超过 MAX_WORKER_RESTARTS 次后停止重启

        通过 monkeypatch 将重启间的 sleep 缩短到 0.01s 加速测试。
        """
        # 加速重启间隔
        import bin.integrated_app.task_queue as tq_module

        original_sleep = tq_module.asyncio.sleep

        async def fast_sleep(delay):
            # 仅缩短 task_queue 内部的 1s 重启等待；其他 sleep 走原逻辑
            if delay == 1.0:
                await original_sleep(0.01)
            else:
                await original_sleep(delay)

        monkeypatch.setattr(tq_module.asyncio, "sleep", fast_sleep)

        q = TaskQueue(maxsize=10, task_timeout_seconds=5)
        await q.start()
        try:

            async def always_crash_worker():
                raise RuntimeError("_worker 持续崩溃")

            q._worker = always_crash_worker
            q._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await q._worker_task
            q._worker_task = asyncio.create_task(q._worker_guarded())

            # 等待 worker 走完所有重启尝试
            await asyncio.wait_for(q._worker_task, timeout=5.0)
            # 重启次数应超过 MAX_WORKER_RESTARTS，worker 任务已结束
            assert q._restart_count > MAX_WORKER_RESTARTS
            assert q._worker_task.done()
        finally:
            await q.stop()


class TestTaskQueueGracefulStop:
    """优雅退出"""

    @pytest.mark.asyncio
    async def test_stop_terminates_worker(self):
        q = TaskQueue()
        await q.start()
        assert q._worker_task is not None
        await q.stop()
        assert q._worker_task is None

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        q = TaskQueue()
        await q.start()
        first = q._worker_task
        await q.start()  # 重复启动不应创建新 worker
        assert q._worker_task is first
        await q.stop()


class TestTaskQueueMaxsize:
    """E3: 队列容量限制"""

    @pytest.mark.asyncio
    async def test_maxsize_bounds_queue(self, started_queue):
        """maxsize=10 时，第 11 个 submit 应阻塞"""
        blocker_done = asyncio.Event()

        async def blocker():
            await blocker_done.wait()

        # 先占住 worker
        await started_queue.submit("blocker", blocker)
        await asyncio.sleep(0.05)
        # 填满队列（maxsize=10）
        for i in range(10):
            await started_queue.submit(f"q-{i}", blocker)
        # 队列已满；submit 应阻塞
        slow_put = asyncio.create_task(started_queue.submit("overflow", blocker))
        await asyncio.sleep(0.1)
        assert not slow_put.done()
        # 释放 blocker，让 overflow 入队
        blocker_done.set()
        await asyncio.wait_for(slow_put, timeout=2.0)

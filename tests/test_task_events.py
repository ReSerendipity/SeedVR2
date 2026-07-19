"""测试 TaskEventBus 任务进度事件总线

覆盖:
- 按 task_id 发布/订阅
- 多订阅者广播
- publish_final 缓存最终状态供迟到订阅者读取
- QueueFull 背压不抛异常
- cleanup_expired 自动清理
- clear_task 彻底清除
- 线程安全（publish 可从非 asyncio 线程调用）
"""

from __future__ import annotations

import asyncio

import pytest

from bin.integrated_app.services.task_events import TaskEventBus


@pytest.fixture
def bus():
    return TaskEventBus(queue_maxsize=8, final_event_ttl=1.0)


class TestSubscribeAndPublish:
    """基础订阅/发布"""

    @pytest.mark.asyncio
    async def test_subscribe_returns_queue(self, bus):
        q = await bus.subscribe("t1")
        assert isinstance(q, asyncio.Queue)
        assert bus.active_task_count == 1

    @pytest.mark.asyncio
    async def test_publish_delivers_to_subscriber(self, bus):
        q = await bus.subscribe("t1")
        bus.publish("t1", {"progress": 0.5, "current_frame": 50})
        event = await asyncio.wait_for(q.get(), timeout=1.0)
        assert event["event"] == "progress"
        assert event["data"]["progress"] == 0.5
        assert event["data"]["current_frame"] == 50
        assert "timestamp" in event

    @pytest.mark.asyncio
    async def test_publish_no_subscribers_silent(self, bus):
        # 无订阅者时 publish 不抛异常
        bus.publish("nobody", {"progress": 0.1})

    @pytest.mark.asyncio
    async def test_publish_broadcasts_to_multiple_subscribers(self, bus):
        q1 = await bus.subscribe("broadcast")
        q2 = await bus.subscribe("broadcast")
        q3 = await bus.subscribe("broadcast")
        bus.publish("broadcast", {"progress": 0.3})
        for q in (q1, q2, q3):
            event = await asyncio.wait_for(q.get(), timeout=1.0)
            assert event["data"]["progress"] == 0.3


class TestUnsubscribe:
    """取消订阅"""

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_queue(self, bus):
        q = await bus.subscribe("t-u")
        assert bus.active_task_count == 1
        await bus.unsubscribe("t-u", q)
        # 取消后 publish 不应投递
        bus.publish("t-u", {"progress": 0.5})
        assert q.empty()

    @pytest.mark.asyncio
    async def test_unsubscribe_cleans_up_empty_task(self, bus):
        """所有订阅者取消后，task_id 应从 _subscribers 中移除"""
        q = await bus.subscribe("t-cleanup")
        await bus.unsubscribe("t-cleanup", q)
        assert "t-cleanup" not in bus._subscribers
        assert bus.active_task_count == 0

    @pytest.mark.asyncio
    async def test_unsubscribe_unknown_task_silent(self, bus):
        """取消不存在的 task 不抛异常"""
        ghost_q = asyncio.Queue(maxsize=8)
        await bus.unsubscribe("ghost", ghost_q)


class TestPublishFinal:
    """最终状态缓存与投递"""

    @pytest.mark.asyncio
    async def test_publish_final_delivers_to_subscribers(self, bus):
        q = await bus.subscribe("t-final")
        bus.publish_final("t-final", {"status": "completed", "output_path": "/out/x.png"})
        event = await asyncio.wait_for(q.get(), timeout=1.0)
        assert event["event"] == "final"
        assert event["data"]["status"] == "completed"
        assert event["data"]["output_path"] == "/out/x.png"

    @pytest.mark.asyncio
    async def test_publish_final_caches_for_late_subscribers(self, bus):
        """任务结束后才订阅的客户端应立即收到最终状态"""
        bus.publish_final("late", {"status": "completed"})
        q = await bus.subscribe("late")
        # 应立即在队列中收到 final 事件
        event = await asyncio.wait_for(q.get(), timeout=1.0)
        assert event["event"] == "final"
        assert event["data"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_get_final_status(self, bus):
        bus.publish_final("status-check", {"status": "failed", "error": "OOM"})
        status = bus.get_final_status("status-check")
        assert status == {"status": "failed", "error": "OOM"}

    @pytest.mark.asyncio
    async def test_get_final_status_missing(self, bus):
        assert bus.get_final_status("nope") is None


class TestCleanupExpired:
    """过期最终状态清理"""

    @pytest.mark.asyncio
    async def test_cleanup_removes_expired(self, bus):
        # final_event_ttl=1.0
        bus.publish_final("old", {"status": "completed"})
        # 等待超过 TTL
        await asyncio.sleep(1.2)
        removed = bus.cleanup_expired()
        assert removed == 1
        assert bus.get_final_status("old") is None

    @pytest.mark.asyncio
    async def test_cleanup_keeps_recent(self, bus):
        bus.publish_final("fresh", {"status": "completed"})
        removed = bus.cleanup_expired()
        assert removed == 0
        assert bus.get_final_status("fresh") is not None

    @pytest.mark.asyncio
    async def test_cleanup_empty_returns_zero(self, bus):
        assert bus.cleanup_expired() == 0


class TestClearTask:
    """彻底清除任务相关数据"""

    @pytest.mark.asyncio
    async def test_clear_task_removes_subscribers_and_final(self, bus):
        await bus.subscribe("t-clear")
        bus.publish_final("t-clear", {"status": "completed"})
        bus.clear_task("t-clear")
        assert "t-clear" not in bus._subscribers
        assert bus.get_final_status("t-clear") is None

    @pytest.mark.asyncio
    async def test_clear_task_unknown_silent(self, bus):
        bus.clear_task("ghost")


class TestBackpressure:
    """QueueFull 背压：不抛异常，丢弃并记录日志"""

    @pytest.mark.asyncio
    async def test_publish_drops_when_queue_full(self, bus):
        """queue_maxsize=8 时，第 9 条应被丢弃而非抛 QueueFull"""
        q = await bus.subscribe("t-full")
        for i in range(20):
            # publish 不应抛 QueueFull
            bus.publish("t-full", {"i": i})
        # 队列最多 8 条
        count = 0
        while not q.empty():
            await q.get()
            count += 1
        assert count == 8

    @pytest.mark.asyncio
    async def test_publish_final_drops_when_queue_full(self, bus):
        q = await bus.subscribe("t-final-full")
        for i in range(20):
            bus.publish_final("t-final-full", {"i": i})
        # 仍能从缓存读到最终状态（最后一次 publish_final 的值）
        status = bus.get_final_status("t-final-full")
        assert status == {"i": 19}
        # 队列最多 8 条
        count = 0
        while not q.empty():
            await q.get()
            count += 1
        assert count == 8


class TestProperties:
    """属性访问"""

    @pytest.mark.asyncio
    async def test_active_task_count(self, bus):
        assert bus.active_task_count == 0
        await bus.subscribe("a")
        await bus.subscribe("b")
        assert bus.active_task_count == 2

    @pytest.mark.asyncio
    async def test_queue_maxsize_minimum_8(self):
        """queue_maxsize < 8 时被钳制为 8"""
        bus = TaskEventBus(queue_maxsize=1)
        assert bus._queue_maxsize == 8

    @pytest.mark.asyncio
    async def test_final_ttl_minimum_1(self):
        bus = TaskEventBus(final_event_ttl=0.1)
        assert bus._final_ttl == 1.0


class TestThreadSafety:
    """publish 可从非 asyncio 线程调用"""

    @pytest.mark.asyncio
    async def test_publish_from_another_thread(self, bus):
        """模拟推理回调线程调用 publish"""
        q = await bus.subscribe("t-thread")
        received = asyncio.Event()

        async def reader():
            await q.get()
            received.set()

        reader_task = asyncio.create_task(reader())
        # 在另一个线程中 publish
        import threading

        thread = threading.Thread(target=bus.publish, args=("t-thread", {"progress": 0.5}))
        thread.start()
        thread.join()
        await asyncio.wait_for(reader_task, timeout=1.0)
        assert received.is_set()

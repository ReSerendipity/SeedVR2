"""SeedVR2 工具箱 - 任务进度事件总线

替代 progress 端点的 DB 高频轮询（原实现每 0.5s 轮询一次数据库，C10 热路径）。
任务执行时主动 publish 进度，progress 端点订阅事件流，实现推送模式。

设计要点:
- 按 task_id 订阅：每个任务有独立的订阅者集合
- asyncio.Queue：每订阅者独立队列，背压通过 maxsize 控制
- 自动清理：任务完成后保留最后状态，订阅者读取后自动清理
- 线程安全：publish 可从任意线程调用（如推理回调）
"""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

# 每订阅者队列上限，防止慢消费者导致内存溢出
_DEFAULT_QUEUE_MAXSIZE = 64
# 任务完成后事件保留时间（秒），供迟到的订阅者读取最终状态
_DEFAULT_FINAL_EVENT_TTL = 60.0


class TaskEventBus:
    """任务进度事件总线 - 按 task_id 的发布/订阅。

    使用场景:
    - 推理引擎在处理过程中调用 publish(task_id, {"progress": 0.5, ...})
    - SSE progress 端点调用 subscribe(task_id) 获取事件流
    - 任务完成/失败时调用 publish_final(task_id, ...) 发送最终状态
    """

    def __init__(
        self,
        queue_maxsize: int = _DEFAULT_QUEUE_MAXSIZE,
        final_event_ttl: float = _DEFAULT_FINAL_EVENT_TTL,
    ):
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        # 任务最终状态的缓存，供迟到的订阅者读取
        self._final_events: dict[str, tuple[float, dict]] = {}
        self._queue_maxsize = max(8, queue_maxsize)
        self._final_ttl = max(1.0, final_event_ttl)
        self._lock = asyncio.Lock()

    async def subscribe(self, task_id: str) -> asyncio.Queue:
        """订阅指定任务的进度事件。

        如果任务已有最终状态（已完成/失败），会立即将最终事件放入队列。

        Args:
            task_id: 任务唯一标识

        Returns:
            用于接收事件的 asyncio.Queue
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_maxsize)
        async with self._lock:
            self._subscribers.setdefault(task_id, set()).add(queue)
            # 如果任务已结束，立即投递最终状态
            final = self._final_events.get(task_id)
        if final is not None:
            try:
                queue.put_nowait({"event": "final", "data": final[1], "timestamp": final[0]})
            except asyncio.QueueFull:
                logger.warning(f"订阅队列已满(task_id={task_id})，无法投递最终状态")
        return queue

    async def unsubscribe(self, task_id: str, queue: asyncio.Queue) -> None:
        """取消订阅"""
        async with self._lock:
            subs = self._subscribers.get(task_id)
            if subs:
                subs.discard(queue)
                if not subs:
                    del self._subscribers[task_id]

    def publish(self, task_id: str, data: dict) -> None:
        """发布任务进度事件到所有订阅者。

        线程安全：可从非 asyncio 线程调用（如推理回调线程）。

        Args:
            task_id: 任务唯一标识
            data: 进度数据（如 {"progress": 0.5, "current_frame": 100, ...}）
        """
        event = {
            "event": "progress",
            "data": data,
            "timestamp": time.time(),
        }
        subs = self._subscribers.get(task_id)
        if not subs:
            return
        for queue in list(subs):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(f"订阅队列已满(task_id={task_id})，丢弃进度事件")

    def publish_final(self, task_id: str, data: dict) -> None:
        """发布任务最终状态（完成/失败/取消）。

        最终状态会被缓存，迟到的订阅者仍可读取。
        缓存到期后自动清理。

        Args:
            task_id: 任务唯一标识
            data: 最终状态（如 {"status": "completed", "output_path": "..."}）
        """
        now = time.time()
        event = {
            "event": "final",
            "data": data,
            "timestamp": now,
        }
        # 缓存最终状态
        self._final_events[task_id] = (now, data)
        # 投递到当前订阅者
        subs = self._subscribers.get(task_id)
        if subs:
            for queue in list(subs):
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(f"订阅队列已满(task_id={task_id})，丢弃最终事件")

    def cleanup_expired(self) -> int:
        """清理过期的最终状态缓存。建议定期调用。

        Returns:
            清理的条目数
        """
        now = time.time()
        expired = [
            tid for tid, (ts, _) in self._final_events.items()
            if now - ts > self._final_ttl
        ]
        for tid in expired:
            del self._final_events[tid]
        return len(expired)

    def get_final_status(self, task_id: str) -> dict | None:
        """获取任务的缓存最终状态（如有）。

        适用于客户端轮询兜底：如果事件总线有最终状态，直接返回，无需查 DB。
        """
        entry = self._final_events.get(task_id)
        return entry[1] if entry is not None else None

    def clear_task(self, task_id: str) -> None:
        """彻底清除任务相关的事件和订阅（任务删除时调用）。"""
        self._subscribers.pop(task_id, None)
        self._final_events.pop(task_id, None)

    @property
    def active_task_count(self) -> int:
        """当前有活跃订阅者的任务数"""
        return len(self._subscribers)


# 全局单例
task_event_bus = TaskEventBus()

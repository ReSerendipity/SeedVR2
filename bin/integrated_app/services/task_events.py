"""SeedVR2 - 任务进度事件总线。

实现发布/订阅 (Pub/Sub) 模式的任务进度事件系统，替代原 progress 端点的
数据库高频轮询方案（原实现每 0.5s 轮询一次数据库，属于 C10 热路径性能瓶颈）。

性能优化:
    - 推送替代轮询：任务执行时主动 publish 进度，SSE 端点订阅事件流，
        将 O(N) 轮询降为 O(1) 事件驱动
    - 背压控制：每订阅者独立 asyncio.Queue，maxsize 限制防止慢消费者内存溢出
    - 线程安全发布：publish/publish_final 可从任意线程调用（如推理回调线程），
        通过 threading.Lock 保护共享数据结构访问

设计模式:
    - 发布/订阅模式 (Pub/Sub)：发布者与订阅者解耦，支持多订阅者
    - 按 task_id 分片：每个任务有独立的订阅者集合，避免广播风暴
    - 最终一致性：任务完成后保留最终状态缓存，迟到订阅者仍可读取
    - TTL 自动清理：最终状态缓存带 TTL，到期自动清理防止内存泄漏

内存管理:
    - 队列上限：每订阅者队列最多 64 条事件，满时丢弃旧事件并记录警告
    - 自动取消订阅：unsubscribe 时清理空订阅者集合
    - 最终事件 TTL：默认 60 秒，超过后自动清理
    - 显式清理：任务删除时调用 clear_task 彻底清除相关资源
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time

logger = logging.getLogger(__name__)

_DEFAULT_QUEUE_MAXSIZE = 64
_DEFAULT_FINAL_EVENT_TTL = 60.0


class TaskEventBus:
    """任务进度事件总线 - 按 task_id 分片的发布/订阅系统。

    提供任务进度事件的实时推送能力，主要用于 SSE (Server-Sent Events) 进度端点。
    支持跨线程发布，线程安全。

    典型工作流:
        1. SSE 端点连接时调用 subscribe(task_id) 获取队列
        2. 推理引擎在回调中调用 publish(task_id, data) 推送进度
        3. 任务完成时调用 publish_final(task_id, data) 发送最终状态
        4. SSE 连接断开时调用 unsubscribe(task_id, queue) 清理
        5. 定期调用 cleanup_expired() 清理过期最终状态缓存

    Attributes:
        _subscribers: task_id -> set[Queue] 的订阅者映射
        _final_events: task_id -> (timestamp, data) 的最终状态缓存
        _queue_maxsize: 每订阅者队列最大长度
        _final_ttl: 最终状态缓存 TTL（秒）
        _async_lock: asyncio 锁，保护异步方法中的订阅者集合修改
        _thread_lock: 线程锁，保护跨线程访问的共享数据结构
    """

    def __init__(
        self,
        queue_maxsize: int = _DEFAULT_QUEUE_MAXSIZE,
        final_event_ttl: float = _DEFAULT_FINAL_EVENT_TTL,
    ):
        """初始化事件总线。

        Args:
            queue_maxsize: 每个订阅者队列的最大事件数，默认 64；
                值过小可能导致进度事件丢失，过大可能导致内存溢出
            final_event_ttl: 任务完成后最终状态的缓存时间（秒），默认 60s；
                供迟到的订阅者读取最终状态，到期后自动清理
        """
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._final_events: dict[str, tuple[float, dict]] = {}
        self._queue_maxsize = max(8, queue_maxsize)
        self._final_ttl = max(1.0, final_event_ttl)
        self._async_lock = asyncio.Lock()
        self._thread_lock = threading.Lock()

    async def subscribe(self, task_id: str) -> asyncio.Queue:
        """订阅指定任务的进度事件，返回用于接收事件的队列。

        如果任务已有最终状态（已完成/失败/取消），会立即将最终事件放入队列，
        保证订阅者不会错过最终结果，即使订阅发生在任务完成之后。

        Args:
            task_id: 任务唯一标识

        Returns:
            asyncio.Queue: 事件队列，调用方应循环 get() 接收事件；
                事件格式为 {"event": "progress"|"final", "data": {...}, "timestamp": float}
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_maxsize)
        async with self._async_lock:
            with self._thread_lock:
                self._subscribers.setdefault(task_id, set()).add(queue)
                final = self._final_events.get(task_id)
        if final is not None:
            try:
                queue.put_nowait({"event": "final", "data": final[1], "timestamp": final[0]})
            except asyncio.QueueFull:
                logger.warning(f"订阅队列已满(task_id={task_id})，无法投递最终状态")
        return queue

    async def unsubscribe(self, task_id: str, queue: asyncio.Queue) -> None:
        """取消订阅，从订阅者集合中移除指定队列。

        如果该任务没有其他订阅者，会自动清理订阅者集合条目。
        SSE 连接断开或客户端断开时应调用此方法防止内存泄漏。

        Args:
            task_id: 任务唯一标识
            queue: subscribe 返回的队列对象
        """
        async with self._async_lock:
            with self._thread_lock:
                subs = self._subscribers.get(task_id)
                if subs:
                    subs.discard(queue)
                    if not subs:
                        del self._subscribers[task_id]

    def publish(self, task_id: str, data: dict) -> None:
        """发布任务进度事件到所有活跃订阅者。

        线程安全方法：可从非 asyncio 线程直接调用（如推理引擎的回调线程）。
        使用 put_nowait 非阻塞入队，队列满时丢弃事件并记录警告（背压控制）。

        Args:
            task_id: 任务唯一标识
            data: 进度数据字典，通常包含：
                - progress: float 0.0-1.0 进度百分比
                - current_frame: int 当前处理帧
                - total_frames: int 总帧数
                - 其他业务特定字段
        """
        event = {
            "event": "progress",
            "data": data,
            "timestamp": time.time(),
        }
        # 线程安全：在锁保护下复制订阅者队列列表快照
        with self._thread_lock:
            subs = self._subscribers.get(task_id)
            if not subs:
                return
            queues = list(subs)

        for queue in queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(f"订阅队列已满(task_id={task_id})，丢弃进度事件")

    def publish_final(self, task_id: str, data: dict) -> None:
        """发布任务最终状态（完成/失败/取消）。

        最终状态会被缓存 TTL 时长，迟到的订阅者仍可读取。
        投递到所有当前订阅者后，订阅者队列不会立即清除（等待客户端主动断开）。

        Args:
            task_id: 任务唯一标识
            data: 最终状态字典，通常包含：
                - status: "completed" | "failed" | "cancelled"
                - output_path: str 输出文件路径（成功时）
                - error: str 错误信息（失败时）
                - 其他业务特定字段
        """
        now = time.time()
        event = {
            "event": "final",
            "data": data,
            "timestamp": now,
        }
        # 线程安全：在锁保护下更新最终状态并复制订阅者快照
        with self._thread_lock:
            self._final_events[task_id] = (now, data)
            subs = self._subscribers.get(task_id)
            queues = list(subs) if subs else []

        for queue in queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(f"订阅队列已满(task_id={task_id})，丢弃最终事件")

    def cleanup_expired(self) -> int:
        """清理过期的最终状态缓存，建议定期调用（如每 60 秒）。

        遍历 _final_events，删除超过 TTL 的条目，释放内存。

        Returns:
            int: 本次清理的过期条目数量
        """
        now = time.time()
        with self._thread_lock:
            expired = [tid for tid, (ts, _) in self._final_events.items() if now - ts > self._final_ttl]
            for tid in expired:
                del self._final_events[tid]
        return len(expired)

    def get_final_status(self, task_id: str) -> dict | None:
        """获取任务的缓存最终状态（如有）。

        适用于客户端轮询兜底场景：如果事件总线已有最终状态，直接返回，
        无需查询数据库，减少 DB 压力。

        Args:
            task_id: 任务唯一标识

        Returns:
            dict | None: 最终状态数据字典，不存在或已过期返回 None
        """
        with self._thread_lock:
            entry = self._final_events.get(task_id)
            return entry[1] if entry is not None else None

    def clear_task(self, task_id: str) -> None:
        """彻底清除指定任务相关的所有事件和订阅。

        任务从历史记录中删除时调用此方法，防止内存泄漏。
        会同时清除订阅者集合和最终状态缓存。

        Args:
            task_id: 任务唯一标识
        """
        with self._thread_lock:
            self._subscribers.pop(task_id, None)
            self._final_events.pop(task_id, None)

    @property
    def active_task_count(self) -> int:
        """当前有活跃订阅者的任务数量。

        Returns:
            int: 正在被订阅的任务数
        """
        with self._thread_lock:
            return len(self._subscribers)


task_event_bus = TaskEventBus()
"""全局单例 - 任务事件总线实例。

应用启动时创建，整个生命周期复用，无需重复实例化。
路由和服务层应直接导入此单例使用，不要自行创建 TaskEventBus 实例。
"""

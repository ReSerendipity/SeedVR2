#!/usr/bin/env python3
"""全局 SSE 事件总线与端点模块。

提供发布/订阅模式的 Server-Sent Events 事件总线，用于跨模块实时推送事件到前端。
客户端通过 EventSource 连接 /api/sse/events 端点后可接收多种事件类型：
- model_status: 模型加载/卸载/切换状态更新
- (其他事件类型可通过 event_bus.publish() 发布)

实现特点：
- 使用 asyncio.Queue 为每个订阅者维护独立队列，支持多客户端并发
- EventBus 单例管理全局订阅/发布
- 定期发送心跳保活，防止连接被中间件超时断开
- 客户端断开时自动清理队列资源

API 端点：
- GET /api/sse/events: SSE 事件流端点（无前缀，直接注册在根路径）

所属项目：SeedVR2 (SeedVR2 视频/图像修复工具)
"""

import asyncio
import contextlib
import json
import logging
import time
import weakref
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sse"])

HEARTBEAT_INTERVAL = 30


class EventBus:
    """SSE 事件总线 - 发布/订阅模式实现。

    使用 weakref.WeakSet 管理订阅者队列，队列被垃圾回收时自动移除订阅。
    publish() 方法可从任意线程调用（线程安全）。

    会话隔离 (T4-4):
        - subscribe() 可传入 session_id 绑定订阅者会话
        - publish() 可传入 target_session 指定目标会话
        - 事件仅投递给匹配 session_id 的订阅者；target_session=None 时广播给所有

    Attributes:
        _subscribers: 订阅者队列的弱引用集合。
        _session_map: 订阅者队列到 session_id 的映射。
        _lock: 保护订阅/取消订阅操作的 asyncio 锁。
    """

    def __init__(self):
        """初始化 EventBus，创建空的订阅者集合和锁。"""
        self._subscribers: weakref.WeakSet[asyncio.Queue] = weakref.WeakSet()
        self._session_map: dict[int, str | None] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, session_id: str | None = None) -> asyncio.Queue:
        """订阅事件流，返回一个用于接收事件的 asyncio.Queue。

        调用方应在连接结束后调用 unsubscribe() 清理资源；
        也可依赖 WeakSet 自动回收。

        Args:
            session_id: 订阅者的会话 ID，用于事件过滤。为 None 时接收所有事件。

        Returns:
            新创建的 asyncio.Queue 实例，订阅者从此队列获取事件。
        """
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._subscribers.add(queue)
            self._session_map[id(queue)] = session_id
        return queue

    async def unsubscribe(self, queue: asyncio.Queue):
        """取消订阅，从订阅者集合中移除指定队列。

        Args:
            queue: 之前通过 subscribe() 获取的队列实例。
        """
        async with self._lock:
            self._subscribers.discard(queue)
            self._session_map.pop(id(queue), None)

    def publish(self, event_type: str, data: Any = None, target_session: str | None = None):
        """发布事件到所有活跃订阅者。

        线程安全方法，可从非 asyncio 线程（如推理线程）调用。
        队列满时会丢弃该订阅者的事件并记录警告。

        会话过滤 (T4-4):
            - target_session=None: 广播给所有订阅者（默认，向后兼容）
            - target_session=<id>: 仅投递给 session_id 匹配的订阅者

        Args:
            event_type: 事件类型标识符（如 "model_status"、"progress"）。
            data: 事件数据，将被 JSON 序列化，默认空字典。
            target_session: 目标会话 ID，为 None 时广播给所有订阅者。
        """
        event = {
            "event": event_type,
            "data": data if data is not None else {},
            "timestamp": time.time(),
        }
        for queue in list(self._subscribers):
            # 会话过滤: 若指定了 target_session，仅投递给匹配的订阅者
            if target_session is not None:
                sub_session = self._session_map.get(id(queue))
                if sub_session != target_session:
                    continue
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("SSE 订阅者队列已满，丢弃事件")
            except Exception:
                pass

    @property
    def subscriber_count(self) -> int:
        """获取当前活跃订阅者数量。

        Returns:
            订阅者数量。
        """
        return len(self._subscribers)


event_bus = EventBus()


def _format_sse(event_type: str, data: Any) -> str:
    """格式化 SSE 消息字符串（内部函数）。

    Args:
        event_type: SSE event 字段值。
        data: 要序列化为 JSON 的数据（支持中文，ensure_ascii=False）。

    Returns:
        符合 SSE 规范的消息字符串，格式为：
        event: <event_type>\\ndata: <json>\\n\\n
    """
    json_data = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {json_data}\n\n"


@router.get("/api/sse/events", summary="SSE 事件流", description="Server-Sent Events 实时事件推送端点")
async def sse_events(request: Request, session_id: str | None = None):
    """SSE 事件流端点。

    API 端点：GET /api/sse/events?session_id=<id>

    前端通过 EventSource API 连接此端点，根据返回的 event 字段分发处理不同类型事件。
    每个连接拥有独立的 asyncio.Queue，支持多客户端并发连接。

    会话隔离 (T4-4):
        - 可选 session_id 查询参数绑定订阅者会话
        - 发布事件时指定 target_session 可实现用户隔离
        - 未提供 session_id 时接收所有事件（向后兼容）

    请求参数：
        - session_id (optional): 会话 ID，用于事件过滤

    返回：text/event-stream 流响应。事件格式：
    - event: heartbeat - 心跳，data: {"ts": <timestamp>}
    - event: model_status - 模型状态变化，data: 模型状态详情
    - event: error - 连接错误，data: {"message": <错误信息>}

    连接断开或异常时自动取消订阅并清理资源。

    Args:
        request: FastAPI 请求对象，用于检测客户端断开。
        session_id: 可选的会话 ID，用于事件过滤。

    Returns:
        StreamingResponse (text/event-stream)。
    """
    queue = await event_bus.subscribe(session_id=session_id)

    async def event_stream() -> AsyncGenerator[str, None]:
        last_heartbeat = time.time()

        try:
            while True:
                if await request.is_disconnected():
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=5.0)
                    event_type = event.get("event", "unknown")
                    event_data = event.get("data", {})
                    yield _format_sse(event_type, event_data)
                except TimeoutError:
                    pass

                now = time.time()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                    yield _format_sse("heartbeat", {"ts": int(now)})
                    last_heartbeat = now

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"SSE stream error: {e}")
            with contextlib.suppress(Exception):
                yield _format_sse("error", {"message": "SSE 连接异常，请刷新页面重试"})
        finally:
            await event_bus.unsubscribe(queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")

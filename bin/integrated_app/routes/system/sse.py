#!/usr/bin/env python3
"""SeedVR2 SSE 事件总线与端点

提供 /api/sse/events 端点，客户端通过 EventSource 连接后可接收：
  - progress:     推理进度更新
  - model_status: 模型状态更新
  - heartbeat:    心跳保活

使用 asyncio.Queue 实现每客户端独立队列，EventBus 单例管理发布/订阅。
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

# 心跳间隔（秒）
HEARTBEAT_INTERVAL = 30


class EventBus:
    """SSE 事件总线 - 发布/订阅模式。

    使用 asyncio.Queue 为每个订阅者维护独立队列，
    publish() 将事件广播到所有活跃队列。
    """

    def __init__(self):
        self._subscribers: weakref.WeakSet[asyncio.Queue] = weakref.WeakSet()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        """订阅事件流，返回一个 asyncio.Queue。

        Returns:
            用于接收事件的 asyncio.Queue 实例。
        """
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue):
        """取消订阅，移除队列。

        Args:
            queue: 之前通过 subscribe() 获取的队列。
        """
        async with self._lock:
            self._subscribers.discard(queue)

    def publish(self, event_type: str, data: Any = None):
        """发布事件到所有订阅者。

        线程安全：可从非 asyncio 线程调用。

        Args:
            event_type: 事件类型（如 "progress", "model_status", "heartbeat"）。
            data: 事件数据（将被 JSON 序列化）。
        """
        event = {
            "event": event_type,
            "data": data if data is not None else {},
            "timestamp": time.time(),
        }
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("SSE 订阅者队列已满，丢弃事件")
            except Exception:
                pass

    @property
    def subscriber_count(self) -> int:
        """当前活跃订阅者数量。"""
        return len(self._subscribers)


# 全局事件总线单例
event_bus = EventBus()


def _format_sse(event_type: str, data: Any) -> str:
    """格式化 SSE 消息。

    Args:
        event_type: SSE event 字段值。
        data: 要序列化为 JSON 的数据。

    Returns:
        格式化的 SSE 字符串 (event: ...\ndata: ...\n\n)。
    """
    json_data = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {json_data}\n\n"


@router.get("/api/sse/events", summary="SSE 事件流", description="Server-Sent Events 实时事件推送端点")
async def sse_events(request: Request):
    """SSE 事件流端点。

    前端通过 EventSource 连接此端点，根据 event 字段分发处理。
    每个连接拥有独立的 asyncio.Queue，支持并发多客户端。
    """
    queue = await event_bus.subscribe()

    async def event_stream() -> AsyncGenerator[str, None]:
        last_heartbeat = time.time()

        try:
            while True:
                if await request.is_disconnected():
                    break

                # 从队列中获取事件（带超时，以便定期发送心跳）
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=5.0)
                    event_type = event.get("event", "unknown")
                    event_data = event.get("data", {})
                    yield _format_sse(event_type, event_data)
                except asyncio.TimeoutError:
                    pass

                # 心跳
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

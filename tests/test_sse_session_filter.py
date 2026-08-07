#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2024-2026 ReSerendipity
# SPDX-License-Identifier: Apache-2.0
"""SSE 事件总线会话过滤测试 (T4-4)。

验证 EventBus 的会话隔离功能：
- target_session=None 时广播给所有订阅者
- target_session=<id> 时仅投递给匹配的订阅者
"""

import asyncio

import pytest

from bin.integrated_app.routes.system.sse import EventBus


class TestEventBusSessionFilter:
    """EventBus 会话过滤测试。"""

    @pytest.mark.asyncio
    async def test_broadcast_all(self):
        """无 target_session 时广播给所有订阅者。"""
        bus = EventBus()
        q1 = await bus.subscribe(session_id="session_a")
        q2 = await bus.subscribe(session_id="session_b")

        bus.publish("test", {"msg": "hello"})

        # 两个订阅者都应收到
        event1 = await asyncio.wait_for(q1.get(), timeout=1.0)
        event2 = await asyncio.wait_for(q2.get(), timeout=1.0)

        assert event1["data"]["msg"] == "hello"
        assert event2["data"]["msg"] == "hello"

        await bus.unsubscribe(q1)
        await bus.unsubscribe(q2)

    @pytest.mark.asyncio
    async def test_targeted_session(self):
        """指定 target_session 时仅投递给匹配的订阅者。"""
        bus = EventBus()
        q_a = await bus.subscribe(session_id="session_a")
        q_b = await bus.subscribe(session_id="session_b")

        bus.publish("private", {"msg": "secret"}, target_session="session_a")

        # session_a 应收到
        event_a = await asyncio.wait_for(q_a.get(), timeout=1.0)
        assert event_a["data"]["msg"] == "secret"

        # session_b 不应收到（超时）
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(q_b.get(), timeout=0.5)

        await bus.unsubscribe(q_a)
        await bus.unsubscribe(q_b)

    @pytest.mark.asyncio
    async def test_no_session_receives_targeted(self):
        """未绑定 session_id 的订阅者不收到定向事件。"""
        bus = EventBus()
        q_no_session = await bus.subscribe(session_id=None)

        bus.publish("private", {"msg": "secret"}, target_session="session_x")

        # 未绑定 session_id 的订阅者不收到
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(q_no_session.get(), timeout=0.5)

        await bus.unsubscribe(q_no_session)

    @pytest.mark.asyncio
    async def test_no_session_receives_broadcast(self):
        """未绑定 session_id 的订阅者收到广播事件。"""
        bus = EventBus()
        q_no_session = await bus.subscribe(session_id=None)

        bus.publish("broadcast", {"msg": "all"})

        event = await asyncio.wait_for(q_no_session.get(), timeout=1.0)
        assert event["data"]["msg"] == "all"

        await bus.unsubscribe(q_no_session)

    @pytest.mark.asyncio
    async def test_unsubscribe_cleans_session_map(self):
        """取消订阅后清理会话映射。"""
        bus = EventBus()
        q = await bus.subscribe(session_id="test_session")
        await bus.unsubscribe(q)

        # 发布定向事件不应报错
        bus.publish("test", {"msg": "hello"}, target_session="test_session")

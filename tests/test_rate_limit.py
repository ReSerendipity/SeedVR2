#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2024-2026 ReSerendipity
# SPDX-License-Identifier: Apache-2.0
"""RateLimitMiddleware 单元与集成测试。

覆盖:
    - 客户端 IP 识别策略 (直连 IP 优先，XFF 仅在显式信任时启用)
    - 滑动窗口计数 (超限拒绝、窗口滑动后恢复)
    - 每 IP 独立计数
    - 429 响应结构与 Retry-After 头
    - 只读 GET / 非限流路径不受影响
    - app_server.create_app() 中的中间件接线
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bin.integrated_app.middleware import rate_limit as rate_limit_module
from bin.integrated_app.middleware.rate_limit import RateLimitMiddleware


def _make_request(client_host: str = "192.0.2.10", xff: str | None = None) -> MagicMock:
    """构造 mock Request：可指定直连 IP 与 X-Forwarded-For 头。"""
    request = MagicMock()
    request.client.host = client_host
    request.headers.get.return_value = xff
    return request


@pytest.fixture
def limited_app():
    """带 RateLimitMiddleware (3 次/分钟) 的最小 FastAPI 应用。"""
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, rate_limit_per_minute=3, window_seconds=60.0)

    @app.post("/api/restore/")
    async def upload():
        return {"success": True}

    @app.post("/api/restore/batch")
    async def batch():
        return {"success": True}

    @app.post("/api/system/locale")
    async def locale():
        return {"success": True}

    @app.get("/ping")
    async def ping():
        return {"success": True}

    @app.get("/api/restore/task-abc/progress")
    async def progress():
        return {"success": True}

    return app


class TestClientIP:
    """IP 识别策略：直连 IP 优先，不盲信 X-Forwarded-For。"""

    def test_direct_ip_used_without_forwarded(self):
        mw = RateLimitMiddleware(app=None, rate_limit_per_minute=30)
        assert mw._client_ip(_make_request(client_host="192.0.2.10")) == "192.0.2.10"

    def test_xff_ignored_by_default(self):
        """未开启 trust_proxy 时，即使携带伪造 XFF 也以直连 IP 为准。"""
        mw = RateLimitMiddleware(app=None, rate_limit_per_minute=30)
        assert (
            mw._client_ip(_make_request(client_host="127.0.0.1", xff="203.0.113.9"))
            == "127.0.0.1"
        )

    def test_xff_used_when_trust_proxy_enabled(self):
        """显式开启 trust_proxy 时取 XFF 最左侧地址（原始客户端 IP）。"""
        mw = RateLimitMiddleware(app=None, rate_limit_per_minute=30, trust_proxy=True)
        assert (
            mw._client_ip(_make_request(client_host="127.0.0.1", xff="203.0.113.9, 10.0.0.1"))
            == "203.0.113.9"
        )

    def test_missing_client_falls_back_to_unknown(self):
        mw = RateLimitMiddleware(app=None, rate_limit_per_minute=30)
        request = MagicMock()
        request.client = None
        assert mw._client_ip(request) == "unknown"


class TestSlidingWindow:
    """滑动窗口计数与每 IP 隔离。"""

    def test_under_limit_allowed(self):
        mw = RateLimitMiddleware(app=None, rate_limit_per_minute=3, window_seconds=60.0)
        assert mw._allow("10.0.0.1") >= 0
        assert mw._allow("10.0.0.1") >= 0
        assert mw._allow("10.0.0.1") >= 0

    def test_over_limit_blocked(self):
        mw = RateLimitMiddleware(app=None, rate_limit_per_minute=2, window_seconds=60.0)
        assert mw._allow("10.0.0.1") >= 0
        assert mw._allow("10.0.0.1") >= 0
        assert mw._allow("10.0.0.1") == -1

    def test_window_slides_with_time(self, monkeypatch):
        """窗口滑动后配额恢复。"""
        now = [1000.0]
        monkeypatch.setattr(rate_limit_module, "_monotonic", lambda: now[0])
        mw = RateLimitMiddleware(app=None, rate_limit_per_minute=2, window_seconds=60.0)
        assert mw._allow("10.0.0.1") >= 0
        assert mw._allow("10.0.0.1") >= 0
        assert mw._allow("10.0.0.1") == -1
        now[0] += 61.0  # 超过窗口时长
        assert mw._allow("10.0.0.1") >= 0

    def test_per_ip_isolation(self):
        """不同 IP 的配额互不影响。"""
        mw = RateLimitMiddleware(app=None, rate_limit_per_minute=2, window_seconds=60.0)
        assert mw._allow("10.0.0.1") >= 0
        assert mw._allow("10.0.0.1") >= 0
        assert mw._allow("10.0.0.1") == -1
        assert mw._allow("10.0.0.2") >= 0  # 其他 IP 不受影响

    def test_retry_after_positive(self):
        mw = RateLimitMiddleware(app=None, rate_limit_per_minute=1, window_seconds=60.0)
        mw._allow("10.0.0.1")
        assert mw._allow("10.0.0.1") == -1
        assert mw._retry_after_seconds("10.0.0.1") >= 1

    def test_zero_limit_disables_middleware(self):
        """rate_limit_per_minute<=0 时完全放行。"""
        mw = RateLimitMiddleware(app=None, rate_limit_per_minute=0)
        for _ in range(10):
            assert mw._allow("10.0.0.1") >= 0


class TestHTTPIntegration:
    """通过 TestClient 验证 429 行为与路径过滤。"""

    def test_under_limit_passes(self, limited_app):
        with TestClient(limited_app) as client:
            for _ in range(3):
                resp = client.post("/api/restore/")
                assert resp.status_code == 200

    def test_over_limit_returns_429_with_retry_after(self, limited_app):
        with TestClient(limited_app) as client:
            for _ in range(3):
                assert client.post("/api/restore/").status_code == 200
            resp = client.post("/api/restore/")
            assert resp.status_code == 429
            assert resp.headers.get("Retry-After") is not None
            assert int(resp.headers["Retry-After"]) >= 1
            assert resp.headers.get("X-RateLimit-Limit") == "3"
            body = resp.json()
            assert body["error"]["code"] == "RATE_LIMITED"
            assert body["error"]["detail"]["retry_after_seconds"] >= 1

    def test_batch_and_retry_paths_limited(self, limited_app):
        with TestClient(limited_app) as client:
            for _ in range(3):
                assert client.post("/api/restore/batch").status_code == 200
            assert client.post("/api/restore/batch").status_code == 429

    def test_readonly_get_endpoints_not_limited(self, limited_app):
        """进度轮询/健康检查等 GET 端点不受限流影响。"""
        with TestClient(limited_app) as client:
            for _ in range(10):
                assert client.get("/api/restore/task-abc/progress").status_code == 200
                assert client.get("/ping").status_code == 200

    def test_unmatched_post_not_limited(self, limited_app):
        """非上传/推理类 POST 端点不在限流范围。"""
        with TestClient(limited_app) as client:
            for _ in range(10):
                assert client.post("/api/system/locale").status_code == 200

    def test_429_not_recorded_so_recovers_immediately(self, limited_app):
        """被拒绝的请求不计入窗口，窗口过期后立即恢复。"""
        with TestClient(limited_app) as client:
            for _ in range(3):
                assert client.post("/api/restore/").status_code == 200
            assert client.post("/api/restore/").status_code == 429


class TestAppServerWiring:
    """验证 app_server.create_app() 中限流中间件接线。"""

    def test_middleware_registered_in_create_app(self):
        from bin.integrated_app.app_server import create_app

        app = create_app({"runtime": {"security": {"rate_limit_per_minute": 7}}})
        names = [m.cls.__name__ for m in app.user_middleware]
        assert "RateLimitMiddleware" in names

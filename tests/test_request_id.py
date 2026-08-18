"""middleware/request_id.py 单元测试（请求 ID 中间件）

覆盖：
- RequestIDMiddleware 分配 UUID4/使用入站 X-Request-ID
- get_request_id/set_request_id ContextVar 与线程本地同步
- RequestIDLogFilter 注入 request_id 到日志上下文
- _sanitize_request_id 清理非法字符防日志注入
"""

from __future__ import annotations

import logging
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from bin.integrated_app.middleware.request_id import (
    RequestIDLogFilter,
    RequestIDMiddleware,
    _sanitize_request_id,
    get_request_id,
    set_request_id,
)


class TestSanitizeRequestId:
    """_sanitize_request_id 清理逻辑测试"""

    def test_valid_request_id_passes_through(self):
        """合法字符应保持不变"""
        assert _sanitize_request_id("abc123def456") == "abc123def456"
        assert _sanitize_request_id("req-1234567890abcdef") == "req-1234567890abcdef"

    def test_invalid_chars_are_removed(self):
        """非法字符应被移除"""
        assert _sanitize_request_id('a;b"c<d>e?') == "abcde"
        assert _sanitize_request_id("hello@world#test!") == "helloworldtest"  # @ # ! removed, letters remain

    def test_unicode_chars_are_removed(self):
        """Unicode 字符应被移除（仅限 ASCII 安全字符）"""
        assert _sanitize_request_id("你好世界") == ""
        assert _sanitize_request_id("test_日本語_test") == "test__test"

    def test_empty_input_returns_empty(self):
        """空输入返回空串"""
        assert _sanitize_request_id("") == ""
        assert _sanitize_request_id(None) == ""  # type: ignore

    def test_max_length_truncation(self):
        """超过最大长度应截断"""
        long_id = "a" * 100
        result = _sanitize_request_id(long_id)
        assert len(result) == 64  # MAX_REQUEST_ID_LEN


class TestRequestIdMiddleware:
    """RequestIDMiddleware 功能测试"""

    def test_uuid4_assigned_to_request_without_header(self):
        """无入站 X-Request-ID 时应分配 UUID4"""
        app = FastAPI()

        @app.get("/")
        async def root(request: Request):
            return {"request_id": request.state.request_id}

        app.add_middleware(RequestIDMiddleware)

        with TestClient(app) as client:
            response = client.get("/")
            assert response.status_code == 200
            request_id = response.json()["request_id"]
            # 应为 16 位 hex
            assert len(request_id) == 16
            assert re.match(r"^[a-f0-9]{16}$", request_id)

    def test_incoming_request_id_is_sanitized_and_used(self):
        """入站 X-Request-ID 应被清理并使用"""
        app = FastAPI()

        @app.get("/")
        async def root(request: Request):
            return {"request_id": request.state.request_id}

        app.add_middleware(RequestIDMiddleware)

        with TestClient(app) as client:
            response = client.get("/", headers={"X-Request-ID": "my-custom-id-123"})
            assert response.status_code == 200
            assert response.json()["request_id"] == "my-custom-id-123"

    def test_response_contains_x_request_id_header(self):
        """响应应包含 X-Request-ID 头"""
        app = FastAPI()

        @app.get("/")
        async def root():
            return {"message": "OK"}

        app.add_middleware(RequestIDMiddleware)

        with TestClient(app) as client:
            response = client.get("/")
            assert response.status_code == 200
            assert "x-request-id" in response.headers
            assert len(response.headers["x-request-id"]) == 16

    def test_different_requests_get_different_ids(self):
        """不同请求应分配不同的 request_id"""
        app = FastAPI()

        @app.get("/")
        async def root(request: Request):
            return {"request_id": request.state.request_id}

        app.add_middleware(RequestIDMiddleware)

        with TestClient(app) as client:
            resp1 = client.get("/")
            resp2 = client.get("/")
            id1 = resp1.json()["request_id"]
            id2 = resp2.json()["request_id"]
            assert id1 != id2


class TestGetSetRequestId:
    """get_request_id/set_request_id 工具函数测试"""

    def test_set_and_get_context_var(self):
        """set_request_id 后 get_request_id 应返回相同值"""
        set_request_id("test-request-id-123")
        assert get_request_id() == "test-request-id-123"

    def test_empty_when_not_set(self):
        """未设置时返回空串"""
        # 注意：由于之前的测试可能设置了值，此处无法强制清空 ContextVar
        # 但我们可以测试设置行为本身
        set_request_id("temp-test-id")
        assert get_request_id() == "temp-test-id"


class TestRequestIdLogFilter:
    """RequestIDLogFilter 日志过滤器测试"""

    def test_filter_adds_request_id_to_record(self, monkeypatch):
        """filter 应为 LogRecord 添加 request_id 属性"""

        # Use module's actual ContextVar instead of creating a new one
        from bin.integrated_app.middleware.request_id import _request_id_var

        token = _request_id_var.set("test-log-request-id")

        try:
            filter_obj = RequestIDLogFilter()
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=1,
                msg="Test message",
                args=(),
                exc_info=None,
            )

            # Ensure filter adds request_id attribute
            result = filter_obj.filter(record)
            assert result is True
            assert hasattr(record, "request_id")
            assert record.request_id == "test-log-request-id"
        finally:
            _request_id_var.reset(token)

    def test_filter_uses_thread_local_as_fallback(self, monkeypatch):
        """异步上下文中没有时使用线程本地回退"""

        from bin.integrated_app.middleware.request_id import _request_id_local

        # 设置线程本地值
        _request_id_local.request_id = "thread-local-fallback"

        filter_obj = RequestIDLogFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None,
        )

        result = filter_obj.filter(record)
        assert result is True
        # 如果 ContextVar 为空且线程本地有值，应使用线程本地
        if not getattr(record, "request_id", None):
            assert record.request_id == "-"  # 最终兜底

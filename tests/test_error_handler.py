"""middleware/error_handler 模块单元测试

覆盖异常处理器的 JSON 响应、HTMX 响应、各异常类型的映射。
使用 mock Request 对象模拟请求。
"""

import json
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.integrated_app.exceptions import (
    ConfigError,
    InferenceCancelledError,
    InferenceError,
    InsufficientRAMError,
    InsufficientVRAMError,
    ModelFileNotFoundError,
    ModelLoadError,
    ModelUnloadError,
    RestoreError,
    VAEDecodeError,
    VAEEncodeError,
)
from app.integrated_app.middleware.error_handler import (
    _build_error_body,
    _htmx_error_response,
    _is_htmx_request,
    register_error_handlers,
)


class TestBuildErrorBody:
    """_build_error_body 测试"""

    def test_builds_correct_structure(self):
        """构建正确的错误响应体结构"""
        exc = RestoreError("test error", code="TEST_CODE", detail={"key": "value"})
        body = _build_error_body(exc)
        assert body["error"]["code"] == "TEST_CODE"
        assert body["error"]["message"] == "test error"
        assert body["error"]["detail"] == {"key": "value"}

    def test_default_detail_is_empty_dict(self):
        """detail 默认为空字典"""
        exc = RestoreError("msg")
        body = _build_error_body(exc)
        assert body["error"]["detail"] == {}


class TestIsHtmxRequest:
    """_is_htmx_request 测试"""

    def test_returns_true_for_htmx_header(self):
        """HX-Request: true 返回 True"""
        request = MagicMock()
        request.headers.get.return_value = "true"
        assert _is_htmx_request(request) is True

    def test_returns_false_for_no_header(self):
        """无 HX-Request 头返回 False"""
        request = MagicMock()
        request.headers.get.return_value = None
        assert _is_htmx_request(request) is False

    def test_returns_false_for_other_value(self):
        """HX-Request 非 true 返回 False"""
        request = MagicMock()
        request.headers.get.return_value = "false"
        assert _is_htmx_request(request) is False


class TestHtmxErrorResponse:
    """_htmx_error_response 测试"""

    def test_returns_response_with_hx_trigger(self):
        """返回带 HX-Trigger 头的响应"""
        response = _htmx_error_response("error message", 400)
        assert response.status_code == 400
        trigger = json.loads(response.headers["HX-Trigger"])
        assert "showToast" in trigger
        assert trigger["showToast"]["message"] == "error message"
        assert trigger["showToast"]["type"] == "error"

    def test_custom_status_code(self):
        """支持自定义状态码"""
        response = _htmx_error_response("msg", 500)
        assert response.status_code == 500


class TestErrorHandlersIntegration:
    """通过 FastAPI TestClient 集成测试异常处理器"""

    @pytest.fixture
    def app_with_handlers(self):
        """创建注册了异常处理器的 FastAPI 应用"""
        app = FastAPI()

        @app.get("/raise/restore")
        async def raise_restore():
            raise RestoreError("restore failed", code="TEST_ERROR", detail={"ctx": "info"})

        @app.get("/raise/restore/subclass")
        async def raise_restore_subclass():
            raise ModelLoadError("model load failed", detail={"model": "3b"})

        @app.get("/raise/value_error")
        async def raise_value_error():
            raise ValueError("bad value")

        @app.get("/raise/memory_error")
        async def raise_memory_error():
            raise MemoryError("oom")

        @app.get("/raise/file_not_found")
        async def raise_file_not_found():
            raise FileNotFoundError("missing.pt")

        @app.get("/raise/generic")
        async def raise_generic():
            raise RuntimeError("unexpected")

        @app.get("/raise/inference_cancelled")
        async def raise_cancelled():
            raise InferenceCancelledError("cancelled by user")

        @app.get("/raise/vram_error")
        async def raise_vram():
            raise InsufficientVRAMError("not enough vram")

        register_error_handlers(app)
        return app

    def test_restore_error_returns_json(self, app_with_handlers):
        """RestoreError 返回 JSON 错误响应"""
        client = TestClient(app_with_handlers, raise_server_exceptions=False)
        response = client.get("/raise/restore")
        assert response.status_code == 500
        body = response.json()
        assert body["error"]["code"] == "TEST_ERROR"
        assert body["error"]["message"] == "restore failed"

    def test_restore_error_subclass_returns_correct_status(self, app_with_handlers):
        """ModelLoadError 返回 503"""
        client = TestClient(app_with_handlers, raise_server_exceptions=False)
        response = client.get("/raise/restore/subclass")
        assert response.status_code == 503
        body = response.json()
        assert body["error"]["code"] == "MODEL_LOAD_FAILED"

    def test_value_error_returns_422(self, app_with_handlers):
        """ValueError 返回 422"""
        client = TestClient(app_with_handlers, raise_server_exceptions=False)
        response = client.get("/raise/value_error")
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "VALUE_ERROR"

    def test_memory_error_returns_422(self, app_with_handlers):
        """MemoryError 返回 422"""
        client = TestClient(app_with_handlers, raise_server_exceptions=False)
        response = client.get("/raise/memory_error")
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "INSUFFICIENT_RAM"

    def test_file_not_found_returns_404(self, app_with_handlers):
        """FileNotFoundError 返回 404"""
        client = TestClient(app_with_handlers, raise_server_exceptions=False)
        response = client.get("/raise/file_not_found")
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "FILE_NOT_FOUND"

    def test_generic_error_returns_500(self, app_with_handlers):
        """未捕获异常返回 500 且不泄露内部信息"""
        client = TestClient(app_with_handlers, raise_server_exceptions=False)
        response = client.get("/raise/generic")
        assert response.status_code == 500
        body = response.json()
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert "unexpected" not in body["error"]["message"]

    def test_inference_cancelled_returns_400(self, app_with_handlers):
        """InferenceCancelledError 返回 400"""
        client = TestClient(app_with_handlers, raise_server_exceptions=False)
        response = client.get("/raise/inference_cancelled")
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "INFERENCE_CANCELLED"

    def test_vram_error_returns_422(self, app_with_handlers):
        """InsufficientVRAMError 返回 422"""
        client = TestClient(app_with_handlers, raise_server_exceptions=False)
        response = client.get("/raise/vram_error")
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "INSUFFICIENT_VRAM"

    def test_htmx_request_returns_hx_trigger(self, app_with_handlers):
        """HTMX 请求返回 HX-Trigger 头"""
        client = TestClient(app_with_handlers, raise_server_exceptions=False)
        response = client.get("/raise/restore", headers={"HX-Request": "true"})
        assert response.status_code == 500
        assert "HX-Trigger" in response.headers
        trigger = json.loads(response.headers["HX-Trigger"])
        assert "showToast" in trigger


class TestExceptionHttpStatus:
    """异常类 HTTP 状态码映射测试"""

    def test_restore_error_status(self):
        assert RestoreError().http_status() == 500

    def test_model_load_error_status(self):
        assert ModelLoadError().http_status() == 503

    def test_model_unload_error_status(self):
        assert ModelUnloadError().http_status() == 503

    def test_insufficient_vram_status(self):
        assert InsufficientVRAMError().http_status() == 422

    def test_insufficient_ram_status(self):
        assert InsufficientRAMError().http_status() == 422

    def test_inference_error_status(self):
        assert InferenceError().http_status() == 500

    def test_vae_decode_error_status(self):
        assert VAEDecodeError().http_status() == 500

    def test_vae_encode_error_status(self):
        assert VAEEncodeError().http_status() == 500

    def test_config_error_status(self):
        assert ConfigError().http_status() == 400

    def test_model_file_not_found_status(self):
        assert ModelFileNotFoundError().http_status() == 404

    def test_inference_cancelled_status(self):
        assert InferenceCancelledError().http_status() == 400


class TestExceptionToDict:
    """异常 to_dict 方法测试"""

    def test_to_dict_contains_all_fields(self):
        exc = RestoreError("msg", code="CODE", detail={"k": "v"})
        d = exc.to_dict()
        assert d["code"] == "CODE"
        assert d["message"] == "msg"
        assert d["detail"] == {"k": "v"}

    def test_to_dict_default_detail(self):
        exc = RestoreError("msg")
        d = exc.to_dict()
        assert d["detail"] == {}

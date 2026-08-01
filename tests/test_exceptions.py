"""测试 SeedVR2 自定义异常层次结构"""

import pytest

from bin.integrated_app.exceptions import (
    BlockSwapError,
    ConfigError,
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


class TestRestoreError:
    """基础异常测试"""

    def test_default_message(self):
        exc = RestoreError()
        assert exc.message == "视频修复操作失败"
        assert exc.code == "RESTORE_ERROR"
        assert exc.detail == {}

    def test_custom_message(self):
        exc = RestoreError("自定义错误")
        assert exc.message == "自定义错误"

    def test_custom_code(self):
        exc = RestoreError("test", code="CUSTOM_CODE")
        assert exc.code == "CUSTOM_CODE"

    def test_custom_detail(self):
        exc = RestoreError("test", detail={"key": "value"})
        assert exc.detail == {"key": "value"}

    def test_http_status(self):
        assert RestoreError.http_status() == 500

    def test_to_dict(self):
        exc = RestoreError("测试", detail={"foo": "bar"})
        d = exc.to_dict()
        assert d == {
            "code": "RESTORE_ERROR",
            "message": "测试",
            "detail": {"foo": "bar"},
        }

    def test_is_exception(self):
        with pytest.raises(RestoreError):
            raise RestoreError()


class TestExceptionCodes:
    """验证每个异常类拥有正确的 code 属性"""

    @pytest.mark.parametrize(
        "exc_cls, expected_code",
        [
            (RestoreError, "RESTORE_ERROR"),
            (ModelLoadError, "MODEL_LOAD_FAILED"),
            (ModelUnloadError, "MODEL_UNLOAD_FAILED"),
            (InsufficientVRAMError, "INSUFFICIENT_VRAM"),
            (InsufficientRAMError, "INSUFFICIENT_RAM"),
            (InferenceError, "INFERENCE_FAILED"),
            (BlockSwapError, "BLOCK_SWAP_FAILED"),
            (VAEDecodeError, "VAE_DECODE_FAILED"),
            (VAEEncodeError, "VAE_ENCODE_FAILED"),
            (ConfigError, "CONFIG_ERROR"),
            (ModelFileNotFoundError, "MODEL_FILE_NOT_FOUND"),
        ],
    )
    def test_code_attribute(self, exc_cls, expected_code):
        exc = exc_cls()
        assert exc.code == expected_code


class TestHttpStatusCodes:
    """验证每个异常类返回正确的 HTTP 状态码"""

    @pytest.mark.parametrize(
        "exc_cls, expected_status",
        [
            (RestoreError, 500),
            (ModelLoadError, 503),
            (ModelUnloadError, 503),
            (InsufficientVRAMError, 422),
            (InsufficientRAMError, 422),
            (InferenceError, 500),
            (BlockSwapError, 500),
            (VAEDecodeError, 500),
            (VAEEncodeError, 500),
            (ConfigError, 400),
            (ModelFileNotFoundError, 404),
        ],
    )
    def test_http_status(self, exc_cls, expected_status):
        assert exc_cls.http_status() == expected_status


class TestExceptionInheritance:
    """验证所有异常都是 RestoreError 的子类"""

    @pytest.mark.parametrize(
        "exc_cls",
        [
            ModelLoadError,
            ModelUnloadError,
            InsufficientVRAMError,
            InsufficientRAMError,
            InferenceError,
            BlockSwapError,
            VAEDecodeError,
            VAEEncodeError,
            ConfigError,
            ModelFileNotFoundError,
        ],
    )
    def test_is_subclass_of_restore_error(self, exc_cls):
        assert issubclass(exc_cls, RestoreError)

    @pytest.mark.parametrize(
        "exc_cls",
        [
            ModelLoadError,
            ModelUnloadError,
            InsufficientVRAMError,
            InsufficientRAMError,
            InferenceError,
            BlockSwapError,
            VAEDecodeError,
            VAEEncodeError,
            ConfigError,
            ModelFileNotFoundError,
        ],
    )
    def test_catch_as_restore_error(self, exc_cls):
        """所有子类异常都可以被 RestoreError 捕获"""
        with pytest.raises(RestoreError):
            raise exc_cls()


class TestExceptionHandlerMiddleware:
    """测试 FastAPI 异常处理器的响应格式"""

    def test_restore_error_handler_response(self):
        from bin.integrated_app.middleware.error_handler import _build_error_body

        exc = InsufficientVRAMError("需要 16GB 显存", detail={"required_gb": 16, "available_gb": 8})
        body = _build_error_body(exc)
        assert body == {
            "error": {
                "code": "INSUFFICIENT_VRAM",
                "message": "需要 16GB 显存",
                "detail": {"required_gb": 16, "available_gb": 8},
            }
        }

    def test_model_load_error_response(self):
        from bin.integrated_app.middleware.error_handler import _build_error_body

        exc = ModelLoadError("权重文件损坏", detail={"path": "/models/3b_fp16.pt"})
        body = _build_error_body(exc)
        assert body["error"]["code"] == "MODEL_LOAD_FAILED"
        assert body["error"]["detail"]["path"] == "/models/3b_fp16.pt"

    def test_config_error_response(self):
        from bin.integrated_app.middleware.error_handler import _build_error_body

        exc = ConfigError("无效的精度设置", detail={"field": "precision", "value": "fp32"})
        body = _build_error_body(exc)
        assert body["error"]["code"] == "CONFIG_ERROR"
        assert body["error"]["detail"]["field"] == "precision"

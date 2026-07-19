"""测试 SeedVR2 模型状态注册中心"""

from bin.integrated_app.model_registry import _ModelRegistry


class TestSingleton:
    """单例模式测试"""

    def test_singleton_identity(self):
        a = _ModelRegistry()
        b = _ModelRegistry()
        assert a is b

    def test_singleton_with_direct_construction(self):
        """直接构造两次应返回同一实例"""
        a = _ModelRegistry()
        b = _ModelRegistry()
        assert id(a) == id(b)


class TestSetEngine:
    """set_engine 测试"""

    def test_set_engine_with_mock(self):
        registry = _ModelRegistry()

        class MockEngine:
            def is_loaded(self):
                return True

            def get_model_info(self):
                return {"model_size": "3b", "precision": "fp16"}

        engine = MockEngine()
        registry.set_engine(engine)
        assert registry.model_loaded is True
        assert registry.current_model_size == "3b"
        assert registry.current_precision == "fp16"

    def test_set_engine_none(self):
        registry = _ModelRegistry()
        registry.set_engine(None)
        assert registry.model_loaded is False
        assert registry.current_model_size is None
        assert registry.current_precision is None
        assert registry.model_info == {}


class TestClearEngine:
    """clear_engine 测试"""

    def test_clear_engine_resets_state(self):
        registry = _ModelRegistry()

        class MockEngine:
            def is_loaded(self):
                return True

            def get_model_info(self):
                return {"model_size": "3b", "precision": "fp16"}

        registry.set_engine(MockEngine())
        assert registry.model_loaded is True

        registry.clear_engine()
        assert registry.model_loaded is False
        assert registry.current_model_size is None
        assert registry.current_precision is None
        assert registry.model_info == {}
        assert registry.get_engine() is None


class TestUpdateAndGetStatus:
    """update_status / get_status 测试"""

    def test_update_status(self):
        registry = _ModelRegistry()
        registry.clear_engine()

        registry.update_status(
            loaded=True,
            model_size="7b",
            precision="fp8",
            info={"model_size": "7b", "precision": "fp8"},
        )
        assert registry.model_loaded is True
        assert registry.current_model_size == "7b"
        assert registry.current_precision == "fp8"

    def test_get_status(self):
        registry = _ModelRegistry()
        registry.clear_engine()

        registry.update_status(
            loaded=True,
            model_size="3b",
            precision="fp16",
            info={"model_size": "3b", "precision": "fp16"},
        )
        status = registry.get_status()
        assert status["model_loaded"] is True
        assert status["current_model_size"] == "3b"
        assert status["current_precision"] == "fp16"
        assert status["model_info"]["model_size"] == "3b"

    def test_get_status_after_clear(self):
        registry = _ModelRegistry()
        registry.clear_engine()
        status = registry.get_status()
        assert status["model_loaded"] is False
        assert status["current_model_size"] is None
        assert status["current_precision"] is None
        assert status["model_info"] == {}

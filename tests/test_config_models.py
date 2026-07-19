"""测试 SeedVR2 配置数据模型"""

from bin.integrated_app.config_models import AppConfig, ModelConfig, ServerConfig


class TestAppConfig:
    """AppConfig 测试"""

    def test_default_instantiation(self):
        config = AppConfig()
        assert config.server is not None
        assert config.model is not None
        assert config.restore is not None
        assert config.gpu is not None
        assert config.history is not None
        assert config.i18n is not None
        assert config.logging is not None

    def test_nested_defaults(self):
        config = AppConfig()
        assert config.server.host == "127.0.0.1"
        assert config.model.default_size == "3b"
        assert config.model.auto_load is True


class TestServerConfig:
    """ServerConfig 测试"""

    def test_default_host(self):
        config = ServerConfig()
        assert config.host == "127.0.0.1"

    def test_default_port(self):
        config = ServerConfig()
        assert config.port == 7870

    def test_default_debug(self):
        config = ServerConfig()
        assert config.debug is False

    def test_custom_values(self):
        config = ServerConfig(host="0.0.0.0", port=9000, debug=True)
        assert config.host == "0.0.0.0"
        assert config.port == 9000
        assert config.debug is True


class TestModelConfig:
    """ModelConfig 测试"""

    def test_default_size(self):
        config = ModelConfig()
        assert config.default_size == "3b"

    def test_default_precision(self):
        config = ModelConfig()
        assert config.default_precision == "fp16"

    def test_default_pretrained_dir(self):
        config = ModelConfig()
        assert config.pretrained_dir == "."

    def test_default_auto_load(self):
        config = ModelConfig()
        assert config.auto_load is True

    def test_default_device(self):
        config = ModelConfig()
        assert config.device == "auto"

    def test_default_models_empty(self):
        config = ModelConfig()
        assert config.models == {}

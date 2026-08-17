import pytest
"""测试 SeedVR2 配置数据模型"""

import os

from bin.integrated_app.config_models import AppConfig, ModelConfig, ServerConfig, get_pretrained_root


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
        config = ServerConfig(host="127.0.0.1", port=9000, debug=True)
        assert config.host == "127.0.0.1"
        assert config.port == 9000
        assert config.debug is True

    def test_public_host_rejected_without_auth(self):
        """安全强制：0.0.0.0 未配置 SEEDVR2_AUTH_PASSWORD 时必须被拒绝。"""
        import os
        old = os.environ.pop("SEEDVR2_AUTH_PASSWORD", None)
        try:
            with pytest.raises(ValueError):
                ServerConfig(host="0.0.0.0", port=9000)
        finally:
            if old is not None:
                os.environ["SEEDVR2_AUTH_PASSWORD"] = old


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
        assert config.pretrained_dir == "pretrained_models"

    def test_default_model_source_mode(self):
        config = ModelConfig()
        assert config.model_source_mode == "portable"

    def test_default_shared_models_root(self):
        config = ModelConfig()
        assert config.shared_models_root == ""

    def test_shared_mode_config(self):
        config = ModelConfig(model_source_mode="shared", shared_models_root="/data/shared_models")
        assert config.model_source_mode == "shared"
        assert config.shared_models_root == "/data/shared_models"

    def test_default_auto_load(self):
        config = ModelConfig()
        assert config.auto_load is True

    def test_default_device(self):
        config = ModelConfig()
        assert config.device == "auto"

    def test_default_models_empty(self):
        config = ModelConfig()
        assert config.models == {}


class TestGetPretrainedRoot:
    """get_pretrained_root() shared/portable 双模式解析测试"""

    def test_portable_mode_default(self):
        """portable 模式默认路径解析"""
        cfg = {"model_source_mode": "portable", "pretrained_dir": "pretrained_models"}
        path = get_pretrained_root(cfg, project_root="/project")
        assert "pretrained_models" in path
        assert "/project" in path

    def test_shared_mode_resolution(self):
        """shared 模式使用外部共享目录"""
        cfg = {
            "model_source_mode": "shared",
            "shared_models_root": "/data/shared_models",
            "pretrained_dir": "pretrained_models",
        }
        path = get_pretrained_root(cfg, project_root="/project")
        assert path == os.path.abspath("/data/shared_models")
        assert "pretrained_models" not in path

    def test_shared_mode_empty_root_falls_back_to_portable(self):
        """shared 模式但 shared_models_root 为空时回退到 portable"""
        cfg = {"model_source_mode": "shared", "shared_models_root": "", "pretrained_dir": "pretrained_models"}
        path = get_pretrained_root(cfg, project_root="/project")
        assert "pretrained_models" in path

    def test_portable_mode_custom_dir(self):
        """portable 模式自定义 pretrained_dir"""
        cfg = {"model_source_mode": "portable", "pretrained_dir": "custom_models"}
        path = get_pretrained_root(cfg, project_root="/project")
        assert "custom_models" in path

    def test_defaults_when_fields_missing(self):
        """缺少 model_source_mode 字段时默认 portable"""
        cfg = {}
        path = get_pretrained_root(cfg, project_root="/project")
        assert "pretrained_models" in path

    def test_model_config_instance_input(self):
        """接受 ModelConfig 实例作为输入"""
        mc = ModelConfig(model_source_mode="shared", shared_models_root="/external/models")
        path = get_pretrained_root(mc)
        assert os.path.isabs(path) or "/external/models" in path

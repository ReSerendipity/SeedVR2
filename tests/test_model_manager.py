"""ModelManager 单元测试

覆盖模型加载/卸载/状态查询功能。
使用 MagicMock 模拟引擎，不加载真实模型。
"""

from unittest.mock import patch

import pytest

from bin.integrated_app.model_manager import ModelManager


@pytest.fixture
def config():
    """测试配置"""
    return {
        "model": {
            "default_size": "3b",
            "default_precision": "fp16",
            "auto_load": False,
            "models": {
                "3b": {"config_dir": "configs_3b", "checkpoint_fp16": "dit_3b.safetensors"},
                "7b": {"config_dir": "configs_7b", "checkpoint_fp16": "dit_7b.safetensors"},
            },
        },
        "inference": {"seed": -1},
    }


class TestModelManagerInit:
    """ModelManager 初始化测试"""

    def test_init(self, config):
        manager = ModelManager(config)
        assert manager.config == config
        assert manager.model_config == config["model"]

    @patch("bin.integrated_app.model_manager.model_registry")
    def test_is_loaded_false_initially(self, _mock_registry, config):
        _mock_registry.model_loaded = False
        manager = ModelManager(config)
        assert manager.is_loaded is False


class TestModelManagerInfo:
    """ModelManager 状态信息测试"""

    @patch("bin.integrated_app.model_manager.model_registry")
    def test_get_model_info_existing(self, mock_registry, config):
        mock_registry.model_loaded = False
        manager = ModelManager(config)
        info = manager.get_model_info(size="3b")
        assert info is not None
        assert "config_dir" in info
        assert "checkpoint_fp16" in info

    @patch("bin.integrated_app.model_manager.model_registry")
    def test_get_model_info_nonexistent(self, mock_registry, config):
        mock_registry.model_loaded = False
        manager = ModelManager(config)
        info = manager.get_model_info(size="99b")
        assert info is None

    @patch("bin.integrated_app.model_manager.model_registry")
    def test_is_loaded_true(self, mock_registry, config):
        mock_registry.model_loaded = True
        manager = ModelManager(config)
        assert manager.is_loaded is True

    @patch("bin.integrated_app.model_manager.model_registry")
    def test_get_pretrained_dir(self, mock_registry, config):
        manager = ModelManager(config)
        path = manager.get_pretrained_dir()
        assert "pretrained_models" in path or len(path) > 0

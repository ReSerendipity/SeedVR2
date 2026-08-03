"""ModelManager 单元测试

覆盖模型加载/卸载/切换/状态查询/文件检查/精度推荐功能。
使用 MagicMock 模拟引擎和 GPU 环境，不加载真实模型。
"""

from unittest.mock import AsyncMock, MagicMock, patch

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
            "pretrained_dir": "pretrained_models",
            "models": {
                "3b": {
                    "config_dir": "configs_3b",
                    "checkpoint_fp16": "dit_3b.safetensors",
                    "checkpoint_fp8": "dit_3b_fp8.safetensors",
                    "min_vram_fp16_gb": 16,
                    "min_vram_fp8_gb": 8,
                },
                "7b": {
                    "config_dir": "configs_7b",
                    "checkpoint_fp16": "dit_7b.safetensors",
                    "checkpoint_fp8": "dit_7b_fp8.safetensors",
                    "min_vram_fp16_gb": 24,
                    "min_vram_fp8_gb": 12,
                },
            },
        },
        "inference": {"seed": -1},
    }


@pytest.fixture
def mock_registry():
    """模拟 model_registry 单例"""
    with patch("bin.integrated_app.model_manager.model_registry") as mock:
        mock.model_loaded = False
        mock.current_model_size = None
        mock.current_precision = None
        mock.get_engine.return_value = None
        mock.get_status.return_value = {
            "model_loaded": False,
            "current_model_size": None,
            "current_precision": None,
            "model_info": {},
        }
        yield mock


# ---------------------------------------------------------------------------
# 初始化与基础属性
# ---------------------------------------------------------------------------


class TestModelManagerInit:
    """ModelManager 初始化测试"""

    def test_init(self, config):
        manager = ModelManager(config)
        assert manager.config == config
        assert manager.model_config == config["model"]

    def test_init_empty_config(self):
        """空配置不报错"""
        manager = ModelManager({})
        assert manager.model_config == {}

    def test_is_loaded_false_initially(self, mock_registry, config):
        mock_registry.model_loaded = False
        manager = ModelManager(config)
        assert manager.is_loaded is False

    def test_is_loaded_true(self, mock_registry, config):
        mock_registry.model_loaded = True
        manager = ModelManager(config)
        assert manager.is_loaded is True

    def test_engine_returns_registry_engine(self, mock_registry, config):
        fake_engine = MagicMock()
        mock_registry.get_engine.return_value = fake_engine
        manager = ModelManager(config)
        assert manager.engine is fake_engine

    def test_engine_none_when_not_loaded(self, mock_registry, config):
        mock_registry.get_engine.return_value = None
        manager = ModelManager(config)
        assert manager.engine is None


# ---------------------------------------------------------------------------
# 模型信息查询
# ---------------------------------------------------------------------------


class TestModelManagerInfo:
    """ModelManager 模型信息查询测试"""

    def test_get_model_info_existing(self, mock_registry, config):
        manager = ModelManager(config)
        info = manager.get_model_info(size="3b")
        assert info is not None
        assert "config_dir" in info
        assert "checkpoint_fp16" in info

    def test_get_model_info_nonexistent(self, mock_registry, config):
        manager = ModelManager(config)
        info = manager.get_model_info(size="99b")
        assert info is None

    def test_get_pretrained_dir(self, mock_registry, config):
        manager = ModelManager(config)
        path = manager.get_pretrained_dir()
        assert "pretrained_models" in path

    def test_get_pretrained_dir_custom(self, mock_registry):
        """自定义 pretrained_dir"""
        cfg: dict = {"model": {"pretrained_dir": "custom_models"}}
        manager = ModelManager(cfg)
        path = manager.get_pretrained_dir()
        assert "custom_models" in path

    def test_get_pretrained_dir_default(self, mock_registry):
        """未配置 pretrained_dir 时使用默认值"""
        cfg: dict = {"model": {}}
        manager = ModelManager(cfg)
        path = manager.get_pretrained_dir()
        assert "pretrained_models" in path


# ---------------------------------------------------------------------------
# check_model_exists
# ---------------------------------------------------------------------------


class TestCheckModelExists:
    """check_model_exists 测试"""

    @patch("os.path.exists", return_value=True)
    def test_file_exists(self, _mock_exists, mock_registry, config):
        manager = ModelManager(config)
        assert manager.check_model_exists("3b", "fp16") is True

    @patch("os.path.exists", return_value=False)
    def test_file_not_exists(self, _mock_exists, mock_registry, config):
        manager = ModelManager(config)
        assert manager.check_model_exists("3b", "fp16") is False

    @patch("os.path.exists", return_value=True)
    def test_unknown_model_size(self, _mock_exists, mock_registry, config):
        manager = ModelManager(config)
        assert manager.check_model_exists("99b", "fp16") is False

    @patch("os.path.exists", return_value=True)
    def test_none_precision_uses_default(self, _mock_exists, mock_registry, config):
        """precision=None 时使用配置中的 default_precision"""
        manager = ModelManager(config)
        assert manager.check_model_exists("3b") is True

    @patch("os.path.exists", return_value=True)
    def test_fp8_precision(self, _mock_exists, mock_registry, config):
        manager = ModelManager(config)
        assert manager.check_model_exists("3b", "fp8") is True

    @patch("os.path.exists", return_value=True)
    def test_fallback_to_fp16_key(self, _mock_exists, mock_registry):
        """缺少指定精度 key 时回退到 checkpoint_fp16"""
        cfg = {
            "model": {
                "models": {
                    "3b": {"checkpoint_fp16": "model.safetensors"},
                },
                "default_precision": "fp16",
            }
        }
        manager = ModelManager(cfg)
        assert manager.check_model_exists("3b", "fp8") is True


# ---------------------------------------------------------------------------
# get_recommended_precision
# ---------------------------------------------------------------------------


class TestGetRecommendedPrecision:
    """get_recommended_precision 测试"""

    @patch("bin.integrated_app.model_manager.torch")
    def test_fp16_when_enough_vram(self, mock_torch, mock_registry, config):
        """显存充足时推荐 fp16"""
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.get_device_properties.return_value.total_memory = 24 * (1024**3)
        manager = ModelManager(config)
        assert manager.get_recommended_precision("3b") == "fp16"

    @patch("bin.integrated_app.model_manager.torch")
    def test_fp8_when_limited_vram(self, mock_torch, mock_registry, config):
        """显存有限时推荐 fp8"""
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.get_device_properties.return_value.total_memory = 10 * (1024**3)
        manager = ModelManager(config)
        assert manager.get_recommended_precision("3b") == "fp8"

    @patch("bin.integrated_app.model_manager.torch")
    def test_fp8_when_insufficient_vram(self, mock_torch, mock_registry, config):
        """显存严重不足时仍返回 fp8"""
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.get_device_properties.return_value.total_memory = 4 * (1024**3)
        manager = ModelManager(config)
        assert manager.get_recommended_precision("3b") == "fp8"

    @patch("bin.integrated_app.model_manager.torch")
    def test_fp8_when_no_cuda(self, mock_torch, mock_registry, config):
        """无 CUDA 时 total_vram_gb=0，低于 min_fp8_gb，返回 fp8"""
        mock_torch.cuda.is_available.return_value = False
        manager = ModelManager(config)
        assert manager.get_recommended_precision("3b") == "fp8"

    @patch("bin.integrated_app.model_manager.torch")
    def test_fp8_when_torch_exception(self, mock_torch, mock_registry, config):
        """torch 异常时 total_vram_gb=0，低于 min_fp8_gb，返回 fp8"""
        mock_torch.cuda.is_available.side_effect = RuntimeError("driver error")
        manager = ModelManager(config)
        assert manager.get_recommended_precision("3b") == "fp8"

    def test_unknown_model_returns_fp16(self, mock_registry, config):
        manager = ModelManager(config)
        assert manager.get_recommended_precision("99b") == "fp16"

    @patch("bin.integrated_app.model_manager.torch")
    def test_7b_requires_more_vram(self, mock_torch, mock_registry, config):
        """7B 模型需要更多显存"""
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.get_device_properties.return_value.total_memory = 16 * (1024**3)
        manager = ModelManager(config)
        # 16GB >= min_fp16_gb(16) for 3b, but < min_fp16_gb(24) for 7b
        assert manager.get_recommended_precision("3b") == "fp16"
        assert manager.get_recommended_precision("7b") == "fp8"


# ---------------------------------------------------------------------------
# load_model
# ---------------------------------------------------------------------------


class TestLoadModel:
    """load_model 测试"""

    @pytest.mark.asyncio
    async def test_already_loaded_skips(self, mock_registry, config):
        """相同模型已加载时跳过"""
        mock_registry.model_loaded = True
        mock_registry.current_model_size = "3b"
        mock_registry.current_precision = "fp16"
        manager = ModelManager(config)
        result = await manager.load_model(model_size="3b", precision="fp16")
        assert result["status"] == "ok"
        assert "已加载" in result["message"]

    @pytest.mark.asyncio
    async def test_no_gpu_raises_runtime_error(self, mock_registry, config):
        """无 GPU 时抛出 RuntimeError"""
        manager = ModelManager(config)
        with patch("bin.integrated_app.gpu_backend.gpu_manager") as mock_gpu:
            mock_gpu.is_gpu_available = False
            with pytest.raises(RuntimeError, match="仅支持 NVIDIA GPU"):
                await manager.load_model(model_size="3b", precision="fp16")

    @pytest.mark.asyncio
    async def test_unknown_model_raises_value_error(self, mock_registry, config):
        """未知模型大小抛出 ValueError"""
        manager = ModelManager(config)
        with patch("bin.integrated_app.gpu_backend.gpu_manager") as mock_gpu:
            mock_gpu.is_gpu_available = True
            with pytest.raises(ValueError, match="未知的模型大小"):
                await manager.load_model(model_size="99b", precision="fp16")

    @pytest.mark.asyncio
    async def test_file_not_found_raises_error(self, mock_registry, config):
        """模型文件不存在抛出 FileNotFoundError"""
        manager = ModelManager(config)
        with (
            patch("bin.integrated_app.gpu_backend.gpu_manager") as mock_gpu,
            patch.object(manager, "check_model_exists", return_value=False),
        ):
            mock_gpu.is_gpu_available = True
            with pytest.raises(FileNotFoundError):
                await manager.load_model(model_size="3b", precision="fp16")

    @pytest.mark.asyncio
    async def test_file_not_found_fallback_precision(self, mock_registry, config):
        """请求精度不存在时回退到另一种精度"""
        manager = ModelManager(config)

        # 模拟 fp16 不存在但 fp8 存在
        def mock_check_exists(size, precision=None):
            return precision != "fp16"

        mock_engine = AsyncMock()
        with (
            patch("bin.integrated_app.gpu_backend.gpu_manager") as mock_gpu,
            patch.object(manager, "check_model_exists", side_effect=mock_check_exists),
            patch("bin.integrated_app.model_manager.check_vram_available", return_value=(True, 16000)),
            patch("bin.integrated_app.model_manager.estimate_model_vram", return_value=8000),
            patch("bin.integrated_app.model_manager.SeedVR2Engine", return_value=mock_engine),
        ):
            mock_gpu.is_gpu_available = True
            result = await manager.load_model(model_size="3b", precision="fp16")
            assert result["status"] == "ok"
            assert result["precision"] == "fp8"

    @pytest.mark.asyncio
    async def test_insufficient_vram_raises_memory_error(self, mock_registry, config):
        """显存不足时抛出 MemoryError"""
        manager = ModelManager(config)
        with (
            patch("bin.integrated_app.gpu_backend.gpu_manager") as mock_gpu,
            patch.object(manager, "check_model_exists", return_value=True),
            patch("bin.integrated_app.model_manager.check_vram_available", return_value=(False, 2000)),
            patch("bin.integrated_app.model_manager.estimate_model_vram", return_value=16000),
        ):
            mock_gpu.is_gpu_available = True
            with pytest.raises(MemoryError, match="显存不足"):
                await manager.load_model(model_size="3b", precision="fp16", device="cuda")

    @pytest.mark.asyncio
    async def test_vram_auto_fallback_to_fp8(self, mock_registry, config):
        """auto 设备 + fp16 显存不足时自动切换到 fp8"""
        manager = ModelManager(config)

        # fp16 不足，fp8 足够
        vram_checks = {(16000,): (False, 4000), (8000,): (True, 12000)}

        def mock_check_vram(required):
            return vram_checks.get((required,), (False, 0))

        def mock_estimate(model_size, precision=None):
            if precision == "fp8":
                return 8000
            return 16000

        mock_engine = AsyncMock()
        with (
            patch("bin.integrated_app.gpu_backend.gpu_manager") as mock_gpu,
            patch.object(manager, "check_model_exists", return_value=True),
            patch("bin.integrated_app.model_manager.check_vram_available", side_effect=mock_check_vram),
            patch("bin.integrated_app.model_manager.estimate_model_vram", side_effect=mock_estimate),
            patch("bin.integrated_app.model_manager.SeedVR2Engine", return_value=mock_engine),
        ):
            mock_gpu.is_gpu_available = True
            result = await manager.load_model(model_size="3b", precision="fp16", device="auto")
            assert result["status"] == "ok"
            assert result["precision"] == "fp8"

    @pytest.mark.asyncio
    async def test_successful_load(self, mock_registry, config):
        """成功加载模型"""
        manager = ModelManager(config)
        mock_engine = AsyncMock()
        with (
            patch("bin.integrated_app.gpu_backend.gpu_manager") as mock_gpu,
            patch.object(manager, "check_model_exists", return_value=True),
            patch("bin.integrated_app.model_manager.check_vram_available", return_value=(True, 24000)),
            patch("bin.integrated_app.model_manager.estimate_model_vram", return_value=8000),
            patch("bin.integrated_app.model_manager.SeedVR2Engine", return_value=mock_engine),
        ):
            mock_gpu.is_gpu_available = True
            result = await manager.load_model(model_size="3b", precision="fp16")
            assert result["status"] == "ok"
            assert result["model_size"] == "3b"
            assert result["precision"] == "fp16"
            mock_registry.set_engine.assert_called_once_with(mock_engine)

    @pytest.mark.asyncio
    async def test_default_parameters_from_config(self, mock_registry, config):
        """未指定参数时从配置读取默认值"""
        manager = ModelManager(config)
        mock_engine = AsyncMock()
        with (
            patch("bin.integrated_app.gpu_backend.gpu_manager") as mock_gpu,
            patch.object(manager, "check_model_exists", return_value=True),
            patch("bin.integrated_app.model_manager.check_vram_available", return_value=(True, 24000)),
            patch("bin.integrated_app.model_manager.estimate_model_vram", return_value=8000),
            patch("bin.integrated_app.model_manager.SeedVR2Engine", return_value=mock_engine),
            patch.object(manager, "get_recommended_precision", return_value="fp16"),
        ):
            mock_gpu.is_gpu_available = True
            result = await manager.load_model()
            assert result["model_size"] == "3b"
            assert result["precision"] == "fp16"


# ---------------------------------------------------------------------------
# unload_model
# ---------------------------------------------------------------------------


class TestUnloadModel:
    """unload_model 测试"""

    @pytest.mark.asyncio
    async def test_unload_when_not_loaded(self, mock_registry, config):
        """未加载模型时返回成功"""
        mock_registry.model_loaded = False
        manager = ModelManager(config)
        result = await manager.unload_model()
        assert result["status"] == "ok"
        assert "没有已加载" in result["message"]

    @pytest.mark.asyncio
    async def test_unload_with_engine(self, mock_registry, config):
        """卸载已加载的模型"""
        mock_registry.model_loaded = True
        mock_engine = AsyncMock()
        mock_registry.get_engine.return_value = mock_engine
        manager = ModelManager(config)

        with patch("bin.integrated_app.model_manager.clear_gpu_cache"):
            result = await manager.unload_model()
            assert result["status"] == "ok"
            assert "已卸载" in result["message"]
            mock_engine.unload_model.assert_awaited_once()
            mock_registry.clear_engine.assert_called_once()

    @pytest.mark.asyncio
    async def test_unload_engine_none(self, mock_registry, config):
        """model_loaded=True 但引擎为 None"""
        mock_registry.model_loaded = True
        mock_registry.get_engine.return_value = None
        manager = ModelManager(config)

        with patch("bin.integrated_app.model_manager.clear_gpu_cache"):
            result = await manager.unload_model()
            assert result["status"] == "ok"
            mock_registry.clear_engine.assert_called_once()


# ---------------------------------------------------------------------------
# switch_model
# ---------------------------------------------------------------------------


class TestSwitchModel:
    """switch_model 测试"""

    @pytest.mark.asyncio
    async def test_switch_to_already_loaded(self, mock_registry, config):
        """切换到已加载的相同模型"""
        mock_registry.model_loaded = True
        mock_registry.current_model_size = "3b"
        mock_registry.current_precision = "fp16"
        manager = ModelManager(config)
        result = await manager.switch_model("3b")
        assert result["status"] == "ok"
        assert "已加载" in result["message"]

    @pytest.mark.asyncio
    async def test_switch_success(self, mock_registry, config):
        """成功切换模型"""
        mock_registry.model_loaded = True
        mock_registry.current_model_size = "3b"
        mock_registry.current_precision = "fp16"
        manager = ModelManager(config)

        with (
            patch.object(manager, "unload_model", new_callable=AsyncMock) as mock_unload,
            patch.object(manager, "load_model", new_callable=AsyncMock) as mock_load,
        ):
            mock_load.return_value = {"status": "ok", "model_size": "7b"}
            result = await manager.switch_model("7b")
            assert result["status"] == "ok"
            assert result["model_size"] == "7b"
            mock_unload.assert_awaited_once()
            mock_load.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_switch_no_previous_model(self, mock_registry, config):
        """无已加载模型时直接加载新模型"""
        mock_registry.model_loaded = False
        mock_registry.current_model_size = None
        manager = ModelManager(config)

        with patch.object(manager, "load_model", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = {"status": "ok", "model_size": "3b"}
            result = await manager.switch_model("3b")
            assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_switch_failure_rollback_success(self, mock_registry, config):
        """切换失败时成功回滚到之前的模型"""
        mock_registry.model_loaded = True
        mock_registry.current_model_size = "3b"
        mock_registry.current_precision = "fp16"
        manager = ModelManager(config)

        call_count = 0

        async def mock_load(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: switching to 7b fails
                raise RuntimeError("load failed")
            else:
                # Second call: rollback to 3b succeeds
                return {"status": "ok", "model_size": "3b"}

        with (
            patch.object(manager, "unload_model", new_callable=AsyncMock),
            patch.object(manager, "load_model", new_callable=AsyncMock, side_effect=mock_load),
            pytest.raises(RuntimeError, match="切换模型失败"),
        ):
            await manager.switch_model("7b")

    @pytest.mark.asyncio
    async def test_switch_failure_rollback_failure(self, mock_registry, config):
        """切换失败且回滚也失败"""
        mock_registry.model_loaded = True
        mock_registry.current_model_size = "3b"
        mock_registry.current_precision = "fp16"
        manager = ModelManager(config)

        call_count = 0

        async def mock_load(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("always fails")

        with (
            patch.object(manager, "unload_model", new_callable=AsyncMock),
            patch.object(manager, "load_model", new_callable=AsyncMock, side_effect=mock_load),
            pytest.raises(RuntimeError, match="切换模型失败"),
        ):
            await manager.switch_model("7b")
        # 回滚失败后应清除引擎
        mock_registry.clear_engine.assert_called()

    @pytest.mark.asyncio
    async def test_switch_failure_no_previous(self, mock_registry, config):
        """切换失败且之前无模型时不回滚"""
        mock_registry.model_loaded = False
        mock_registry.current_model_size = None
        manager = ModelManager(config)

        async def mock_load(**kwargs):
            raise RuntimeError("load failed")

        with (
            patch.object(manager, "load_model", new_callable=AsyncMock, side_effect=mock_load),
            pytest.raises(RuntimeError, match="切换模型失败"),
        ):
            await manager.switch_model("7b")


# ---------------------------------------------------------------------------
# get_current_model_info / get_status
# ---------------------------------------------------------------------------


class TestModelStatus:
    """get_current_model_info 和 get_status 测试"""

    def test_get_current_model_info(self, mock_registry, config):
        mock_registry.get_status.return_value = {
            "model_loaded": True,
            "current_model_size": "3b",
            "current_precision": "fp16",
            "model_info": {"name": "SeedVR2-3B"},
        }
        manager = ModelManager(config)
        info = manager.get_current_model_info()
        assert info["model_loaded"] is True
        assert info["current_model_size"] == "3b"
        assert info["current_precision"] == "fp16"

    def test_get_status_includes_available_models(self, mock_registry, config):
        mock_registry.get_status.return_value = {
            "model_loaded": False,
            "current_model_size": None,
            "current_precision": None,
            "model_info": {},
        }
        manager = ModelManager(config)
        status = manager.get_status()
        assert "available_models" in status
        assert "3b" in status["available_models"]
        assert "7b" in status["available_models"]

    def test_get_status_empty_models(self, mock_registry):
        """配置中没有 models 时返回空列表"""
        mock_registry.get_status.return_value = {
            "model_loaded": False,
            "current_model_size": None,
            "current_precision": None,
            "model_info": {},
        }
        cfg: dict = {"model": {}}
        manager = ModelManager(cfg)
        status = manager.get_status()
        assert status["available_models"] == []

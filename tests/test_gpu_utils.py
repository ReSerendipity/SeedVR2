"""gpu_utils 模块单元测试

覆盖 GPU 显存查询、模型显存估算、缓存清理、OOM 保护装饰器、系统信息聚合。
使用 mock 模拟 torch.cuda 和 psutil，不依赖真实 GPU 硬件。
"""

from unittest.mock import patch

import pytest

from bin.integrated_app import gpu_utils


class TestGetGpuMemoryInfo:
    """get_gpu_memory_info 测试"""

    def test_returns_dict_with_keys(self):
        """返回包含所有必需键的字典"""
        with patch.object(gpu_utils, "_HAS_TORCH_CUDA", False):
            info = gpu_utils.get_gpu_memory_info()
        assert "total_mb" in info
        assert "allocated_mb" in info
        assert "reserved_mb" in info
        assert "available_mb" in info
        assert "utilization_pct" in info

    def test_returns_zeros_without_cuda(self):
        """无 CUDA 时返回全 0"""
        with patch.object(gpu_utils, "_HAS_TORCH_CUDA", False):
            info = gpu_utils.get_gpu_memory_info()
        assert info["total_mb"] == 0
        assert info["available_mb"] == 0
        assert info["utilization_pct"] == 0


class TestCheckVramAvailable:
    """check_vram_available 测试"""

    def test_sufficient_vram(self):
        """显存足够时返回 True"""
        mock_info = {"available_mb": 16000, "total_mb": 24000, "utilization_pct": 33.3}
        with patch.object(gpu_utils, "get_gpu_memory_info", return_value=mock_info):
            ok, available = gpu_utils.check_vram_available(8000)
        assert ok is True
        assert available == 16000

    def test_insufficient_vram(self):
        """显存不足时返回 False"""
        mock_info = {"available_mb": 4000, "total_mb": 8000, "utilization_pct": 50.0}
        with patch.object(gpu_utils, "get_gpu_memory_info", return_value=mock_info):
            ok, available = gpu_utils.check_vram_available(8000)
        assert ok is False
        assert available == 4000


class TestEstimateModelVram:
    """estimate_model_vram 测试"""

    def test_3b_fp16_no_resolution(self):
        """3B FP16 无分辨率时返回基础显存"""
        vram = gpu_utils.estimate_model_vram("3b", precision="fp16")
        assert vram == 8000

    def test_3b_fp8_no_resolution(self):
        """3B FP8 无分辨率时返回基础显存"""
        vram = gpu_utils.estimate_model_vram("3b", precision="fp8")
        assert vram == 4000

    def test_7b_fp16_no_resolution(self):
        """7B FP16 无分辨率时返回基础显存"""
        vram = gpu_utils.estimate_model_vram("7b", precision="fp16")
        assert vram == 16000

    def test_7b_fp8_no_resolution(self):
        """7B FP8 无分辨率时返回基础显存"""
        vram = gpu_utils.estimate_model_vram("7b", precision="fp8")
        assert vram == 8000

    def test_unknown_model_uses_default(self):
        """未知模型使用默认估值"""
        vram = gpu_utils.estimate_model_vram("unknown", precision="fp16")
        assert vram == 8000

    def test_with_resolution_1080p(self):
        """1080p 分辨率时返回基础+推理显存"""
        vram = gpu_utils.estimate_model_vram("3b", resolution=(1080, 1920), precision="fp16")
        assert vram == 8000 + 4000

    def test_with_resolution_4k(self):
        """4K 分辨率时显存按比例增长"""
        vram = gpu_utils.estimate_model_vram("3b", resolution=(2160, 3840), precision="fp16")
        # 4K = 4x 1080p pixels
        assert vram == 8000 + int(4000 * 4.0)

    def test_with_resolution_smaller_than_1080p(self):
        """小于 1080p 时不缩小推理显存"""
        vram = gpu_utils.estimate_model_vram("3b", resolution=(720, 1280), precision="fp16")
        # pixel_factor < 1.0, so max(1.0, factor) = 1.0
        assert vram == 8000 + 4000


class TestClearGpuCache:
    """clear_gpu_cache 测试"""

    def test_no_error_without_cuda(self):
        """无 CUDA 时不报错"""
        with patch.object(gpu_utils, "_HAS_TORCH_CUDA", False):
            gpu_utils.clear_gpu_cache()  # should not raise


class TestForceGarbageCollect:
    """force_garbage_collect 测试"""

    def test_runs_without_error(self):
        """不报错"""
        with patch.object(gpu_utils, "_HAS_TORCH_CUDA", False):
            gpu_utils.force_garbage_collect()  # should not raise


class TestOomProtect:
    """oom_protect 装饰器测试"""

    @pytest.mark.asyncio
    async def test_oom_raises_memory_error(self):
        """CUDA OOM 异常转换为 MemoryError"""

        @gpu_utils.oom_protect
        async def failing_func():
            raise RuntimeError("CUDA out of memory")

        with patch.object(gpu_utils, "force_garbage_collect"), pytest.raises(MemoryError, match="GPU 显存不足"):
            await failing_func()

    @pytest.mark.asyncio
    async def test_non_oom_runtime_error_passes_through(self):
        """非 OOM RuntimeError 原样抛出"""

        @gpu_utils.oom_protect
        async def failing_func():
            raise RuntimeError("some other error")

        with pytest.raises(RuntimeError, match="some other error"):
            await failing_func()

    @pytest.mark.asyncio
    async def test_success_passes_through(self):
        """正常执行返回结果"""

        @gpu_utils.oom_protect
        async def success_func():
            return "result"

        result = await success_func()
        assert result == "result"

    @pytest.mark.asyncio
    async def test_generic_exception_passes_through(self):
        """非 RuntimeError 异常原样抛出"""

        @gpu_utils.oom_protect
        async def failing_func():
            raise ValueError("bad value")

        with pytest.raises(ValueError, match="bad value"):
            await failing_func()


class TestGetSystemMemoryInfo:
    """get_system_memory_info 测试"""

    def test_returns_dict_with_keys(self):
        """返回包含所有必需键的字典"""
        info = gpu_utils.get_system_memory_info()
        assert "total_mb" in info
        assert "available_mb" in info
        assert "used_mb" in info
        assert "utilization_pct" in info


class TestGetFullSystemInfo:
    """get_full_system_info 测试"""

    def test_returns_dict_with_expected_keys(self):
        """返回包含系统、GPU、内存信息的字典"""
        info = gpu_utils.get_full_system_info()
        assert "os" in info
        assert "os_version" in info
        assert "processor" in info
        assert "python_version" in info
        assert "gpu" in info
        assert "memory" in info

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


# ===========================================================================
# VRAM 预检 + 精度/分块推荐 测试（P2-1）
# ===========================================================================


class TestNormalizeModelName:
    """_normalize_model_name 测试"""

    def test_3b(self):
        assert gpu_utils._normalize_model_name("3b") == "3b"

    def test_3b_uppercase(self):
        assert gpu_utils._normalize_model_name("3B") == "3b"

    def test_7b(self):
        assert gpu_utils._normalize_model_name("7b") == "7b"

    def test_7b_uppercase(self):
        assert gpu_utils._normalize_model_name("7B") == "7b"

    def test_7b_sharp_with_hyphen(self):
        assert gpu_utils._normalize_model_name("7b-sharp") == "7b_sharp"

    def test_7b_sharp_with_underscore(self):
        assert gpu_utils._normalize_model_name("7b_sharp") == "7b_sharp"

    def test_7b_sharp_mixed_case(self):
        assert gpu_utils._normalize_model_name("7B-Sharp") == "7b_sharp"

    def test_7b_sharp_no_separator(self):
        assert gpu_utils._normalize_model_name("7bsharp") == "7b_sharp"

    def test_unknown_model(self):
        assert gpu_utils._normalize_model_name("unknown") == "unknown"


class TestEstimateVramRequirements:
    """estimate_vram_requirements 测试"""

    def test_3b_fp8_1080p_image(self):
        """3B FP8 + 1080p 图像，返回值应在 8-10GB 范围内（验收标准）"""
        vram = gpu_utils.estimate_vram_requirements("3b", "fp8", 1920, 1080, num_frames=1)
        assert 8.0 <= vram <= 10.0

    def test_3b_fp16_1080p_image(self):
        """3B FP16 + 1080p 图像，返回值应在 16-18GB 范围内"""
        vram = gpu_utils.estimate_vram_requirements("3b", "fp16", 1920, 1080, num_frames=1)
        assert 16.0 <= vram <= 18.0

    def test_7b_fp16_1080p_image(self):
        """7B FP16 + 1080p 图像，基线 24GB"""
        vram = gpu_utils.estimate_vram_requirements("7b", "fp16", 1920, 1080, num_frames=1)
        assert 24.0 <= vram <= 26.0

    def test_7b_fp8_1080p_image(self):
        """7B FP8 + 1080p 图像，基线 12GB"""
        vram = gpu_utils.estimate_vram_requirements("7b", "fp8", 1920, 1080, num_frames=1)
        assert 12.0 <= vram <= 14.0

    def test_7b_sharp_same_as_7b(self):
        """7B-Sharp 显存基线与 7B 相同"""
        vram_sharp = gpu_utils.estimate_vram_requirements("7b-sharp", "fp16", 1920, 1080)
        vram_7b = gpu_utils.estimate_vram_requirements("7b", "fp16", 1920, 1080)
        assert vram_sharp == vram_7b

    def test_4k_resolution_increases_vram(self):
        """4K 分辨率显存应高于 1080p"""
        vram_1080p = gpu_utils.estimate_vram_requirements("3b", "fp16", 1920, 1080)
        vram_4k = gpu_utils.estimate_vram_requirements("3b", "fp16", 3840, 2160)
        assert vram_4k > vram_1080p

    def test_video_increases_vram(self):
        """视频帧数增加显存需求"""
        vram_image = gpu_utils.estimate_vram_requirements("3b", "fp16", 1920, 1080, num_frames=1)
        vram_video = gpu_utils.estimate_vram_requirements("3b", "fp16", 1920, 1080, num_frames=100)
        assert vram_video > vram_image

    def test_fp8_less_than_fp16(self):
        """FP8 显存应低于 FP16"""
        fp16 = gpu_utils.estimate_vram_requirements("7b", "fp16", 1920, 1080)
        fp8 = gpu_utils.estimate_vram_requirements("7b", "fp8", 1920, 1080)
        assert fp8 < fp16

    def test_unknown_model_uses_default(self):
        """未知模型使用 3B 默认值"""
        vram = gpu_utils.estimate_vram_requirements("unknown", "fp16", 1920, 1080)
        vram_3b = gpu_utils.estimate_vram_requirements("3b", "fp16", 1920, 1080)
        assert vram == vram_3b

    def test_smaller_resolution_uses_base(self):
        """小于 1080p 时分辨率开销为 0"""
        vram_small = gpu_utils.estimate_vram_requirements("3b", "fp8", 1280, 720)
        vram_1080p = gpu_utils.estimate_vram_requirements("3b", "fp8", 1920, 1080)
        # 小分辨率不应有额外开销，但帧缓冲可能不同
        assert vram_small <= vram_1080p

    def test_returns_float(self):
        """返回值为 float 类型"""
        vram = gpu_utils.estimate_vram_requirements("3b", "fp16", 1920, 1080)
        assert isinstance(vram, float)


class TestRecommendParams:
    """recommend_params 测试"""

    def test_7b_8gb_available_recommends_fp8_blockswap(self):
        """7B 模型 + 8GB 可用显存 → 推荐 FP8 + BlockSwap（验收标准）"""
        result = gpu_utils.recommend_params("7b", 1920, 1080, num_frames=1, available_vram_gb=8.0)
        assert result["precision"] == "fp8"
        assert result["enable_blockswap"] is True

    def test_3b_24gb_available_recommends_fp16(self):
        """3B 模型 + 24GB 可用显存 → 推荐 FP16 不开 BlockSwap"""
        result = gpu_utils.recommend_params("3b", 1920, 1080, num_frames=1, available_vram_gb=24.0)
        assert result["precision"] == "fp16"
        assert result["enable_blockswap"] is False
        assert result["risk"] == "low"

    def test_3b_10gb_available_recommends_fp8(self):
        """3B 模型 + 10GB 可用显存 → FP16 不够（需 16GB），推荐 FP8"""
        result = gpu_utils.recommend_params("3b", 1920, 1080, num_frames=1, available_vram_gb=10.0)
        assert result["precision"] == "fp8"
        assert result["enable_blockswap"] is False
        assert result["risk"] == "low"

    def test_7b_12gb_available_recommends_fp8(self):
        """7B 模型 + 12GB 可用显存 → FP16 不够（需 24GB），FP8 刚好够（12GB）"""
        result = gpu_utils.recommend_params("7b", 1920, 1080, num_frames=1, available_vram_gb=12.0)
        # safe_threshold = 12 * 0.9 = 10.8, fp8_needed ≈ 12.02 > 10.8 → 需要 BlockSwap
        assert result["precision"] == "fp8"
        assert result["enable_blockswap"] is True

    def test_7b_4gb_available_high_risk(self):
        """7B 模型 + 4GB 可用显存 → 高风险"""
        result = gpu_utils.recommend_params("7b", 1920, 1080, num_frames=1, available_vram_gb=4.0)
        assert result["precision"] == "fp8"
        assert result["enable_blockswap"] is True
        assert result["risk"] == "high"
        assert result["warning"] != ""

    def test_returns_all_required_keys(self):
        """返回字典包含所有必需键"""
        result = gpu_utils.recommend_params("3b", 1920, 1080, available_vram_gb=16.0)
        required_keys = {
            "precision",
            "enable_blockswap",
            "blocks_to_swap",
            "tile_size",
            "vram_tile_overlap",
            "estimated_vram_gb",
            "available_vram_gb",
            "risk",
            "warning",
        }
        assert set(result.keys()) == required_keys

    def test_tile_size_scales_with_vram(self):
        """tile_size 随可用显存分级"""
        # 20GB+ → 1024
        result_high = gpu_utils.recommend_params("3b", 1920, 1080, available_vram_gb=24.0)
        assert result_high["tile_size"] == 1024
        assert result_high["vram_tile_overlap"] == 512

        # 12-20GB → 768
        result_mid = gpu_utils.recommend_params("3b", 1920, 1080, available_vram_gb=16.0)
        assert result_mid["tile_size"] == 768
        assert result_mid["vram_tile_overlap"] == 256

        # 8-12GB → 512
        result_low = gpu_utils.recommend_params("3b", 1920, 1080, available_vram_gb=10.0)
        assert result_low["tile_size"] == 512
        assert result_low["vram_tile_overlap"] == 128

        # <8GB → 256
        result_min = gpu_utils.recommend_params("3b", 1920, 1080, available_vram_gb=4.0)
        assert result_min["tile_size"] == 256
        assert result_min["vram_tile_overlap"] == 64

    def test_blocks_to_swap_zero_when_no_blockswap(self):
        """不开 BlockSwap 时 blocks_to_swap 为 0"""
        result = gpu_utils.recommend_params("3b", 1920, 1080, available_vram_gb=24.0)
        assert result["enable_blockswap"] is False
        assert result["blocks_to_swap"] == 0

    def test_blocks_to_swap_positive_when_blockswap(self):
        """开 BlockSwap 时 blocks_to_swap 为正数"""
        result = gpu_utils.recommend_params("7b", 1920, 1080, available_vram_gb=8.0)
        assert result["enable_blockswap"] is True
        assert result["blocks_to_swap"] > 0
        # 7B 有 36 块，保留 4 块，换出 32 块
        assert result["blocks_to_swap"] == 32

    def test_auto_detect_vram_when_not_provided(self):
        """available_vram_gb=None 时自动探测"""
        mock_info = {"available_mb": 16384, "total_mb": 24576, "utilization_pct": 33.3}
        with patch.object(gpu_utils, "get_gpu_memory_info", return_value=mock_info):
            result = gpu_utils.recommend_params("3b", 1920, 1080)
        # 16GB available → FP16 needs ~16.02, safe_threshold=14.4 → 不够 → FP8
        assert result["available_vram_gb"] == 16.0

    def test_warning_empty_for_low_risk(self):
        """低风险时 warning 为空字符串"""
        result = gpu_utils.recommend_params("3b", 1920, 1080, available_vram_gb=32.0)
        assert result["risk"] == "low"
        assert result["warning"] == ""

    def test_warning_nonempty_for_medium_risk(self):
        """中等风险时 warning 非空"""
        result = gpu_utils.recommend_params("7b", 1920, 1080, available_vram_gb=8.0)
        assert result["risk"] == "medium"
        assert result["warning"] != ""

    def test_7b_sharp_same_recommendation_as_7b(self):
        """7B-Sharp 推荐结果与 7B 相同"""
        result_7b = gpu_utils.recommend_params("7b", 1920, 1080, available_vram_gb=8.0)
        result_sharp = gpu_utils.recommend_params("7b-sharp", 1920, 1080, available_vram_gb=8.0)
        assert result_7b["precision"] == result_sharp["precision"]
        assert result_7b["enable_blockswap"] == result_sharp["enable_blockswap"]
        assert result_7b["estimated_vram_gb"] == result_sharp["estimated_vram_gb"]

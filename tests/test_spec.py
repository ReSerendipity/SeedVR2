"""spec.py 领域公式契约层单元测试。

验证从 routes/engines/config 提炼的纯函数行为，
并与实际代码行为（common.parse_unified_params / enforce_double_resolution / 模型配置常量）保持一致。
"""

from __future__ import annotations

import pytest

from app.integrated_app.spec import (
    CONDITION_NOISE_SCALE,
    CONDITION_SR,
    DEFAULT_RESOLUTION_H,
    DEFAULT_RESOLUTION_W,
    DIFFUSION_CFG_SCALE,
    DIFFUSION_STEPS,
    DIFFUSION_T,
    LATENT_SPATIAL_FACTOR,
    MODEL_SPECS,
    TILE_ALIGNMENT,
    align_tile_dimension,
    double_res_target_resolution,
    double_res_tile_params,
    frame_count_from_duration,
    is_valid_batch_size,
    latent_spatial_size,
    model_size_from_dit_model,
    normalize_batch_size,
    pad_temporal_frames,
    recommend_precision,
    resolution_clamp,
)


class TestNormalizeBatchSize:
    """batch_size 4n+1 正规化。"""

    def test_keeps_valid_4n_plus_1(self):
        assert normalize_batch_size(1) == 1
        assert normalize_batch_size(5) == 5
        assert normalize_batch_size(9) == 9
        assert normalize_batch_size(13) == 13
        assert normalize_batch_size(33) == 33

    def test_rounds_to_nearest_4n_plus_1(self):
        assert normalize_batch_size(10) == 9
        assert normalize_batch_size(6) == 5
        assert normalize_batch_size(14) == 13

    def test_below_one_returns_one(self):
        assert normalize_batch_size(0) == 1
        assert normalize_batch_size(-5) == 1

    def test_is_valid_batch_size(self):
        assert is_valid_batch_size(5) is True
        assert is_valid_batch_size(1) is True
        assert is_valid_batch_size(10) is False
        assert is_valid_batch_size(0) is False

    def test_matches_runtime_rule(self):
        """与 common.parse_unified_params 中的修正逻辑一致。"""
        for n in (3, 6, 10, 100):
            expected = max(1, 4 * max(0, round((n - 1) / 4)) + 1)
            assert normalize_batch_size(n) == expected


class TestTemporalPadding:
    """视频帧数时间维度对齐 (T-1) % (4*sp_size) == 0。"""

    def test_already_aligned_unchanged(self):
        assert pad_temporal_frames(33, 1) == 33
        assert pad_temporal_frames(1, 1) == 1
        assert pad_temporal_frames(29, 1) == 29

    def test_pads_to_alignment(self):
        assert pad_temporal_frames(32, 1) == 33
        assert pad_temporal_frames(30, 1) == 33
        assert pad_temporal_frames(2, 1) == 5

    def test_respects_sp_size(self):
        # sp_size=2 -> 对齐倍数 8: (T-1) % 8 == 0
        assert pad_temporal_frames(33, 2) == 33  # (32) % 8 == 0 -> 已对齐
        assert pad_temporal_frames(40, 2) == 41  # (39) % 8 == 7 -> 补 1 帧

    def test_below_one_returns_one(self):
        assert pad_temporal_frames(0) == 1
        assert pad_temporal_frames(-3) == 1


class TestTileAlignment:
    """空间维度 16 对齐。"""

    def test_aligned_dimensions_unchanged(self):
        assert align_tile_dimension(1920) == 1920
        assert align_tile_dimension(1088) == 1088
        assert align_tile_dimension(512) == 512

    def test_unaligned_dimensions_padded(self):
        assert align_tile_dimension(1080) == 1088
        assert align_tile_dimension(1) == 16
        assert align_tile_dimension(17) == 32

    def test_non_positive_returns_zero(self):
        assert align_tile_dimension(0) == 0
        assert align_tile_dimension(-10) == 0


class TestDoubleRes:
    """两倍模式分辨率与 tile 参数。"""

    def test_target_resolution_short_edge_x2(self):
        assert double_res_target_resolution(1080, 1920) == 2160
        assert double_res_target_resolution(1920, 1080) == 2160
        assert double_res_target_resolution(768, 1344) == 1536

    def test_target_resolution_invalid_input(self):
        assert double_res_target_resolution(0, 100) == 0
        assert double_res_target_resolution(-1, 100) == 0

    def test_tile_params_standard(self):
        assert double_res_tile_params(1080) == (1080, 540)
        assert double_res_tile_params(256) == (256, 128)

    def test_tile_params_minimum_size(self):
        # 小图：tile_size 下限 64
        size, overlap = double_res_tile_params(32)
        assert size == 64
        assert overlap == 16

    def test_tile_overlap_never_exceeds_half(self):
        # overlap <= tile_size // 2
        size, overlap = double_res_tile_params(100)
        assert size == 100
        assert overlap == 50 == size // 2


class TestLatentSize:
    """潜空间尺寸计算。"""

    def test_latent_factor_is_16(self):
        # VAE s8 × patch 2 = 16
        assert LATENT_SPATIAL_FACTOR == 16

    def test_latent_spatial_size(self):
        assert latent_spatial_size(1920, 1088) == (120, 68)
        assert latent_spatial_size(1536, 1536) == (96, 96)


class TestPrecisionRecommendation:
    """显存 → 精度推荐。"""

    def test_recommends_fp16_when_enough_vram(self):
        assert recommend_precision(24.0, 16.0, 8.0) == "fp16"
        assert recommend_precision(16.0, 16.0, 8.0) == "fp16"

    def test_recommends_fp8_when_only_fp8_fits(self):
        assert recommend_precision(12.0, 16.0, 8.0) == "fp8"
        assert recommend_precision(8.0, 16.0, 8.0) == "fp8"

    def test_falls_back_to_fp8_when_nothing_fits(self):
        assert recommend_precision(4.0, 16.0, 8.0) == "fp8"


class TestResolutionClamp:
    """分辨率回退与钳位。"""

    def test_zero_resolution_falls_back_to_default(self):
        resolution, max_resolution = resolution_clamp(0, 0)
        assert resolution == min(DEFAULT_RESOLUTION_H, DEFAULT_RESOLUTION_W) == 1080
        assert max_resolution == 0

    def test_positive_resolution_kept(self):
        assert resolution_clamp(2160, 0) == (2160, 0)
        assert resolution_clamp(2048, 4096) == (2048, 4096)

    def test_negative_max_resolution_clamped_to_zero(self):
        assert resolution_clamp(1080, -5) == (1080, 0)


class TestFrameCount:
    """帧数 = 时长 × 帧率。"""

    def test_frame_count(self):
        assert frame_count_from_duration(10.0, 30.0) == 300
        assert frame_count_from_duration(0.5, 24.0) == 12

    def test_invalid_inputs(self):
        assert frame_count_from_duration(0, 30.0) == 0
        assert frame_count_from_duration(10.0, 0) == 0
        assert frame_count_from_duration(-1.0, 30.0) == 0


class TestModelSizeFromDitModel:
    """dit_model 尺寸提取。"""

    def test_basic(self):
        assert model_size_from_dit_model("3b_fp16") == "3b"
        assert model_size_from_dit_model("7b_fp8") == "7b"

    def test_sharp_variant(self):
        assert model_size_from_dit_model("7b_sharp_fp16") == "7b_sharp"

    def test_empty_falls_back_to_3b(self):
        assert model_size_from_dit_model("") == "3b"


class TestModelSpecs:
    """模型架构常量与 configs_3b/configs_7b 一致。"""

    def test_has_three_model_sizes(self):
        assert set(MODEL_SPECS.keys()) == {"3b", "7b", "7b_sharp"}

    def test_num_layers_matches_configs(self):
        assert MODEL_SPECS["3b"]["num_layers"] == 32
        assert MODEL_SPECS["7b"]["num_layers"] == 36
        assert MODEL_SPECS["7b_sharp"]["num_layers"] == 36

    def test_vram_thresholds_match_config_yaml(self):
        assert MODEL_SPECS["3b"]["min_vram_fp16_gb"] == 16
        assert MODEL_SPECS["3b"]["min_vram_fp8_gb"] == 8
        assert MODEL_SPECS["7b"]["min_vram_fp16_gb"] == 24
        assert MODEL_SPECS["7b"]["min_vram_fp8_gb"] == 12

    def test_diffusion_constants_match(self):
        for size, spec in MODEL_SPECS.items():
            assert spec["diffusion"]["T"] == DIFFUSION_T == 1000.0, size
            assert spec["diffusion"]["steps"] == DIFFUSION_STEPS == 50, size
            assert spec["cfg_scale"] == DIFFUSION_CFG_SCALE == 7.5, size
            assert spec["condition"]["noise_scale"] == CONDITION_NOISE_SCALE == 0.25, size
            assert spec["condition"]["sr"] == CONDITION_SR == 1.0, size
            assert spec["patch_size"] == [1, 2, 2], size
            assert spec["vae_scaling_factor"] == 0.9152, size

    def test_tile_alignment_constant(self):
        assert TILE_ALIGNMENT == 16


if __name__ == "__main__":
    pytest.main([__file__, "-q", "-p", "no:cacheprovider"])

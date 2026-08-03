"""color_fix 模块单元测试

覆盖 LAB、HSV、Wavelet、Wavelet-Adaptive、AdaIN 颜色校正算法及
apply_color_correction 调度函数。
使用 numpy 合成测试图像，不依赖外部文件。
"""

from unittest.mock import patch

import cv2
import numpy as np
import pytest

from bin.integrated_app.color_fix import (
    apply_color_correction,
    color_fix_adain,
    color_fix_hsv,
    color_fix_lab,
    color_fix_wavelet,
    color_fix_wavelet_adaptive,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def small_image():
    """64x64 纯色 RGB 图像 (红色)"""
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    img[:, :, 0] = 200  # R
    img[:, :, 1] = 50  # G
    img[:, :, 2] = 50  # B
    return img


@pytest.fixture
def small_image_shifted():
    """与 small_image 同尺寸但颜色偏移的图像 (偏蓝)"""
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    img[:, :, 0] = 50  # R
    img[:, :, 1] = 50  # G
    img[:, :, 2] = 200  # B
    return img


@pytest.fixture
def gradient_image():
    """128x128 渐变 RGB 图像"""
    img = np.zeros((128, 128, 3), dtype=np.uint8)
    for c in range(3):
        img[:, :, c] = np.linspace(0, 255, 128, dtype=np.uint8).reshape(1, -1)
    return img


@pytest.fixture
def gradient_image_bright():
    """与 gradient_image 同尺寸但整体更亮的渐变图像"""
    img = np.zeros((128, 128, 3), dtype=np.uint8)
    for c in range(3):
        img[:, :, c] = np.clip(np.linspace(50, 255, 128, dtype=np.float32).reshape(1, -1), 0, 255).astype(np.uint8)
    return img


@pytest.fixture
def random_image():
    """64x64 随机噪声图像 (固定种子保证可复现)"""
    rng = np.random.RandomState(42)
    return rng.randint(0, 256, (64, 64, 3), dtype=np.uint8)


@pytest.fixture
def random_image_shifted():
    """与 random_image 同尺寸但有颜色偏移的随机图像"""
    rng = np.random.RandomState(99)
    return rng.randint(0, 256, (64, 64, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# color_fix_lab
# ---------------------------------------------------------------------------


class TestColorFixLab:
    """LAB 颜色匹配测试"""

    def test_returns_same_shape(self, small_image, small_image_shifted):
        """输出形状与输入一致"""
        result = color_fix_lab(small_image, small_image_shifted)
        assert result.shape == small_image.shape

    def test_returns_uint8(self, small_image, small_image_shifted):
        """输出 dtype 为 uint8"""
        result = color_fix_lab(small_image, small_image_shifted)
        assert result.dtype == np.uint8

    def test_values_in_valid_range(self, gradient_image, gradient_image_bright):
        """输出像素值在 [0, 255] 范围内"""
        result = color_fix_lab(gradient_image, gradient_image_bright)
        assert result.min() >= 0
        assert result.max() <= 255

    def test_identical_images_unchanged(self, small_image):
        """相同图像校正后应几乎不变"""
        result = color_fix_lab(small_image, small_image.copy())
        # 允许因色彩空间转换的微小舍入差异
        assert np.mean(np.abs(result.astype(np.float32) - small_image.astype(np.float32))) < 5.0

    def test_resizes_mismatched_reference(self, small_image):
        """参考图像尺寸不同时自动 resize"""
        large_ref = cv2.resize(small_image, (128, 128))
        result = color_fix_lab(small_image, large_ref)
        assert result.shape == small_image.shape

    def test_color_shift_corrected(self, small_image, small_image_shifted):
        """校正后 result 的 LAB 均值应更接近 reference"""
        result_lab = cv2.cvtColor(color_fix_lab(small_image, small_image_shifted), cv2.COLOR_RGB2LAB)
        ref_lab = cv2.cvtColor(small_image_shifted, cv2.COLOR_RGB2LAB)
        orig_lab = cv2.cvtColor(small_image, cv2.COLOR_RGB2LAB)

        # 校正后 A 通道均值应更接近 reference
        orig_diff = abs(orig_lab[:, :, 1].mean() - ref_lab[:, :, 1].mean())
        corrected_diff = abs(result_lab[:, :, 1].mean() - ref_lab[:, :, 1].mean())
        assert corrected_diff <= orig_diff + 1.0  # 允许舍入误差

    def test_handles_zero_std(self):
        """处理标准差为 0 的纯色图像不报错"""
        img = np.full((32, 32, 3), 128, dtype=np.uint8)
        ref = np.full((32, 32, 3), 100, dtype=np.uint8)
        result = color_fix_lab(img, ref)
        assert result.shape == img.shape
        assert result.dtype == np.uint8


# ---------------------------------------------------------------------------
# color_fix_hsv
# ---------------------------------------------------------------------------


class TestColorFixHsv:
    """HSV 颜色匹配测试"""

    def test_returns_same_shape(self, small_image, small_image_shifted):
        """输出形状与输入一致"""
        result = color_fix_hsv(small_image, small_image_shifted)
        assert result.shape == small_image.shape

    def test_returns_uint8(self, small_image, small_image_shifted):
        """输出 dtype 为 uint8"""
        result = color_fix_hsv(small_image, small_image_shifted)
        assert result.dtype == np.uint8

    def test_values_in_valid_range(self, gradient_image, gradient_image_bright):
        """输出像素值在 [0, 255] 范围内"""
        result = color_fix_hsv(gradient_image, gradient_image_bright)
        assert result.min() >= 0
        assert result.max() <= 255

    def test_identical_images_unchanged(self, small_image):
        """相同图像校正后应几乎不变"""
        result = color_fix_hsv(small_image, small_image.copy())
        assert np.mean(np.abs(result.astype(np.float32) - small_image.astype(np.float32))) < 5.0

    def test_resizes_mismatched_reference(self, small_image):
        """参考图像尺寸不同时自动 resize"""
        large_ref = cv2.resize(small_image, (128, 128))
        result = color_fix_hsv(small_image, large_ref)
        assert result.shape == small_image.shape

    def test_handles_zero_std(self):
        """处理标准差为 0 的纯色图像不报错"""
        img = np.full((32, 32, 3), 128, dtype=np.uint8)
        ref = np.full((32, 32, 3), 100, dtype=np.uint8)
        result = color_fix_hsv(img, ref)
        assert result.shape == img.shape


# ---------------------------------------------------------------------------
# color_fix_adain
# ---------------------------------------------------------------------------


class TestColorFixAdaIN:
    """AdaIN 颜色匹配测试"""

    def test_returns_same_shape(self, small_image, small_image_shifted):
        """输出形状与输入一致"""
        result = color_fix_adain(small_image, small_image_shifted)
        assert result.shape == small_image.shape

    def test_returns_uint8(self, small_image, small_image_shifted):
        """输出 dtype 为 uint8"""
        result = color_fix_adain(small_image, small_image_shifted)
        assert result.dtype == np.uint8

    def test_values_in_valid_range(self, gradient_image, gradient_image_bright):
        """输出像素值在 [0, 255] 范围内"""
        result = color_fix_adain(gradient_image, gradient_image_bright)
        assert result.min() >= 0
        assert result.max() <= 255

    def test_identical_images_unchanged(self, small_image):
        """相同图像校正后应几乎不变"""
        result = color_fix_adain(small_image, small_image.copy())
        assert np.mean(np.abs(result.astype(np.float32) - small_image.astype(np.float32))) < 2.0

    def test_resizes_mismatched_reference(self, small_image):
        """参考图像尺寸不同时自动 resize"""
        large_ref = cv2.resize(small_image, (128, 128))
        result = color_fix_adain(small_image, large_ref)
        assert result.shape == small_image.shape

    def test_mean_matches_reference(self, random_image, random_image_shifted):
        """校正后 RGB 均值应接近 reference 的 RGB 均值"""
        corrected = color_fix_adain(random_image, random_image_shifted).astype(np.float32)
        ref = random_image_shifted.astype(np.float32)
        for c in range(3):
            assert abs(corrected[:, :, c].mean() - ref[:, :, c].mean()) < 5.0

    def test_handles_zero_std(self):
        """处理标准差为 0 的纯色图像不报错"""
        img = np.full((32, 32, 3), 128, dtype=np.uint8)
        ref = np.full((32, 32, 3), 100, dtype=np.uint8)
        result = color_fix_adain(img, ref)
        assert result.shape == img.shape
        assert result.dtype == np.uint8


# ---------------------------------------------------------------------------
# color_fix_wavelet
# ---------------------------------------------------------------------------


class TestColorFixWavelet:
    """小波颜色匹配测试"""

    def test_returns_same_shape(self, gradient_image, gradient_image_bright):
        """输出形状与输入一致"""
        result = color_fix_wavelet(gradient_image, gradient_image_bright)
        assert result.shape == gradient_image.shape

    def test_returns_uint8(self, gradient_image, gradient_image_bright):
        """输出 dtype 为 uint8"""
        result = color_fix_wavelet(gradient_image, gradient_image_bright)
        assert result.dtype == np.uint8

    def test_values_in_valid_range(self, gradient_image, gradient_image_bright):
        """输出像素值在 [0, 255] 范围内"""
        result = color_fix_wavelet(gradient_image, gradient_image_bright)
        assert result.min() >= 0
        assert result.max() <= 255

    def test_resizes_mismatched_reference(self, small_image):
        """参考图像尺寸不同时自动 resize"""
        large_ref = cv2.resize(small_image, (128, 128))
        result = color_fix_wavelet(small_image, large_ref)
        assert result.shape == small_image.shape

    def test_fallback_to_lab_when_pywt_missing(self, small_image, small_image_shifted):
        """pywt 未安装时回退到 LAB 颜色匹配"""
        with patch.dict("sys.modules", {"pywt": None}):
            # 模拟 import pywt 抛出 ImportError
            import builtins

            original_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if name == "pywt":
                    raise ImportError("No module named 'pywt'")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result = color_fix_wavelet(small_image, small_image_shifted)
                assert result.shape == small_image.shape
                assert result.dtype == np.uint8

    def test_custom_level(self, gradient_image, gradient_image_bright):
        """自定义分解层数正常工作"""
        result = color_fix_wavelet(gradient_image, gradient_image_bright, level=3)
        assert result.shape == gradient_image.shape
        assert result.dtype == np.uint8


# ---------------------------------------------------------------------------
# color_fix_wavelet_adaptive
# ---------------------------------------------------------------------------


class TestColorFixWaveletAdaptive:
    """小波 + 自适应饱和度颜色校正测试"""

    def test_returns_same_shape(self, gradient_image, gradient_image_bright):
        """输出形状与输入一致"""
        result = color_fix_wavelet_adaptive(gradient_image, gradient_image_bright)
        assert result.shape == gradient_image.shape

    def test_returns_uint8(self, gradient_image, gradient_image_bright):
        """输出 dtype 为 uint8"""
        result = color_fix_wavelet_adaptive(gradient_image, gradient_image_bright)
        assert result.dtype == np.uint8

    def test_values_in_valid_range(self, gradient_image, gradient_image_bright):
        """输出像素值在 [0, 255] 范围内"""
        result = color_fix_wavelet_adaptive(gradient_image, gradient_image_bright)
        assert result.min() >= 0
        assert result.max() <= 255

    def test_saturation_weight_zero(self, small_image, small_image_shifted):
        """saturation_weight=0 时完全使用 wavelet 结果的饱和度"""
        result = color_fix_wavelet_adaptive(small_image, small_image_shifted, saturation_weight=0.0)
        assert result.shape == small_image.shape
        assert result.dtype == np.uint8

    def test_saturation_weight_one(self, small_image, small_image_shifted):
        """saturation_weight=1 时完全保留 result 的饱和度"""
        result = color_fix_wavelet_adaptive(small_image, small_image_shifted, saturation_weight=1.0)
        assert result.shape == small_image.shape
        assert result.dtype == np.uint8

    def test_custom_level(self, gradient_image, gradient_image_bright):
        """自定义分解层数正常工作"""
        result = color_fix_wavelet_adaptive(gradient_image, gradient_image_bright, level=2)
        assert result.shape == gradient_image.shape


# ---------------------------------------------------------------------------
# apply_color_correction
# ---------------------------------------------------------------------------


class TestApplyColorCorrection:
    """apply_color_correction 调度函数测试"""

    def test_method_none_returns_original(self, small_image):
        """method='none' 返回原始图像"""
        result = apply_color_correction(small_image, small_image.copy(), method="none")
        assert np.array_equal(result, small_image)

    def test_method_lab(self, small_image, small_image_shifted):
        """method='lab' 调用 color_fix_lab"""
        result = apply_color_correction(small_image, small_image_shifted, method="lab")
        expected = color_fix_lab(small_image, small_image_shifted)
        assert np.array_equal(result, expected)

    def test_method_hsv(self, small_image, small_image_shifted):
        """method='hsv' 调用 color_fix_hsv"""
        result = apply_color_correction(small_image, small_image_shifted, method="hsv")
        expected = color_fix_hsv(small_image, small_image_shifted)
        assert np.array_equal(result, expected)

    def test_method_adain(self, small_image, small_image_shifted):
        """method='adain' 调用 color_fix_adain"""
        result = apply_color_correction(small_image, small_image_shifted, method="adain")
        expected = color_fix_adain(small_image, small_image_shifted)
        assert np.array_equal(result, expected)

    def test_method_wavelet(self, gradient_image, gradient_image_bright):
        """method='wavelet' 调用 color_fix_wavelet"""
        result = apply_color_correction(gradient_image, gradient_image_bright, method="wavelet")
        expected = color_fix_wavelet(gradient_image, gradient_image_bright)
        assert np.array_equal(result, expected)

    def test_method_wavelet_adaptive(self, gradient_image, gradient_image_bright):
        """method='wavelet_adaptive' 调用 color_fix_wavelet_adaptive"""
        result = apply_color_correction(gradient_image, gradient_image_bright, method="wavelet_adaptive")
        expected = color_fix_wavelet_adaptive(gradient_image, gradient_image_bright)
        assert np.array_equal(result, expected)

    def test_unknown_method_falls_back_to_lab(self, small_image, small_image_shifted):
        """未知方法回退到 LAB"""
        result = apply_color_correction(small_image, small_image_shifted, method="invalid")
        expected = color_fix_lab(small_image, small_image_shifted)
        assert np.array_equal(result, expected)

    def test_default_method_is_lab(self, small_image, small_image_shifted):
        """默认方法为 lab"""
        result = apply_color_correction(small_image, small_image_shifted)
        expected = color_fix_lab(small_image, small_image_shifted)
        assert np.array_equal(result, expected)


# ---------------------------------------------------------------------------
# Integration / robustness tests
# ---------------------------------------------------------------------------


class TestRobustness:
    """鲁棒性测试"""

    def test_large_color_difference_handled(self):
        """极大颜色差异的图像不报错"""
        result_img = np.zeros((64, 64, 3), dtype=np.uint8)
        result_img[:, :, 0] = 255  # 纯红
        ref_img = np.zeros((64, 64, 3), dtype=np.uint8)
        ref_img[:, :, 2] = 255  # 纯蓝

        for method in ["lab", "hsv", "adain"]:
            result = apply_color_correction(result_img, ref_img, method=method)
            assert result.shape == result_img.shape
            assert result.dtype == np.uint8
            assert result.min() >= 0
            assert result.max() <= 255

    def test_single_pixel_image(self):
        """1x1 图像不报错"""
        result_img = np.array([[[100, 150, 200]]], dtype=np.uint8)
        ref_img = np.array([[[50, 100, 150]]], dtype=np.uint8)

        for method in ["lab", "hsv", "adain"]:
            result = apply_color_correction(result_img, ref_img, method=method)
            assert result.shape == (1, 1, 3)
            assert result.dtype == np.uint8

    def test_all_black_image(self):
        """全黑图像不报错"""
        img = np.zeros((32, 32, 3), dtype=np.uint8)
        ref = np.zeros((32, 32, 3), dtype=np.uint8)

        for method in ["lab", "hsv", "adain"]:
            result = apply_color_correction(img, ref, method=method)
            assert result.shape == img.shape
            assert result.dtype == np.uint8

    def test_all_white_image(self):
        """全白图像不报错"""
        img = np.full((32, 32, 3), 255, dtype=np.uint8)
        ref = np.full((32, 32, 3), 255, dtype=np.uint8)

        for method in ["lab", "hsv", "adain"]:
            result = apply_color_correction(img, ref, method=method)
            assert result.shape == img.shape
            assert result.dtype == np.uint8

    def test_non_contiguous_array(self, small_image, small_image_shifted):
        """非连续内存数组正常工作"""
        # 切片操作产生非连续数组
        result = small_image[::2, ::2, :]
        ref = small_image_shifted[::2, ::2, :]
        for method in ["lab", "hsv", "adain"]:
            out = apply_color_correction(result, ref, method=method)
            assert out.shape == result.shape
            assert out.dtype == np.uint8

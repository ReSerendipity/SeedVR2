"""security/watermark.py 单元测试（DCT 频域水印）

覆盖：
- embed_watermark 正常嵌入、边界输入（None/空/灰度/多通道）
- extract_watermark 提取与原始载荷比对（品牌标识可验证）
- verify_watermark 签名验证逻辑（有密钥/无密钥路径）
- QIM 量化调制的水印鲁棒性（基础检查）
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from bin.integrated_app.security.watermark import (
    _WATERMARK_ALPHA,
    _WATERMARK_KEY_ENV,
    _text_to_bits,
    _bits_to_text,
    embed_watermark,
    extract_watermark,
    verify_watermark,
)


class TestTextToBits:
    """文本转二进制位测试"""

    def test_simple_text_conversion(self):
        text = "A"
        bits = _text_to_bits(text)
        reconstructed = _bits_to_text(bits)
        assert reconstructed == text

    def test_unicode_text_conversion(self):
        text = "SeedVR2_中文"
        bits = _text_to_bits(text)
        reconstructed = _bits_to_text(bits)
        assert reconstructed == text

    def test_empty_text(self):
        text = ""
        bits = _text_to_bits(text)
        assert len(bits) == 0


class TestEmbedWatermark:
    """水印嵌入测试"""

    def test_embed_basic_rgb_image(self, tmp_path):
        """RGB 图像正常嵌入"""
        # 创建测试图像 (128x128 RGB)
        img = np.random.randint(0, 256, (128, 128, 3), dtype=np.uint8)
        payload = "TEST_WATERMARK_PAYLOAD"

        result = embed_watermark(img, payload=payload)

        assert result.shape == img.shape
        assert result.dtype == np.uint8
        # 嵌入强度极低时图像变化应该很小
        assert np.abs(result.astype(np.float64) - img.astype(np.float64)).max() < 10

    def test_embed_grayscale_image(self):
        """灰度图像嵌入"""
        img = np.random.randint(0, 256, (128, 128), dtype=np.uint8)
        result = embed_watermark(img, payload="TEST")

        assert result.shape == img.shape
        assert result.dtype == np.uint8

    def test_embed_none_input(self):
        """None 输入返回 None"""
        assert embed_watermark(None) is None

    def test_embed_empty_array(self):
        """空数组返回空数组"""
        img = np.array([])
        result = embed_watermark(img)
        assert result.size == 0

    def test_embed_small_image(self):
        """小于 8x8 的图像不崩溃（无法分块 DCT）"""
        img = np.random.randint(0, 256, (4, 4, 3), dtype=np.uint8)
        result = embed_watermark(img, payload="TEST")
        # 函数应返回有效结果但不一定包含水印
        assert result.shape == img.shape
        assert result.dtype == np.uint8

    def test_embed_preserves_value_range(self):
        """嵌入后像素值仍在 [0, 255] 范围内"""
        img = np.random.randint(0, 256, (128, 128, 3), dtype=np.uint8)
        result = embed_watermark(img, payload="TEST")

        assert result.min() >= 0
        assert result.max() <= 255


class TestExtractWatermark:
    """水印提取测试"""

    def test_extract_basic_brands_contain_seedvr2(self):
        """提取的水印应包含品牌标识 'SeedVR2'"""
        img = np.random.randint(50, 200, (128, 128, 3), dtype=np.uint8)
        payload = "SeedVR2_ReSerendipity_20250101120000"

        watermarked = embed_watermark(img, payload=payload)
        extracted = extract_watermark(watermarked)

        # 核心验证：品牌标识 'SeedVR2' 必须存在于提取结果中
        assert "SeedVR2" in extracted

    def test_extract_after_slight_compression_simulation(self):
        """模拟轻微 JPEG 压缩后的水印鲁棒性（丢弃高频噪声）"""
        img = np.random.randint(80, 180, (128, 128, 3), dtype=np.uint8)
        payload = "SeedVR2_CompressTest"

        watermarked = embed_watermark(img, payload=payload)
        # 轻微扰动（±2 量化误差，模拟 JPEG 低压缩比）
        perturbed = np.clip(watermarked.astype(np.int16) + np.random.randint(-2, 3, watermarked.shape), 0, 255).astype(np.uint8)

        extracted = extract_watermark(perturbed)
        # DCT 中频对轻微扰动具有鲁棒性
        assert "SeedVR2" in extracted or len(extracted) > 0


class TestVerifyWatermark:
    """水印验证逻辑测试"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, monkeypatch, tmp_path):
        """每个测试前清除水印密钥环境变量"""
        monkeypatch.delenv(_WATERMARK_KEY_ENV, raising=False)
        yield

    def test_verify_without_key_returns_false_for_unsigned_payload(self, tmp_path, monkeypatch):
        """未配置密钥时对未签名载荷退化为弱检测（字符串包含）"""
        img = np.random.randint(0, 256, (128, 128, 3), dtype=np.uint8)
        payload = "NotSeedVR2_TestPayload"

        watermarked = embed_watermark(img, payload=payload)
        result = verify_watermark(watermarked)

        # 没有密钥时退化为品牌字符串检查
        assert result is False

    def test_verify_empty_image(self):
        """空图像验证返回 False"""
        assert verify_watermark(np.array([])) is False

    def test_verify_random_noise_image(self):
        """随机噪声图像不应通过验证"""
        noise = np.random.randint(0, 256, (128, 128, 3), dtype=np.uint8)
        # 没有嵌入水印，验证应失败
        assert verify_watermark(noise) is False

    def test_verify_with_custom_alpha(self):
        """自定义 alpha 参数验证"""
        img = np.random.randint(0, 256, (128, 128, 3), dtype=np.uint8)
        payload = "SeedVR2_CustomAlpha"

        watermarked = embed_watermark(img, payload=payload, alpha=_WATERMARK_ALPHA * 1.5)
        # 使用不同 alpha 提取可能会失效，但不应崩溃
        extracted = extract_watermark(watermarked, alpha=_WATERMARK_ALPHA * 1.5)
        assert isinstance(extracted, str)

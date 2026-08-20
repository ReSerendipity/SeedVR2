#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2024-2026 ReSerendipity
# SPDX-License-Identifier: Apache-2.0
"""上传文件魔数校验模块测试 (T4-2)。

验证各种图片和视频格式的魔数校验逻辑，
包括正常文件通过、伪装文件被拦截的场景。
"""

from app.integrated_app.security.magic_check import validate_upload_magic


class TestImageMagicCheck:
    """图片魔数校验测试。"""

    def test_png_valid(self):
        """合法 PNG 文件通过校验。"""
        contents = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        is_valid, detected, err = validate_upload_magic(contents, ".png")
        assert is_valid is True
        assert detected == "image"
        assert err is None

    def test_jpeg_valid(self):
        """合法 JPEG 文件通过校验。"""
        contents = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        is_valid, detected, err = validate_upload_magic(contents, ".jpg")
        assert is_valid is True
        assert detected == "image"

    def test_jpeg_uppercase_ext(self):
        """大写扩展名也能通过。"""
        contents = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        is_valid, detected, _ = validate_upload_magic(contents, ".JPEG")
        assert is_valid is True
        assert detected == "image"

    def test_bmp_valid(self):
        """合法 BMP 文件通过校验。"""
        contents = b"BM" + b"\x00" * 100
        is_valid, detected, _ = validate_upload_magic(contents, ".bmp")
        assert is_valid is True
        assert detected == "image"

    def test_webp_valid(self):
        """合法 WebP 文件通过校验。"""
        contents = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 100
        is_valid, detected, _ = validate_upload_magic(contents, ".webp")
        assert is_valid is True
        assert detected == "image"

    def test_gif87a_rejected_not_supported(self):
        """GIF87a 不在支持的扩展名中，被拒绝。"""
        contents = b"GIF87a" + b"\x00" * 100
        is_valid, _, _ = validate_upload_magic(contents, ".gif")
        assert is_valid is False

    def test_gif89a_rejected_not_supported(self):
        """GIF89a 不在支持的扩展名中，被拒绝。"""
        contents = b"GIF89a" + b"\x00" * 100
        is_valid, _, _ = validate_upload_magic(contents, ".gif")
        assert is_valid is False

    def test_fake_image_rejected(self):
        """伪装的图片（实际为可执行文件）被拒绝。"""
        # MZ header (Windows EXE) 伪装为 .jpg
        contents = b"MZ\x90\x00" + b"\x00" * 100
        is_valid, detected, err = validate_upload_magic(contents, ".jpg")
        assert is_valid is False
        assert "不匹配" in err or "伪装" in err

    def test_png_with_jpg_ext_rejected(self):
        """PNG 内容但扩展名为 .jpg 被拒绝。"""
        contents = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        is_valid, _, err = validate_upload_magic(contents, ".jpg")
        assert is_valid is False

    def test_empty_file_rejected(self):
        """空文件被拒绝。"""
        is_valid, _, err = validate_upload_magic(b"", ".png")
        assert is_valid is False
        assert "空" in err


class TestVideoMagicCheck:
    """视频魔数校验测试。"""

    def test_mp4_valid(self):
        """合法 MP4 文件通过校验。"""
        # ftyp box: size=0x18, 'ftyp', 'isom'
        contents = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 100
        is_valid, detected, _ = validate_upload_magic(contents, ".mp4")
        assert is_valid is True
        assert detected == "video"

    def test_mkv_valid(self):
        """合法 MKV 文件通过校验。"""
        contents = b"\x1aE\xdf\xa3" + b"\x00" * 100
        is_valid, detected, _ = validate_upload_magic(contents, ".mkv")
        assert is_valid is True
        assert detected == "video"

    def test_flv_valid(self):
        """合法 FLV 文件通过校验。"""
        contents = b"FLV" + b"\x00" * 100
        is_valid, detected, _ = validate_upload_magic(contents, ".flv")
        assert is_valid is True
        assert detected == "video"

    def test_fake_video_rejected(self):
        """伪装的视频文件被拒绝。"""
        # PNG header 伪装为 .mp4
        contents = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        is_valid, _, err = validate_upload_magic(contents, ".mp4")
        assert is_valid is False
        assert "不匹配" in err or "伪装" in err

    def test_unsupported_ext_rejected(self):
        """不支持的扩展名被拒绝。"""
        contents = b"\x00" * 100
        is_valid, _, _ = validate_upload_magic(contents, ".exe")
        assert is_valid is False

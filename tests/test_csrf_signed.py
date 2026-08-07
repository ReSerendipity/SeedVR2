#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2024-2026 ReSerendipity
# SPDX-License-Identifier: Apache-2.0
"""CSRF 签名令牌 + 密钥持久化测试 (T4-1)。

验证 HMAC 签名 CSRF token 的生成与验证逻辑，
以及服务端密钥持久化机制。
"""

import os
import tempfile

from bin.integrated_app.middleware.csrf import CSRFMiddleware
from bin.integrated_app.security.secret_key import get_secret_key, reset_cached_key


class TestSecretKey:
    """密钥持久化测试。"""

    def test_key_is_bytes(self):
        """密钥返回 bytes 类型。"""
        reset_cached_key()
        key = get_secret_key()
        assert isinstance(key, bytes)
        assert len(key) == 32

    def test_key_persistent(self):
        """同一路径多次调用返回相同密钥。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = os.path.join(tmpdir, ".test_secret")
            reset_cached_key()
            key1 = get_secret_key(key_file)
            reset_cached_key()
            key2 = get_secret_key(key_file)
            assert key1 == key2

    def test_key_file_created(self):
        """密钥文件被创建。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = os.path.join(tmpdir, ".test_secret2")
            reset_cached_key()
            get_secret_key(key_file)
            assert os.path.exists(key_file)


class TestCSRFSignedToken:
    """CSRF 签名令牌测试。"""

    def test_token_format(self):
        """token 格式为 nonce.signature。"""
        reset_cached_key()
        token = CSRFMiddleware._generate_signed_token()
        assert "." in token
        parts = token.split(".")
        assert len(parts) == 2
        # nonce 和 signature 都是 hex 字符串
        assert all(c in "0123456789abcdef" for c in parts[0])
        assert all(c in "0123456789abcdef" for c in parts[1])

    def test_valid_token_passes_verification(self):
        """合法 token 通过验证。"""
        reset_cached_key()
        token = CSRFMiddleware._generate_signed_token()
        assert CSRFMiddleware._verify_signed_token(token) is True

    def test_tampered_token_rejected(self):
        """篡改后的 token 被拒绝。"""
        reset_cached_key()
        token = CSRFMiddleware._generate_signed_token()
        # 篡改 signature
        nonce, sig = token.split(".")
        tampered = f"{nonce}.{'0' * len(sig)}"
        assert CSRFMiddleware._verify_signed_token(tampered) is False

    def test_empty_token_rejected(self):
        """空 token 被拒绝。"""
        assert CSRFMiddleware._verify_signed_token("") is False

    def test_no_dot_token_rejected(self):
        """无分隔符的 token 被拒绝。"""
        assert CSRFMiddleware._verify_signed_token("abc123") is False

    def test_different_secret_rejected(self):
        """不同密钥生成的 token 被拒绝。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_file1 = os.path.join(tmpdir, ".secret1")
            key_file2 = os.path.join(tmpdir, ".secret2")

            reset_cached_key()
            get_secret_key(key_file1)
            token = CSRFMiddleware._generate_signed_token()

            reset_cached_key()
            get_secret_key(key_file2)
            assert CSRFMiddleware._verify_signed_token(token) is False

    def test_token_survives_restart(self):
        """token 在密钥持久化后跨"重启"仍可验证。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = os.path.join(tmpdir, ".persistent_secret")

            reset_cached_key()
            get_secret_key(key_file)
            token = CSRFMiddleware._generate_signed_token()

            # 模拟重启：清除缓存后重新加载
            reset_cached_key()
            get_secret_key(key_file)
            assert CSRFMiddleware._verify_signed_token(token) is True

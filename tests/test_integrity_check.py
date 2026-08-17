"""security/integrity_check.py 单元测试（SHA256 模型完整性校验）

覆盖：
- compute_sha256：正常计算/文件不存在报错
- verify_checkpoint：匹配/不匹配/跳过空哈希/强制校验失败
- verify_model_files：批量验证逻辑
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from bin.integrated_app.security.integrity_check import (
    _CHUNK_SIZE,
    compute_sha256,
    verify_checkpoint,
    verify_model_files,
)


class TestComputeSha256:
    """compute_sha256 哈希计算测试"""

    def test_compute_sha256_small_file(self, tmp_path):
        """小文件应正确计算 SHA256"""
        test_file = tmp_path / "small.txt"
        content = b"Hello, World!"
        test_file.write_bytes(content)

        expected_hash = hashlib.sha256(content).hexdigest()
        actual_hash = compute_sha256(test_file)

        assert actual_hash == expected_hash
        assert len(actual_hash) == 64  # SHA256 hex length

    def test_compute_sha256_binary_file(self, tmp_path):
        """二进制文件应正确计算"""
        test_file = tmp_path / "binary.bin"
        binary_content = bytes(range(256)) * 100  # 重复字节模式
        test_file.write_bytes(binary_content)

        expected_hash = hashlib.sha256(binary_content).hexdigest()
        actual_hash = compute_sha256(test_file)

        assert actual_hash == expected_hash

    def test_compute_sha256_large_file_chunks(self, tmp_path):
        """大文件应分块读取并得到正确哈希"""
        test_file = tmp_path / "large.bin"
        # 创建大于 CHUNK_SIZE 的文件
        chunk_size = 8 * 1024 * 1024  # 8MB
        large_content = b"A" * chunk_size + b"B" * 1024  # 略超一块
        test_file.write_bytes(large_content)

        expected_hash = hashlib.sha256(large_content).hexdigest()
        actual_hash = compute_sha256(test_file)

        assert actual_hash == expected_hash

    def test_compute_sha256_nonexistent_file(self, tmp_path):
        """不存在的文件应抛出 FileNotFoundError"""
        nonexistent = tmp_path / "does_not_exist.bin"
        with pytest.raises(FileNotFoundError):
            compute_sha256(nonexistent)

    def test_compute_sha256_empty_file(self, tmp_path):
        """空文件的 SHA256 应等于标准空哈希"""
        empty_file = tmp_path / "empty.txt"
        empty_file.write_bytes(b"")

        # SHA256 of empty string is well-known
        expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        actual = compute_sha256(empty_file)

        assert actual == expected


class TestVerifyCheckpoint:
    """verify_checkpoint 模型校验测试"""

    def test_verify_checkpoint_match(self, tmp_path):
        """哈希匹配时应返回 True"""
        test_file = tmp_path / "model.safetensors"
        content = b"fake model content"
        test_file.write_bytes(content)

        expected_hash = hashlib.sha256(content).hexdigest()
        result = verify_checkpoint(str(test_file), expected_hash, purpose="TestModel")

        assert result is True

    def test_verify_checkpoint_mismatch(self, tmp_path, caplog):
        """哈希不匹配时应返回 False 并记录错误"""
        test_file = tmp_path / "model.safetensors"
        test_file.write_bytes(b"model content")

        wrong_hash = "a" * 64
        result = verify_checkpoint(str(test_file), wrong_hash, purpose="TestModel")

        assert result is False
        assert "[SECURITY CRITICAL]" in caplog.text or "[INTEGRITY]" in caplog.text

    def test_verify_checkpoint_skip_if_empty_default(self, tmp_path):
        """expected_hash 为空且 skip_if_empty=True 时应跳过并返回 True"""
        test_file = tmp_path / "model.safetensors"
        test_file.write_bytes(b"model content")

        result = verify_checkpoint(str(test_file), None, purpose="TestModel", skip_if_empty=True)

        assert result is True

    def test_verify_checkpoint_fail_on_empty_when_required(self, tmp_path, caplog):
        """expected_hash 为空但 skip_if_empty=False 时应拒绝加载"""
        test_file = tmp_path / "model.safetensors"
        test_file.write_bytes(b"model content")

        result = verify_checkpoint(str(test_file), "", purpose="TestModel", skip_if_empty=False)

        assert result is False
        assert "期望哈希为空但 skip_if_empty=False" in caplog.text

    def test_verify_checkpoint_nonexistent_file(self, tmp_path, caplog):
        """文件不存在时应返回 False"""
        nonexistent = str(tmp_path / "nonexistent.safetensors")

        result = verify_checkpoint(nonexistent, "a" * 64, purpose="TestModel", skip_if_empty=False)

        assert result is False
        assert "文件不存在" in caplog.text

    def test_verify_checkpoint_whitespace_trim(self, tmp_path):
        """期望哈希的空白字符应被修剪"""
        test_file = tmp_path / "model.safetensors"
        content = b"model content"
        test_file.write_bytes(content)

        expected_hash = hashlib.sha256(content).hexdigest()
        # 带空格和换行
        messy_hash = f"  {expected_hash}\n  "

        result = verify_checkpoint(str(test_file), messy_hash, purpose="TestModel")

        assert result is True


class TestVerifyModelFiles:
    """verify_model_files 批量验证测试"""

    def test_verify_model_files_all_pass(self, tmp_path):
        """所有配置文件存在且哈希匹配时全部通过"""
        pretrained_dir = tmp_path / "pretrained"
        pretrained_dir.mkdir()

        # 创建 DiT checkpoint
        dit_file = pretrained_dir / "seedvr2_ema_3b_fp16.safetensors"
        dit_content = b"dit model"
        dit_file.write_bytes(dit_content)
        dit_hash = hashlib.sha256(dit_content).hexdigest()

        # 创建 VAE checkpoint
        vae_file = pretrained_dir / "ema_vae_fp16.safetensors"
        vae_content = b"vae model"
        vae_file.write_bytes(vae_content)
        vae_hash = hashlib.sha256(vae_content).hexdigest()

        # 创建 pos_emb.pt
        pos_file = pretrained_dir / "pos_emb.pt"
        pos_content = b"pos emb"
        pos_file.write_bytes(pos_content)
        pos_hash = hashlib.sha256(pos_content).hexdigest()

        model_cfg = {
            "checkpoint_fp16": "seedvr2_ema_3b_fp16.safetensors",
            "sha256_fp16": dit_hash,
            "vae_checkpoint": "ema_vae_fp16.safetensors",
            "sha256_vae": vae_hash,
            "pos_emb": "pos_emb.pt",
            "sha256_pos_emb": pos_hash,
        }

        results = verify_model_files(str(pretrained_dir), model_cfg, precision="fp16")

        assert results.get("DiT-fp16") is True
        assert results.get("VAE") is True
        assert results.get("pos_emb") is True
        assert all(results.values())

    def test_verify_model_files_partial_failure(self, tmp_path, caplog):
        """部分文件缺失时仅标记失败的项"""
        pretrained_dir = tmp_path / "pretrained"
        pretrained_dir.mkdir()

        # 只创建 DiT checkpoint
        dit_file = pretrained_dir / "seedvr2_ema_3b_fp16.safetensors"
        dit_file.write_bytes(b"dit")
        dit_hash = hashlib.sha256(b"dit").hexdigest()

        model_cfg = {
            "checkpoint_fp16": "seedvr2_ema_3b_fp16.safetensors",
            "sha256_fp16": dit_hash,
            "vae_checkpoint": "missing_vae.pt",  # 不存在
            "sha256_vae": "x" * 64,
        }

        results = verify_model_files(str(pretrained_dir), model_cfg, precision="fp16")

        assert results.get("DiT-fp16") is True
        assert results.get("VAE") is False
        assert not all(results.values())

    def test_verify_model_files_without_configured_hashes(self, tmp_path):
        """未配置哈希时全部跳过并返回 True"""
        pretrained_dir = tmp_path / "pretrained"
        pretrained_dir.mkdir()

        model_cfg = {
            "checkpoint_fp16": "model.safetensors",
            # 无 sha256 字段
        }

        results = verify_model_files(str(pretrained_dir), model_cfg, precision="fp16")

        # 没有哈希配置，不应有结果或均为 True
        for key, value in results.items():
            assert value is True  # 跳过即视为通过

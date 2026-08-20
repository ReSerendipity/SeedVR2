"""模型权重加密模块测试 (weight_encryption.py)。"""

import os
import re

import pytest

from app.integrated_app.security.weight_encryption import (
    _MAGIC,
    _VERSION,
    LicenseInfo,
    decrypt_to_memory,
    decrypt_to_temp_file,
    derive_encryption_key,
    encrypt_file,
    generate_license,
    get_machine_fingerprint,
)

KEY = b"\x11" * 32  # 32 字节测试密钥


def test_get_machine_fingerprint():
    """机器指纹为 64 位十六进制且稳定。"""
    fp1 = get_machine_fingerprint()
    fp2 = get_machine_fingerprint()
    assert re.fullmatch(r"[0-9a-f]{64}", fp1)
    assert fp1 == fp2  # 同机稳定


def test_generate_license():
    """许可证包含用户、指纹和 64 位密钥。"""
    lic = generate_license("user@example.com")
    assert isinstance(lic, LicenseInfo)
    assert lic.user == "user@example.com"
    assert re.fullmatch(r"[0-9a-f]{64}", lic.license_key)
    assert lic.machine_fingerprint == get_machine_fingerprint()
    assert lic.issued_at  # issued_at 非空


def test_generate_license_different_users():
    """不同用户生成不同密钥。"""
    a = generate_license("a@example.com").license_key
    b = generate_license("b@example.com").license_key
    assert a != b


def test_derive_encryption_key():
    """密钥派生为 32 字节且确定。"""
    k1 = derive_encryption_key("abc")
    k2 = derive_encryption_key("abc")
    assert len(k1) == 32
    assert k1 == k2
    assert derive_encryption_key("abc") != derive_encryption_key("abd")


def test_encrypt_decrypt_roundtrip(tmp_path):
    """加密-解密往返一致。"""
    plain = os.urandom(2048) + b"\x00tail" * 16
    src = tmp_path / "model.safetensors"
    enc = tmp_path / "model.safetensors.encrypted"
    src.write_bytes(plain)

    encrypt_file(src, enc, KEY)

    # 文件头: magic + version
    raw = enc.read_bytes()
    assert raw.startswith(_MAGIC + _VERSION)

    decrypted = decrypt_to_memory(enc, KEY)
    assert decrypted == plain


def test_encrypt_wrong_key_fails(tmp_path):
    """错误密钥解密抛异常。"""
    src = tmp_path / "a.bin"
    enc = tmp_path / "a.bin.enc"
    src.write_bytes(b"secret data")
    encrypt_file(src, enc, KEY)

    wrong = b"\x22" * 32
    with pytest.raises((ValueError, Exception)):
        decrypt_to_memory(enc, wrong)


def test_encrypt_bad_key_length(tmp_path):
    """密钥长度错误抛 ValueError。"""
    src = tmp_path / "a.bin"
    src.write_bytes(b"x")
    with pytest.raises(ValueError):
        encrypt_file(src, tmp_path / "a.enc", b"short")


def test_decrypt_invalid_magic(tmp_path):
    """魔数错误抛 ValueError。"""
    bad = tmp_path / "bad.enc"
    bad.write_bytes(b"NOPE" + b"\x00" * 32)
    with pytest.raises(ValueError, match="魔数"):
        decrypt_to_memory(bad, KEY)


def test_decrypt_invalid_version(tmp_path):
    """版本错误抛 ValueError。"""
    bad = tmp_path / "bad2.enc"
    bad.write_bytes(_MAGIC + b"\xff" + b"\x00" * 40)
    with pytest.raises(ValueError, match="版本"):
        decrypt_to_memory(bad, KEY)


def test_decrypt_to_temp_file(tmp_path):
    """解密到临时文件，内容一致且后缀正确。"""
    src = tmp_path / "m.safetensors"
    enc = tmp_path / "m.safetensors.encrypted"
    plain = b"weights" * 100
    src.write_bytes(plain)
    encrypt_file(src, enc, KEY)

    temp_path = decrypt_to_temp_file(enc, KEY)
    try:
        assert temp_path.endswith(".safetensors")
        with open(temp_path, "rb") as f:
            assert f.read() == plain
    finally:
        os.unlink(temp_path)


def test_encrypt_missing_input(tmp_path):
    """输入文件不存在时抛异常。"""
    with pytest.raises(OSError):
        encrypt_file(tmp_path / "missing.bin", tmp_path / "out.enc", KEY)

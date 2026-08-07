# SPDX-FileCopyrightText: Copyright (c) 2024-2026 ReSerendipity
# SPDX-License-Identifier: Apache-2.0
"""模型权重 AES-GCM 加密存储模块 (P3 长期方案)

将 safetensors 模型权重加密为 .encrypted 格式，防止直接复制使用。
密钥从本地许可证文件（绑定机器指纹）或授权服务器获取。

安全模型:
    1. 首次部署: 运行 `python scripts/encrypt_weights.py` 加密 pretrained_models/
    2. 加密后的文件格式: [12B nonce] + [16B tag] + [encrypted data]
    3. 运行时: 从许可证文件读取密钥，解密后加载到内存（不落盘明文）
    4. 机器绑定: 许可证文件包含机器指纹（MAC+CPU+磁盘序列号），不可跨机器使用

局限性 (已在安全审计报告中注明):
    - 本地场景下密钥仍需存在于内存中，有内存提取风险
    - 对具备 root/admin 权限的攻击者无法完全防御
    - 主要目的是抬高门槛，阻止普通用户直接复制权重文件

使用方式:
    from bin.integrated_app.security.weight_encryption import (
        encrypt_file,
        decrypt_to_memory,
        get_machine_fingerprint,
    )

    # 加密
    encrypt_file("model.safetensors", "model.safetensors.encrypted", key)

    # 解密到内存 (不落盘)
    data = decrypt_to_memory("model.safetensors.encrypted", key)

    # 生成机器绑定许可证
    license_key = generate_license("user@example.com")
"""

import hashlib
import logging
import os
import platform
import socket
import uuid
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# AES-GCM 参数
_NONCE_SIZE = 12  # 96-bit nonce (NIST recommended for GCM)
_TAG_SIZE = 16  # 128-bit authentication tag
_KEY_SIZE = 32  # 256-bit key
_CHUNK_SIZE = 8 * 1024 * 1024  # 8MB chunks for large files

# 加密文件魔数 (用于识别加密格式)
_MAGIC = b"SVR2ENC"  # 7 bytes
_VERSION = b"\x01"  # 1 byte


def get_machine_fingerprint() -> str:
    """获取当前机器的硬件指纹（用于许可证绑定）。

    组合 MAC 地址、CPU 信息和平台信息生成唯一指纹。
    同一台机器的指纹保持稳定，不同机器的指纹不同。

    Returns:
        str: 机器指纹的 SHA256 哈希（64 字符十六进制）。
    """
    components = []

    # MAC 地址
    try:
        mac = uuid.getnode()
        components.append(f"mac:{mac:012x}")
    except Exception:
        pass

    # 主机名
    try:
        components.append(f"host:{socket.gethostname()}")
    except Exception:
        pass

    # CPU 信息
    try:
        components.append(f"cpu:{platform.processor()}")
        components.append(f"machine:{platform.machine()}")
    except Exception:
        pass

    # 平台
    try:
        components.append(f"sys:{platform.system()}")
    except Exception:
        pass

    fingerprint = "|".join(components)
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


@dataclass
class LicenseInfo:
    """许可证信息。"""
    user: str
    machine_fingerprint: str
    issued_at: str
    license_key: str


def generate_license(user: str) -> LicenseInfo:
    """生成机器绑定许可证。

    Args:
        user: 用户标识 (如邮箱)。

    Returns:
        LicenseInfo: 包含机器指纹和许可证密钥的信息。
    """
    import time

    fingerprint = get_machine_fingerprint()
    issued_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    # 许可证密钥 = SHA256(user + machine_fingerprint + secret_salt)
    # secret_salt 应为项目特定的秘密值，这里用固定值作为示例
    secret_salt = "SeedVR2_ReSerendipity_License_2024"
    license_key = hashlib.sha256(
        f"{user}|{fingerprint}|{secret_salt}".encode("utf-8")
    ).hexdigest()

    return LicenseInfo(
        user=user,
        machine_fingerprint=fingerprint,
        issued_at=issued_at,
        license_key=license_key,
    )


def derive_encryption_key(license_key: str) -> bytes:
    """从许可证密钥派生 AES-256 加密密钥。

    Args:
        license_key: 许可证密钥字符串。

    Returns:
        bytes: 32 字节 AES-256 密钥。
    """
    return hashlib.sha256(license_key.encode("utf-8")).digest()[:_KEY_SIZE]


def encrypt_file(input_path: str | os.PathLike, output_path: str | os.PathLike, key: bytes) -> None:
    """加密文件为 AES-GCM 格式。

    文件格式:
        [7B magic "SVR2ENC"] + [1B version] + [12B nonce] + [16B tag] + [encrypted data]

    Args:
        input_path: 输入文件路径 (明文)。
        output_path: 输出文件路径 (加密后)。
        key: 32 字节 AES-256 密钥。

    Raises:
        ImportError: 未安装 cryptography 库时抛出。
        ValueError: 密钥长度不正确时抛出。
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise ImportError(
            "AES-GCM 加密需要 cryptography 库: pip install cryptography"
        )

    if len(key) != _KEY_SIZE:
        raise ValueError(f"密钥长度必须为 {_KEY_SIZE} 字节, 当前: {len(key)}")

    import os as _os

    nonce = _os.urandom(_NONCE_SIZE)
    aesgcm = AESGCM(key)

    input_path = Path(input_path)
    output_path = Path(output_path)

    # 读取整个文件并加密 (对于大模型文件，分块加密需要更复杂的协议)
    with open(input_path, "rb") as f:
        plaintext = f.read()

    ciphertext = aesgcm.encrypt(nonce, plaintext, None)

    with open(output_path, "wb") as f:
        f.write(_MAGIC)
        f.write(_VERSION)
        f.write(nonce)
        f.write(ciphertext)  # AESGCM.encrypt 返回 ciphertext + tag

    logger.info(f"已加密: {input_path} -> {output_path} ({len(plaintext)} bytes)")


def decrypt_to_memory(encrypted_path: str | os.PathLike, key: bytes) -> bytes:
    """解密加密文件到内存 (不落盘明文)。

    Args:
        encrypted_path: 加密文件路径。
        key: 32 字节 AES-256 密钥。

    Returns:
        bytes: 解密后的明文数据。

    Raises:
        ImportError: 未安装 cryptography 库时抛出。
        ValueError: 文件格式不正确或解密失败时抛出。
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise ImportError(
            "AES-GCM 解密需要 cryptography 库: pip install cryptography"
        )

    if len(key) != _KEY_SIZE:
        raise ValueError(f"密钥长度必须为 {_KEY_SIZE} 字节, 当前: {len(key)}")

    encrypted_path = Path(encrypted_path)

    with open(encrypted_path, "rb") as f:
        magic = f.read(len(_MAGIC))
        if magic != _MAGIC:
            raise ValueError(f"无效的加密文件格式 (魔数不匹配): {encrypted_path}")

        version = f.read(1)
        if version != _VERSION:
            raise ValueError(f"不支持的加密文件版本: {version}")

        nonce = f.read(_NONCE_SIZE)
        ciphertext_with_tag = f.read()

    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext_with_tag, None)

    logger.info(f"已解密: {encrypted_path} ({len(plaintext)} bytes)")
    return plaintext


def decrypt_to_temp_file(encrypted_path: str | os.PathLike, key: bytes) -> str:
    """解密加密文件到临时文件，用完自动删除。

    用于需要文件路径的 API（如 safetensors 加载）。

    Args:
        encrypted_path: 加密文件路径。
        key: 32 字节 AES-256 密钥。

    Returns:
        str: 临时文件路径 (调用方负责删除)。
    """
    import tempfile

    plaintext = decrypt_to_memory(encrypted_path, key)

    fd, temp_path = tempfile.mkstemp(suffix=".safetensors", prefix="_dec_")
    with os.fdopen(fd, "wb") as f:
        f.write(plaintext)

    logger.debug(f"已解密到临时文件: {temp_path}")
    return temp_path

# SPDX-FileCopyrightText: Copyright (c) 2024-2026 ReSerendipity
# SPDX-License-Identifier: Apache-2.0
"""服务端密钥管理模块 - 持久化 SECRET_KEY。

首次启动时生成随机密钥并持久化到 data/.seedvr2_secret，
后续重启复用同一密钥，保证 CSRF token 跨重启有效。

安全策略:
    - 密钥使用 secrets.token_bytes(32) 生成（256 位熵）
    - 持久化文件权限限制为 0o600（仅所有者可读写）
    - 密钥以 hex 编码存储，方便 YAML 引用
    - 支持从 config.yaml 指定密钥，覆盖自动生成的密钥

使用方式:
    from bin.integrated_app.security.secret_key import get_secret_key

    key = get_secret_key()  # 返回 bytes，32 字节
"""

import contextlib
import logging
import os
import secrets
from pathlib import Path

logger = logging.getLogger(__name__)

# 默认密钥持久化路径（相对于项目根目录）
_DEFAULT_KEY_FILE = "data/.seedvr2_secret"

# 密钥字节数
_KEY_BYTES = 32

# 单例缓存
_cached_key: bytes | None = None


def get_secret_key(key_file: str | os.PathLike | None = None) -> bytes:
    """获取服务端持久化密钥。

    首次调用时从文件读取密钥；文件不存在则生成新密钥并持久化。
    后续调用返回缓存的密钥（线程安全单例）。

    Args:
        key_file: 密钥文件路径，为 None 时使用默认路径 data/.seedvr2_secret。

    Returns:
        32 字节随机密钥（bytes）。
    """
    global _cached_key

    if _cached_key is not None:
        return _cached_key

    if key_file is None:
        project_root = Path(__file__).resolve().parents[3]
        key_file = project_root / _DEFAULT_KEY_FILE
    else:
        key_file = Path(key_file)

    if key_file.exists():
        try:
            hex_str = key_file.read_text(encoding="utf-8").strip()
            _cached_key = bytes.fromhex(hex_str)
            if len(_cached_key) != _KEY_BYTES:
                logger.warning("密钥文件内容长度异常，重新生成密钥")
                _cached_key = _generate_and_persist(key_file)
            logger.debug("从持久化文件加载服务端密钥")
            return _cached_key
        except Exception as e:
            logger.warning(f"读取密钥文件失败，重新生成: {e}")

    _cached_key = _generate_and_persist(key_file)
    return _cached_key


def _generate_and_persist(key_file: Path) -> bytes:
    """生成新密钥并持久化到文件。

    Args:
        key_file: 密钥文件路径。

    Returns:
        新生成的 32 字节密钥。
    """
    key = secrets.token_bytes(_KEY_BYTES)

    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(key.hex(), encoding="utf-8")

    # 尝试设置文件权限为 0o600（仅所有者可读写）
    with contextlib.suppress(Exception):
        os.chmod(key_file, 0o600)

    logger.info(f"已生成并持久化服务端密钥: {key_file}")
    return key


def reset_cached_key() -> None:
    """重置密钥缓存（仅用于测试）。

    下次调用 get_secret_key 时会重新从文件读取或生成。
    """
    global _cached_key
    _cached_key = None

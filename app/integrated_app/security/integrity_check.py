# SPDX-FileCopyrightText: Copyright (c) 2024-2026 ReSerendipity
# SPDX-License-Identifier: Apache-2.0
"""模型权重 SHA256 完整性校验模块

在模型加载前验证 safetensors / .pt 文件的 SHA256 哈希值，
防止权重投毒攻击 (CWE-353)。

使用方式:
    from app.integrated_app.security.integrity_check import verify_checkpoint

    verify_checkpoint(
        path="model/seedvr2_ema_3b_fp16.safetensors",
        expected_hash="abc123...",  # 从 config.yaml 读取
        purpose="DiT-3B-FP16",
    )

配置示例 (config.yaml):
    model:
      models:
        3b:
          sha256_fp16: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
          sha256_fp8: "..."
          sha256_vae: "..."
"""

import hashlib
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# 大文件分块读取大小 (8MB chunks, balances memory vs speed)
_CHUNK_SIZE = 8 * 1024 * 1024


def compute_sha256(filepath: str | os.PathLike) -> str:
    """计算文件的 SHA256 哈希值。

    使用分块读取策略，支持大文件（GB 级模型权重）而不占用过多内存。

    Args:
        filepath: 文件路径。

    Returns:
        str: 十六进制 SHA256 哈希字符串（64 字符）。

    Raises:
        FileNotFoundError: 文件不存在时抛出。
        OSError: 文件读取失败时抛出。
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {filepath}")

    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_CHUNK_SIZE)
            if not chunk:
                break
            sha256.update(chunk)
    return sha256.hexdigest()


def verify_checkpoint(
    path: str | os.PathLike,
    expected_hash: str | None,
    *,
    purpose: str = "model",
    skip_if_empty: bool = True,
) -> bool:
    """验证模型文件 SHA256 哈希值，防止权重投毒。

    安全策略:
        1. 如果 expected_hash 为空或 None，且 skip_if_empty=True，跳过校验并记录调试日志
           （向后兼容：未配置哈希的模型仍可加载，但会在日志中提示）
        2. 如果 expected_hash 非空，计算文件实际哈希并比对
        3. 哈希不匹配时记录严重安全警告并返回 False
        4. 哈希匹配时记录信息日志

    Args:
        path: 模型文件路径。
        expected_hash: 期望的 SHA256 哈希值（64 字符十六进制字符串）。
        purpose: 描述性标签（如 "DiT-3B-FP16"），用于日志消息。
        skip_if_empty: expected_hash 为空时是否跳过校验（默认 True，向后兼容）。

    Returns:
        bool: True 表示校验通过（或跳过），False 表示校验失败。

    Note:
        CWE-353: 修改后的运行时文件检测。通过在加载前验证哈希，
        防止攻击者替换模型权重文件实施投毒攻击。
    """
    if not expected_hash or not expected_hash.strip():
        if skip_if_empty:
            logger.debug(
                f"[INTEGRITY] {purpose}: 未配置 SHA256 哈希，跳过校验 ({path}). "
                f"建议在 config.yaml 中配置 sha256 字段以启用完整性校验。"
            )
            return True
        else:
            logger.error(f"[INTEGRITY] {purpose}: 期望哈希为空但 skip_if_empty=False，拒绝加载")
            return False

    expected_hash = expected_hash.strip().lower()

    if not Path(path).exists():
        logger.error(f"[INTEGRITY] {purpose}: 文件不存在: {path}")
        return False

    logger.info(f"[INTEGRITY] 正在校验 {purpose} SHA256 完整性: {path}")
    actual_hash = compute_sha256(path)

    if actual_hash == expected_hash:
        logger.info(f"[INTEGRITY] {purpose}: SHA256 校验通过 ✓")
        return True
    else:
        logger.error(
            f"[SECURITY CRITICAL] {purpose}: SHA256 校验失败！\n"
            f"    文件: {path}\n"
            f"    期望: {expected_hash}\n"
            f"    实际: {actual_hash}\n"
            f"    该文件可能已被篡改或投毒 (CWE-353)。拒绝加载此文件。"
        )
        return False


def verify_model_files(
    pretrained_dir: str | os.PathLike,
    model_cfg: dict,
    precision: str = "fp16",
) -> dict[str, bool]:
    """批量验证模型配置中所有文件的 SHA256 完整性。

    检查 DiT checkpoint、VAE checkpoint、文本嵌入文件的哈希值。
    任一文件校验失败不会中断其他文件的校验，但会在返回结果中标记。

    Args:
        pretrained_dir: 预训练模型根目录路径。
        model_cfg: 单个模型的配置字典（config.yaml 中 model.models.<size>）。
        precision: 精度标识 ("fp16" 或 "fp8")。

    Returns:
        dict[str, bool]: 文件用途到校验结果的映射，True 表示通过。
    """
    results: dict[str, bool] = {}
    pretrained_path = Path(pretrained_dir)

    # DiT checkpoint
    checkpoint_key = f"checkpoint_{precision}"
    checkpoint_name = model_cfg.get(checkpoint_key) or model_cfg.get("checkpoint_fp16", "")
    if checkpoint_name:
        checkpoint_path = pretrained_path / checkpoint_name
        hash_key = f"sha256_{precision}"
        expected = model_cfg.get(hash_key, "")
        results[f"DiT-{precision}"] = verify_checkpoint(
            checkpoint_path, expected, purpose=f"DiT-{precision}", skip_if_empty=True
        )

    # VAE checkpoint
    vae_name = model_cfg.get("vae_checkpoint", "")
    if vae_name:
        vae_path = pretrained_path / vae_name
        vae_expected = model_cfg.get("sha256_vae", "")
        results["VAE"] = verify_checkpoint(vae_path, vae_expected, purpose="VAE", skip_if_empty=True)

    # Text embeddings
    for emb_key, emb_name in [("pos_emb", model_cfg.get("pos_emb", "")), ("neg_emb", model_cfg.get("neg_emb", ""))]:
        if emb_name:
            emb_path = pretrained_path / emb_name
            emb_expected = model_cfg.get(f"sha256_{emb_key}", "")
            results[emb_key] = verify_checkpoint(emb_path, emb_expected, purpose=emb_key, skip_if_empty=True)

    # Summary
    failed = [k for k, v in results.items() if not v]
    if failed:
        logger.error(f"[SECURITY] 模型完整性校验失败 ({len(failed)}/{len(results)} 文件): {', '.join(failed)}")
    elif any(results.values()):
        logger.info(f"[INTEGRITY] 所有已配置哈希的模型文件校验通过 ({sum(results.values())}/{len(results)})")

    return results

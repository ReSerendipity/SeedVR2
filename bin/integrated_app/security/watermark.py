# SPDX-FileCopyrightText: Copyright (c) 2024-2026 ReSerendipity
# SPDX-License-Identifier: Apache-2.0
"""不可感知数字水印模块 (DCT 频域水印)

在推理输出图像/视频帧中嵌入不可感知的 DCT 频域水印，
即使所有 UI/代码标识被移除，仍可从输出内容中提取归属水印，
是唯一可举证的侵权溯源手段。

水印信息: "SeedVR2_ReSerendipity" + 生成时间戳
嵌入策略: 在图像的 DCT 中频系数中嵌入二进制水印序列，
          利用人类视觉对中频不敏感的特性实现不可感知性。

安全特性:
    - 不可感知: 水印强度极低 (alpha=0.01)，PSNR > 42dB
    - 鲁棒性: DCT 中频系数对 JPEG 压缩、缩放、裁剪有一定鲁棒性
    - 可溯源: 提取水印可验证 "SeedVR2" 归属标识
    - 不可移除: 攻击者不知道水印嵌入位置和强度，难以完全去除

使用方式:
    from bin.integrated_app.security.watermark import embed_watermark

    watermarked_np = embed_watermark(image_np)  # 在保存前调用
"""

import hashlib
import hmac
import logging
import os
import time
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# 水印品牌标识
_WATERMARK_BRAND = "SeedVR2_ReSerendipity"

# 水印嵌入强度 (越小越不可感知，越大越鲁棒)
# 对于 QIM 量化: quant_step = 1.0 / alpha
# alpha=0.5 -> quant_step=2, 对 8bit 图像最大修改量 ~1, PSNR > 48dB
_WATERMARK_ALPHA = 0.5

# ===== 密钥签名配置（v2）=====
# 载荷格式: "<brand>_<timestamp>|<hmac-sha256 hex>"
# 无密钥时嵌入旧格式未签名载荷（兼容旧版验证）；有密钥时嵌入签名载荷，
# 未持有密钥者无法伪造可通过验证的水印，溯源举证以签名验证为准。
_WATERMARK_KEY_ENV = "SEEDVR2_WATERMARK_KEY"
_WATERMARK_KEY_FILE = Path(__file__).resolve().parent.parent.parent.parent / ".watermark_key"
_HMAC_SEPARATOR = "|"

# DCT 块大小
_BLOCK_SIZE = 8

# 水印嵌入的中频系数位置 (在 8x8 DCT 块中)
# 选择中频区域 (4-6 行/列) 作为嵌入位置，平衡不可感知性和鲁棒性
_EMBED_POSITIONS = [
    (4, 5),
    (5, 4),
    (5, 6),
    (6, 5),
    (4, 6),
    (6, 4),
    (5, 5),
    (6, 6),
]


def _text_to_bits(text: str) -> np.ndarray:
    """将文本转换为二进制位序列。

    Args:
        text: 待嵌入的文本字符串。

    Returns:
        np.ndarray: 二进制位数组 (0 和 1)。
    """
    data = text.encode("utf-8")
    bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8))
    return bits


def _bits_to_text(bits: np.ndarray) -> str:
    """将二进制位序列转换回文本。

    Args:
        bits: 二进制位数组。

    Returns:
        str: 解码后的文本字符串。
    """
    # 确保长度是 8 的倍数
    length = (len(bits) // 8) * 8
    if length == 0:
        return ""
    packed = np.packbits(bits[:length])
    try:
        return packed.tobytes().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _generate_watermark_payload() -> str:
    """生成包含品牌标识和时间戳的水印载荷。

    Returns:
        str: 格式为 "SeedVR2_ReSerendipity_YYYYMMDDHHMMSS" 的水印字符串。
    """
    timestamp = time.strftime("%Y%m%d%H%M%S")
    return f"{_WATERMARK_BRAND}_{timestamp}"


def _load_secret_key() -> bytes | None:
    """加载水印签名密钥（环境变量优先，其次项目根 .watermark_key 文件）。"""
    env_key = os.environ.get(_WATERMARK_KEY_ENV, "").strip()
    if env_key:
        return env_key.encode("utf-8")
    try:
        if _WATERMARK_KEY_FILE.exists():
            key = _WATERMARK_KEY_FILE.read_text(encoding="utf-8").strip()
            if key:
                return key.encode("utf-8")
    except Exception as e:
        logger.debug(f"读取水印密钥文件失败: {e}")
    return None


def _sign_payload(payload: str, key: bytes) -> str:
    """对水印载荷附加 HMAC-SHA256 签名。"""
    digest = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}{_HMAC_SEPARATOR}{digest}"


def _verify_signature(signed_payload: str, key: bytes) -> str | None:
    """验证签名载荷，返回原始载荷；签名缺失或无效返回 None。

    解析规则：首个分隔符前的部分为载荷，其后固定 64 位 hex 为摘要；
    提取噪声不会影响解析（分隔符后的多余内容被忽略）。
    """
    sep_pos = signed_payload.find(_HMAC_SEPARATOR)
    if sep_pos < 0:
        return None
    payload = signed_payload[:sep_pos]
    digest = signed_payload[sep_pos + 1 : sep_pos + 1 + 64]
    if len(digest) != 64:
        return None
    expected = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if hmac.compare_digest(expected, digest):
        return payload
    return None


def _dct_1d(arr: np.ndarray) -> np.ndarray:
    """一维 DCT 变换 (Type-II)。

    使用矩阵乘法实现，避免依赖 scipy。
    """
    size = arr.shape[-1]
    n = np.arange(size)
    k = n.reshape(-1, 1)
    dct_matrix = np.cos(np.pi * (2 * n + 1) * k / (2 * size)) * np.sqrt(2.0 / size)
    dct_matrix[0] *= 1.0 / np.sqrt(2)
    return arr @ dct_matrix.T


def _idct_1d(arr: np.ndarray) -> np.ndarray:
    """一维逆 DCT 变换 (Type-II 的逆)。

    使用矩阵乘法实现。
    """
    size = arr.shape[-1]
    n = np.arange(size)
    k = n.reshape(-1, 1)
    idct_matrix = np.cos(np.pi * (2 * k + 1) * n / (2 * size)) * np.sqrt(2.0 / size)
    idct_matrix[:, 0] *= 1.0 / np.sqrt(2)
    return arr @ idct_matrix.T


def _dct_2d_block(block: np.ndarray) -> np.ndarray:
    """二维 DCT 变换 (行 DCT 后列 DCT)。

    Args:
        block: 2D 数组 (通常 8x8)。

    Returns:
        np.ndarray: DCT 变换后的系数矩阵。
    """
    return _dct_1d(_dct_1d(block.T).T)


def _idct_2d_block(block: np.ndarray) -> np.ndarray:
    """二维逆 DCT 变换。

    Args:
        block: DCT 系数矩阵。

    Returns:
        np.ndarray: 空间域图像块。
    """
    return _idct_1d(_idct_1d(block.T).T)


def embed_watermark(
    image_np: np.ndarray,
    *,
    payload: str | None = None,
    alpha: float = _WATERMARK_ALPHA,
) -> np.ndarray:
    """在图像中嵌入不可感知 DCT 频域水印。

    水印嵌入流程:
        1. 生成水印载荷 (品牌标识 + 时间戳)
        2. 将载荷转换为二进制位序列
        3. 对图像每个通道分 8x8 块做 DCT 变换
        4. 在中频系数中嵌入水印位 (QIM 量化索引调制)
        5. 做 IDCT 变换回空间域
        6. 裁剪到有效像素范围 [0, 255]

    Args:
        image_np: 输入图像 NumPy 数组 (H x W x C, uint8)。
        payload: 自定义水印载荷，None 时自动生成品牌标识+时间戳。
        alpha: 水印嵌入强度，默认 0.01 (极低，不可感知)。

    Returns:
        np.ndarray: 嵌入水印后的图像 (与输入相同 shape 和 dtype)。

    Note:
        - 水印强度极低，PSNR > 42dB，肉眼不可感知
        - 对 JPEG 压缩、缩放等常见操作有一定鲁棒性
        - 即使 UI/代码标识全部被移除，输出图像仍可提取 "SeedVR2" 归属
    """
    if image_np is None or image_np.size == 0:
        return image_np

    if payload is None:
        payload = _generate_watermark_payload()
    key = _load_secret_key()
    if key is not None and _HMAC_SEPARATOR not in payload:
        payload = _sign_payload(payload, key)
    else:
        logger.debug(
            "未配置水印签名密钥，将嵌入未签名水印（不可证伪归属）。" "请运行 scripts/init_watermark_key.py 生成密钥"
        )

    bits = _text_to_bits(payload)
    if len(bits) == 0:
        return image_np

    # 转为 float 处理
    result = image_np.astype(np.float64).copy()
    h, w = result.shape[:2]
    if result.ndim == 2:
        result = result[:, :, np.newaxis]

    # 只在第一个通道嵌入水印 (减少视觉影响)
    channel_data = result[:, :, 0]

    bit_idx = 0
    blocks_h = h // _BLOCK_SIZE
    blocks_w = w // _BLOCK_SIZE

    for bi in range(blocks_h):
        for bj in range(blocks_w):
            if bit_idx >= len(bits):
                break

            # 提取 8x8 块
            y0 = bi * _BLOCK_SIZE
            x0 = bj * _BLOCK_SIZE
            block = channel_data[y0 : y0 + _BLOCK_SIZE, x0 : x0 + _BLOCK_SIZE].copy()

            # DCT 变换
            dct_block = _dct_2d_block(block)

            # 在中频位置嵌入水印位 (QIM: Quantization Index Modulation)
            # 每个块嵌入 1 位水印
            bit = bits[bit_idx]
            # 量化步长
            quant_step = 1.0 / alpha

            for py, px in _EMBED_POSITIONS:
                coeff = dct_block[py, px]
                if bit == 1:
                    # 量化到奇数倍步长
                    quantized = round(coeff / quant_step)
                    if quantized % 2 == 0:
                        quantized += 1
                else:
                    # 量化到偶数倍步长
                    quantized = round(coeff / quant_step)
                    if quantized % 2 == 1:
                        quantized += 1
                dct_block[py, px] = quantized * quant_step

            # IDCT 变换回空间域
            watermarked_block = _idct_2d_block(dct_block)
            channel_data[y0 : y0 + _BLOCK_SIZE, x0 : x0 + _BLOCK_SIZE] = watermarked_block

            bit_idx += 1

    result[:, :, 0] = channel_data

    # 裁剪到有效范围并恢复 dtype
    result = np.clip(result, 0, 255).astype(image_np.dtype)
    if image_np.ndim == 2:
        result = result[:, :, 0]

    logger.debug(f"水印已嵌入: payload='{payload[:30]}...', {bit_idx}/{len(bits)} 位已写入")
    return result


def extract_watermark(
    image_np: np.ndarray,
    *,
    expected_length: int = 256,
    alpha: float = _WATERMARK_ALPHA,
) -> str:
    """从图像中提取 DCT 频域水印。

    用于验证输出图像是否包含 SeedVR2 归属水印。

    Args:
        image_np: 待检测的图像 NumPy 数组 (H x W x C, uint8)。
        expected_length: 期望提取的最大位数。
        alpha: 水印强度 (需与嵌入时一致)。

    Returns:
        str: 提取到的水印文本。如果包含 "SeedVR2" 则确认归属。
    """
    if image_np is None or image_np.size == 0:
        return ""

    data = image_np.astype(np.float64)
    if data.ndim == 2:
        data = data[:, :, np.newaxis]

    channel_data = data[:, :, 0]
    h, w = channel_data.shape

    bits: list[int] = []
    blocks_h = h // _BLOCK_SIZE
    blocks_w = w // _BLOCK_SIZE
    quant_step = 1.0 / alpha

    for bi in range(blocks_h):
        for bj in range(blocks_w):
            if len(bits) >= expected_length:
                break

            y0 = bi * _BLOCK_SIZE
            x0 = bj * _BLOCK_SIZE
            block = channel_data[y0 : y0 + _BLOCK_SIZE, x0 : x0 + _BLOCK_SIZE]
            dct_block = _dct_2d_block(block)

            # 从中频位置提取水印位
            votes = []
            for py, px in _EMBED_POSITIONS:
                coeff = dct_block[py, px]
                quantized = round(coeff / quant_step)
                votes.append(quantized % 2)

            # 多数投票确定水印位
            bit = 1 if sum(votes) > len(votes) // 2 else 0
            bits.append(bit)

    return _bits_to_text(np.array(bits, dtype=np.uint8))


def verify_watermark(image_np: np.ndarray, *, expected_length: int = 2048) -> bool:
    """验证图像是否包含可信的 SeedVR2 归属水印（v2 签名验证）。

    - 配置了密钥时（推荐）：严格验证 HMAC 签名，仅持有密钥嵌入的水印通过；
      旧版未签名水印将验证失败（无法证明真伪）。
    - 未配置密钥时：退化为弱检测（品牌字符串包含检查），仅作参考。

    Args:
        image_np: 待验证的图像。
        expected_length: 提取位数上限（签名载荷较长，默认 2048 bit）。

    Returns:
        bool: True 表示检测到可信水印。
    """
    try:
        extracted = extract_watermark(image_np, expected_length=expected_length)
        if not extracted:
            return False
        key = _load_secret_key()
        if key is not None:
            return _verify_signature(extracted, key) is not None
        return "SeedVR2" in extracted
    except Exception as e:
        logger.debug(f"水印验证失败: {e}")
        return False

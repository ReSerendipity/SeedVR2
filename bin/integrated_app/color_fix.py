"""颜色校正后处理 - LAB 颜色匹配算法

参考: https://github.com/pkuliyi2015/sd-webui-stablesr/blob/master/srmodule/colorfix.py
"""
import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def color_fix_lab(result: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """LAB 颜色匹配 - 将 result 的颜色分布对齐到 reference

    Args:
        result: 修复后的图像 (H, W, 3) RGB 格式，uint8
        reference: 原始输入图像 (H, W, 3) RGB 格式，uint8

    Returns:
        颜色校正后的图像 (H, W, 3) RGB 格式，uint8
    """
    # 确保尺寸一致
    if result.shape[:2] != reference.shape[:2]:
        reference = cv2.resize(reference, (result.shape[1], result.shape[0]))

    # 转换为 LAB 色彩空间
    result_lab = cv2.cvtColor(result, cv2.COLOR_RGB2LAB).astype(np.float32)
    reference_lab = cv2.cvtColor(reference, cv2.COLOR_RGB2LAB).astype(np.float32)

    # 对 L, A, B 通道分别进行均值方差匹配
    result_out = result_lab.copy()
    for i in range(3):
        mean_ref = reference_lab[:, :, i].mean()
        std_ref = reference_lab[:, :, i].std()
        mean_res = result_lab[:, :, i].mean()
        std_res = result_lab[:, :, i].std()

        if std_res > 0:
            result_out[:, :, i] = (result_lab[:, :, i] - mean_res) * (std_ref / std_res) + mean_ref

    # 裁剪到合法范围
    result_out = np.clip(result_out, 0, 255).astype(np.uint8)

    # 转换回 RGB
    result_rgb = cv2.cvtColor(result_out, cv2.COLOR_LAB2RGB)
    return result_rgb


def color_fix_hsv(result: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """HSV 颜色匹配 - 将 result 的颜色分布对齐到 reference

    Args:
        result: 修复后的图像 (H, W, 3) RGB 格式，uint8
        reference: 原始输入图像 (H, W, 3) RGB 格式，uint8

    Returns:
        颜色校正后的图像 (H, W, 3) RGB 格式，uint8
    """
    if result.shape[:2] != reference.shape[:2]:
        reference = cv2.resize(reference, (result.shape[1], result.shape[0]))

    result_hsv = cv2.cvtColor(result, cv2.COLOR_RGB2HSV).astype(np.float32)
    reference_hsv = cv2.cvtColor(reference, cv2.COLOR_RGB2HSV).astype(np.float32)

    result_out = result_hsv.copy()
    for i in range(3):
        mean_ref = reference_hsv[:, :, i].mean()
        std_ref = reference_hsv[:, :, i].std()
        mean_res = result_hsv[:, :, i].mean()
        std_res = result_hsv[:, :, i].std()

        if std_res > 0:
            result_out[:, :, i] = (result_hsv[:, :, i] - mean_res) * (std_ref / std_res) + mean_ref

    result_out = np.clip(result_out, 0, 255).astype(np.uint8)
    result_rgb = cv2.cvtColor(result_out, cv2.COLOR_HSV2RGB)
    return result_rgb


def color_fix_wavelet(result: np.ndarray, reference: np.ndarray, level: int = 5) -> np.ndarray:
    """小波颜色匹配 - 使用小波分解进行颜色校正

    Args:
        result: 修复后的图像 (H, W, 3) RGB 格式，uint8
        reference: 原始输入图像 (H, W, 3) RGB 格式，uint8
        level: 小波分解层数

    Returns:
        颜色校正后的图像 (H, W, 3) RGB 格式，uint8
    """
    try:
        import pywt
    except ImportError:
        logger.warning("pywt 未安装，回退到 LAB 颜色匹配")
        return color_fix_lab(result, reference)

    if result.shape[:2] != reference.shape[:2]:
        reference = cv2.resize(reference, (result.shape[1], result.shape[0]))

    result_float = result.astype(np.float32) / 255.0
    reference_float = reference.astype(np.float32) / 255.0

    result_out = np.zeros_like(result_float)

    for c in range(3):
        # 小波分解
        coeffs_res = pywt.wavedec2(result_float[:, :, c], 'haar', level=level)
        coeffs_ref = pywt.wavedec2(reference_float[:, :, c], 'haar', level=level)

        # 保留 result 的低频，使用 reference 的高频细节
        new_coeffs = [coeffs_ref[0]]  # 使用 reference 的近似系数
        for i in range(1, len(coeffs_res)):
            new_coeffs.append(coeffs_res[i])  # 使用 result 的细节系数

        # 小波重构
        result_out[:, :, c] = pywt.waverec2(new_coeffs, 'haar')

    result_out = np.clip(result_out * 255, 0, 255).astype(np.uint8)
    return result_out


def color_fix_wavelet_adaptive(result: np.ndarray, reference: np.ndarray,
                                level: int = 5, saturation_weight: float = 0.5) -> np.ndarray:
    """小波 + 自适应饱和度颜色校正

    在小波颜色重建的基础上，对饱和度进行自适应调整，保留更多原始色彩信息。

    Args:
        result: 修复后的图像 (H, W, 3) RGB 格式，uint8
        reference: 原始输入图像 (H, W, 3) RGB 格式，uint8
        level: 小波分解层数
        saturation_weight: 饱和度保留权重 (0.0=完全使用reference, 1.0=完全保留result)

    Returns:
        颜色校正后的图像 (H, W, 3) RGB 格式，uint8
    """
    # 先做小波颜色重建
    wavelet_result = color_fix_wavelet(result, reference, level)

    # 自适应饱和度调整: 在 HSV 空间混合 result 和 wavelet_result 的饱和度
    result_hsv = cv2.cvtColor(result, cv2.COLOR_RGB2HSV).astype(np.float32)
    wavelet_hsv = cv2.cvtColor(wavelet_result, cv2.COLOR_RGB2HSV).astype(np.float32)

    # 混合饱和度通道 (S 通道, index=1)
    result_hsv[:, :, 1] = (
        (1 - saturation_weight) * wavelet_hsv[:, :, 1]
        + saturation_weight * result_hsv[:, :, 1]
    )

    result_out = np.clip(result_hsv, 0, 255).astype(np.uint8)
    return cv2.cvtColor(result_out, cv2.COLOR_HSV2RGB)


def color_fix_adain(result: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """自适应实例归一化 (AdaIN) - 匹配均值和方差

    Args:
        result: 修复后的图像 (H, W, 3) RGB 格式，uint8
        reference: 原始输入图像 (H, W, 3) RGB 格式，uint8

    Returns:
        颜色校正后的图像 (H, W, 3) RGB 格式，uint8
    """
    if result.shape[:2] != reference.shape[:2]:
        reference = cv2.resize(reference, (result.shape[1], result.shape[0]))

    result_float = result.astype(np.float32) / 255.0
    reference_float = reference.astype(np.float32) / 255.0

    for c in range(3):
        mean_ref = reference_float[:, :, c].mean()
        std_ref = reference_float[:, :, c].std()
        mean_res = result_float[:, :, c].mean()
        std_res = result_float[:, :, c].std()

        if std_res > 0:
            result_float[:, :, c] = (result_float[:, :, c] - mean_res) * (std_ref / std_res) + mean_ref

    return (np.clip(result_float, 0, 1) * 255).astype(np.uint8)


def apply_color_correction(
    result: np.ndarray,
    reference: np.ndarray,
    method: str = "lab"
) -> np.ndarray:
    """应用颜色校正

    Args:
        result: 修复后的图像
        reference: 原始输入图像
        method: 校正方法 ("lab", "hsv", "wavelet", "wavelet_adaptive", "adain", "none")

    Returns:
        校正后的图像
    """
    methods = {
        "lab": color_fix_lab,
        "hsv": color_fix_hsv,
        "wavelet": color_fix_wavelet,
        "wavelet_adaptive": color_fix_wavelet_adaptive,
        "adain": color_fix_adain,
    }
    if method == "none":
        return result
    if method not in methods:
        logger.warning(f"未知的颜色校正方法: {method}，使用 LAB")
        method = "lab"
    return methods[method](result, reference)

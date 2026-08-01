"""后处理 / 颜色校正 / 质量增强模块

本模块属于 SeedVR2 视频修复项目的 AI 推理优化层，提供图像/视频修复后的
多种后处理和质量增强技术，包括小波重建、锐化、颜色保真度控制、Alpha通道处理、
EXIF元数据保留、文本区域专项修复等功能。

核心技术栈:
- OpenCV (cv2): 图像处理、滤波、几何变换
- NumPy: 数组操作与数值计算
- PyWavelets (pywt): 小波分解与重构
- Pillow (PIL): EXIF元数据读写
- EasyOCR: 文本区域检测

竞品来源:
- SCST/DiffBIR/FlashVSR/Upscale-A-Video: Wavelet 颜色校正 (P0) [已在 color_fix.py 实现]
- Upscale-A-Video/CodeFormer/Vivid-VR/STAR: AdaIN 颜色校正 (P1) [已在 color_fix.py 实现]
- DiffBIR: 小波重建后处理 (P1)
- Upscale-A-Video: 条件 VAE 解码 (P1) [已在 vae_tiled_enhance.py 实现]
- Real-ESRGAN: SRVGGNetCompact 轻量级后处理 (P1)
- waifu2x: Alpha 通道处理 (P2)
- upscayl: EXIF 元数据复制 (P2)
- Vivid-VR: 文本修复流水线 (P2)
- CodeFormer: Fidelity Weight 控制 (P2)
- clarity-upscaler: 多步放大策略 (P2)

Key Features:
- 小波重建后处理 (DiffBIR wavelet_reconstruction): 高低频融合提升锐度
- SRVGGNetCompact 轻量级后处理/锐化: Unsharp Mask/Laplacian锐化
- Alpha 通道处理: 透明通道独立处理与合成
- EXIF 元数据复制: 保留原始拍摄信息
- 文本修复流水线: EasyOCR检测 + 区域增强 + 羽化合成
- Fidelity Weight 控制: 质量-保真度平衡
- 多步放大策略: 分阶段低倍率放大避免质量下降
- 统一后处理入口: 可配置的后处理流水线
"""

import contextlib
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 小波重建后处理 (DiffBIR inspired) - P1
# ---------------------------------------------------------------------------


def wavelet_reconstruction(
    restored: np.ndarray,
    reference: np.ndarray,
    level: int = 3,
    low_freq_weight: float = 0.8,
) -> np.ndarray:
    """小波重建后处理 - 高低频融合提升锐度

    参考 DiffBIR 的 wavelet_reconstruction:
    将修复结果的高频细节与原始图像的低频信息融合，
    保留修复产生的锐利细节，同时使用原始图像的颜色基调。

    与 color_fix_wavelet 的区别:
    - color_fix_wavelet: 颜色校正，替换低频系数来自 reference
    - wavelet_reconstruction: 锐度增强，融合高频来自 restored + 低频来自 reference

    Args:
        restored: 修复后的图像 (H, W, 3) RGB, uint8
        reference: 原始输入图像 (H, W, 3) RGB, uint8
        level: 小波分解层数 (3-5)
        low_freq_weight: 低频信息权重 (0.5-0.9)

    Returns:
        增强后的图像 (H, W, 3) RGB, uint8
    """
    try:
        import pywt
    except ImportError:
        logger.warning("pywt 未安装，无法使用小波重建")
        return restored

    if restored.shape[:2] != reference.shape[:2]:
        reference = cv2.resize(reference, (restored.shape[1], restored.shape[0]))

    result_float = restored.astype(np.float32) / 255.0
    reference_float = reference.astype(np.float32) / 255.0

    result_out = np.zeros_like(result_float)

    for c in range(3):
        # 小波分解
        coeffs_res = pywt.wavedec2(result_float[:, :, c], "haar", level=level)
        coeffs_ref = pywt.wavedec2(reference_float[:, :, c], "haar", level=level)

        # 融合策略:
        # - 低频 (approximation): 使用 reference 的低频 * low_freq_weight + restored 的低频 * (1 - low_freq_weight)
        # - 高频 (details): 使用 restored 的高频 (保留修复产生的锐利细节)
        new_coeffs = [low_freq_weight * coeffs_ref[0] + (1 - low_freq_weight) * coeffs_res[0]]

        # 所有高频层来自 restored (保留修复细节)
        for i in range(1, len(coeffs_res)):
            new_coeffs.append(coeffs_res[i])

        # 小波重构
        result_out[:, :, c] = pywt.waverec2(new_coeffs, "haar")

    result_out = np.clip(result_out * 255, 0, 255).astype(np.uint8)
    return result_out


# ---------------------------------------------------------------------------
# Alpha 通道处理 (waifu2x inspired) - P2
# ---------------------------------------------------------------------------


def process_alpha_channel(
    rgb_image: np.ndarray,
    alpha_channel: np.ndarray | None = None,
    mode: str = "preserve",
) -> tuple[np.ndarray, np.ndarray | None]:
    """处理 Alpha 通道 (透明通道独立处理)

    参考 waifu2x 的 alpha_util.lua:
    对 PNG 图像的 Alpha 通道独立处理，避免 RGB 修复影响透明区域。

    Args:
        rgb_image: RGB 图像 (H, W, 3) uint8
        alpha_channel: Alpha 通道 (H, W) uint8 或 None
        mode: 处理模式 ('preserve'=保留原alpha, 'separate'=独立修复alpha)

    Returns:
        (rgb_result, alpha_result) tuple
    """
    if alpha_channel is None:
        return rgb_image, None

    if mode == "preserve":
        # 保留原始 alpha 通道不做修改
        return rgb_image, alpha_channel

    elif mode == "separate":
        # 独立修复 alpha 通道 (使用 RGB 修复结果的信息)
        # 对 alpha 通道应用与 RGB 相同的缩放
        if alpha_channel.shape[:2] != rgb_image.shape[:2]:
            alpha_channel = cv2.resize(alpha_channel, (rgb_image.shape[1], rgb_image.shape[0]))

        return rgb_image, alpha_channel

    return rgb_image, alpha_channel


def extract_alpha_from_image(image: np.ndarray) -> tuple[np.ndarray, np.ndarray | None]:
    """从 RGBA 图像中提取 RGB 和 Alpha 通道

    Args:
        image: RGBA 图像 (H, W, 4) 或 RGB 图像 (H, W, 3)

    Returns:
        (rgb, alpha) tuple
    """
    if image.ndim == 3 and image.shape[2] == 4:
        rgb = image[:, :, :3]
        alpha = image[:, :, 3]
        return rgb, alpha
    elif image.ndim == 3 and image.shape[2] == 3:
        return image, None
    else:
        return image, None


def merge_alpha_to_image(rgb: np.ndarray, alpha: np.ndarray | None) -> np.ndarray:
    """合并 RGB 和 Alpha 通道为 RGBA 图像

    Args:
        rgb: RGB 图像 (H, W, 3)
        alpha: Alpha 通道 (H, W) 或 None

    Returns:
        RGBA 图像 (H, W, 4) 或 RGB 图像 (H, W, 3)
    """
    if alpha is None:
        return rgb

    if alpha.shape[:2] != rgb.shape[:2]:
        alpha = cv2.resize(alpha, (rgb.shape[1], rgb.shape[0]))

    rgba = np.concatenate([rgb, alpha[:, :, np.newaxis]], axis=2)
    return rgba


# ---------------------------------------------------------------------------
# EXIF 元数据复制 (upscayl inspired) - P2
# ---------------------------------------------------------------------------


def copy_exif_metadata(
    source_path: str,
    target_path: str,
) -> bool:
    """复制 EXIF 元数据到输出图像

    参考 upscayl 的 copyMetadata():
    将原始图片的元数据 (EXIF, IPTC, XMP) 复制到修复后的输出图片，
    保留原始的拍摄信息、相机设置、GPS 等数据。

    Args:
        source_path: 原始图片路径
        target_path: 输出图片路径

    Returns:
        是否成功复制
    """
    try:
        from PIL import Image

        source_img = Image.open(source_path)

        # 提取 EXIF 数据
        exif_data = source_img.info.get("exif")
        if exif_data:
            target_img = Image.open(target_path)
            target_img.info["exif"] = exif_data
            target_img.save(target_path, exif=exif_data)
            logger.info(f"EXIF 元数据已复制: {source_path} -> {target_path}")
            return True
        else:
            logger.debug(f"源图像无 EXIF 数据: {source_path}")
            return False

    except ImportError:
        logger.warning("Pillow 未安装，无法复制 EXIF 元数据")
        return False
    except Exception as e:
        logger.warning(f"EXIF 复制失败: {e}")
        return False


# ---------------------------------------------------------------------------
# Fidelity Weight 控制 (CodeFormer inspired) - P2
# ---------------------------------------------------------------------------


def apply_fidelity_weight(
    restored: np.ndarray,
    original: np.ndarray,
    fidelity_weight: float = 0.7,
) -> np.ndarray:
    """Fidelity Weight 控制 - 平衡质量-保真度

    参考 CodeFormer 的 Fuse_sft_block w 参数:
    通过 fidelity_weight 参数控制修复结果与原始输入的混合比例，
    在图像质量和输入保真度之间取得平衡。

    Args:
        restored: 修复后的图像 (H, W, 3) uint8
        original: 原始输入图像 (H, W, 3) uint8
        fidelity_weight: 保真度权重 (0.0=完全使用修复结果, 1.0=完全使用原始)

    Returns:
        混合后的图像
    """
    if original.shape[:2] != restored.shape[:2]:
        original = cv2.resize(original, (restored.shape[1], restored.shape[0]))

    # 简单加权混合
    result = cv2.addWeighted(restored, 1 - fidelity_weight, original, fidelity_weight, 0)
    return result


# ---------------------------------------------------------------------------
# 多步放大策略 (clarity-upscaler inspired) - P2
# ---------------------------------------------------------------------------


@dataclass
class MultiStepUpscaleConfig:
    """多步放大策略配置

    参考 clarity-upscaler 的最多 3 次迭代放大策略:
    通过多次低倍率放大代替单次高倍率放大，避免质量下降。
    """

    # 是否启用多步放大
    enabled: bool = True
    # 目标放大倍率
    target_scale: float = 4.0
    # 单步最大放大倍率 (超过时自动分步)
    max_single_step: float = 2.0
    # 最大迭代次数
    max_iterations: int = 3


class MultiStepUpscaler:
    """多步放大策略

    参考 clarity-upscaler:
    当目标放大倍率超过 max_single_step 时，
    自动将放大任务拆分为多次低倍率放大，
    每次放大后应用颜色校正，避免单次大倍率放大导致的质量下降。

    Example:
        目标 4x 放大, max_single_step=2x -> 2x 放大 + 颹色校正 + 2x 放大 + 颹色校正
    """

    def __init__(self, config: MultiStepUpscaleConfig | None = None):
        """初始化多步放大器

        Args:
            config: 多步放大配置，为 None 时使用默认配置
        """
        self.config = config or MultiStepUpscaleConfig()

    def compute_steps(self) -> list[float]:
        """计算放大步骤

        Returns:
            每步的放大倍率列表
        """
        if not self.config.enabled:
            return [self.config.target_scale]

        target = self.config.target_scale
        max_step = self.config.max_single_step
        max_iter = self.config.max_iterations

        if target <= max_step:
            return [target]

        # 计算最优分步方案
        steps = []
        remaining = target

        for _ in range(max_iter):
            if remaining <= 1.0:
                break
            step_scale = min(max_step, remaining)
            steps.append(step_scale)
            remaining = remaining / step_scale

        # 如果还有剩余 (超过 max_iterations)
        if remaining > 1.01:
            steps.append(remaining)

        logger.info(f"多步放大: target={target}x -> steps={steps}")
        return steps

    def upscale_with_steps(
        self,
        input_path: str,
        output_path: str,
        upscale_fn: callable,
        color_fix_fn: Callable | None = None,
    ) -> str:
        """分步放大执行

        Args:
            input_path: 输入图片路径
            output_path: 最终输出路径
            upscale_fn: 放大函数 (接受 input_path, output_path, scale)
            color_fix_fn: 颹色校正函数 (可选)

        Returns:
            最终输出路径
        """
        steps = self.compute_steps()

        if len(steps) == 1:
            return upscale_fn(input_path, output_path, scale=steps[0])

        # 多步放大
        import tempfile

        temp_files = []

        current_input = input_path

        for i, step_scale in enumerate(steps):
            if i < len(steps) - 1:
                # 中间步骤: 使用临时文件
                temp_dir = tempfile.mkdtemp()
                temp_output = os.path.join(temp_dir, f"step_{i}_{step_scale}x.png")
                temp_files.append(temp_output)
            else:
                # 最后一步: 使用最终输出路径
                temp_output = output_path

            # 放大
            upscale_fn(current_input, temp_output, scale=step_scale)

            # 颹色校正 (除最后一步外)
            if color_fix_fn and i < len(steps) - 1:
                color_fix_fn(current_input, temp_output)

            current_input = temp_output

        # 清理临时文件
        for temp_file in temp_files[:-1]:
            with contextlib.suppress(OSError):
                os.remove(temp_file)

        return output_path


# ---------------------------------------------------------------------------
# 图像锐化增强 (Real-ESRGAN SRVGGNetCompact inspired) - P1
# ---------------------------------------------------------------------------


def apply_sharpening(
    image: np.ndarray,
    strength: float = 0.3,
    method: str = "unsharp_mask",
) -> np.ndarray:
    """图像锐化增强

    参考 Real-ESRGAN 的 SRVGGNetCompact 轻量级后处理:
    对修复后的图像应用锐化增强，提升细节清晰度。

    Args:
        image: 输入图像 (H, W, 3) uint8
        strength: 锐化强度 (0.0-1.0)
        method: 锐化方法 ('unsharp_mask', 'laplacian')

    Returns:
        锐化后的图像
    """
    if strength <= 0:
        return image

    image_float = image.astype(np.float32)

    if method == "unsharp_mask":
        # Unsharp Mask 锐化: 原始 - 模糊 * strength
        blurred = cv2.GaussianBlur(image_float, (0, 0), sigmaX=3)
        sharpened = image_float + strength * (image_float - blurred)

    elif method == "laplacian":
        # Laplacian 锐化
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY).astype(np.float32)
        laplacian = cv2.Laplacian(gray, cv2.CV_32F)
        # 将 laplacian 应用到每个通道
        for c in range(3):
            sharpened_channel = image_float[:, :, c] + strength * laplacian
            image_float[:, :, c] = sharpened_channel
        sharpened = image_float

    else:
        return image

    sharpened = np.clip(sharpened, 0, 255).astype(np.uint8)
    return sharpened


# ---------------------------------------------------------------------------
# 统一后处理入口
# ---------------------------------------------------------------------------


def apply_post_processing(
    restored: np.ndarray,
    reference: np.ndarray,
    config: dict | None = None,
) -> np.ndarray:
    """统一后处理入口

    根据配置依次应用所有后处理步骤。

    Args:
        restored: 修复后的图像
        reference: 原始输入图像
        config: 后处理配置

    Returns:
        处理后的图像
    """
    if config is None:
        return restored

    result = restored.copy()

    # 1. 小波重建 (可选)
    if config.get("wavelet_reconstruction", False):
        level = config.get("wavelet_level", 3)
        low_freq_weight = config.get("low_freq_weight", 0.8)
        result = wavelet_reconstruction(result, reference, level=level, low_freq_weight=low_freq_weight)

    # 2. 锐化增强 (可选)
    sharpen_strength = config.get("sharpen_strength", 0.0)
    if sharpen_strength > 0:
        result = apply_sharpening(result, strength=sharpen_strength)

    # 3. Fidelity Weight (可选)
    fidelity_weight = config.get("fidelity_weight", 0.0)
    if fidelity_weight > 0:
        result = apply_fidelity_weight(result, reference, fidelity_weight=fidelity_weight)

    return result


# ---------------------------------------------------------------------------
# 文本修复流水线 (Vivid-VR inspired) - P2
# ---------------------------------------------------------------------------


@dataclass
class TextRestorationConfig:
    """文本修复流水线配置

    参考 Vivid-VR 的 EasyOCR + Real-ESRGAN 文本检测增强策略:
    检测图像中的文本区域，对文本和背景分别进行修复增强，
    最后合成完整图像，避免文本区域在通用修复中被模糊化。

    Attributes:
        enabled: 是否启用文本修复流水线
        ocr_languages: OCR 识别语言列表
        ocr_confidence_threshold: OCR 检测置信度阈值
        text_enhance_method: 文本区域增强方法 ('sharpen', 'realesrgan', 'binary')
        background_blend_mode: 背景与文本合成模式 ('alpha', 'feather', 'hard')
        feather_radius: 羽化合成时的羽化半径 (像素)
        min_text_area: 最小文本区域面积 (像素)，低于此值忽略
    """

    enabled: bool = False
    ocr_languages: list[str] | None = None
    ocr_confidence_threshold: float = 0.5
    text_enhance_method: str = "sharpen"
    background_blend_mode: str = "feather"
    feather_radius: int = 5
    min_text_area: int = 100

    def __post_init__(self):
        if self.ocr_languages is None:
            self.ocr_languages = ["ch_sim", "en"]


class TextRestorationPipeline:
    """文本修复流水线

    参考 Vivid-VR 的 EasyOCR + Real-ESRGAN 文本检测增强策略:
    分四步完成文本区域的修复增强，避免文字在通用图像修复中被模糊化。

    四步流水线:
    1. 文本区域检测: 使用 EasyOCR 或类似方案检测图像中的文字区域
    2. 文本区域修复: 对检测到的文本区域进行增强 (锐化/超分辨率/二值化)
    3. 背景修复: 对非文字区域进行通用修复
    4. 合成: 将修复后的文字区域和背景区域合成为最终图像

    用法:
        config = TextRestorationConfig(ocr_languages=["ch_sim", "en"])
        pipeline = TextRestorationPipeline(config)
        result = pipeline.process(restored_image, original_image)
    """

    def __init__(self, config: TextRestorationConfig | None = None):
        self.config = config or TextRestorationConfig()
        self._ocr_reader = None

    def _get_ocr_reader(self):
        """延迟加载 OCR 读取器

        Returns:
            EasyOCR 读取器实例
        """
        if self._ocr_reader is not None:
            return self._ocr_reader

        try:
            import easyocr

            self._ocr_reader = easyocr.Reader(
                self.config.ocr_languages,
                gpu=False,  # 默认 CPU 模式，避免 GPU 资源争用
            )
            logger.info(f"EasyOCR 初始化: languages={self.config.ocr_languages}")
        except ImportError:
            logger.warning("easyocr 未安装，文本检测将使用简化方案")
            self._ocr_reader = None

        return self._ocr_reader

    def detect_text_regions(self, image: np.ndarray) -> list[dict]:
        """第一步: 文本区域检测

        使用 EasyOCR 或简化方案检测图像中的文字区域。

        Args:
            image: 输入图像 (H, W, 3) RGB, uint8

        Returns:
            文本区域列表，每个元素包含:
            - bbox: 边界框 [x1, y1, x2, y2]
            - text: 识别出的文本
            - confidence: 检测置信度
            - mask: 区域掩码 (可选)
        """
        reader = self._get_ocr_reader()

        if reader is not None:
            # 使用 EasyOCR 检测
            results = reader.readtext(cv2.cvtColor(image, cv2.COLOR_RGB2BGR))

            text_regions = []
            for detection in results:
                bbox_pts, text, confidence = detection

                if confidence < self.config.ocr_confidence_threshold:
                    continue

                # 将多边形边界框转换为矩形
                xs = [pt[0] for pt in bbox_pts]
                ys = [pt[1] for pt in bbox_pts]
                x1, y1 = int(min(xs)), int(min(ys))
                x2, y2 = int(max(xs)), int(max(ys))

                # 检查最小面积
                area = (x2 - x1) * (y2 - y1)
                if area < self.config.min_text_area:
                    continue

                text_regions.append(
                    {
                        "bbox": [x1, y1, x2, y2],
                        "text": text,
                        "confidence": confidence,
                    }
                )

            logger.info(f"文本检测: 找到 {len(text_regions)} 个文本区域")
            return text_regions

        else:
            # 简化方案: 使用边缘检测寻找可能包含文本的区域
            logger.info("使用简化文本检测方案 (边缘检测)")
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
            edges = cv2.Canny(gray, 50, 150)

            # 使用连通域分析查找文本候选区域
            contours, _ = cv2.findContours(
                edges,
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE,
            )

            text_regions = []
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                area = w * h

                if area < self.config.min_text_area:
                    continue

                # 文本区域通常宽高比适中
                aspect_ratio = w / max(h, 1)
                if aspect_ratio > 10 or aspect_ratio < 0.1:
                    continue

                text_regions.append(
                    {
                        "bbox": [x, y, x + w, y + h],
                        "text": "",
                        "confidence": 0.3,
                    }
                )

            logger.info(f"简化文本检测: 找到 {len(text_regions)} 个候选区域")
            return text_regions

    def enhance_text_region(
        self,
        image: np.ndarray,
        bbox: list[int],
    ) -> np.ndarray:
        """第二步: 文本区域修复

        对检测到的文本区域进行增强，提升文字清晰度。

        Args:
            image: 输入图像 (H, W, 3) RGB, uint8
            bbox: 文本区域边界框 [x1, y1, x2, y2]

        Returns:
            增强后的文本区域图像
        """
        x1, y1, x2, y2 = bbox
        # 边界保护
        h, w = image.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        text_region = image[y1:y2, x1:x2].copy()
        method = self.config.text_enhance_method

        if method == "sharpen":
            # 锐化增强: 增强文字边缘
            text_region = apply_sharpening(text_region, strength=0.5, method="unsharp_mask")

        elif method == "realesrgan":
            # Real-ESRGAN 增强: 使用超分辨率模型增强文字清晰度
            # 注意: 需要加载 Real-ESRGAN 模型，此处提供框架
            logger.info("Real-ESRGAN 文本增强 (框架，使用锐化替代)")
            text_region = apply_sharpening(text_region, strength=0.8, method="unsharp_mask")

        elif method == "binary":
            # 二值化增强: 将文本区域转为高对比度二值图
            gray = cv2.cvtColor(text_region, cv2.COLOR_RGB2GRAY)
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            text_region = cv2.cvtColor(binary, cv2.COLOR_GRAY2RGB)

        return text_region

    def enhance_background(
        self,
        image: np.ndarray,
        text_mask: np.ndarray,
    ) -> np.ndarray:
        """第三步: 背景修复

        对非文字区域进行通用修复。

        Args:
            image: 输入图像 (H, W, 3) RGB, uint8
            text_mask: 文本区域掩码 (H, W), 255=文本区域

        Returns:
            修复后的背景图像
        """
        # 背景区域: 使用通用修复结果 (已在 restored 图像中)
        # 对背景区域轻微锐化以保持一致性
        background = image.copy()

        # 仅对背景区域锐化
        bg_mask = text_mask == 0
        sharpened = apply_sharpening(background, strength=0.1, method="unsharp_mask")

        # 掩码合成: 背景区域使用锐化结果，文本区域保持原样
        for c in range(3):
            background[:, :, c] = np.where(
                bg_mask,
                sharpened[:, :, c],
                background[:, :, c],
            )

        return background

    def composite(
        self,
        text_enhanced: np.ndarray,
        background: np.ndarray,
        text_mask: np.ndarray,
    ) -> np.ndarray:
        """第四步: 合成

        将修复后的文本区域和背景区域合成为最终图像。

        Args:
            text_enhanced: 增强后的文本区域图像 (H, W, 3)
            background: 修复后的背景图像 (H, W, 3)
            text_mask: 文本区域掩码 (H, W), 255=文本区域

        Returns:
            合成后的最终图像
        """
        blend_mode = self.config.background_blend_mode

        if blend_mode == "hard":
            # 硬边界合成: 直接用掩码选择
            mask_3ch = (text_mask > 0).astype(np.uint8)[:, :, np.newaxis] * 255
            result = np.where(mask_3ch == 255, text_enhanced, background)

        elif blend_mode == "feather":
            # 羽化合成: 在文本边界进行平滑过渡
            # 对掩码进行高斯模糊实现羽化
            mask_float = (text_mask > 0).astype(np.float32)
            feathered = cv2.GaussianBlur(
                mask_float,
                (0, 0),
                sigmaX=self.config.feather_radius,
            )
            # 限制在 [0, 1]
            feathered = np.clip(feathered, 0, 1)
            alpha = feathered[:, :, np.newaxis]

            result = (alpha * text_enhanced + (1 - alpha) * background).astype(np.uint8)

        elif blend_mode == "alpha":
            # Alpha 合成: 使用掩码值作为 alpha 通道
            mask_float = text_mask.astype(np.float32) / 255.0
            alpha = mask_float[:, :, np.newaxis]
            result = (alpha * text_enhanced + (1 - alpha) * background).astype(np.uint8)

        else:
            result = background

        return result

    def process(
        self,
        restored: np.ndarray,
        original: np.ndarray,
    ) -> np.ndarray:
        """执行完整的文本修复流水线

        依次执行: 检测 -> 文本增强 -> 背景增强 -> 合成

        Args:
            restored: 修复后的图像 (H, W, 3) RGB, uint8
            original: 原始输入图像 (H, W, 3) RGB, uint8

        Returns:
            最终修复图像
        """
        if not self.config.enabled:
            return restored

        # 第一步: 文本区域检测
        text_regions = self.detect_text_regions(original)

        if not text_regions:
            logger.info("未检测到文本区域，跳过文本修复")
            return restored

        # 构建文本掩码
        h, w = restored.shape[:2]
        text_mask = np.zeros((h, w), dtype=np.uint8)

        for region in text_regions:
            x1, y1, x2, y2 = region["bbox"]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            text_mask[y1:y2, x1:x2] = 255

        # 第二步: 文本区域修复
        text_enhanced = restored.copy()
        for region in text_regions:
            bbox = region["bbox"]
            x1, y1, x2, y2 = bbox
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)

            enhanced_region = self.enhance_text_region(restored, bbox)
            text_enhanced[y1:y2, x1:x2] = enhanced_region

        # 第三步: 背景修复
        background = self.enhance_background(restored, text_mask)

        # 第四步: 合成
        result = self.composite(text_enhanced, background, text_mask)

        logger.info(
            f"文本修复流水线完成: 检测到 {len(text_regions)} 个文本区域, "
            f"增强方法={self.config.text_enhance_method}, "
            f"合成模式={self.config.background_blend_mode}"
        )
        return result

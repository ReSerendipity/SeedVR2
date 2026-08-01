# // Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# //
# // Licensed under the Apache License, Version 2.0 (the "License");
# // you may not use this file except in compliance with the License.
# // You may obtain a copy of the License at
# //
# //     http://www.apache.org/licenses/LICENSE-2.0
# //
# // Unless required by applicable law or agreed to in writing, software
# // distributed under the License is distributed on an "AS IS" BASIS,
# // WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# // See the License for the specific language governing permissions and
# // limitations under the License.

"""SeedVR2 图像区域自适应缩放变换模块。

本模块提供三种图像缩放策略：基于目标面积的等比缩放（AreaResize）、
按目标面积随机裁剪（AreaRandomCrop）以及固定比例缩放（ScaleResize），
统一支持 PIL Image 和 torch.Tensor 两种输入格式，用于视频修复模型的
数据预处理流水线。

核心技术栈:
    - PyTorch
    - torchvision.transforms.functional (图像变换)
    - PIL (Pillow，图像处理)
    - InterpolationMode (插值算法)

输入张量约定:
    - 3D Tensor: (C, H, W) 单张图像
    - 4D Tensor: (B, C, H, W) 批量图像
    - PIL Image: (W, H) 尺寸通过 size 属性获取
"""

import math
import random

import torch
from PIL import Image
from torchvision.transforms import functional as TVF
from torchvision.transforms.functional import InterpolationMode


class AreaResize:
    """按目标像素面积等比缩放图像的可调用变换类。

    变换逻辑：计算缩放因子 scale = sqrt(max_area / (height * width))，
    保持原始宽高比不变，将图像面积缩放到不超过 max_area。
    当 downsample_only=True 时，面积小于 max_area 的图像保持原尺寸不放大。

    输入输出形状:
        - PIL Image -> PIL Image（尺寸变化）
        - Tensor (C, H, W) -> Tensor (C, H', W')，H'*W' <= max_area
        - Tensor (B, C, H, W) -> Tensor (B, C, H', W')
    """

    def __init__(
        self,
        max_area: float,
        downsample_only: bool = False,
        interpolation: InterpolationMode = InterpolationMode.BICUBIC,
    ):
        """初始化 AreaResize 变换。

        Args:
            max_area: 目标最大像素面积（像素数），例如 1024*1024=1048576。
            downsample_only: 是否仅允许缩小。若为 True，当图像面积小于 max_area 时保持原尺寸。
                默认为 False。
            interpolation: 缩放使用的插值算法，默认为 InterpolationMode.BICUBIC（双三次插值）。
        """
        self.max_area = max_area
        self.downsample_only = downsample_only
        self.interpolation = interpolation

    def __call__(self, image: torch.Tensor | Image.Image) -> torch.Tensor | Image.Image:
        """执行按面积等比缩放变换。

        Args:
            image: 输入图像，支持 torch.Tensor 或 PIL.Image 类型。
                - Tensor: 形状为 (..., H, W) 的图像张量，支持 3D (C,H,W) 或 4D (B,C,H,W)
                - PIL Image: PIL 图像对象

        Returns:
            Union[torch.Tensor, Image.Image]: 缩放后的图像，类型与输入一致。
                若输入为 Tensor，输出形状为 (..., H', W')，其中 H'*W' <= max_area；
                若输入为 PIL Image，返回缩放后的 PIL Image。

        Raises:
            NotImplementedError: 当输入类型既不是 torch.Tensor 也不是 PIL.Image 时抛出。
        """
        if isinstance(image, torch.Tensor):
            height, width = image.shape[-2:]
        elif isinstance(image, Image.Image):
            width, height = image.size
        else:
            raise NotImplementedError(f"不支持的图像类型: {type(image)}")

        scale = math.sqrt(self.max_area / (height * width))

        scale = 1 if scale >= 1 and self.downsample_only else scale

        resized_height, resized_width = round(height * scale), round(width * scale)

        return TVF.resize(
            image,
            size=(resized_height, resized_width),
            interpolation=self.interpolation,
        )


class AreaRandomCrop:
    """按目标面积随机位置裁剪图像的可调用变换类。

    变换逻辑：先按目标面积和原始宽高比计算目标尺寸，若原图尺寸大于目标尺寸，
    则在随机位置裁剪出目标尺寸的区域；若原图尺寸小于目标尺寸则保持原图。
    注意：本类直接裁剪而非先缩放，实际裁剪区域面积等于 max_area。

    输入输出形状:
        - PIL Image -> PIL Image（尺寸为计算得到的 target_size）
        - Tensor (C, H, W) -> Tensor (C, th, tw)
        - Tensor (B, C, H, W) -> Tensor (B, C, th, tw)
    """

    def __init__(
        self,
        max_area: float,
    ):
        """初始化 AreaRandomCrop 变换。

        Args:
            max_area: 裁剪目标区域的像素面积（像素数）。
        """
        self.max_area = max_area

    def get_params(self, input_size: tuple[int, int], output_size: tuple[int, int]) -> tuple[int, int, int, int]:
        """生成随机裁剪的位置参数。

        根据输入尺寸和目标输出尺寸，计算随机裁剪区域的左上角坐标和尺寸。
        当输入尺寸小于等于目标尺寸时返回全图区域参数。

        Args:
            input_size: 输入图像尺寸元组 (height, width)。
            output_size: 目标输出尺寸元组 (target_height, target_width)。

        Returns:
            tuple[int, int, int, int]: 裁剪参数 (i, j, h, w)，其中：
                - i: 裁剪区域顶部坐标（行偏移）
                - j: 裁剪区域左侧坐标（列偏移）
                - h: 裁剪区域高度
                - w: 裁剪区域宽度
        """
        h, w = input_size
        th, tw = output_size
        if w <= tw and h <= th:
            return 0, 0, h, w

        i = random.randint(0, h - th)
        j = random.randint(0, w - tw)
        return i, j, th, tw

    def __call__(self, image: torch.Tensor | Image.Image) -> torch.Tensor | Image.Image:
        """执行按面积随机裁剪变换。

        根据原始宽高比和目标面积计算目标尺寸，然后调用 get_params 获取随机位置
        并执行裁剪。

        Args:
            image: 输入图像，支持 torch.Tensor 或 PIL.Image 类型。
                - Tensor: 形状为 (..., H, W) 的图像张量
                - PIL Image: PIL 图像对象

        Returns:
            Union[torch.Tensor, Image.Image]: 随机裁剪后的图像，类型与输入一致。
                裁剪区域面积约等于 max_area（受四舍五入影响）。

        Raises:
            NotImplementedError: 当输入类型既不是 torch.Tensor 也不是 PIL.Image 时抛出。
        """
        if isinstance(image, torch.Tensor):
            height, width = image.shape[-2:]
        elif isinstance(image, Image.Image):
            width, height = image.size
        else:
            raise NotImplementedError(f"不支持的图像类型: {type(image)}")

        aspect_ratio = width / height
        resized_height = math.sqrt(self.max_area / aspect_ratio)
        resized_width = aspect_ratio * resized_height

        resized_height, resized_width = round(resized_height), round(resized_width)
        i, j, h, w = self.get_params((height, width), (resized_height, resized_width))
        image = TVF.crop(image, i, j, h, w)
        return image


class ScaleResize:
    """按固定缩放比例缩放图像的可调用变换类。

    变换逻辑：对图像宽高同时乘以固定 scale 因子进行缩放。
    Tensor 输入使用 BILINEAR 插值并启用 antialias 抗锯齿；
    PIL Image 输入使用 LANCZOS 插值以获得更高质量。

    输入输出形状:
        - PIL Image -> PIL Image（尺寸为 round(H*scale) x round(W*scale)）
        - Tensor (C, H, W) -> Tensor (C, round(H*scale), round(W*scale))
        - Tensor (B, C, H, W) -> Tensor (B, C, round(H*scale), round(W*scale))
    """

    def __init__(
        self,
        scale: float,
    ):
        """初始化 ScaleResize 变换。

        Args:
            scale: 缩放比例因子，例如 0.5 表示缩小为原来的一半，2.0 表示放大两倍。
        """
        self.scale = scale

    def __call__(self, image: torch.Tensor | Image.Image) -> torch.Tensor | Image.Image:
        """执行固定比例缩放变换。

        根据输入类型自动选择插值算法和抗锯齿设置：
        - Tensor: BILINEAR 插值，4D 张量启用 antialias，3D 张量给出警告
        - PIL Image: LANCZOS 插值（高质量重采样）

        Args:
            image: 输入图像，支持 torch.Tensor 或 PIL.Image 类型。
                - Tensor: 形状为 (..., H, W) 的图像张量
                - PIL Image: PIL 图像对象

        Returns:
            Union[torch.Tensor, Image.Image]: 缩放后的图像，类型与输入一致。
                输出尺寸为 (round(H*scale), round(W*scale))。

        Raises:
            NotImplementedError: 当输入类型既不是 torch.Tensor 也不是 PIL.Image 时抛出。
        """
        if isinstance(image, torch.Tensor):
            height, width = image.shape[-2:]
            interpolation_mode = InterpolationMode.BILINEAR
            antialias = True if image.ndim == 4 else "warn"
        elif isinstance(image, Image.Image):
            width, height = image.size
            interpolation_mode = InterpolationMode.LANCZOS
            antialias = "warn"
        else:
            raise NotImplementedError(f"不支持的图像类型: {type(image)}")

        scale = self.scale

        resized_height, resized_width = round(height * scale), round(width * scale)
        image = TVF.resize(
            image,
            size=(resized_height, resized_width),
            interpolation=interpolation_mode,
            antialias=antialias,
        )
        return image

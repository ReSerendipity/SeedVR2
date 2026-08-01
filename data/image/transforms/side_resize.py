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

"""SeedVR2 图像短边缩放变换模块。

本模块提供按短边目标尺寸等比缩放图像的变换，保持原始宽高比不变。
支持仅缩小模式（downsample_only），避免小图被不必要地放大导致模糊。
是视频修复模型数据预处理中常用的尺寸控制策略。

核心技术栈:
    - PyTorch
    - torchvision.transforms.functional (TVF.resize)
    - PIL (Pillow，图像处理)
    - InterpolationMode (插值算法)

输入张量约定:
    - 3D Tensor: (C, H, W) 单张图像
    - 4D Tensor: (B, C, H, W) 批量图像
    - PIL Image: (W, H) 尺寸通过 size 属性获取
"""

import torch
from PIL import Image
from torchvision.transforms import InterpolationMode
from torchvision.transforms import functional as TVF


class SideResize:
    """按短边目标尺寸等比缩放图像的可调用变换类。

    变换逻辑：以图像较短边为基准，将短边缩放到 size 指定的像素长度，
    长边按原始宽高比等比例缩放，保持宽高比不变。
    当 downsample_only=True 时，若图像短边已小于 size，则保持原图尺寸不放大。

    输入输出形状:
        - PIL Image (W, H) -> PIL Image (W', H')，min(W', H') = size（或 min(W,H) 当 downsample_only）
        - Tensor (C, H, W) -> Tensor (C, H', W')，min(H', W') = size（或 min(H,W)）
        - Tensor (B, C, H, W) -> Tensor (B, C, H', W')
    """

    def __init__(
        self,
        size: int,
        downsample_only: bool = False,
        interpolation: InterpolationMode = InterpolationMode.BICUBIC,
    ):
        """初始化 SideResize 变换。

        Args:
            size: 短边目标像素长度，例如 512 表示将短边缩放到 512 像素。
            downsample_only: 是否仅允许缩小。若为 True，当图像短边长度已小于 size 时保持原尺寸。
                默认为 False（允许放大）。
            interpolation: 缩放使用的插值算法，默认为 InterpolationMode.BICUBIC（双三次插值）。
        """
        self.size = size
        self.downsample_only = downsample_only
        self.interpolation = interpolation

    def __call__(self, image: torch.Tensor | Image.Image) -> torch.Tensor | Image.Image:
        """执行短边等比缩放变换。

        将图像较短边缩放到目标尺寸，长边按宽高比等比例缩放。若 downsample_only=True
        且图像短边已小于目标尺寸，则保持原图不进行缩放。

        Args:
            image: 输入图像，支持 torch.Tensor 或 PIL.Image 类型。
                - Tensor: 形状为 (..., H, W) 的图像张量，支持 3D (C,H,W) 或 4D (B,C,H,W)
                - PIL Image: PIL 图像对象

        Returns:
            Union[torch.Tensor, Image.Image]: 缩放后的图像，类型与输入一致。
                输出短边长度为 size（当 downsample_only 且原图较小时保持原短边长度）。

        Raises:
            NotImplementedError: 当输入类型既不是 torch.Tensor 也不是 PIL.Image 时抛出。
        """
        if isinstance(image, torch.Tensor):
            height, width = image.shape[-2:]
        elif isinstance(image, Image.Image):
            width, height = image.size
        else:
            raise NotImplementedError(f"不支持的图像类型: {type(image)}")

        if self.downsample_only and min(width, height) < self.size:
            size = min(width, height)
        else:
            size = self.size

        return TVF.resize(image, size, self.interpolation)

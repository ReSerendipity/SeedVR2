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

"""SeedVR2 图像整除裁剪变换模块。

本模块提供将图像宽高裁剪为指定因子整数倍的中心裁剪变换，
确保图像尺寸能够被下采样因子（如 VAE 的 8x/16x 下采样）整除，
避免后续卷积、池化或 PatchEmbed 操作出现尺寸不匹配错误。

核心技术栈:
    - PyTorch
    - torchvision.transforms.functional (center_crop)
    - PIL (Pillow，图像处理)

输入张量约定:
    - 3D Tensor: (C, H, W) 单张图像
    - 4D Tensor: (B, C, H, W) 批量图像
    - PIL Image: (W, H) 尺寸通过 size 属性获取

典型应用场景:
    - VAE 编码前确保图像尺寸被 8 或 16 整除
    - Transformer PatchEmbed 前确保尺寸被 patch_size 整除
    - 多尺度特征融合前的尺寸对齐
"""

import torch
from PIL import Image
from torchvision.transforms import functional as TVF


class DivisibleCrop:
    """将图像宽高中心裁剪为指定因子整数倍的可调用变换类。

    变换逻辑：计算裁剪后的尺寸 new_h = H - (H % factor_h)，
    new_w = W - (W % factor_w)，然后执行中心裁剪。裁剪从图像四边
    均匀移除边缘像素，保留图像中心区域。

    输入输出形状:
        - PIL Image (W, H) -> PIL Image (new_w, new_h)
        - Tensor (C, H, W) -> Tensor (C, new_h, new_w)
        - Tensor (B, C, H, W) -> Tensor (B, C, new_h, new_w)
        其中 new_h % height_factor == 0, new_w % width_factor == 0
    """

    def __init__(self, factor: int | tuple[int, int]):
        """初始化 DivisibleCrop 变换。

        Args:
            factor: 整除因子。可以传入单个整数（宽高使用相同因子），
                或传入 (height_factor, width_factor) 元组分别指定高和宽的因子。
                例如 factor=8 表示宽高都需被 8 整除；factor=(8, 16) 表示高被 8 整除、宽被 16 整除。
        """
        if not isinstance(factor, tuple):
            factor = (factor, factor)

        self.height_factor, self.width_factor = factor[0], factor[1]

    def __call__(self, image: torch.Tensor | Image.Image) -> torch.Tensor | Image.Image:
        """执行整除中心裁剪变换。

        从图像中心裁剪出宽高都能被对应因子整除的最大矩形区域。

        Args:
            image: 输入图像，支持 torch.Tensor 或 PIL.Image 类型。
                - Tensor: 形状为 (..., H, W) 的图像张量，支持 3D (C,H,W) 或 4D (B,C,H,W)
                - PIL Image: PIL 图像对象

        Returns:
            Union[torch.Tensor, Image.Image]: 裁剪后的图像，类型与输入一致。
                输出高度为 H - (H % height_factor)，宽度为 W - (W % width_factor)。
                裁剪区域位于图像中心。

        Raises:
            NotImplementedError: 当输入类型既不是 torch.Tensor 也不是 PIL.Image 时抛出。
        """
        if isinstance(image, torch.Tensor):
            height, width = image.shape[-2:]
        elif isinstance(image, Image.Image):
            width, height = image.size
        else:
            raise NotImplementedError(f"不支持的图像类型: {type(image)}")

        cropped_height = height - (height % self.height_factor)
        cropped_width = width - (width % self.width_factor)

        image = TVF.center_crop(img=image, output_size=(cropped_height, cropped_width))
        return image

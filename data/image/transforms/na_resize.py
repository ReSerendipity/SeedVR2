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

"""SeedVR2 原生分辨率(Native Aspect)图像缩放变换工厂模块。

本模块提供 NaResize 工厂函数，根据指定模式统一创建不同策略的图像缩放变换组合，
是数据预处理流水线中图像尺寸归一化的统一入口。支持 area（等面积缩放）、
side（短边缩放）、square（方形缩放+中心裁剪）三种模式。

核心技术栈:
    - PyTorch
    - torchvision.transforms (Resize, CenterCrop, Compose, InterpolationMode)
    - 本项目 .area_resize.AreaResize
    - 本项目 .side_resize.SideResize

缩放模式说明:
    - area:   将图像像素面积缩放到 resolution^2，保持宽高比
    - side:   将图像短边缩放到 resolution 像素，保持宽高比
    - square: 将图像短边缩放到 resolution 后中心裁剪为 resolution x resolution 正方形
"""

from typing import Literal

from torchvision.transforms import CenterCrop, Compose, InterpolationMode, Resize

from .area_resize import AreaResize
from .side_resize import SideResize


def NaResize(
    resolution: int,
    mode: Literal["area", "side", "square"],
    downsample_only: bool,
    interpolation: InterpolationMode = InterpolationMode.BICUBIC,
) -> AreaResize | SideResize | Compose:
    """创建原生分辨率图像缩放变换的工厂函数。

    根据指定的缩放模式返回对应的变换对象（或变换组合），统一接口便于在
    配置文件中切换不同的预处理策略。

    Args:
        resolution: 目标分辨率参数，含义因模式而异：
            - area: 图像面积不超过 resolution^2 像素
            - side: 图像短边长度为 resolution 像素
            - square: 输出图像为 resolution x resolution 像素正方形
        mode: 缩放模式，支持以下三种：
            - "area":   等面积缩放，保持宽高比，调用 AreaResize
            - "side":   短边缩放，保持宽高比，调用 SideResize
            - "square": 方形缩放，先 Resize 短边再 CenterCrop，输出固定尺寸正方形
        downsample_only: 是否仅允许缩小。为 True 时，若图像尺寸已小于目标则保持原图。
            对 "square" 模式无效（square 始终强制输出固定尺寸）。
        interpolation: 缩放使用的插值算法，默认为 InterpolationMode.BICUBIC（双三次插值）。

    Returns:
        Union[AreaResize, SideResize, Compose]: 可调用的变换对象：
            - mode="area"   -> AreaResize 实例
            - mode="side"   -> SideResize 实例
            - mode="square" -> Compose([Resize, CenterCrop]) 组合变换

    Raises:
        ValueError: 当 mode 不是 "area"、"side" 或 "square" 时抛出。
    """
    if mode == "area":
        return AreaResize(
            max_area=resolution**2,
            downsample_only=downsample_only,
            interpolation=interpolation,
        )
    if mode == "side":
        return SideResize(
            size=resolution,
            downsample_only=downsample_only,
            interpolation=interpolation,
        )
    if mode == "square":
        return Compose(
            [
                Resize(
                    size=resolution,
                    interpolation=interpolation,
                ),
                CenterCrop(resolution),
            ]
        )
    raise ValueError(f"Unknown resize mode: {mode}")

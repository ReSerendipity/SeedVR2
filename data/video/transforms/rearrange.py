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

"""SeedVR2 视频帧张量重排布变换模块。

本模块基于 einops.rearrange 封装了一个可调用的变换类 Rearrange，
用于在视频数据预处理/后处理流水线中灵活重排张量维度，支持视频帧的
维度合并、拆分、转置等操作。可直接作为 torchvision.transforms 流水线
中的一个变换步骤使用。

核心技术栈:
    - PyTorch
    - einops (张量维度重排)

典型应用场景:
    - 将 (B, T, C, H, W) 视频张量合并为 (B*T, C, H, W) 批量图像
    - 将通道维和时间维拆分/合并以适配不同模型输入格式
    - 空间分块（patch）前的维度重排
"""

import torch
from einops import rearrange


class Rearrange:
    """基于 einops 模式字符串的可调用张量重排布变换类。

    封装 einops.rearrange 为符合 torchvision.transforms 接口的可调用对象，
    初始化时指定重排模式（pattern）和可选的命名轴参数（kwargs），
    调用时直接对输入张量执行维度重排。

    变换逻辑：调用 einops.rearrange(x, pattern, **kwargs)，完全遵循 einops 语法。
    详见 einops 文档: https://einops.rocks/api/rearrange/

    输入输出形状:
        输入形状: 任意形状的 PyTorch 张量（或 numpy 数组），形状需匹配 pattern 描述
        输出形状: 由 pattern 和 kwargs 决定，例如：
            - pattern="b t c h w -> (b t) c h w"：将视频批量展平为图像批量
            - pattern="b c h w -> b (h w) c"：将空间维展平为序列维
    """

    def __init__(self, pattern: str, **kwargs):
        """初始化 Rearrange 变换。

        Args:
            pattern: einops 重排模式字符串，描述输入和输出维度的映射关系。
                例如 "b t c h w -> (b t) c h w" 表示将 batch 和 time 维合并。
            **kwargs: 传递给 einops.rearrange 的命名轴参数，用于指定具体的维度大小。
                例如 h=16, w=16 用于将 (h w) 轴拆分为固定大小的 h 和 w。
        """
        self.pattern = pattern
        self.kwargs = kwargs

    def __call__(self, x) -> torch.Tensor:
        """执行张量维度重排变换。

        Args:
            x: 输入张量，支持 torch.Tensor 或 numpy.ndarray。
                张量维度必须与初始化时指定的 pattern 相匹配。

        Returns:
            torch.Tensor: 维度重排后的张量。形状由 pattern 和 kwargs 决定。

        Raises:
            einops.EinopsError: 当张量形状与 pattern 不匹配，或 pattern 语法有误时抛出。
        """
        return rearrange(x, self.pattern, **self.kwargs)

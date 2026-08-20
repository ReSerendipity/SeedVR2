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

"""Patch 嵌入与恢复模块。

实现视频到 patch token 的转换和逆转换：

- **patchify**: 将视频张量 (b c t h w) 转换为 patch token 序列 (b n d)。
- **unpatchify**: 将 patch token 序列恢复为视频张量。
- **PatchifyEmbed**: 可学习的 patch 嵌入层，用 3D 卷积将视频 patch 投影到 token 维度。
- **UnPatchify**: 将 token 投影回视频空间，unpatchify 后输出视频张量。

Patch 化算法:
    3D 视频 patch 嵌入将视频沿时间、高度、宽度三个维度划分为不重叠的 patch，
    每个 patch 展平后通过线性投影得到 token 向量。使用 3D 卷积实现等价于
    同时执行 patch 划分和线性投影，且保持空间结构。

    例如，patch_size=(2,2,2) 表示时间步长 2、空间高宽步长 2，每个 patch 包含
    2*2*2 = 8 个体素，展平为 8*c 维向量后投影到 dim 维。
"""

from collections.abc import Sequence

import torch
from einops import rearrange
from torch import nn


def patchify(x: torch.Tensor, patch_size: Sequence[int]):
    """将视频张量划分为 patch 并展平为 token 序列。

    Args:
        x (torch.Tensor): 输入视频张量，形状为 (b, c, t, h, w)。
        patch_size (Sequence[int]): patch 大小，长度为 3 的序列 (p_t, p_h, p_w)。

    Returns:
        torch.Tensor: patch token 序列，形状为 (b, n, p_t*p_h*p_w*c)，
            其中 n = t/p_t * h/p_h * w/p_w。
    """
    b, c, t, h, w = x.shape
    p_t, p_h, p_w = patch_size
    assert t % p_t == h % p_h == w % p_w == 0
    x = x.reshape((b, c, t // p_t, p_t, h // p_h, p_h, w // p_w, p_w))
    x = torch.einsum("n c t p h q w r -> n t h w p q r c", x)
    return x.reshape((b, -1, p_t * p_h * p_w * c))


def unpatchify(x: torch.Tensor, patch_size: Sequence[int], t: int, h: int, w: int, c: int):
    """将 patch token 序列恢复为视频张量。

    Args:
        x (torch.Tensor): patch token 序列，形状为 (b, n, p_t*p_h*p_w*c)。
        patch_size (Sequence[int]): patch 大小 (p_t, p_h, p_w)。
        t (int): 视频时间帧数。
        h (int): 视频高度。
        w (int): 视频宽度。
        c (int): 视频通道数。

    Returns:
        torch.Tensor: 恢复后的视频张量，形状为 (b, c, t, h, w)。
    """
    p_t, p_h, p_w = patch_size
    assert t % p_t == h % p_h == w % p_w == 0
    n_t, n_h, n_w = t // p_t, h // p_h, w // p_w
    x = x.reshape((-1, n_t, n_h, n_w, p_t, p_h, p_w, c))
    x = torch.einsum("n t h w p q r c -> n c t p h q w r", x)
    x = x.reshape((-1, c, t, h, w))
    return x


class PatchifyEmbed(nn.Module):
    """3D Patch 嵌入层，使用 3D 卷积将视频 patch 投影到 token 维度。

    Args:
        in_channels (int): 输入视频通道数。
        dim (int): 输出 token 维度。
        patch_size (Tuple[int, int, int]): patch 大小 (p_t, p_h, p_w)，默认 (1,2,2)。

    Attributes:
        proj (nn.Conv3d): 3D 卷积层，kernel_size 和 stride 均为 patch_size。
        patch_size (Tuple[int, int, int]): patch 大小。
    """

    def __init__(
        self,
        in_channels: int,
        dim: int,
        patch_size: tuple[int, int, int] = (1, 2, 2),
    ):
        super().__init__()
        self.patch_size = patch_size
        self.proj = nn.Conv3d(
            in_channels=in_channels,
            out_channels=dim,
            kernel_size=patch_size,
            stride=patch_size,
        )

    def forward(self, x: torch.FloatTensor) -> torch.FloatTensor:
        """前向传播，执行视频到 patch token 的嵌入。

        Args:
            x (torch.FloatTensor): 输入视频张量，形状为 (b, c, t, h, w)。

        Returns:
            torch.FloatTensor: patch token 序列，形状为 (b, t*h*w/(p_t*p_h*p_w), dim)，
                已展平空间时间维度。
        """
        return rearrange(self.proj(x), "b c t h w -> b (t h w) c")

    def unpatchify(self, x: torch.FloatTensor, t: int, h: int, w: int) -> torch.FloatTensor:
        """将 token 序列恢复为视频空间形状（不还原通道数）。

        Args:
            x (torch.FloatTensor): token 序列，形状 (b, n, dim)。
            t (int): 原始时间帧数。
            h (int): 原始高度。
            w (int): 原始宽度。

        Returns:
            torch.FloatTensor: 恢复为空间形状的张量 (b, dim, t//p_t, h//p_h, w//p_w)。
        """
        p_t, p_h, p_w = self.patch_size
        return rearrange(
            x,
            "b (t h w) c -> b c t h w",
            t=t // p_t,
            h=h // p_h,
            w=w // p_w,
        )


class UnPatchify(nn.Module):
    """将 token 投影回视频空间并 unpatchify。

    Args:
        out_channels (int): 输出视频通道数。
        dim (int): 输入 token 维度。
        patch_size (Tuple[int, int, int]): patch 大小 (p_t, p_h, p_w)，默认 (1,2,2)。

    Attributes:
        proj (nn.Linear): 线性投影层，dim -> p_t*p_h*p_w*out_channels。
        patch_size (Tuple[int, int, int]): patch 大小。
    """

    def __init__(
        self,
        out_channels: int,
        dim: int,
        patch_size: tuple[int, int, int] = (1, 2, 2),
    ):
        super().__init__()
        self.patch_size = patch_size
        self.proj = nn.Linear(dim, out_channels * patch_size[0] * patch_size[1] * patch_size[2])

    def forward(
        self,
        x: torch.FloatTensor,
        t: int,
        h: int,
        w: int,
    ) -> torch.FloatTensor:
        """前向传播，将 token 序列投影并恢复为视频张量。

        Args:
            x (torch.FloatTensor): token 序列，形状 (b, n, dim)。
            t (int): 目标时间帧数。
            h (int): 目标高度。
            w (int): 目标宽度。

        Returns:
            torch.FloatTensor: 输出视频张量，形状 (b, out_channels, t, h, w)。
        """
        c = x.shape[-1]
        p_t, p_h, p_w = self.patch_size
        x = self.proj(x)
        x = unpatchify(x, self.patch_size, t, h, w, c // p_t // p_h // p_w)
        return x

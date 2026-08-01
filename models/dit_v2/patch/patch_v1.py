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

"""NaDiT v2 Patch 嵌入与还原模块 (v1 实现)。

实现视频 patch 化和反 patch 化操作，支持变长序列和因果时序卷积的帧数填充：

- **PatchIn**: 标准 patch 嵌入层，将 5D 视频张量 [B, C, T, H, W] 转换为
  4D token 张量 [B, T//t, H//h, W//w, dim]，支持因果首帧重复填充。
- **PatchOut**: 标准 patch 还原层，将 4D token 张量还原为 5D 视频张量。
- **NaPatchIn**: 变长版本 PatchIn，处理展平的变长 token 序列 [sum_len, C]，
  支持序列并行切片输入。
- **NaPatchOut**: 变长版本 PatchOut，处理展平的变长 token 序列，
  支持序列并行输出聚合。

Patch 算法:
    Patch 嵌入（Patchify）：
    1. 若时序 patch 大小 t > 1，对首帧重复 (t-1) 次填充（因果卷积要求）。
    2. 将视频 [B, C, T, H, W] 按 (t, h, w) 分块，重排为 [B, T//t, H//h, W//w, t*h*w*C]。
    3. 通过线性层投影到 Transformer 维度 dim。

    Patch 还原（Unpatchify）：
    1. 通过线性层将 dim 维投影回 t*h*w*C。
    2. 重排为 [B, C, T, H, W]。
    3. 若 t > 1，裁掉开头填充的 (t-1) 帧。
"""

import torch
from einops import rearrange
from torch import nn
from torch.nn.modules.utils import _triple

from common.cache import Cache
from common.distributed.ops import gather_outputs, slice_inputs

from .. import na


class PatchIn(nn.Module):
    """标准 Patch 嵌入层（批量版本）。

    将 5D 视频张量按 3D patch 大小分块并投影到 Transformer 维度。

    Args:
        in_channels (int): 输入视频通道数 C。
        patch_size (Union[int, Tuple[int, int, int]]): Patch 大小 (t, h, w)，
            t 为时序 patch 大小，h/w 为空间 patch 大小。
        dim (int): Transformer 特征维度。

    Attributes:
        patch_size (Tuple[int,int,int]): Patch 大小元组 (t, h, w)。
        proj (nn.Linear): 线性投影层，将 t*h*w*C 维映射到 dim 维。
    """

    def __init__(
        self,
        in_channels: int,
        patch_size: int | tuple[int, int, int],
        dim: int,
    ):
        super().__init__()
        t, h, w = _triple(patch_size)
        self.patch_size = t, h, w
        self.proj = nn.Linear(in_channels * t * h * w, dim)

    def forward(
        self,
        vid: torch.Tensor,
    ) -> torch.Tensor:
        """前向传播，执行 patch 嵌入。

        Args:
            vid (torch.Tensor): 输入视频张量，形状 [B, C, T, H, W]。

        Returns:
            torch.Tensor: Patch 嵌入后的 token 张量，形状 [B, T//t, H//h, W//w, dim]。
        """
        t, h, w = self.patch_size
        if t > 1:
            assert vid.size(2) % t == 1
            vid = torch.cat([vid[:, :, :1]] * (t - 1) + [vid], dim=2)
        vid = rearrange(vid, "b c (T t) (H h) (W w) -> b T H W (t h w c)", t=t, h=h, w=w)
        vid = self.proj(vid)
        return vid


class PatchOut(nn.Module):
    """标准 Patch 还原层（批量版本）。

    将 Transformer 输出的 token 张量还原回 5D 视频张量。

    Args:
        out_channels (int): 输出视频通道数 C。
        patch_size (Union[int, Tuple[int, int, int]]): Patch 大小 (t, h, w)。
        dim (int): Transformer 特征维度。

    Attributes:
        patch_size (Tuple[int,int,int]): Patch 大小元组 (t, h, w)。
        proj (nn.Linear): 线性投影层，将 dim 维映射回 t*h*w*C 维。
    """

    def __init__(
        self,
        out_channels: int,
        patch_size: int | tuple[int, int, int],
        dim: int,
    ):
        super().__init__()
        t, h, w = _triple(patch_size)
        self.patch_size = t, h, w
        self.proj = nn.Linear(dim, out_channels * t * h * w)

    def forward(
        self,
        vid: torch.Tensor,
    ) -> torch.Tensor:
        """前向传播，执行 patch 还原。

        Args:
            vid (torch.Tensor): 输入 token 张量，形状 [B, T//t, H//h, W//w, dim]。

        Returns:
            torch.Tensor: 还原后的视频张量，形状 [B, C, T, H, W]。
        """
        t, h, w = self.patch_size
        vid = self.proj(vid)
        vid = rearrange(vid, "b T H W (t h w c) -> b c (T t) (H h) (W w)", t=t, h=h, w=w)
        if t > 1:
            vid = vid[:, :, (t - 1) :]
        return vid


class NaPatchIn(PatchIn):
    """变长版本 Patch 嵌入层，支持展平 token 序列和序列并行。

    继承 PatchIn，处理变长输入：每个样本的视频 token 被展平为一维序列
    [sum_vid_len, C]，通过 na.flatten/unflatten 进行批量与逐样本转换。
    支持序列并行时的输入切片。

    适用于 NaDiT 的变长序列推理/训练场景。
    """

    def forward(
        self,
        vid: torch.Tensor,
        vid_shape: torch.LongTensor,
        cache: Cache = Cache(disable=True),
    ) -> torch.Tensor:
        """前向传播，执行变长 patch 嵌入。

        Args:
            vid (torch.Tensor): 展平的视频 token，形状 (sum_vid_len, C)。
            vid_shape (torch.LongTensor): 每个样本的视频网格大小 (b, 3)。
            cache (Cache): 缓存对象，用于缓存 patchify 前的原始形状。

        Returns:
            Tuple[torch.Tensor, torch.LongTensor]: (vid_out, vid_shape_out) 元组，
                vid_out 形状为 (sum_patch_len, dim)，vid_shape_out 为 patch 后的网格大小。
        """
        cache = cache.namespace("patch")
        vid_shape_before_patchify = cache("vid_shape_before_patchify", lambda: vid_shape)
        t, h, w = self.patch_size
        if not (t == h == w == 1):
            vid = na.unflatten(vid, vid_shape)
            for i in range(len(vid)):
                if t > 1 and vid_shape_before_patchify[i, 0] % t != 0:
                    vid[i] = torch.cat([vid[i][:1]] * (t - vid[i].size(0) % t) + [vid[i]], dim=0)
                vid[i] = rearrange(vid[i], "(T t) (H h) (W w) c -> T H W (t h w c)", t=t, h=h, w=w)
            vid, vid_shape = na.flatten(vid)

        vid = slice_inputs(vid, dim=0)
        vid = self.proj(vid)
        return vid, vid_shape


class NaPatchOut(PatchOut):
    """变长版本 Patch 还原层，支持展平 token 序列和序列并行。

    继承 PatchOut，处理变长输出：将展平的 token 序列还原回逐样本 3D 网格，
    支持序列并行时的输出聚合，以及因果填充帧的裁剪。
    """

    def forward(
        self,
        vid: torch.FloatTensor,
        vid_shape: torch.LongTensor,
        cache: Cache = Cache(disable=True),
    ) -> tuple[
        torch.FloatTensor,
        torch.LongTensor,
    ]:
        """前向传播，执行变长 patch 还原。

        Args:
            vid (torch.FloatTensor): 展平的 token 张量，形状 (sum_patch_len, dim)。
            vid_shape (torch.LongTensor): 每个样本的 patch 网格大小 (b, 3)。
            cache (Cache): 缓存对象，从中读取 patchify 前的原始形状用于裁剪填充帧。

        Returns:
            Tuple[torch.FloatTensor, torch.LongTensor]: (vid_out, vid_shape_out) 元组，
                vid_out 形状为 (sum_vid_len, C)，vid_shape_out 为还原后的网格大小。
        """
        cache = cache.namespace("patch")
        vid_shape_before_patchify = cache.get("vid_shape_before_patchify")

        t, h, w = self.patch_size
        vid = self.proj(vid)
        vid = gather_outputs(vid, gather_dim=0, padding_dim=0, unpad_shape=vid_shape, cache=cache.namespace("vid"))
        if not (t == h == w == 1):
            vid = na.unflatten(vid, vid_shape)
            for i in range(len(vid)):
                vid[i] = rearrange(vid[i], "T H W (t h w c) -> (T t) (H h) (W w) c", t=t, h=h, w=w)
                if t > 1 and vid_shape_before_patchify[i, 0] % t != 0:
                    vid[i] = vid[i][(t - vid_shape_before_patchify[i, 0] % t) :]
            vid, vid_shape = na.flatten(vid)

        return vid, vid_shape

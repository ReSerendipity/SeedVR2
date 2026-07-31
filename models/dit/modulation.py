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

"""自适应层调制 (Adaptive Layer Modulation) 模块。

实现 DiT 中核心的 AdaLN-Zero (Adaptive Layer Normalization Zero) 机制：

- **AdaSingle**: 单分支自适应调制层，通过时间步嵌入生成 shift/scale/gate 参数，
  对 Transformer 块中的注意力和 MLP 子层进行条件化调制。

AdaLN 算法:
    标准 DiT 使用自适应层归一化 (Adaptive Layer Norm)，公式为::

        h = modLN(h, c) = (1 + scale(c)) * LN(h) + shift(c)
        h = h + gate(c) * Attn(h)  (或 MLP)

    其中 c 为时间步嵌入，scale/shift/gate 由 c 通过线性层生成。
    AdaLN-Zero 将 gate 初始化为 0，使得初始时残差块为恒等映射，
    有助于深度 Transformer 的稳定训练。

    emb_dim 需要为 6 * dim，因为每个子层需要 3 组参数 (shift, scale, gate)，
    注意力和 MLP 共 2 个子层，所以总维度为 6 * dim。
"""

from typing import Callable, List, Optional
import torch
from einops import rearrange
from torch import nn

from common.cache import Cache
from common.distributed.ops import slice_inputs

ada_layer_type = Callable[[int, int], nn.Module]


def get_ada_layer(ada_layer: str) -> ada_layer_type:
    """根据类型名称返回自适应调制层类。

    Args:
        ada_layer (str): 调制层类型，目前仅支持 "single" (AdaSingle)。

    Returns:
        ada_layer_type: 调制层类对象。

    Raises:
        NotImplementedError: 不支持的类型。
    """
    if ada_layer == "single":
        return AdaSingle
    raise NotImplementedError(f"{ada_layer} is not supported")


def expand_dims(x: torch.Tensor, dim: int, ndim: int):
    """扩展张量维度，在指定位置插入长度为 1 的维度。

    例: x 形状为 (b, d)，目标 ndim=5，dim=1，返回 (b, 1, 1, 1, d)。

    Args:
        x (torch.Tensor): 输入张量。
        dim (int): 插入维度的位置。
        ndim (int): 目标维度数。

    Returns:
        torch.Tensor: 扩展后的张量。
    """
    shape = x.shape
    shape = shape[:dim] + (1,) * (ndim - len(shape)) + shape[dim:]
    return x.reshape(shape)


class AdaSingle(nn.Module):
    """自适应单分支调制层，通过时间步嵌入对隐藏状态进行 shift/scale/gate 调制。

    使用可学习的 per-layer shift/scale/gate 参数与时间步嵌入生成的参数相加，
    支持变长序列 (通过 hid_len 参数) 和缓存加速。

    Args:
        dim (int): 特征维度。
        emb_dim (int): 嵌入维度，必须等于 6 * dim。
        layers (List[str]): 要调制的层名称列表，如 ["attn", "mlp"]。

    Attributes:
        dim (int): 特征维度。
        emb_dim (int): 嵌入维度。
        layers (List[str]): 层名称列表。
        {layer}_shift (nn.Parameter): 每层的 shift 可学习参数，形状 (dim,)。
        {layer}_scale (nn.Parameter): 每层的 scale 可学习参数，初始化为 1。
        {layer}_gate (nn.Parameter): 每层的 gate 可学习参数。
    """

    def __init__(
        self,
        dim: int,
        emb_dim: int,
        layers: List[str],
    ):
        assert emb_dim == 6 * dim, "AdaSingle requires emb_dim == 6 * dim"
        super().__init__()
        self.dim = dim
        self.emb_dim = emb_dim
        self.layers = layers
        for l in layers:
            self.register_parameter(f"{l}_shift", nn.Parameter(torch.randn(dim) / dim**0.5))
            self.register_parameter(f"{l}_scale", nn.Parameter(torch.randn(dim) / dim**0.5 + 1))
            self.register_parameter(f"{l}_gate", nn.Parameter(torch.randn(dim) / dim**0.5))

    def forward(
        self,
        hid: torch.FloatTensor,
        emb: torch.FloatTensor,
        layer: str,
        mode: str,
        cache: Cache = Cache(disable=True),
        branch_tag: str = "",
        hid_len: Optional[torch.LongTensor] = None,
    ) -> torch.FloatTensor:
        """前向传播，执行自适应调制。

        Args:
            hid (torch.FloatTensor): 输入隐藏状态，形状 (b, ..., c)。
            emb (torch.FloatTensor): 时间步嵌入，形状 (b, d)，d = 6*dim。
            layer (str): 当前调制的层名称，必须在 self.layers 中。
            mode (str): 调制模式，"in" 表示输入调制 (shift+scale)，"out" 表示输出门控 (gate)。
            cache (Cache): 缓存对象，用于缓存重复计算的 emb。
            branch_tag (str): 分支标签，用于缓存命名空间区分 vid/txt。
            hid_len (Optional[torch.LongTensor]): 变长序列的每个样本长度，形状 (b,)。

        Returns:
            torch.FloatTensor: 调制后的隐藏状态，原地修改后返回。
        """
        idx = self.layers.index(layer)
        emb = rearrange(emb, "b (d l g) -> b d l g", l=len(self.layers), g=3)[..., idx, :]
        emb = expand_dims(emb, 1, hid.ndim + 1)

        if hid_len is not None:
            emb = cache(
                f"emb_repeat_{idx}_{branch_tag}",
                lambda: slice_inputs(
                    torch.cat([e.repeat(l, *([1] * e.ndim)) for e, l in zip(emb, hid_len)]),
                    dim=0,
                ),
            )

        shiftA, scaleA, gateA = emb.unbind(-1)
        shiftB, scaleB, gateB = (
            getattr(self, f"{layer}_shift"),
            getattr(self, f"{layer}_scale"),
            getattr(self, f"{layer}_gate"),
        )

        if mode == "in":
            return hid.mul_(scaleA + scaleB).add_(shiftA + shiftB)
        if mode == "out":
            return hid.mul_(gateA + gateB)
        raise NotImplementedError

    def extra_repr(self) -> str:
        """返回模块的额外字符串表示。"""
        return f"dim={self.dim}, emb_dim={self.emb_dim}, layers={self.layers}"

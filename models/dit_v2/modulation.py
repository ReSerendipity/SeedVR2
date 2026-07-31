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

实现 DiT 中的 AdaLN-Zero 机制，v2 版本相比 v1 增加了：

- 通过 ``modes`` 参数控制每个 layer 支持的调制模式（"in" 输入 shift+scale，"out" 输出 gate）。
- 内部使用 SiLU + Linear 从时间步嵌入生成调制参数，而非直接 reshape emb。
- 支持 ``vid_only`` 模式（最后一层仅调制视频分支）。

AdaLN-Zero 算法:
    标准 DiT 调制公式::

        # 输入调制 (mode="in", 在 Norm 后、Attn/MLP 前)
        h = (1 + scale(c) + scale_bias) * LN(h) + (shift(c) + shift_bias)

        # 输出门控 (mode="out", 在 Attn/MLP 后、残差前)
        h = (gate(c) + gate_bias) * h

    其中 c 为时间步嵌入，scale/shift/gate 由 c 通过 Linear+SiLU 生成，
    scale_bias/shift_bias/gate_bias 为 per-layer 可学习参数。
    gate 初始化为 0，使初始时残差块为恒等映射，稳定深度训练。
"""

from typing import Callable, List, Optional
import torch
from einops import rearrange
from torch import nn

from common.cache import Cache
from common.distributed.ops import slice_inputs

ada_layer_type = Callable[..., nn.Module]


def get_ada_layer(ada_layer: str) -> ada_layer_type:
    """根据类型名称返回自适应调制层类。

    Args:
        ada_layer: 调制层类型，目前支持 ``"single"`` (AdaSingle)。

    Returns:
        ada_layer_type: 调制层类对象。
    """
    if ada_layer == "single":
        return AdaSingle
    raise NotImplementedError(f"{ada_layer} is not supported")


def expand_dims(x: torch.Tensor, dim: int, ndim: int):
    """扩展张量维度，在指定位置插入长度为 1 的维度。

    例: x 形状为 (b, d)，目标 ndim=3, dim=1，返回 (b, 1, d)。

    Args:
        x: 输入张量。
        dim: 插入维度的位置（从0计数）。
        ndim: 目标维度总数。

    Returns:
        torch.Tensor: 扩展后的张量。
    """
    shape = x.shape
    n_insert = ndim - len(shape)
    new_shape = shape[:dim] + (1,) * n_insert + shape[dim:]
    return x.reshape(new_shape)


class AdaSingle(nn.Module):
    """自适应单分支调制层，通过时间步嵌入对隐藏状态进行 shift/scale/gate 调制。

    使用 SiLU 激活 + Linear 层从 emb 生成调制参数，并结合可学习的 per-layer
    shift/scale/gate bias 参数。支持变长序列 (通过 hid_len repeat)。

    Args:
        dim: 特征维度。
        emb_dim: 时间步嵌入维度（Linear 输入维度）。
        layers: 要调制的层名称列表，如 ``["attn", "mlp"]``。
        modes: 支持的调制模式列表，默认 ``None`` 表示同时支持 ``"in"`` 和 ``"out"``。
            - ``"in"``: 输入调制（shift + scale），2 组参数
            - ``"out"``: 输出门控（gate），1 组参数
            - ``None``/``["in","out"]``: 全部 3 组参数
    """

    def __init__(
        self,
        dim: int,
        emb_dim: int,
        layers: List[str],
        modes: Optional[List[str]] = None,
    ):
        super().__init__()
        self.dim = dim
        self.emb_dim = emb_dim
        self.layers = layers
        self.modes = modes if modes is not None else ["in", "out"]

        params_per_layer = 0
        if "in" in self.modes:
            params_per_layer += 2
        if "out" in self.modes:
            params_per_layer += 1
        self.params_per_layer = params_per_layer

        self.silu = nn.SiLU()
        output_dim = len(layers) * params_per_layer * dim
        self.linear = nn.Linear(emb_dim, output_dim, bias=True)
        nn.init.zeros_(self.linear.weight)
        nn.init.zeros_(self.linear.bias)

        for l in layers:
            if "in" in self.modes:
                self.register_parameter(f"{l}_shift", nn.Parameter(torch.zeros(dim)))
                self.register_parameter(f"{l}_scale", nn.Parameter(torch.zeros(dim)))
            if "out" in self.modes:
                self.register_parameter(f"{l}_gate", nn.Parameter(torch.zeros(dim)))

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
            hid: 输入隐藏状态，形状 (total_l, c) 或 (b, ..., c)。
            emb: 时间步嵌入，形状 (b, emb_dim)。
            layer: 当前调制的层名称，必须在 ``self.layers`` 中。
            mode: 调制模式，``"in"`` (shift+scale) 或 ``"out"`` (gate)。
            cache: 缓存对象，用于缓存 repeat 后的 emb。
            branch_tag: 分支标签（"vid"/"txt"），用于缓存命名空间。
            hid_len: 变长序列每样本长度，形状 (b,)。

        Returns:
            torch.FloatTensor: 调制后的隐藏状态（in-place 修改）。
        """
        idx = self.layers.index(layer)
        params = self.linear(self.silu(emb))
        params = rearrange(
            params, "b (d l g) -> b d l g",
            l=len(self.layers), g=self.params_per_layer
        )[..., idx, :]
        params = expand_dims(params, 1, hid.ndim + 1)

        if hid_len is not None:
            params = cache(
                f"emb_repeat_{idx}_{branch_tag}",
                lambda: slice_inputs(
                    torch.cat([e.repeat(l, *([1] * (e.ndim - 1))) for e, l in zip(params, hid_len)]),
                    dim=0,
                ),
            )

        if mode == "in":
            assert "in" in self.modes
            if self.params_per_layer == 3:
                shiftA, scaleA, _ = params.unbind(-1)
            else:
                shiftA, scaleA = params.unbind(-1)
            shiftB = getattr(self, f"{layer}_shift")
            scaleB = getattr(self, f"{layer}_scale")
            return hid.mul_(1 + scaleA + scaleB).add_(shiftA + shiftB)
        elif mode == "out":
            assert "out" in self.modes
            if self.params_per_layer == 3:
                _, _, gateA = params.unbind(-1)
            else:
                gateA = params.squeeze(-1)
            gateB = getattr(self, f"{layer}_gate")
            return hid.mul_(gateA + gateB)
        else:
            raise ValueError(f"Unknown mode: {mode}")

    def extra_repr(self) -> str:
        """返回模块的额外字符串表示。"""
        return f"dim={self.dim}, emb_dim={self.emb_dim}, layers={self.layers}, modes={self.modes}"

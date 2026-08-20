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

"""3D 旋转位置编码 (Rotary Position Embedding, RoPE) 模块。

为视频 Transformer 提供三维（时间 t、高度 h、宽度 w）位置编码：

- **rotary_emb**: 3D 旋转位置编码类，根据注意力头维度分配各轴的频率分量，
  支持 1D、2D、3D 位置编码。
- **apply_rope**: 对查询/键张量应用旋转位置编码的函数。

RoPE 算法:
    旋转位置编码 (RoPE) 通过旋转矩阵将位置信息注入到 query 和 key 向量中：

    对于二维向量 (x1, x2)，在位置 m 处的旋转为::

        [cos(mθ)  -sin(mθ)] [x1]
        [sin(mθ)   cos(mθ)] [x2]

    这种旋转编码使得注意力分数天然具有相对位置感知能力：
    <RoPE(q,m), RoPE(k,n)> = f(q,k, m-n)，仅依赖相对位置 m-n。

    对于 3D 视频数据，将头维度划分为 t/h/w 三部分，分别在时间、高度、宽度轴应用 RoPE，
    使用不同的频率基 (theta_t, theta_h, theta_w) 控制各轴的位置编码尺度。
"""

import torch
from torch import nn
from yunchang.globals import (
    HAS_LONGCONTEXT,
    PROCESS_GROUP,
)
from yunchang.yunchang_utils import (
    get_seq_sharding_info,
)

if HAS_LONGCONTEXT:
    from yunchang.kernels.attention.math_attention import apply_rope_emb as _apply_rope_emb


class rotary_emb(nn.Module):
    """3D 旋转位置编码 (RoPE)。

    根据视频的时间、高度、宽度三维坐标生成位置编码，支持将头维度
    分配给不同维度（1D/2D/3D）。

    Args:
        dim (int): 每个注意力头的维度。
        max_seqlen_t (int): 时间轴最大序列长度。
        max_seqlen_h (int): 高度轴最大序列长度。
        max_seqlen_w (int): 宽度轴最大序列长度。
        rope_dim (Optional[str]): 维度分配方式，None 表示使用默认 1/4, 1/4, 1/2 分配给 t/h/w。
        theta_t (int): 时间轴频率基，默认 3600。
        theta_h (int): 高度轴频率基，默认 3600。
        theta_w (int): 宽度轴频率基，默认 3600。

    Attributes:
        dim (int): 头维度。
        dim_t, dim_h, dim_w (int): 各轴分配的维度。
        freqs_t, freqs_h, freqs_w (torch.Tensor): 预计算的频率张量，注册为 buffer。
    """

    def __init__(
        self,
        dim: int,
        max_seqlen_t: int,
        max_seqlen_h: int,
        max_seqlen_w: int,
        rope_dim: str | None = None,
        theta_t=3600,
        theta_h=3600,
        theta_w=3600,
    ):
        super().__init__()
        self.dim = dim
        if rope_dim is not None:
            self.dim_t = int(rope_dim[0])
            self.dim_h = int(rope_dim[1])
            self.dim_w = dim - self.dim_t - self.dim_h
        else:
            self.dim_t = dim // 4
            self.dim_h = dim // 4
            self.dim_w = dim // 2
        self.theta_t = theta_t
        self.theta_h = theta_h
        self.theta_w = theta_w

        freqs_t = self.precompute_freqs_cis(self.dim_t, max_seqlen_t, theta_t)
        freqs_h = self.precompute_freqs_cis(self.dim_h, max_seqlen_h, theta_h)
        freqs_w = self.precompute_freqs_cis(self.dim_w, max_seqlen_w, theta_w)
        self.register_buffer("freqs_t", freqs_t, persistent=False)
        self.register_buffer("freqs_h", freqs_h, persistent=False)
        self.register_buffer("freqs_w", freqs_w, persistent=False)

    def precompute_freqs_cis(self, dim, max_seqlen, theta):
        """预计算旋转角度的余弦和正弦值。

        Args:
            dim (int): 该轴的特征维度。
            max_seqlen (int): 最大序列长度。
            theta (float): 频率基数。

        Returns:
            torch.Tensor: 预计算的频率张量，形状 (max_seqlen, dim)，复数形式。
        """
        freqs = 1.0 / (theta ** (torch.arange(0, dim, 2, dtype=torch.float64) / dim))
        t = torch.arange(max_seqlen, dtype=torch.float64)
        freqs = torch.outer(t, freqs).float()
        return torch.polar(torch.ones_like(freqs), freqs)

    def get_3d_freqs_cis(self, freqs_list: tuple[torch.Tensor], t: int, h: int, w: int, dtype):
        """获取 3D 网格位置的旋转频率张量。

        通过外积方式将 t、h、w 三个 1D 频率张量组合为 3D 网格频率，
        然后展平为一维序列，与 patch token 序列顺序对应。

        Args:
            freqs_list (Tuple[torch.Tensor]): (freqs_t, freqs_h, freqs_w) 三元组。
            t (int): 时间维度 token 数。
            h (int): 高度维度 token 数。
            w (int): 宽度维度 token 数。
            dtype (torch.dtype): 输出数据类型。

        Returns:
            torch.Tensor: 展平后的频率张量，形状 (t*h*w, dim)，复数形式。
        """
        freqs_t, freqs_h, freqs_w = freqs_list
        freqs_t = freqs_t[:t].reshape(t, 1, 1, self.dim_t // 2)
        freqs_h = freqs_h[:h].reshape(1, h, 1, self.dim_h // 2)
        freqs_w = freqs_w[:w].reshape(1, 1, w, self.dim_w // 2)
        freqs_t = freqs_t.repeat(1, h, w, 1)
        freqs_h = freqs_h.repeat(t, 1, w, 1)
        freqs_w = freqs_w.repeat(t, h, 1, 1)
        freqs = torch.cat([freqs_t, freqs_h, freqs_w], dim=-1)
        return freqs.reshape(t * h * w, -1)

    def forward(self, x, t, h, w, branch, branch_tag, cache):
        """前向传播，对查询或键张量应用 3D RoPE。

        Args:
            x (torch.Tensor): 查询或键张量，形状 (b, n, heads, dim)。
            t (int): 时间维度 token 数。
            h (int): 高度维度 token 数。
            w (int): 宽度维度 token 数。
            branch (str): 分支类型，'vid' 或 'txt'。
            branch_tag (str): 分支标签，用于缓存。
            cache: 缓存对象。

        Returns:
            torch.Tensor: 应用 RoPE 后的张量，形状与输入相同。
        """
        if branch == "txt":
            t = h = w = 0
            n = x.shape[1]
            freqs = self.get_3d_freqs_cis((self.freqs_t, self.freqs_h, self.freqs_w), n, 1, 1, dtype=x.dtype)
        else:
            freqs = cache(
                f"freqs_{branch_tag}",
                lambda: self.get_3d_freqs_cis((self.freqs_t, self.freqs_h, self.freqs_w), t, h, w, dtype=x.dtype),
            )

        if x.shape[1] != freqs.shape[0]:
            sp_size, sp_rank, _ = get_seq_sharding_info(PROCESS_GROUP)
            assert x.shape[1] * sp_size == freqs.shape[0]
            chunk_size = freqs.shape[0] // sp_size
            freqs = freqs[chunk_size * sp_rank : chunk_size * (sp_rank + 1)]

        return apply_rope(x, freqs=freqs)


def apply_rope(xq: torch.Tensor, xk: torch.Tensor | None = None, freqs=None):
    """对查询/键张量应用旋转位置编码。

    Args:
        xq (torch.Tensor): 查询张量，形状 (b, n, num_heads, head_dim)。
        xk (Optional[torch.Tensor]): 键张量，形状同 xq，若为 None 则仅对 xq 应用。
        freqs (torch.Tensor): 预计算的旋转频率，复数形式，形状 (n, head_dim//2)。

    Returns:
        Union[torch.Tensor, Tuple[torch.Tensor, torch.Tensor]]: 应用 RoPE 后的张量。
            若 xk 不为 None，返回 (xq_out, xk_out) 元组。
    """
    assert xq.dtype in [
        torch.float16,
        torch.bfloat16,
    ], f"only support bf16/fp16, but got {xq.dtype}"

    batch_size, seqlen_q, num_heads_q, head_size = xq.shape
    if xk is not None:
        batch_size, seqlen_k, num_heads_k, head_size = xk.shape
    if HAS_LONGCONTEXT and (xq.device.type == "cuda"):
        if xk is not None:
            return _apply_rope_emb(xq, xk, freqs, head_size)
        else:
            return _apply_rope_emb(xq, None, freqs, head_size)

    xq_ = torch.view_as_complex(xq.float().reshape(*xq.shape[:-1], -1, 2))
    if xk is not None:
        xk_ = torch.view_as_complex(xk.float().reshape(*xk.shape[:-1], -1, 2))
    freqs = freqs[: xq_.shape[-3]]
    freqs = freqs.unsqueeze(0).unsqueeze(-2)
    xq_out = torch.view_as_real(xq_ * freqs).flatten(3)
    if xk is not None:
        xk_out = torch.view_as_real(xk_ * freqs).flatten(3)
    if xk is not None:
        return xq_out.type_as(xq), xk_out.type_as(xk)
    return xq_out.type_as(xq)

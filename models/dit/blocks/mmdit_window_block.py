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

"""多模态窗口 Transformer Block 模块。

实现 MM-DiT (Multi-Modal Diffusion Transformer) 的窗口注意力版本：

- **MMWindowAttention**: 多模态窗口注意力层，视频分支做窗口分区注意力，
  文本分支做全局注意力，视频窗口内注意力同时关注同窗口的视频 token 和所有文本 token，
  文本注意力则关注全部视频和文本 token。
- **MMWindowTransformerBlock**: 完整的 Transformer block，包含
  注意力子层 + MLP 子层 + AdaLN-Zero 自适应调制 + 残差连接。

MM-DiT 注意力模式:
    MM-DiT (Multi-Modal DiT) 是一种统一的多模态扩散 Transformer 架构，
    视频和文本 token 在同一序列中进行联合注意力计算：

    - 视频查询 (Q_vid) 关注：同窗口内视频键值 + 全部文本键值
    - 文本查询 (Q_txt) 关注：全部视频键值 + 全部文本键值

    这种设计保持了视频-文本跨模态交互的完整性，同时通过窗口注意力控制
    视频自注意力的计算复杂度，避免 O(n^2) 的全局视频注意力开销。

窗口注意力算法:
    对于视频 token (t*h*w 个)，沿时间、高度、宽度划分为 (nt, nh, nw) 个窗口，
    每个窗口大小为 (tt, hh, ww)。每个窗口内的视频 token 与所有文本 token 拼接，
    在窗口内做标准缩放点积注意力。文本 token 则做全局注意力。
"""

from typing import Tuple, Union
import torch
from einops import rearrange
from torch import nn
from torch.nn import functional as F
from torch.nn.modules.utils import _triple

from common.distributed.ops import (
    gather_heads,
    gather_heads_scatter_seq,
    gather_seq_scatter_heads_qkv,
    scatter_heads,
)
from common.utils import safe_pad_operation, safe_interpolate_operation
from ..attention import TorchAttention
from ..mlp import get_mlp
from ..mm import MMArg, MMModule
from ..modulation import ada_layer_type
from ..normalization import norm_layer_type
from ..rope import RotaryEmbedding3d


class MMWindowAttention(nn.Module):
    """多模态窗口注意力，对视频序列做窗口分区、对文本做全局注意力。

    视频查询在各自的局部窗口内关注视频 token 和所有文本 token，
    文本查询则关注全局所有视频和文本 token。

    Args:
        vid_dim (int): 视频特征维度。
        txt_dim (int): 文本特征维度。
        heads (int): 注意力头数。
        head_dim (int): 每个注意力头的维度。
        qk_bias (bool): Q/K 投影是否使用偏置。
        qk_rope (bool): 是否对 Q/K 应用 RoPE 位置编码。
        qk_norm (norm_layer_type): Q/K 归一化层构造函数。
        qk_norm_eps (float): Q/K 归一化 epsilon。
        window (Union[int, Tuple[int, int, int]]): 窗口配置。
        window_method (str): 窗口划分方法，"win" 或 "win_by_size"。
        shared_qkv (bool): 视频/文本是否共享 QKV 投影权重。

    Attributes:
        window (Tuple[int,int,int]): 窗口大小或窗口数量。
        window_method (str): 窗口划分方法。
        head_dim (int): 头维度。
        proj_qkv (MMModule): QKV 投影层（双分支）。
        proj_out (MMModule): 输出投影层（双分支）。
        norm_q (MMModule): Q 归一化层（双分支）。
        norm_k (MMModule): K 归一化层（双分支）。
        rope (Optional[RotaryEmbedding3d]): 3D RoPE 位置编码（视频分支）。
        attn (TorchAttention): 标准 PyTorch 注意力实现。
    """

    def __init__(
        self,
        vid_dim: int,
        txt_dim: int,
        heads: int,
        head_dim: int,
        qk_bias: bool,
        qk_rope: bool,
        qk_norm: norm_layer_type,
        qk_norm_eps: float,
        window: Union[int, Tuple[int, int, int]],
        window_method: str,
        shared_qkv: bool,
    ):
        super().__init__()
        dim = MMArg(vid_dim, txt_dim)
        inner_dim = heads * head_dim
        qkv_dim = inner_dim * 3

        self.window = _triple(window)
        self.window_method = window_method
        assert all(map(lambda v: isinstance(v, int) and v >= 0, self.window))

        self.head_dim = head_dim
        self.proj_qkv = MMModule(nn.Linear, dim, qkv_dim, bias=qk_bias, shared_weights=shared_qkv)
        self.proj_out = MMModule(nn.Linear, inner_dim, dim, shared_weights=shared_qkv)
        self.norm_q = MMModule(qk_norm, dim=head_dim, eps=qk_norm_eps, elementwise_affine=True)
        self.norm_k = MMModule(qk_norm, dim=head_dim, eps=qk_norm_eps, elementwise_affine=True)
        self.rope = RotaryEmbedding3d(dim=head_dim // 2) if qk_rope else None
        self.attn = TorchAttention()

    def forward(
        self,
        vid: torch.FloatTensor,
        txt: torch.FloatTensor,
        txt_mask: torch.BoolTensor,
    ) -> Tuple[
        torch.FloatTensor,
        torch.FloatTensor,
    ]:
        """前向传播，执行多模态窗口注意力计算。

        Args:
            vid (torch.FloatTensor): 视频输入，形状 (b, T, H, W, c)，4D 空间时间格式。
            txt (torch.FloatTensor): 文本输入，形状 (b, L, c)。
            txt_mask (torch.BoolTensor): 文本注意力 mask，形状 (b, L)，True 表示有效位置。

        Returns:
            Tuple[torch.FloatTensor, torch.FloatTensor]: (vid_out, txt_out) 元组，
                形状分别为 (b, T, H, W, vid_dim) 和 (b, L, txt_dim)。
        """
        vid_qkv, txt_qkv = self.proj_qkv(vid, txt)
        vid_qkv = gather_seq_scatter_heads_qkv(vid_qkv, seq_dim=2)
        _, T, H, W, _ = vid_qkv.shape
        _, L, _ = txt.shape

        if self.window_method == "win":
            nt, nh, nw = self.window
            tt, hh, ww = T // nt, H // nh, W // nw
        elif self.window_method == "win_by_size":
            tt, hh, ww = self.window
            tt, hh, ww = (
                tt if tt > 0 else T,
                hh if hh > 0 else H,
                ww if ww > 0 else W,
            )
            nt, nh, nw = T // tt, H // hh, W // ww
        else:
            raise NotImplementedError

        vid_qkv = rearrange(vid_qkv, "b T H W (o h d) -> o b h (T H W) d", o=3, d=self.head_dim)
        txt_qkv = rearrange(txt_qkv, "b L (o h d) -> o b h L d", o=3, d=self.head_dim)
        txt_qkv = scatter_heads(txt_qkv, dim=2)

        vid_q, vid_k, vid_v = vid_qkv.unbind()
        txt_q, txt_k, txt_v = txt_qkv.unbind()

        vid_q, txt_q = self.norm_q(vid_q, txt_q)
        vid_k, txt_k = self.norm_k(vid_k, txt_k)

        if self.rope:
            vid_q, vid_k = self.rope(vid_q, vid_k, (T, H, W))

        def vid_window(v):
            return rearrange(
                v,
                "b h (nt tt nh hh nw ww) d -> b h (nt nh nw) (tt hh ww) d",
                hh=hh,
                ww=ww,
                tt=tt,
                nh=nh,
                nw=nw,
                nt=nt,
            )

        def txt_window(t):
            return rearrange(t, "b h L d -> b h 1 L d").expand(-1, -1, nt * nh * nw, -1, -1)

        vid_msk = safe_pad_operation(txt_mask, (tt * hh * ww, 0), value=True)
        vid_msk = rearrange(vid_msk, "b l -> b 1 1 1 l").expand(-1, 1, 1, tt * hh * ww, -1)
        vid_out = self.attn(
            vid_window(vid_q),
            torch.cat([vid_window(vid_k), txt_window(txt_k)], dim=-2),
            torch.cat([vid_window(vid_v), txt_window(txt_v)], dim=-2),
            vid_msk,
        )
        vid_out = rearrange(
            vid_out,
            "b h (nt nh nw) (tt hh ww) d -> b (nt tt) (nh hh) (nw ww) (h d)",
            hh=hh,
            ww=ww,
            tt=tt,
            nh=nh,
            nw=nw,
        )
        vid_out = gather_heads_scatter_seq(vid_out, head_dim=4, seq_dim=2)

        txt_msk = safe_pad_operation(txt_mask, (T * H * W, 0), value=True)
        txt_msk = rearrange(txt_msk, "b l -> b 1 1 l").expand(-1, 1, L, -1)
        txt_out = self.attn(
            txt_q,
            torch.cat([vid_k, txt_k], dim=-2),
            torch.cat([vid_v, txt_v], dim=-2),
            txt_msk,
        )
        txt_out = rearrange(txt_out, "b h L d -> b L (h d)")
        txt_out = gather_heads(txt_out, dim=2)

        vid_out, txt_out = self.proj_out(vid_out, txt_out)
        return vid_out, txt_out


class MMWindowTransformerBlock(nn.Module):
    """多模态窗口 Transformer block，包含注意力 + MLP + 自适应调制。

    标准的 Pre-Norm Transformer block 结构：
    1. 输入经过 AdaLN 调制（in 模式：shift+scale）
    2. 经过多模态窗口注意力
    3. AdaLN 门控（out 模式：gate）
    4. 残差连接
    5. 再次 AdaLN 调制（in 模式）
    6. 经过 MLP
    7. AdaLN 门控（out 模式）
    8. 残差连接

    Args:
        vid_dim (int): 视频特征维度。
        txt_dim (int): 文本特征维度。
        emb_dim (int): 时间步嵌入维度（6*dim for AdaSingle）。
        heads (int): 注意力头数。
        head_dim (int): 每头维度。
        expand_ratio (int): MLP 扩展倍数。
        norm (norm_layer_type): 归一化层构造函数。
        norm_eps (float): 归一化 epsilon。
        ada (ada_layer_type): 自适应调制层构造函数。
        qk_bias (bool): Q/K 投影偏置。
        qk_rope (bool): 是否启用 RoPE。
        qk_norm (norm_layer_type): Q/K 归一化层。
        window (Union[int, Tuple[int,int,int]]): 窗口配置。
        window_method (str): 窗口划分方法。
        shared_qkv (bool): QKV 是否共享权重。
        shared_mlp (bool): MLP 是否共享权重。
        mlp_type (str): MLP 类型 ("normal" 或 "swiglu")。
        **kwargs: 额外参数。

    Attributes:
        attn_norm (MMModule): 注意力前归一化层（双分支）。
        attn (MMWindowAttention): 多模态窗口注意力层。
        mlp_norm (MMModule): MLP 前归一化层（双分支）。
        mlp (MMModule): MLP 层（双分支）。
        ada (MMModule): AdaLN 自适应调制层（双分支）。
    """

    def __init__(
        self,
        *,
        vid_dim: int,
        txt_dim: int,
        emb_dim: int,
        heads: int,
        head_dim: int,
        expand_ratio: int,
        norm: norm_layer_type,
        norm_eps: float,
        ada: ada_layer_type,
        qk_bias: bool,
        qk_rope: bool,
        qk_norm: norm_layer_type,
        window: Union[int, Tuple[int, int, int]],
        window_method: str,
        shared_qkv: bool,
        shared_mlp: bool,
        mlp_type: str,
        **kwargs,
    ):
        super().__init__()
        dim = MMArg(vid_dim, txt_dim)
        self.attn_norm = MMModule(norm, dim=dim, eps=norm_eps, elementwise_affine=False)
        self.attn = MMWindowAttention(
            vid_dim=vid_dim,
            txt_dim=txt_dim,
            heads=heads,
            head_dim=head_dim,
            qk_bias=qk_bias,
            qk_rope=qk_rope,
            qk_norm=qk_norm,
            qk_norm_eps=norm_eps,
            window=window,
            window_method=window_method,
            shared_qkv=shared_qkv,
        )
        self.mlp_norm = MMModule(norm, dim=dim, eps=norm_eps, elementwise_affine=False)
        self.mlp = MMModule(
            get_mlp(mlp_type),
            dim=dim,
            expand_ratio=expand_ratio,
            shared_weights=shared_mlp,
        )
        self.ada = MMModule(ada, dim=dim, emb_dim=emb_dim, layers=["attn", "mlp"])

    def forward(
        self,
        vid: torch.FloatTensor,
        txt: torch.FloatTensor,
        txt_mask: torch.BoolTensor,
        emb: torch.FloatTensor,
    ) -> Tuple[
        torch.FloatTensor,
        torch.FloatTensor,
    ]:
        """前向传播，执行完整的 Transformer block 计算。

        Args:
            vid (torch.FloatTensor): 视频输入，形状 (b, T, H, W, vid_dim)。
            txt (torch.FloatTensor): 文本输入，形状 (b, L, txt_dim)。
            txt_mask (torch.BoolTensor): 文本 mask，形状 (b, L)。
            emb (torch.FloatTensor): 时间步嵌入，形状 (b, emb_dim)。

        Returns:
            Tuple[torch.FloatTensor, torch.FloatTensor]: (vid_out, txt_out) 元组。
        """
        vid_attn, txt_attn = self.attn_norm(vid, txt)
        vid_attn, txt_attn = self.ada(vid_attn, txt_attn, emb=emb, layer="attn", mode="in")
        vid_attn, txt_attn = self.attn(vid_attn, txt_attn, txt_mask=txt_mask)
        vid_attn, txt_attn = self.ada(vid_attn, txt_attn, emb=emb, layer="attn", mode="out")
        vid_attn, txt_attn = (vid_attn + vid), (txt_attn + txt)

        vid_mlp, txt_mlp = self.mlp_norm(vid_attn, txt_attn)
        vid_mlp, txt_mlp = self.ada(vid_mlp, txt_mlp, emb=emb, layer="mlp", mode="in")
        vid_mlp, txt_mlp = self.mlp(vid_mlp, txt_mlp)
        vid_mlp, txt_mlp = self.ada(vid_mlp, txt_mlp, emb=emb, layer="mlp", mode="out")
        vid_mlp, txt_mlp = (vid_mlp + vid_attn), (txt_mlp + txt_attn)

        return vid_mlp, txt_mlp

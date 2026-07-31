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

"""NaDiT v2 多模态注意力实现模块。

实现两种变长多模态注意力机制，均基于 Flash Attention v2 的 cu_seqlens API：

- **NaMMAttention**: 多模态全局注意力，将视频和文本 token 拼接后做全注意力计算。
  支持 Q/K 归一化、可选 RoPE（包括多模态 MM-RoPE）、共享/独立权重。
- **NaSwinAttention**: 继承 NaMMAttention，实现变长窗口注意力（Swin 风格）。
  视频 token 按窗口分区，每个窗口内视频 token 与全局文本 token 联合注意力，
  窗口划分通过预计算索引实现以支持任意分辨率。

注意力算法:
    1. 视频/文本分别投影 Q/K/V（支持共享权重）。
    2. 对 Q/K 应用归一化（QK-Norm，稳定训练）。
    3. 应用 RoPE 位置编码（可选 MM-RoPE：视频和文本使用不同频率）。
    4. 按样本拼接视频和文本序列，计算 cu_seqlens 累积长度。
    5. 窗口注意力：使用 repeat_concat_idx 按窗口重复文本 token。
    6. 调用 Flash Attention v2 变长 API 批量计算注意力。
    7. 拆分结果回视频和文本，投影输出。

MM-RoPE 说明:
    多模态旋转位置编码为视频和文本使用不同的频率缩放因子：
    - 视频（像素位置）：使用标准 3D RoPE 频率（θ=10000^(-2i/d)）。
    - 文本（语言位置）：使用更低的频率基（如 θ=10000^(-2i/d) * scale），
      使得文本位置编码变化更慢，适配语言序列的长程依赖特性。
"""

from typing import Optional, Tuple, Union
import torch
from einops import rearrange
from torch import nn
from torch.nn import functional as F
from torch.nn.modules.utils import _triple

from common.cache import Cache
from common.distributed.ops import gather_heads_scatter_seq, gather_seq_scatter_heads_qkv
from common.utils import safe_pad_operation
from ... import na
from ...attention import FlashAttentionVarlen
from ...mm import MMArg, MMModule
from ...normalization import norm_layer_type
from ...rope import get_na_rope
from ...window import get_window_op
from itertools import chain


class NaMMAttention(nn.Module):
    """NaDiT v2 多模态全局注意力，支持可选的多模态 RoPE 和 QK-Norm。

    将视频和文本 token 沿序列维拼接后，使用 Flash Attention v2 的变长 API
    做全局自注意力，每个样本的视频 token 可以关注所有视频和文本 token，
    文本 token 同理。支持视频/文本分支共享或独立投影权重。

    Args:
        vid_dim (int): 视频特征维度。
        txt_dim (int): 文本特征维度。
        heads (int): 注意力头数。
        head_dim (int): 每个注意力头的维度。
        qk_bias (bool): Q/K 投影是否使用偏置。
        qk_norm (norm_layer_type): Q/K 归一化层构造函数（如 RMSNorm）。
        qk_norm_eps (float): Q/K 归一化 epsilon。
        rope_type (Optional[str]): RoPE 类型，None 禁用，"normal" 视频-only，"mm" 多模态。
        rope_dim (int): RoPE 频率维度（通常为 head_dim // 2）。
        shared_weights (bool): 视频/文本分支是否共享 QKV/输出投影权重。
        **kwargs: 额外参数。

    Attributes:
        head_dim (int): 每头维度。
        proj_qkv (MMModule): QKV 投影层（双分支线性层）。
        proj_out (MMModule): 输出投影层（双分支线性层）。
        norm_q (MMModule): Q 归一化层（双分支）。
        norm_k (MMModule): K 归一化层（双分支）。
        rope: RoPE 位置编码实例（可能为 None）。
        attn (FlashAttentionVarlen): Flash Attention v2 变长实现。
    """

    def __init__(
        self,
        vid_dim: int,
        txt_dim: int,
        heads: int,
        head_dim: int,
        qk_bias: bool,
        qk_norm: norm_layer_type,
        qk_norm_eps: float,
        rope_type: Optional[str],
        rope_dim: int,
        shared_weights: bool,
        **kwargs,
    ):
        super().__init__()
        dim = MMArg(vid_dim, txt_dim)
        inner_dim = heads * head_dim
        qkv_dim = inner_dim * 3
        self.head_dim = head_dim
        self.proj_qkv = MMModule(
            nn.Linear, dim, qkv_dim, bias=qk_bias, shared_weights=shared_weights
        )
        self.proj_out = MMModule(nn.Linear, inner_dim, dim, shared_weights=shared_weights)
        self.norm_q = MMModule(
            qk_norm,
            dim=head_dim,
            eps=qk_norm_eps,
            elementwise_affine=True,
            shared_weights=shared_weights,
        )
        self.norm_k = MMModule(
            qk_norm,
            dim=head_dim,
            eps=qk_norm_eps,
            elementwise_affine=True,
            shared_weights=shared_weights,
        )

        self.rope = get_na_rope(rope_type=rope_type, dim=rope_dim)
        self.attn = FlashAttentionVarlen()

    def forward(
        self,
        vid: torch.FloatTensor,
        txt: torch.FloatTensor,
        vid_shape: torch.LongTensor,
        txt_shape: torch.LongTensor,
        cache: Cache,
    ) -> Tuple[
        torch.FloatTensor,
        torch.FloatTensor,
    ]:
        """前向传播，执行多模态全局注意力计算。

        Args:
            vid (torch.FloatTensor): 视频 token，展平形状 (sum_vid_len, vid_dim)。
            txt (torch.FloatTensor): 文本 token，展平形状 (sum_txt_len, txt_dim)。
            vid_shape (torch.LongTensor): 每个样本的视频网格大小 (b, 3)。
            txt_shape (torch.LongTensor): 每个样本的文本长度 (b, 1)。
            cache (Cache): 缓存对象，用于缓存 cu_seqlens、拼接索引等。

        Returns:
            Tuple[torch.FloatTensor, torch.FloatTensor]: (vid_out, txt_out) 元组，
                形状分别为 (sum_vid_len, vid_dim) 和 (sum_txt_len, txt_dim)。
        """
        vid_qkv, txt_qkv = self.proj_qkv(vid, txt)
        vid_qkv = gather_seq_scatter_heads_qkv(
            vid_qkv,
            seq_dim=0,
            qkv_shape=vid_shape,
            cache=cache.namespace("vid"),
        )
        txt_qkv = gather_seq_scatter_heads_qkv(
            txt_qkv,
            seq_dim=0,
            qkv_shape=txt_shape,
            cache=cache.namespace("txt"),
        )
        vid_qkv = rearrange(vid_qkv, "l (o h d) -> l o h d", o=3, d=self.head_dim)
        txt_qkv = rearrange(txt_qkv, "l (o h d) -> l o h d", o=3, d=self.head_dim)

        vid_q, vid_k, vid_v = vid_qkv.unbind(1)
        txt_q, txt_k, txt_v = txt_qkv.unbind(1)

        vid_q, txt_q = self.norm_q(vid_q, txt_q)
        vid_k, txt_k = self.norm_k(vid_k, txt_k)

        if self.rope:
            if self.rope.mm:
                vid_q, vid_k, txt_q, txt_k = self.rope(
                    vid_q, vid_k, vid_shape, txt_q, txt_k, txt_shape, cache
                )
            else:
                vid_q, vid_k = self.rope(vid_q, vid_k, vid_shape, cache)

        vid_len = cache("vid_len", lambda: vid_shape.prod(-1))
        txt_len = cache("txt_len", lambda: txt_shape.prod(-1))
        all_len = cache("all_len", lambda: vid_len + txt_len)

        concat, unconcat = cache("mm_pnp", lambda: na.concat_idx(vid_len, txt_len))

        attn = self.attn(
            q=concat(vid_q, txt_q).bfloat16(),
            k=concat(vid_k, txt_k).bfloat16(),
            v=concat(vid_v, txt_v).bfloat16(),
            cu_seqlens_q=cache("mm_seqlens", lambda: safe_pad_operation(all_len.cumsum(0), (1, 0)).int()),
            cu_seqlens_k=cache("mm_seqlens", lambda: safe_pad_operation(all_len.cumsum(0), (1, 0)).int()),
            max_seqlen_q=cache("mm_maxlen", lambda: all_len.max().item()),
            max_seqlen_k=cache("mm_maxlen", lambda: all_len.max().item()),
        ).type_as(vid_q)

        attn = rearrange(attn, "l h d -> l (h d)")
        vid_out, txt_out = unconcat(attn)
        vid_out = gather_heads_scatter_seq(vid_out, head_dim=1, seq_dim=0)
        txt_out = gather_heads_scatter_seq(txt_out, head_dim=1, seq_dim=0)

        vid_out, txt_out = self.proj_out(vid_out, txt_out)
        return vid_out, txt_out


class NaSwinAttention(NaMMAttention):
    """NaDiT v2 多模态窗口注意力（Swin 风格），支持变长序列和窗口分区。

    继承 NaMMAttention，将全局注意力替换为窗口注意力以降低计算复杂度：
    - 视频 token 沿 (T, H, W) 划分为不重叠的 3D 窗口。
    - 每个窗口内的视频 token 与全部文本 token 拼接（文本按窗口重复）。
    - 使用 Flash Attention v2 批量计算所有窗口的注意力。
    - 注意力后通过 window_reverse 将窗口 token 还原回原位置。

    窗口划分通过预计算索引实现，而非固定 reshape，因此支持任意视频分辨率
    （不要求是窗口大小的整数倍）。同时支持 MM-RoPE 在窗口内的正确应用。

    Args:
        *args: 传递给 NaMMAttention 的位置参数。
        window (Union[int, Tuple[int, int, int]]): 窗口大小 (t, h, w)。
        window_method (str): 窗口划分方法，"win"（按窗口数划分）或 "win_by_size"（按窗口大小划分）。
        **kwargs: 传递给 NaMMAttention 的关键字参数。

    Attributes:
        window (Tuple[int,int,int]): 窗口大小或窗口数量。
        window_method (str): 窗口划分方法。
        window_op: 窗口切片生成函数。
    """

    def __init__(
        self,
        *args,
        window: Union[int, Tuple[int, int, int]],
        window_method: str,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.window = _triple(window)
        self.window_method = window_method
        assert all(map(lambda v: isinstance(v, int) and v >= 0, self.window))

        self.window_op = get_window_op(window_method)

    def forward(
        self,
        vid: torch.FloatTensor,
        txt: torch.FloatTensor,
        vid_shape: torch.LongTensor,
        txt_shape: torch.LongTensor,
        cache: Cache,
    ) -> Tuple[
        torch.FloatTensor,
        torch.FloatTensor,
    ]:
        """前向传播，执行变长多模态窗口注意力计算。

        Args:
            vid (torch.FloatTensor): 视频 token，展平形状 (sum_vid_len, vid_dim)。
            txt (torch.FloatTensor): 文本 token，展平形状 (sum_txt_len, txt_dim)。
            vid_shape (torch.LongTensor): 每个样本的视频网格大小 (b, 3)。
            txt_shape (torch.LongTensor): 每个样本的文本长度 (b, 1)。
            cache (Cache): 缓存对象，用于缓存窗口索引、cu_seqlens 等。

        Returns:
            Tuple[torch.FloatTensor, torch.FloatTensor]: (vid_out, txt_out) 元组。
        """

        vid_qkv, txt_qkv = self.proj_qkv(vid, txt)
        vid_qkv = gather_seq_scatter_heads_qkv(
            vid_qkv,
            seq_dim=0,
            qkv_shape=vid_shape,
            cache=cache.namespace("vid"),
        )
        txt_qkv = gather_seq_scatter_heads_qkv(
            txt_qkv,
            seq_dim=0,
            qkv_shape=txt_shape,
            cache=cache.namespace("txt"),
        )

        cache_win = cache.namespace(f"{self.window_method}_{self.window}_sd3")

        def make_window(x: torch.Tensor):
            t, h, w, _ = x.shape
            window_slices = self.window_op((t, h, w), self.window)
            return [x[st, sh, sw] for (st, sh, sw) in window_slices]

        window_partition, window_reverse, window_shape, window_count = cache_win(
            "win_transform",
            lambda: na.window_idx(vid_shape, make_window),
        )
        vid_qkv_win = window_partition(vid_qkv)

        vid_qkv_win = rearrange(vid_qkv_win, "l (o h d) -> l o h d", o=3, d=self.head_dim)
        txt_qkv = rearrange(txt_qkv, "l (o h d) -> l o h d", o=3, d=self.head_dim)

        vid_q, vid_k, vid_v = vid_qkv_win.unbind(1)
        txt_q, txt_k, txt_v = txt_qkv.unbind(1)

        vid_q, txt_q = self.norm_q(vid_q, txt_q)
        vid_k, txt_k = self.norm_k(vid_k, txt_k)

        txt_len = cache("txt_len", lambda: txt_shape.prod(-1))

        vid_len_win = cache_win("vid_len", lambda: window_shape.prod(-1))
        txt_len_win = cache_win("txt_len", lambda: txt_len.repeat_interleave(window_count))
        all_len_win = cache_win("all_len", lambda: vid_len_win + txt_len_win)
        concat_win, unconcat_win = cache_win(
            "mm_pnp", lambda: na.repeat_concat_idx(vid_len_win, txt_len, window_count)
        )

        if self.rope:
            if self.rope.mm:
                _, num_h, _ = txt_q.shape
                txt_q_repeat = rearrange(txt_q, "l h d -> l (h d)")
                txt_q_repeat = na.unflatten(txt_q_repeat, txt_shape)
                txt_q_repeat = [[x] * n for x, n in zip(txt_q_repeat, window_count)]
                txt_q_repeat = list(chain(*txt_q_repeat))
                txt_q_repeat, txt_shape_repeat = na.flatten(txt_q_repeat)
                txt_q_repeat = rearrange(txt_q_repeat, "l (h d) -> l h d", h=num_h)

                txt_k_repeat = rearrange(txt_k, "l h d -> l (h d)")
                txt_k_repeat = na.unflatten(txt_k_repeat, txt_shape)
                txt_k_repeat = [[x] * n for x, n in zip(txt_k_repeat, window_count)]
                txt_k_repeat = list(chain(*txt_k_repeat))
                txt_k_repeat, _ = na.flatten(txt_k_repeat)
                txt_k_repeat = rearrange(txt_k_repeat, "l (h d) -> l h d", h=num_h)

                vid_q, vid_k, txt_q, txt_k = self.rope(
                    vid_q, vid_k, window_shape, txt_q_repeat, txt_k_repeat, txt_shape_repeat, cache_win
                )
            else:
                vid_q, vid_k = self.rope(vid_q, vid_k, window_shape, cache_win)
            
        out = self.attn(
            q=concat_win(vid_q, txt_q).bfloat16(),
            k=concat_win(vid_k, txt_k).bfloat16(),
            v=concat_win(vid_v, txt_v).bfloat16(),
            cu_seqlens_q=cache_win(
                "vid_seqlens_q", lambda: safe_pad_operation(all_len_win.cumsum(0), (1, 0)).int()
            ),
            cu_seqlens_k=cache_win(
                "vid_seqlens_k", lambda: safe_pad_operation(all_len_win.cumsum(0), (1, 0)).int()
            ),
            max_seqlen_q=cache_win("vid_max_seqlen_q", lambda: all_len_win.max().item()),
            max_seqlen_k=cache_win("vid_max_seqlen_k", lambda: all_len_win.max().item()),
        ).type_as(vid_q)

        vid_out, txt_out = unconcat_win(out)

        vid_out = rearrange(vid_out, "l h d -> l (h d)")
        txt_out = rearrange(txt_out, "l h d -> l (h d)")
        vid_out = window_reverse(vid_out)

        vid_out = gather_heads_scatter_seq(vid_out, head_dim=1, seq_dim=0)
        txt_out = gather_heads_scatter_seq(txt_out, head_dim=1, seq_dim=0)

        vid_out, txt_out = self.proj_out(vid_out, txt_out)

        return vid_out, txt_out

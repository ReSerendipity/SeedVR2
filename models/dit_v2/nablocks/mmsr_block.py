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

"""NaDiT v2 MMSR (Multi-Modal Swin Restorer) Transformer Block 模块。

实现 NaDiT v2 版本的变长窗口注意力 Transformer block，相比 v1 的主要改进：

- **支持 vid-only 最后层**：在最后几层可以禁用文本分支，仅处理视频 token，
  通过 MMModule 的 vid_only 参数实现，节省计算和显存。
- **共享/独立权重控制**：支持视频和文本分支共享或独立 QKV/MLP/AdaLN 权重。
- **多模态 RoPE (MM-RoPE)**：支持对视频和文本分别应用不同频率缩放的 RoPE，
  像素位置使用高频率，语言位置使用低频率，适配多模态位置编码。
- **可选窗口/全局注意力**：通过 NaMMAttention (全局) 和 NaSwinAttention (窗口)
  两种注意力实现，支持混合注意力架构。
- **梯度检查点支持**：可通过外层包装启用梯度检查点以节省训练显存。

Block 结构遵循 Pre-Norm AdaLN-Zero 设计：
    1. AdaLN 调制 (shift+scale) → 注意力 → AdaLN 门控 (gate) → 残差
    2. AdaLN 调制 (shift+scale) → MLP → AdaLN 门控 (gate) → 残差
"""

from typing import Tuple
import torch
import torch.nn as nn

from common.cache import Cache

from .attention.mmattn import NaSwinAttention
from ..mm import MMArg
from ..modulation import ada_layer_type
from ..normalization import norm_layer_type
from ..mm import MMArg, MMModule
from ..mlp import get_mlp
    

class NaMMSRTransformerBlock(nn.Module):
    """NaDiT v2 MMSR Transformer block，支持共享/独立权重和 vid-only MLP。

    完整的 Pre-Norm Transformer block，集成 NaSwinAttention 变长窗口注意力、
    多模态 MLP、AdaLN-Zero 自适应调制，支持视频/文本分支权重共享和
    最后层 vid-only 模式。

    Args:
        vid_dim (int): 视频特征维度。
        txt_dim (int): 文本特征维度。
        emb_dim (int): 时间步嵌入维度（6*dim for AdaSingle）。
        heads (int): 注意力头数。
        head_dim (int): 每个注意力头的维度。
        expand_ratio (int): MLP 隐藏层扩展倍数。
        norm (norm_layer_type): 归一化层构造函数（如 LayerNorm/RMSNorm）。
        norm_eps (float): 归一化 epsilon 值。
        ada (ada_layer_type): AdaLN 自适应调制层构造函数。
        qk_bias (bool): Q/K 投影是否使用偏置。
        qk_norm (norm_layer_type): Q/K 归一化层构造函数。
        mlp_type (str): MLP 类型，"normal" 或 "swiglu"。
        shared_weights (bool): 视频/文本分支是否共享 QKV/MLP/AdaLN 权重。
        rope_type (str): RoPE 类型，"normal" (视频-only) 或 "mm" (多模态)。
        rope_dim (int): RoPE 频率维度（通常为 head_dim // 2）。
        is_last_layer (bool): 是否为最后一层，启用 vid-only 模式（禁用文本分支）。
        **kwargs: 额外参数，包含 window (窗口大小)、window_method (窗口划分方法)。

    Attributes:
        attn_norm (MMModule): 注意力前归一化层（双分支，支持共享/独立）。
        attn (NaSwinAttention): 多模态变长窗口注意力层。
        mlp_norm (MMModule): MLP 前归一化层（支持 vid-only）。
        mlp (MMModule): MLP 层（支持 vid-only）。
        ada (MMModule): AdaLN 自适应调制层（支持 vid-only）。
        is_last_layer (bool): 是否为最后一层标记。
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
        qk_norm: norm_layer_type,
        mlp_type: str,
        shared_weights: bool,
        rope_type: str,
        rope_dim: int,
        is_last_layer: bool,
        **kwargs,
    ):
        super().__init__()
        dim = MMArg(vid_dim, txt_dim)
        self.attn_norm = MMModule(norm, dim=dim, eps=norm_eps, elementwise_affine=False, shared_weights=shared_weights,)

        self.attn = NaSwinAttention(
            vid_dim=vid_dim,
            txt_dim=txt_dim,
            heads=heads,
            head_dim=head_dim,
            qk_bias=qk_bias,
            qk_norm=qk_norm,
            qk_norm_eps=norm_eps,
            rope_type=rope_type,
            rope_dim=rope_dim,
            shared_weights=shared_weights,
            window=kwargs.pop("window", None),
            window_method=kwargs.pop("window_method", None),
        )

        self.mlp_norm = MMModule(norm, dim=dim, eps=norm_eps, elementwise_affine=False, shared_weights=shared_weights, vid_only=is_last_layer)
        self.mlp = MMModule(
            get_mlp(mlp_type),
            dim=dim,
            expand_ratio=expand_ratio,
            shared_weights=shared_weights,
            vid_only=is_last_layer
        )
        self.ada = MMModule(ada, dim=dim, emb_dim=emb_dim, layers=["attn", "mlp"], shared_weights=shared_weights, vid_only=is_last_layer)
        self.is_last_layer = is_last_layer

    def forward(
        self,
        vid: torch.FloatTensor,
        txt: torch.FloatTensor,
        vid_shape: torch.LongTensor,
        txt_shape: torch.LongTensor,
        emb: torch.FloatTensor,
        cache: Cache,
    ) -> Tuple[
        torch.FloatTensor,
        torch.FloatTensor,
        torch.LongTensor,
        torch.LongTensor,
    ]:
        """前向传播，执行完整的 NaDiT v2 Transformer block 计算。

        Args:
            vid (torch.FloatTensor): 视频 token，展平形状 (sum_vid_len, vid_dim)。
            txt (torch.FloatTensor): 文本 token，展平形状 (sum_txt_len, txt_dim)。
            vid_shape (torch.LongTensor): 每个样本的视频网格大小 (b, 3)，即 (T, H, W) 网格数。
            txt_shape (torch.LongTensor): 每个样本的文本长度 (b, 1)。
            emb (torch.FloatTensor): 时间步嵌入，形状 (b, emb_dim)。
            cache (Cache): 缓存对象，用于缓存窗口索引、cu_seqlens 等重复计算结果。

        Returns:
            Tuple[torch.FloatTensor, torch.FloatTensor, torch.LongTensor, torch.LongTensor]:
                (vid_out, txt_out, vid_shape, txt_shape) 元组，保持 shape 传递以支持链式调用。
                若为最后一层（vid_only=True），txt_out 为输入 txt 不变。
        """
        hid_len = MMArg(
            cache("vid_len", lambda: vid_shape.prod(-1)),
            cache("txt_len", lambda: txt_shape.prod(-1)),
        )
        ada_kwargs = {
            "emb": emb,
            "hid_len": hid_len,
            "cache": cache,
            "branch_tag": MMArg("vid", "txt"),
        }

        vid_attn, txt_attn = self.attn_norm(vid, txt)
        vid_attn, txt_attn = self.ada(vid_attn, txt_attn, layer="attn", mode="in", **ada_kwargs)
        vid_attn, txt_attn = self.attn(vid_attn, txt_attn, vid_shape, txt_shape, cache)
        vid_attn, txt_attn = self.ada(vid_attn, txt_attn, layer="attn", mode="out", **ada_kwargs)
        vid_attn, txt_attn = (vid_attn + vid), (txt_attn + txt)

        vid_mlp, txt_mlp = self.mlp_norm(vid_attn, txt_attn)
        vid_mlp, txt_mlp = self.ada(vid_mlp, txt_mlp, layer="mlp", mode="in", **ada_kwargs)
        vid_mlp, txt_mlp = self.mlp(vid_mlp, txt_mlp)
        vid_mlp, txt_mlp = self.ada(vid_mlp, txt_mlp, layer="mlp", mode="out", **ada_kwargs)
        vid_mlp, txt_mlp = (vid_mlp + vid_attn), (txt_mlp + txt_attn)

        return vid_mlp, txt_mlp, vid_shape, txt_shape

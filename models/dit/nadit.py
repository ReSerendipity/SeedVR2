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

"""NaDiT (Native Resolution Diffusion Transformer) 模型。

支持原生分辨率/变长序列的视频扩散 Transformer 架构：

- **NaPatchifyEmbed**: 支持变长输入的 Patch 嵌入，将不同尺寸的视频批处理到一起。
- **NaRoPE**: 变长版本的 3D RoPE，支持每个样本有不同的 t/h/w 网格。
- **NaDiT**: NaDiT 主模型，支持任意分辨率、任意长度视频输入。
- **NaDiTConfig**: NaDiT 配置类。

NaDiT 核心思想:
    传统 DiT 要求所有输入视频具有相同的分辨率和帧数，需要裁剪/resize/padding，
    这既损失信息又浪费计算。NaDiT 通过以下机制支持原生分辨率：

    1. **变长注意力**: 使用 Flash Attention v2 的变长序列 API (cu_seqlens)，
       batch 内每个样本可以有不同的 token 数量，无需 padding 到相同长度。
    2. **动态位置编码**: RoPE 位置编码根据每个样本的实际 t/h/w 动态生成。
    3. **变长 Patch 化**: Patch 嵌入和恢复支持不同尺寸输入，使用累积长度索引。
    4. **MMSR Block**: 多模态 Swin 风格窗口注意力块，同时支持视频和文本联合注意力。
"""

from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F
from einops import rearrange
from models.common.context_parallel import (
    get_context_parallel_group,
    initialize_context_parallel,
)
from models.common.fp8 import FP8Linear, apply_fp8_linear_optimization, is_fp8_enabled
from models.common.moe import build_moe_layer

from common.cache import Cache

from .embedding import TimeEmbedding, emb_add
from .modulation import get_ada_layer
from .na import na_concat, na_split, unpatchify
from .nablocks import get_na_block
from .normalization import get_norm_layer
from .rope import apply_rope


def initialize_linear(in_features: int, out_features: int, bias: bool = True, fp8: bool = False) -> nn.Module:
    """创建线性层，支持 FP8 量化。

    Args:
        in_features (int): 输入特征维度。
        out_features (int): 输出特征维度。
        bias (bool): 是否使用偏置，默认 True。
        fp8 (bool): 是否使用 FP8 线性层，默认 False。

    Returns:
        nn.Module: 线性层实例。
    """
    if fp8 and is_fp8_enabled():
        return FP8Linear(in_features, out_features, bias=bias)
    return nn.Linear(in_features, out_features, bias=bias)


@dataclass
class NaDiTConfig:
    """NaDiT 模型配置。

    Attributes:
        in_channels (int): 输入视频通道数。
        patch_size (Tuple[int, int, int]): Patch 大小 (p_t, p_h, p_w)。
        depth (int): Transformer 块层数。
        dim (int): 隐藏维度。
        num_heads (int): 注意力头数。
        mlp_expand_ratio (int): MLP 扩展倍数，默认 4。
        mlp_type (str): MLP 类型，"normal" 或 "swiglu"。
        norm_type (Optional[str]): 归一化类型。
        ada_layer (str): 自适应调制层类型。
        text_dim (int): 文本嵌入维度。
        rope_theta_t/theta_h/theta_w (int): RoPE 各轴频率基。
        rope_dim (Optional[str]): RoPE 维度分配。
        max_seqlen_t/h/w (int): 各轴最大序列长度。
        block_type (str): Transformer 块类型。
        window_size (Optional[Tuple[int,int,int]]): 窗口注意力窗口大小。
        window_step (Optional[int]): 窗口步长。
        na_moe (Optional[dict]): MoE 配置。
        fp8 (bool): 是否启用 FP8。
    """

    in_channels: int = 16
    patch_size: tuple[int, int, int] = (1, 2, 2)
    depth: int = 12
    dim: int = 1024
    num_heads: int = 16
    mlp_expand_ratio: int = 4
    mlp_type: str = "normal"
    norm_type: str | None = "layer"
    ada_layer: str = "single"
    text_dim: int = 4096
    rope_theta_t: int = 3600
    rope_theta_h: int = 3600
    rope_theta_w: int = 3600
    rope_dim: str | None = None
    max_seqlen_t: int = 4096
    max_seqlen_h: int = 4096
    max_seqlen_w: int = 4096
    block_type: str = "mmsr"
    window_size: tuple[int, int, int] | None = None
    window_step: int | None = None
    na_moe: dict | None = None
    fp8: bool = False


class NaPatchifyEmbed(nn.Module):
    """支持变长输入的 Patch 嵌入层。

    使用 3D 卷积作为 patch 投影，支持将不同尺寸的视频样本批处理。
    """

    def __init__(self, in_channels: int, dim: int, patch_size: tuple[int, int, int] = (1, 2, 2)):
        super().__init__()
        self.patch_size = patch_size
        self.proj = nn.Conv3d(in_channels, dim, kernel_size=patch_size, stride=patch_size)

    def forward(self, x: torch.FloatTensor, window_sizes: torch.LongTensor):
        """前向传播，对变长视频列表做 patch 嵌入。

        Args:
            x: 视频列表或批量张量。
            window_sizes (torch.LongTensor): 每个样本的 patch 网格数 (b, 3)。

        Returns:
            torch.FloatTensor: 拼接的 patch token，形状 (sum_len, dim)。
        """
        if isinstance(x, list):
            outs = []
            for xi in x:
                outs.append(self.proj(xi))
            return torch.cat([rearrange(o, "b c t h w -> b (t h w) c") for o in outs], dim=1).squeeze(0)
        else:
            wt, wh, ww = self.patch_size
            return rearrange(self.proj(x), "b c t h w -> (b t h w) c")


class NaRoPE(nn.Module):
    """变长版本的 3D 旋转位置编码。

    支持每个样本有不同的 t/h/w 网格大小，根据 window_sizes 动态生成频率。
    """

    def __init__(self, dim: int, theta_t=3600, theta_h=3600, theta_w=3600, rope_dim=None):
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

    def precompute_freqs_cis(self, dim, max_seqlen, theta):
        """预计算频率张量。"""
        freqs = 1.0 / (theta ** (torch.arange(0, dim, 2, dtype=torch.float64, device="cuda") / dim))
        t = torch.arange(max_seqlen, dtype=torch.float64, device="cuda")
        freqs = torch.outer(t, freqs).float()
        return torch.polar(torch.ones_like(freqs), freqs)

    def get_freqs_cis(self, nt, nh, nw):
        """获取指定网格大小的频率张量。"""
        ft = self.precompute_freqs_cis(self.dim_t, nt, self.theta_t).reshape(nt, 1, 1, self.dim_t // 2)
        fh = self.precompute_freqs_cis(self.dim_h, nh, self.theta_h).reshape(1, nh, 1, self.dim_h // 2)
        fw = self.precompute_freqs_cis(self.dim_w, nw, self.theta_w).reshape(1, 1, nw, self.dim_w // 2)
        ft = ft.repeat(1, nh, nw, 1)
        fh = fh.repeat(nt, 1, nw, 1)
        fw = fw.repeat(nt, nh, 1, 1)
        return torch.cat([ft, fh, fw], dim=-1).reshape(nt * nh * nw, -1)

    def forward(self, x, window_sizes, branch="vid", cache=None):
        """前向传播，应用变长 RoPE。

        Args:
            x: query/key 张量。
            window_sizes: 每个样本的 (nt, nh, nw)。
            branch: 分支类型。
            cache: 缓存对象。

        Returns:
            应用 RoPE 后的张量。
        """
        b = window_sizes.shape[0]
        if branch == "txt":
            x.shape[0] if b == 0 else None
        nw_cu = F.pad((window_sizes[:, 0] * window_sizes[:, 1] * window_sizes[:, 2]).cumsum(0), (1, 0))
        freq_list = []
        for i in range(b):
            nt, nh, nw = window_sizes[i].tolist()
            if cache is not None:
                freq_list.append(
                    cache(f"freqs_{nt}_{nh}_{nw}", lambda nt=nt, nh=nh, nw=nw: self.get_freqs_cis(nt, nh, nw))
                )
            else:
                freq_list.append(self.get_freqs_cis(nt, nh, nw))
        if branch == "txt" and b > 0:
            txt_start = nw_cu[-1].item()
            txt_len = x.shape[0] - txt_start
            freq_list.append(self.get_freqs_cis(txt_len, 1, 1))
        freqs = torch.cat(freq_list, dim=0)
        return apply_rope(x.unsqueeze(0), freqs=freqs).squeeze(0)


class NaDiT(nn.Module):
    """NaDiT (Native Resolution Diffusion Transformer) 主模型。

    支持任意分辨率、任意长度视频的扩散 Transformer，采用 AdaLN-Zero 调制、
    3D RoPE 位置编码、窗口/全局注意力混合、可选 MoE 结构。

    Args:
        config (NaDiTConfig): 模型配置。
    """

    def __init__(self, config: NaDiTConfig):
        super().__init__()
        self.config = config
        self.in_channels = config.in_channels
        self.out_channels = config.in_channels
        self.patch_size = config.patch_size
        self.depth = config.depth
        self.dim = config.dim
        self.num_heads = config.num_heads
        self.head_dim = config.dim // config.num_heads

        self.patch_embed = NaPatchifyEmbed(config.in_channels, config.dim, config.patch_size)
        self.time_embed = TimeEmbedding(config.dim)
        self.text_proj = nn.Sequential(
            nn.SiLU(),
            initialize_linear(config.text_dim, config.dim, fp8=config.fp8),
        )
        self.rotary_emb = NaRoPE(
            self.head_dim,
            theta_t=config.rope_theta_t,
            theta_h=config.rope_theta_h,
            theta_w=config.rope_theta_w,
            rope_dim=config.rope_dim,
        )

        norm_layer = get_norm_layer(config.norm_type)
        ada_layer = get_ada_layer(config.ada_layer)

        self.blocks = nn.ModuleList()
        for i in range(config.depth):
            block_cfg = {
                "dim": config.dim,
                "num_heads": config.num_heads,
                "mlp_expand_ratio": config.mlp_expand_ratio,
                "mlp_type": config.mlp_type,
                "norm_layer": norm_layer,
                "ada_layer": ada_layer,
                "window_size": config.window_size,
                "window_step": config.window_step,
                "block_id": i,
                "fp8": config.fp8,
            }
            if config.na_moe is not None and i in config.na_moe["mlp_layers"]:
                block_cfg["mlp_layer"] = build_moe_layer(config.na_moe, config.dim, config.mlp_expand_ratio)
            self.blocks.append(get_na_block(config.block_type)(**block_cfg))

        self.norm_out = norm_layer(config.dim, eps=1e-6, elementwise_affine=False)
        self.out_proj = nn.Sequential(
            nn.SiLU(),
            initialize_linear(
                config.dim,
                self.out_channels * config.patch_size[0] * config.patch_size[1] * config.patch_size[2],
                fp8=config.fp8,
            ),
        )
        self.ada_final = ada_layer(config.dim, 6 * config.dim, ["mod_out"])

        if config.fp8:
            apply_fp8_linear_optimization(self)
        initialize_context_parallel(get_context_parallel_group(), 2, False)

    def forward(
        self,
        x: torch.FloatTensor,
        timesteps: torch.LongTensor,
        text_emb: torch.FloatTensor,
        window_sizes: torch.LongTensor,
        txt_lens: torch.LongTensor,
        **kwargs,
    ) -> torch.FloatTensor:
        """NaDiT 前向传播。

        Args:
            x (torch.FloatTensor): 输入视频张量（已 patch 化后为 (sum_vid, c) 列表）。
            timesteps (torch.LongTensor): 扩散时间步，形状 (b,)。
            text_emb (torch.FloatTensor): 文本嵌入，形状 (sum_txt, text_dim)。
            window_sizes (torch.LongTensor): 每个样本的视频 patch 网格数 (b, 3)。
            txt_lens (torch.LongTensor): 每个样本的文本 token 长度 (b,)。
            **kwargs: 额外参数。

        Returns:
            List[torch.FloatTensor]: 每个样本的输出视频噪声预测列表。
        """
        cache = Cache(disable=False)
        b = window_sizes.shape[0]
        vid_lens = window_sizes[:, 0] * window_sizes[:, 1] * window_sizes[:, 2]

        x_vid = self.patch_embed(x, window_sizes)
        x_txt = self.text_proj(F.silu(text_emb))

        t_emb = self.time_embed(timesteps)

        x, cu_seqlens, seq_lens = na_concat(x_vid, x_txt, vid_lens, txt_lens)
        x = emb_add(x, t_emb, vid_lens, txt_lens)

        for i, block in enumerate(self.blocks):
            x = block(x, t_emb, self.rotary_emb, cu_seqlens, seq_lens, window_sizes, txt_lens, cache, i)

        x = x.view(-1, self.dim)
        x = self.ada_final(x, t_emb, "mod_out", "in", cache=cache, hid_len=seq_lens)
        x = self.norm_out(x)
        x = self.ada_final(x, t_emb, "mod_out", "out", cache=cache, hid_len=seq_lens)
        x = self.out_proj(x)

        x_vid, x_txt = na_split(x.view(b, -1, x.shape[-1]), vid_lens, txt_lens)
        return unpatchify(x_vid, window_sizes, self.patch_size)

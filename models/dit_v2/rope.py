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

"""多模态 3D 旋转位置编码 (MM-RoPE)。

v2 版本的 RoPE 相比 v1 做了关键升级：

- **MMRotaryEmbedding3d**: 为像素(vid)和语言(txt)分支使用不同的频率基和维度分配，
  像素分支分配更多维度给空间维度，语言分支使用 1D RoPE。
- **NaRoPE3d**: 封装底层频率生成，提供注意力层期望的直接 Q/K 旋转接口。
- 频率计算与 v1 相同，但通过 ``get_freqs`` 的 is_pixel 参数区分两套参数。
- cos/sin 支持 flatten 到 1D 位置索引，兼容变长序列的 positions 索引计算。
"""

from typing import Optional, Tuple, List
import torch
from torch import nn


def _build_3d_positions(shape: torch.LongTensor, device: torch.device) -> List[torch.Tensor]:
    """根据 (b, 3) 的 vid_shape 生成每个样本的 3D 位置索引列表。"""
    positions_list = []
    for i in range(shape.shape[0]):
        t, h, w = shape[i].tolist()
        ft = torch.arange(t, device=device)
        fh = torch.arange(h, device=device)
        fw = torch.arange(w, device=device)
        grid_t, grid_h, grid_w = torch.meshgrid(ft, fh, fw, indexing='ij')
        pos = torch.stack([grid_t.flatten(), grid_h.flatten(), grid_w.flatten()], dim=-1)
        positions_list.append(pos)
    return positions_list


def get_freqs(
    dim: int,
    axes_dim: Tuple[int, int, int],
    theta: float = 10000.0,
) -> Tuple[torch.FloatTensor]:
    """生成三个轴的频率基（内部使用，对 vid/txt 分别配置）。"""
    axes_freqs = []
    for i in range(3):
        ax_dim = axes_dim[i]
        ax_theta = theta
        freqs = 1.0 / (
            ax_theta
            ** (torch.arange(0, ax_dim, 2, dtype=torch.float32) / ax_dim)
        )
        axes_freqs.append(freqs)
    return axes_freqs


def precompute_freqs_cis_3d(
    t: int,
    h: int,
    w: int,
    dim: int,
    axes_dim: Tuple[int, int, int],
    theta: float = 10000.0,
    pixel_theta: float = 10000.0,
    language_theta: float = 10000.0,
):
    """预计算 3D 网格的 RoPE cos/sin 复数旋转表。

    Args:
        t/h/w: 时间/高度/宽度网格数。
        dim: head_dim 总维度。
        axes_dim: vid 分支三 (t,h,w) 维度分配。
        theta/pixel_theta/language_theta: 不同分支的频率基。
    """
    ft = torch.arange(t, dtype=torch.float32)
    fh = torch.arange(h, dtype=torch.float32)
    fw = torch.arange(w, dtype=torch.float32)

    freqs_t, freqs_h, freqs_w = get_freqs(dim, axes_dim, theta=pixel_theta)

    freqs_t = torch.outer(ft, freqs_t)
    freqs_h = torch.outer(fh, freqs_h)
    freqs_w = torch.outer(fw, freqs_w)
    freqs = torch.cat(
        [
            freqs_t[:, None, None, :].expand(-1, h, w, -1),
            freqs_h[None, :, None, :].expand(t, -1, w, -1),
            freqs_w[None, None, :, :].expand(t, h, -1, -1),
        ],
        dim=-1,
    )
    freqs_cis = torch.polar(torch.ones_like(freqs), freqs)  # complex64

    return freqs_cis


def precompute_freqs_cis_1d(l, dim, theta):
    """预计算 1D 序列（文本）的 RoPE 旋转表。"""
    ft = torch.arange(l, dtype=torch.float32)
    freqs = 1.0 / (theta ** (torch.arange(0, dim, 2, dtype=torch.float32) / dim))
    freqs = torch.outer(ft, freqs)
    freqs_cis = torch.polar(torch.ones_like(freqs), freqs)
    return freqs_cis


def reshape_for_broadcast(freqs_cis: torch.Tensor, x: torch.Tensor):
    """将 freqs_cis reshape 为可与 Q/K 广播的形状。"""
    ndim = x.ndim
    shape = [1] * ndim
    shape[-2] = freqs_cis.shape[0]
    shape[-1] = freqs_cis.shape[-1]
    return freqs_cis.view(*shape)


def flatten_3d_freqs(freqs_cis_3d, positions):
    """根据 (b, n, 3) 位置索引从 3D 网格 cos/sin 中取 flatten 后的 1D 频率。

    Args:
        freqs_cis_3d: (t, h, w, head_dim/2) 复数旋转表。
        positions: (b, n, 3) 整数位置索引。

    Returns:
        (b, n, head_dim/2) 复数旋转值。
    """
    t = positions[:, :, 0]
    h = positions[:, :, 1]
    w = positions[:, :, 2]
    freqs = freqs_cis_3d[t, h, w]
    return freqs


def apply_rotary_emb(xq, xk, freqs_cis, text_freqs_cis=None, pixel_shape=None):
    """将 RoPE 旋转应用到 Q/K，支持 vid+txt 拼接的多模态场景。

    Args:
        xq/xk: Q/K 张量 (total, n_heads, head_dim)，实值。
        freqs_cis: vid 分支旋转表 (total_pixel, head_dim/2) 复数。
        text_freqs_cis: txt 分支旋转表 (total_text, head_dim/2) 复数，可选。
        pixel_shape: (t,h,w) 像素网格形状，用于 3D 广播（未使用）。

    Returns:
        (xq_out, xk_out) 旋转后的实值张量，与输入形状相同。
    """
    n_pixel = freqs_cis.shape[0]
    if text_freqs_cis is not None:
        freqs_cis = torch.cat([freqs_cis, text_freqs_cis], dim=0)
    xq_ = torch.view_as_complex(xq.float().reshape(*xq.shape[:-1], -1, 2))
    xk_ = torch.view_as_complex(xk.float().reshape(*xk.shape[:-1], -1, 2))
    freqs_cis = reshape_for_broadcast(freqs_cis, xq_)
    xq_out = torch.view_as_real(xq_ * freqs_cis).flatten(-2)
    xk_out = torch.view_as_real(xk_ * freqs_cis).flatten(-2)
    return xq_out.type_as(xq), xk_out.type_as(xk)


class MMRotaryEmbedding3d(torch.nn.Module):
    """多模态 3D RoPE 模块，分别维护 vid（像素）和 txt（语言）两套频率参数。

    Args:
        dim: head_dim 总维度。
        axes_dim: vid 分支 (t,h,w) 维度分配元组，如 (32,96,96)。
        theta: 基础 theta。
        pixel_theta: 像素分支 theta。
        language_theta: 语言 1D RoPE 的 theta。
        max_lengths: 预计算的最大 (t,h,w,seq_len)。
    """

    def __init__(
        self,
        dim: int = 2048,
        axes_dim: Tuple[int, int, int] = None,
        theta: float = 10000.0,
        pixel_theta: float = 10000.0,
        language_theta: float = 10000.0,
        max_lengths: Tuple[int, int, int, int] = (1024, 128, 128, 4096),
    ):
        super().__init__()
        self.dim = dim
        self.theta = theta
        self.pixel_theta = pixel_theta
        self.language_theta = language_theta
        if axes_dim is None:
            t = dim // 9
            h = dim * 4 // 9
            t = t - (t % 2)
            h = h - (h % 2)
            w = dim - t - h
            if w % 2 != 0:
                w -= 1
                if t + h + w != dim:
                    w = dim - t - h
                    if w % 2 != 0:
                        t += 2 if t + 2 <= dim - h else 0
                        w = dim - t - h
            axes_dim = (t, h, w)
        self.axes_dim = axes_dim
        self.max_t, self.max_h, self.max_w, self.max_l = max_lengths
        self._register_buffers()

    def _register_buffers(self):
        """预计算并注册 vid 3D 频率和 txt 1D 频率为 persistent buffer。"""
        freqs_cis_3d = precompute_freqs_cis_3d(
            self.max_t, self.max_h, self.max_w,
            self.dim, self.axes_dim, self.theta, self.pixel_theta, self.language_theta,
        )
        self.register_buffer("freqs_cis_3d", freqs_cis_3d, persistent=False)

        language_dim = sum(self.axes_dim)
        language_freqs_cis_1d = precompute_freqs_cis_1d(self.max_l, language_dim, self.language_theta)
        self.register_buffer("language_freqs_cis_1d", language_freqs_cis_1d, persistent=False)

    def forward(self, positions, cu_seqlens_txt=None, n_txt_per_sample=None):
        """根据像素位置索引和文本序列长度生成 flatten 频率。

        Args:
            positions: (b, n_pixel, 3) 整数位置索引。
            cu_seqlens_txt: 文本累积序列长度。
            n_txt_per_sample: 每个样本的文本序列长度。

        Returns:
            (pixel_freqs, text_freqs)；text_freqs 可能为 None。
        """
        pixel_freqs = flatten_3d_freqs(self.freqs_cis_3d, positions)
        pixel_freqs = pixel_freqs.flatten(0, 1)

        text_freqs = None
        if cu_seqlens_txt is not None and n_txt_per_sample is not None:
            max_n_txt = n_txt_per_sample.max().item()
            language_freqs_cis_1d = self.language_freqs_cis_1d[:max_n_txt]
            text_freqs = language_freqs_cis_1d.unsqueeze(0).expand(positions.shape[0], -1, -1)
            text_freqs = text_freqs.flatten(0, 1)

        return pixel_freqs, text_freqs


class NaRoPE3d(nn.Module):
    """NaDiT v2 3D RoPE 应用模块，封装 MMRotaryEmbedding3d 并提供注意力层期望的调用接口。

    Args:
        emb: MMRotaryEmbedding3d 底层频率生成模块。
        mm: 是否为多模态（MM）模式。
    """

    def __init__(self, emb: MMRotaryEmbedding3d, mm: bool = False):
        super().__init__()
        self.emb = emb
        self.mm = mm

    def _apply_vid_rope(self, xq, xk, vid_shape, cache):
        """对视频 Q/K 应用 3D RoPE。"""
        device = xq.device
        b = vid_shape.shape[0]

        def _get_freqs():
            positions_list = _build_3d_positions(vid_shape, device)
            pixel_freqs_list = []
            for pos in positions_list:
                pf = self.emb.freqs_cis_3d[pos[:, 0], pos[:, 1], pos[:, 2]]
                pixel_freqs_list.append(pf)
            return pixel_freqs_list

        pixel_freqs_list = cache("rope_pixel_freqs", _get_freqs)

        cu_lens = torch.nn.functional.pad(vid_shape.prod(-1).cumsum(0), (1, 0))
        xq_out_parts = []
        xk_out_parts = []
        for i in range(b):
            start = cu_lens[i].item()
            end = cu_lens[i + 1].item()
            freqs = pixel_freqs_list[i]
            xq_i = xq[start:end].unsqueeze(0)
            xk_i = xk[start:end].unsqueeze(0)
            freqs_b = reshape_for_broadcast(freqs.unsqueeze(0), xq_i)
            xq_i_c = torch.view_as_complex(xq_i.float().reshape(*xq_i.shape[:-1], -1, 2))
            xk_i_c = torch.view_as_complex(xk_i.float().reshape(*xk_i.shape[:-1], -1, 2))
            xq_o = torch.view_as_real(xq_i_c * freqs_b).flatten(-2).type_as(xq)
            xk_o = torch.view_as_real(xk_i_c * freqs_b).flatten(-2).type_as(xk)
            xq_out_parts.append(xq_o.squeeze(0))
            xk_out_parts.append(xk_o.squeeze(0))
        return torch.cat(xq_out_parts, dim=0), torch.cat(xk_out_parts, dim=0)

    def _apply_txt_rope(self, xq, xk, txt_lengths, cache):
        """对文本 Q/K 应用 1D RoPE。"""
        device = xq.device
        b = txt_lengths.shape[0]

        def _get_freqs():
            max_l = txt_lengths.max().item()
            return self.emb.language_freqs_cis_1d[:max_l]

        lang_freqs = cache("rope_lang_freqs", _get_freqs)
        cu_lens = torch.nn.functional.pad(txt_lengths.cumsum(0), (1, 0))
        xq_out_parts = []
        xk_out_parts = []
        for i in range(b):
            start = cu_lens[i].item()
            end = cu_lens[i + 1].item()
            l = end - start
            freqs = lang_freqs[:l]
            xq_i = xq[start:end].unsqueeze(0)
            xk_i = xk[start:end].unsqueeze(0)
            freqs_b = reshape_for_broadcast(freqs.unsqueeze(0), xq_i)
            xq_i_c = torch.view_as_complex(xq_i.float().reshape(*xq_i.shape[:-1], -1, 2))
            xk_i_c = torch.view_as_complex(xk_i.float().reshape(*xk_i.shape[:-1], -1, 2))
            xq_o = torch.view_as_real(xq_i_c * freqs_b).flatten(-2).type_as(xq)
            xk_o = torch.view_as_real(xk_i_c * freqs_b).flatten(-2).type_as(xk)
            xq_out_parts.append(xq_o.squeeze(0))
            xk_out_parts.append(xk_o.squeeze(0))
        return torch.cat(xq_out_parts, dim=0), torch.cat(xk_out_parts, dim=0)

    def forward(self, vid_q, vid_k, vid_shape, *args):
        """应用 RoPE 到 Q/K。

        普通模式: (vid_q, vid_k, vid_shape, cache) -> (vid_q, vid_k)
        MM模式: (vid_q, vid_k, vid_shape, txt_q, txt_k, txt_shape, cache) -> (vid_q, vid_k, txt_q, txt_k)
        """
        if self.mm and len(args) >= 4:
            txt_q, txt_k, txt_shape, cache = args[0], args[1], args[2], args[3]
            if txt_shape.dim() > 1:
                txt_lengths = txt_shape.prod(-1)
            else:
                txt_lengths = txt_shape.squeeze(-1) if txt_shape.shape[-1] == 1 else txt_shape
            vid_q, vid_k = self._apply_vid_rope(vid_q, vid_k, vid_shape, cache)
            txt_q, txt_k = self._apply_txt_rope(txt_q, txt_k, txt_lengths, cache)
            return vid_q, vid_k, txt_q, txt_k
        else:
            cache = args[-1]
            vid_q, vid_k = self._apply_vid_rope(vid_q, vid_k, vid_shape, cache)
            return vid_q, vid_k


def get_na_rope(rope_type: Optional[str] = None, dim: int = 128, **kwargs):
    """NaDiT RoPE 工厂函数，根据 rope_type 返回对应的 RoPE 实例。

    Args:
        rope_type: RoPE 类型，None 禁用，"normal" 视频-only，"mm" 多模态，"rope3d" 同 normal。
        dim: RoPE 频率维度（复数维度，通常为 head_dim // 2）。
        **kwargs: 传递给 MMRotaryEmbedding3d 的额外参数。

    Returns:
        NaRoPE3d 实例或 None。
    """
    if rope_type is None:
        return None
    head_dim = dim * 2
    axes_dim = kwargs.pop("axes_dim", None)
    if axes_dim is None:
        t = head_dim // 9
        h = head_dim * 4 // 9
        t = t - (t % 2)
        h = h - (h % 2)
        w = head_dim - t - h
        if w % 2 != 0:
            w -= 1
            if t + h + w != head_dim:
                w = head_dim - t - h
                if w % 2 != 0:
                    t += 2 if t + 2 <= head_dim - h else 0
                    w = head_dim - t - h
        axes_dim = (t, h, w)
    is_mm = (rope_type == "mm")
    if is_mm:
        kwargs.setdefault("language_theta", 10000.0 * 0.5)
    max_lengths = kwargs.pop("max_lengths", (1024, 128, 128, 4096))
    emb = MMRotaryEmbedding3d(
        dim=head_dim,
        axes_dim=axes_dim,
        max_lengths=max_lengths,
        **kwargs,
    )
    return NaRoPE3d(emb, mm=is_mm)

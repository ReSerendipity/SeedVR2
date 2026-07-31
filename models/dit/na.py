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

"""Native (分辨率无关) 序列处理模块。

为 NaDiT (Native Resolution DiT) 提供变长序列处理工具：

- **na_concat**: 将多模态变长序列（vid/txt）沿序列维度拼接，返回拼接后张量和各部分长度信息。
- **na_split**: 将拼接后的序列按模态拆分回 vid/txt 各部分。
- **unpatchify**: 变长版本的 unpatchify，支持每个样本有不同的视频尺寸。

NaDiT (Native Resolution Diffusion Transformer) 是一种支持原生分辨率的
视频扩散 Transformer 架构，通过变长序列处理、动态 padding 和位置编码插值，
使得模型可以处理任意分辨率和长度的视频输入，无需固定尺寸裁剪或 padding。
"""

from typing import List, Optional, Tuple
import torch
import torch.nn.functional as F


def na_concat(
    vid: torch.FloatTensor,
    txt: torch.FloatTensor,
    vid_len: torch.LongTensor,
    txt_len: torch.LongTensor,
) -> Tuple[
    torch.FloatTensor,
    torch.LongTensor,
    torch.LongTensor,
]:
    """将视频和文本变长序列拼接为单一序列，用于联合注意力计算。

    将 batch 内所有视频和文本 token 按 [vid_0, txt_0, vid_1, txt_1, ...] 顺序
    拼接为一个大序列，并计算累积长度用于后续拆分。

    Args:
        vid (torch.FloatTensor): 视频 token，形状 (sum_vid_len, c)，所有样本的视频 token 已展平拼接。
        txt (torch.FloatTensor): 文本 token，形状 (sum_txt_len, c)，所有样本的文本 token 已展平拼接。
        vid_len (torch.LongTensor): 每个样本的视频 token 长度，形状 (b,)。
        txt_len (torch.LongTensor): 每个样本的文本 token 长度，形状 (b,)。

    Returns:
        Tuple[torch.FloatTensor, torch.LongTensor, torch.LongTensor]:
            - x (torch.FloatTensor): 拼接后的序列，形状 (sum(vid_len+txt_len), c)。
            - cu_seqlens (torch.LongTensor): 累积序列长度，形状 (b+1,)，用于 Flash Attention v2 变长 API。
            - seq_lens (torch.LongTensor): 每个样本的总长度 (vid_len + txt_len)，形状 (b,)。
    """
    b = vid_len.shape[0]
    device = vid.device
    seq_lens = vid_len + txt_len
    max_seqlen = seq_lens.max().item()

    pad_num = max_seqlen * b - seq_lens.sum().item()
    x = torch.empty(max_seqlen * b, vid.shape[-1], dtype=vid.dtype, device=device)
    vid_cu = F.pad(vid_len.cumsum(0), (1, 0))
    txt_cu = F.pad(txt_len.cumsum(0), (1, 0))
    cu = F.pad(seq_lens.cumsum(0), (1, 0))
    for i in range(b):
        x[cu[i] : cu[i] + vid_len[i]] = vid[vid_cu[i] : vid_cu[i + 1]]
        x[cu[i] + vid_len[i] : cu[i + 1]] = txt[txt_cu[i] : txt_cu[i + 1]]
    if pad_num > 0:
        x[-pad_num:] = 0
    x = x.view(b, max_seqlen, -1)
    cu_seqlens = F.pad(seq_lens.cumsum(0, dtype=torch.int32), (1, 0))
    return x, cu_seqlens, seq_lens


def na_split(
    x: torch.FloatTensor,
    vid_len: torch.LongTensor,
    txt_len: torch.LongTensor,
) -> Tuple[
    torch.FloatTensor,
    torch.FloatTensor,
]:
    """将拼接的联合序列拆分回视频和文本部分。

    Args:
        x (torch.FloatTensor): 拼接后的序列，形状 (b, max_seqlen, c)。
        vid_len (torch.LongTensor): 每个样本的视频 token 长度，形状 (b,)。
        txt_len (torch.LongTensor): 每个样本的文本 token 长度，形状 (b,)。

    Returns:
        Tuple[torch.FloatTensor, torch.FloatTensor]:
            - vid (torch.FloatTensor): 视频 token，形状 (sum_vid_len, c)，已按样本拼接。
            - txt (torch.FloatTensor): 文本 token，形状 (sum_txt_len, c)，已按样本拼接。
    """
    b = x.shape[0]
    seq_lens = vid_len + txt_len
    cu = F.pad(seq_lens.cumsum(0), (1, 0))
    vid = torch.cat([x[i, : vid_len[i]] for i in range(b)])
    txt = torch.cat([x[i, vid_len[i] : vid_len[i] + txt_len[i]] for i in range(b)])
    return vid, txt


def unpatchify(
    x: torch.FloatTensor,
    window_sizes: torch.LongTensor,
    patch_size,
):
    """变长版本的 unpatchify，支持每个样本有不同的窗口数量（即不同的 t/h/w）。

    Args:
        x (torch.FloatTensor): 输入 token 序列，形状 (sum_nw*wt*wh*ww, c) 或 (b, sum_nw*wt*wh*ww, c)。
        window_sizes (torch.LongTensor): 每个样本的窗口数量，形状 (b, 3)，分别为 (nt, nh, nw)。
        patch_size: 窗口大小 (wt, wh, ww)。

    Returns:
        List[torch.FloatTensor]: 每个样本恢复后的视频张量列表，每个元素形状为 (c, t, h, w)。
    """
    wt, wh, ww = patch_size
    if x.dim() == 2:
        x = x.unsqueeze(0)
        window_sizes = window_sizes.unsqueeze(0)
    b = x.shape[0]
    nws = window_sizes.tolist()
    nw_cu = F.pad((window_sizes[:, 0] * window_sizes[:, 1] * window_sizes[:, 2]).cumsum(0), (1, 0))
    outs = []
    for i in range(b):
        nt, nh, nw = nws[i]
        n_windows = nt * nh * nw
        xi = x[i : i + 1, nw_cu[i] * wt * wh * ww : nw_cu[i + 1] * wt * wh * ww]
        xi = xi.reshape(-1, nt, nh, nw, wt, wh, ww, xi.shape[-1])
        xi = torch.einsum("b t h w p q r c -> b c t p h q w r", xi)
        t, h, w = nt * wt, nh * wh, nw * ww
        outs.append(xi.reshape(-1, t, h, w))
    return outs

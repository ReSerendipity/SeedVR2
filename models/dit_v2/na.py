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

"""NaDiT v2 变长序列处理工具。

为 Native Resolution DiT 提供变长序列操作原语：

- **flatten / unflatten**: 将不同形状的张量列表打包为扁平 2D 张量，可逆。
- **concat_idx / repeat_concat_idx**: 生成多模态序列交错拼接/拆分的索引函数对，
  支持 Flash Attention v2 变长 API 所需的 ``cu_seqlens`` 格式。
- **window_idx**: 生成窗口划分/还原函数对，配合自适应窗口注意力。

变长序列表示约定:
    - 扁平张量: ``(total_tokens, channels)``，所有样本的 token 在第 0 维拼接。
    - shape 张量: ``(batch, ndim)``，记录每个样本除 channels 外的空间/时间形状。
    - cu_seqlens: ``(batch+1,)`` int32 累积长度，``cu_seqlens[i+1] - cu_seqlens[i] = len(sample_i)``。
"""

from itertools import chain
from typing import Callable, List, Tuple
import torch
import torch.nn.functional as F


def flatten(x_list: List[torch.Tensor]) -> Tuple[torch.Tensor, torch.LongTensor]:
    """将不同形状的张量列表打包为扁平 2D 张量和 shape 信息。

    每个张量除最后一维（通道维）外可以有不同形状。flatten 将每个张量
    重塑为 ``(-1, C)`` 后沿第 0 维拼接。

    Args:
        x_list: 张量列表，每个元素形状为 ``(*spatial_shape, C)``，
            spatial_shape 可以不同但维度数必须一致。

    Returns:
        (flat_x, shapes):
            - flat_x: 形状 ``(total_tokens, C)`` 的扁平张量。
            - shapes: 形状 ``(batch, ndim)`` 的 LongTensor，记录每个样本的 spatial_shape。
    """
    if len(x_list) == 0:
        return torch.zeros(0, device=x_list[0].device if x_list else None), torch.zeros(0, 0)
    ndim = x_list[0].ndim - 1
    shapes = torch.zeros(len(x_list), ndim, dtype=torch.long, device=x_list[0].device)
    flat_parts = []
    for i, x in enumerate(x_list):
        shapes[i] = torch.tensor(x.shape[:-1], device=x.device)
        flat_parts.append(x.reshape(-1, x.shape[-1]))
    flat_x = torch.cat(flat_parts, dim=0)
    return flat_x, shapes


def unflatten(flat_x: torch.Tensor, shapes: torch.LongTensor) -> List[torch.Tensor]:
    """flatten 的逆操作，将扁平张量还原为不同形状的张量列表。

    Args:
        flat_x: 形状 ``(total_tokens, C)`` 的扁平张量。
        shapes: 形状 ``(batch, ndim)`` 的 LongTensor。

    Returns:
        张量列表，每个元素形状为 ``(*spatial_shape_i, C)``。
    """
    batch = shapes.shape[0]
    c = flat_x.shape[-1]
    cu_lens = F.pad(shapes.prod(-1).cumsum(0), (1, 0))
    x_list = []
    for i in range(batch):
        shape_i = shapes[i].tolist()
        start = cu_lens[i].item()
        end = cu_lens[i + 1].item()
        x_list.append(flat_x[start:end].reshape(*shape_i, c))
    return x_list


def _build_interleaved_indices(
    lengths_a: torch.LongTensor,
    lengths_b: torch.LongTensor,
    device: torch.device,
) -> Tuple[torch.LongTensor, torch.LongTensor, torch.LongTensor]:
    """构建两组序列交错拼接的前向/反向索引。

    拼接顺序: ``[a_0, b_0, a_1, b_1, ..., a_b, b_b]``。

    Args:
        lengths_a: ``(batch,)`` 每组 a 段长度。
        lengths_b: ``(batch,)`` 每组 b 段长度。
        device: 张量设备。

    Returns:
        (concat_idx, unconcat_a_idx, unconcat_b_idx): 拼接索引和拆分索引。
    """
    total_a = lengths_a.sum().item()
    total_b = lengths_b.sum().item()
    total = total_a + total_b
    batch = len(lengths_a)

    cu_a = F.pad(lengths_a.cumsum(0), (1, 0))
    cu_b = F.pad(lengths_b.cumsum(0), (1, 0))

    concat_idx = torch.zeros(total, dtype=torch.long, device=device)
    offset = 0
    a_offset = 0
    b_offset = total_a
    for i in range(batch):
        la = lengths_a[i].item()
        lb = lengths_b[i].item()
        concat_idx[offset : offset + la] = torch.arange(a_offset, a_offset + la, device=device)
        offset += la
        concat_idx[offset : offset + lb] = torch.arange(b_offset, b_offset + lb, device=device)
        offset += lb
        a_offset += la
        b_offset += lb

    unconcat_a_idx = torch.zeros(total_a, dtype=torch.long, device=device)
    unconcat_b_idx = torch.zeros(total_b, dtype=torch.long, device=device)
    pos = 0
    a_pos = 0
    b_pos = 0
    for i in range(batch):
        la = lengths_a[i].item()
        lb = lengths_b[i].item()
        unconcat_a_idx[a_pos : a_pos + la] = torch.arange(pos, pos + la, device=device)
        a_pos += la
        pos += la
        unconcat_b_idx[b_pos : b_pos + lb] = torch.arange(pos, pos + lb, device=device)
        b_pos += lb
        pos += lb

    return concat_idx, unconcat_a_idx, unconcat_b_idx


def concat_idx(
    lengths_a: torch.LongTensor,
    lengths_b: torch.LongTensor,
) -> Tuple[Callable, Callable]:
    """生成两组变长序列交错拼接/拆分的函数对。

    拼接顺序为 ``[a_0, b_0, a_1, b_1, ...]``，适用于 Flash Attention v2
    变长 self-attention（每个样本的 vid 和 txt 拼接后计算注意力）。

    Args:
        lengths_a: ``(batch,)`` 每组 a 段（如视频）的长度。
        lengths_b: ``(batch,)`` 每组 b 段（如文本）的长度。

    Returns:
        (concat_fn, unconcat_fn):
            - concat_fn(a, b): 将 a 和 b 交错拼接为单一扁平张量。
            - unconcat_fn(x): 将拼接张量拆分回 (a, b)。
    """
    device = lengths_a.device
    c_idx, ua_idx, ub_idx = _build_interleaved_indices(lengths_a, lengths_b, device)

    def concat_fn(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
        ab = torch.cat([a, b], dim=0)
        return ab[c_idx]

    def unconcat_fn(x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        a = x[ua_idx]
        b = x[ub_idx]
        return a, b

    return concat_fn, unconcat_fn


def repeat_concat_idx(
    vid_len_win: torch.LongTensor,
    txt_len: torch.LongTensor,
    window_count: torch.LongTensor,
) -> Tuple[Callable, Callable]:
    """生成窗口级多模态序列交错拼接/拆分的函数对。

    与 ``concat_idx`` 类似，但处理窗口注意力场景：每个样本被划分为
    多个窗口，每个窗口的视频 token 段后面跟该样本的文本 token
    （文本在各窗口间共享，拼接时自动重复）。

    Args:
        vid_len_win: ``(total_windows,)`` 每个窗口的视频 token 数。
        txt_len: ``(batch,)`` 每个样本的文本 token 数（原始未重复）。
        window_count: ``(batch,)`` 每个样本的窗口数。

    Returns:
        (concat_fn, unconcat_fn):
            - concat_fn(vid, txt): vid 为窗口级扁平张量，txt 为 per-sample 扁平张量
              （未重复），输出为交错拼接张量（txt 自动按窗口重复）。
            - unconcat_fn(x): 拆分回 (vid, txt)，txt 部分取第一个窗口的结果（去重）。
    """
    device = vid_len_win.device
    txt_len_win = txt_len.repeat_interleave(window_count)
    c_idx, ua_idx, ub_idx = _build_interleaved_indices(vid_len_win, txt_len_win, device)

    total_vid = vid_len_win.sum().item()

    _, ub_unique_idx = [], []
    offset = 0
    b_pos = 0
    unique_b_indices = []
    cu_vw = F.pad(vid_len_win.cumsum(0), (1, 0))
    w_offset = 0
    for i in range(len(window_count)):
        nw = window_count[i].item()
        nt = txt_len[i].item()
        for w in range(nw):
            vl = vid_len_win[w_offset + w].item()
            offset += vl
            if w == 0:
                unique_b_indices.append(torch.arange(offset, offset + nt, device=device))
            offset += nt
        w_offset += nw
    ub_unique_idx = torch.cat(unique_b_indices) if unique_b_indices else torch.zeros(0, dtype=torch.long, device=device)

    def concat_fn(vid: torch.Tensor, txt: torch.Tensor) -> torch.Tensor:
        if txt.shape[0] == total_vid:
            pass
        else:
            txt_list = unflatten(txt, torch.stack([txt_len], dim=-1) if txt.ndim == 2 else txt_len.unsqueeze(-1))
            txt_expanded = list(chain.from_iterable([t] * nw for t, nw in zip(txt_list, window_count)))
            txt, _ = flatten(txt_expanded) if txt_expanded else (txt, None)
            if txt is None:
                txt = torch.zeros(0, vid.shape[-1], device=device, dtype=vid.dtype)
        vt = torch.cat([vid, txt], dim=0)
        return vt[c_idx]

    def unconcat_fn(x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        vid_out = x[ua_idx]
        txt_out = x[ub_unique_idx]
        return vid_out, txt_out

    return concat_fn, unconcat_fn


def window_idx(
    vid_shape: torch.LongTensor,
    make_window_fn: Callable,
) -> Tuple[Callable, Callable, torch.LongTensor, torch.LongTensor]:
    """生成窗口划分/还原函数对及窗口形状信息。

    用于变长窗口注意力：将不同分辨率的视频 token 分别划分为固定大小窗口，
    拼接为窗口级扁平张量用于 Flash Attention，注意力后还原为原始顺序。

    Args:
        vid_shape: ``(batch, 3)`` 每个样本的 ``(t, h, w)`` 网格形状。
        make_window_fn: 窗口切片函数，接收 ``(t, h, w)`` 形状张量，
            返回窗口切片列表 ``[(slice_t, slice_h, slice_w), ...]``。

    Returns:
        (window_partition, window_reverse, window_shape, window_count):
            - window_partition(x): 将扁平视频张量划分为窗口级扁平张量。
            - window_reverse(x): 将窗口级张量还原为原始扁平顺序。
            - window_shape: ``(total_windows, 3)`` 每个窗口的 ``(wt, wh, ww)`` 形状。
            - window_count: ``(batch,)`` 每个样本的窗口数。
    """
    device = vid_shape.device
    batch = vid_shape.shape[0]

    p_list = []
    r_list = []
    all_window_shapes = []
    flat_offset = 0
    win_flat_offset = 0
    counts = []

    for i in range(batch):
        t, h, w = vid_shape[i].tolist()
        dummy = torch.zeros(t, h, w, 1, device=device)
        slices = make_window_fn(dummy)
        n_win = len(slices)
        counts.append(n_win)
        sample_size = t * h * w
        s_indices = torch.zeros(sample_size, dtype=torch.long, device=device)

        for wi, (st, sh, sw) in enumerate(slices):
            wt = st.stop - st.start
            wh = sh.stop - sh.start
            ww = sw.stop - sw.start
            all_window_shapes.append([wt, wh, ww])

            tt, hh, ww_idx = torch.meshgrid(
                torch.arange(st.start, st.stop, device=device),
                torch.arange(sh.start, sh.stop, device=device),
                torch.arange(sw.start, sw.stop, device=device),
                indexing='ij',
            )
            local_flat = (tt * h * w + hh * w + ww_idx).flatten()
            global_flat = local_flat + flat_offset
            win_sz = len(global_flat)
            p_list.append(global_flat)
            win_positions = torch.arange(win_flat_offset, win_flat_offset + win_sz, device=device)
            s_indices[local_flat] = win_positions
            win_flat_offset += win_sz

        r_list.append(s_indices)
        flat_offset += sample_size

    partition_idx = torch.cat(p_list, dim=0) if p_list else torch.zeros(0, dtype=torch.long, device=device)
    reverse_idx = torch.cat(r_list, dim=0) if r_list else torch.zeros(0, dtype=torch.long, device=device)
    window_shape = torch.tensor(all_window_shapes, dtype=torch.long, device=device) if all_window_shapes else torch.zeros(0, 3, dtype=torch.long, device=device)
    window_count = torch.tensor(counts, dtype=torch.long, device=device) if counts else torch.zeros(0, dtype=torch.long, device=device)

    def window_partition(x: torch.Tensor) -> torch.Tensor:
        return x[partition_idx]

    def window_reverse(x: torch.Tensor) -> torch.Tensor:
        return x[reverse_idx]

    return window_partition, window_reverse, window_shape, window_count

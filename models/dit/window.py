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

"""窗口划分 (Window Partition) 模块。

为窗口注意力 (Window Attention) 提供时空窗口划分与逆变换功能：

- **window_partition**: 将 3D 视频 token 划分为不重叠的时空窗口。
- **window_reverse**: 将窗口化后的数据恢复回原始形状。

窗口注意力算法:
    窗口注意力 (Window Attention) 是 Swin Transformer 中提出的方法，
    将特征图划分为不重叠的局部窗口，仅在窗口内计算自注意力，
    从而将注意力计算复杂度从 O(n^2) 降低到 O(n * w^2)，其中 w 为窗口大小。

    对于 3D 视频数据，窗口沿 (t, h, w) 三个维度划分，例如 window_size=(2,8,8)
    表示每个窗口包含 2 帧、8x8 的空间区域。通过窗口划分，长视频序列被拆分为
    多个小窗口独立计算注意力，显著降低内存和计算开销。
"""

import torch


def window_partition(x: torch.FloatTensor, window_size, t, h, w):
    """将 3D token 序列划分为不重叠的时空窗口。

    Args:
        x (torch.FloatTensor): 输入张量，形状 (b, t*h*w, c) 或 (b, t*h*w, nheads, head_dim)。
        window_size: 窗口大小，(wt, wh, ww)。
        t (int): 时间维度大小。
        h (int): 高度维度大小。
        w (int): 宽度维度大小。

    Returns:
        torch.FloatTensor: 窗口化后的张量，形状为
            (b*num_windows, wt*wh*ww, ...)，其中 num_windows = (t/wt)*(h/wh)*(w/ww)。
    """
    wt, wh, ww = window_size
    b = x.shape[0]
    n_dim = x.ndim
    if n_dim == 3:
        c = x.shape[-1]
        x = x.view(b, t, h, w, c)
        ws = (wt, wh, ww)
        nt, nh, nw = t // ws[0], h // ws[1], w // ws[2]
        x = x.view(b, nt, ws[0], nh, ws[1], nw, ws[2], c)
        x = x.permute(0, 1, 3, 5, 2, 4, 6, 7).contiguous()
        x = x.view(-1, ws[0] * ws[1] * ws[2], c)
    elif n_dim == 4:
        nheads, c = x.shape[-2], x.shape[-1]
        x = x.view(b, t, h, w, nheads, c)
        ws = (wt, wh, ww)
        nt, nh, nw = t // ws[0], h // ws[1], w // ws[2]
        x = x.view(b, nt, ws[0], nh, ws[1], nw, ws[2], nheads, c)
        x = x.permute(0, 1, 3, 5, 2, 4, 6, 7, 8).contiguous()
        x = x.view(-1, ws[0] * ws[1] * ws[2], nheads, c)
    else:
        raise NotImplementedError(f"Unsupported ndim: {n_dim}")
    return x


def window_reverse(windows, window_size, t, h, w):
    """将窗口化后的数据恢复回原始序列形状。

    Args:
        windows (torch.FloatTensor): 窗口化张量，形状 (b*num_windows, wt*wh*ww, ...)。
        window_size: 窗口大小，(wt, wh, ww)。
        t (int): 时间维度大小。
        h (int): 高度维度大小。
        w (int): 宽度维度大小。

    Returns:
        torch.FloatTensor: 恢复后的张量，形状 (b, t*h*w, ...)。
    """
    wt, wh, ww = window_size
    b_ = windows.shape[0]
    nt, nh, nw = t // wt, h // wh, w // ww
    b = b_ // (nt * nh * nw)
    n_dim = windows.ndim
    if n_dim == 3:
        c = windows.shape[-1]
        x = windows.view(b, nt, nh, nw, wt, wh, ww, c)
        x = x.permute(0, 1, 4, 2, 5, 3, 6, 7).contiguous().view(b, t * h * w, c)
    elif n_dim == 4:
        nheads, c = windows.shape[-2], windows.shape[-1]
        x = windows.view(b, nt, nh, nw, wt, wh, ww, nheads, c)
        x = x.permute(0, 1, 4, 2, 5, 3, 6, 7, 8).contiguous().view(b, t * h * w, nheads, c)
    else:
        raise NotImplementedError(f"Unsupported ndim: {n_dim}")
    return x

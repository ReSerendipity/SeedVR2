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

"""720p 自适应窗口划分模块。

提供两种自适应窗口划分方法（对应 config 中 ``window_method`` 的取值）：

- ``720pwin_by_size_bysize`` (make_720Pwindows_bysize)：按窗口数自适应计算窗口大小，
  将空间分辨率缩放到 720p 基准后均分。
- ``720pswin_by_size_bysize`` (make_shifted_720Pwindows_bysize)：移位窗口版本，
  在基础窗口之上按半窗口移位生成窗口以扩大感受野。
"""

import math
from collections.abc import Callable
from math import ceil

import torch


def get_window_op(method: str) -> Callable:
    """窗口划分工厂函数，根据 method 返回对应的窗口切片生成函数。

    Args:
        method: "720pwin_by_size_bysize"（按窗口数自适应720P窗口）、
            "720pswin_by_size_bysize"（移位窗口版本）、
            "win"（固定窗口大小划分）或 "win_by_size"（自适应720P窗口）。

    Returns:
        函数 f(shape, window) -> List[Tuple[slice, slice, slice]]。
    """
    if method == "720pwin_by_size_bysize":
        return make_720Pwindows_bysize
    elif method == "720pswin_by_size_bysize":
        return make_shifted_720Pwindows_bysize
    elif method == "win":

        def _win_op(shape: tuple[int, int, int], window: tuple[int, int, int]) -> list[tuple[slice, slice, slice]]:
            t, h, w = shape
            wt, wh, ww = window
            slices = []
            for it in range(0, t, max(wt, 1)):
                for ih in range(0, h, max(wh, 1)):
                    for iw in range(0, w, max(ww, 1)):
                        slices.append(
                            (
                                slice(it, min(it + max(wt, 1), t)),
                                slice(ih, min(ih + max(wh, 1), h)),
                                slice(iw, min(iw + max(ww, 1), w)),
                            )
                        )
            return slices

        return _win_op
    elif method == "win_by_size":

        def _win_by_size_op(shape: tuple[int, int, int], window) -> list[tuple[slice, slice, slice]]:
            t, h, w = shape
            if isinstance(window, (tuple, list)):
                wt = window[0] if len(window) > 0 else 1
                ref_ws = window[1] if len(window) > 1 else 24
            else:
                wt = 1
                ref_ws = window
            # 720P自适应窗口大小
            if h * w <= 36 * 64:
                ws = max(h, w)
            else:
                ws_h = int(ref_ws * (h / 36) ** 0.5)
                ws_w = int(ref_ws * (w / 64) ** 0.5)
                ws = max(ws_h, ws_w)
                ws = max(ws, 4)
                if ws % 4 != 0:
                    ws = (ws // 4 + 1) * 4
            wh = ww = ws
            slices = []
            for it in range(0, t, max(wt, 1)):
                for ih in range(0, h, wh):
                    for iw in range(0, w, ww):
                        slices.append(
                            (
                                slice(it, min(it + max(wt, 1), t)),
                                slice(ih, min(ih + wh, h)),
                                slice(iw, min(iw + ww, w)),
                            )
                        )
            return slices

        return _win_by_size_op
    else:
        raise ValueError(f"Unknown window method: {method}")


def window_partition(x: torch.FloatTensor, window_size: tuple[int]) -> torch.FloatTensor:
    """将特征张量划分为不重叠的 3D 窗口。

    Args:
        x: (b, t, h, w, c)。
        window_size: (wt, wh, ww)。

    Returns:
        (b*num_windows, wt*wh*ww, c)。
    """
    b, t, h, w, c = x.shape
    wt, wh, ww = window_size
    x = x.view(b, t // wt, wt, h // wh, wh, w // ww, ww, c)
    windows = x.permute(0, 1, 3, 5, 2, 4, 6, 7).contiguous().view(-1, wt * wh * ww, c)
    return windows


def window_reverse(windows: torch.FloatTensor, window_size: tuple[int], t: int, h: int, w: int):
    """window_partition 的逆操作，将窗口拼回原形状。"""
    b = int(windows.shape[0] / (t * h * w / window_size[0] / window_size[1] / window_size[2]))
    wt, wh, ww = window_size
    x = windows.view(b, t // wt, h // wh, w // ww, wt, wh, ww, -1)
    x = x.permute(0, 1, 4, 2, 5, 3, 6, 7).contiguous().view(b, t, h, w, -1)
    return x


def calc_out_size(pad_func, size, window_size, window_shift):
    """计算 padding 后对齐到窗口的输出尺寸。"""
    size_padded = (
        pad_func(2 * window_shift - (size + window_shift) % window_size)
        if (size + window_shift) % window_size != 0
        else 0
    )
    out_size = size + size_padded
    return out_size, size_padded


def make_windows(t, h, w, window_size, window_temporal, device):
    """标准窗口 padding + 划分，返回 padded 形状和窗口划分/还原参数。"""
    window_shift = 0
    _, pad_t = calc_out_size(lambda x: x, t, window_temporal, window_shift)
    _, pad_h = calc_out_size(lambda x: max(x, 0), h, window_size, window_shift)
    _, pad_w = calc_out_size(lambda x: max(x, 0), w, window_size, window_shift)
    tp = t + pad_t
    hp = h + pad_h
    wp = w + pad_w
    return pad_t, pad_h, pad_w, tp, hp, wp


def make_shifted_windows(t, h, w, window_size, window_temporal, device):
    """移位窗口版本，padding 使 (size + shift) % ws == 0。"""
    window_shift = window_size // 2
    _, pad_t = calc_out_size(lambda x: x, t, window_temporal, window_shift=0)
    _, pad_h = calc_out_size(lambda x: max(x, 0), h, window_size, window_shift)
    _, pad_w = calc_out_size(lambda x: max(x, 0), w, window_size, window_shift)
    tp = t + pad_t
    hp = h + pad_h
    wp = w + pad_w
    return pad_t, pad_h, pad_w, tp, hp, wp


def make_720Pwindows_bysize(
    size: tuple[int, int, int], num_windows: tuple[int, int, int]
) -> list[tuple[slice, slice, slice]]:
    """720p 自适应窗口划分：根据空间尺寸自适应计算窗口大小。

    算法：
        scale = sqrt((45 * 80) / (h * w)) 将空间分辨率缩放到 720p 基准，
        再按 num_windows (nt, nh, nw) 均分得到窗口大小 (wt, wh, ww)，
        返回覆盖整个网格的窗口切片列表。

    Args:
        size: (t, h, w) 原始网格尺寸。
        num_windows: (nt, nh, nw) 各维窗口数。

    Returns:
        窗口切片列表 [(slice_t, slice_h, slice_w), ...]。
    """
    t, h, w = size
    resized_nt, resized_nh, resized_nw = num_windows
    # 缩放到 720p 基准
    scale = math.sqrt((45 * 80) / (h * w))
    resized_h, resized_w = round(h * scale), round(w * scale)
    wh, ww = ceil(resized_h / resized_nh), ceil(resized_w / resized_nw)  # 窗口大小
    wt = ceil(min(t, 30) / resized_nt)  # 窗口大小
    nt, nh, nw = ceil(t / wt), ceil(h / wh), ceil(w / ww)  # 窗口数量
    return [
        (
            slice(it * wt, min((it + 1) * wt, t)),
            slice(ih * wh, min((ih + 1) * wh, h)),
            slice(iw * ww, min((iw + 1) * ww, w)),
        )
        for iw in range(nw)
        if min((iw + 1) * ww, w) > iw * ww
        for ih in range(nh)
        if min((ih + 1) * wh, h) > ih * wh
        for it in range(nt)
        if min((it + 1) * wt, t) > it * wt
    ]


def make_shifted_720Pwindows_bysize(
    size: tuple[int, int, int], num_windows: tuple[int, int, int]
) -> list[tuple[slice, slice, slice]]:
    """720p 自适应移位窗口划分（Swin 风格）。

    与 make_720Pwindows_bysize 相同的基础窗口计算，但额外以半窗口移位
    （st/sh/sw）生成重叠的移位窗口，扩大感受野。

    Args:
        size: (t, h, w) 原始网格尺寸。
        num_windows: (nt, nh, nw) 各维窗口数。

    Returns:
        窗口切片列表 [(slice_t, slice_h, slice_w), ...]。
    """
    t, h, w = size
    resized_nt, resized_nh, resized_nw = num_windows
    # 缩放到 720p 基准
    scale = math.sqrt((45 * 80) / (h * w))
    resized_h, resized_w = round(h * scale), round(w * scale)
    wh, ww = ceil(resized_h / resized_nh), ceil(resized_w / resized_nw)  # 窗口大小
    wt = ceil(min(t, 30) / resized_nt)  # 窗口大小

    st, sh, sw = (  # 移位大小
        0.5 if wt < t else 0,
        0.5 if wh < h else 0,
        0.5 if ww < w else 0,
    )
    nt, nh, nw = ceil((t - st) / wt), ceil((h - sh) / wh), ceil((w - sw) / ww)  # 窗口数量
    nt, nh, nw = (
        nt + 1 if st > 0 else 1,
        nh + 1 if sh > 0 else 1,
        nw + 1 if sw > 0 else 1,
    )
    return [
        (
            slice(max(int((it - st) * wt), 0), min(int((it - st + 1) * wt), t)),
            slice(max(int((ih - sh) * wh), 0), min(int((ih - sh + 1) * wh), h)),
            slice(max(int((iw - sw) * ww), 0), min(int((iw - sw + 1) * ww), w)),
        )
        for iw in range(nw)
        if min(int((iw - sw + 1) * ww), w) > max(int((iw - sw) * ww), 0)
        for ih in range(nh)
        if min(int((ih - sh + 1) * wh), h) > max(int((ih - sh) * wh), 0)
        for it in range(nt)
        if min(int((it - st + 1) * wt), t) > max(int((it - st) * wt), 0)
    ]

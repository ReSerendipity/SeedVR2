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

"""2D→3D 卷积权重膨胀工具库（基础版）。

提供将预训练 2D 卷积权重膨胀为 3D 因果卷积权重的核心函数，以及因果卷积所需的
首尾帧处理工具（extend_head/remove_head）和归一化包装器。此为简化版实现，
完整版（含内存限制和序列并行支持）见 causal_inflation_lib.py。
"""

from enum import Enum

import numpy as np
import torch
from diffusers.models.normalization import RMSNorm
from einops import rearrange
from torch import Tensor, nn

from common.logger import get_logger

logger = get_logger(__name__)


class MemoryState(Enum):
    """因果卷积记忆状态枚举（基础版）。

    Attributes:
        DISABLED: 不启用记忆缓存。
        INITIALIZING: 处理首个切片，需初始化记忆。
        ACTIVE: 使用缓存的前序帧进行因果卷积。
    """

    DISABLED = 0
    INITIALIZING = 1
    ACTIVE = 2


def causal_norm_wrapper(norm_layer: nn.Module, x: torch.Tensor) -> torch.Tensor:
    """因果归一化包装器，自动处理 4D/5D 张量的维度重排。

    - LayerNorm/RMSNorm：将通道维移到最后，归一化后移回。
    - GroupNorm/BatchNorm：对 5D 张量将时序维合并到 batch 维，归一化后还原。

    Args:
        norm_layer: 归一化层实例（LayerNorm/RMSNorm/GroupNorm/BatchNorm2d/SyncBatchNorm）。
        x: 输入张量，形状 [B, C, H, W]（4D）或 [B, C, T, H, W]（5D）。

    Returns:
        torch.Tensor: 归一化后的张量，与输入同形状同 dtype。

    Raises:
        NotImplementedError: 传入不支持的归一化层类型。
    """
    if isinstance(norm_layer, (nn.LayerNorm, RMSNorm)):
        if x.ndim == 4:
            x = rearrange(x, "b c h w -> b h w c")
            x = norm_layer(x)
            x = rearrange(x, "b h w c -> b c h w")
            return x
        if x.ndim == 5:
            x = rearrange(x, "b c t h w -> b t h w c")
            x = norm_layer(x)
            x = rearrange(x, "b t h w c -> b c t h w")
            return x
    if isinstance(norm_layer, (nn.GroupNorm, nn.BatchNorm2d, nn.SyncBatchNorm)):
        if x.ndim <= 4:
            return norm_layer(x)
        if x.ndim == 5:
            t = x.size(2)
            x = rearrange(x, "b c t h w -> (b t) c h w")
            x = norm_layer(x)
            x = rearrange(x, "(b t) c h w -> b c t h w", t=t)
            return x
    raise NotImplementedError


def remove_head(tensor: Tensor, times: int = 1) -> Tensor:
    """移除上采样过程中重复的首帧特征。

    在带时序上采样的解码器中，首个时间步的特征会因像素重组（pixel shuffle）
    产生冗余的重复首帧，此函数裁剪多余的帧以保持时序长度正确。

    Args:
        tensor: 输入张量，形状 [B, C, T, H, W]。
        times: 需要移除的重复帧数。

    Returns:
        Tensor: 裁剪后的张量，形状 [B, C, T - times + 1, H, W]。
        保留第一帧，跳过 times 个重复帧，拼接后续帧。
    """
    if times == 0:
        return tensor
    return torch.cat(tensors=(tensor[:, :, :1], tensor[:, :, times + 1 :]), dim=2)


def extend_head(tensor: Tensor, times: int | None = 2, memory: Tensor | None = None) -> Tensor:
    """在因果卷积前扩展输入的时序头部。

    两种模式：
    - memory 为 None：重复首帧 times 次，为因果卷积提供左侧填充，
      避免第一帧输出无效。
    - memory 不为 None：将上一切片保存的记忆（尾帧）拼接到当前输入前面，
      保持流式推理的时序连续性。

    Args:
        tensor: 输入张量，形状 [B, C, T, H, W]。
        times: 首帧重复次数，通常为 kernel_size[0] - 1 = 2。
        memory: 前序切片的缓存帧，形状 [B, C, cache_size, H, W]。

    Returns:
        Tensor: 扩展后的张量，时序长度为 T + times（memory为None时）
        或 T + cache_size（memory存在时）。
    """
    if times == 0:
        return tensor
    if memory is not None:
        return torch.cat((memory.to(tensor), tensor), dim=2)
    else:
        tile_repeat = np.ones(tensor.ndim).astype(int)
        tile_repeat[2] = times
        return torch.cat(tensors=(torch.tile(tensor[:, :, :1], list(tile_repeat)), tensor), dim=2)


def inflate_weight(weight_2d: torch.Tensor, weight_3d: torch.Tensor, inflation_mode: str):
    """将 2D 卷积权重膨胀为 3D 卷积权重。

    两种膨胀策略：
    - 'replicate'：将 2D 核 [Cout, Cin, kH, kW] 复制到时间维 [Cout, Cin, kT, kH, kW]
      并除以 kT 以保持激活值尺度不变。
    - 'constant'（tail）：仅在时间核的最后一个位置填入 2D 权重，其余为 0。
      等价于初始化时仅看当前帧，前序帧权重需通过训练学习。

    Args:
        weight_2d: 2D 卷积权重，形状 [Cout, Cin, kH, kW]。
        weight_3d: 待初始化的 3D 卷积权重，形状 [Cout, Cin, kT, kH, kW]。
        inflation_mode: 膨胀模式，'replicate' 或 'constant'。

    Returns:
        torch.Tensor: 初始化后的 3D 权重（与 weight_3d 同一张量）。
    """
    assert inflation_mode in ["constant", "replicate"]
    assert weight_3d.shape[:2] == weight_2d.shape[:2]
    with torch.no_grad():
        if inflation_mode == "replicate":
            depth = weight_3d.size(2)
            weight_3d.copy_(weight_2d.unsqueeze(2).repeat(1, 1, depth, 1, 1) / depth)
        else:
            weight_3d.fill_(0.0)
            weight_3d[:, :, -1].copy_(weight_2d)
    return weight_3d


def inflate_bias(bias_2d: torch.Tensor, bias_3d: torch.Tensor, inflation_mode: str):
    """将 2D 卷积偏置膨胀为 3D 卷积偏置。

    偏置直接从 2D 复制到 3D，无需修改（偏置不涉及时空维度）。

    Args:
        bias_2d: 2D 卷积偏置，形状 [Cout]。
        bias_3d: 3D 卷积偏置，形状 [Cout]。
        inflation_mode: 膨胀模式占位符，保持与 inflate_weight 接口一致。

    Returns:
        torch.Tensor: 初始化后的 3D 偏置（与 bias_3d 同一张量）。
    """
    assert bias_3d.shape == bias_2d.shape
    with torch.no_grad():
        bias_3d.copy_(bias_2d)
    return bias_3d


def modify_state_dict(layer, state_dict, prefix, inflate_weight_fn, inflate_bias_fn):
    """在加载 state_dict 时自动将 2D 权重膨胀为 3D。

    这是 _load_from_state_dict 的辅助函数，检查给定前缀的权重/偏置是否为
    4D（2D 卷积格式），若是则调用膨胀函数转换为 5D（3D 卷积格式）后再加载。

    Args:
        layer: 目标层实例（需要有 inflation_mode 属性）。
        state_dict: 待加载的 state_dict。
        prefix: 当前层的参数前缀（如 'encoder.conv_in.'）。
        inflate_weight_fn: 权重膨胀函数。
        inflate_bias_fn: 偏置膨胀函数。

    Returns:
        dict: 修改后的 state_dict（原地修改）。
    """
    weight_name = prefix + "weight"
    bias_name = prefix + "bias"
    if weight_name in state_dict:
        weight_2d = state_dict[weight_name]
        if weight_2d.dim() == 4:
            # Assuming the 2D weights are 4D tensors (out_channels, in_channels, h, w)
            weight_3d = inflate_weight_fn(
                weight_2d=weight_2d,
                weight_3d=layer.weight,
                inflation_mode=layer.inflation_mode,
            )
            state_dict[weight_name] = weight_3d
        else:
            return state_dict
            # It's a 3d state dict, should not do inflation on both bias and weight.
    if bias_name in state_dict:
        bias_2d = state_dict[bias_name]
        if bias_2d.dim() == 1:
            # Assuming the 2D biases are 1D tensors (out_channels,)
            bias_3d = inflate_bias_fn(
                bias_2d=bias_2d,
                bias_3d=layer.bias,
                inflation_mode=layer.inflation_mode,
            )
            state_dict[bias_name] = bias_3d
    return state_dict

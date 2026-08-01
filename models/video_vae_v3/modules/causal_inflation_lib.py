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

"""完整版膨胀因果3D卷积库。

提供生产级的 InflatedCausalConv3d 实现，相比基础版增加了：
1. 内存限制卷积（memory_limit_conv）：递归沿 H/W 维度分片计算大张量，避免 OOM。
2. 序列并行支持（slicing_forward）：跨多GPU的环形缓存通信。
3. 流式切片推理：沿时间维切片处理长视频，缓存跨片上下文。
4. CPU 卸载：推理时将时序记忆卸载到 CPU 以节省 GPU 显存。
5. GroupNorm 分块计算：大张量归一化时分通道计算，降低峰值显存。

核心算法：
- 因果卷积：时间维 kernel_size=3, stride=1 时，输出 t 帧仅依赖输入 t-2, t-1, t 帧；
  首帧重复填充2次以确保第一帧输出有效。
- 权重膨胀：2D预训练权重 [Cout,Cin,kH,kW] → 3D [Cout,Cin,kT,kH,kW]，
  'tail' 模式仅在时间末位赋2D权重（初始等价于2D卷积看当前帧），
  'replicate' 模式复制并平均（初始等价于时间维平均池化+2D卷积）。
"""

import math
from contextlib import contextmanager

import torch
import torch.distributed as dist
import torch.nn.functional as F
from diffusers.models.normalization import RMSNorm
from einops import rearrange
from torch import Tensor, nn
from torch.nn import Conv3d

from common.distributed.advanced import (
    get_next_sequence_parallel_rank,
    get_prev_sequence_parallel_rank,
    get_sequence_parallel_group,
    get_sequence_parallel_rank,
    get_sequence_parallel_world_size,
)
from common.logger import get_logger
from common.utils import safe_pad_operation
from models.video_vae_v3.modules.context_parallel_lib import cache_send_recv, get_cache_size
from models.video_vae_v3.modules.global_config import get_norm_limit
from models.video_vae_v3.modules.types import MemoryState, _inflation_mode_t, _memory_device_t

logger = get_logger(__name__)


@contextmanager
def ignore_padding(model):
    """临时将卷积的padding设为(0,0,0)的上下文管理器。

    在 memory_limit_conv 递归分片时，内部padding已手动处理，
    需要临时禁用Conv3d自带的padding以避免双重填充。

    Args:
        model: nn.Conv3d 实例，将临时修改其 padding 属性。

    Yields:
        None: 进入上下文时 padding=(0,0,0)，退出时恢复原值。
    """
    orig_padding = model.padding
    model.padding = (0, 0, 0)
    try:
        yield
    finally:
        model.padding = orig_padding


class InflatedCausalConv3d(Conv3d):
    """完整版膨胀因果3D卷积层。

    支持内存限制分片、序列并行、流式推理和CPU卸载。
    前向流程分为 basic_forward（简单模式）和 slicing_forward（分片/并行模式）。
    """

    def __init__(
        self,
        *args,
        inflation_mode: _inflation_mode_t,
        memory_device: _memory_device_t = "same",
        **kwargs,
    ):
        """初始化完整版因果3D卷积层。

        Args:
            *args: 传递给 nn.Conv3d 的位置参数。
            inflation_mode: 权重膨胀模式。
            memory_device: 缓存设备，'cpu' 卸载到CPU，'same' 保留在GPU。
            **kwargs: 传递给 nn.Conv3d 的关键字参数。
        """
        self.inflation_mode = inflation_mode
        self.memory = None
        super().__init__(*args, **kwargs)
        self.temporal_padding = self.padding[0]
        self.memory_device = memory_device
        self.padding = (0, *self.padding[1:])  # Remove temporal pad to keep causal.
        self.memory_limit = float("inf")

    def set_memory_limit(self, value: float):
        """设置单卷积的显存上限（GiB）。

        超过该限制时，memory_limit_conv 会自动递归沿空间维度分片计算。

        Args:
            value: 显存限制（GiB），float('inf') 表示不分片。
        """
        self.memory_limit = value

    def set_memory_device(self, memory_device: _memory_device_t):
        """设置时序记忆缓存的存储设备。

        Args:
            memory_device: 'cpu' 卸载到CPU；'same' 保留在GPU。
        """
        self.memory_device = memory_device

    def memory_limit_conv(
        self,
        x,
        *,
        split_dim=3,
        padding=(0, 0, 0, 0, 0, 0),
        prev_cache=None,
    ):
        """带显存限制的递归分卷积计算。

        当输入+padding+缓存预估显存超过 memory_limit 时，沿 split_dim 维度
        将输入切分为多块递归计算，每块内部再沿更高维度递归分片，直到显存
        满足限制或到达最后一维（通道维不切分）。各块计算后拼接为完整输出。

        分片策略：按预估显存比例计算切分数，等长切分（最后一块取余数）。
        跨块边界处自动保存尾部 cache_len 个元素作为下一块的前缀缓存，
        确保卷积在块边界处的正确性。

        Args:
            x: 输入张量 [B, C, T, H, W]。
            split_dim: 当前递归切分维度（3=H, 4=W，初始从H开始）。
            padding: 6维填充 (left,right,top,bottom,front,back) 展平为元组。
            prev_cache: 来自前一块的前缀缓存，拼接到当前块前部。

        Returns:
            Tensor: 卷积输出，形状与不分片时一致。
        """
        # Compatible with no limit.
        if math.isinf(self.memory_limit):
            if prev_cache is not None:
                x = torch.cat([prev_cache, x], dim=split_dim - 1)
            return super().forward(x)

        # Compute tensor shape after concat & padding.
        shape = torch.tensor(x.size())
        if prev_cache is not None:
            shape[split_dim - 1] += prev_cache.size(split_dim - 1)
        shape[-3:] += torch.tensor(padding).view(3, 2).sum(-1).flip(0)
        memory_occupy = shape.prod() * x.element_size() / 1024**3  # GiB
        logger.debug(
            f"x:{(shape, x.dtype)} {memory_occupy:.3f}GiB "
            f"prev_cache:{prev_cache.shape if prev_cache is not None else None}"
        )
        if memory_occupy < self.memory_limit or split_dim == x.ndim:
            if prev_cache is not None:
                x = torch.cat([prev_cache, x], dim=split_dim - 1)
            x = safe_pad_operation(x, padding, value=0.0)
            with ignore_padding(self):
                return super().forward(x)

        logger.debug(f"Exceed memory limit {memory_occupy} > {self.memory_limit}, split dim {split_dim}")

        # Split input (& prev_cache).
        num_splits = math.ceil(memory_occupy / self.memory_limit)
        size_per_split = x.size(split_dim) // num_splits
        split_sizes = [size_per_split] * (num_splits - 1)
        split_sizes += [x.size(split_dim) - sum(split_sizes)]

        x = list(x.split(split_sizes, dim=split_dim))
        logger.debug(f"Conv inputs: {[inp.size() for inp in x]} {x[0].dtype}")
        if prev_cache is not None:
            prev_cache = list(prev_cache.split(split_sizes, dim=split_dim))

        # Loop Fwd.
        cache = None
        for idx in range(len(x)):
            # Concat prev cache from last dim
            if prev_cache is not None:
                x[idx] = torch.cat([prev_cache[idx], x[idx]], dim=split_dim - 1)

            # Get padding pattern.
            lpad_dim = (x[idx].ndim - split_dim - 1) * 2
            rpad_dim = lpad_dim + 1
            padding = list(padding)
            padding[lpad_dim] = self.padding[split_dim - 2] if idx == 0 else 0
            padding[rpad_dim] = self.padding[split_dim - 2] if idx == len(x) - 1 else 0
            pad_len = padding[lpad_dim] + padding[rpad_dim]
            padding = tuple(padding)

            # Prepare cache for next slice (this dim).
            next_cache = None
            cache_len = cache.size(split_dim) if cache is not None else 0
            next_catch_size = get_cache_size(
                conv_module=self,
                input_len=x[idx].size(split_dim) + cache_len,
                pad_len=pad_len,
                dim=split_dim - 2,
            )
            if next_catch_size != 0:
                assert next_catch_size <= x[idx].size(split_dim)
                next_cache = x[idx].transpose(0, split_dim)[-next_catch_size:].transpose(0, split_dim)

            # Recursive.
            x[idx] = self.memory_limit_conv(
                x[idx],
                split_dim=split_dim + 1,
                padding=padding,
                prev_cache=cache,
            )

            # Update cache.
            cache = next_cache

        logger.debug(f"Conv outputs, concat(dim={split_dim}): {[d.size() for d in x]}")
        return torch.cat(x, split_dim)

    def forward(
        self,
        input: Tensor | list[Tensor],
        memory_state: MemoryState = MemoryState.UNSET,
    ) -> Tensor:
        """因果3D卷积前向入口。

        根据配置选择 basic_forward 或 slicing_forward。

        Args:
            input: 输入张量 [B,C,T,H,W] 或张量列表（分片模式）。
            memory_state: 记忆状态。

        Returns:
            Tensor: 卷积输出。
        """
        assert memory_state != MemoryState.UNSET
        if memory_state != MemoryState.ACTIVE:
            self.memory = None
        if math.isinf(self.memory_limit) and torch.is_tensor(input) and get_sequence_parallel_group() is None:
            return self.basic_forward(input, memory_state)
        return self.slicing_forward(input, memory_state)

    def basic_forward(self, input: Tensor, memory_state: MemoryState = MemoryState.UNSET):
        """基础前向：无分片、无序列并行的简单因果卷积。

        适用于小张量或单卡推理场景。

        Args:
            input: 输入张量 [B,C,T,H,W]。
            memory_state: 记忆状态。

        Returns:
            Tensor: 卷积输出。
        """
        mem_size = self.stride[0] - self.kernel_size[0]
        if (self.memory is not None) and (memory_state == MemoryState.ACTIVE):
            input = extend_head(input, memory=self.memory, times=-1)
        else:
            input = extend_head(input, times=self.temporal_padding * 2)
        memory = input[:, :, mem_size:].detach() if (mem_size != 0 and memory_state != MemoryState.DISABLED) else None
        if memory_state != MemoryState.DISABLED and not self.training and (self.memory_device is not None):
            self.memory = memory
            if self.memory_device == "cpu" and self.memory is not None:
                self.memory = self.memory.to("cpu")
        return super().forward(input)

    def slicing_forward(
        self,
        input: Tensor | list[Tensor],
        memory_state: MemoryState = MemoryState.UNSET,
    ) -> Tensor:
        """分片前向：支持序列并行和流式切片推理。

        流程：
        1. 通过 cache_send_recv 在相邻GPU间传递时序缓存（序列并行模式）。
        2. 沿时间维将输入切成多个切片，逐片调用 memory_limit_conv。
        3. 维护跨片缓存 cache，拼接到下一片输入前部以保持卷积连续性。
        4. 首尾GPU维护流式记忆 self.memory，支持超长视频的流式处理。

        Args:
            input: 输入张量或张量列表。
            memory_state: 记忆状态。

        Returns:
            Tensor: 拼接后的卷积输出。
        """
        squeeze_out = False
        if torch.is_tensor(input):
            input = [input]
            squeeze_out = True

        cache_size = self.kernel_size[0] - self.stride[0]
        cache = cache_send_recv(input, cache_size=cache_size, memory=self.memory, times=self.temporal_padding * 2)

        # For slice=4 and sp=2, and 17 frames in total
        #                  sp0                  sp1
        # slice 0: [`0 0` 0 1 2 {3 4}]   [{3 4} 5 6 (7 8)]    extend=`0 0` cache={3 4} memory=(7 8)
        # slice 1: [(7 8) 9 10 {11 12}]  [{11 12} 13 14 15 16]
        sp_rank = get_sequence_parallel_rank()
        sp_size = get_sequence_parallel_world_size()
        sp_group = get_sequence_parallel_group()
        send_dst = get_next_sequence_parallel_rank()
        recv_src = get_prev_sequence_parallel_rank()
        if (
            memory_state in [MemoryState.INITIALIZING, MemoryState.ACTIVE]  # use_slicing
            and not self.training
            and (self.memory_device is not None)
            and sp_rank in [0, sp_size - 1]
            and cache_size != 0
        ):
            if cache_size > input[-1].size(2) and cache is not None and len(input) == 1:
                input[0] = torch.cat([cache, input[0]], dim=2)
                cache = None
            assert cache_size <= input[-1].size(2)
            if sp_size == 1:
                self.memory = input[-1][:, :, -cache_size:].detach().contiguous()
            else:
                if sp_rank == sp_size - 1:
                    dist.send(
                        input[-1][:, :, -cache_size:].detach().contiguous(),
                        send_dst,
                        group=sp_group,
                    )
                if sp_rank == 0:
                    shape = list(input[0].size())
                    shape[2] = cache_size
                    self.memory = torch.empty(*shape, device=input[0].device, dtype=input[0].dtype).contiguous()
                    dist.recv(self.memory, recv_src, group=sp_group)
            if self.memory_device == "cpu" and self.memory is not None:
                self.memory = self.memory.to("cpu")

        padding = tuple(x for x in reversed(self.padding) for _ in range(2))
        for i in range(len(input)):
            # Prepare cache for next input slice.
            next_cache = None
            cache_size = 0
            if i < len(input) - 1:
                cache_len = cache.size(2) if cache is not None else 0
                cache_size = get_cache_size(self, input[i].size(2) + cache_len, pad_len=0)
            if cache_size != 0:
                if cache_size > input[i].size(2) and cache is not None:
                    input[i] = torch.cat([cache, input[i]], dim=2)
                    cache = None
                assert cache_size <= input[i].size(2), f"{cache_size} > {input[i].size(2)}"
                next_cache = input[i][:, :, -cache_size:]

            # Conv forward for this input slice.
            input[i] = self.memory_limit_conv(
                input[i],
                padding=padding,
                prev_cache=cache,
            )

            # Update cache.
            cache = next_cache

        return input[0] if squeeze_out else input

    def tflops(self, args, kwargs, output) -> float:
        """估计该卷积层的 TFLOPs。

        公式：2 * Kt*Kh*Kw * Cin * Numel_out / 1e12。

        Args:
            args: 前向调用位置参数（未使用）。
            kwargs: 前向调用关键字参数（未使用）。
            output: 前向输出张量。

        Returns:
            float: 浮点运算量（百万次）。
        """
        if torch.is_tensor(output):
            output_numel = output.numel()
        elif isinstance(output, list):
            output_numel = sum(o.numel() for o in output)
        else:
            raise NotImplementedError
        return (2 * math.prod(self.kernel_size) * self.in_channels * (output_numel / 1e6)) / 1e6

    def _load_from_state_dict(
        self, state_dict, prefix, local_metadata, strict, missing_keys, unexpected_keys, error_msgs
    ):
        """加载state_dict时自动膨胀2D权重到3D（完整版）。"""
        if self.inflation_mode != "none":
            state_dict = modify_state_dict(
                self,
                state_dict,
                prefix,
                inflate_weight_fn=inflate_weight,
                inflate_bias_fn=inflate_bias,
            )
        super()._load_from_state_dict(
            state_dict,
            prefix,
            local_metadata,
            (strict and self.inflation_mode == "none"),
            missing_keys,
            unexpected_keys,
            error_msgs,
        )


def init_causal_conv3d(
    *args,
    inflation_mode: _inflation_mode_t,
    **kwargs,
):
    """初始化完整版因果3D卷积层。

    Args:
        *args: 位置参数。
        inflation_mode: 膨胀模式：
            - 'none': 不膨胀（原生3D权重）。
            - 'tail': 2D权重放在时间核尾部（初始仅看当前帧）。
            - 'replicate': 2D权重复制到时间核并平均（初始等价于时间平均+2D卷积）。
        **kwargs: 关键字参数。

    Returns:
        InflatedCausalConv3d: 因果3D卷积层实例。
    """
    return InflatedCausalConv3d(*args, inflation_mode=inflation_mode, **kwargs)


def causal_norm_wrapper(norm_layer: nn.Module, x: torch.Tensor) -> torch.Tensor:
    """完整版因果归一化包装器，支持大张量分块GroupNorm。

    相比基础版增加了：当GroupNorm处理的(B*T, C, H, W)张量超过全局norm_limit时，
    按通道维度分成2或4块独立计算GroupNorm后拼接，避免大显存峰值。
    fp16时分2块，fp32时分4块。

    Args:
        norm_layer: 归一化层。
        x: 输入张量 4D 或 5D。

    Returns:
        torch.Tensor: 归一化结果。
    """
    input_dtype = x.dtype
    if isinstance(norm_layer, (nn.LayerNorm, RMSNorm)):
        if x.ndim == 4:
            x = rearrange(x, "b c h w -> b h w c")
            x = norm_layer(x)
            x = rearrange(x, "b h w c -> b c h w")
            return x.to(input_dtype)
        if x.ndim == 5:
            x = rearrange(x, "b c t h w -> b t h w c")
            x = norm_layer(x)
            x = rearrange(x, "b t h w c -> b c t h w")
            return x.to(input_dtype)
    if isinstance(norm_layer, (nn.GroupNorm, nn.BatchNorm2d, nn.SyncBatchNorm)):
        if x.ndim <= 4:
            return norm_layer(x).to(input_dtype)
        if x.ndim == 5:
            t = x.size(2)
            x = rearrange(x, "b c t h w -> (b t) c h w")
            memory_occupy = x.numel() * x.element_size() / 1024**3
            if isinstance(norm_layer, nn.GroupNorm) and memory_occupy > get_norm_limit():
                num_chunks = min(4 if x.element_size() == 2 else 2, norm_layer.num_groups)
                logger.debug(f"large tensor {x.shape}, norm in {num_chunks} chunks")
                assert norm_layer.num_groups % num_chunks == 0
                num_groups_per_chunk = norm_layer.num_groups // num_chunks

                x = list(x.chunk(num_chunks, dim=1))
                weights = norm_layer.weight.chunk(num_chunks, dim=0)
                biases = norm_layer.bias.chunk(num_chunks, dim=0)
                for i, (w, b) in enumerate(zip(weights, biases, strict=False)):
                    x[i] = F.group_norm(x[i], num_groups_per_chunk, w, b, norm_layer.eps)
                    x[i] = x[i].to(input_dtype)
                x = torch.cat(x, dim=1)
            else:
                x = norm_layer(x)
            x = rearrange(x, "(b t) c h w -> b c t h w", t=t)
            return x.to(input_dtype)
    raise NotImplementedError


def remove_head(tensor: Tensor, times: int = 1) -> Tensor:
    """移除上采样过程中重复的首帧特征。

    时序上采样（pixel shuffle式）会在时间维产生重复首帧，此函数裁剪多余帧。
    序列并行模式下，非首rank（sp_rank>0）不做裁剪（无重复首帧问题）。

    Args:
        tensor: 输入 [B,C,T,H,W]。
        times: 重复帧数。

    Returns:
        Tensor: 裁剪后的张量。
    """
    sp_rank = get_sequence_parallel_rank()
    if times == 0 or sp_rank > 0:
        return tensor
    return torch.cat(tensors=(tensor[:, :, :1], tensor[:, :, times + 1 :]), dim=2)


def extend_head(tensor: Tensor, times: int = 2, memory: Tensor | None = None) -> Tensor:
    """在因果卷积前扩展输入的时序头部。

    - memory 不为 None：拼接前序缓存帧（流式推理）。
    - times > 0：重复首帧 times 次作为因果填充（首次推理或非流式）。
    - times = -1：使用memory但不重复首帧（内部状态）。

    Args:
        tensor: 输入 [B,C,T,H,W]。
        times: 首帧重复次数，默认2（对应kernel_t=3的因果填充）。
        memory: 前序缓存帧。

    Returns:
        Tensor: 扩展后的输入。
    """
    if memory is not None:
        return torch.cat((memory.to(tensor), tensor), dim=2)
    assert times >= 0, "Invalid input for function 'extend_head'!"
    if times == 0:
        return tensor
    else:
        tile_repeat = [1] * tensor.ndim
        tile_repeat[2] = times
        return torch.cat(tensors=(torch.tile(tensor[:, :, :1], tile_repeat), tensor), dim=2)


def inflate_weight(weight_2d: torch.Tensor, weight_3d: torch.Tensor, inflation_mode: str):
    """完整版权重膨胀函数。

    与 inflated_lib 版本的区别：膨胀模式名称使用 'tail' 而非 'constant'。

    Args:
        weight_2d: 2D权重 [Cout,Cin,kH,kW]。
        weight_3d: 3D权重 [Cout,Cin,kT,kH,kW]。
        inflation_mode: 'replicate' 或 'tail'。

    Returns:
        torch.Tensor: 膨胀后的3D权重。
    """
    assert inflation_mode in ["tail", "replicate"]
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
    """偏置膨胀函数，直接复制2D偏置到3D。

    Args:
        bias_2d: 2D偏置 [Cout]。
        bias_3d: 3D偏置 [Cout]。
        inflation_mode: 膨胀模式占位符。

    Returns:
        torch.Tensor: 3D偏置。
    """
    assert bias_3d.shape == bias_2d.shape
    with torch.no_grad():
        bias_3d.copy_(bias_2d)
    return bias_3d


def modify_state_dict(layer, state_dict, prefix, inflate_weight_fn, inflate_bias_fn):
    """完整版state_dict修改函数，2D→3D权重自动膨胀。

    Args:
        layer: 目标层（需有inflation_mode属性）。
        state_dict: 待加载的state_dict。
        prefix: 参数前缀。
        inflate_weight_fn: 权重膨胀函数。
        inflate_bias_fn: 偏置膨胀函数。

    Returns:
        dict: 修改后的state_dict。
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

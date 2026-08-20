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

"""序列并行（Context Parallel）工具库。

支持在多GPU序列并行场景下对因果卷积的输入进行切分、输出进行聚合，
以及跨GPU的缓存（时序上下文）发送/接收。用于长视频推理时将时序维度
分布到多个GPU上并行处理，同时通过环形通信保持因果一致性。
"""

import torch
import torch.distributed as dist
from torch import Tensor

from common.distributed import get_device
from common.distributed.advanced import (
    get_next_sequence_parallel_rank,
    get_prev_sequence_parallel_rank,
    get_sequence_parallel_group,
    get_sequence_parallel_rank,
    get_sequence_parallel_world_size,
)
from common.distributed.ops import Gather
from common.logger import get_logger
from common.utils import safe_pad_operation
from model_lib.video_vae_v3.modules.types import MemoryState

logger = get_logger(__name__)


def causal_conv_slice_inputs(x: Tensor, split_size: int, memory_state: MemoryState) -> Tensor:
    """在序列并行模式下沿时序维度切分输入张量。

    将输入视频张量 [B, C, T, H, W] 按时序维度均匀切分到 sp_size 个GPU上。
    第一个切片额外保留首帧用于因果卷积的重复填充。

    Args:
        x: 输入张量，形状 [B, C, T, H, W]。
        split_size: 每个GPU处理的最小时序切片长度。
        memory_state: 当前记忆状态，决定首帧是否需要保留。

    Returns:
        Tensor: 当前 rank 对应的切片，形状 [B, C, T_local, H, W]。
        若未启用序列并行则直接返回原张量。

    Raises:
        AssertionError: 当切片数量少于并行世界大小时。
    """
    sp_size = get_sequence_parallel_world_size()
    sp_group = get_sequence_parallel_group()
    sp_rank = get_sequence_parallel_rank()
    if sp_group is None:
        return x

    assert memory_state != MemoryState.UNSET
    leave_out = 1 if memory_state != MemoryState.ACTIVE else 0

    # Should have at least sp_size slices.
    num_slices = (x.size(2) - leave_out) // split_size
    assert num_slices >= sp_size, f"{num_slices} < {sp_size}"

    split_sizes = [split_size + leave_out] + [split_size] * (num_slices - 1)
    split_sizes += [x.size(2) - sum(split_sizes)]
    assert sum(split_sizes) == x.size(2)

    split_sizes = torch.tensor(split_sizes)
    slices_per_rank = len(split_sizes) // sp_size
    split_sizes = split_sizes.split(
        [slices_per_rank] * (sp_size - 1) + [len(split_sizes) - slices_per_rank * (sp_size - 1)]
    )
    split_sizes = [s.sum().item() for s in split_sizes]
    logger.debug(f"split_sizes: {split_sizes}")
    return x.split(split_sizes, dim=2)[sp_rank]


def causal_conv_gather_outputs(x: Tensor) -> Tensor:
    """在序列并行模式下聚合各GPU的输出张量。

    将各 rank 的输出 [B, C, T_local, H, W] 通过 AllGather 收集并拼接为完整序列。
    各 rank 的输出长度可能不同（因切分不均），需先 padding 到统一长度再 Gather，
    最后移除 padding。

    Args:
        x: 当前 rank 的输出张量，形状 [B, C, T_local, H, W]。

    Returns:
        Tensor: 聚合后的完整输出，形状 [B, C, T_total, H, W]。
        若未启用序列并行则直接返回原张量。
    """
    sp_group = get_sequence_parallel_group()
    sp_size = get_sequence_parallel_world_size()
    if sp_group is None:
        return x

    # Communicate shapes.
    unpad_lens = torch.empty((sp_size,), device=get_device(), dtype=torch.long)
    local_unpad_len = torch.tensor([x.size(2)], device=get_device(), dtype=torch.long)
    torch.distributed.all_gather_into_tensor(unpad_lens, local_unpad_len, group=sp_group)

    # Padding to max_len for gather.
    max_len = unpad_lens.max()
    x_pad = safe_pad_operation(x, (0, 0, 0, 0, 0, max_len - x.size(2))).contiguous()

    # Gather outputs.
    x_pad = Gather.apply(sp_group, x_pad, 2, True)

    # Remove padding.
    x_pad_lists = list(x_pad.chunk(sp_size, dim=2))
    for i, (x_pad, unpad_len) in enumerate(zip(x_pad_lists, unpad_lens, strict=False)):
        x_pad_lists[i] = x_pad[:, :, :unpad_len]

    return torch.cat(x_pad_lists, dim=2)


def get_output_len(conv_module, input_len: int, pad_len: int, dim: int = 0) -> int:
    """计算卷积层在指定维度上的输出长度。

    公式：output_len = floor((input_len + pad_len - dilated_kernel) / stride) + 1

    Args:
        conv_module: 卷积模块（nn.Conv3d），包含 kernel_size, stride, dilation 属性。
        input_len: 输入序列长度。
        pad_len: 该维度上的总填充长度。
        dim: 维度索引（0=时间, 1=高度, 2=宽度）。

    Returns:
        int: 输出序列长度。
    """
    dilated_kernerl_size = conv_module.dilation[dim] * (conv_module.kernel_size[dim] - 1) + 1
    output_len = (input_len + pad_len - dilated_kernerl_size) // conv_module.stride[dim] + 1
    return output_len


def get_cache_size(conv_module, input_len: int, pad_len: int, dim: int = 0) -> int:
    """计算因果卷积需要缓存的前序上下文长度。

    缓存长度 = 重叠长度（kernel - stride） + 剩余长度（不足以形成一个完整输出步长的部分），
    用于下一个切片卷积时保持时序连续性。

    Args:
        conv_module: 卷积模块。
        input_len: 输入序列长度（含已拼接的前序缓存）。
        pad_len: 该维度填充长度。
        dim: 维度索引。

    Returns:
        int: 需要缓存的帧数/像素数。保证 >= 0。
    """
    dilated_kernerl_size = conv_module.dilation[dim] * (conv_module.kernel_size[dim] - 1) + 1
    output_len = (input_len + pad_len - dilated_kernerl_size) // conv_module.stride[dim] + 1
    remain_len = input_len + pad_len - ((output_len - 1) * conv_module.stride[dim] + dilated_kernerl_size)
    overlap_len = dilated_kernerl_size - conv_module.stride[dim]
    cache_len = overlap_len + remain_len  # >= 0
    logger.debug(
        f"I:{input_len}, "
        f"P:{pad_len}, "
        f"K:{conv_module.kernel_size[dim]}, "
        f"S:{conv_module.stride[dim]}, "
        f"O:{output_len}, "
        f"Cache:{cache_len}"
    )
    assert output_len > 0
    return cache_len


def cache_send_recv(tensor: list[Tensor], cache_size: int, times: int, memory: Tensor = None) -> Tensor:
    """在序列并行的相邻GPU之间发送/接收因果卷积缓存。

    实现环形通信：rank i 将尾部 cache_size 帧发送给 rank i+1，
    同时从 rank i-1 接收 cache_size 帧作为前缀缓存。首帧（rank 0）使用 memory 或
    重复第一帧进行填充。

    Args:
        tensor: 输入张量列表，每个元素为 [B, C, T, H, W]。
        cache_size: 需要缓存/传递的帧数。若为0则不通信。
        times: 首帧重复填充次数（用于INITIALIZING状态）。
        memory: 上一流式切片的记忆缓存，仅 rank 0 使用。

    Returns:
        Tensor: 需要拼接到当前输入前面的缓存张量，形状 [B, C, cache_size, H, W]；
        若无需缓存则返回 None。
    """
    sp_group = get_sequence_parallel_group()
    sp_rank = get_sequence_parallel_rank()
    sp_size = get_sequence_parallel_world_size()
    send_dst = get_next_sequence_parallel_rank()
    recv_src = get_prev_sequence_parallel_rank()
    recv_buffer = None
    recv_req = None

    logger.debug(f"[sp{sp_rank}] cur_tensors:{[(t.size(), t.dtype) for t in tensor]}, times: {times}")
    if sp_rank == 0 or sp_group is None:
        if memory is not None:
            recv_buffer = memory.to(tensor[0])
        elif times > 0:
            tile_repeat = [1] * tensor[0].ndim
            tile_repeat[2] = times
            recv_buffer = torch.tile(tensor[0][:, :, :1], tile_repeat)

    if cache_size != 0 and sp_group is not None:
        if sp_rank > 0:
            shape = list(tensor[0].size())
            shape[2] = cache_size
            recv_buffer = torch.empty(*shape, device=tensor[0].device, dtype=tensor[0].dtype).contiguous()
            recv_req = dist.irecv(recv_buffer, recv_src, group=sp_group)
        if sp_rank < sp_size - 1:
            if cache_size > tensor[-1].size(2) and len(tensor) == 1:
                logger.debug(f"[sp{sp_rank}] force concat before send {tensor[-1].size()}")
                if recv_req is not None:
                    recv_req.wait()
                tensor[0] = torch.cat([recv_buffer, tensor[0]], dim=2)
                recv_buffer = None
            assert cache_size <= tensor[-1].size(
                2
            ), f"Not enough value to cache, got {tensor[-1].size()}, cache_size={cache_size}"
            dist.isend(tensor[-1][:, :, -cache_size:].detach().contiguous(), send_dst, group=sp_group)
        if recv_req is not None:
            recv_req.wait()

    logger.debug(
        f"[sp{sp_rank}] recv_src:{recv_src}, " f"recv_buffer:{recv_buffer.size() if recv_buffer is not None else None}"
    )
    return recv_buffer

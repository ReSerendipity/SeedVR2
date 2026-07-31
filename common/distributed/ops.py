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

"""Distributed communication operations for sequence parallelism.

**Sequence Parallelism Communication Primitives:**

This module implements custom PyTorch autograd functions for sequence-parallel
training of transformer models. In sequence parallelism, the sequence dimension
is split across GPUs within a group, and all-to-all communication is used to
exchange data before and after self-attention so that each GPU computes attention
over a subset of heads but all sequence tokens.

Key operations:
- **All-to-All** (``SeqAllToAll``): Swaps data between the sequence and head
  dimensions across GPUs. Forward: scatter sequence, gather heads. Backward:
  scatter heads, gather sequence.
- **Slice** (``Slice``): Splits a tensor along a dimension and keeps the local
  shard. Backward performs all-gather.
- **Gather** (``Gather``): All-gathers tensor shards along a dimension. Backward
  slices the gradient to the local shard.

Higher-level convenience functions:
- ``gather_seq_scatter_heads_qkv``: Handles QKV projection before attention
  (gather seq -> scatter heads).
- ``slice_inputs``: Splits input sequences for SP processing.
- ``gather_heads_scatter_seq``: Attention output: gather heads -> scatter seq.
- ``scatter_heads`` / ``gather_heads``: Standalone head slice/gather.
- ``gather_outputs``: Final output gathering with padding removal.
- ``SPDistForward`` / ``sync_inputs``: Utility for broadcasting inputs across
  SP ranks with async pipelining for overlap.
"""

from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import torch
import torch.distributed as dist
from torch import Tensor

from common.cache import Cache
from common.distributed.advanced import (
    get_sequence_parallel_group,
    get_sequence_parallel_rank,
    get_sequence_parallel_world_size,
)

from .basic import get_device

_SEQ_DATA_BUF = defaultdict(lambda: [None, None, None])
_SEQ_DATA_META_SHAPES = defaultdict()
_SEQ_DATA_META_DTYPES = defaultdict()
_SEQ_DATA_ASYNC_COMMS = defaultdict(list)
_SYNC_BUFFER = defaultdict(dict)


def single_all_to_all(
    local_input: Tensor,
    scatter_dim: int,
    gather_dim: int,
    group: dist.ProcessGroup,
    async_op: bool = False,
):
    """Perform a single all-to-all communication using all_to_all_single.

    Rearranges data by scattering along ``scatter_dim`` and gathering along
    ``gather_dim``. The scatter dimension is transposed to dim 0 for efficient
    communication, then transposed back after gathering.

    Args:
        local_input: Input tensor to exchange.
        scatter_dim: Dimension along which to split and scatter data to other ranks.
        gather_dim: Dimension along which to gather received data.
        group: Process group for the collective communication.
        async_op: If True, returns the async work handle for later waiting.

    Returns:
        If async_op is False, returns the output tensor. If async_op is True,
        returns (output, work_handle, prev_scatter_dim) for the caller to
        finish transpose/reshape.
    """
    seq_world_size = dist.get_world_size(group)
    prev_scatter_dim = scatter_dim
    if scatter_dim != 0:
        local_input = local_input.transpose(0, scatter_dim)
        if gather_dim == 0:
            gather_dim = scatter_dim
        scatter_dim = 0

    inp_shape = list(local_input.shape)
    inp_shape[scatter_dim] = inp_shape[scatter_dim] // seq_world_size
    input_t = local_input.reshape(
        [seq_world_size, inp_shape[scatter_dim]] + inp_shape[scatter_dim + 1 :]
    ).contiguous()
    output = torch.empty_like(input_t)
    comm = dist.all_to_all_single(output, input_t, group=group, async_op=async_op)
    if async_op:
        return output, comm, prev_scatter_dim

    output = torch.cat(output.split(1), dim=gather_dim + 1).squeeze(0)
    if prev_scatter_dim:
        output = output.transpose(0, prev_scatter_dim).contiguous()
    return output


def _all_to_all(
    local_input: Tensor,
    scatter_dim: int,
    gather_dim: int,
    group: dist.ProcessGroup,
):
    """Perform all-to-all using the list-based all_to_all API.

    Splits ``local_input`` along ``scatter_dim`` into seq_world_size chunks,
    sends chunk i to rank i, receives chunks from all ranks, and concatenates
    them along ``gather_dim``.

    Args:
        local_input: Input tensor.
        scatter_dim: Dimension to split for scattering.
        gather_dim: Dimension to concatenate received chunks.
        group: Process group.

    Returns:
        Gathered output tensor.
    """
    seq_world_size = dist.get_world_size(group)
    input_list = [
        t.contiguous() for t in torch.tensor_split(local_input, seq_world_size, scatter_dim)
    ]
    output_list = [torch.empty_like(input_list[0]) for _ in range(seq_world_size)]
    dist.all_to_all(output_list, input_list, group=group)
    return torch.cat(output_list, dim=gather_dim).contiguous()


class SeqAllToAll(torch.autograd.Function):
    """Custom autograd function for sequence-parallel all-to-all communication.

    Implements the forward and backward passes for scattering along one
    dimension and gathering along another, with correct gradient computation.

    Forward: scatter along ``scatter_dim``, gather along ``gather_dim``.
    Backward: reverse the dimensions (scatter along gather_dim, gather along scatter_dim).

    This is the core communication primitive for exchanging QKV between
    sequence-sharded GPUs in attention.
    """

    @staticmethod
    def forward(
        ctx: Any,
        group: dist.ProcessGroup,
        local_input: Tensor,
        scatter_dim: int,
        gather_dim: int,
        async_op: bool,
    ) -> Tensor:
        """Forward pass: all-to-all exchanging scatter_dim for gather_dim.

        Args:
            ctx: Autograd context for saving tensors/state.
            group: SP process group.
            local_input: Input tensor.
            scatter_dim: Dimension to scatter.
            gather_dim: Dimension to gather.
            async_op: If True, perform async communication.

        Returns:
            Output tensor (or tuple with comm handle if async_op).
        """
        ctx.group = group
        ctx.scatter_dim = scatter_dim
        ctx.gather_dim = gather_dim
        ctx.async_op = async_op
        if async_op:
            output, comm, prev_scatter_dim = single_all_to_all(
                local_input, scatter_dim, gather_dim, group, async_op=async_op
            )
            ctx.prev_scatter_dim = prev_scatter_dim
            return output, comm

        return _all_to_all(local_input, scatter_dim, gather_dim, group)

    @staticmethod
    def backward(ctx: Any, *grad_output: Tensor) -> Tuple[None, Tensor, None, None]:
        """Backward pass: reverse the all-to-all for gradient computation.

        Gradient flows back through the transpose of the forward operation.
        """
        if ctx.async_op:
            input_t = torch.cat(grad_output[0].split(1), dim=ctx.gather_dim + 1).squeeze(0)
            if ctx.prev_scatter_dim:
                input_t = input_t.transpose(0, ctx.prev_scatter_dim)
        else:
            input_t = grad_output[0]
        return (
            None,
            _all_to_all(input_t, ctx.gather_dim, ctx.scatter_dim, ctx.group),
            None,
            None,
            None,
        )


class Slice(torch.autograd.Function):
    """Custom autograd function to slice a tensor along a dimension for sequence parallelism.

    Forward splits the tensor along ``dim`` and keeps only the local rank's shard.
    Backward performs an all-gather to reconstruct the full gradient tensor.
    """

    @staticmethod
    def forward(ctx: Any, group: dist.ProcessGroup, local_input: Tensor, dim: int) -> Tensor:
        """Forward: slice to local shard.

        Args:
            ctx: Autograd context.
            group: SP process group.
            local_input: Full tensor to slice.
            dim: Dimension along which to split.

        Returns:
            Local shard of the tensor.
        """
        ctx.group = group
        ctx.rank = dist.get_rank(group)
        seq_world_size = dist.get_world_size(group)
        ctx.seq_world_size = seq_world_size
        ctx.dim = dim
        dim_size = local_input.shape[dim]
        return local_input.split(dim_size // seq_world_size, dim=dim)[ctx.rank].contiguous()

    @staticmethod
    def backward(ctx: Any, grad_output: Tensor) -> Tuple[None, Tensor, None]:
        """Backward: all-gather to reconstruct full gradient."""
        dim_size = list(grad_output.size())
        split_size = dim_size[0]
        dim_size[0] = dim_size[0] * ctx.seq_world_size
        output = torch.empty(dim_size, dtype=grad_output.dtype, device=torch.cuda.current_device())
        dist._all_gather_base(output, grad_output, group=ctx.group)
        return (None, torch.cat(output.split(split_size), dim=ctx.dim), None)


class Gather(torch.autograd.Function):
    """Custom autograd function to all-gather tensor shards along a dimension.

    Forward all-gathers shards and concatenates along ``dim``.
    Backward slices the gradient to the local rank's shard.
    """

    @staticmethod
    def forward(
        ctx: Any,
        group: dist.ProcessGroup,
        local_input: Tensor,
        dim: int,
        grad_scale: Optional[bool] = False,
    ) -> Tensor:
        """Forward: all-gather local shards and concatenate.

        Args:
            ctx: Autograd context.
            group: SP process group.
            local_input: Local tensor shard.
            dim: Dimension to concatenate gathered shards.
            grad_scale: If True, scale gradient by world size (for averaging).

        Returns:
            Gathered full tensor.
        """
        ctx.group = group
        ctx.rank = dist.get_rank(group)
        ctx.dim = dim
        ctx.grad_scale = grad_scale
        seq_world_size = dist.get_world_size(group)
        ctx.seq_world_size = seq_world_size
        dim_size = list(local_input.size())
        split_size = dim_size[0]
        ctx.part_size = dim_size[dim]
        dim_size[0] = dim_size[0] * seq_world_size
        output = torch.empty(dim_size, dtype=local_input.dtype, device=torch.cuda.current_device())
        dist._all_gather_base(output, local_input.contiguous(), group=ctx.group)
        return torch.cat(output.split(split_size), dim=dim)

    @staticmethod
    def backward(ctx: Any, grad_output: Tensor) -> Tuple[None, Tensor]:
        """Backward: slice gradient to local shard, optionally scaling."""
        if ctx.grad_scale:
            grad_output = grad_output * ctx.seq_world_size
        return (
            None,
            grad_output.split(ctx.part_size, dim=ctx.dim)[ctx.rank].contiguous(),
            None,
            None,
        )


def gather_seq_scatter_heads_qkv(
    qkv_tensor: Tensor,
    *,
    seq_dim: int,
    qkv_shape: Optional[Tensor] = None,
    cache: Cache = Cache(disable=True),
    restore_shape: bool = True,
):
    """Perform all-to-all to gather sequence and scatter heads for QKV in attention.

    In sequence parallelism, QKV is initially split along the sequence dimension.
    Before attention computation, we need to gather all sequence tokens and scatter
    heads across GPUs so each GPU computes attention for a subset of heads.

    This function:
    1. Reshapes QKV to separate the Q/K/V projection dimension into 3 parts.
    2. Applies all-to-all to swap sequence and head dimensions.
    3. Optionally restores the shape and removes padding.

    Args:
        qkv_tensor: QKV tensor with sequence split across SP ranks. Last dimension
            is the concatenated Q/K/V projection.
        seq_dim: Dimension corresponding to sequence (gather dimension for all-to-all).
        qkv_shape: Original unpadded shape for padding removal.
        cache: Cache for padding size computation.
        restore_shape: If True, reshape output to match expected format.

    Returns:
        QKV tensor with heads scattered and sequence gathered across SP ranks.
    """
    group = get_sequence_parallel_group()
    if not group:
        return qkv_tensor
    world = get_sequence_parallel_world_size()
    orig_shape = qkv_tensor.shape
    scatter_dim = qkv_tensor.dim()
    bef_all2all_shape = list(orig_shape)
    qkv_proj_dim = bef_all2all_shape[-1]
    bef_all2all_shape = bef_all2all_shape[:-1] + [3, qkv_proj_dim // 3]
    qkv_tensor = qkv_tensor.view(bef_all2all_shape)
    qkv_tensor = SeqAllToAll.apply(group, qkv_tensor, scatter_dim, seq_dim, False)
    if restore_shape:
        out_shape = list(orig_shape)
        out_shape[seq_dim] *= world
        out_shape[-1] = qkv_proj_dim // world
        qkv_tensor = qkv_tensor.view(out_shape)

    if qkv_shape is not None:
        unpad_dim_size = cache(
            "unpad_dim_size", lambda: torch.sum(torch.prod(qkv_shape, dim=-1)).item()
        )
        if unpad_dim_size % world != 0:
            padding_size = qkv_tensor.size(seq_dim) - unpad_dim_size
            qkv_tensor = _unpad_tensor(qkv_tensor, seq_dim, padding_size)
    return qkv_tensor


def slice_inputs(x: Tensor, dim: int, padding: bool = True):
    """Slice input tensor along a dimension for sequence parallel processing.

    Splits the input evenly across SP ranks, adding padding if necessary to
    ensure divisibility.

    Args:
        x: Input tensor to split.
        dim: Dimension along which to split (typically sequence dimension).
        padding: If True, pad tensor to be divisible by SP world size before slicing.

    Returns:
        Local shard of the input tensor.
    """
    group = get_sequence_parallel_group()
    if group is None:
        return x
    sp_rank = get_sequence_parallel_rank()
    sp_world = get_sequence_parallel_world_size()
    dim_size = x.shape[dim]
    unit = (dim_size + sp_world - 1) // sp_world
    if padding and dim_size % sp_world:
        padding_size = sp_world - (dim_size % sp_world)
        x = _pad_tensor(x, dim, padding_size)
    slc = [slice(None)] * len(x.shape)
    slc[dim] = slice(unit * sp_rank, unit * (sp_rank + 1))
    return x[slc]


def remove_seqeunce_parallel_padding(x: Tensor, dim: int, unpad_dim_size: int):
    """Remove padding added during sequence parallel slicing.

    Args:
        x: Padded tensor.
        dim: Dimension from which to remove padding.
        unpad_dim_size: Original size before padding.

    Returns:
        Tensor with padding removed.
    """
    group = get_sequence_parallel_group()
    if group is None:
        return x
    sp_world = get_sequence_parallel_world_size()
    if unpad_dim_size % sp_world == 0:
        return x
    padding_size = sp_world - (unpad_dim_size % sp_world)
    assert (padding_size + unpad_dim_size) % sp_world == 0
    return _unpad_tensor(x, dim=dim, padding_size=padding_size)


def gather_heads_scatter_seq(x: Tensor, head_dim: int, seq_dim: int) -> Tensor:
    """Perform all-to-all after attention: gather heads and scatter sequence.

    This is the reverse of ``gather_seq_scatter_heads``: after attention is
    computed with scattered heads, this gathers heads back and scatters
    sequence across SP ranks.

    Args:
        x: Attention output tensor with heads split across SP ranks.
        head_dim: Head dimension (scatter dim for all-to-all).
        seq_dim: Sequence dimension (gather dim for all-to-all).

    Returns:
        Tensor with heads gathered and sequence scattered.
    """
    group = get_sequence_parallel_group()
    if not group:
        return x
    dim_size = x.size(seq_dim)
    sp_world = get_sequence_parallel_world_size()
    if dim_size % sp_world != 0:
        padding_size = sp_world - (dim_size % sp_world)
        x = _pad_tensor(x, seq_dim, padding_size)
    return SeqAllToAll.apply(group, x, seq_dim, head_dim, False)


def gather_seq_scatter_heads(x: Tensor, seq_dim: int, head_dim: int) -> Tensor:
    """Perform all-to-all: gather sequence and scatter heads for embeddings.

    Used for the embedding/projection input before attention layers.

    Args:
        x: Input tensor with sequence split.
        seq_dim: Sequence dimension.
        head_dim: Head dimension.

    Returns:
        Tensor after all-to-all exchange.
    """
    group = get_sequence_parallel_group()
    if not group:
        return x
    return SeqAllToAll.apply(group, x, head_dim, seq_dim, False)


def scatter_heads(x: Tensor, dim: int) -> Tensor:
    """Slice/scatter heads across sequence parallel ranks.

    Args:
        x: Tensor with full heads.
        dim: Dimension along which to scatter heads.

    Returns:
        Local head shard.
    """
    group = get_sequence_parallel_group()
    if not group:
        return x
    return Slice.apply(group, x, dim)


def gather_heads(x: Tensor, dim: int, grad_scale: Optional[bool] = False) -> Tensor:
    """Gather heads from all sequence parallel ranks.

    Args:
        x: Local head shard.
        dim: Dimension along which to gather.
        grad_scale: If True, scale gradients by world size.

    Returns:
        Gathered tensor with all heads.
    """
    group = get_sequence_parallel_group()
    if not group:
        return x
    return Gather.apply(group, x, dim, grad_scale)


def gather_outputs(
    x: Tensor,
    *,
    gather_dim: int,
    padding_dim: Optional[int] = None,
    unpad_shape: Optional[Tensor] = None,
    cache: Cache = Cache(disable=True),
    scale_grad=True,
):
    """Gather final outputs from all SP ranks and remove padding.

    Used after the model forward pass to gather outputs back to a full tensor.

    Args:
        x: Local output shard.
        gather_dim: Dimension along which to gather.
        padding_dim: Dimension from which to remove padding.
        unpad_shape: Original unpadded shape.
        cache: Cache for unpadded size computation.
        scale_grad: If True, scale gradients (passed to Gather).

    Returns:
        Gathered and unpadded output tensor.
    """
    group = get_sequence_parallel_group()
    if not group:
        return x
    x = Gather.apply(group, x, gather_dim, scale_grad)
    if padding_dim is not None:
        unpad_dim_size = cache(
            "unpad_dim_size", lambda: torch.sum(torch.prod(unpad_shape, dim=1)).item()
        )
        x = remove_seqeunce_parallel_padding(x, padding_dim, unpad_dim_size)
    return x


def _pad_tensor(x: Tensor, dim: int, padding_size: int):
    """Pad a tensor with zeros along a given dimension.

    Args:
        x: Tensor to pad.
        dim: Dimension to pad.
        padding_size: Number of zero elements to append.

    Returns:
        Padded tensor.
    """
    shape = list(x.shape)
    shape[dim] = padding_size
    pad = torch.zeros(shape, dtype=x.dtype, device=x.device)
    return torch.cat([x, pad], dim=dim)


def _unpad_tensor(x: Tensor, dim: int, padding_size):
    """Remove padding from a tensor along a given dimension.

    Args:
        x: Padded tensor.
        dim: Dimension from which to remove padding.
        padding_size: Number of elements to remove from the end.

    Returns:
        Unpadded tensor.
    """
    slc = [slice(None)] * len(x.shape)
    slc[dim] = slice(0, -padding_size)
    return x[slc]


def _broadcast_data(data, shape, dtype, src, group, async_op):
    """Recursively broadcast nested data structures (tensors, lists, dicts).

    Args:
        data: Data structure to broadcast (Tensor, list, tuple, or dict).
        shape: Shape(s) of tensor(s) for pre-allocating recv buffers.
        dtype: Dtype(s) of tensor(s).
        src: Source rank.
        group: Process group.
        async_op: If True, returns async work handles.

    Returns:
        List of async work handles if async_op, else None.
    """
    comms = []
    if isinstance(data, (list, tuple)):
        for i, sub_shape in enumerate(shape):
            comms += _broadcast_data(data[i], sub_shape, dtype[i], src, group, async_op)
    elif isinstance(data, dict):
        for key, sub_data in data.items():
            comms += _broadcast_data(sub_data, shape[key], dtype[key], src, group, async_op)
    elif isinstance(data, Tensor):
        comms.append(dist.broadcast(data, src=src, group=group, async_op=async_op))
    return comms


def _traverse(data: Any, op: Callable) -> Union[None, List, Dict, Any]:
    """Recursively traverse nested data structures applying an operation to Tensors.

    Args:
        data: Data structure (Tensor, list, tuple, dict, or scalar).
        op: Callable applied to each Tensor.

    Returns:
        Transformed data structure with the same nesting.
    """
    if isinstance(data, (list, tuple)):
        return [_traverse(sub_data, op) for sub_data in data]
    elif isinstance(data, dict):
        return {key: _traverse(sub_data, op) for key, sub_data in data.items()}
    elif isinstance(data, Tensor):
        return op(data)
    else:
        return None


def _get_shapes(data):
    """Extract shapes from all Tensors in a nested structure.

    Args:
        data: Nested data structure (Tensor, list, tuple, or dict).

    Returns:
        Nested structure of torch.Size objects matching the input structure,
        where each Tensor is replaced by its shape.
    """
    return _traverse(data, op=lambda x: x.shape)


def _get_dtypes(data):
    """Extract dtypes from all Tensors in a nested structure.

    Args:
        data: Nested data structure (Tensor, list, tuple, or dict).

    Returns:
        Nested structure of torch.dtype objects matching the input structure,
        where each Tensor is replaced by its dtype.
    """
    return _traverse(data, op=lambda x: x.dtype)


def _construct_broadcast_buffer(shapes, dtypes, device):
    """Construct empty buffer(s) matching a nested shape/dtype structure for receiving broadcast.

    Args:
        shapes: Nested shape structure (from _get_shapes).
        dtypes: Nested dtype structure (from _get_dtypes).
        device: Device for allocated tensors.

    Returns:
        Nested structure of empty tensors matching shapes/dtypes.
    """
    if isinstance(shapes, torch.Size):
        return torch.empty(shapes, dtype=dtypes, device=device)

    if isinstance(shapes, (list, tuple)):
        buffer = []
        for i, sub_shape in enumerate(shapes):
            buffer.append(_construct_broadcast_buffer(sub_shape, dtypes[i], device))
    elif isinstance(shapes, dict):
        buffer = {}
        for key, sub_shape in shapes.items():
            buffer[key] = _construct_broadcast_buffer(sub_shape, dtypes[key], device)
    else:
        return None
    return buffer


class SPDistForward:
    """Utility for synchronizing data across sequence parallel ranks with async pipelining.

    In some SP workflows, each rank may produce different intermediate results
    that need to be shared across the SP group (e.g., for certain ring-attention
    or cyclic computation patterns). This class implements a ring-broadcast
    pattern where each rank's data is broadcast to all others in sequence,
    using double buffering and async communication to overlap communication
    with computation.

    Args:
        name: Unique name for this forward sync instance (used for buffer storage).
        comm_shape: If True, shapes are gathered across ranks (supports different
            shapes per rank). If False, assumes all ranks have the same shape.
        device: Torch device for buffers. Auto-detected if None.
    """

    def __init__(
        self,
        name: str,
        comm_shape: bool,
        device: torch.device = None,
    ):
        self.name = name
        self.comm_shape = comm_shape
        if device:
            self.device = device
        else:
            self.device = get_device()

    def __call__(self, inputs) -> Any:
        """Synchronize inputs across SP ranks using ring broadcast with async overlap.

        Yields data from each rank in sequence. For each local_step i:
        1. If i==0, rank i broadcasts its input (and shape metadata if comm_shape).
        2. Wait for the previous async broadcast to complete.
        3. Issue the next async broadcast for rank i+1.
        4. Yield the data for current step.

        This pipelining overlaps the broadcast of step i+1 with computation
        of step i.

        Args:
            inputs: Local input tensor/data to share. Only meaningful on rank 0
                of each SP step (i.e., rank == local_step).

        Yields:
            Data from each SP rank in order.
        """
        group = get_sequence_parallel_group()
        if not group:
            yield inputs
        else:
            device = self.device
            sp_world = get_sequence_parallel_world_size()
            sp_rank = get_sequence_parallel_rank()
            for local_step in range(sp_world):
                src_rank = dist.get_global_rank(group, local_step)
                is_src = sp_rank == local_step
                local_shapes = []
                local_dtypes = []
                if local_step == 0:
                    local_result = inputs
                    _SEQ_DATA_BUF[self.name][-1] = local_result
                    local_shapes = _get_shapes(local_result)
                    local_dtypes = _get_dtypes(local_result)
                    if self.comm_shape:
                        group_shapes_lists = [None] * sp_world
                        dist.all_gather_object(group_shapes_lists, local_shapes, group=group)
                        _SEQ_DATA_META_SHAPES[self.name] = group_shapes_lists
                    else:
                        _SEQ_DATA_META_SHAPES[self.name] = [local_shapes] * sp_world
                    _SEQ_DATA_META_DTYPES[self.name] = local_dtypes
                shapes = _SEQ_DATA_META_SHAPES[self.name][local_step]
                dtypes = _SEQ_DATA_META_DTYPES[self.name]
                buf_id = local_step % 2
                if local_step == 0:
                    sync_data = (
                        local_result
                        if is_src
                        else _construct_broadcast_buffer(shapes, dtypes, device)
                    )
                    _broadcast_data(sync_data, shapes, dtypes, src_rank, group, False)
                    _SEQ_DATA_BUF[self.name][buf_id] = sync_data

                if _SEQ_DATA_ASYNC_COMMS[self.name]:
                    for comm in _SEQ_DATA_ASYNC_COMMS[self.name]:
                        comm.wait()
                if local_step < sp_world - 1:
                    next_buf_id = 1 - buf_id
                    shapes = _SEQ_DATA_META_SHAPES[self.name][local_step + 1]
                    src_rank = dist.get_global_rank(group, local_step + 1)
                    is_src = sp_rank == local_step + 1
                    next_sync_data = (
                        _SEQ_DATA_BUF[self.name][-1]
                        if is_src
                        else _construct_broadcast_buffer(shapes, dtypes, device)
                    )
                    _SEQ_DATA_ASYNC_COMMS[self.name] = _broadcast_data(
                        next_sync_data, shapes, dtypes, src_rank, group, True
                    )
                    _SEQ_DATA_BUF[self.name][next_buf_id] = next_sync_data
                yield _SEQ_DATA_BUF[self.name][buf_id]


sync_inputs = SPDistForward(name="bef_fwd", comm_shape=True)


def sync_data(data, sp_idx, name="tmp"):
    """Broadcast data from a specific SP rank to all other ranks.

    Simple synchronous broadcast of a Python object (including tensors)
    using broadcast_object_list.

    Args:
        data: Data to broadcast. Only the data from sp_idx is used; other ranks'
            data is overwritten.
        sp_idx: Source rank within the SP group.
        name: Buffer name (for caching, currently not used).

    Returns:
        The broadcast data (same on all ranks).
    """
    group = get_sequence_parallel_group()
    if group is None:
        return data
    sp_rank = get_sequence_parallel_rank()
    src_rank = dist.get_global_rank(group, sp_idx)
    objects = [data] if sp_rank == sp_idx else [None]
    dist.broadcast_object_list(objects, src=src_rank, group=group)
    return objects[0]

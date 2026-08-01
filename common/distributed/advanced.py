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

"""Advanced distributed utilities for sequence parallelism and FSDP/hybrid sharding.

**Parallelism Strategy Overview:**

This module implements 2D parallelism combining data parallelism with either
sequence parallelism or model sharding (FSDP):

1. **Sequence Parallelism (SP)**:
   - Splits the input sequence dimension across GPUs within a group (typically within a node).
   - Each GPU holds a subset of sequence tokens but full attention heads.
   - Uses all-to-all communication to exchange queries/keys/values before and after
     self-attention, so each GPU computes attention over its assigned heads for all tokens.
   - Communicaton pattern:
     - Before attention: scatter sequence -> gather heads (all-to-all)
     - After attention: gather sequence -> scatter heads (all-to-all)
   - Process groups:
     - Data parallel group: GPUs holding different data shards (same SP rank)
     - Sequence parallel group: GPUs holding different sequence shards (same DP rank)

   Example: 8 GPUs, SP size = 4 (2 data-parallel replicas, each split across 4 GPUs):

       Ranks: [0,1,2,3]  [4,5,6,7]
              <-SP group->  <-SP group->
              <---DP group---><--DP group---> (rank i and rank i+4 are DP peers)

2. **Model Sharding (FSDP/Hybrid)**:
   - Uses PyTorch's DeviceMesh for 2D hybrid sharding.
   - Intra-node: shard model parameters, gradients, optimizer states (FSDP sharding).
   - Inter-node: replicate sharded models for data parallelism across nodes.
   - Supports multiple sharding strategies (NO_SHARD, FULL_SHARD, HYBRID_SHARD).

**CPU Groups:**
CPU (Gloo backend) process groups are also created alongside GPU (NCCL) groups
for operations that need to run on CPU tensors (e.g., meta-device initialization,
shape inference).
"""

import torch
import torch.distributed as dist
from torch.distributed.device_mesh import DeviceMesh, init_device_mesh
from torch.distributed.fsdp import ShardingStrategy

from .basic import get_global_rank, get_world_size

_DATA_PARALLEL_GROUP = None
_SEQUENCE_PARALLEL_GROUP = None
_SEQUENCE_PARALLEL_CPU_GROUP = None
_MODEL_SHARD_CPU_INTER_GROUP = None
_MODEL_SHARD_CPU_INTRA_GROUP = None
_MODEL_SHARD_INTER_GROUP = None
_MODEL_SHARD_INTRA_GROUP = None
_SEQUENCE_PARALLEL_GLOBAL_RANKS = None


def get_data_parallel_group() -> dist.ProcessGroup | None:
    """Get the data parallel (inter-SP) process group.

    GPUs in the same DP group hold different data shards but the same model
    replica (or same FSDP shard position). Gradients are all-reduced across
    this group.

    Returns:
        The DP process group, or None if sequence parallelism is not initialized.
    """
    return _DATA_PARALLEL_GROUP


def get_sequence_parallel_group() -> dist.ProcessGroup | None:
    """Get the sequence parallel (intra-SP) process group.

    GPUs in the same SP group work together on the same data sample, with
    sequence tokens split across members. All-to-all communication occurs
    within this group during attention.

    Returns:
        The SP NCCL (GPU) process group, or None if SP is not initialized.
    """
    return _SEQUENCE_PARALLEL_GROUP


def get_sequence_parallel_cpu_group() -> dist.ProcessGroup | None:
    """Get the sequence parallel CPU (Gloo) process group.

    Same membership as the GPU SP group but uses Gloo backend for CPU tensors.

    Returns:
        The SP Gloo (CPU) process group, or None if SP is not initialized.
    """
    return _SEQUENCE_PARALLEL_CPU_GROUP


def get_data_parallel_rank() -> int:
    """Get the rank of the current process within its data parallel group.

    Returns:
        Rank within the DP group, or global rank if SP is not initialized.
    """
    group = get_data_parallel_group()
    if group is not None and dist.is_initialized():
        return dist.get_rank(group)
    return get_global_rank()


def get_data_parallel_world_size() -> int:
    """Get the size of the data parallel group (number of DP replicas).

    Returns:
        DP group size, or world size if SP is not initialized.
    """
    group = get_data_parallel_group()
    if group is not None and dist.is_initialized():
        return dist.get_world_size(group)
    return get_world_size()


def get_sequence_parallel_rank() -> int:
    """Get the rank of the current process within its sequence parallel group.

    Returns:
        Rank within the SP group (0 to sp_size-1), or 0 if SP is not initialized.
    """
    group = get_sequence_parallel_group()
    if group is not None and dist.is_initialized():
        return dist.get_rank(group)
    return 0


def get_sequence_parallel_world_size() -> int:
    """Get the size of the sequence parallel group (sequence split factor).

    Returns:
        SP group size, or 1 if SP is not initialized.
    """
    group = get_sequence_parallel_group()
    if group is not None and dist.is_initialized():
        return dist.get_world_size(group)
    return 1


def get_model_shard_cpu_intra_group() -> dist.ProcessGroup | None:
    """Get the CPU (Gloo) intra-node process group for model sharding.

    Used for CPU-side operations during FSDP initialization (e.g., parameter
    shape/dtype inference on CPU before sharding to GPU).

    Returns:
        The intra-node CPU process group for FSDP sharding.
    """
    return _MODEL_SHARD_CPU_INTRA_GROUP


def get_model_shard_cpu_inter_group() -> dist.ProcessGroup | None:
    """Get the CPU (Gloo) inter-node process group for model sharding.

    Returns:
        The inter-node CPU process group for FSDP hybrid sharding.
    """
    return _MODEL_SHARD_CPU_INTER_GROUP


def get_model_shard_intra_group() -> dist.ProcessGroup | None:
    """Get the GPU (NCCL) intra-node process group for model sharding.

    Parameters, gradients, and optimizer states are sharded within this group.

    Returns:
        The intra-node GPU process group for FSDP sharding.
    """
    return _MODEL_SHARD_INTRA_GROUP


def get_model_shard_inter_group() -> dist.ProcessGroup | None:
    """Get the GPU (NCCL) inter-node process group for model sharding.

    Sharded models are replicated across this group for data parallelism
    between nodes in HYBRID_SHARD mode.

    Returns:
        The inter-node GPU process group for FSDP hybrid sharding.
    """
    return _MODEL_SHARD_INTER_GROUP


def init_sequence_parallel(sequence_parallel_size: int):
    """Initialize sequence parallel process groups.

    Creates two types of process groups:
    - Sequence parallel groups: consecutive ranks of size ``sequence_parallel_size``
      that work together on the same data sample (sequence split).
    - Data parallel groups: ranks at the same SP index across different SP groups
      (holding different data samples but same sequence position).

    Both NCCL (GPU) and Gloo (CPU) groups are created for SP.

    The grouping layout for world_size=8, sequence_parallel_size=4::

        SP groups (NCCL+Gloo): [0,1,2,3], [4,5,6,7]
        DP groups (implicit):   [0,4], [1,5], [2,6], [3,7]

    Args:
        sequence_parallel_size: Number of GPUs per sequence parallel group.
            Must evenly divide world_size. world_size / sequence_parallel_size
            gives the number of data parallel replicas.
    """
    global _DATA_PARALLEL_GROUP
    global _SEQUENCE_PARALLEL_GROUP
    global _SEQUENCE_PARALLEL_CPU_GROUP
    global _SEQUENCE_PARALLEL_GLOBAL_RANKS
    assert dist.is_initialized()
    world_size = dist.get_world_size()
    rank = dist.get_rank()
    data_parallel_size = world_size // sequence_parallel_size
    for i in range(data_parallel_size):
        start_rank = i * sequence_parallel_size
        end_rank = (i + 1) * sequence_parallel_size
        ranks = range(start_rank, end_rank)
        group = dist.new_group(ranks)
        cpu_group = dist.new_group(ranks, backend="gloo")
        if rank in ranks:
            _SEQUENCE_PARALLEL_GROUP = group
            _SEQUENCE_PARALLEL_CPU_GROUP = cpu_group
            _SEQUENCE_PARALLEL_GLOBAL_RANKS = list(ranks)


def init_model_shard_group(
    *,
    sharding_strategy: ShardingStrategy,
    device_mesh: DeviceMesh | None = None,
):
    """Initialize process groups for FSDP / hybrid model sharding.

    Creates a 2D device mesh for hybrid sharding:
    - Intra ("intra") dimension: GPUs within a node where parameters are sharded.
    - Inter ("inter") dimension: Nodes across which sharded models are replicated
      (data parallelism across nodes in hybrid mode).

    Both NCCL (GPU) and Gloo (CPU) meshes are created.

    The sharding strategy determines the group sizes:
    - NO_SHARD: no sharding (intra size = 1, inter size = world_size)
    - FULL_SHARD / SHARD_GRAD_OP: shard across all GPUs (intra size = world_size)
    - HYBRID_SHARD / _HYBRID_SHARD_ZERO2: shard within node (intra size = num GPUs
      per node), replicate across nodes (inter size = num nodes)

    Args:
        sharding_strategy: FSDP sharding strategy determining mesh dimensions.
        device_mesh: Optional pre-defined DeviceMesh. If provided, its shape[1]
            is used as the intra-node shard size. If None, determined from
            sharding_strategy.
    """
    global _MODEL_SHARD_INTER_GROUP
    global _MODEL_SHARD_INTRA_GROUP
    global _MODEL_SHARD_CPU_INTER_GROUP
    global _MODEL_SHARD_CPU_INTRA_GROUP
    assert dist.is_initialized()
    world_size = dist.get_world_size()
    if device_mesh is not None:
        num_shards_per_group = device_mesh.shape[1]
    elif sharding_strategy == ShardingStrategy.NO_SHARD:
        num_shards_per_group = 1
    elif sharding_strategy in [
        ShardingStrategy.HYBRID_SHARD,
        ShardingStrategy._HYBRID_SHARD_ZERO2,
    ]:
        num_shards_per_group = torch.cuda.device_count()
    else:
        num_shards_per_group = world_size
    num_groups = world_size // num_shards_per_group
    device_mesh = (num_groups, num_shards_per_group)

    gpu_mesh_2d = init_device_mesh("cuda", device_mesh, mesh_dim_names=("inter", "intra"))
    cpu_mesh_2d = init_device_mesh("cpu", device_mesh, mesh_dim_names=("inter", "intra"))

    _MODEL_SHARD_INTER_GROUP = gpu_mesh_2d.get_group("inter")
    _MODEL_SHARD_INTRA_GROUP = gpu_mesh_2d.get_group("intra")
    _MODEL_SHARD_CPU_INTER_GROUP = cpu_mesh_2d.get_group("inter")
    _MODEL_SHARD_CPU_INTRA_GROUP = cpu_mesh_2d.get_group("intra")


def get_sequence_parallel_global_ranks() -> list[int]:
    """Get the global ranks of all processes in the current SP group.

    Returns:
        List of global ranks belonging to the same SP group as the caller.
        Returns [current_rank] if SP is not initialized.
    """
    if _SEQUENCE_PARALLEL_GLOBAL_RANKS is None:
        if dist.is_initialized():
            return [dist.get_rank()]
        return [0]
    return _SEQUENCE_PARALLEL_GLOBAL_RANKS


def get_next_sequence_parallel_rank() -> int:
    """Get the global rank of the next process in the SP ring.

    Used for ring-based communication patterns (e.g., P2P send/recv in
    ring attention). The ranks form a ring, so the last rank's "next" is
    the first rank.

    Returns:
        Global rank of the next SP neighbor.
    """
    sp_global_ranks = get_sequence_parallel_global_ranks()
    sp_rank = get_sequence_parallel_rank()
    sp_size = get_sequence_parallel_world_size()
    return sp_global_ranks[(sp_rank + 1) % sp_size]


def get_prev_sequence_parallel_rank() -> int:
    """Get the global rank of the previous process in the SP ring.

    The inverse of :func:`get_next_sequence_parallel_rank`.

    Returns:
        Global rank of the previous SP neighbor.
    """
    sp_global_ranks = get_sequence_parallel_global_ranks()
    sp_rank = get_sequence_parallel_rank()
    sp_size = get_sequence_parallel_world_size()
    return sp_global_ranks[(sp_rank + sp_size - 1) % sp_size]

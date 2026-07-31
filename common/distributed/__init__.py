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

"""Distributed training and parallelism utilities for multi-GPU training.

This package provides a comprehensive set of tools for distributed training
with PyTorch, supporting multiple parallelism strategies:

**Parallelism Strategies:**

1. **Data Parallelism (DDP)**: The simplest form of parallelism where each GPU
   holds a complete copy of the model and processes a different data shard.
   Gradients are synchronized via all-reduce after each backward pass.
   Supported via :func:`basic.convert_to_ddp`.

2. **Sequence Parallelism (SP)**: Splits the sequence dimension across GPUs
   within a node, using all-to-all communication to exchange attention heads
   and key-value pairs. Useful for very long sequences (video frames, long text).
   Supported via :mod:`advanced` and communication ops in :mod:`ops`.

3. **Fully Sharded Data Parallelism (FSDP) / Hybrid Sharding**: Shards model
   parameters, gradients, and optimizer states across GPUs. Supports hybrid
   strategies where sharding is within a node and data parallelism across nodes.
   Process group setup via :func:`advanced.init_model_shard_group`.

**Modules:**
    - basic: Core distributed initialization, rank queries, DDP wrapping.
    - advanced: Sequence parallel and FSDP process group management.
    - ops: Custom autograd functions for sequence-parallel communication
      (all-to-all, gather, slice) with correct gradient propagation.
    - meta_init_utils: Utilities for materializing meta-device tensors,
      particularly non-persistent buffers (e.g., RoPE).

**Environment Variables:**
    Uses standard PyTorch distributed environment variables:
    - RANK: Global rank of the current process.
    - LOCAL_RANK: Local rank within the node.
    - WORLD_SIZE: Total number of processes.
"""

from .basic import (
    barrier_if_distributed,
    convert_to_ddp,
    get_device,
    get_global_rank,
    get_local_rank,
    get_world_size,
    init_torch,
)

__all__ = [
    "barrier_if_distributed",
    "convert_to_ddp",
    "get_device",
    "get_global_rank",
    "get_local_rank",
    "get_world_size",
    "init_torch",
]

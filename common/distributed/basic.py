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

"""Core distributed training utilities for PyTorch DDP initialization and rank queries.

This module provides the fundamental building blocks for distributed training:

- **Rank queries**: Get global rank, local rank, and world size from environment
  variables (set by torchrun/DeepSpeed/accelerate launchers).
- **Device management**: Map local rank to the correct CUDA device.
- **Synchronization**: Distributed barriers that are no-ops in single-GPU mode.
- **Initialization**: PyTorch distributed process group setup with NCCL backend,
  TF32 configuration, and cuDNN benchmark mode.
- **DDP wrapping**: Convenience wrapper for DistributedDataParallel.

All functions gracefully degrade to single-GPU behavior when world_size=1
(i.e., when not launched under a distributed launcher).
"""

import os
from datetime import timedelta
import torch
import torch.distributed as dist
from torch.nn.parallel import DistributedDataParallel


def get_global_rank() -> int:
    """Get the global rank of the current process.

    Global rank is the unique index of the process across all nodes in the
    distributed job. Ranks are numbered 0, 1, ..., world_size-1.

    Returns:
        Global rank as integer. Returns 0 if not running in distributed mode
        (RANK environment variable not set).
    """
    return int(os.environ.get("RANK", "0"))


def get_local_rank() -> int:
    """Get the local rank of the current process within its node.

    Local rank is the index of the GPU on the current node, typically 0-7 for
    an 8-GPU node. It is used to set ``torch.cuda.set_device()``.

    Returns:
        Local rank as integer. Returns 0 if not running in distributed mode
        (LOCAL_RANK environment variable not set).
    """
    return int(os.environ.get("LOCAL_RANK", "0"))


def get_world_size() -> int:
    """Get the total number of processes (GPUs) in the distributed job.

    Returns:
        World size as integer. Returns 1 if not running in distributed mode
        (WORLD_SIZE environment variable not set), indicating single-GPU.
    """
    return int(os.environ.get("WORLD_SIZE", "1"))


def get_device() -> torch.device:
    """Get the torch device for the current process.

    Maps the local rank to a CUDA device (e.g., local_rank=0 -> cuda:0).

    Returns:
        A ``torch.device`` object representing the CUDA device for this rank.
    """
    return torch.device("cuda", get_local_rank())


def barrier_if_distributed(*args, **kwargs):
    """Synchronize all processes if running in distributed mode.

    Calls ``torch.distributed.barrier()`` which blocks until all ranks reach
    this point. Has no effect if the distributed process group has not been
    initialized (single-GPU mode).

    Args:
        *args: Additional arguments passed to ``dist.barrier()`` (e.g., group).
        **kwargs: Additional keyword arguments passed to ``dist.barrier()``.
    """
    if dist.is_initialized():
        return dist.barrier(*args, **kwargs)


def init_torch(cudnn_benchmark=True, timeout=timedelta(seconds=600)):
    """Initialize PyTorch for (potentially distributed) training.

    Performs common setup steps:
    1. Enables TF32 for both CUDA matmul and cuDNN (faster on Ampere+ GPUs with
       minimal accuracy loss).
    2. Sets cuDNN benchmark mode for optimized kernel selection (good for fixed
       input sizes).
    3. Sets the current CUDA device to the local rank.
    4. Initializes the NCCL distributed process group if world_size > 1.

    This function is safe to call in single-GPU mode (world_size=1); distributed
    initialization is simply skipped.

    Args:
        cudnn_benchmark: If True, enables cuDNN benchmark mode which auto-tunes
            convolution algorithms. Set to False for variable input sizes.
            Defaults to True.
        timeout: Timeout for NCCL process group operations. Defaults to 600 seconds.
    """
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cudnn.benchmark = cudnn_benchmark
    torch.cuda.set_device(get_local_rank())
    if get_world_size() > 1:
        dist.init_process_group(
            backend="nccl",
            rank=get_global_rank(),
            world_size=get_world_size(),
            timeout=timeout,
        )


def convert_to_ddp(module: torch.nn.Module, **kwargs) -> DistributedDataParallel:
    """Wrap a PyTorch module with DistributedDataParallel.

    Configures DDP with the correct device_ids and output_device based on the
    local rank. Uses NCCL backend for GPU communication.

    Args:
        module: The PyTorch module to wrap.
        **kwargs: Additional keyword arguments passed to ``DistributedDataParallel``
            constructor (e.g., ``find_unused_parameters``, ``gradient_as_bucket_view``).

    Returns:
        The DDP-wrapped module. If not in distributed mode (world_size=1),
        this is still called but DDP will effectively be a pass-through wrapper.

    Note:
        The module should already be on the correct CUDA device before calling
        this function.
    """
    return DistributedDataParallel(
        module=module,
        device_ids=[get_local_rank()],
        output_device=get_local_rank(),
        **kwargs,
    )

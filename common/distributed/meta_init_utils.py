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

"""Utilities for materializing meta-device tensors, particularly non-persistent buffers.

When models are initialized on the PyTorch ``meta`` device (for FSDP/FSDP2 with
``sync_module_states`` or to avoid allocating large GPU memory during model
construction), all parameters and buffers are created as meta tensors (no data).
Parameters are typically materialized via FSDP's sharding mechanism, but
**non-persistent buffers** (buffers excluded from ``state_dict`` via
``register_buffer(..., persistent=False)``) are not saved in checkpoints and
thus not restored by FSDP, which can lead to runtime errors when these buffers
are accessed.

This module provides a materialization hook that specifically handles the case
of RoPE (Rotary Position Embedding) dummy buffers, which are non-persistent and
need to be instantiated on CPU before moving to GPU.
"""

import torch
from rotary_embedding_torch import RotaryEmbedding
from torch import nn

try:
    from torch.distributed.fsdp._common_utils import _is_fsdp_flattened
except ImportError:
    _is_fsdp_flattened = None

__all__ = ["meta_non_persistent_buffer_init_fn"]


def meta_non_persistent_buffer_init_fn(module: nn.Module) -> nn.Module:
    """Materialize non-persistent buffers that were created on the meta device.

    Iterates through all submodules and locates any non-persistent buffers
    (specifically RotaryEmbedding "dummy" buffers) that are still on the meta
    device, then creates real zero-initialized CPU tensors to replace them.

    This is necessary because:
    1. Non-persistent buffers are not stored in ``state_dict``, so they are not
       restored when loading checkpoints.
    2. When initializing a model on meta device (e.g., for FSDP initialization),
       these buffers remain as meta tensors and will cause errors when accessed
       during forward passes.
    3. The rotary_embedding_torch library creates a "dummy" buffer that requires
       materialization.

    After calling this function, all buffers in the module should be real tensors
    (not meta), as verified by the assertion.

    Args:
        module: The nn.Module whose meta non-persistent buffers should be
            materialized. The module is modified in-place and also returned.

    Returns:
        The same module (modified in-place) with all meta buffers materialized
        as CPU zero tensors.

    Raises:
        AssertionError: If any buffer remains on meta device after processing.
    """
    with torch.no_grad():
        for submodule in module.modules():
            if not isinstance(submodule, RotaryEmbedding):
                continue
            for buffer_name, buffer in submodule.named_buffers(recurse=False):
                if buffer.is_meta and "dummy" in buffer_name:
                    materialized_buffer = torch.zeros_like(buffer, device="cpu")
                    setattr(submodule, buffer_name, materialized_buffer)
    assert not any(b.is_meta for n, b in module.named_buffers())
    return module

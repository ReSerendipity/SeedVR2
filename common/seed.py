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

"""Random seed management for reproducible training and inference.

This module provides utilities for setting random seeds across all relevant
random number generators (Python random, NumPy, PyTorch CPU/CUDA) with
optional rank-based offsetting for distributed training.

When training with data parallelism, each rank should use a different seed
to produce different data augmentation and dropout masks, while maintaining
reproducibility across runs. The ``same_across_ranks`` flag allows forcing
identical seeds on all ranks when needed (e.g., for exact reproducibility
in debugging).
"""

import random
from typing import Optional
import numpy as np
import torch

from common.distributed import get_global_rank


def set_seed(seed: Optional[int], same_across_ranks: bool = False):
    """Set random seed for Python, NumPy, and PyTorch generators.

    Initializes all random number generators to ensure reproducible results.
    In distributed mode, the seed is offset by the global rank by default,
    so each process uses a different but deterministic seed. This is important
    for data parallel training where different ranks should see different
    random augmentations and dropout patterns.

    The following RNGs are seeded:
    - Python's built-in ``random`` module
    - NumPy's global random state (``np.random``)
    - PyTorch's CPU generator (``torch.manual_seed``)
    - PyTorch's CUDA generators (set implicitly by ``torch.manual_seed``)

    Note:
        This function does NOT set ``torch.backends.cudnn.deterministic`` or
        ``torch.backends.cudnn.benchmark``. Callers should configure those
        separately if full determinism is required.

    Args:
        seed: Base random seed. If None, no seeding is performed (RNGs retain
            their current state).
        same_across_ranks: If True, all distributed ranks use exactly the same
            seed without rank offset. This is useful for debugging or inference
            where identical behavior across ranks is desired. If False (default),
            the seed is offset by the global rank, giving each rank a unique
            but reproducible sequence. Defaults to False.

    Example:
        >>> set_seed(42)                     # Each rank gets seed 42 + rank
        >>> set_seed(42, same_across_ranks=True)  # All ranks use seed 42
    """
    if seed is not None:
        seed += get_global_rank() if not same_across_ranks else 0
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)

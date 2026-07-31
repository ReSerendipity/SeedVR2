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

"""Uniform trailing sampling timesteps with optional timestep shifting.

**Algorithm Principle:**

Uniform trailing timesteps (also known as "end" spacing or "trailing" spacing)
define the sampling steps such that each step interval [t_i, t_{i+1}] ends at
the boundary, ensuring the final step lands exactly at t=0 (or t=T for forward).
For N steps, the timesteps are:

    t_i = T * (1 - i/N),  for i = 0, 1, ..., N-1

This produces intervals of equal width T/N. The "trailing" property means the
last step reaches exactly t=0, avoiding the common off-by-one error where the
final latent is at a small but nonzero timestep rather than fully denoised.
This is described in the "Common Diffusion Noise Schedules and Sample Steps are
Flawed" paper (https://arxiv.org/abs/2305.08891).

**Timestep Shifting:**

For high-resolution images/videos, more steps should be allocated to the
low-noise region (near t=0) where fine details are generated. Timestep shifting
(used in SD3, https://arxiv.org/abs/2403.03206) applies a nonlinear warping:

    t' = shift * t / (1 + (shift - 1) * t)

When shift > 1, this pushes timesteps toward lower values (allocating more
steps to the detail generation phase). Larger shifts are used for higher
resolutions. Common values: shift=1.0 (no shift, for low resolution), shift=3.0
(for 1024px), shift=5.0+ (for 2K+).

After shifting, timesteps are scaled from [0,1] to [0,T] range and optionally
discretized to integer values for discrete schedules.
"""

import torch

from ...types import SamplingDirection
from ..base import SamplingTimesteps


class UniformTrailingSamplingTimesteps(SamplingTimesteps):
    """Uniform trailing sampling timesteps with optional SD3-style timestep shifting.

    Generates N equally-spaced trailing timesteps from T down to (but not including)
    0 in continuous space, or from T down to 0 in discrete space. Supports timestep
    shifting to bias sampling steps toward the low-noise or high-noise region.

    The timesteps sequence is always in backward direction (from noise to data),
    suitable for generation.

    Args:
        T: Maximum timestep (1.0 for continuous, int for discrete).
        steps: Number of sampling steps (N).
        shift: Timestep shift parameter (SD3 mu). shift=1.0 means no shift (uniform).
            shift>1 shifts timesteps toward t=0 (more steps for detail generation).
            shift<1 shifts toward t=T (more steps for coarse structure).
            Defaults to 1.0.
        device: Torch device for the timesteps tensor. Defaults to "cpu".

    Reference:
        - Trailing spacing: https://arxiv.org/abs/2305.08891
        - Timestep shifting: https://arxiv.org/abs/2403.03206 (eq. 23)
    """

    def __init__(
        self,
        T: int,
        steps: int,
        shift: float = 1.0,
        device: torch.device = "cpu",
    ):
        timesteps = torch.arange(1.0, 0.0, -1.0 / steps, device=device)

        timesteps = shift * timesteps / (1 + (shift - 1) * timesteps)

        if isinstance(T, float):
            timesteps = timesteps * T
        else:
            timesteps = timesteps.mul(T + 1).sub(1).round().int()

        super().__init__(T=T, timesteps=timesteps, direction=SamplingDirection.backward)

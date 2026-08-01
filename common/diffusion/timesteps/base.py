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

"""Abstract base classes for diffusion timesteps and sampling timestep schedules.

**Algorithm Principle:**

While a diffusion schedule defines the continuous relationship between x_0 and x_T
over time t∈[0,T], sampling timesteps define the *discretization* of this continuous
interval into a finite sequence of steps that the ODE solver will actually evaluate
during generation or training.

The choice of timestep spacing significantly affects sample quality and sampling
speed. Common strategies include:
- **Uniform spacing**: Equal spacing in t-space (simple but suboptimal)
- **Trailing spacing**: Timesteps placed such that each step ends at the start
  of the next (avoids off-by-one issues at the endpoint; recommended by the
  "Common Diffusion Noise Schedules are Flawed" paper)
- **Shifted spacing**: Nonlinear warping of timesteps to allocate more steps
  to high-noise or low-noise regions depending on resolution (SD3 shift)

Timesteps can be used for both:
1. **Sampling**: Discrete steps for ODE integration during generation
2. **Training**: Timestep sampling during training (not implemented in this base class)
"""

from abc import ABC

import torch

from ..types import SamplingDirection


class Timesteps(ABC):  # noqa: B024  # 作为不可实例化的共享基类，抽象方法由子类各自定义
    """Abstract base class for diffusion timestep definitions.

    Timesteps encapsulate the maximum timestep T and whether the schedule
    operates in continuous (float T) or discrete (int T) mode. This is the
    base class for both training timestep samplers and sampling timestep
    sequences.

    Args:
        T: Maximum timestep (inclusive). Must be positive.
    """

    def __init__(self, T: int | float):
        assert T > 0
        self._T = T

    @property
    def T(self) -> int | float:
        """Maximum timestep (inclusive) of the schedule.

        Returns:
            int for discrete, float for continuous timesteps.
        """
        return self._T

    def is_continuous(self) -> bool:
        """Check whether timesteps are continuous (float) or discrete (int).

        Returns:
            True if T is float (continuous), False if T is int (discrete).
        """
        return isinstance(self.T, float)


class SamplingTimesteps(Timesteps):
    """Ordered sequence of timesteps for ODE solver discretization during sampling.

    SamplingTimesteps stores a 1-D tensor of timesteps in the order they will
    be traversed during sampling, along with the sampling direction (backward
    for generation, forward for inversion). It provides indexing and lookup
    operations used by samplers to navigate between steps.

    The timesteps tensor should be monotonically decreasing for backward
    sampling (T → 0) and monotonically increasing for forward sampling (0 → T).

    Args:
        T: Maximum timestep (inclusive).
        timesteps: 1-D tensor of timestep values in sampling order.
        direction: Sampling direction (backward for generation, forward for inversion).
    """

    def __init__(
        self,
        T: int | float,
        timesteps: torch.Tensor,
        direction: SamplingDirection,
    ):
        assert timesteps.ndim == 1
        super().__init__(T)
        self.timesteps = timesteps
        self.direction = direction

    def __len__(self) -> int:
        """Return the number of sampling steps in the sequence.

        Returns:
            Number of timesteps (length of the timesteps tensor).
        """
        return len(self.timesteps)

    def __getitem__(self, idx: int | torch.IntTensor) -> torch.Tensor:
        """Get timestep value(s) at the given step index/indices.

        Args:
            idx: Integer index or integer tensor of indices. If int, returns
                a scalar tensor. If tensor, returns a tensor of the same shape.

        Returns:
            Timestep value(s) at the given index/indices.
        """
        return self.timesteps[idx]

    def index(self, t: torch.Tensor) -> torch.Tensor:
        """Find the step index for each timestep value in t.

        Performs exact matching: for each scalar timestep value in ``t``,
        finds its position in the timesteps sequence. Returns -1 for values
        not found.

        This is used to determine the current step position given a timestep
        value, enabling batch support where different batch elements may be at
        different steps.

        Args:
            t: Timestep tensor of arbitrary shape (typically [B]).

        Returns:
            Index tensor of the same shape as t, containing the integer index
            of each timestep in the sequence, or -1 if not found.
        """
        i, j = t.reshape(-1, 1).eq(self.timesteps).nonzero(as_tuple=True)
        idx = torch.full_like(t, fill_value=-1, dtype=torch.int)
        idx.view(-1)[i] = j.int()
        return idx

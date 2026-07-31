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

"""Linear interpolation (rectified flow) schedule.

**Algorithm Principle:**

The linear interpolation schedule (lerp) is the schedule used in Flow Matching
and Rectified Flow models. It defines the simplest possible interpolation
between data and noise:

    x_t = (1 - t/T) * x_0 + (t/T) * x_T

where:
- A(t) = 1 - t/T (signal coefficient)
- B(t) = t/T     (noise coefficient)

Key properties:
1. **Straight trajectories**: For optimal transport couplings between data and
   noise distributions, the ODE trajectories dx/dt = x_T - x_0 are straight
   lines, enabling accurate sampling with very few steps (even 1 step in theory).
2. **Zero-SNR at t=T**: A(T) = 0, meaning x_T is pure noise with no signal
   leakage, which avoids the "noise schedule flaw" identified in the zSNR paper.
3. **Uniform velocity**: v = dx/dt = x_T - x_0 is constant along straight
   trajectories, which is why v_lerp prediction works well.
4. **Used in SD3 and modern flow models**: This is the schedule adopted by
   Stable Diffusion 3 and other recent flow-matching models.

The schedule can operate in both continuous mode (T=1.0, t∈[0,1]) and
discrete mode (T=N, t∈{0,1,...,N}).

**References:**
- Rectified Flow: https://arxiv.org/abs/2209.03003
- Flow Matching for Generative Modeling: https://arxiv.org/abs/2210.02747
- Stable Diffusion 3: https://arxiv.org/abs/2403.03206
"""

from typing import Union
import torch

from .base import Schedule


class LinearInterpolationSchedule(Schedule):
    """Linear interpolation (rectified flow) diffusion schedule.

    Implements x_t = (1 - t/T)*x_0 + (t/T)*x_T. This is the schedule for
    flow matching and rectified flow, providing straight-line ODE trajectories
    between data and noise.

    Args:
        T: Maximum timestep. Use float (e.g., 1.0) for continuous schedules
            (flow matching), int (e.g., 1000) for discrete schedules (DDPM-style).
            Defaults to 1.0 (continuous).
    """

    def __init__(self, T: Union[int, float] = 1.0):
        self._T = T

    @property
    def T(self) -> Union[int, float]:
        """Maximum timestep of the schedule.

        Returns:
            int for discrete, float for continuous schedule.
        """
        return self._T

    def A(self, t: torch.Tensor) -> torch.Tensor:
        """Compute signal coefficient A(t) = 1 - t/T.

        A(t) decreases linearly from 1 (at t=0, pure signal) to 0 (at t=T, pure noise).

        Args:
            t: Timestep tensor.

        Returns:
            Signal coefficient, same shape as t.
        """
        return 1 - (t / self.T)

    def B(self, t: torch.Tensor) -> torch.Tensor:
        """Compute noise coefficient B(t) = t/T.

        B(t) increases linearly from 0 (at t=0, pure signal) to 1 (at t=T, pure noise).

        Args:
            t: Timestep tensor.

        Returns:
            Noise coefficient, same shape as t.
        """
        return t / self.T

    def isnr(self, snr: torch.Tensor) -> torch.Tensor:
        """Compute timestep from SNR for the linear interpolation schedule.

        For the linear schedule:
            SNR = A(t)^2 / B(t)^2 = ((T-t)/t)^2
            sqrt(SNR) = (T-t)/t
            t*sqrt(SNR) = T - t
            t*(sqrt(SNR) + 1) = T
            t = T / (1 + sqrt(SNR))

        Args:
            snr: Signal-to-noise ratio tensor.

        Returns:
            Timestep tensor. For discrete schedules, values are rounded to int.
        """
        t = self.T / (1 + snr**0.5)
        t = t if self.is_continuous() else t.round().int()
        return t

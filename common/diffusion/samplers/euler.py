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


"""Euler method ODE solver for diffusion sampling.

**Algorithm Principle:**

The Euler method is the simplest first-order numerical ODE solver. For an ODE
dx/dt = f(x, t), the Euler step from t to s is:

    x_s = x_t + (s - t) * f(x_t, t)

For diffusion flow matching, instead of directly using the velocity, this
implementation uses the schedule interpolation formula to compute x_s directly
from the model's prediction of x_0, x_T, or velocity. Given the schedule:

    x_t = A(t) * x_0 + B(t) * x_T

and a model prediction at time t, the solver converts the prediction to
(pred_x_0, pred_x_T), then computes x_s by evaluating the schedule at s:

    x_s = A(s) * pred_x_0 + B(s) * pred_x_T

This is equivalent to the Euler step when the prediction is exact (straight-line
flow in rectified flow), and provides a numerically stable way to step between
arbitrary timesteps without requiring explicit velocity computation.

**Properties:**
- First-order accuracy (O(h) local truncation error per step)
- Simple and fast (one model evaluation per step)
- Stable for reasonable step sizes
- Commonly used with 20-100 steps for diffusion models

Reference: https://en.wikipedia.org/wiki/Euler_method
"""

from typing import Callable
import torch
from einops import rearrange
from torch.nn import functional as F

from models.dit_v2 import na

from ..types import PredictionType
from ..utils import expand_dims
from .base import Sampler, SamplerModelArgs


class EulerSampler(Sampler):
    """First-order Euler ODE solver for diffusion sampling.

    Implements the Euler integration method for flow-matching / rectified flow
    ODEs. At each step, the model predicts the velocity/endpoint at the current
    timestep, and the solver uses the schedule interpolation formula to compute
    the next latent state.

    Two stepping modes are provided:
    - :meth:`step`: Steps to the automatically-determined next timestep.
    - :meth:`step_to`: Steps to a specified target timestep s.

    The sampling loop iterates through all timestep pairs (t_i, t_{i+1}),
    performing one model evaluation and one Euler step per transition. If
    ``return_endpoint`` is True, a final model evaluation at the last timestep
    projects directly to x_0 or x_T.
    """

    def sample(
        self,
        x: torch.Tensor,
        f: Callable[[SamplerModelArgs], torch.Tensor],
    ) -> torch.Tensor:
        """Run the full Euler sampling loop from initial x to the endpoint.

        Iterates over consecutive timestep pairs, performing one model
        evaluation and Euler step per transition. If ``return_endpoint`` is
        True, performs a final model evaluation at the last timestep and
        projects to the exact endpoint.

        Args:
            x: Initial tensor (noise for generation, data for inversion).
                Shape [B, C, ...].
            f: Model function taking SamplerModelArgs and returning prediction.

        Returns:
            The final sampled tensor.
        """
        timesteps = self.timesteps.timesteps
        progress = self.get_progress_bar()
        i = 0
        for t, s in zip(timesteps[:-1], timesteps[1:]):
            pred = f(SamplerModelArgs(x, t, i))
            x = self.step_to(pred, x, t, s)
            i += 1
            progress.update()

        if self.return_endpoint:
            t = timesteps[-1]
            pred = f(SamplerModelArgs(x, t, i))
            x = self.get_endpoint(pred, x, t)
            progress.update()
        return x

    def step(
        self,
        pred: torch.Tensor,
        x_t: torch.Tensor,
        t: torch.Tensor,
    ) -> torch.Tensor:
        """Perform one Euler step from timestep t to the next timestep.

        Automatically determines the next timestep using
        :meth:`~Sampler.get_next_timestep` and delegates to :meth:`step_to`.

        Args:
            pred: Model prediction at timestep t.
            x_t: Current latent at timestep t.
            t: Current timestep.

        Returns:
            Latent at the next timestep s.
        """
        return self.step_to(pred, x_t, t, self.get_next_timestep(t))

    def step_to(
        self,
        pred: torch.Tensor,
        x_t: torch.Tensor,
        t: torch.Tensor,
        s: torch.Tensor,
    ) -> torch.Tensor:
        """Perform one Euler step from timestep t to a specified target timestep s.

        Converts the model prediction to (x_0, x_T) using the schedule, then
        evaluates the interpolation at timestep s to compute x_s. Out-of-bound
        timesteps (s < 0 or s > T) are clamped to the respective endpoint.

        Args:
            pred: Model prediction at timestep t, in ``self.prediction_type`` format.
            x_t: Current latent tensor at timestep t. Shape [B, C, ...].
            t: Source timestep, shape [B].
            s: Target timestep, shape [B]. Can be out of bounds (-1 or T+1)
                to clamp to endpoint.

        Returns:
            Latent tensor x_s at timestep s, same shape as x_t.
        """
        t = expand_dims(t, x_t.ndim)
        s = expand_dims(s, x_t.ndim)
        T = self.schedule.T
        pred_x_0, pred_x_T = self.schedule.convert_from_pred(pred, self.prediction_type, x_t, t)
        pred_x_s = self.schedule.forward(pred_x_0, pred_x_T, s.clamp(0, T))
        pred_x_s = pred_x_s.where(s >= 0, pred_x_0)
        pred_x_s = pred_x_s.where(s <= T, pred_x_T)
        return pred_x_s

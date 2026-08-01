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

"""Abstract base class for diffusion ODE/SDE samplers.

A sampler defines how to numerically integrate the probability flow ODE
(or SDE) from noise to data (or vice versa). Given an initial latent x and
a score/velocity model f, the sampler iteratively applies integration steps
along a predefined sequence of timesteps to produce the final sample.

**Mathematical framework:**

For flow matching / rectified flow, the ODE is:

    dx/dt = v(x_t, t) = x_T - x_0   (velocity prediction)

where v is predicted by the neural network. The Euler method discretizes this as:

    x_{s} = x_t + (s - t) * v(x_t, t)

or equivalently, using the schedule interpolation:

    x_s = A(s)/A(t) * x_t + (B(s) - B(t)*A(s)/A(t)) * pred

The base class provides:
- Common interface (``sample`` method) for all samplers
- Timestep navigation (``get_next_timestep``)
- Endpoint projection (``get_endpoint``) for final denoising step
- Progress bar utilities
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

import torch
from tqdm import tqdm

from ..schedules.base import Schedule
from ..timesteps.base import SamplingTimesteps
from ..types import PredictionType, SamplingDirection
from ..utils import assert_schedule_timesteps_compatible


@dataclass
class SamplerModelArgs:
    """Arguments passed to the model function during sampling.

    Attributes:
        x_t: Current noisy latent tensor at timestep t. Shape [B, C, ...].
        t: Current timestep scalar per batch element. Shape [B].
        i: Integer sampling step index (0-based). Useful for scheduling
            time-dependent behaviors such as noise augmentation.
    """

    x_t: torch.Tensor
    t: torch.Tensor
    i: int


class Sampler(ABC):
    """Abstract base class for diffusion ODE solvers (samplers).

    A sampler orchestrates the denoising loop: it iterates over timesteps,
    queries the model for predictions, and applies numerical integration steps
    to move from one timestep to the next.

    Subclasses must implement the :meth:`sample` method with a specific
    numerical integration scheme (Euler, Heun, DPM-Solver, etc.).

    Args:
        schedule: The diffusion schedule defining x_t = A(t)x_0 + B(t)x_T.
        timesteps: The sampling timesteps defining the discretization sequence.
        prediction_type: What quantity the model predicts (x_0, x_T, v_cos, v_lerp).
        return_endpoint: If True, after completing all sampling steps, perform
            one final model evaluation at the last timestep and project to the
            exact endpoint (x_0 or x_T) rather than returning the last ODE step
            result. This is recommended for best quality. Defaults to True.
    """

    def __init__(
        self,
        schedule: Schedule,
        timesteps: SamplingTimesteps,
        prediction_type: PredictionType,
        return_endpoint: bool = True,
    ):
        assert_schedule_timesteps_compatible(
            schedule=schedule,
            timesteps=timesteps,
        )
        self.schedule = schedule
        self.timesteps = timesteps
        self.prediction_type = prediction_type
        self.return_endpoint = return_endpoint

    @abstractmethod
    def sample(
        self,
        x: torch.Tensor,
        f: Callable[[SamplerModelArgs], torch.Tensor],
    ) -> torch.Tensor:
        """Generate a sample by numerically integrating the diffusion ODE.

        Starting from the initial tensor ``x`` (typically pure noise at t=T for
        generation, or clean data at t=0 for inversion), iteratively applies
        the integration rule using model predictions from ``f``.

        Args:
            x: Initial tensor. For standard generation, this is Gaussian noise
                sampled at t=T. For inversion, this is clean data at t=0.
                Shape [B, C, ...].
            f: Model function that takes :class:`SamplerModelArgs` and returns
                a prediction tensor of the same shape as x_t, in the format
                specified by ``self.prediction_type``.

        Returns:
            The final sampled tensor after all integration steps. If
            ``return_endpoint`` is True, this is projected to the exact
            endpoint (x_0 or x_T).
        """

    def get_next_timestep(
        self,
        t: torch.Tensor,
    ) -> torch.Tensor:
        """Look up the next timestep in the sampling sequence for each batch element.

        Supports batches where different elements may be at different current
        timesteps t. If a batch element has already reached the last timestep,
        returns a sentinel out-of-bound value (-1 for backward sampling, T+1
        for forward sampling) that signals no further steps.

        Args:
            t: Current timestep(s), shape [B] (one per batch element).

        Returns:
            Next timestep(s), shape [B]. Returns -1 (backward) or T+1 (forward)
            for elements that have no next step.
        """
        T = self.timesteps.T
        steps = len(self.timesteps)
        curr_idx = self.timesteps.index(t)
        next_idx = curr_idx + 1
        bound = -1 if self.timesteps.direction == SamplingDirection.backward else T + 1

        s = self.timesteps[next_idx.clamp_max(steps - 1)]
        s = s.where(next_idx < steps, bound)
        return s

    def get_endpoint(
        self,
        pred: torch.Tensor,
        x_t: torch.Tensor,
        t: torch.Tensor,
    ) -> torch.Tensor:
        """Project the current state and prediction to the ODE endpoint.

        Converts the model prediction to x_0 and x_T using the schedule,
        then returns the appropriate endpoint based on sampling direction:
        x_0 for backward (generation) direction, x_T for forward (inversion).

        Args:
            pred: Model prediction at timestep t, in ``self.prediction_type`` format.
            x_t: Current noisy latent at timestep t.
            t: Current timestep.

        Returns:
            The endpoint tensor (x_0 for generation, x_T for inversion).
        """
        x_0, x_T = self.schedule.convert_from_pred(pred, self.prediction_type, x_t, t)
        return x_0 if self.timesteps.direction == SamplingDirection.backward else x_T

    def get_progress_bar(self):
        """Create a tqdm progress bar for the sampling loop.

        The number of iterations is ``len(timesteps) - 1`` if ``return_endpoint``
        is False (step transitions only), or ``len(timesteps)`` if True
        (steps + final endpoint evaluation).

        Returns:
            A tqdm progress bar iterable.
        """
        return tqdm(
            iterable=range(len(self.timesteps) - (0 if self.return_endpoint else 1)),
            dynamic_ncols=True,
            desc=self.__class__.__name__,
        )

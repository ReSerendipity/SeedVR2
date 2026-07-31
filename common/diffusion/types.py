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

"""Type definitions for diffusion model prediction targets and sampling directions.

This module defines enumerations that specify:
1. What quantity the neural network is trained to predict (PredictionType)
2. Which direction the ODE solver traverses (SamplingDirection)
"""

from enum import Enum


class PredictionType(str, Enum):
    """Enumeration of diffusion model prediction targets.

    The neural network can be trained to predict different quantities in the
    diffusion process. The choice affects both training objectives and how
    predictions are converted back to x_0 / x_T during sampling.

    The general interpolation is:
        x_t = A(t) * x_0 + B(t) * x_T

    where x_0 is the clean data, x_T is pure noise, and A(t), B(t) are
    schedule-dependent coefficients.

    For the linear interpolation (rectified flow) schedule with T=1:
        A(t) = 1 - t,  B(t) = t
        x_t = (1 - t) * x_0 + t * x_T

    For the cosine schedule (DDPM-style alpha/beta bar):
        A(t) = sqrt(alpha_bar_t),  B(t) = sqrt(1 - alpha_bar_t)
    """

    x_0 = "x_0"
    """Predict the clean data sample x_0 directly.

    The model outputs an estimate of the clean (denoised) data.
    This is sometimes called ``epsilon`` prediction in DDPM literature is wrong;
    x_0 prediction directly predicts the data. Simple conversion but can be
    problematic at high noise levels.
    """

    x_T = "x_T"
    """Predict the noise sample x_T (epsilon in DDPM notation).

    The model outputs an estimate of the Gaussian noise that was added.
    This is the standard DDPM prediction target (https://arxiv.org/abs/2006.11239).
    However, the "Common Diffusion Noise Schedules and Sample Steps are Flawed"
    paper (https://arxiv.org/abs/2305.08891) shows this is problematic at
    zero-terminal SNR (zSNR) where A(T)=0, leading to division by zero when
    converting back to x_0.
    """

    v_cos = "v_cos"
    r"""Predict cosine-schedule velocity v = dx/dt for cosine-based schedules.

    Velocity is defined as v = A(t) * x_T - B(t) * x_0 for cosine schedules,
    which equals the time derivative of x_t under the cosine parameterization.
    This prediction type was proposed in Progressive Distillation
    (https://arxiv.org/abs/2202.00512) and has better numerical properties
    across all noise levels.

    Conversion:
        x_0 = A(t) * x_t - B(t) * v
        x_T = B(t) * x_t + A(t) * v
    """

    v_lerp = "v_lerp"
    """Predict rectified-flow velocity v = x_T - x_0 for linear interpolation schedules.

    For the linear interpolation schedule x_t = (1 - t/T) * x_0 + (t/T) * x_T,
    the velocity is simply v = x_T - x_0 (the straight-line direction from
    data to noise). This is the prediction target used by Rectified Flow
    (https://arxiv.org/abs/2209.03003) and Stable Diffusion 3. It has the
    simplest parameterization and leads to straight ODE trajectories.

    Conversion:
        x_0 = (x_t - B(t) * v) / (A(t) + B(t))
        x_T = (x_t + A(t) * v) / (A(t) + B(t))
    """


class SamplingDirection(str, Enum):
    """Enumeration of ODE sampling traversal directions.

    During sampling, the ODE solver can move either forward or backward in time:
    - Backward: from noise (t=T) to data (t=0) for generation
    - Forward: from data (t=0) to noise (t=T) for inversion (e.g., DDIM inversion)
    """

    backward = "backward"
    """Sample from x_T (noise) backward to x_0 (clean data).

    This is the standard generation direction: start from random noise
    and iteratively denoise to produce a clean sample.
    """

    forward = "forward"
    """Sample from x_0 (clean data) forward to x_T (noise).

    This is the inversion direction: start from a real data sample and
    add noise following the ODE trajectory. Used for DDIM-style inversion
    in image/video editing workflows.
    """

    @staticmethod
    def reverse(direction):
        """Return the opposite sampling direction.

        Args:
            direction: A SamplingDirection value.

        Returns:
            The reversed direction (backward <-> forward).

        Raises:
            NotImplementedError: If the direction is not recognized.
        """
        if direction == SamplingDirection.backward:
            return SamplingDirection.forward
        if direction == SamplingDirection.forward:
            return SamplingDirection.backward
        raise NotImplementedError

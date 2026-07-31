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

"""Diffusion model sampling infrastructure for video restoration.

This package implements a modular diffusion sampling framework based on
flow matching / rectified flow principles. It decouples three key components:

**Algorithm Overview:**

The diffusion process is defined by an interpolation schedule that maps between
the data distribution (x_0, clean video) and the noise distribution (x_T, Gaussian noise):

    x_t = A(t) * x_0 + B(t) * x_T,  t ∈ [0, T]

where A(t) and B(t) are schedule-dependent interpolation coefficients.
For the linear interpolation (rectified flow) schedule used in this project:

    x_t = (1 - t/T) * x_0 + (t/T) * x_T

Sampling proceeds by solving an ODE from t=T (noise) backward to t=0 (clean data)
using a numerical solver (Euler method), where the model predicts either x_0, x_T,
or velocity v depending on the prediction type.

**Components:**

- **Schedules** (``schedules/``): Define the forward/noising process x_t = A(t)x_0 + B(t)x_T.
  Currently implements linear interpolation (rectified flow).
- **Samplers** (``samplers/``): ODE solvers that traverse from noise to data.
  Currently implements the Euler method (first-order solver).
- **Timesteps** (``timesteps/``): Discretization schemes that select which t values
  to evaluate during sampling. Supports uniform trailing spacing with timestep shifting.
- **Types** (``types.py``): Enumerations for prediction types and sampling directions.
- **Utils** (``utils.py``): Classifier-free guidance, dimension expansion, schedule validation.
- **Config** (``config.py``): Factory functions for creating components from OmegaConf configs.

**Key References:**
- Rectified Flow: https://arxiv.org/abs/2209.03003
- Flow Matching: https://arxiv.org/abs/2210.02747
- Classifier-Free Guidance: https://arxiv.org/abs/2207.12598
- Common Diffusion Noise Schedules and Sample Steps are Flawed: https://arxiv.org/abs/2305.08891
- SD3 Timestep Shifting: https://arxiv.org/abs/2403.03206
"""

from .config import (
    create_sampler_from_config,
    create_sampling_timesteps_from_config,
    create_schedule_from_config,
)
from .samplers.base import Sampler
from .samplers.euler import EulerSampler
from .schedules.base import Schedule
from .schedules.lerp import LinearInterpolationSchedule
from .timesteps.base import SamplingTimesteps, Timesteps
from .timesteps.sampling.trailing import UniformTrailingSamplingTimesteps
from .types import PredictionType, SamplingDirection
from .utils import classifier_free_guidance, classifier_free_guidance_dispatcher, expand_dims

__all__ = [
    # Configs
    "create_sampler_from_config",
    "create_sampling_timesteps_from_config",
    "create_schedule_from_config",
    # Schedules
    "Schedule",
    "LinearInterpolationSchedule",
    # Samplers
    "Sampler",
    "EulerSampler",
    # Timesteps
    "Timesteps",
    "SamplingTimesteps",
    # Types
    "PredictionType",
    "SamplingDirection",
    "UniformTrailingSamplingTimesteps",
    # Utils
    "classifier_free_guidance",
    "classifier_free_guidance_dispatcher",
    "expand_dims",
]

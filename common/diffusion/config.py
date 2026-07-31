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

"""Factory functions for creating diffusion components from configuration.

This module provides convenient constructors that instantiate schedules,
samplers, and sampling timestep schedules from OmegaConf DictConfig objects,
selecting the appropriate implementation based on a ``type`` field in the config.

Typical config structure::

    diffusion:
      schedule:
        type: lerp
        T: 1.0
      sampler:
        type: euler
        prediction_type: v_lerp
      timesteps:
        type: uniform_trailing
        steps: 50
        shift: 3.0
"""

import torch
from omegaconf import DictConfig

from .samplers.base import Sampler
from .samplers.euler import EulerSampler
from .schedules.base import Schedule
from .schedules.lerp import LinearInterpolationSchedule
from .timesteps.base import SamplingTimesteps
from .timesteps.sampling.trailing import UniformTrailingSamplingTimesteps


def create_schedule_from_config(
    config: DictConfig,
    device: torch.device,
    dtype: torch.dtype = torch.float32,
) -> Schedule:
    """Create a diffusion schedule from configuration.

    Args:
        config: Configuration dict with a ``type`` field selecting the schedule
            implementation. Supported types:
            - ``"lerp"``: Linear interpolation (rectified flow) schedule.
              Optional ``T`` field (default 1.0) sets the maximum timestep.
        device: Torch device for schedule tensors.
        dtype: Torch dtype for schedule computations. Defaults to float32.

    Returns:
        An initialized Schedule instance.

    Raises:
        NotImplementedError: If the schedule ``type`` is not recognized.
    """
    if config.type == "lerp":
        return LinearInterpolationSchedule(T=config.get("T", 1.0))

    raise NotImplementedError


def create_sampler_from_config(
    config: DictConfig,
    schedule: Schedule,
    timesteps: SamplingTimesteps,
) -> Sampler:
    """Create a diffusion sampler (ODE solver) from configuration.

    Args:
        config: Configuration dict with a ``type`` field selecting the sampler
            implementation. Supported types:
            - ``"euler"``: First-order Euler ODE solver. Requires
              ``prediction_type`` field specifying what the model predicts.
        schedule: The diffusion schedule instance defining the interpolation.
        timesteps: The sampling timesteps defining discretization steps.

    Returns:
        An initialized Sampler instance.

    Raises:
        NotImplementedError: If the sampler ``type`` is not recognized.
    """
    if config.type == "euler":
        return EulerSampler(
            schedule=schedule,
            timesteps=timesteps,
            prediction_type=config.prediction_type,
        )
    raise NotImplementedError


def create_sampling_timesteps_from_config(
    config: DictConfig,
    schedule: Schedule,
    device: torch.device,
    dtype: torch.dtype = torch.float32,
) -> SamplingTimesteps:
    """Create sampling timesteps (discretization) from configuration.

    Args:
        config: Configuration dict with a ``type`` field selecting the timestep
            schedule. Supported types:
            - ``"uniform_trailing"``: Uniform trailing spacing (per
              https://arxiv.org/abs/2305.08891). Requires ``steps`` (number of
              sampling steps), optional ``shift`` (timestep shift parameter for
              flow matching, default 1.0; see SD3 paper eq.23).
        schedule: The diffusion schedule, used to determine T and continuity.
        device: Torch device for timestep tensors.
        dtype: Torch dtype for timestep computations. Defaults to float32.

    Returns:
        An initialized SamplingTimesteps instance.

    Raises:
        NotImplementedError: If the timestep ``type`` is not recognized.
    """
    if config.type == "uniform_trailing":
        return UniformTrailingSamplingTimesteps(
            T=schedule.T,
            steps=config.steps,
            shift=config.get("shift", 1.0),
            device=device,
        )
    raise NotImplementedError

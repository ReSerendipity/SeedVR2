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

"""Diffusion utility functions: classifier-free guidance, tensor reshaping, validation.

This module provides helper functions used across the diffusion sampling pipeline:
- Classifier-free guidance (CFG) for conditional generation
- CFG rescaling to prevent over-saturation at high guidance scales
- Tensor dimension expansion for broadcasting
- Schedule-timesteps compatibility validation
"""

from typing import Callable
import torch


def expand_dims(tensor: torch.Tensor, ndim: int):
    """Reshape a tensor to have ``ndim`` dimensions by appending singleton dims.

    New dimensions are added to the right (trailing dimensions). This is used
    for broadcasting 1D timestep tensors (shape [B]) to match the dimensionality
    of data tensors (e.g., [B, C, T, H, W] for video, [B, C, H, W] for images).

    Args:
        tensor: Input tensor, typically of shape [B] (batch of timestep scalars).
        ndim: Target number of dimensions. Must be >= tensor.ndim.

    Returns:
        Reshaped tensor with ``ndim`` dimensions, where new trailing dimensions
        are size 1.

    Example:
        >>> t = torch.tensor([0.5, 0.8])  # shape [2]
        >>> expand_dims(t, 4)  # shape [2, 1, 1, 1]
    """
    shape = tensor.shape + (1,) * (ndim - tensor.ndim)
    return tensor.reshape(shape)


def assert_schedule_timesteps_compatible(schedule, timesteps):
    """Validate that a diffusion schedule and sampling timesteps are compatible.

    Checks two compatibility conditions:
    1. They must have the same maximum timestep T.
    2. They must agree on continuity (both continuous with float T, or both
       discrete with int T).

    Args:
        schedule: A Schedule instance.
        timesteps: A Timesteps or SamplingTimesteps instance.

    Raises:
        ValueError: If T values differ or continuity is mismatched.
    """
    if schedule.T != timesteps.T:
        raise ValueError("Schedule and timesteps must have the same T.")
    if schedule.is_continuous() != timesteps.is_continuous():
        raise ValueError("Schedule and timesteps must have the same continuity.")


def classifier_free_guidance(
    pos: torch.Tensor,
    neg: torch.Tensor,
    scale: float,
    rescale: float = 0.0,
):
    """Apply classifier-free guidance (CFG) to model predictions.

    Classifier-free guidance (https://arxiv.org/abs/2207.12598) trades off
    diversity for sample quality by extrapolating between unconditional (neg)
    and conditional (pos) predictions:

        cfg = neg + scale * (pos - neg)

    When scale=1, this returns pos (no guidance). When scale>1, the conditional
    signal is amplified. Typical values are 3-10 for image/video generation.

    Optionally applies CFG rescaling (https://arxiv.org/abs/2305.08891) which
    prevents over-saturation and contrast issues at high guidance scales by
    matching the standard deviation of the guided output to that of the
    conditional prediction:

        factor = std(pos) / std(cfg)
        cfg *= rescale * factor + (1 - rescale)

    When rescale=0, no rescaling is applied. When rescale=1, full rescaling
    matches the conditional output std. Recommended value is ~0.7.

    Args:
        pos: Conditional model prediction (e.g., with text prompt). Shape [B, ...].
        neg: Unconditional model prediction (e.g., empty/unconditional prompt).
            Same shape as pos.
        scale: Guidance scale. 1.0 = no guidance, higher = stronger alignment
            with conditioning.
        rescale: CFG rescale factor in [0, 1]. 0.0 disables rescaling (default),
            1.0 fully rescales to match conditional std.

    Returns:
        Guided prediction tensor with the same shape as pos/neg.
    """
    cfg = neg + scale * (pos - neg)

    if rescale != 0.0:
        pos_std = pos.std(dim=list(range(1, pos.ndim)), keepdim=True)
        cfg_std = cfg.std(dim=list(range(1, cfg.ndim)), keepdim=True)
        factor = pos_std / cfg_std
        factor = rescale * factor + (1 - rescale)
        cfg *= factor

    return cfg


def classifier_free_guidance_dispatcher(
    pos: Callable,
    neg: Callable,
    scale: float,
    rescale: float = 0.0,
):
    """Conditionally execute model forward passes for classifier-free guidance.

    This is an optimization that avoids running the unconditional model when
    guidance scale is 1.0 (i.e., no guidance is applied). When scale == 1.0,
    only the conditional (pos) model is evaluated. Otherwise, both conditional
    and unconditional models are evaluated and CFG is applied.

    Args:
        pos: Zero-argument callable that returns the conditional prediction
            (typically a lambda wrapping model.forward with conditioning).
        neg: Zero-argument callable that returns the unconditional prediction
            (typically a lambda wrapping model.forward without conditioning
            or with null conditioning).
        scale: Guidance scale. If 1.0, only pos is called.
        rescale: CFG rescale factor, passed to classifier_free_guidance.
            Defaults to 0.0.

    Returns:
        The (optionally guided) prediction tensor.
    """
    if scale == 1.0:
        return pos()

    return classifier_free_guidance(
        pos=pos(),
        neg=neg(),
        scale=scale,
        rescale=rescale,
    )

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

"""PyTorch tensor operation utilities with Half-precision safety fallbacks.

This module provides safe wrappers around common PyTorch operations that may
fail when using half-precision (FP16/BF16) tensors, particularly for padding
modes (replicate, reflect, circular) and interpolation modes (bilinear, bicubic,
trilinear) that lack native half-precision CUDA kernel implementations.

The wrappers automatically detect RuntimeErrors caused by unsupported dtypes,
temporarily upcast to float32 for the operation, and restore the original dtype.
"""

import torch.nn.functional as F


def safe_pad_operation(x, padding, mode="constant", value=0.0):
    """Safely pad a tensor with automatic dtype fallback for unsupported modes.

    Wraps ``torch.nn.functional.pad`` with a fallback mechanism. When using
    padding modes that don't support half-precision (replicate, reflect, circular),
    the function catches the RuntimeError, performs the operation in float32,
    and converts back to the original dtype.

    Args:
        x: Input tensor to pad.
        padding: Padding size tuple following F.pad convention. For 4D tensors,
            this is (pad_left, pad_right, pad_top, pad_bottom) for 2D padding,
            extended for higher dimensions.
        mode: Padding mode. One of 'constant', 'reflect', 'replicate', 'circular'.
            Defaults to 'constant'.
        value: Fill value for 'constant' padding mode. Defaults to 0.0.

    Returns:
        Padded tensor with the same dtype as input.

    Note:
        The modes 'replicate', 'reflect', and 'circular' are known to raise
        "not implemented for 'Half'" errors on CUDA with FP16 tensors.
        This function transparently handles that case.
    """
    problematic_modes = ["replicate", "reflect", "circular"]

    if mode in problematic_modes:
        try:
            return F.pad(x, padding, mode=mode, value=value)
        except RuntimeError as e:
            if "not implemented for 'Half'" in str(e):
                original_dtype = x.dtype
                return F.pad(x.float(), padding, mode=mode, value=value).to(original_dtype)
            else:
                raise e
    else:
        return F.pad(x, padding, mode=mode, value=value)


def safe_interpolate_operation(
    x, size=None, scale_factor=None, mode="nearest", align_corners=None, recompute_scale_factor=None
):
    """Safely interpolate/upsample a tensor with automatic dtype fallback.

    Wraps ``torch.nn.functional.interpolate`` with a fallback mechanism. When
    using interpolation modes that don't fully support half-precision (bilinear,
    bicubic, trilinear), the function catches RuntimeErrors and falls back to
    float32 computation.

    Args:
        x: Input tensor to interpolate. Expected shape (N, C, ...) or (N, C, D, H, W).
        size: Target output spatial size. Mutually exclusive with scale_factor.
        scale_factor: Multiplier for spatial size. Mutually exclusive with size.
        mode: Interpolation mode. One of 'nearest', 'linear', 'bilinear', 'bicubic',
            'trilinear', 'area', 'nearest-exact'. Defaults to 'nearest'.
        align_corners: If True, the corner pixels of input and output are aligned,
            preserving values at corners. Only effective for modes that support it
            (linear, bilinear, bicubic, trilinear). Defaults to None.
        recompute_scale_factor: Recompute the scale_factor for use in interpolation
            calculation. Defaults to None.

    Returns:
        Interpolated tensor with the same dtype as input.

    Note:
        The modes 'bilinear', 'bicubic', and 'trilinear' may raise errors related
        to half-precision index computation ("not implemented for 'Half'" or
        "compute_indices_weights"). This function handles those transparently.
    """
    problematic_modes = ["bilinear", "bicubic", "trilinear"]

    if mode in problematic_modes:
        try:
            return F.interpolate(
                x,
                size=size,
                scale_factor=scale_factor,
                mode=mode,
                align_corners=align_corners,
                recompute_scale_factor=recompute_scale_factor,
            )
        except RuntimeError as e:
            if "not implemented for 'Half'" in str(e) or "compute_indices_weights" in str(e):
                original_dtype = x.dtype
                return F.interpolate(
                    x.float(),
                    size=size,
                    scale_factor=scale_factor,
                    mode=mode,
                    align_corners=align_corners,
                    recompute_scale_factor=recompute_scale_factor,
                ).to(original_dtype)
            else:
                raise e
    else:
        return F.interpolate(
            x,
            size=size,
            scale_factor=scale_factor,
            mode=mode,
            align_corners=align_corners,
            recompute_scale_factor=recompute_scale_factor,
        )

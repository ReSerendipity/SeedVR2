"""
Tile Blending Utilities for SeedVR2

Provides weighted overlap blending for tiled processing to eliminate seam artifacts
between adjacent tiles. Also provides temporal tiling support for long video processing.

Inspired by RVRT's temporal+spatial tiling with overlap blending and DiffVSR's
sliding window approach.

Key Features:
- Linear and cosine weight blending for spatial tile overlaps
- Temporal segment processing with configurable overlap for long videos
- Seamless integration with existing VAE tiled encode/decode
"""

import logging
import math
from typing import Callable

import torch

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Spatial tile blending
# ---------------------------------------------------------------------------

def create_linear_weight_map(
    tile_size: int,
    overlap: int,
    num_dims: int = 2,
    device: torch.device | str = "cpu",
    dtype: torch.dtype = torch.float32,
) -> torch.Tensor:
    """Create a linear weight map for blending overlapping spatial tiles.

    Produces a weight tensor where the overlap region has smoothly varying weights
    (0 to 1) to enable seamless blending between adjacent tiles.

    Args:
        tile_size: Size of each spatial tile
        overlap: Number of overlapping pixels between adjacent tiles
        num_dims: Number of spatial dimensions (2 for H,W)
        device: Target device
        dtype: Tensor dtype

    Returns:
        Weight map tensor of shape (tile_size,) * num_dims

    Example:
        # For a 512x512 tile with 64px overlap:
        weights = create_linear_weight_map(512, 64)
        # weights is 512x512 with smooth transition in overlap regions
    """
    if overlap <= 0:
        return torch.ones([tile_size] * num_dims, device=device, dtype=dtype)

    # Create 1D linear ramp
    ramp = torch.ones(tile_size, device=device, dtype=dtype)
    for i in range(overlap):
        weight = (i + 1) / (overlap + 1)
        ramp[i] = weight
        ramp[tile_size - 1 - i] = weight

    # Expand to N dimensions
    weight_map = ramp
    for _ in range(num_dims - 1):
        weight_map = weight_map.unsqueeze(-1) * ramp.view(
            [-1] + [1] * _
        )
        # Reshape for broadcasting
        weight_map = weight_map.expand([tile_size] * num_dims).clone()

    return weight_map


def create_cosine_weight_map(
    tile_size: int,
    overlap: int,
    num_dims: int = 2,
    device: torch.device | str = "cpu",
    dtype: torch.dtype = torch.float32,
) -> torch.Tensor:
    """Create a cosine weight map for smoother blending in overlap regions.

    Uses a cosine curve for the transition, which provides smoother blending
    than linear interpolation.

    Args:
        tile_size: Size of each spatial tile
        overlap: Number of overlapping pixels between adjacent tiles
        num_dims: Number of spatial dimensions (2 for H,W)
        device: Target device
        dtype: Tensor dtype

    Returns:
        Weight map tensor of shape (tile_size,) * num_dims
    """
    if overlap <= 0:
        return torch.ones([tile_size] * num_dims, device=device, dtype=dtype)

    # Cosine ramp
    ramp = torch.ones(tile_size, device=device, dtype=dtype)
    for i in range(overlap):
        # Cosine curve from 0 to 1
        angle = math.pi * (i + 1) / (2 * (overlap + 1))
        weight = math.sin(angle) ** 2
        ramp[i] = weight
        ramp[tile_size - 1 - i] = weight

    # Build N-dimensional weight map
    weight_map = ramp
    for dim in range(1, num_dims):
        weight_map = weight_map.unsqueeze(-1) * ramp.unsqueeze(0)

    return weight_map


def blend_tiled_output(
    tiles: list[torch.Tensor],
    tile_positions: list[tuple[int, int]],
    output_shape: tuple[int, int],
    tile_size: int,
    overlap: int,
    weight_type: str = "cosine",
    device: torch.device | str = "cpu",
    dtype: torch.dtype = torch.float32,
) -> torch.Tensor:
    """Blend multiple spatial tiles into a single output using weighted overlap.

    Args:
        tiles: List of tile tensors, each of shape (C, tile_h, tile_w) or (tile_h, tile_w)
        tile_positions: List of (y, x) top-left positions for each tile
        output_shape: (height, width) of the final output
        tile_size: Size of each tile
        overlap: Overlap between adjacent tiles
        weight_type: 'linear' or 'cosine'
        device: Target device
        dtype: Weight tensor dtype

    Returns:
        Blended output tensor of shape matching tiles but with output_shape spatial dims
    """
    if not tiles:
        raise ValueError("No tiles provided")

    # Determine output shape from tiles if not specified
    if output_shape is None:
        c = tiles[0].shape[0] if tiles[0].ndim >= 3 else 1
        h = max(pos[0] + tile_size for pos in tile_positions)
        w = max(pos[1] + tile_size for pos in tile_positions)
        output_shape = (h, w)

    h, w = output_shape
    c = tiles[0].shape[0] if tiles[0].ndim >= 3 else 1

    # Create weight map
    if weight_type == "cosine":
        weight_map = create_cosine_weight_map(tile_size, overlap, num_dims=2,
                                               device=device, dtype=dtype)
    else:
        weight_map = create_linear_weight_map(tile_size, overlap, num_dims=2,
                                               device=device, dtype=dtype)

    # Accumulators for weighted blending
    output = torch.zeros(c, h, w, device=device, dtype=dtype)
    weight_sum = torch.zeros(1, h, w, device=device, dtype=dtype)

    for tile, (y, x) in zip(tiles, tile_positions):
        # Ensure tile has channel dimension
        if tile.ndim == 2:
            tile = tile.unsqueeze(0)

        # Clamp tile to output bounds
        tile_h = min(tile_size, h - y)
        tile_w = min(tile_size, w - x)
        tile_c = tile.shape[0]

        # Extract tile region and weight
        tile_crop = tile[:, :tile_h, :tile_w]
        w_crop = weight_map[:tile_h, :tile_w].unsqueeze(0)

        # Weighted accumulation
        output[:, y:y+tile_h, x:x+tile_w] += tile_crop * w_crop
        weight_sum[:, y:y+tile_h, x:x+tile_w] += w_crop

    # Normalize
    weight_sum = weight_sum.clamp(min=1e-8)
    output = output / weight_sum

    return output


# ---------------------------------------------------------------------------
# Temporal tiling for long videos
# ---------------------------------------------------------------------------

def compute_temporal_segments(
    total_frames: int,
    segment_size: int,
    overlap: int = 0,
) -> list[tuple[int, int]]:
    """Compute temporal segment boundaries with overlap for long video processing.

    This function divides a long video into overlapping segments that can be
    processed independently, similar to DiffVSR's sliding window approach.

    Args:
        total_frames: Total number of frames in the video
        segment_size: Number of frames per segment
        overlap: Number of overlapping frames between adjacent segments

    Returns:
        List of (start_frame, end_frame) tuples for each segment

    Example:
        # 100 frames, 32-frame segments, 8-frame overlap:
        segments = compute_temporal_segments(100, 32, 8)
        # [(0, 32), (24, 56), (48, 80), (72, 100)]
    """
    if total_frames <= segment_size:
        return [(0, total_frames)]

    segments = []
    stride = segment_size - overlap
    if stride <= 0:
        stride = segment_size // 2
        logger.warning(f"Overlap ({overlap}) >= segment_size ({segment_size}), "
                       f"using stride={stride}")

    start = 0
    while start < total_frames:
        end = min(start + segment_size, total_frames)
        segments.append((start, end))

        if end >= total_frames:
            break
        start += stride

    logger.info(f"Temporal segments: {len(segments)} segments for {total_frames} frames "
                f"(segment_size={segment_size}, overlap={overlap}, stride={stride})")
    return segments


def blend_temporal_segments(
    segment_results: list[torch.Tensor],
    segments: list[tuple[int, int]],
    total_frames: int,
    overlap: int,
    weight_type: str = "cosine",
) -> torch.Tensor:
    """Blend overlapping temporal segments using weighted overlap.

    When processing long videos in segments with overlap, this function
    blends the overlapping regions to ensure temporal smoothness.

    Args:
        segment_results: List of processed segment tensors, each (T, C, H, W) or (C, T, H, W)
        segments: List of (start, end) frame indices from compute_temporal_segments
        total_frames: Total output frames
        overlap: Number of overlapping frames between segments
        weight_type: 'linear' or 'cosine' for overlap weighting

    Returns:
        Blended output tensor with total_frames in temporal dimension
    """
    if not segment_results:
        raise ValueError("No segment results provided")

    # Determine tensor layout
    sample = segment_results[0]
    if sample.ndim == 4:
        # Could be (T, C, H, W) or (C, T, H, W) - assume T,C,H,W for video
        if sample.shape[0] <= sample.shape[1]:
            # (T, C, H, W) layout
            c_dim = 1
        else:
            # (C, T, H, W) layout
            c_dim = 0
    else:
        raise ValueError(f"Expected 4D tensor, got {sample.ndim}D")

    if c_dim == 1:
        c = sample.shape[1]
        h, w = sample.shape[2], sample.shape[3]
        dim_order = "TCHW"
    else:
        c = sample.shape[0]
        h, w = sample.shape[2], sample.shape[3]
        dim_order = "CTHW"

    # Create output accumulator
    output = torch.zeros(total_frames, c, h, w, device=sample.device, dtype=sample.dtype)
    weight_sum = torch.zeros(total_frames, 1, 1, 1, device=sample.device, dtype=sample.dtype)

    # Create temporal weight vector for overlap blending
    for seg_idx, (result, (start, end)) in enumerate(zip(segment_results, segments)):
        seg_len = end - start

        if c_dim == 1:
            seg_data = result  # (T, C, H, W)
        else:
            seg_data = result.permute(1, 0, 2, 3)  # -> (T, C, H, W)

        # Create temporal weight for this segment
        weight = torch.ones(seg_len, device=output.device, dtype=output.dtype)

        if overlap > 0 and seg_len >= overlap:
            # Blend overlap regions
            if weight_type == "cosine":
                for i in range(min(overlap, seg_len)):
                    angle = math.pi * (i + 1) / (2 * (overlap + 1))
                    w_val = math.sin(angle) ** 2
                    weight[i] = w_val
                    if seg_len - 1 - i >= 0:
                        weight[seg_len - 1 - i] = w_val
            else:
                for i in range(min(overlap, seg_len)):
                    w_val = (i + 1) / (overlap + 1)
                    weight[i] = w_val
                    if seg_len - 1 - i >= 0:
                        weight[seg_len - 1 - i] = w_val

        # Accumulate
        weight = weight.view(-1, 1, 1, 1)
        output[start:end] += seg_data[:end-start] * weight
        weight_sum[start:end] += weight

    # Normalize
    weight_sum = weight_sum.clamp(min=1e-8)
    output = output / weight_sum

    return output

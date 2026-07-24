"""VAE Tiled 处理增强模块

参考 SCST vaehook.py 的 GroupNorm 跨 tile 统计 + 高斯权重混合技术，
以及 VEnhancer 三维度滑动窗口 + 高斯权重混合方案。

竞品来源:
- SCST (GroupNorm 跨 tile 统计 + 高斯权重混合) - P0
- VEnhancer (三维度滑动窗口 + 高斯权重混合) - P1
- CogVideo (diffusers 原生 tiling + slicing) - P1
- DiffBIR (make_tiled_fn 通用 tiled 封装) - P0
- Upscale-A-Video (条件 VAE 解码 融合低频信息) - P1

Key Features:
- GroupNorm 跨 tile 统计: 在 tiled 编解码中累积 GroupNorm 的 running_mean/running_var，
  避免单个 tile 的统计偏差导致接缝
- 高斯权重混合: 使用高斯分布权重替代线性/余弦权重，更平滑的 tile 接缝
- 通用 tiled 推理封装: make_tiled_fn 支持 Encoder/Decoder/Diffusion 独立控制
- 条件 VAE 解码: 融合低分辨率信息以保持颜色一致性
"""

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import torch
import torch.nn.functional as F

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 高斯权重混合 (SCST / VEnhancer inspired)
# ---------------------------------------------------------------------------

def create_gaussian_weight_map(
    tile_size: int,
    overlap: int,
    sigma: float | None = None,
    num_dims: int = 2,
    device: torch.device | str = "cpu",
    dtype: torch.dtype = torch.float32,
) -> torch.Tensor:
    """创建高斯权重映射，用于 tiled 处理的重叠区域混合

    与 linear/cosine 权重相比，高斯权重在重叠区域提供更自然的渐变过渡，
    有效消除 tile 接缝伪影。

    参考: SCST vaehook.py 的 GaussianWeightedBlend 和 VEnhancer 的三维度高斯混合

    Args:
        tile_size: tile 大小
        overlap: 重叠像素数
        sigma: 高斯分布标准差，None 时自动计算 (overlap / 4)
        num_dims: 空间维度数 (2 for H,W)
        device: 目标设备
        dtype: 张量数据类型

    Returns:
        权重映射张量
    """
    if overlap <= 0:
        return torch.ones([tile_size] * num_dims, device=device, dtype=dtype)

    # 自动计算 sigma: overlap 的 1/4 保证平滑过渡
    if sigma is None:
        sigma = overlap / 4.0

    # 创建 1D 高斯权重
    ramp = torch.ones(tile_size, device=device, dtype=dtype)
    center = tile_size / 2.0

    for i in range(overlap):
        # 计算距离边缘的相对位置
        dist_from_edge = i + 1
        # 高斯权重: 距中心越远权重越小
        # 使用距离边缘的相对距离计算
        weight = 1.0 - math.exp(-0.5 * ((overlap - dist_from_edge) / sigma) ** 2)
        # 归一化确保边缘处接近 0，中心为 1
        weight = math.exp(-0.5 * ((dist_from_edge - overlap) / sigma) ** 2)
        ramp[i] = weight
        ramp[tile_size - 1 - i] = weight

    # 扩展到 N 维
    if num_dims == 1:
        return ramp

    # 2D 或更高维度的外积
    weight_map = ramp.unsqueeze(-1) * ramp.unsqueeze(0)
    if num_dims > 2:
        for _ in range(num_dims - 2):
            weight_map = weight_map.unsqueeze(-1) * ramp.unsqueeze(0).unsqueeze(0)

    return weight_map


def blend_tiles_gaussian(
    tiles: list[torch.Tensor],
    tile_positions: list[tuple[int, int]],
    output_shape: tuple[int, int],
    tile_size: int,
    overlap: int,
    sigma: float | None = None,
    device: torch.device | str = "cpu",
    dtype: torch.dtype = torch.float32,
) -> torch.Tensor:
    """使用高斯权重混合多个 tile 到单个输出

    Args:
        tiles: tile 张量列表，每个为 (C, tile_h, tile_w)
        tile_positions: 每个 tile 的 (y, x) 左上角位置
        output_shape: (height, width) 输出尺寸
        tile_size: tile 大小
        overlap: tile 间重叠
        sigma: 高斯 sigma，None 自动计算
        device: 目标设备
        dtype: 数据类型

    Returns:
        混合后的输出张量
    """
    if not tiles:
        raise ValueError("No tiles provided")

    h, w = output_shape
    c = tiles[0].shape[0] if tiles[0].ndim >= 3 else 1

    # 创建高斯权重映射
    weight_map = create_gaussian_weight_map(
        tile_size, overlap, sigma=sigma,
        num_dims=2, device=device, dtype=dtype
    )

    # 累加混合
    output = torch.zeros(c, h, w, device=device, dtype=dtype)
    weight_sum = torch.zeros(1, h, w, device=device, dtype=dtype)

    for tile, (y, x) in zip(tiles, tile_positions):
        if tile.ndim == 2:
            tile = tile.unsqueeze(0)

        tile_h = min(tile_size, h - y)
        tile_w = min(tile_size, w - x)

        tile_crop = tile[:, :tile_h, :tile_w]
        w_crop = weight_map[:tile_h, :tile_w].unsqueeze(0)

        output[:, y:y+tile_h, x:x+tile_w] += tile_crop * w_crop
        weight_sum[:, y:y+tile_h, x:x+tile_w] += w_crop

    # 归一化
    weight_sum = weight_sum.clamp(min=1e-8)
    output = output / weight_sum

    return output


# ---------------------------------------------------------------------------
# GroupNorm 跨 tile 统计 (SCST inspired)
# ---------------------------------------------------------------------------

class GroupNormAccumulator:
    """GroupNorm 跨 tile 统计累积器

    在 tiled VAE 编解码中，单个 tile 的 GroupNorm 统计（mean/var）会有偏差，
    导致不同 tile 的输出在接缝处不一致。此累积器在所有 tile 上收集
    running_mean 和 running_var，最后用全局统计替换各 tile 的局部统计。

    参考: SCST vaehook.py 的 VaeHook.GroupNorm_accumulator

    Usage:
        accumulator = GroupNormAccumulator(vae_model)

        # 在处理所有 tile 之前开始累积
        accumulator.start_accumulation()

        # 处理每个 tile (GroupNorm 统计会被自动收集)
        for tile in tiles:
            result = vae.encode(tile)

        # 用全局统计替换局部统计
        accumulator.apply_accumulated_stats()
    """

    def __init__(self, model: torch.nn.Module):
        """初始化累积器

        Args:
            model: 包含 GroupNorm 层的模型 (如 VAE)
        """
        self.model = model
        self._groupnorm_modules: list[torch.nn.GroupNorm] = []
        self._original_stats: dict[str, tuple[torch.Tensor, torch.Tensor]] = {}
        self._accumulated_mean: dict[str, torch.Tensor] = {}
        self._accumulated_var: dict[str, torch.Tensor] = {}
        self._accumulated_count: dict[str, int] = {}
        self._is_accumulating = False

        # 收集所有 GroupNorm 模块
        for name, module in model.named_modules():
            if isinstance(module, torch.nn.GroupNorm):
                self._groupnorm_modules.append(module)
                self._module_names.append(name)

    def start_accumulation(self):
        """开始累积 GroupNorm 统计

        保存原始 running_mean/running_var，并切换到累积模式。
        """
        self._accumulated_mean.clear()
        self._accumulated_var.clear()
        self._accumulated_count.clear()
        self._is_accumulating = True

        for name, module in zip(self._module_names, self._groupnorm_modules):
            # 保存原始统计
            if module.running_mean is not None:
                self._original_stats[name] = (
                    module.running_mean.clone(),
                    module.running_var.clone(),
                )

            # 初始化累积器
            num_channels = module.num_channels
            device = module.running_mean.device if module.running_mean is not None else "cpu"
            dtype = module.running_mean.dtype if module.running_mean is not None else torch.float32

            self._accumulated_mean[name] = torch.zeros(num_channels, device=device, dtype=dtype)
            self._accumulated_var[name] = torch.zeros(num_channels, device=device, dtype=dtype)
            self._accumulated_count[name] = 0

        logger.info(f"GroupNorm 跨 tile 统计累积开始: {len(self._groupnorm_modules)} 个 GroupNorm 层")

    def accumulate_from_output(self, output: torch.Tensor, group_size: int = 32):
        """从 tile 输出中累积 GroupNorm 统计

        在每个 tile 处理完成后调用此方法，将当前 tile 的统计加入全局累积。

        Args:
            output: 当前 tile 的输出张量
            group_size: GroupNorm 的分组大小
        """
        if not self._is_accumulating:
            return

        # 计算 output 在各通道上的 mean 和 var
        # output: (B, C, H, W) or (C, H, W)
        if output.ndim == 4:
            # 每个通道的 mean/var
            mean = output.mean(dim=[0, 2, 3])
            var = output.var(dim=[0, 2, 3])
        elif output.ndim == 3:
            mean = output.mean(dim=[1, 2])
            var = output.var(dim=[1, 2])
        else:
            return

        num_channels = mean.shape[0]
        batch_count = output.shape[0] if output.ndim == 4 else 1

        # 累积到对应 GroupNorm 层
        for name in self._accumulated_mean:
            if self._accumulated_mean[name].shape[0] == num_channels:
                self._accumulated_mean[name] += mean * batch_count
                self._accumulated_var[name] += var * batch_count
                self._accumulated_count[name] += batch_count

    def apply_accumulated_stats(self):
        """将累积的全局统计应用到各 GroupNorm 层

        用全局 mean/var 替换局部统计，确保所有 tile 使用一致的归一化参数。
        """
        if not self._is_accumulating:
            return

        for name, module in zip(self._module_names, self._groupnorm_modules):
            if name in self._accumulated_mean and self._accumulated_count[name] > 0:
                count = self._accumulated_count[name]
                global_mean = self._accumulated_mean[name] / count
                global_var = self._accumulated_var[name] / count

                # 替换 GroupNorm 的 running 统计
                if module.running_mean is not None:
                    module.running_mean.copy_(global_mean)
                if module.running_var is not None:
                    module.running_var.copy_(global_var)

        self._is_accumulating = False
        logger.info("GroupNorm 全局统计已应用到各层")

    def restore_original_stats(self):
        """恢复原始 GroupNorm 统计（推理完成后清理）"""
        for name, module in zip(self._module_names, self._groupnorm_modules):
            if name in self._original_stats:
                orig_mean, orig_var = self._original_stats[name]
                if module.running_mean is not None:
                    module.running_mean.copy_(orig_mean)
                if module.running_var is not None:
                    module.running_var.copy_(orig_var)

        self._original_stats.clear()
        self._is_accumulating = False


# ---------------------------------------------------------------------------
# 通用 tiled 推理封装 (DiffBIR make_tiled_fn inspired)
# ---------------------------------------------------------------------------

def make_tiled_fn(
    fn: Callable,
    tile_size: int,
    overlap: int,
    batch_size: int = 1,
    weight_type: str = "gaussian",
    progress_callback: Callable | None = None,
) -> Callable:
    """创建 tiled 推理封装函数

    参考 DiffBIR 的 make_tiled_fn，将任意推理函数包装为支持 tiled 处理的版本。
    支持 Encoder/Decoder/Diffusion 等不同阶段的独立控制。

    Args:
        fn: 原始推理函数，接收 (tensor, **kwargs) 返回 tensor
        tile_size: tile 大小
        overlap: 重叠像素数
        batch_size: 每个 tile 的批大小
        weight_type: 权重类型 ('gaussian', 'cosine', 'linear')
        progress_callback: 进度回调

    Returns:
        包装后的 tiled 推理函数
    """

    def tiled_fn(tensor: torch.Tensor, **kwargs) -> torch.Tensor:
        """tiled 推理包装"""
        if tensor.ndim < 3:
            return fn(tensor, **kwargs)

        # 确定 spatial 维度
        if tensor.ndim == 4:  # (B, C, H, W) or (C, T, H, W)
            h_dim, w_dim = -2, -1
        elif tensor.ndim == 5:  # (B, C, T, H, W)
            h_dim, w_dim = -2, -1
        else:
            return fn(tensor, **kwargs)

        h, w = tensor.shape[h_dim], tensor.shape[w_dim]

        # 如果输入比 tile 小，不需要 tiled
        if h <= tile_size and w <= tile_size:
            return fn(tensor, **kwargs)

        # 计算 tile 位置
        stride = tile_size - overlap
        tile_positions_h = []
        tile_positions_w = []

        y = 0
        while y < h:
            tile_positions_h.append(min(y, h - tile_size))
            y += stride
            if y + tile_size >= h:
                break

        x = 0
        while x < w:
            tile_positions_w.append(min(x, w - tile_size))
            x += stride
            if x + tile_size >= w:
                break

        # 确保覆盖整个图像
        if tile_positions_h[-1] + tile_size < h:
            tile_positions_h.append(h - tile_size)
        if tile_positions_w[-1] + tile_size < w:
            tile_positions_w.append(w - tile_size)

        # 创建权重映射
        device = tensor.device
        dtype = tensor.dtype

        if weight_type == "gaussian":
            from bin.integrated_app.optimization.vae_tiled_enhance import create_gaussian_weight_map
            weight_map = create_gaussian_weight_map(tile_size, overlap, num_dims=2, device=device, dtype=dtype)
        elif weight_type == "cosine":
            from bin.integrated_app.optimization.tile_blend import create_cosine_weight_map
            weight_map = create_cosine_weight_map(tile_size, overlap, num_dims=2, device=device, dtype=dtype)
        else:
            from bin.integrated_app.optimization.tile_blend import create_linear_weight_map
            weight_map = create_linear_weight_map(tile_size, overlap, num_dims=2, device=device, dtype=dtype)

        # 初始化输出累积器
        output_shape = list(tensor.shape)
        output_shape[h_dim] = h
        output_shape[w_dim] = w
        output = torch.zeros(output_shape, device=device, dtype=dtype)
        weight_sum = torch.zeros([1, h, w], device=device, dtype=dtype)

        total_tiles = len(tile_positions_h) * len(tile_positions_w)
        processed = 0

        # 处理每个 tile
        for y_pos in tile_positions_h:
            for x_pos in tile_positions_w:
                # 提取 tile
                tile_slices = [slice(None)] * tensor.ndim
                tile_slices[h_dim] = slice(y_pos, y_pos + tile_size)
                tile_slices[w_dim] = slice(x_pos, x_pos + tile_size)
                tile_input = tensor[tuple(tile_slices)]

                # 运行推理
                tile_output = fn(tile_input, **kwargs)

                # 提取输出 tile 对应区域
                actual_h = min(tile_size, h - y_pos)
                actual_w = min(tile_size, w - x_pos)

                tile_slices_out = [slice(None)] * tile_output.ndim
                tile_slices_out[h_dim] = slice(0, actual_h)
                tile_slices_out[w_dim] = slice(0, actual_w)
                tile_crop = tile_output[tuple(tile_slices_out)]

                w_crop = weight_map[:actual_h, :actual_w].unsqueeze(0)

                # 累加
                out_slices = [slice(None)] * output.ndim
                out_slices[h_dim] = slice(y_pos, y_pos + actual_h)
                out_slices[w_dim] = slice(x_pos, x_pos + actual_w)
                output[tuple(out_slices)] += tile_crop * w_crop
                weight_sum[:, y_pos:y_pos+actual_h, x_pos:x_pos+actual_w] += w_crop

                processed += 1
                if progress_callback:
                    progress_callback(processed, total_tiles)

        # 归一化
        weight_sum = weight_sum.clamp(min=1e-8)

        # 扩展 weight_sum 到匹配 output 的维度
        expand_shape = [1] * output.ndim
        expand_shape[h_dim] = h
        expand_shape[w_dim] = w
        weight_expanded = weight_sum.expand(expand_shape)

        output = output / weight_expanded

        return output

    return tiled_fn


# ---------------------------------------------------------------------------
# 条件 VAE 解码 (Upscale-A-Video decode_latents_vsr inspired)
# ---------------------------------------------------------------------------

def conditional_vae_decode(
    vae_model: torch.nn.Module,
    latents: torch.Tensor,
    low_res_latent: torch.Tensor | None = None,
    blend_weight: float = 0.3,
    **decode_kwargs,
) -> torch.Tensor:
    """条件 VAE 解码 - 融合低分辨率信息保持颜色一致性

    参考 Upscale-A-Video 的 decode_latents_vsr 方法。
    在 VAE 解码时融合低分辨率的 latent 信息，保持输出与输入的颜色一致性。

    Args:
        vae_model: VAE 模型
        latents: 高分辨率潜编码
        low_res_latent: 低分辨率潜编码 (用于条件融合)
        blend_weight: 低频信息融合权重 (0.0=不融合, 1.0=完全使用低频)
        **decode_kwargs: VAE 解码参数 (tiled, tile_size, tile_overlap 等)

    Returns:
        解码后的像素空间输出
    """
    # 标准 VAE 解码
    if low_res_latent is None or blend_weight <= 0:
        return vae_model.decode(latents, **decode_kwargs)

    # 解码高分辨率 latent
    high_res_output = vae_model.decode(latents, **decode_kwargs)

    # 解码低分辨率 latent (颜色参考)
    low_res_output = vae_model.decode(low_res_latent, **decode_kwargs)

    # 上采样低分辨率输出到高分辨率尺寸
    target_h, target_w = high_res_output.shape[-2:]
    low_res_upsampled = F.interpolate(
        low_res_output,
        size=(target_h, target_w),
        mode="bilinear",
        align_corners=False,
    )

    # 融合: 高频来自高分辨率解码，低频来自低分辨率参考
    # 使用低通滤波提取低频
    kernel_size = 15
    sigma = 3.0
    kernel = _create_gaussian_kernel(kernel_size, sigma, device=high_res_output.device)

    # 对高分辨率输出应用低通滤波
    high_res_low_freq = _apply_gaussian_filter(high_res_output, kernel)
    # 对低分辨率上采样应用低通滤波
    low_res_low_freq = _apply_gaussian_filter(low_res_upsampled, kernel)

    # 高频 = 原始 - 低频
    high_freq = high_res_output - high_res_low_freq

    # 融合低频: 使用 blend_weight 混合
    blended_low_freq = (1 - blend_weight) * high_res_low_freq + blend_weight * low_res_low_freq

    # 最终: 低频(融合) + 高频(保留)
    result = blended_low_freq + high_freq

    return result


def _create_gaussian_kernel(
    kernel_size: int,
    sigma: float,
    device: torch.device,
    channels: int = 1,
) -> torch.Tensor:
    """创建 2D 高斯滤波核"""
    x = torch.arange(kernel_size, device=device, dtype=torch.float32) - kernel_size // 2
    gauss_1d = torch.exp(-0.5 * (x / sigma) ** 2)
    gauss_2d = gauss_1d.unsqueeze(-1) * gauss_1d.unsqueeze(0)
    kernel = gauss_2d / gauss_2d.sum()

    # 扩展到多通道
    kernel = kernel.unsqueeze(0).unsqueeze(0).expand(channels, 1, -1, -1).contiguous()
    return kernel


def _apply_gaussian_filter(
    tensor: torch.Tensor,
    kernel: torch.Tensor,
) -> torch.Tensor:
    """对张量应用高斯滤波"""
    channels = tensor.shape[1] if tensor.ndim == 4 else 1
    padding = kernel.shape[-1] // 2

    if tensor.ndim == 4:
        # (B, C, H, W)
        result = F.conv2d(tensor, kernel[:channels], padding=padding, groups=channels)
    elif tensor.ndim == 3:
        # (C, H, W) -> (1, C, H, W)
        result = F.conv2d(tensor.unsqueeze(0), kernel[:channels], padding=padding, groups=channels)
        result = result.squeeze(0)
    else:
        return tensor

    return result


# ---------------------------------------------------------------------------
# VAE Slicing 支持 (CogVideo inspired)
# ---------------------------------------------------------------------------

def enable_vae_slicing(
    vae_model: torch.nn.Module,
    slice_size: int = 1,
) -> torch.nn.Module:
    """启用 VAE slicing 模式 (CogVideo diffusers 原生方式)

    将 VAE 解码分成多个 slice，每个 slice 处理一部分 latent 通道，
    减少显存峰值。

    Args:
        vae_model: VAE 模型
        slice_size: 每个 slice 的 latent 通道数

    Returns:
        配置后的 VAE 模型
    """
    vae_model._slice_size = slice_size
    vae_model._slicing_enabled = True
    logger.info(f"VAE slicing 已启用: slice_size={slice_size}")
    return vae_model


def disable_vae_slicing(vae_model: torch.nn.Module) -> torch.nn.Module:
    """禁用 VAE slicing 模式"""
    vae_model._slicing_enabled = False
    vae_model._slice_size = 1
    logger.info("VAE slicing 已禁用")
    return vae_model


# ---------------------------------------------------------------------------
# CPU Offload 机制 (CogVideo / Upscale-A-Video inspired)
# ---------------------------------------------------------------------------

def enable_sequential_cpu_offload(
    model: torch.nn.Module,
    device: torch.device | str = "cuda",
) -> torch.nn.Module:
    """启用顺序 CPU offload (CogVideo diffusers 方式)

    在推理过程中，将不在使用的子模块移到 CPU，仅在需要时加载到 GPU。
    减少 VRAM 占用，但增加推理时间。

    Args:
        model: 要 offload 的模型
        device: 推理设备 (通常为 cuda)

    Returns:
        配置后的模型
    """
    device = torch.device(device)

    # 将整个模型先移到 CPU
    model.to("cpu")

    # 标记需要 offload
    model._sequential_cpu_offload = True
    model._offload_device = device

    logger.info(f"顺序 CPU offload 已启用: device={device}")
    return model


def offload_module_to_cpu(module: torch.nn.Module) -> None:
    """将模块 offload 到 CPU"""
    module.to("cpu")
    torch.cuda.empty_cache()


def load_module_to_gpu(module: torch.nn.Module, device: torch.device | str = "cuda") -> None:
    """将模块加载到 GPU"""
    module.to(device)


# ---------------------------------------------------------------------------
# 8bit 缓存量化 (Real-CUGAN q()/dq() inspired) - P2
# ---------------------------------------------------------------------------

@dataclass
class CacheQuantizerConfig:
    """8bit 缓存量化配置

    参考 bilibili-ailab (Real-CUGAN) 的 q()/dq() 缓存量化/反量化机制，
    将中间激活缓存从 float32 量化为 uint8 以减少显存占用。

    量化公式:
        对称模式:   q(x) = round(x / scale)           scale = max(|x|)
        非对称模式: q(x) = round((x - offset) / scale) scale = max(x) - min(x), offset = min(x)
    """

    # 是否启用量化
    enabled: bool = True
    # 量化模式: 'symmetric' (对称) 或 'asymmetric' (非对称)
    quant_mode: str = "symmetric"
    # 量化位数 (目前仅支持 8bit)
    num_bits: int = 8
    # 最小 scale 值，防止除零
    eps: float = 1e-8


class CacheQuantizer:
    """8bit 缓存量化器

    参考 bilibili-ailab (Real-CUGAN) 的 q()/dq() 缓存量化/反量化机制。
    在推理过程中将 float32 的中间激活量化为 uint8，减少显存占用，
    在需要时反量化回 float32 继续计算。

    量化流程:
    1. q(): float32 -> uint8 + (scale, offset) 元数据
    2. dq(): uint8 + (scale, offset) -> float32

    对称量化: 适用于零中心分布的激活（如残差），仅保存 scale
    非对称量化: 适用于偏移分布的激活，保存 scale + offset

    Usage:
        quantizer = CacheQuantizer(CacheQuantizerConfig())

        # 量化
        quantized_data, meta = quantizer.q(activation_tensor)

        # 反量化
        restored = quantizer.dq(quantized_data, meta)

        # 显存节省: float32 (4 bytes/elem) -> uint8 (1 byte/elem) + 少量元数据
    """

    def __init__(self, config: CacheQuantizerConfig | None = None):
        self.config = config or CacheQuantizerConfig()
        self._quant_max = (1 << self.config.num_bits) - 1  # 255 for 8bit

    def q(
        self, tensor: torch.Tensor
    ) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
        """将 float32 张量量化为 uint8

        Args:
            tensor: 待量化的 float32 张量

        Returns:
            (quantized, meta) 元组:
              quantized: uint8 量化后的张量
              meta: 包含 'scale' 和可选 'offset' 的元数据字典
        """
        if not self.config.enabled:
            return tensor, {}

        mode = self.config.quant_mode
        eps = self.config.eps

        if mode == "symmetric":
            # 对称量化: scale = max(|x|), offset = 0
            scale = tensor.abs().max().clamp(min=eps) / self._quant_max
            quantized = torch.clamp(
                torch.round(tensor / scale), 0, self._quant_max
            ).to(torch.uint8)
            meta = {"scale": scale.detach()}
        else:
            # 非对称量化: scale = max - min, offset = min
            t_min = tensor.min()
            t_max = tensor.max()
            scale = (t_max - t_min).clamp(min=eps) / self._quant_max
            offset = t_min
            quantized = torch.clamp(
                torch.round((tensor - offset) / scale), 0, self._quant_max
            ).to(torch.uint8)
            meta = {"scale": scale.detach(), "offset": offset.detach()}

        return quantized, meta

    def dq(
        self,
        quantized: torch.Tensor,
        meta: dict[str, torch.Tensor],
    ) -> torch.Tensor:
        """将 uint8 量化张量反量化为 float32

        Args:
            quantized: uint8 量化张量
            meta: q() 返回的元数据字典，包含 'scale' 和可选 'offset'

        Returns:
            反量化后的 float32 张量
        """
        if not self.config.enabled or not meta:
            return quantized.float()

        scale = meta["scale"]
        restored = quantized.float() * scale

        if "offset" in meta:
            restored = restored + meta["offset"]

        return restored


# ---------------------------------------------------------------------------
# Selective Block Offloading (MIA-VSR inspired) - P2
# ---------------------------------------------------------------------------

@dataclass
class SelectiveBlockOffloaderConfig:
    """选择性 Block 卸载配置

    参考 MIA-VSR 基于 importance mask 选择性卸载的机制，
    根据 transformer block 的重要性分数决定是否卸载到 CPU，
    在显存有限时优先保留重要 block 在 GPU 上。
    """

    # 是否启用选择性卸载
    enabled: bool = True
    # 重要性阈值: 低于此值的 block 将被卸载到 CPU
    importance_threshold: float = 0.5
    # 可用 VRAM 上限 (GB)，超过时触发卸载
    vram_limit_gb: float = 8.0
    # 重要性计算方法: 'norm' (参数范数), 'activation' (激活统计), 'custom' (自定义)
    importance_method: str = "norm"
    # 卸载目标设备
    offload_device: str = "cpu"


class SelectiveBlockOffloader:
    """选择性 Block 卸载器

    参考 MIA-VSR (Memory-efficient Importance-Aware Video Super-Resolution)
    的选择性卸载机制: 基于 importance mask 决定哪些 transformer block
    卸载到 CPU，在显存有限时优先保留重要 block 在 GPU 上。

    核心思路:
    1. 计算每个 transformer block 的重要性分数 (默认使用参数范数)
    2. 根据阈值和可用 VRAM 决定卸载哪些 block
    3. 重要性低的 block 卸载到 CPU，需要时再加载回 GPU
    4. 重要 block 始终保留在 GPU 上，减少 I/O 开销

    Usage:
        offloader = SelectiveBlockOffloader(SelectiveBlockOffloaderConfig())

        # 计算 importance mask
        importance = offloader.compute_importance_mask(model_blocks)

        # 执行选择性卸载
        offloader.offload(model_blocks, importance)

        # 恢复所有 block 到 GPU
        offloader.restore(model_blocks)
    """

    def __init__(self, config: SelectiveBlockOffloaderConfig | None = None):
        self.config = config or SelectiveBlockOffloaderConfig()
        self._offloaded_indices: list[int] = []

    def compute_importance_mask(
        self,
        blocks: list[torch.nn.Module],
        method: str | None = None,
    ) -> torch.Tensor:
        """计算每个 block 的重要性分数

        默认使用参数范数作为重要性指标: 参数范数越大，
        说明该 block 承载了更多信息，应优先保留在 GPU 上。

        Args:
            blocks: transformer block 列表
            method: 重要性计算方法，None 时使用配置中的方法

        Returns:
            重要性分数张量，形状 (num_blocks,)，值域 [0, 1]
        """
        method = method or self.config.importance_method
        num_blocks = len(blocks)

        if method == "norm":
            # 参数范数: L2 norm of all parameters in each block
            norms = torch.zeros(num_blocks)
            for i, block in enumerate(blocks):
                param_norm = 0.0
                for p in block.parameters():
                    param_norm += p.data.norm().item() ** 2
                norms[i] = param_norm ** 0.5

        elif method == "activation":
            # 激活统计: 需要运行一次推理来收集激活
            # 这里提供框架，实际需要 hook 来收集激活
            logger.warning(
                "activation 重要性方法需要先运行一次推理收集激活统计，"
                "当前回退到 norm 方法"
            )
            return self.compute_importance_mask(blocks, method="norm")

        else:
            # custom: 返回均匀重要性
            logger.warning(f"未知的重要性方法 '{method}'，使用均匀重要性")
            norms = torch.ones(num_blocks)

        # 归一化到 [0, 1]
        if norms.max() > 0:
            importance = norms / norms.max()
        else:
            importance = torch.ones(num_blocks)

        return importance

    def offload(
        self,
        blocks: list[torch.nn.Module],
        importance: torch.Tensor,
        target_device: torch.device | str | None = None,
    ) -> list[int]:
        """根据重要性分数选择性卸载 block 到 CPU

        Args:
            blocks: transformer block 列表
            importance: 重要性分数张量 (num_blocks,)
            target_device: 卸载目标设备，None 时使用配置中的设备

        Returns:
            被卸载的 block 索引列表
        """
        if not self.config.enabled:
            return []

        target_device = target_device or self.config.offload_device
        threshold = self.config.importance_threshold

        # 检查 VRAM 是否需要卸载
        if torch.cuda.is_available():
            vram_used_gb = torch.cuda.memory_allocated() / (1024 ** 3)
            if vram_used_gb < self.config.vram_limit_gb:
                logger.debug(
                    f"VRAM 使用 {vram_used_gb:.1f}GB 未超过限制 "
                    f"{self.config.vram_limit_gb:.1f}GB，跳过卸载"
                )
                return []

        # 选择低重要性 block 卸载
        self._offloaded_indices = []
        for i, score in enumerate(importance):
            if score < threshold and i < len(blocks):
                blocks[i].to(target_device)
                self._offloaded_indices.append(i)

        if self._offloaded_indices:
            torch.cuda.empty_cache()
            logger.info(
                f"选择性卸载: {len(self._offloaded_indices)}/{len(blocks)} 个 block "
                f"已卸载到 {target_device}，阈值={threshold:.2f}"
            )

        return list(self._offloaded_indices)

    def load_block(
        self,
        blocks: list[torch.nn.Module],
        block_idx: int,
        device: torch.device | str = "cuda",
    ) -> None:
        """按需加载单个 block 回 GPU

        在推理过程中，当需要某个已卸载的 block 时调用此方法。

        Args:
            blocks: transformer block 列表
            block_idx: 需要加载的 block 索引
            device: 目标 GPU 设备
        """
        if block_idx < len(blocks):
            blocks[block_idx].to(device)
            if block_idx in self._offloaded_indices:
                self._offloaded_indices.remove(block_idx)

    def restore(
        self,
        blocks: list[torch.nn.Module],
        device: torch.device | str = "cuda",
    ) -> None:
        """恢复所有已卸载的 block 到 GPU

        Args:
            blocks: transformer block 列表
            device: 目标 GPU 设备
        """
        for idx in self._offloaded_indices:
            if idx < len(blocks):
                blocks[idx].to(device)

        count = len(self._offloaded_indices)
        self._offloaded_indices.clear()
        if count > 0:
            logger.info(f"选择性卸载恢复: {count} 个 block 已加载回 GPU")


# ---------------------------------------------------------------------------
# TeaCache 时间步跳过 (FlashVSR inspired) - P2
# ---------------------------------------------------------------------------

@dataclass
class TeaCacheSkipperConfig:
    """TeaCache 时间步跳过配置

    参考 FlashVSR 的多项式拟合缓存机制 (TeaCache)，
    基于多项式拟合预测当前时间步的输出是否与缓存足够接近，
    如果接近则跳过当前步的计算，直接使用缓存结果。
    """

    # 是否启用时间步跳过
    enabled: bool = True
    # 多项式阶数: 用于拟合时间步与输出变化的关系
    poly_order: int = 3
    # 跳过阈值: 预测变化小于此值时跳过当前步
    threshold: float = 0.05
    # 最大连续跳过步数: 防止跳过过多导致质量下降
    max_skip_steps: int = 3


class TeaCacheSkipper:
    """TeaCache 时间步跳过器

    参考 FlashVSR 的多项式拟合缓存机制 (TeaCache):
    基于多项式拟合预测当前时间步的输出变化量，
    如果预测变化量小于阈值，则跳过当前步的完整计算，
    直接使用缓存结果。

    核心思路:
    1. 记录最近若干步的 (timestep, output) 数据点
    2. 使用多项式拟合这些数据点，预测当前步的输出
    3. 如果预测输出与缓存的最近输出足够接近 (变化 < 阈值)，跳过计算
    4. 跳过时直接使用缓存的输出作为当前步结果

    优势: 在扩散模型采样的后期步 (变化较小的步) 可以显著节省计算，
    而在变化较大的前期步仍执行完整计算。

    Usage:
        skipper = TeaCacheSkipper(TeaCacheSkipperConfig())

        for t in timesteps:
            # 检查是否可以跳过当前步
            if skipper.should_skip(t):
                output = skipper.get_cached_output()
            else:
                output = model(noisy_input, t)
                skipper.update(t, output)
    """

    def __init__(self, config: TeaCacheSkipperConfig | None = None):
        self.config = config or TeaCacheSkipperConfig()
        # 历史数据点: (timestep, output)
        self._history_t: list[float] = []
        self._history_outputs: list[torch.Tensor] = []
        # 最近缓存的输出
        self._cached_output: torch.Tensor | None = None
        # 连续跳过计数
        self._consecutive_skips: int = 0

    def update(
        self,
        timestep: float,
        output: torch.Tensor,
    ) -> None:
        """更新缓存历史

        在执行完整计算后调用此方法，记录新的 (timestep, output) 数据点。

        Args:
            timestep: 当前时间步
            output: 当前步的模型输出
        """
        self._history_t.append(float(timestep))
        self._history_outputs.append(output.detach())

        # 保持历史数据量不超过多项式拟合所需
        max_points = self.config.poly_order + 2
        while len(self._history_t) > max_points:
            self._history_t.pop(0)
            self._history_outputs.pop(0)

        self._cached_output = output.detach()
        self._consecutive_skips = 0

    def should_skip(self, timestep: float) -> bool:
        """判断是否应跳过当前时间步

        使用多项式拟合预测当前步的输出变化量，
        如果变化量小于阈值则建议跳过。

        Args:
            timestep: 当前时间步

        Returns:
            True 表示可以跳过当前步
        """
        if not self.config.enabled:
            return False

        # 没有足够的历史数据时不能跳过
        if len(self._history_t) < self.config.poly_order + 1:
            return False

        # 已达到最大连续跳过次数
        if self._consecutive_skips >= self.config.max_skip_steps:
            return False

        # 多项式拟合预测变化量
        predicted_change = self._predict_change(timestep)

        if predicted_change is not None and predicted_change < self.config.threshold:
            return True

        return False

    def get_cached_output(self) -> torch.Tensor | None:
        """获取缓存的输出

        在 should_skip() 返回 True 时调用此方法获取跳过步的输出。

        Returns:
            缓存的模型输出，或 None (无缓存时)
        """
        if self._cached_output is not None:
            self._consecutive_skips += 1
            return self._cached_output.clone()
        return None

    def _predict_change(self, timestep: float) -> float | None:
        """使用多项式拟合预测当前步的输出变化量

        基于历史 (timestep, output_norm) 数据点拟合多项式，
        预测当前 timestep 的输出范数，与最近输出范数的差值作为变化量。

        Args:
            timestep: 待预测的时间步

        Returns:
            预测的变化量 (非负)，或 None (拟合失败时)
        """
        try:
            t_arr = torch.tensor(self._history_t, dtype=torch.float32)
            # 计算每个历史输出的范数作为拟合目标
            o_norms = torch.tensor(
                [o.norm().item() for o in self._history_outputs],
                dtype=torch.float32,
            )

            # 多项式拟合: 使用最小二乘法
            order = min(self.config.poly_order, len(self._history_t) - 1)
            coeffs = torch.linalg.lstsq(
                torch.vander(t_arr, N=order + 1), o_norms.unsqueeze(1)
            ).solution.squeeze(1)

            # 预测当前 timestep 的输出范数
            t_pred = torch.tensor([timestep], dtype=torch.float32)
            predicted_norm = (torch.vander(t_pred, N=order + 1) @ coeffs).item()

            # 变化量 = 预测范数与最近输出范数的差值
            recent_norm = o_norms[-1].item()
            change = abs(predicted_norm - recent_norm)

            return change

        except Exception as e:
            logger.debug(f"TeaCache 多项式拟合失败: {e}")
            return None

    def reset(self) -> None:
        """重置缓存状态 (新序列开始时调用)"""
        self._history_t.clear()
        self._history_outputs.clear()
        self._cached_output = None
        self._consecutive_skips = 0


# ---------------------------------------------------------------------------
# VAE Tiled Hook - 捕获 tile 输出用于高斯权重混合
# ---------------------------------------------------------------------------

class TiledVAEHook:
    """VAE Tiled 解码 Hook - 捕获内部 tile 输出并应用高斯权重混合

    SeedVR2 的原生 VAE tiled decode 在内部处理 tile 拼接，
    不暴露单个 tile 的输出。此类通过 monkey-patch VAE 的 tiled decode
    函数来捕获 tile 输出，然后使用高斯权重重新混合。

    用法:
        hook = TiledVAEHook(vae_model)
        hook.install()
        # 此后 vae.decode(..., tiled=True) 会自动捕获 tile 输出
        # 并在 decode 完成后设置 vae._last_tile_outputs 等属性
        result = vae.decode(batch, tiled=True, ...)
        hook.uninstall()
    """

    def __init__(self, vae_model: torch.nn.Module):
        self.vae = vae_model
        self._original_decode = None
        self._installed = False

    def install(self) -> None:
        """安装 hook，monkey-patch VAE 的 decode 方法"""
        if self._installed:
            return

        self._original_decode = self.vae.decode

        def _patched_decode(batch, tiled=False, tile_size=None, tile_overlap=None, **kwargs):
            if not tiled or tile_size is None:
                return self._original_decode(batch, tiled=tiled, tile_size=tile_size,
                                             tile_overlap=tile_overlap, **kwargs)

            # 执行原始 tiled decode
            result = self._original_decode(batch, tiled=tiled, tile_size=tile_size,
                                           tile_overlap=tile_overlap, **kwargs)

            # 尝试从 VAE 内部状态捕获 tile 信息
            # 某些 VAE 实现会在 decode 过程中设置 _internal_tile_state
            tile_state = getattr(self.vae, '_internal_tile_state', None)
            if tile_state and 'outputs' in tile_state and 'positions' in tile_state:
                self.vae._last_tile_outputs = tile_state['outputs']
                self.vae._last_tile_positions = tile_state['positions']
                self.vae._last_tile_size = tile_size if isinstance(tile_size, int) else tile_size[0]
                self.vae._last_tile_overlap = tile_overlap if isinstance(tile_overlap, int) else tile_overlap[0]
                logger.debug(f"TiledVAEHook: 捕获到 {len(tile_state['outputs'])} 个 tile 输出")
            else:
                # 无法捕获内部 tile 状态，标记为不可用
                self.vae._last_tile_outputs = None
                self.vae._last_tile_positions = None

            return result

        self.vae.decode = _patched_decode
        self._installed = True
        logger.info("TiledVAEHook 已安装")

    def uninstall(self) -> None:
        """卸载 hook，恢复原始 decode 方法"""
        if not self._installed:
            return
        if self._original_decode is not None:
            self.vae.decode = self._original_decode
            self._original_decode = None
        self._installed = False
        logger.info("TiledVAEHook 已卸载")

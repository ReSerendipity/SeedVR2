"""VAE Tiled 处理增强模块

本模块属于 SeedVR2 视频修复项目的 AI 推理优化层，提供 VAE (变分自编码器)
的分块 (tiled) 编解码增强技术，解决高分辨率图像/视频处理时的显存不足问题，
同时通过高级融合策略消除 tile 接缝伪影。

核心技术栈:
- PyTorch: 张量计算与神经网络操作
- 高斯权重混合: 重叠区域平滑过渡消除接缝
- GroupNorm 跨 tile 统计: 避免归一化统计偏差
- CUDA 显存管理: 自动 tile size 推荐与 OOM 回退
- 高斯滤波: 低频信息提取用于颜色一致性

竞品来源:
- SCST (GroupNorm 跨 tile 统计 + 高斯权重混合 + 自动 tile size 推荐 + NaN 检测) - P0
- VEnhancer (三维度滑动窗口 + 高斯权重混合) - P1
- CogVideo (diffusers 原生 tiling + slicing) - P1
- DiffBIR (make_tiled_fn 通用 tiled 封装) - P0
- Upscale-A-Video (条件 VAE 解码 融合低频信息) - P1

Key Features:
- GroupNorm 跨 tile 统计: 在 tiled 编解码中累积 GroupNorm 的 running_mean/running_var，
  避免单个 tile 的统计偏差导致接缝
- 高斯权重混合: 使用高斯分布权重替代线性/余弦权重，更平滑的 tile 接缝
- 自动 tile size 推荐: 根据 GPU 显存自动选择合适的 tile size (SCST 启发)
- NaN 检测与回退: 检测到 NaN 时自动降低 tile size 或禁用 fp16 (SCST 启发)
- 通用 tiled 推理封装: make_tiled_fn 支持 Encoder/Decoder/Diffusion 独立控制
- 条件 VAE 解码: 融合低分辨率信息以保持颜色一致性
- VAE Slicing: 通道级切片减少峰值显存
- 顺序 CPU Offload: 子模块按需加载到 GPU
- 8bit 缓存量化: 中间激活量化减少显存占用
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
# 自动 tile size 推荐 (SCST get_recommend_encoder_tile_size/get_recommend_decoder_tile_size inspired)
# ---------------------------------------------------------------------------

def get_recommend_encoder_tile_size(device: torch.device | str | None = None) -> int:
    """根据 GPU 显存推荐编码器 tile size

    参考 SCST 的 get_recommend_encoder_tile_size 实现:
    - >16GB VRAM: 3072
    - >12GB VRAM: 2048
    - >8GB VRAM: 1536
    - <=8GB VRAM: 960

    Args:
        device: GPU 设备，None 时使用 cuda:0

    Returns:
        推荐的编码器 tile size
    """
    if torch.cuda.is_available():
        if device is None:
            device = torch.device("cuda:0")
        elif isinstance(device, str):
            device = torch.device(device)
        try:
            total_memory_mb = torch.cuda.get_device_properties(device).total_memory // (2**20)
        except Exception:
            total_memory_mb = 8 * 1000  # fallback to 8GB

        if total_memory_mb > 16 * 1000:
            return 3072
        elif total_memory_mb > 12 * 1000:
            return 2048
        elif total_memory_mb > 8 * 1000:
            return 1536
        else:
            return 960
    else:
        return 512


def get_recommend_decoder_tile_size(device: torch.device | str | None = None) -> int:
    """根据 GPU 显存推荐解码器 tile size (输出像素空间)

    注意: VAE decode 的 tile_size 参数是输出像素空间单位，
    VAE 内部自动按 spatial_downsample_factor=8 转换为潜空间:
    64 像素 -> 8 latent, 512 -> 64 latent, 768 -> 96 latent, 1024 -> 128 latent,
    1536 -> 192 latent, 2048 -> 256 latent

    ComfyUI HD 工作流默认 decode_tile_size=768 (对应潜空间 96)

    Args:
        device: GPU 设备，None 时使用 cuda:0

    Returns:
        推荐的解码器 tile size (输出像素空间)
    """
    if torch.cuda.is_available():
        if device is None:
            device = torch.device("cuda:0")
        elif isinstance(device, str):
            device = torch.device(device)
        try:
            total_memory_mb = torch.cuda.get_device_properties(device).total_memory // (2**20)
        except Exception:
            total_memory_mb = 8 * 1000  # fallback to 8GB

        if total_memory_mb > 30 * 1000:
            return 2048
        elif total_memory_mb > 16 * 1000:
            return 1536
        elif total_memory_mb > 12 * 1000:
            return 1024
        elif total_memory_mb > 8 * 1000:
            return 768
        else:
            return 512
    else:
        return 512


def get_optimal_tile_size(
    h: int,
    w: int,
    is_decoder: bool = False,
    device: torch.device | str | None = None,
    max_tile_size: int | None = None,
) -> tuple[int, int]:
    """计算最优 tile size 和 overlap，考虑显存和输入尺寸

    Args:
        h: 输入高度
        w: 输入宽度
        is_decoder: 是否为解码器 (解码器需要更大的 overlap)
        device: GPU 设备
        max_tile_size: 最大 tile size 限制

    Returns:
        (tile_size, overlap) 元组
    """
    if is_decoder:
        recommended = get_recommend_decoder_tile_size(device)
        overlap = min(128, recommended // 6)  # overlap ~= tile_size/6
    else:
        recommended = get_recommend_encoder_tile_size(device)
        overlap = min(128, recommended // 8)  # overlap ~= tile_size/8

    if max_tile_size is not None:
        recommended = min(recommended, max_tile_size)

    # 如果输入比 tile 小，不需要 tiling
    tile_size = min(recommended, h, w)

    # 确保 tile_size 是 16 的倍数 (VAE 下采样要求)
    tile_size = (tile_size // 16) * 16
    tile_size = max(tile_size, 256)  # 最小 256

    # 调整 overlap 不超过 tile_size 的 1/4
    overlap = min(overlap, tile_size // 4)
    overlap = (overlap // 8) * 8  # overlap 是 8 的倍数
    overlap = max(overlap, 32)

    return tile_size, overlap


def detect_nan(tensor: torch.Tensor, stage: str = "unknown") -> bool:
    """检测张量中是否存在 NaN 或 Inf

    参考 SCST 的 devices.test_for_nans，在 VAE tiled 处理中检测异常值。

    Args:
        tensor: 待检测张量
        stage: 阶段名称 (用于日志)

    Returns:
        True 表示存在 NaN/Inf
    """
    if torch.isnan(tensor).any():
        logger.warning(f"[NaN 检测] {stage}: 检测到 NaN 值!")
        return True
    if torch.isinf(tensor).any():
        logger.warning(f"[NaN 检测] {stage}: 检测到 Inf 值!")
        return True
    return False


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
        sigma: 高斯分布标准差，None 时自动计算 (overlap / 3)
        num_dims: 空间维度数 (2 for H,W, 3 for T,H,W)
        device: 目标设备
        dtype: 张量数据类型

    Returns:
        权重映射张量
    """
    if overlap <= 0:
        return torch.ones([tile_size] * num_dims, device=device, dtype=dtype)

    # 自动计算 sigma: overlap 的 1/3 保证平滑过渡
    if sigma is None:
        sigma = overlap / 3.0

    # 创建 1D 高斯权重 ramp
    ramp = torch.ones(tile_size, device=device, dtype=dtype)

    # 从边缘开始，权重从 0 逐渐增加到 1
    for i in range(overlap):
        # 距离边缘的距离 (0=边缘, overlap=内部)
        dist = i + 1
        # 高斯权重: 边缘处接近 0，内部为 1
        # 使用高斯分布: weight = exp(-0.5 * ((overlap - dist) / sigma)^2)
        # 边缘(dist=0): weight = exp(-0.5 * (overlap/sigma)^2) ≈ 0
        # 内部(dist=overlap): weight = exp(0) = 1
        weight = math.exp(-0.5 * ((overlap - dist) / sigma) ** 2)
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
    tile_positions: list[tuple[int, ...]],
    output_shape: tuple[int, ...],
    tile_size: int,
    overlap: int,
    sigma: float | None = None,
    device: torch.device | str = "cpu",
    dtype: torch.dtype = torch.float32,
) -> torch.Tensor:
    """使用高斯权重混合多个 tile 到单个输出

    支持 2D (H,W) 和 3D (T,H,W) 视频处理。

    Args:
        tiles: tile 张量列表，每个为 (C, ...spatial_dims)
        tile_positions: 每个 tile 的位置元组 (y, x) 或 (t, y, x)
        output_shape: 输出空间尺寸 (h, w) 或 (t, h, w)
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

    num_dims = len(output_shape)
    c = tiles[0].shape[0] if tiles[0].ndim > num_dims else 1

    # 创建高斯权重映射
    weight_map = create_gaussian_weight_map(
        tile_size, overlap, sigma=sigma,
        num_dims=num_dims, device=device, dtype=dtype
    )

    # 初始化输出和权重累加器
    full_shape = (c,) + output_shape
    output = torch.zeros(full_shape, device=device, dtype=dtype)
    weight_sum_shape = (1,) + output_shape
    weight_sum = torch.zeros(weight_sum_shape, device=device, dtype=dtype)

    for tile, pos in zip(tiles, tile_positions):
        if tile.ndim == num_dims:
            tile = tile.unsqueeze(0)

        # 计算 tile 在输出中的实际大小
        tile_sizes = []
        for d in range(num_dims):
            tile_sizes.append(min(tile_size, output_shape[d] - pos[d]))

        # 提取 tile 的有效区域
        tile_slices = [slice(None)]  # 通道维度
        w_slices = []
        out_slices = [slice(None)]  # 通道维度

        for d in range(num_dims):
            ts = tile_sizes[d]
            tile_slices.append(slice(0, ts))
            w_slices.append(slice(0, ts))
            out_slices.append(slice(pos[d], pos[d] + ts))

        tile_crop = tile[tuple(tile_slices)]

        # 提取权重的对应区域
        w_crop = weight_map[tuple(w_slices)].unsqueeze(0)

        # 累加
        output[tuple(out_slices)] += tile_crop * w_crop
        weight_sum[tuple(out_slices[1:])] += w_crop.squeeze(0)

    # 归一化
    weight_sum = weight_sum.clamp(min=1e-8)
    output = output / weight_sum

    return output


# ---------------------------------------------------------------------------
# GroupNorm 跨 tile 统计 (SCST inspired)
# ---------------------------------------------------------------------------

def _get_group_norm_stats(
    input_tensor: torch.Tensor,
    num_groups: int = 32,
    eps: float = 1e-6,
) -> tuple[torch.Tensor, torch.Tensor]:
    """计算 GroupNorm 的 mean 和 var

    参考 SCST 的 get_var_mean 实现，正确处理 fp16 下的 inf 问题。

    Args:
        input_tensor: 输入张量 (B, C, *spatial)
        num_groups: GroupNorm 的分组数
        eps: epsilon

    Returns:
        (var, mean) 元组
    """
    b, c = input_tensor.shape[0], input_tensor.shape[1]
    channel_in_group = c // num_groups

    # 处理 fp16 下 var 可能 inf 的问题
    if input_tensor.dtype == torch.float16:
        fp32_tensor = input_tensor.float()
    else:
        fp32_tensor = input_tensor

    input_reshaped = fp32_tensor.contiguous().view(
        1, b * num_groups, channel_in_group, *input_tensor.shape[2:]
    )
    var, mean = torch.var_mean(
        input_reshaped, dim=[0, 2] + list(range(3, input_reshaped.ndim)), unbiased=False
    )

    # clamp 避免 fp16 溢出
    if input_tensor.dtype == torch.float16:
        var = torch.clamp(var, 0, 60000)
        var = var.half()
        mean = mean.half()

    return var, mean


def custom_group_norm(
    input_tensor: torch.Tensor,
    num_groups: int,
    mean: torch.Tensor,
    var: torch.Tensor,
    weight: torch.Tensor | None = None,
    bias: torch.Tensor | None = None,
    eps: float = 1e-6,
) -> torch.Tensor:
    """使用预计算的 mean/var 执行 GroupNorm

    参考 SCST 的 custom_group_norm 实现。

    Args:
        input_tensor: 输入张量 (B, C, *spatial)
        num_groups: 分组数
        mean: 预计算的 mean
        var: 预计算的 var
        weight: 可选的 affine weight
        bias: 可选的 affine bias
        eps: epsilon

    Returns:
        归一化后的张量
    """
    b, c = input_tensor.shape[0], input_tensor.shape[1]
    channel_in_group = c // num_groups

    input_reshaped = input_tensor.contiguous().view(
        1, b * num_groups, channel_in_group, *input_tensor.shape[2:]
    )

    out = F.batch_norm(
        input_reshaped, mean, var,
        weight=None, bias=None,
        training=False, momentum=0, eps=eps
    )

    out = out.view(b, c, *input_tensor.shape[2:])

    # Post affine transform
    if weight is not None:
        shape = [1, -1] + [1] * (input_tensor.ndim - 2)
        out = out * weight.view(*shape)
    if bias is not None:
        shape = [1, -1] + [1] * (input_tensor.ndim - 2)
        out = out + bias.view(*shape)

    return out


class GroupNormAccumulator:
    """GroupNorm 跨 tile 统计累积器

    在 tiled VAE 编解码中，单个 tile 的 GroupNorm 统计（mean/var）会有偏差，
    导致不同 tile 的输出在接缝处不一致。此累积器在所有 tile 上收集
    running_mean 和 running_var，最后用全局统计替换各 tile 的局部统计。

    参考: SCST vaehook.py 的 GroupNormParam 类

    Usage:
        accumulator = GroupNormAccumulator(vae_model)

        # 在处理所有 tile 之前开始累积
        accumulator.start_accumulation()

        # 处理每个 tile (GroupNorm 统计会被自动收集)
        for tile in tiles:
            result = vae.encode(tile)
            accumulator.accumulate_from_output(result, group_norm_modules)

        # 用全局统计替换局部统计
        global_norm_fn = accumulator.get_global_norm_function()

        # 重新应用 GroupNorm
        result = global_norm_fn(result)
    """

    def __init__(self, model: torch.nn.Module, num_groups: int = 32):
        """初始化累积器

        Args:
            model: 包含 GroupNorm 层的模型 (如 VAE)
            num_groups: GroupNorm 的分组数 (通常为 32)
        """
        self.model = model
        self.num_groups = num_groups
        self._groupnorm_modules: list[tuple[str, torch.nn.GroupNorm]] = []
        self._original_stats: dict[str, tuple[torch.Tensor, torch.Tensor]] = {}

        # 累积统计: 每个 GroupNorm 层的 var_list, mean_list, pixel_list
        self._var_lists: dict[str, list[torch.Tensor]] = {}
        self._mean_lists: dict[str, list[torch.Tensor]] = {}
        self._pixel_lists: dict[str, list[int]] = {}
        self._weights: dict[str, torch.Tensor | None] = {}
        self._biases: dict[str, torch.Tensor | None] = {}

        self._is_accumulating = False

        # 收集所有 GroupNorm 模块
        for name, module in model.named_modules():
            if isinstance(module, torch.nn.GroupNorm):
                self._groupnorm_modules.append((name, module))

    def start_accumulation(self):
        """开始累积 GroupNorm 统计

        保存原始 running_mean/running_var，并切换到累积模式。
        """
        self._var_lists.clear()
        self._mean_lists.clear()
        self._pixel_lists.clear()
        self._weights.clear()
        self._biases.clear()
        self._is_accumulating = True

        for name, module in self._groupnorm_modules:
            # 保存原始统计
            if module.running_mean is not None:
                self._original_stats[name] = (
                    module.running_mean.clone(),
                    module.running_var.clone(),
                )

            # 初始化累积器
            self._var_lists[name] = []
            self._mean_lists[name] = []
            self._pixel_lists[name] = []
            self._weights[name] = module.weight.data.clone() if module.weight is not None else None
            self._biases[name] = module.bias.data.clone() if module.bias is not None else None

        logger.info(f"GroupNorm 跨 tile 统计累积开始: {len(self._groupnorm_modules)} 个 GroupNorm 层")

    def accumulate_from_tile(
        self,
        tile: torch.Tensor,
        module_name: str | None = None,
    ):
        """从单个 tile 的 GroupNorm 输入中累积统计

        在每个 tile 通过 GroupNorm 之前调用，累积该 tile 的统计。

        Args:
            tile: 当前 tile 的输入张量 (GroupNorm 输入)
            module_name: GroupNorm 模块名称，None 时累积所有模块
        """
        if not self._is_accumulating:
            return

        try:
            var, mean = _get_group_norm_stats(tile, self.num_groups)
            num_pixels = tile.shape[2] * tile.shape[3] if tile.ndim >= 4 else tile.shape[-1]

            if module_name is not None:
                if module_name in self._var_lists:
                    self._var_lists[module_name].append(var)
                    self._mean_lists[module_name].append(mean)
                    self._pixel_lists[module_name].append(num_pixels)
            else:
                # 累积到所有模块 (假设输入尺寸匹配)
                for name, _ in self._groupnorm_modules:
                    if name in self._var_lists:
                        self._var_lists[name].append(var.clone())
                        self._mean_lists[name].append(mean.clone())
                        self._pixel_lists[name].append(num_pixels)
        except Exception as e:
            logger.debug(f"GroupNorm 累积失败: {e}")

    def get_global_norm_function(self, module_name: str) -> Callable | None:
        """获取全局 GroupNorm 函数

        所有 tile 处理完成后调用，返回使用全局统计的 GroupNorm 函数。

        Args:
            module_name: GroupNorm 模块名称

        Returns:
            全局 GroupNorm 函数，或 None (无累积数据时)
        """
        if not self._is_accumulating:
            return None

        if module_name not in self._var_lists or len(self._var_lists[module_name]) == 0:
            return None

        var_list = self._var_lists[module_name]
        mean_list = self._mean_lists[module_name]
        pixel_list = self._pixel_lists[module_name]

        # 参考 SCST 的 GroupNormParam.summary() 实现
        # 按 pixel 数量加权平均
        var_stacked = torch.vstack(var_list)
        mean_stacked = torch.vstack(mean_list)
        max_pixels = max(pixel_list)
        pixels = torch.tensor(
            pixel_list, dtype=torch.float32, device=var_stacked.device
        ) / max_pixels
        sum_pixels = pixels.sum()
        pixels = pixels.unsqueeze(1) / sum_pixels

        global_var = (var_stacked * pixels).sum(dim=0)
        global_mean = (mean_stacked * pixels).sum(dim=0)

        weight = self._weights.get(module_name)
        bias = self._biases.get(module_name)

        def global_norm_fn(x, mean=global_mean, var=global_var, w=weight, b=bias):
            return custom_group_norm(x, self.num_groups, mean, var, w, b)

        return global_norm_fn

    def apply_accumulated_stats(self):
        """将累积的全局统计应用到各 GroupNorm 层的 running_mean/running_var

        用全局 mean/var 替换局部统计，确保后续推理使用一致的归一化参数。
        """
        if not self._is_accumulating:
            return

        for name, module in self._groupnorm_modules:
            if name in self._var_lists and len(self._var_lists[name]) > 0:
                var_list = self._var_lists[name]
                mean_list = self._mean_lists[name]
                pixel_list = self._pixel_lists[name]

                try:
                    var_stacked = torch.vstack(var_list)
                    mean_stacked = torch.vstack(mean_list)
                    max_pixels = max(pixel_list)
                    pixels = torch.tensor(
                        pixel_list, dtype=torch.float32, device=var_stacked.device
                    ) / max_pixels
                    sum_pixels = pixels.sum()
                    pixels = pixels.unsqueeze(1) / sum_pixels

                    global_mean = (mean_stacked * pixels).sum(dim=0)
                    global_var = (var_stacked * pixels).sum(dim=0)

                    # 替换 GroupNorm 的 running 统计
                    if module.running_mean is not None:
                        module.running_mean.copy_(global_mean.to(module.running_mean.dtype))
                    if module.running_var is not None:
                        module.running_var.copy_(global_var.to(module.running_var.dtype))
                except Exception as e:
                    logger.debug(f"应用全局统计到 {name} 失败: {e}")

        self._is_accumulating = False
        logger.info("GroupNorm 全局统计已应用到各层")

    def restore_original_stats(self):
        """恢复原始 GroupNorm 统计（推理完成后清理）"""
        for name, module in self._groupnorm_modules:
            if name in self._original_stats:
                orig_mean, orig_var = self._original_stats[name]
                if module.running_mean is not None:
                    module.running_mean.copy_(orig_mean)
                if module.running_var is not None:
                    module.running_var.copy_(orig_var)

        self._original_stats.clear()
        self._is_accumulating = False

    def reset(self):
        """重置累积状态"""
        self._var_lists.clear()
        self._mean_lists.clear()
        self._pixel_lists.clear()
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
    use_gaussian_blend: bool = True,
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
        use_gaussian_blend: 是否使用高斯权重混合

    Returns:
        包装后的 tiled 推理函数
    """

    def tiled_fn(tensor: torch.Tensor, **kwargs) -> torch.Tensor:
        """tiled 推理包装"""
        if tensor.ndim < 3:
            return fn(tensor, **kwargs)

        # 确定 spatial 维度
        if tensor.ndim == 4:  # (B, C, H, W)
            h_dim, w_dim = -2, -1
            num_spatial = 2
        elif tensor.ndim == 5:  # (B, C, T, H, W) - video
            t_dim, h_dim, w_dim = -3, -2, -1
            num_spatial = 3
        else:
            return fn(tensor, **kwargs)

        if num_spatial == 2:
            h, w = tensor.shape[h_dim], tensor.shape[w_dim]
        else:
            t, h, w = tensor.shape[t_dim], tensor.shape[h_dim], tensor.shape[w_dim]

        # 如果输入比 tile 小，不需要 tiled
        max_spatial = max(h, w) if num_spatial == 2 else max(t, h, w)
        if max_spatial <= tile_size:
            return fn(tensor, **kwargs)

        # 计算 tile 位置
        stride = tile_size - overlap

        def compute_positions(size: int) -> list[int]:
            positions = []
            pos = 0
            while pos < size:
                positions.append(min(pos, size - tile_size))
                pos += stride
                if pos + tile_size >= size:
                    break
            if positions[-1] + tile_size < size:
                positions.append(size - tile_size)
            return positions

        if num_spatial == 2:
            y_positions = compute_positions(h)
            x_positions = compute_positions(w)
        else:
            t_positions = compute_positions(t)
            y_positions = compute_positions(h)
            x_positions = compute_positions(w)

        # 创建权重映射
        device = tensor.device
        dtype = tensor.dtype

        if use_gaussian_blend and weight_type == "gaussian":
            weight_map = create_gaussian_weight_map(
                tile_size, overlap, num_dims=num_spatial, device=device, dtype=dtype
            )
        else:
            # Fallback 到线性权重
            weight_map = torch.ones([tile_size] * num_spatial, device=device, dtype=dtype)

        # 初始化输出累积器
        output_shape = list(tensor.shape)
        if num_spatial == 2:
            output_shape[h_dim] = h
            output_shape[w_dim] = w
        else:
            output_shape[t_dim] = t
            output_shape[h_dim] = h
            output_shape[w_dim] = w
        output = torch.zeros(output_shape, device=device, dtype=dtype)

        weight_sum_shape = [1] * tensor.ndim
        if num_spatial == 2:
            weight_sum_shape[h_dim] = h
            weight_sum_shape[w_dim] = w
        else:
            weight_sum_shape[t_dim] = t
            weight_sum_shape[h_dim] = h
            weight_sum_shape[w_dim] = w
        weight_sum = torch.zeros(weight_sum_shape, device=device, dtype=dtype)

        # 计算总 tile 数
        if num_spatial == 2:
            total_tiles = len(y_positions) * len(x_positions)
        else:
            total_tiles = len(t_positions) * len(y_positions) * len(x_positions)
        processed = 0

        # NaN 检测和回退
        nan_fallback = False

        # 处理每个 tile
        if num_spatial == 2:
            for y_pos in y_positions:
                for x_pos in x_positions:
                    # 提取 tile
                    tile_slices = [slice(None)] * tensor.ndim
                    tile_slices[h_dim] = slice(y_pos, y_pos + tile_size)
                    tile_slices[w_dim] = slice(x_pos, x_pos + tile_size)
                    tile_input = tensor[tuple(tile_slices)]

                    # 运行推理
                    try:
                        tile_output = fn(tile_input, **kwargs)
                    except RuntimeError as e:
                        if "out of memory" in str(e).lower():
                            logger.warning(f"Tile OOM at ({y_pos},{x_pos}), 尝试更小的 tile")
                            torch.cuda.empty_cache()
                            # 回退: 直接对整个输入运行 fn
                            return fn(tensor, **kwargs)
                        raise

                    # NaN 检测
                    if detect_nan(tile_output, f"tile ({y_pos},{x_pos})"):
                        nan_fallback = True
                        break

                    # 提取输出 tile 对应区域
                    actual_h = min(tile_size, h - y_pos)
                    actual_w = min(tile_size, w - x_pos)

                    tile_slices_out = [slice(None)] * tile_output.ndim
                    tile_slices_out[h_dim] = slice(0, actual_h)
                    tile_slices_out[w_dim] = slice(0, actual_w)
                    tile_crop = tile_output[tuple(tile_slices_out)]

                    w_slices = [slice(0, actual_h), slice(0, actual_w)]
                    w_crop = weight_map[tuple(w_slices)]
                    while w_crop.ndim < tile_crop.ndim:
                        w_crop = w_crop.unsqueeze(0)

                    # 累加
                    out_slices = [slice(None)] * output.ndim
                    out_slices[h_dim] = slice(y_pos, y_pos + actual_h)
                    out_slices[w_dim] = slice(x_pos, x_pos + actual_w)
                    output[tuple(out_slices)] += tile_crop * w_crop

                    ws_slices = [slice(None)]
                    ws_slices.extend([slice(y_pos, y_pos + actual_h), slice(x_pos, x_pos + actual_w)])
                    weight_sum[tuple(ws_slices)] += w_crop

                    processed += 1
                    if progress_callback:
                        progress_callback(processed, total_tiles)
        else:
            # 3D video tiling
            for t_pos in t_positions:
                for y_pos in y_positions:
                    for x_pos in x_positions:
                        tile_slices = [slice(None)] * tensor.ndim
                        tile_slices[t_dim] = slice(t_pos, t_pos + tile_size)
                        tile_slices[h_dim] = slice(y_pos, y_pos + tile_size)
                        tile_slices[w_dim] = slice(x_pos, x_pos + tile_size)
                        tile_input = tensor[tuple(tile_slices)]

                        try:
                            tile_output = fn(tile_input, **kwargs)
                        except RuntimeError as e:
                            if "out of memory" in str(e).lower():
                                logger.warning(f"3D Tile OOM at ({t_pos},{y_pos},{x_pos}), 回退")
                                torch.cuda.empty_cache()
                                return fn(tensor, **kwargs)
                            raise

                        if detect_nan(tile_output, f"3D tile ({t_pos},{y_pos},{x_pos})"):
                            nan_fallback = True
                            break

                        actual_t = min(tile_size, t - t_pos)
                        actual_h = min(tile_size, h - y_pos)
                        actual_w = min(tile_size, w - x_pos)

                        tile_slices_out = [slice(None)] * tile_output.ndim
                        tile_slices_out[t_dim] = slice(0, actual_t)
                        tile_slices_out[h_dim] = slice(0, actual_h)
                        tile_slices_out[w_dim] = slice(0, actual_w)
                        tile_crop = tile_output[tuple(tile_slices_out)]

                        w_slices = [slice(0, actual_t), slice(0, actual_h), slice(0, actual_w)]
                        w_crop = weight_map[tuple(w_slices)]
                        while w_crop.ndim < tile_crop.ndim:
                            w_crop = w_crop.unsqueeze(0)

                        out_slices = [slice(None)] * output.ndim
                        out_slices[t_dim] = slice(t_pos, t_pos + actual_t)
                        out_slices[h_dim] = slice(y_pos, y_pos + actual_h)
                        out_slices[w_dim] = slice(x_pos, x_pos + actual_w)
                        output[tuple(out_slices)] += tile_crop * w_crop

                        ws_slices = [slice(None)]
                        ws_slices.extend([
                            slice(t_pos, t_pos + actual_t),
                            slice(y_pos, y_pos + actual_h),
                            slice(x_pos, x_pos + actual_w)
                        ])
                        weight_sum[tuple(ws_slices)] += w_crop

                        processed += 1
                        if progress_callback:
                            progress_callback(processed, total_tiles)

        # NaN 回退: 如果检测到 NaN，直接对整个输入运行 fn
        if nan_fallback:
            logger.warning("Tiled 推理检测到 NaN，回退到非 tiled 推理")
            torch.cuda.empty_cache()
            return fn(tensor, **kwargs)

        # 归一化
        weight_sum = weight_sum.clamp(min=1e-8)
        output = output / weight_sum

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
        return vae_model.decode(latents, **decode_kwargs).sample

    # 解码高分辨率 latent
    high_res_output = vae_model.decode(latents, **decode_kwargs).sample

    # 解码低分辨率 latent (颜色参考)
    low_res_output = vae_model.decode(low_res_latent, **decode_kwargs).sample

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
    kernel = _create_gaussian_kernel(kernel_size, sigma, device=high_res_output.device,
                                      channels=high_res_output.shape[1] if high_res_output.ndim == 4 else 1)

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
    """创建 2D 高斯滤波核 (depthwise 卷积格式)

    用于条件 VAE 解码时的低通滤波，提取低频颜色信息。

    Args:
        kernel_size: 滤波核大小 (奇数)
        sigma: 高斯标准差，控制模糊程度
        device: 张量所在设备
        channels: 输入通道数 (用于 depthwise conv)

    Returns:
        高斯核张量，形状为 [channels, 1, kernel_size, kernel_size]
    """
    x = torch.arange(kernel_size, device=device, dtype=torch.float32) - kernel_size // 2
    gauss_1d = torch.exp(-0.5 * (x / sigma) ** 2)
    gauss_2d = gauss_1d.unsqueeze(-1) * gauss_1d.unsqueeze(0)
    kernel = gauss_2d / gauss_2d.sum()

    kernel = kernel.unsqueeze(0).unsqueeze(0).expand(channels, 1, -1, -1).contiguous()
    return kernel


def _apply_gaussian_filter(
    tensor: torch.Tensor,
    kernel: torch.Tensor,
) -> torch.Tensor:
    """对张量应用高斯低通滤波

    支持 2D (B,C,H,W)、3D (C,H,W) 和 5D (B,C,T,H,W) 视频张量。
    对 5D 视频张量逐帧应用滤波。

    Args:
        tensor: 输入张量
        kernel: 高斯滤波核 (由 _create_gaussian_kernel 创建)

    Returns:
        滤波后的张量，形状与输入一致
    """
    channels = tensor.shape[1] if tensor.ndim == 4 else 1
    padding = kernel.shape[-1] // 2

    if tensor.ndim == 4:
        result = F.conv2d(tensor, kernel[:channels], padding=padding, groups=channels)
    elif tensor.ndim == 3:
        result = F.conv2d(tensor.unsqueeze(0), kernel[:channels], padding=padding, groups=channels)
        result = result.squeeze(0)
    elif tensor.ndim == 5:
        b, c, t, h, w = tensor.shape
        result = []
        for i in range(t):
            frame = tensor[:, :, i]
            filtered = F.conv2d(frame, kernel[:c], padding=padding, groups=c)
            result.append(filtered)
        result = torch.stack(result, dim=2)
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
    """禁用 VAE slicing 模式

    恢复 VAE 为正常解码模式，所有通道一次性处理。

    Args:
        vae_model: VAE 模型实例

    Returns:
        配置后的 VAE 模型
    """
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
    """将模型模块卸载到 CPU 并清理 GPU 缓存

    在顺序 CPU offload 策略中，使用完一个模块后将其移回 CPU 以释放显存。

    Args:
        module: 要卸载的 PyTorch 模块
    """
    module.to("cpu")
    torch.cuda.empty_cache()


def load_module_to_gpu(module: torch.nn.Module, device: torch.device | str = "cuda") -> None:
    """将模型模块加载到 GPU

    在顺序 CPU offload 策略中，需要使用某个模块前将其加载到 GPU。

    Args:
        module: 要加载的 PyTorch 模块
        device: 目标 GPU 设备，默认 "cuda"
    """
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
    """

    def __init__(self, config: CacheQuantizerConfig | None = None):
        self.config = config or CacheQuantizerConfig()
        self._quant_max = (1 << self.config.num_bits) - 1  # 255 for 8bit

    def q(
        self, tensor: torch.Tensor
    ) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
        """将 float32 张量量化为 uint8"""
        if not self.config.enabled:
            return tensor, {}

        mode = self.config.quant_mode
        eps = self.config.eps

        if mode == "symmetric":
            scale = tensor.abs().max().clamp(min=eps) / self._quant_max
            quantized = torch.clamp(
                torch.round(tensor / scale), 0, self._quant_max
            ).to(torch.uint8)
            meta = {"scale": scale.detach()}
        else:
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
        """将 uint8 量化张量反量化为 float32"""
        if not self.config.enabled or not meta:
            return quantized.float()

        scale = meta["scale"]
        restored = quantized.float() * scale

        if "offset" in meta:
            restored = restored + meta["offset"]

        return restored


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
            tile_state = getattr(self.vae, '_internal_tile_state', None)
            if tile_state and 'outputs' in tile_state and 'positions' in tile_state:
                self.vae._last_tile_outputs = tile_state['outputs']
                self.vae._last_tile_positions = tile_state['positions']
                self.vae._last_tile_size = tile_size if isinstance(tile_size, int) else tile_size[0]
                self.vae._last_tile_overlap = tile_overlap if isinstance(tile_overlap, int) else tile_overlap[0]
                logger.debug(f"TiledVAEHook: 捕获到 {len(tile_state['outputs'])} 个 tile 输出")
            else:
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
        # 清理临时属性
        for attr in ['_last_tile_outputs', '_last_tile_positions', '_last_tile_size', '_last_tile_overlap']:
            if hasattr(self.vae, attr):
                delattr(self.vae, attr)
        logger.info("TiledVAEHook 已卸载")

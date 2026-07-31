# Copyright (c) 2023 HuggingFace Team
# Copyright (c) 2025 ByteDance Ltd. and/or its affiliates.
# SPDX-License-Identifier: Apache License, Version 2.0 (the "License")
#
# This file has been modified by ByteDance Ltd. and/or its affiliates. on 1st June 2025
#
# Original file was released under Apache License, Version 2.0 (the "License"), with the full license text
# available at http://www.apache.org/licenses/LICENSE-2.0.
#
# This modified file is released under the same license.

"""Causal Video VAE 主模型实现。

实现基于 3D 因果卷积的视频变分自编码器（VideoAutoencoderKL），架构参考 Stable Diffusion VAE
并扩展到时序维度。核心特点：

架构设计：
- Encoder3D: 4个下采样块（每个含2个ResnetBlock3D），后3个同时进行时序2x下采样 + 空间2x下采样，
  中间 UNetMidBlock3D（无注意力），输出高斯分布参数（μ, logσ²）。
- Decoder3D: 对称结构，中间块 + 4个上采样块（pixel shuffle式上采样），前3个同时时序上采样。
- ResnetBlock3D: 两卷积残差块，GroupNorm + SiLU，使用因果3D卷积。
- Upsample3D: 1x1 Conv3d 通道扩展 + pixel shuffle 重排实现上采样，identity初始化保持恒等映射。
- Downsample3D: 步长为2的因果3D卷积下采样，右下角补零对齐。

关键特性：
1. 因果卷积（Causal Conv）：时间维不使用未来帧信息，支持流式/在线推理。
2. 权重膨胀（Weight Inflation）：可从2D图像VAE checkpoint加载，自动膨胀到3D。
3. 选择性梯度检查点（Selective Checkpointing）：coarse块级/fine模块级梯度检查点节省训练显存。
4. 时序切片推理（Temporal Slicing）：长视频沿时间维切片处理，缓存跨片上下文。
5. 空间分块推理（Spatial Tiling）：大分辨率视频分空间tile处理，余弦窗渐变融合。
6. 内存限制卷积：递归沿空间维度分片卷积计算，避免大激活值OOM。
7. 序列并行（Context Parallel）：多GPU分布时序维度，环形通信传递缓存。
8. CPU卸载：推理时将时序记忆卸载到CPU。

VAE 潜变量空间：
- 默认配置 (s8_c16_t4): 空间压缩 16x (8x8)，时序压缩 8x，通道数 16。
- 输入视频 [B,3,T,H,W] → 潜变量 [B,16,T/8,H/8,W/8]。
"""

from contextlib import nullcontext
from typing import Optional, Tuple, Literal, Callable, Union

import torch
import torch.nn as nn
import torch.nn.functional as F
from diffusers.models.autoencoders.vae import DiagonalGaussianDistribution
from einops import rearrange

from common.distributed.advanced import get_sequence_parallel_world_size
from common.logger import get_logger
from common.utils import safe_pad_operation
from models.video_vae_v3.modules.causal_inflation_lib import (
    InflatedCausalConv3d,
    causal_norm_wrapper,
    init_causal_conv3d,
    remove_head,
)
from models.video_vae_v3.modules.context_parallel_lib import (
    causal_conv_gather_outputs,
    causal_conv_slice_inputs,
)
from models.video_vae_v3.modules.global_config import set_norm_limit
from models.video_vae_v3.modules.types import (
    CausalAutoencoderOutput,
    CausalDecoderOutput,
    CausalEncoderOutput,
    MemoryState,
    _inflation_mode_t,
    _memory_device_t,
    _receptive_field_t,
    _selective_checkpointing_t,
)

logger = get_logger(__name__)  # pylint: disable=invalid-name


def gradient_checkpointing(module: Union[Callable, nn.Module], *args, enabled: bool, **kwargs):
    """梯度检查点包装函数（推理时直接执行，不重计算）。

    训练时若 enabled=True 使用 torch 梯度检查点节省显存；推理时直接前向。

    Args:
        module: 要执行的模块或函数。
        *args: 传递给 module 的位置参数。
        enabled: 是否启用梯度检查点。
        **kwargs: 传递给 module 的关键字参数。

    Returns:
        module(*args, **kwargs) 的输出。
    """
    return module(*args, **kwargs)


class ResnetBlock2D(nn.Module):
    r"""2D 残差块（用于构建 ResnetBlock3D 的基类）。

    标准 Pre-Norm 残差块：GroupNorm → SiLU → Conv → GroupNorm → SiLU → Dropout → Conv + Shortcut。

    Parameters:
        in_channels: 输入通道数。
        out_channels: 输出通道数，默认与 in_channels 相同。
        dropout: Dropout 概率。
    """

    def __init__(
        self, *, in_channels: int, out_channels: Optional[int] = None, dropout: float = 0.0
    ):
        super().__init__()
        self.in_channels = in_channels
        out_channels = in_channels if out_channels is None else out_channels
        self.out_channels = out_channels

        self.nonlinearity = nn.SiLU()

        self.norm1 = torch.nn.GroupNorm(
            num_groups=32, num_channels=in_channels, eps=1e-6, affine=True
        )

        self.conv1 = nn.Conv2d(in_channels, out_channels, kernel_size=3, stride=1, padding=1)

        self.norm2 = torch.nn.GroupNorm(
            num_groups=32, num_channels=out_channels, eps=1e-6, affine=True
        )

        self.dropout = torch.nn.Dropout(dropout)
        self.conv2 = nn.Conv2d(out_channels, out_channels, kernel_size=3, stride=1, padding=1)

        self.use_in_shortcut = self.in_channels != out_channels

        self.conv_shortcut = None
        if self.use_in_shortcut:
            self.conv_shortcut = nn.Conv2d(
                in_channels, out_channels, kernel_size=1, stride=1, padding=0
            )

    def forward(self, input_tensor: torch.Tensor) -> torch.Tensor:
        """2D残差块前向传播。

        Args:
            input_tensor: 输入 [B, C, H, W]。

        Returns:
            输出 [B, Cout, H, W]。
        """
        hidden = input_tensor

        hidden = self.norm1(hidden)
        hidden = self.nonlinearity(hidden)
        hidden = self.conv1(hidden)

        hidden = self.norm2(hidden)
        hidden = self.nonlinearity(hidden)
        hidden = self.dropout(hidden)
        hidden = self.conv2(hidden)

        if self.conv_shortcut is not None:
            input_tensor = self.conv_shortcut(input_tensor)

        output_tensor = input_tensor + hidden

        return output_tensor


class Upsample3D(nn.Module):
    """3D 上采样层（pixel shuffle 风格）。

    使用 1x1 Conv3d 将通道数扩展 upscale_ratio 倍（spatial²*temporal），
    然后通过 einops rearrange 重排为上采样后的时空分辨率。
    权重初始化为identity矩阵，保证初始时上采样等价于最近邻插值。
    后接 3x3 因果卷积平滑。
    """

    def __init__(
        self,
        channels: int,
        inflation_mode: _inflation_mode_t = "tail",
        temporal_up: bool = False,
        spatial_up: bool = True,
        slicing: bool = False,
    ):
        """初始化3D上采样层。

        Args:
            channels: 输入/输出通道数。
            inflation_mode: 卷积权重膨胀模式。
            temporal_up: 是否在时间维进行2x上采样。
            spatial_up: 是否在空间维进行2x上采样。
            slicing: 是否启用时序切片上采样（大分辨率时节省显存）。
        """
        super().__init__()
        self.channels = channels
        self.conv = init_causal_conv3d(
            self.channels, self.channels, kernel_size=3, padding=1, inflation_mode=inflation_mode
        )

        self.temporal_up = temporal_up
        self.spatial_up = spatial_up
        self.temporal_ratio = 2 if temporal_up else 1
        self.spatial_ratio = 2 if spatial_up else 1
        self.slicing = slicing

        upscale_ratio = (self.spatial_ratio**2) * self.temporal_ratio
        self.upscale_conv = nn.Conv3d(
            self.channels, self.channels * upscale_ratio, kernel_size=1, padding=0
        )
        identity = (
            torch.eye(self.channels).repeat(upscale_ratio, 1).reshape_as(self.upscale_conv.weight)
        )

        self.upscale_conv.weight.data.copy_(identity)
        nn.init.zeros_(self.upscale_conv.bias)
        self.gradient_checkpointing = False

    def forward(
        self,
        hidden_states: torch.FloatTensor,
        memory_state: MemoryState,
    ) -> torch.FloatTensor:
        return gradient_checkpointing(
            self.custom_forward,
            hidden_states,
            memory_state,
            enabled=self.training and self.gradient_checkpointing,
        )

    def custom_forward(
        self,
        hidden_states: torch.FloatTensor,
        memory_state: MemoryState,
    ) -> torch.FloatTensor:
        """上采样前向实现。

        流程：1x1 conv扩展通道 → pixel shuffle 重排 → （时序上采样时）移除重复首帧 → 3x3平滑卷积。

        Args:
            hidden_states: 输入 [B, C, T, H, W]。
            memory_state: 因果记忆状态。

        Returns:
            上采样输出 [B, C, T*z, H*x, W*y]，其中 z=temporal_ratio, x/y=spatial_ratio。
        """
        assert hidden_states.shape[1] == self.channels

        if self.slicing:
            split_size = hidden_states.size(2) // 2
            hidden_states = list(
                hidden_states.split([split_size, hidden_states.size(2) - split_size], dim=2)
            )
        else:
            hidden_states = [hidden_states]

        for i in range(len(hidden_states)):
            hidden_states[i] = self.upscale_conv(hidden_states[i])
            hidden_states[i] = rearrange(
                hidden_states[i],
                "b (x y z c) f h w -> b c (f z) (h x) (w y)",
                x=self.spatial_ratio,
                y=self.spatial_ratio,
                z=self.temporal_ratio,
            )

        if self.temporal_up and memory_state != MemoryState.ACTIVE:
            hidden_states[0] = remove_head(hidden_states[0])

        if self.slicing:
            hidden_states = self.conv(hidden_states, memory_state=memory_state)
            return torch.cat(hidden_states, dim=2)
        else:
            return self.conv(hidden_states[0], memory_state=memory_state)


class Downsample3D(nn.Module):
    """3D 下采样层（步长卷积）。

    使用 (kT,3,3) 卷积核，步长 (sT,sH,sW)=(2,2,2) 进行时空下采样。
    卷积前在右下角补零以对齐步长卷积的尺寸。
    """

    def __init__(
        self,
        channels: int,
        inflation_mode: _inflation_mode_t = "tail",
        temporal_down: bool = False,
        spatial_down: bool = True,
    ):
        """初始化3D下采样层。

        Args:
            channels: 输入/输出通道数。
            inflation_mode: 权重膨胀模式。
            temporal_down: 是否在时间维2x下采样。
            spatial_down: 是否在空间维2x下采样。
        """
        super().__init__()
        self.channels = channels
        self.temporal_down = temporal_down
        self.spatial_down = spatial_down

        self.temporal_ratio = 2 if temporal_down else 1
        self.spatial_ratio = 2 if spatial_down else 1

        self.temporal_kernel = 3 if temporal_down else 1
        self.spatial_kernel = 3 if spatial_down else 1

        self.conv = init_causal_conv3d(
            self.channels,
            self.channels,
            kernel_size=(self.temporal_kernel, self.spatial_kernel, self.spatial_kernel),
            stride=(self.temporal_ratio, self.spatial_ratio, self.spatial_ratio),
            padding=((1 if self.temporal_down else 0), 0, 0),
            inflation_mode=inflation_mode,
        )
        self.gradient_checkpointing = False

    def forward(
        self,
        hidden_states: torch.FloatTensor,
        memory_state: MemoryState,
    ) -> torch.FloatTensor:
        return gradient_checkpointing(
            self.custom_forward,
            hidden_states,
            memory_state,
            enabled=self.training and self.gradient_checkpointing,
        )

    def custom_forward(
        self,
        hidden_states: torch.FloatTensor,
        memory_state: MemoryState,
    ) -> torch.FloatTensor:
        """下采样前向实现。

        空间下采样时在右侧/底部补1个零 → 因果卷积（时间/空间步长2）。

        Args:
            hidden_states: 输入 [B, C, T, H, W]。
            memory_state: 记忆状态。

        Returns:
            下采样输出 [B, C, T/sT, H/sH, W/sW]。
        """
        assert hidden_states.shape[1] == self.channels

        if self.spatial_down:
            hidden_states = safe_pad_operation(hidden_states, (0, 1, 0, 1), mode="constant", value=0)

        hidden_states = self.conv(hidden_states, memory_state=memory_state)
        return hidden_states


class ResnetBlock3D(ResnetBlock2D):
    """3D 残差块，使用因果3D卷积。

    在 ResnetBlock2D 基础上将 conv1/conv2/conv_shortcut 替换为 InflatedCausalConv3d。
    支持配置时间感受野：'half' 对应第二卷积核 (1,3,3)（仅空间），
    'full' 对应 (3,3,3)（时空）。
    """

    def __init__(
        self,
        *args,
        inflation_mode: _inflation_mode_t = "tail",
        time_receptive_field: _receptive_field_t = "half",
        **kwargs,
    ):
        """初始化3D残差块。

        Args:
            *args: 传递给 ResnetBlock2D 的参数。
            inflation_mode: 卷积权重膨胀模式。
            time_receptive_field: 时间感受野类型。
            **kwargs: 传递给 ResnetBlock2D 的参数。
        """
        super().__init__(*args, **kwargs)
        self.conv1 = init_causal_conv3d(
            self.in_channels,
            self.out_channels,
            kernel_size=3,
            stride=1,
            padding=1,
            inflation_mode=inflation_mode,
        )

        self.conv2 = init_causal_conv3d(
            self.out_channels,
            self.out_channels,
            kernel_size=(1, 3, 3) if time_receptive_field == "half" else (3, 3, 3),
            stride=1,
            padding=(0, 1, 1) if time_receptive_field == "half" else (1, 1, 1),
            inflation_mode=inflation_mode,
        )

        if self.use_in_shortcut:
            self.conv_shortcut = init_causal_conv3d(
                self.in_channels,
                self.out_channels,
                kernel_size=1,
                stride=1,
                padding=0,
                bias=(self.conv_shortcut.bias is not None),
                inflation_mode=inflation_mode,
            )
        self.gradient_checkpointing = False

    def forward(self, input_tensor: torch.Tensor, memory_state: MemoryState = MemoryState.UNSET):
        return gradient_checkpointing(
            self.custom_forward,
            input_tensor,
            memory_state,
            enabled=self.training and self.gradient_checkpointing,
        )

    def custom_forward(
        self, input_tensor: torch.Tensor, memory_state: MemoryState = MemoryState.UNSET
    ):
        """3D残差块前向实现。

        流程：GN → SiLU → CausalConv3d → GN → SiLU → Dropout → CausalConv3d + Shortcut。
        使用 causal_norm_wrapper 处理 GroupNorm 的5D张量维度。

        Args:
            input_tensor: 输入 [B, C, T, H, W]。
            memory_state: 因果记忆状态。

        Returns:
            输出 [B, Cout, T, H, W]。
        """
        assert memory_state != MemoryState.UNSET
        hidden_states = input_tensor

        hidden_states = causal_norm_wrapper(self.norm1, hidden_states)
        hidden_states = self.nonlinearity(hidden_states)
        hidden_states = self.conv1(hidden_states, memory_state=memory_state)

        hidden_states = causal_norm_wrapper(self.norm2, hidden_states)
        hidden_states = self.nonlinearity(hidden_states)
        hidden_states = self.dropout(hidden_states)
        hidden_states = self.conv2(hidden_states, memory_state=memory_state)

        if self.conv_shortcut is not None:
            input_tensor = self.conv_shortcut(input_tensor, memory_state=memory_state)

        output_tensor = input_tensor + hidden_states

        return output_tensor


class DownEncoderBlock3D(nn.Module):
    """3D 编码器下采样块。

    由 num_layers 个 ResnetBlock3D 加一个可选的 Downsample3D 组成。
    支持配置是否在该块进行时序下采样。
    """

    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        dropout: float = 0.0,
        num_layers: int = 1,
        add_downsample: bool = True,
        inflation_mode: _inflation_mode_t = "tail",
        time_receptive_field: _receptive_field_t = "half",
        temporal_down: bool = True,
        spatial_down: bool = True,
    ):
        """初始化下采样块。

        Args:
            in_channels: 输入通道。
            out_channels: 输出通道。
            dropout: Dropout率。
            num_layers: 残差块数量。
            add_downsample: 是否在末尾添加下采样层。
            inflation_mode: 权重膨胀模式。
            time_receptive_field: 时间感受野。
            temporal_down: 是否在该块进行时序2x下采样。
            spatial_down: 是否在该块进行空间2x下采样。
        """
        super().__init__()
        resnets = []

        for i in range(num_layers):
            in_channels = in_channels if i == 0 else out_channels
            resnets.append(
                ResnetBlock3D(
                    in_channels=in_channels,
                    out_channels=out_channels,
                    dropout=dropout,
                    inflation_mode=inflation_mode,
                    time_receptive_field=time_receptive_field,
                )
            )

        self.resnets = nn.ModuleList(resnets)

        self.downsamplers = None
        if add_downsample:
            self.downsamplers = nn.ModuleList(
                [
                    Downsample3D(
                        channels=out_channels,
                        inflation_mode=inflation_mode,
                        temporal_down=temporal_down,
                        spatial_down=spatial_down,
                    )
                ]
            )

    def forward(
        self, hidden_states: torch.FloatTensor, memory_state: MemoryState
    ) -> torch.FloatTensor:
        """下采样块前向。

        依次通过所有残差块，然后通过下采样层（如果有）。

        Args:
            hidden_states: 输入 [B, C, T, H, W]。
            memory_state: 记忆状态。

        Returns:
            输出（可能下采样）的特征图。
        """
        for resnet in self.resnets:
            hidden_states = resnet(hidden_states, memory_state=memory_state)

        if self.downsamplers is not None:
            for downsampler in self.downsamplers:
                hidden_states = downsampler(hidden_states, memory_state=memory_state)

        return hidden_states


class UpDecoderBlock3D(nn.Module):
    """3D 解码器上采样块。

    由 num_layers 个 ResnetBlock3D 加一个可选的 Upsample3D 组成。
    支持时序/空间独立控制上采样，以及切片上采样。
    """

    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        dropout: float = 0.0,
        num_layers: int = 1,
        add_upsample: bool = True,
        inflation_mode: _inflation_mode_t = "tail",
        time_receptive_field: _receptive_field_t = "half",
        temporal_up: bool = True,
        spatial_up: bool = True,
        slicing: bool = False,
    ):
        """初始化上采样块。

        Args:
            in_channels: 输入通道。
            out_channels: 输出通道。
            dropout: Dropout率。
            num_layers: 残差块数量。
            add_upsample: 是否添加上采样层。
            inflation_mode: 权重膨胀模式。
            time_receptive_field: 时间感受野。
            temporal_up: 是否时序2x上采样。
            spatial_up: 是否空间2x上采样。
            slicing: 是否启用切片上采样。
        """
        super().__init__()
        resnets = []

        for i in range(num_layers):
            input_channels = in_channels if i == 0 else out_channels

            resnets.append(
                ResnetBlock3D(
                    in_channels=input_channels,
                    out_channels=out_channels,
                    dropout=dropout,
                    inflation_mode=inflation_mode,
                    time_receptive_field=time_receptive_field,
                )
            )

        self.resnets = nn.ModuleList(resnets)

        self.upsamplers = None
        if add_upsample:
            self.upsamplers = nn.ModuleList(
                [
                    Upsample3D(
                        channels=out_channels,
                        inflation_mode=inflation_mode,
                        temporal_up=temporal_up,
                        spatial_up=spatial_up,
                        slicing=slicing,
                    )
                ]
            )

    def forward(
        self, hidden_states: torch.FloatTensor, memory_state: MemoryState
    ) -> torch.FloatTensor:
        """上采样块前向。"""
        for resnet in self.resnets:
            hidden_states = resnet(hidden_states, memory_state=memory_state)

        if self.upsamplers is not None:
            for upsampler in self.upsamplers:
                hidden_states = upsampler(hidden_states, memory_state=memory_state)

        return hidden_states


class UNetMidBlock3D(nn.Module):
    """U-Net 中间块（瓶颈层），由两个 ResnetBlock3D 组成。

    该版本无自注意力层（与 attn_video_vae.py 中带注意力的版本不同）。
    """

    def __init__(
        self,
        channels: int,
        dropout: float = 0.0,
        inflation_mode: _inflation_mode_t = "tail",
        time_receptive_field: _receptive_field_t = "half",
    ):
        super().__init__()
        self.resnets = nn.ModuleList(
            [
                ResnetBlock3D(
                    in_channels=channels,
                    out_channels=channels,
                    dropout=dropout,
                    inflation_mode=inflation_mode,
                    time_receptive_field=time_receptive_field,
                ),
                ResnetBlock3D(
                    in_channels=channels,
                    out_channels=channels,
                    dropout=dropout,
                    inflation_mode=inflation_mode,
                    time_receptive_field=time_receptive_field,
                ),
            ]
        )

    def forward(self, hidden_states: torch.Tensor, memory_state: MemoryState):
        """中间块前向：两个残差块顺序处理。"""
        for resnet in self.resnets:
            hidden_states = resnet(hidden_states, memory_state)
        return hidden_states


class Encoder3D(nn.Module):
    r"""VAE 3D 编码器，将视频输入编码为潜变量高斯分布参数。

    架构：Conv_in → [DownEncoderBlock3D × N] → UNetMidBlock3D → GroupNorm → SiLU → Conv_out
    最后 conv_out 输出 2*latent_channels 通道（μ 和 logσ²）用于参数化对角高斯分布。
    """

    def __init__(
        self,
        in_channels: int = 3,
        out_channels: int = 3,
        block_out_channels: Tuple[int, ...] = (64,),
        layers_per_block: int = 2,
        double_z: bool = True,
        temporal_down_num: int = 2,
        inflation_mode: _inflation_mode_t = "tail",
        time_receptive_field: _receptive_field_t = "half",
        selective_checkpointing: Tuple[_selective_checkpointing_t] = ("none",),
    ):
        """初始化3D编码器。

        Args:
            in_channels: 输入通道数（视频为3）。
            out_channels: 潜变量通道数。
            block_out_channels: 各下采样块的输出通道元组。
            layers_per_block: 每个块内残差层数。
            double_z: 是否输出2倍通道（μ+logσ²）。
            temporal_down_num: 从末尾数的前N个块进行时序下采样。
            inflation_mode: 权重膨胀模式。
            time_receptive_field: 时间感受野。
            selective_checkpointing: 每个块的梯度检查点策略。
        """
        super().__init__()
        self.layers_per_block = layers_per_block

        self.temporal_down_num = temporal_down_num

        self.conv_in = init_causal_conv3d(
            in_channels,
            block_out_channels[0],
            kernel_size=3,
            stride=1,
            padding=1,
            inflation_mode=inflation_mode,
        )

        self.down_blocks = nn.ModuleList([])

        # down
        output_channel = block_out_channels[0]
        for i in range(len(block_out_channels)):
            input_channel = output_channel
            output_channel = block_out_channels[i]
            is_final_block = i == len(block_out_channels) - 1
            is_temporal_down_block = i >= len(block_out_channels) - self.temporal_down_num - 1

            down_block = DownEncoderBlock3D(
                num_layers=self.layers_per_block,
                in_channels=input_channel,
                out_channels=output_channel,
                add_downsample=not is_final_block,
                temporal_down=is_temporal_down_block,
                spatial_down=True,
                inflation_mode=inflation_mode,
                time_receptive_field=time_receptive_field,
            )
            self.down_blocks.append(down_block)

        # mid
        self.mid_block = UNetMidBlock3D(
            channels=block_out_channels[-1],
            inflation_mode=inflation_mode,
            time_receptive_field=time_receptive_field,
        )

        # out
        self.conv_norm_out = nn.GroupNorm(
            num_channels=block_out_channels[-1], num_groups=32, eps=1e-6
        )
        self.conv_act = nn.SiLU()

        conv_out_channels = 2 * out_channels if double_z else out_channels
        self.conv_out = init_causal_conv3d(
            block_out_channels[-1], conv_out_channels, 3, padding=1, inflation_mode=inflation_mode
        )

        assert len(selective_checkpointing) == len(self.down_blocks)
        self.set_gradient_checkpointing(selective_checkpointing)

    def set_gradient_checkpointing(self, checkpointing_types):
        """设置选择性梯度检查点策略。

        Args:
            checkpointing_types: 每个下采样块的检查点类型列表，
                'coarse'=块级检查点，'fine'=模块级检查点，其他=禁用。
        """
        gradient_checkpointing = []
        for down_block, sac_type in zip(self.down_blocks, checkpointing_types):
            if sac_type == "coarse":
                gradient_checkpointing.append(True)
            elif sac_type == "fine":
                for n, m in down_block.named_modules():
                    if hasattr(m, "gradient_checkpointing"):
                        m.gradient_checkpointing = True
                        logger.debug(f"set gradient_checkpointing: {n}")
                gradient_checkpointing.append(False)
            else:
                gradient_checkpointing.append(False)
        self.gradient_checkpointing = gradient_checkpointing
        logger.info(f"[Encoder3D] gradient_checkpointing: {checkpointing_types}")

    def forward(self, sample: torch.FloatTensor, memory_state: MemoryState) -> torch.FloatTensor:
        r"""编码器前向传播。

        Args:
            sample: 输入视频 [B, C, T, H, W]。
            memory_state: 因果记忆状态。

        Returns:
            潜变量分布参数 [B, 2*latent_channels, T_lat, H_lat, W_lat]。
        """
        sample = self.conv_in(sample, memory_state=memory_state)
        # down
        for down_block, sac in zip(self.down_blocks, self.gradient_checkpointing):
            sample = gradient_checkpointing(
                down_block,
                sample,
                memory_state=memory_state,
                enabled=self.training and sac,
            )

        # middle
        sample = self.mid_block(sample, memory_state=memory_state)

        # post-process
        sample = causal_norm_wrapper(self.conv_norm_out, sample)
        sample = self.conv_act(sample)
        sample = self.conv_out(sample, memory_state=memory_state)

        return sample


class Decoder3D(nn.Module):
    r"""VAE 3D 解码器，从潜变量重建视频。

    架构：Conv_in → UNetMidBlock3D → [UpDecoderBlock3D × N] → GroupNorm → SiLU → Conv_out
    与编码器对称，上采样使用 pixel shuffle + 因果卷积。
    """

    def __init__(
        self,
        in_channels: int = 3,
        out_channels: int = 3,
        block_out_channels: Tuple[int, ...] = (64,),
        layers_per_block: int = 2,
        inflation_mode: _inflation_mode_t = "tail",
        time_receptive_field: _receptive_field_t = "half",
        temporal_up_num: int = 2,
        slicing_up_num: int = 0,
        selective_checkpointing: Tuple[_selective_checkpointing_t] = ("none",),
    ):
        """初始化3D解码器。

        Args:
            in_channels: 潜变量通道数。
            out_channels: 输出通道数（视频为3）。
            block_out_channels: 各块通道数（编码器顺序）。
            layers_per_block: 每块残差层数（上采样块+1）。
            inflation_mode: 权重膨胀模式。
            time_receptive_field: 时间感受野。
            temporal_up_num: 前N个上采样块进行时序上采样。
            slicing_up_num: 后N个上采样块启用切片模式。
            selective_checkpointing: 梯度检查点策略。
        """
        super().__init__()
        self.layers_per_block = layers_per_block
        self.temporal_up_num = temporal_up_num

        self.conv_in = init_causal_conv3d(
            in_channels,
            block_out_channels[-1],
            kernel_size=3,
            stride=1,
            padding=1,
            inflation_mode=inflation_mode,
        )

        self.up_blocks = nn.ModuleList([])

        # mid
        self.mid_block = UNetMidBlock3D(
            channels=block_out_channels[-1],
            inflation_mode=inflation_mode,
            time_receptive_field=time_receptive_field,
        )

        # up
        reversed_block_out_channels = list(reversed(block_out_channels))
        output_channel = reversed_block_out_channels[0]
        for i in range(len(reversed_block_out_channels)):
            prev_output_channel = output_channel
            output_channel = reversed_block_out_channels[i]

            is_final_block = i == len(block_out_channels) - 1
            is_temporal_up_block = i < self.temporal_up_num
            is_slicing_up_block = i >= len(block_out_channels) - slicing_up_num

            up_block = UpDecoderBlock3D(
                num_layers=self.layers_per_block + 1,
                in_channels=prev_output_channel,
                out_channels=output_channel,
                add_upsample=not is_final_block,
                temporal_up=is_temporal_up_block,
                slicing=is_slicing_up_block,
                inflation_mode=inflation_mode,
                time_receptive_field=time_receptive_field,
            )
            self.up_blocks.append(up_block)

        # out
        self.conv_norm_out = nn.GroupNorm(
            num_channels=block_out_channels[0], num_groups=32, eps=1e-6
        )
        self.conv_act = nn.SiLU()
        self.conv_out = init_causal_conv3d(
            block_out_channels[0], out_channels, 3, padding=1, inflation_mode=inflation_mode
        )

        assert len(selective_checkpointing) == len(self.up_blocks)
        self.set_gradient_checkpointing(selective_checkpointing)

    def set_gradient_checkpointing(self, checkpointing_types):
        """设置解码器的选择性梯度检查点策略。"""
        gradient_checkpointing = []
        for up_block, sac_type in zip(self.up_blocks, checkpointing_types):
            if sac_type == "coarse":
                gradient_checkpointing.append(True)
            elif sac_type == "fine":
                for n, m in up_block.named_modules():
                    if hasattr(m, "gradient_checkpointing"):
                        m.gradient_checkpointing = True
                        logger.debug(f"set gradient_checkpointing: {n}")
                gradient_checkpointing.append(False)
            else:
                gradient_checkpointing.append(False)
        self.gradient_checkpointing = gradient_checkpointing
        logger.info(f"[Decoder3D] gradient_checkpointing: {checkpointing_types}")

    def forward(self, sample: torch.FloatTensor, memory_state: MemoryState) -> torch.FloatTensor:
        r"""解码器前向传播。

        Args:
            sample: 潜变量 [B, latent_channels, T_lat, H_lat, W_lat]。
            memory_state: 因果记忆状态。

        Returns:
            重建视频 [B, C, T, H, W]。
        """
        sample = self.conv_in(sample, memory_state=memory_state)

        # middle
        sample = self.mid_block(sample, memory_state=memory_state)

        # up
        for up_block, sac in zip(self.up_blocks, self.gradient_checkpointing):
            sample = gradient_checkpointing(
                up_block,
                sample,
                memory_state=memory_state,
                enabled=self.training and sac,
            )

        # post-process
        sample = causal_norm_wrapper(self.conv_norm_out, sample)
        sample = self.conv_act(sample)
        sample = self.conv_out(sample, memory_state=memory_state)

        return sample


class VideoAutoencoderKL(nn.Module):
    """基于 3D 因果卷积的视频变分自编码器（VAE）。

    封装 Encoder3D + quant_conv + Decoder3D + post_quant_conv，
    提供 encode/decode、时序切片推理、空间分块推理、流式处理等高层接口。
    默认配置 (s8_c16_t4)：空间压缩16x、时序压缩8x、潜变量16通道。

    Attributes:
        spatial_downsample_factor: 空间下采样总因子。
        temporal_downsample_factor: 时序下采样总因子。
        use_slicing: 是否启用时序切片推理。
        slicing_sample_min_size: 切片编码的最小时序长度。
        slicing_latent_min_size: 切片解码的最小时序长度。
    """

    def __init__(
        self,
        in_channels: int = 3,
        out_channels: int = 3,
        block_out_channels: Tuple[int] = (64,),
        layers_per_block: int = 1,
        latent_channels: int = 4,
        use_quant_conv: bool = True,
        use_post_quant_conv: bool = True,
        enc_selective_checkpointing: Tuple[_selective_checkpointing_t] = ("none",),
        dec_selective_checkpointing: Tuple[_selective_checkpointing_t] = ("none",),
        temporal_scale_num: int = 3,
        slicing_up_num: int = 0,
        inflation_mode: _inflation_mode_t = "tail",
        time_receptive_field: _receptive_field_t = "half",
        slicing_sample_min_size: int = None,
        spatial_downsample_factor: int = 16,
        temporal_downsample_factor: int = 8,
        freeze_encoder: bool = False,
    ):
        """初始化 VideoAutoencoderKL。

        Args:
            in_channels: 输入视频通道数。
            out_channels: 输出视频通道数。
            block_out_channels: 各层通道配置。
            layers_per_block: 每块残差层数。
            latent_channels: 潜变量通道数。
            use_quant_conv: 编码器后是否用 1x1 conv 处理后验参数。
            use_post_quant_conv: 解码器前是否用 1x1 conv 处理潜变量。
            enc_selective_checkpointing: 编码器梯度检查点配置。
            dec_selective_checkpointing: 解码器梯度检查点配置。
            temporal_scale_num: 时序下/上采样块数量。
            slicing_up_num: 切片上采样块数量。
            inflation_mode: 权重膨胀模式。
            time_receptive_field: 时间感受野类型。
            slicing_sample_min_size: 时序切片最小长度。
            spatial_downsample_factor: 空间下采样因子。
            temporal_downsample_factor: 时序下采样因子。
            freeze_encoder: 是否冻结编码器（torch.no_grad）。
        """
        super().__init__()
        self.spatial_downsample_factor = spatial_downsample_factor
        self.temporal_downsample_factor = temporal_downsample_factor
        self.freeze_encoder = freeze_encoder
        if slicing_sample_min_size is None:
            slicing_sample_min_size = temporal_downsample_factor
        self.slicing_sample_min_size = slicing_sample_min_size
        self.slicing_latent_min_size = slicing_sample_min_size // (2**temporal_scale_num)

        self.encoder = Encoder3D(
            in_channels=in_channels,
            out_channels=latent_channels,
            block_out_channels=block_out_channels,
            layers_per_block=layers_per_block,
            double_z=True,
            temporal_down_num=temporal_scale_num,
            selective_checkpointing=enc_selective_checkpointing,
            inflation_mode=inflation_mode,
            time_receptive_field=time_receptive_field,
        )

        self.decoder = Decoder3D(
            in_channels=latent_channels,
            out_channels=out_channels,
            block_out_channels=block_out_channels,
            layers_per_block=layers_per_block,
            temporal_up_num=temporal_scale_num,
            slicing_up_num=slicing_up_num,
            selective_checkpointing=dec_selective_checkpointing,
            inflation_mode=inflation_mode,
            time_receptive_field=time_receptive_field,
        )

        self.quant_conv = (
            init_causal_conv3d(
                in_channels=2 * latent_channels,
                out_channels=2 * latent_channels,
                kernel_size=1,
                inflation_mode=inflation_mode,
            )
            if use_quant_conv
            else None
        )
        self.post_quant_conv = (
            init_causal_conv3d(
                in_channels=latent_channels,
                out_channels=latent_channels,
                kernel_size=1,
                inflation_mode=inflation_mode,
            )
            if use_post_quant_conv
            else None
        )

        self.use_slicing = False

    def enable_slicing(self):
        """启用时序切片推理，处理长视频避免OOM。"""
        self.use_slicing = True

    def disable_slicing(self):
        """禁用时序切片推理。"""
        self.use_slicing = False

    def encode(self, x: torch.FloatTensor) -> CausalEncoderOutput:
        """编码视频为潜变量。

        Args:
            x: 输入视频 [B,C,T,H,W] 或 [B,C,H,W]（单帧）。

        Returns:
            CausalEncoderOutput(latent, posterior)，latent 为采样的潜变量，posterior 为后验分布。
        """
        if x.ndim == 4:
            x = x.unsqueeze(2)
        h = self.slicing_encode(x)
        p = DiagonalGaussianDistribution(h)
        z = p.sample()
        return CausalEncoderOutput(z, p)

    def decode(self, z: torch.FloatTensor) -> CausalDecoderOutput:
        """解码潜变量为视频。

        Args:
            z: 潜变量 [B,C,T_lat,H_lat,W_lat] 或 [B,C,H_lat,W_lat]。

        Returns:
            CausalDecoderOutput(sample)，sample 为重建视频。
        """
        if z.ndim == 4:
            z = z.unsqueeze(2)
        x = self.slicing_decode(z)
        return CausalDecoderOutput(x)

    def _encode(self, x: torch.Tensor, memory_state: MemoryState) -> torch.Tensor:
        """单切片编码内部方法。

        序列并行切分 → encoder → quant_conv → 序列并行聚合。
        """
        x = causal_conv_slice_inputs(x, self.slicing_sample_min_size, memory_state=memory_state)
        h = self.encoder(x, memory_state=memory_state)
        h = self.quant_conv(h, memory_state=memory_state) if self.quant_conv is not None else h
        h = causal_conv_gather_outputs(h)
        return h

    def _decode(self, z: torch.Tensor, memory_state: MemoryState) -> torch.Tensor:
        """单切片解码内部方法。

        序列并行切分 → post_quant_conv → decoder → 序列并行聚合。
        """
        z = causal_conv_slice_inputs(z, self.slicing_latent_min_size, memory_state=memory_state)
        z = (
            self.post_quant_conv(z, memory_state=memory_state)
            if self.post_quant_conv is not None
            else z
        )
        x = self.decoder(z, memory_state=memory_state)
        x = causal_conv_gather_outputs(x)
        return x

    def slicing_encode(self, x: torch.Tensor) -> torch.Tensor:
        """时序切片编码。

        当视频长度超过 slicing_sample_min_size * sp_size 时，沿时间维切片：
        - 第一片：首帧+第一个切片（INITIALIZING状态，重复首帧填充）。
        - 后续片：仅当前切片（ACTIVE状态，使用memory缓存前序帧）。
        - 否则：直接编码（DISABLED状态）。

        Args:
            x: 输入视频 [B,C,T,H,W]。

        Returns:
            编码结果 [B,2*latent_channels,T_lat,H_lat,W_lat]。
        """
        sp_size = get_sequence_parallel_world_size()
        if self.use_slicing and (x.shape[2] - 1) > self.slicing_sample_min_size * sp_size:
            x_slices = x[:, :, 1:].split(split_size=self.slicing_sample_min_size * sp_size, dim=2)
            encoded_slices = [
                self._encode(
                    torch.cat((x[:, :, :1], x_slices[0]), dim=2),
                    memory_state=MemoryState.INITIALIZING,
                )
            ]
            for x_idx in range(1, len(x_slices)):
                encoded_slices.append(
                    self._encode(x_slices[x_idx], memory_state=MemoryState.ACTIVE)
                )
            return torch.cat(encoded_slices, dim=2)
        else:
            return self._encode(x, memory_state=MemoryState.DISABLED)

    def slicing_decode(self, z: torch.Tensor) -> torch.Tensor:
        """时序切片解码，与 slicing_encode 对称。

        Args:
            z: 潜变量 [B,C,T_lat,H_lat,W_lat]。

        Returns:
            重建视频 [B,C,T,H,W]。
        """
        sp_size = get_sequence_parallel_world_size()
        if self.use_slicing and (z.shape[2] - 1) > self.slicing_latent_min_size * sp_size:
            z_slices = z[:, :, 1:].split(split_size=self.slicing_latent_min_size * sp_size, dim=2)
            decoded_slices = [
                self._decode(
                    torch.cat((z[:, :, :1], z_slices[0]), dim=2),
                    memory_state=MemoryState.INITIALIZING,
                )
            ]
            for z_idx in range(1, len(z_slices)):
                decoded_slices.append(
                    self._decode(z_slices[z_idx], memory_state=MemoryState.ACTIVE)
                )
            return torch.cat(decoded_slices, dim=2)
        else:
            return self._decode(z, memory_state=MemoryState.DISABLED)

    def forward(self, x: torch.FloatTensor) -> CausalAutoencoderOutput:
        """VAE 前向：编码 → 采样 → 解码（端到端重建）。

        Args:
            x: 输入视频。

        Returns:
            CausalAutoencoderOutput(sample, latent, posterior)。
        """
        with torch.no_grad() if self.freeze_encoder else nullcontext():
            z, p = self.encode(x)
        x = self.decode(z).sample
        return CausalAutoencoderOutput(x, z, p)

    def preprocess(self, x: torch.Tensor):
        """输入预处理，验证时序长度约束。

        Args:
            x: 输入 [B,C,T,H,W] 或 [B,C,H,W]。

        Returns:
            输入张量（验证后）。
        """
        assert x.ndim == 4 or x.size(2) % self.temporal_downsample_factor == 1
        return x

    def postprocess(self, x: torch.Tensor):
        """输出后处理（占位）。"""
        return x

    def set_causal_slicing(
        self,
        *,
        split_size: Optional[int],
        memory_device: _memory_device_t,
    ):
        """配置因果切片推理参数。

        Args:
            split_size: 时间维切片大小，None 禁用切片。
            memory_device: 记忆缓存设备（None时split_size也必须为None）。
        """
        assert (
            split_size is None or memory_device is not None
        ), "if split_size is set, memory_device must not be None."
        if split_size is not None:
            self.enable_slicing()
            self.slicing_sample_min_size = split_size
            self.slicing_latent_min_size = split_size // self.temporal_downsample_factor
        else:
            self.disable_slicing()
        for module in self.modules():
            if isinstance(module, InflatedCausalConv3d):
                module.set_memory_device(memory_device)

    def set_memory_limit(self, conv_max_mem: Optional[float], norm_max_mem: Optional[float]):
        """设置卷积和归一化的显存限制。

        Args:
            conv_max_mem: 单卷积最大显存（GiB），None 表示无限制。
            norm_max_mem: GroupNorm 分片阈值（GiB），None 表示无限制。
        """
        set_norm_limit(norm_max_mem)
        for m in self.modules():
            if isinstance(m, InflatedCausalConv3d):
                m.set_memory_limit(conv_max_mem if conv_max_mem is not None else float("inf"))


class VideoAutoencoderKLWrapper(VideoAutoencoderKL):
    """VideoAutoencoderKL 的简化包装器，提供适配外部调用的 encode/decode 接口。

    处理4D/5D张量自动转换，squeeze/unsqueeze时间维度。
    """

    def __init__(
        self, *args, spatial_downsample_factor: int, temporal_downsample_factor: int, **kwargs
    ):
        self.spatial_downsample_factor = spatial_downsample_factor
        self.temporal_downsample_factor = temporal_downsample_factor
        super().__init__(*args, **kwargs)

    def forward(self, x) -> CausalAutoencoderOutput:
        z, _, p = self.encode(x)
        x, _ = self.decode(z)
        return CausalAutoencoderOutput(x, z, None, p)

    def encode(self, x) -> CausalEncoderOutput:
        if x.ndim == 4:
            x = x.unsqueeze(2)
        p = super().encode(x).latent_dist
        z = p.sample().squeeze(2)
        return CausalEncoderOutput(z, None, p)

    def decode(self, z) -> CausalDecoderOutput:
        if z.ndim == 4:
            z = z.unsqueeze(2)
        x = super().decode(z).sample.squeeze(2)
        return CausalDecoderOutput(x, None)

    def preprocess(self, x):
        assert x.ndim == 4 or x.size(2) % 4 == 1
        return x

    def postprocess(self, x):
        return x

    def set_causal_slicing(
        self,
        *,
        split_size: Optional[int],
        memory_device: Optional[Literal["cpu", "same"]],
    ):
        assert (
            split_size is None or memory_device is not None
        ), "if split_size is set, memory_device must not be None."
        if split_size is not None:
            self.enable_slicing()
        else:
            self.disable_slicing()
        self.slicing_sample_min_size = split_size
        if split_size is not None:
            self.slicing_latent_min_size = split_size // self.temporal_downsample_factor
        for module in self.modules():
            if isinstance(module, InflatedCausalConv3d):
                module.set_memory_device(memory_device)

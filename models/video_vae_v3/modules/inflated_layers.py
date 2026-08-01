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

"""膨胀因果3D卷积层（基础版）。

定义 InflatedCausalConv3d 类，继承自 nn.Conv3d，实现因果卷积逻辑：
- 移除时间维度的padding，通过运行时缓存前序帧实现因果性。
- 支持从2D卷积checkpoint自动膨胀权重（replicate/tail模式）。
- 支持流式推理的记忆缓存（可卸载到CPU）。

此为基础实现，完整版（含内存限制分片和序列并行）见 causal_inflation_lib.py。
"""

from functools import partial
from typing import Literal

from torch import Tensor
from torch.nn import Conv3d

from models.video_vae_v3.modules.inflated_lib import (
    MemoryState,
    extend_head,
    inflate_bias,
    inflate_weight,
    modify_state_dict,
)

_inflation_mode_t = Literal["none", "tail", "replicate"]
_memory_device_t = Literal["cpu", "same"] | None


class InflatedCausalConv3d(Conv3d):
    """膨胀因果3D卷积层。

    将标准 nn.Conv3d 修改为因果卷积：时间维度上不使用未来帧的信息。
    实现方式是移除时间维度的零填充，改为在 forward 时自动重复首帧或使用
    缓存的前序帧作为前缀输入，保证输出 t 时刻仅依赖 [0, t] 时刻的输入。

    支持从 2D 卷积权重自动膨胀初始化（兼容图像 VAE checkpoint 迁移到视频 VAE）。

    Attributes:
        inflation_mode: 权重膨胀模式。
        temporal_padding: 时间维度填充长度 = kernel_size[0] - 1。
        memory: 流式推理的缓存帧。
        memory_device: 缓存存储设备。
    """

    def __init__(
        self,
        *args,
        inflation_mode: _inflation_mode_t,
        memory_device: _memory_device_t = "same",
        **kwargs,
    ):
        """初始化因果3D卷积层。

        Args:
            *args: 传递给 nn.Conv3d 的位置参数。
            inflation_mode: 权重膨胀模式（'none'/'tail'/'replicate'）。
            memory_device: 缓存设备，'cpu' 卸载到CPU，'same' 保留在GPU。
            **kwargs: 传递给 nn.Conv3d 的关键字参数。
        """
        self.inflation_mode = inflation_mode
        self.memory = None
        super().__init__(*args, **kwargs)
        self.temporal_padding = self.padding[0]
        self.memory_device = memory_device
        self.padding = (0, *self.padding[1:])  # Remove temporal pad to keep causal.

    def set_memory_device(self, memory_device: _memory_device_t):
        """设置记忆缓存的存储设备。

        Args:
            memory_device: 'cpu' 将缓存卸载到CPU以节省GPU显存；
                'same' 保留在与输入相同的GPU设备上。
        """
        self.memory_device = memory_device

    def forward(self, input: Tensor, memory_state: MemoryState = MemoryState.DISABLED) -> Tensor:
        """因果3D卷积前向传播。

        根据 memory_state 决定输入填充方式：
        - DISABLED/INITIALIZING：重复首帧 temporal_padding*2 次作为填充。
        - ACTIVE：使用 self.memory 中缓存的前序帧拼接输入，保证时序连续。

        卷积完成后，保存输出尾部的若干帧作为下一次调用的记忆。

        Args:
            input: 输入张量 [B, C, T, H, W]。
            memory_state: 记忆状态，控制填充和缓存行为。

        Returns:
            Tensor: 卷积输出 [B, Cout, T_out, H_out, W_out]。
        """
        mem_size = self.stride[0] - self.kernel_size[0]
        if (self.memory is not None) and (memory_state == MemoryState.ACTIVE):
            input = extend_head(input, memory=self.memory)
        else:
            input = extend_head(input, times=self.temporal_padding * 2)
        memory = input[:, :, mem_size:].detach() if (mem_size != 0 and memory_state != MemoryState.DISABLED) else None
        if memory_state != MemoryState.DISABLED and not self.training and (self.memory_device is not None):
            self.memory = memory
            if self.memory_device == "cpu" and self.memory is not None:
                self.memory = self.memory.to("cpu")
        return super().forward(input)

    def _load_from_state_dict(
        self, state_dict, prefix, local_metadata, strict, missing_keys, unexpected_keys, error_msgs
    ):
        """加载state_dict时自动膨胀2D权重到3D。

        重写PyTorch的加载钩子，当检测到4D权重（2D卷积格式）时，
        自动调用 modify_state_dict 膨胀为5D（3D卷积格式）后再加载。

        Args:
            state_dict: 待加载的状态字典。
            prefix: 参数名前缀。
            local_metadata: 本地元数据。
            strict: 是否严格匹配键名。
            missing_keys: 缺失键列表（输出参数）。
            unexpected_keys: 多余键列表（输出参数）。
            error_msgs: 错误消息列表（输出参数）。
        """
        if self.inflation_mode != "none":
            state_dict = modify_state_dict(
                self,
                state_dict,
                prefix,
                inflate_weight_fn=partial(inflate_weight, position="tail"),
                inflate_bias_fn=partial(inflate_bias, position="tail"),
            )
        super()._load_from_state_dict(
            state_dict,
            prefix,
            local_metadata,
            (strict and self.inflation_mode == "none"),
            missing_keys,
            unexpected_keys,
            error_msgs,
        )


def init_causal_conv3d(
    *args,
    inflation_mode: _inflation_mode_t,
    **kwargs,
):
    """初始化因果3D卷积层的工厂函数。

    Args:
        *args: 传递给 InflatedCausalConv3d 的位置参数。
        inflation_mode: 权重膨胀模式：
            - 'none': 不进行膨胀，state_dict加载使用默认逻辑。
            - 'tail': 将2D权重放在时间核最后一个位置（等价于'tail'位置填充）。
            - 'replicate': 复制2D权重并平均到时间核各位置。
        **kwargs: 传递给 InflatedCausalConv3d 的关键字参数。

    Returns:
        InflatedCausalConv3d: 初始化后的因果3D卷积层。
    """
    return InflatedCausalConv3d(*args, inflation_mode=inflation_mode, **kwargs)

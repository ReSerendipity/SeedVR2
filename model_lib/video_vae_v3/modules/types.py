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

"""Video VAE v3 类型定义模块。

定义 VAE 模型使用的核心类型别名、状态枚举、数据分布类和输出数据结构，
包括高斯分布参数化、记忆状态机、编码器/解码器输出 NamedTuple 等。
"""

from enum import Enum
from typing import Literal, NamedTuple

import torch

_receptive_field_t = Literal["half", "full"]
"""时序感受野类型：'half' 表示卷积核仅在空间维度膨胀，时序维度为1；'full' 表示时空维度均为3。"""

_inflation_mode_t = Literal["none", "tail", "replicate"]
"""2D->3D 权重膨胀模式：'none' 不膨胀（原生3D权重）；'tail' 将2D权重放在时间核尾部；'replicate' 复制2D权重并平均。"""

_memory_device_t = Literal["cpu", "same"] | None
"""缓存设备类型：'cpu' 将时序记忆卸载到CPU；'same' 保留在GPU；None 表示不使用记忆缓存。"""

_gradient_checkpointing_t = Literal["half", "full"] | None
"""梯度检查点类型（预留）。"""

_selective_checkpointing_t = Literal["coarse", "fine"] | None
"""选择性梯度检查点类型：'coarse' 块级检查点；'fine' 模块级检查点；None 禁用。"""


class DiagonalGaussianDistribution:
    """对角高斯分布，用于VAE的重参数化技巧。

    将编码器输出的均值和对数方差参数化为高斯分布 N(μ, σ²)，
    支持采样、取众数和计算KL散度。

    Attributes:
        mean (torch.Tensor): 分布均值 μ。
        logvar (torch.Tensor): 对数方差 log(σ²)，被裁剪到 [-30, 20] 以避免数值不稳定。
        std (torch.Tensor): 标准差 σ = exp(0.5 * logvar)。
        var (torch.Tensor): 方差 σ² = exp(logvar)。
    """

    def __init__(self, mean: torch.Tensor, logvar: torch.Tensor):
        """初始化对角高斯分布。

        Args:
            mean: 均值张量，任意形状。
            logvar: 对数方差张量，与 mean 同形状。
        """
        self.mean = mean
        self.logvar = torch.clamp(logvar, -30.0, 20.0)
        self.std = torch.exp(0.5 * self.logvar)
        self.var = torch.exp(self.logvar)

    def mode(self) -> torch.Tensor:
        """返回分布的众数（即均值），用于确定性推理。

        Returns:
            torch.Tensor: 均值 μ，与输入同形状。
        """
        return self.mean

    def sample(self) -> torch.FloatTensor:
        """使用重参数化技巧从分布中采样。

        采样公式：z = μ + σ * ε，其中 ε ~ N(0, I)。
        梯度可通过重参数化传回编码器。

        Returns:
            torch.FloatTensor: 采样的潜变量 z = μ + σ * randn_like(μ)。
        """
        return self.mean + self.std * torch.randn_like(self.mean)

    def kl(self) -> torch.Tensor:
        """计算与标准正态分布 N(0, I) 的 KL 散度。

        KL(N(μ,σ²) || N(0,I)) = 0.5 * Σ(μ² + σ² - 1 - log(σ²))，
        对除batch维度外的所有维度求和。

        Returns:
            torch.Tensor: 每个样本的 KL 散度值，形状为 [batch_size]。
        """
        return 0.5 * torch.sum(
            self.mean**2 + self.var - 1.0 - self.logvar,
            dim=list(range(1, self.mean.ndim)),
        )


class MemoryState(Enum):
    """因果卷积记忆状态枚举，控制流式处理中的缓存行为。

    状态机流转：DISABLED → INITIALIZING → ACTIVE（循环）→ DISABLED。

    Attributes:
        DISABLED: 不启用记忆缓存，用于一次性处理完整序列。
        INITIALIZING: 正在处理第一个切片，需要初始化/重置记忆库，对首帧重复填充。
        ACTIVE: 记忆库中已有历史数据，使用缓存的前序帧特征进行因果卷积。
        UNSET: 错误状态，表示调用方未传入正确的记忆状态。
    """

    DISABLED = 0
    INITIALIZING = 1
    ACTIVE = 2
    UNSET = 3


class QuantizerOutput(NamedTuple):
    """量化器输出结构。

    Attributes:
        latent: 量化后的潜变量张量。
        extra_loss: 量化带来的额外损失（如承诺损失）。
        statistics: 量化统计信息字典。
    """

    latent: torch.Tensor
    extra_loss: torch.Tensor
    statistics: dict[str, torch.Tensor]


class CausalAutoencoderOutput(NamedTuple):
    """因果自编码器完整输出结构。

    Attributes:
        sample: 重建的输出样本（视频帧）。
        latent: 潜变量表示 z。
        posterior: 后验分布 q(z|x)，可用于计算 KL 损失。
    """

    sample: torch.Tensor
    latent: torch.Tensor
    posterior: DiagonalGaussianDistribution | None


class CausalEncoderOutput(NamedTuple):
    """因果编码器输出结构。

    Attributes:
        latent: 编码后的潜变量（已采样）。
        posterior: 后验分布 q(z|x)。
    """

    latent: torch.Tensor
    posterior: DiagonalGaussianDistribution | None


class CausalDecoderOutput(NamedTuple):
    """因果解码器输出结构。

    Attributes:
        sample: 解码重建的样本。
    """

    sample: torch.Tensor

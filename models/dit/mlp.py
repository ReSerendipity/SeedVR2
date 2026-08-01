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

"""MLP (多层感知机) 子模块。

提供 DiT Transformer 块中的前馈网络 (Feed-Forward Network, FFN) 实现，包括：

- **MLP**: 标准两层 MLP，结构为 Linear -> GELU -> Linear，是 Transformer 的经典 FFN 实现。
- **SwiGLUMLP**: SwiGLU 门控 MLP 变体，使用 SwiGLU 激活函数替代标准 GELU，
  在 LLaMA 等现代大语言模型中被广泛采用，性能通常优于标准 GELU。
- **get_mlp**: 工厂函数，根据类型字符串返回对应的 MLP 类。

MLP 算法:
    标准 Transformer FFN::

        FFN(x) = Linear2(GELU(Linear1(x)))

    其中 expand_ratio 控制隐藏层扩展倍数，通常为 4。

SwiGLU 算法:
    SwiGLU (Sigmoid-Gated Linear Unit) 通过门控机制增强表达能力::

        SwiGLU(x) = Linear_out(SiLU(Linear_gate(x)) * Linear(x))

    隐藏层维度计算为 hidden = int(2 * dim * expand_ratio / 3)，
    并对齐到 multiple_of (通常为 256) 以优化 GPU 计算效率。
"""

import torch
import torch.nn.functional as F
from torch import nn


def get_mlp(mlp_type: str | None = "normal"):
    """根据类型字符串返回对应的 MLP 类。

    Args:
        mlp_type (Optional[str]): MLP 类型，支持 "normal" (标准 MLP) 和 "swiglu" (SwiGLU MLP)。
            默认为 "normal"。

    Returns:
        Type[nn.Module]: MLP 类对象（未实例化）。

    Raises:
        无显式异常，但传入不支持的类型会在调用方导致后续错误。
    """
    if mlp_type == "normal":
        return MLP
    elif mlp_type == "swiglu":
        return SwiGLUMLP


class MLP(nn.Module):
    """标准两层 MLP：Linear -> GELU -> Linear。

    这是 Transformer 架构中最经典的前馈网络实现，使用 tanh 近似的 GELU 激活函数。

    Args:
        dim (int): 输入和输出的特征维度。
        expand_ratio (int): 隐藏层扩展倍数，隐藏层维度为 dim * expand_ratio，通常为 4。

    Attributes:
        proj_in (nn.Linear): 输入投影层，dim -> dim*expand_ratio。
        act (nn.GELU): GELU 激活函数，使用 tanh 近似 (approximate="tanh")。
        proj_out (nn.Linear): 输出投影层，dim*expand_ratio -> dim。
    """

    def __init__(
        self,
        dim: int,
        expand_ratio: int,
    ):
        super().__init__()
        self.proj_in = nn.Linear(dim, dim * expand_ratio)
        self.act = nn.GELU("tanh")
        self.proj_out = nn.Linear(dim * expand_ratio, dim)

    def forward(self, x: torch.FloatTensor) -> torch.FloatTensor:
        """前向传播，执行标准两层 MLP 计算。

        Args:
            x (torch.FloatTensor): 输入张量，形状为 (..., dim)。

        Returns:
            torch.FloatTensor: 输出张量，形状与输入相同为 (..., dim)。
        """
        x = self.proj_in(x)
        x = self.act(x)
        x = self.proj_out(x)
        return x


class SwiGLUMLP(nn.Module):
    """SwiGLU 门控 MLP 变体，使用 SwiGLU 激活替代标准 GELU。

    SwiGLU (Sigmoid-Gated Linear Unit) 是一种门控线性单元变体，
    通过 SiLU 激活的门控分支与线性分支逐元素相乘，再投影回输出维度。
    该结构在 LLaMA、PaLM 等模型中被验证有更好的性能表现。

    Args:
        dim (int): 输入和输出的特征维度。
        expand_ratio (int): 扩展倍数，隐藏层维度按 2*dim*expand_ratio/3 计算。
        multiple_of (int): 隐藏层维度对齐基数，默认为 256，确保维度是该值的倍数以提升 GPU 效率。

    Attributes:
        proj_in_gate (nn.Linear): 门控分支投影，dim -> hidden_dim，无偏置。
        proj_in (nn.Linear): 数值分支投影，dim -> hidden_dim，无偏置。
        proj_out (nn.Linear): 输出投影，hidden_dim -> dim，无偏置。

    Note:
        所有线性层均不使用偏置 (bias=False)，这是 SwiGLU 的常见配置。
    """

    def __init__(
        self,
        dim: int,
        expand_ratio: int,
        multiple_of: int = 256,
    ):
        super().__init__()
        hidden_dim = int(2 * dim * expand_ratio / 3)
        hidden_dim = multiple_of * ((hidden_dim + multiple_of - 1) // multiple_of)
        self.proj_in_gate = nn.Linear(dim, hidden_dim, bias=False)
        self.proj_out = nn.Linear(hidden_dim, dim, bias=False)
        self.proj_in = nn.Linear(dim, hidden_dim, bias=False)

    def forward(self, x: torch.FloatTensor) -> torch.FloatTensor:
        """前向传播，执行 SwiGLU 门控 MLP 计算。

        Args:
            x (torch.FloatTensor): 输入张量，形状为 (..., dim)。

        Returns:
            torch.FloatTensor: 输出张量，形状为 (..., dim)。
        """
        x = self.proj_out(F.silu(self.proj_in_gate(x)) * self.proj_in(x))
        return x

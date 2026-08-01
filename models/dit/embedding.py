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

"""嵌入层模块。

提供 DiT 所需的各类嵌入实现，主要包括：

- **TimeEmbedding**: 扩散时间步嵌入层，将标量时间步 t ∈ [0, 1000] 转换为高维特征向量，
  用于条件调制 Transformer 块的归一化层。

时间步编码算法:
    采用正弦位置编码 (Sinusoidal Positional Encoding)，原始公式来自 Transformer 论文::

        PE(pos, 2i) = sin(pos / 10000^(2i/d))
        PE(pos, 2i+1) = cos(pos / 10000^(2i/d))

    之后通过两层 MLP 投影到目标维度，使用 SiLU (Sigmoid Linear Unit) 激活函数。
    时间步嵌入为去噪过程提供条件信息，让模型知道当前处于扩散过程的哪个阶段。
"""

import torch
from diffusers.models.embeddings import get_timestep_embedding
from torch import nn


def emb_add(emb1: torch.Tensor, emb2: torch.Tensor | None):
    """安全地将两个嵌入张量相加，处理 emb2 为 None 的情况。

    Args:
        emb1 (torch.Tensor): 第一个嵌入张量，非空。
        emb2 (Optional[torch.Tensor]): 第二个嵌入张量，可以为 None。

    Returns:
        torch.Tensor: 若 emb2 为 None 则返回 emb1，否则返回 emb1 + emb2。
    """
    return emb1 if emb2 is None else emb1 + emb2


class TimeEmbedding(nn.Module):
    """时间步嵌入层，将扩散时间步转换为高维特征向量。

    使用正弦位置编码生成基础嵌入，再通过两层 MLP 进行非线性投影，最终输出
    用于自适应层归一化 (AdaLN) 的条件嵌入。

    Args:
        sinusoidal_dim (int): 正弦编码的维度，通常为 256。
        hidden_dim (int): MLP 隐藏层维度，通常为 max(vid_dim, txt_dim)。
        output_dim (int): 输出嵌入维度，需为 Transformer 维度的 6 倍 (AdaLN-Zero 需要 6 组参数)。

    Attributes:
        sinusoidal_dim (int): 正弦编码维度。
        proj_in (nn.Linear): 输入投影层，sinusoidal_dim -> hidden_dim。
        proj_hid (nn.Linear): 隐藏层投影，hidden_dim -> hidden_dim。
        proj_out (nn.Linear): 输出投影层，hidden_dim -> output_dim。
        act (nn.SiLU): SiLU 激活函数。
    """

    def __init__(
        self,
        sinusoidal_dim: int,
        hidden_dim: int,
        output_dim: int,
    ):
        super().__init__()
        self.sinusoidal_dim = sinusoidal_dim
        self.proj_in = nn.Linear(sinusoidal_dim, hidden_dim)
        self.proj_hid = nn.Linear(hidden_dim, hidden_dim)
        self.proj_out = nn.Linear(hidden_dim, output_dim)
        self.act = nn.SiLU()

    def forward(
        self,
        timestep: int | float | torch.IntTensor | torch.FloatTensor,
        device: torch.device,
        dtype: torch.dtype,
    ) -> torch.FloatTensor:
        """前向传播，计算时间步嵌入。

        Args:
            timestep (Union[int, float, torch.IntTensor, torch.FloatTensor]):
                扩散时间步，可以是标量或形状为 (batch,) 的张量。
            device (torch.device): 输出张量所在设备。
            dtype (torch.dtype): 输出张量的数据类型。

        Returns:
            torch.FloatTensor: 时间步嵌入，形状为 (batch, output_dim)。
        """
        if not torch.is_tensor(timestep):
            timestep = torch.tensor([timestep], device=device, dtype=dtype)
        if timestep.ndim == 0:
            timestep = timestep[None]

        emb = get_timestep_embedding(
            timesteps=timestep,
            embedding_dim=self.sinusoidal_dim,
            flip_sin_to_cos=False,
            downscale_freq_shift=0,
        )
        emb = emb.to(dtype)
        emb = self.proj_in(emb)
        emb = self.act(emb)
        emb = self.proj_hid(emb)
        emb = self.act(emb)
        emb = self.proj_out(emb)
        return emb

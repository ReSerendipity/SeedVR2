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

"""时间步嵌入模块。

提供扩散模型的时间步嵌入实现：

- **TimeEmbedding**: 使用正弦位置编码 + 三层 MLP（SiLU 激活）将扩散时间步映射到
  高维条件向量，用于 AdaLN-Zero 自适应调制。
- **emb_add**: 辅助函数，将两个嵌入向量相加（支持 None）。

正弦时间步编码:
    与原始 Transformer 的位置编码类似，扩散时间步 t 通过不同频率的正弦/余弦函数
    编码为向量::

        PE(t, 2i)   = sin(t / 10000^(2i/d))
        PE(t, 2i+1) = cos(t / 10000^(2i/d))

    与 v1 版本不同，v2 使用 diffusers 库的 ``get_timestep_embedding`` 并通过
    三层 MLP（proj_in -> SiLU -> proj_hid -> SiLU -> proj_out）投影，
    而非 v1 的两层 MLP。
"""

from typing import Optional, Union
import torch
from diffusers.models.embeddings import get_timestep_embedding
from torch import nn


def emb_add(emb1: torch.Tensor, emb2: Optional[torch.Tensor]):
    """将两个嵌入向量相加，emb2 为 None 时返回 emb1。

    Args:
        emb1 (torch.Tensor): 第一个嵌入。
        emb2 (Optional[torch.Tensor]): 第二个嵌入，可为 None。

    Returns:
        torch.Tensor: emb1 + emb2 或 emb1。
    """
    return emb1 if emb2 is None else emb1 + emb2


class TimeEmbedding(nn.Module):
    """时间步嵌入层，正弦编码 + 三层 SiLU MLP。

    Args:
        sinusoidal_dim (int): 正弦编码的维度，通常为 256。
        hidden_dim (int): MLP 隐藏层维度。
        output_dim (int): 最终输出维度（即 AdaLN 的 emb_dim，通常为 6*dim）。

    Attributes:
        sinusoidal_dim (int): 正弦编码维度。
        proj_in (nn.Linear): 第一层线性投影。
        proj_hid (nn.Linear): 隐藏层线性投影。
        proj_out (nn.Linear): 输出层线性投影。
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
        timestep: Union[int, float, torch.IntTensor, torch.FloatTensor],
        device: torch.device,
        dtype: torch.dtype,
    ) -> torch.FloatTensor:
        """前向传播，生成时间步嵌入。

        Args:
            timestep: 扩散时间步，可以是标量 int/float 或张量。
            device (torch.device): 输出张量所在设备。
            dtype (torch.dtype): 输出张量数据类型。

        Returns:
            torch.FloatTensor: 时间步嵌入，形状 (b, output_dim)。
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

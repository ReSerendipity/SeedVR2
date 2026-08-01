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

"""DiT (Diffusion Transformer) 模型包。

提供两种视频扩散 Transformer 架构的实现：

- **标准 DiT (dit blocks)**: 固定分辨率版本，使用窗口注意力 + 多模态 (MM-DiT) 架构。
- **NaDiT (Native Resolution DiT)**: 原生分辨率版本，支持变长序列、任意分辨率输入，
  使用 Flash Attention v2 变长 API，无需 padding/crop。

子模块结构:
    - attention.py: 注意力机制（Torch 标准注意力、Flash Attention 变长）
    - embedding.py: 时间步嵌入（正弦编码 + MLP）
    - mlp.py: 前馈网络（标准 MLP、SwiGLU MLP）
    - mm.py: 多模态包装（视频/文本双分支）
    - modulation.py: AdaLN-Zero 自适应调制层
    - normalization.py: 归一化层工厂（LayerNorm、RMSNorm、FusedNorm）
    - patch.py: 3D Patch 嵌入/恢复
    - rope.py: 3D 旋转位置编码 (RoPE)
    - window.py: 时空窗口划分/逆变换
    - na.py: 变长序列处理工具
    - nadit.py: NaDiT 主模型定义
    - blocks/: 标准 DiT 的 Transformer block
    - nablocks/: NaDiT 的 Transformer block

DiT 架构概述:
    DiT (Diffusion Transformer) 将 Transformer 架构用于扩散模型的噪声预测，
    核心创新是 AdaLN-Zero：通过扩散时间步嵌入自适应调制每个 Transformer 层的
    归一化和残差连接，替代传统的 cross-attention 条件注入方式。

    视频 DiT 将视频划分为 3D patch，添加时间步和文本条件，通过多层 Transformer block
    处理后预测噪声。窗口注意力 (Window Attention) 通过局部窗口划分降低长序列的
    O(n^2) 注意力复杂度到 O(n * w^2)。

NaDiT 架构改进:
    标准 DiT 要求固定分辨率输入，NaDiT 通过以下改进支持任意分辨率：
    1. 使用 Flash Attention v2 的 cu_seqlens 变长 API 处理不同长度序列
    2. RoPE 位置编码根据实际 t/h/w 动态生成
    3. Patch 嵌入/恢复支持不同尺寸，通过累积长度索引
    4. 窗口划分通过索引映射而非 reshape 实现，支持非均匀尺寸
"""

from .blocks import get_block
from .nablocks import get_nablock
from .nadit import NaDiT, NaDiTConfig

__all__ = ["get_block", "get_nablock", "NaDiT", "NaDiTConfig"]

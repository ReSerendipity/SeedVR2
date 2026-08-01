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

"""NaDiT v2 (Native Resolution Diffusion Transformer v2) 模型包。

相比 v1 的主要改进:
    - 支持多种 RoPE 类型（pixel 频率 RoPE、多模态 MM-RoPE）
    - 720p 自适应窗口划分（根据输入分辨率动态计算窗口大小）
    - 支持移位窗口 (Shifted Window) 注意力以增强跨窗口信息交互
    - 支持多个文本输入（列表形式的文本嵌入）
    - 最后一层支持 vid_only 模式（文本分支不再计算）
    - 使用 rotary_embedding_torch 库实现 RoPE
    - 更灵活的 MLP/QKV 权重共享配置（前 N 层共享，后续独立）
    - 可选梯度检查点支持训练

子模块结构:
    - attention.py: 注意力机制（Torch SDPA、Flash Attention 变长）
    - embedding.py: 时间步嵌入（正弦编码 + 3 层 MLP）
    - mlp.py: 前馈网络（标准 MLP、SwiGLU MLP）
    - mm.py: 多模态包装（vid/txt 双分支，支持 vid_only 模式）
    - modulation.py: AdaLN-Zero 自适应调制层（支持 in/out 模式独立配置）
    - normalization.py: 归一化层工厂（LayerNorm、RMSNorm、FusedNorm）
    - rope.py: 旋转位置编码（3D 视频 RoPE、多模态 MM-RoPE）
    - window.py: 720p 自适应窗口划分函数（常规窗口 + 移位窗口）
    - na.py: 变长序列处理工具（flatten/unflatten、concat/window/pack 等）
    - nadit.py: NaDiT v2 主模型定义
    - patch/: Patch 嵌入/还原（支持因果时序 padding）
    - nablocks/: NaDiT v2 Transformer block（全局注意力、窗口注意力）
"""

from .nablocks import get_nablock
from .nadit import NaDiT, NaDiTOutput

__all__ = ["get_nablock", "NaDiT", "NaDiTOutput"]

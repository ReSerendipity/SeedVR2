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

"""Video VAE v3 核心组件模块包。

包含构建 Causal Video VAE（基于3D因果卷积的视频变分自编码器）的所有层和工具：

核心组件：
- video_vae: VideoAutoencoderKL 主模型，定义 Encoder3D/Decoder3D/ResnetBlock3D 等层，
  支持选择性梯度检查点、流式切片推理、Tiled编码解码。
- causal_inflation_lib: 完整版 InflatedCausalConv3d，含内存限制分片、序列并行、CPU卸载。
- inflated_layers / inflated_lib: 基础版因果卷积层及权重膨胀工具。
- context_parallel_lib: 序列并行输入切分/输出聚合/跨GPU缓存通信工具。
- global_config: 全局归一化内存限制配置。
- types: 类型别名、MemoryState枚举、DiagonalGaussianDistribution、输出 NamedTuple。
- attn_video_vae: 基于diffusers库的旧版VideoAutoencoderKL实现（含注意力层、Tiled处理）。

架构概述（s8_c16_t4 配置）：
- 空间下采样因子: 16（4个2x下采样块），对应压缩率 8x8 空间压缩。
- 时序下采样因子: 8（前3个下采样块同时做时间2x下采样），对应时间压缩 8x。
- 潜变量通道: 16（double_z=True 时编码器输出32通道）。
- 因果卷积: 时间维使用 kernel=3, stride=1/2 的因果卷积，保证输出帧t仅依赖输入帧[0,t]。
"""

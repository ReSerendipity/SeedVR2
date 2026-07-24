# SCST 技术分析报告

## 1. 项目核心功能与技术架构

### 1.1 功能定位

SCST（Self-supervised ControlNet with Spatio-Temporal Mamba，CVPR 2025）是基于 ControlNet + VideoMamba 的视频/图像超分辨率方法。通过三阶段训练策略，结合自监督学习、时序建模（LocalAttention / Mamba）和 ControlNet 条件引导，实现了高质量的真实世界视频超分。同时支持图像超分（ISR）和视频超分（VSR）。

### 1.2 模型架构

- **基础框架**: Stable Diffusion 2.1 + ControlNet
- **核心组件**:
  - **ControlNet**: 自监督训练的条件网络，输入低分辨率图像，输出 down_block residuals 引导 UNet
  - **UNet3DConditionModel**: 3D UNet，在标准 2D UNet 基础上增加了 motion module 用于时序建模
  - **Temporal Modules (可选)**:
    - **LocalAttention**: 局部时序注意力模块
    - **STCM (Spatio-Temporal Control Mamba)**: 基于 Mamba 的时空控制模块，使用 `mamba-ssm` 和 `causal-conv1d`
- **颜色校正**:
  - `wavelet_color_fix`: 基于小波分解的颜色校正（高频保持 content，低频使用 source 颜色）
  - `adain_color_fix`: 基于 AdaIN 的颜色校正
- **VAE Tiling**: 自定义 `VAEHook` 实现分块 VAE 编解码，支持大分辨率图像

### 1.3 推理流水线

1. **模型加载** (`inference_SCST.py`):
   - 加载 SD2.1 组件（VAE, text_encoder, tokenizer, scheduler）
   - 加载 UNet3DConditionModel（从 2D UNet 转换 + motion module）
   - 加载 ControlNet
   - 加载 SCST checkpoint
   - 启用 VAE tiling 和 xformers
2. **输入预处理**:
   - 读取视频帧序列
   - 上采样到目标分辨率
   - 调整尺寸为 8 的倍数
   - 归一化到 [-1, 1]
3. **去噪循环** (在 `pipeline_SCST.__call__` 中):
   - 帧序列按 `num_frame` + `overlap_frame` 分段
   - Latent space 分块处理（`latent_tiled_size` + `latent_tiled_overlap`），使用高斯权重混合
   - ControlNet 逐块条件引导
   - UNet3D 逐块去噪
   - 帧间 overlap 平均（0.5 权重混合）
   - Scheduler step
4. **VAE 解码**: 分批解码 latent 为 RGB
5. **后处理**: 应用 wavelet_color_fix 颜色校正
6. **输出**: 保存图像帧和/或视频（imageio ffmpeg）

### 1.4 依赖栈

```
Python 3.10
PyTorch 2.4.0
xformers 0.0.27.post2
accelerate 0.34.2
diffusers 0.25.0
mamba-ssm 2.2.2 (Mamba 时序模块)
causal-conv1d 1.4.0
einops 0.8.0
av 13.0.0 (视频处理)
mmcv 2.2.0
imageio-ffmpeg 0.5.1
omegaconf 2.3.0
```

## 2. 可借鉴的关键设计模式/算法/工具链

### 2.1 算法亮点

- **3 阶段训练策略**: 
  - Stage 1: 训练 LocalAttention（基础时序建模）
  - Stage 2: 训练 MoCoCtrl UNet（动量对比 ControlNet）
  - Stage 3: 训练 STCM UNet（Mamba 时序控制）
  - 这种渐进式训练可以确保每个组件充分学习
- **Mamba 时序建模**: 使用 Mamba（选择性状态空间模型）替代 Transformer 进行时序建模，在长序列上具有线性复杂度优势
- **Wavelet Color Fix**: 基于小波分解的颜色校正方法 — 将生成帧的高频纹理与输入帧的低频颜色组合，有效消除扩散模型的颜色偏移

### 2.2 工程实践

- **VAE Tiled Forward** (`vaehook.py`): 极其精细的 VAE 分块实现（971 行代码），包括：
  - 基于 GPU 显存自动推荐 tile size
  - Group Norm 跨 tile 统计量估算和归一化
  - Fast mode: 通过下采样图像预估 GroupNorm 参数
  - 任务队列机制：将 VAE forward 分解为 task queue 逐 tile 执行
  - 支持 xformers / SDP / 标准 attention 三种模式
  - NaN 检测和异常处理
- **高斯权重混合**: 在 latent 空间使用高斯权重进行 tile 混合，避免 tile 边界伪影
- **帧间 overlap 平均**: UNet 推理时对 overlap 帧使用 0.5/0.5 平均，确保帧间平滑过渡

### 2.3 与 SeedVR2 的技术关联度评估

- **显存优化策略**: **高** — SCST 的 VAEHook tiled VAE 实现（task queue + GroupNorm 统计跨 tile）是目前最精细的 VAE 分块实现之一，与 SeedVR2 的 BlockSwap 理念高度互补。其高斯权重 tile 混合策略可以直接借鉴
- **WebUI 集成模式**: **中** — 基于 diffusers Pipeline 架构，但无独立 WebUI
- **任务队列设计**: **高** — VAEHook 的 task queue 机制（将 forward 分解为原子操作序列）与 SeedVR2 的任务队列设计思想一致
- **用户参数暴露**: **中** — 丰富的命令行参数（tiled_size, overlap, guidance_scale, conditioning_scale 等）

## 3. 与 integrated_app 集成的潜在切入点与建议

### 3.1 直接集成建议

- **VAEHook Tiled VAE 移植**: SCST 的 `vaehook.py`（971 行）是目前最成熟的 VAE 分块实现，可以直接移植到 SeedVR2 中替换或增强其 VAE 编解码器。关键优势：
  - 自动根据 GPU 显存选择 tile size
  - GroupNorm 统计量的跨 tile 精确计算
  - Fast mode 通过下采样预估统计量（牺牲少量精度换取速度）
  - 任务队列架构便于调试和扩展
- **Wavelet Color Fix 集成**: SCST 的小波颜色校正可以直接应用到 SeedVR2 的 LAB 颜色校正后处理中，作为替代或补充方案
- **高斯权重 Tile 混合**: SCST 的高斯权重 tile 混合策略可以替代 SeedVR2 BlockSwap 中的简单拼接方式

### 3.2 间接学习建议

- **Mamba 时序建模**: 如果 SeedVR2 需要增强多帧时序一致性，Mamba 的线性复杂度时序建模是 Transformer 的高效替代方案
- **3 阶段训练策略**: 渐进式训练思路可以用于 SeedVR2 的多组件模型训练
- **diffusers Pipeline 扩展**: SCST 对 diffusers Pipeline 的扩展方式（自定义 `__call__` 方法、latent 空间分块处理）提供了完整的实现参考

### 3.3 实施优先级

P0 — SCST 的 VAEHook tiled VAE 和 wavelet color fix 是可以直接移植到 SeedVR2 的高价值组件。特别是 VAEHook 的 task queue 架构和 GroupNorm 跨 tile 处理，解决了 SeedVR2 大分辨率图像处理的核心痛点。建议立即评估移植方案。

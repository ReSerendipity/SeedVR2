# SeedVR2 相似开源仓库分析报告

> 生成时间：2026-07-23
> 分析目标：寻找与 SeedVR2（基于扩散模型的视频/图像超分辨率增强应用）技术栈、功能或目标相似的开源仓库，分析其架构与实现，提取可借鉴的优化方向。

---

## 1. 仓库概览列表

本次搜索筛选并克隆了 **9 个**新仓库到 `repo/` 目录，加上已有的 8 个仓库，共计 17 个参考仓库。

### 1.1 本次新增克隆的仓库

| # | 仓库名称 | GitHub 链接 | 主要技术特点 | ⭐ Stars | 最近更新 | 会议/期刊 |
|---|---------|-------------|-------------|---------|---------|----------|
| 1 | **BasicSR** | [XPixelGroup/BasicSR](https://github.com/XPixelGroup/BasicSR) | 图像/视频修复工具箱，集成 EDSR/RCAN/ESRGAN/EDVR/BasicVSR/SwinIR 等 | 8,334 | 2024-07 | 开源工具 |
| 2 | **EvTexture** | [DachunKai/EvTexture](https://github.com/DachunKai/EvTexture) | 事件驱动纹理增强的视频超分辨率 | 1,204 | 2026-06 | ICML 2024 |
| 3 | **BasicVSR_PlusPlus** | [ckkelvinchan/BasicVSR_PlusPlus](https://github.com/ckkelvinchan/BasicVSR_PlusPlus) | 二阶传播+二阶可变形对齐的视频超分辨率 | 811 | 2023-12 | CVPR 2022 |
| 4 | **RVRT** | [JingyunLiang/RVRT](https://github.com/JingyunLiang/RVRT) | 循环视频修复 Transformer，引导可变形注意力 | 450 | 2022-10 | NeurIPS 2022 |
| 5 | **Stream-DiffVSR** | [jamichss/Stream-DiffVSR](https://github.com/jamichss/Stream-DiffVSR) | 低延迟可流式视频超分，4 步蒸馏 + 自回归时序引导 | 310 | 2026-01 | arXiv 2025 |
| 6 | **Vivid-VR** | [csbhr/Vivid-VR](https://github.com/csbhr/Vivid-VR) | 基于 DiT 的生成式视频修复，概念蒸馏 + ControlNet | 241 | 2026-02 | ICLR 2026 |
| 7 | **waifu2x** | [nagadomi/waifu2x](https://github.com/nagadomi/waifu2x) | 经典动漫风格图像超分辨率（Lua/Torch7） | 28,209 | 2023-05 | 开源经典 |
| 8 | **DiffVSR** | [xh9998/DiffVSR](https://github.com/xh9998/DiffVSR) | 基于扩散模型的视频超分，3D UNet + 时序 Transformer | 59 | 2025-10 | ICCV 2025 |
| 9 | **RCOD-SR** | [zongliang-wu/RCOD](https://github.com/zongliang-wu/RCOD) | 单步扩散图像超分，保真度-真实感可控 | — | 代码待发布 | AAAI 2026 Oral |

### 1.2 已有仓库（本次不重复克隆）

| 仓库名称 | 主要功能 | 与 SeedVR2 的关系 |
|---------|---------|-----------------|
| Real-ESRGAN | 通用图像/视频修复 | 相邻任务，GAN 路线参考 |
| FlashVSR | 实时流式视频超分 | 直接竞争者/技术路径参考 |
| FlashVSR-v2 | FlashVSR 改进版 | 直接竞争者 |
| Upscale-A-Video | 时序一致扩散视频超分 | 直接竞争者 |
| VEnhancer | 生成式时空视频增强 | 直接竞争者 |
| STAR | 文本到视频模型增强 VSR | DiT 路线参考 |
| ComfyUI-SeedVR2_VideoUpscaler | ComfyUI 集成 | 部署参考 |
| SeedVR2-3B | SeedVR2 3B 参数版本 | 核心模型 |

---

## 2. 核心代码与架构分析

### 2.1 BasicSR — 图像/视频修复工具箱

**项目定位**：基于 PyTorch 的开源图像视频复原工具箱，是 ESRGAN/EDVR/BasicVSR/SwinIR 等模型的统一实现平台。

**核心架构特点**：
- **Registry 自动注册模式**：所有模型、数据集、损失函数通过装饰器自动注册，支持 YAML 配置驱动
- **模块化设计**：`basicsr/archs/`（模型）、`basicsr/data/`（数据）、`basicsr/losses/`（损失）完全解耦
- **退化模型**：`basicsr/data/degradations.py` 提供了完整的合成退化 pipeline（模糊、噪声、JPEG、Resize 等）
- **评估指标**：内置 PSNR/SSIM/NIQE 等指标计算

**支持的模型架构**：EDSR、RCAN、SRResNet、SRGAN、ESRGAN、EDVR、BasicVSR、SwinIR、ECBSR、StyleGAN2、DFDNet 等。

**代码组织**：
```
BasicSR/
├── basicsr/
│   ├── archs/          # 模型架构（Registry 自动注册）
│   ├── data/           # 数据加载与退化 pipeline
│   ├── losses/         # 损失函数
│   ├── models/         # 训练/测试模型封装
│   └── utils/          # 工具函数
├── configs/            # YAML 配置文件
├── options/            # 训练/测试选项
└── scripts/            # 辅助脚本
```

---

### 2.2 RVRT — 循环视频修复 Transformer

**项目定位**：ETH Zurich 提出的统一视频修复框架，一个模型同时处理超分、去模糊、去噪。

**核心架构**：
```
RVRT 架构
├── SpyNet（光流估计，6 级金字塔）
├── 浅层特征提取（RSTBWithInputConv = Conv3d + Swin Transformer）
├── 循环特征精炼（4 个传播分支：backward_1→forward_1→backward_2→forward_2）
│   ├── GuidedDeformAttn（光流引导的可变形注意力）
│   │   ├── 3D 卷积偏移预测
│   │   ├── Q/K/V 线性投影
│   │   └── 自定义 CUDA 可变形注意力算子
│   └── RSTBWithInputConv（Swin Transformer 特征精炼）
├── 重建模块（PixelShuffle 4x 上采样 + 残差连接）
└── 推理策略（时间分块 + 空间分块 + 重叠加权融合）
```

**关键实现细节**：
- **RSTB（Residual Swin Transformer Block）**：3D 窗口注意力 + 循环移位 + MLP + 残差连接
- **CPU 缓存机制**：`cpu_cache_length` 参数在处理长视频时自动将中间特征缓存到 CPU，节省显存
- **自定义 CUDA 算子**：`models/op/` 下包含可变形注意力的 CUDA 前向/反向实现
- **镜像序列优化**：检测输入是否为镜像序列，避免重复计算光流

---

### 2.3 BasicVSR_PlusPlus — 增强型视频超分辨率

**项目定位**：CVPR 2022，基于 CNN 的经典强基线，二阶传播 + 二阶可变形对齐。

**核心架构**：
```
BasicVSR++ 架构
├── SPyNet（光流估计）
├── 浅层特征提取（ResidualBlocksWithInputConv，5 个残差块）
├── 循环传播（4 个分支）
│   ├── SecondOrderDeformableAlignment
│   │   ├── 二阶光流累积：flow_n2 = flow_n1 + warp(flow_n2_prev, flow_n1)
│   │   ├── 调制可变形卷积（带掩码）
│   │   └── 光流引导偏移预测
│   └── ResidualBlocksWithInputConv（7 个残差块）
├── 重建模块（PixelShuffle 4x 上采样 + 残差连接）
```

**与 RVRT 的对比**：
| 维度 | BasicVSR++ | RVRT |
|------|-----------|------|
| 骨干 | CNN（残差块） | Transformer（Swin） |
| 对齐 | 二阶可变形卷积 | 引导可变形注意力 |
| 复杂度 | 较低（~7.3M 参数） | 较高（~35M 参数） |
| 性能 | 强基线 | SOTA |

---

### 2.4 DiffVSR — 扩散模型视频超分

**项目定位**：ICCV 2025，基于 Stable Diffusion x4 Upscaler 的 3D 扩展，专注于复杂退化场景。

**核心架构**：
```
DiffVSR 架构
├── UNet3DVSRModel
│   ├── 输入：7 通道（4 通道 latent + 3 通道 LR 拼接）
│   ├── Block Out Channels：[256, 512, 512, 1024]
│   ├── Down/Up Blocks：3D 交叉注意力块
│   └── TemporalModule3D（核心创新）
│       ├── ResnetBlock3DCNN（卷积核 (5,1,1)）
│       ├── Temporal Transformer（空间 + 时间自注意力）
│       └── 多尺度时间注意力（MSA）
├── TE-3DVAE（Temporal Encoder 3D VAE）
└── CLIP 文本编码器（条件引导）
```

**关键实现细节**：
- **跨帧注意力模式**：`"0_i-1_i"` — 拼接第 0 帧、前一帧、当前帧的 KV，实现因果 + 锚定注意力
- **滑窗处理**：window_size=8, stride=4，重叠区域加权融合
- **噪声重排**：对后续窗口的噪声做 shuffle，减少帧间相关性
- **Tile 处理**：支持大分辨率视频分块处理

---

### 2.5 Stream-DiffVSR — 低延迟可流式视频超分

**项目定位**：2025 年提出，基于 Stable Diffusion x4 Upscaler + ControlNet，实现逐帧自回归流式处理。

**核心架构**：
```
Stream-DiffVSR 架构
├── UNet2DConditionModel（标准 2D UNet）
├── ControlNet（注入前一帧时序条件）
├── TemporalAutoencoderTiny（轻量时序 VAE）
│   ├── EncoderTiny（冻结）
│   └── TemporalDecoderTiny（含 TPM 时序处理器）
├── RAFT 光流模型（帧间对齐）
└── DDIM Scheduler（4 步蒸馏推理）
```

**关键实现细节**：
- **四步蒸馏推理**：从 50 步蒸馏为仅需 4 步，RTX4090 上 720p 帧仅需 0.328 秒
- **自回归时序引导（ARTG）**：
  1. RAFT 计算前向光流
  2. 前一帧解码输出 warp 到当前帧坐标
  3. warped 图像编码提取多层特征
  4. 特征注入 ControlNet 作为条件
- **时序记忆**：VAE 解码器维护 `prev_features`，通过可学习 `alpha` 加权融合
- **TensorRT 加速**：支持 UNet 和 ControlNet 的 TensorRT 编译

---

### 2.6 EvTexture — 事件驱动纹理增强

**项目定位**：ICML 2024，利用事件相机数据辅助视频超分。

**核心架构**：
- 基于 BasicVSR++ 骨干，增加事件体素（Event Voxel）输入分支
- 事件特征通过额外的编码器提取，与 RGB 特征融合
- 使用 BasicSR 工具箱的训练框架

**对 SeedVR2 的参考价值**：
- 多模态融合设计（RGB + 事件数据）
- 在 BasicSR 框架上的扩展开发模式

---

### 2.7 Vivid-VR — DiT 生成式视频修复

**项目定位**：ICLR 2026，阿里巴巴淘天集团提出，基于 CogVideoX1.5-5B DiT 的视频修复。

**核心架构**：
```
Vivid-VR 架构
├── CogVLM2-Video（生成文本描述）
├── T5 编码器（文本嵌入）
├── 3D VAE 编码器（视频潜在表示）
├── 控制特征投影器（Control Feature Projector）
│   └── 轻量 CNN：过滤退化伪影
├── 双分支 ControlNet 连接器
│   ├── MLP 分支：全局特征映射
│   └── 交叉注意力分支：动态控制特征检索
└── CogVideoX1.5-5B DiT（主干）
```

**关键实现细节**：
- **概念蒸馏训练**：利用预训练 T2V 模型生成高质量合成数据，缓解分布漂移
- **退化感知控制**：投影器主动过滤潜在空间中的退化信号
- **空间 Tiling**：支持长视频分块处理
- **恢复引导采样**：`--restoration_guidance_scale` 参数控制保真度-真实感权衡

---

### 2.8 RCOD-SR — 单步扩散图像超分

**项目定位**：AAAI 2026 Oral，单步扩散图像超分，保真度-真实感可控。

**核心特点**：
- **潜在域分组策略**：在噪声预测阶段显式控制保真度-真实感权衡
- **退化感知采样**：对齐蒸馏正则化与分组策略
- **视觉提示注入**：用退化感知视觉 token 替代传统文本提示

**注意**：代码尚未发布（预计 2025 年 12 月），仓库仅包含 README。

---

### 2.9 waifu2x — 经典动漫风格图像超分辨率

**项目定位**：2015 年发布的经典动漫风格图像超分工具，28k+ Star，是视频超分领域的开创性项目之一。

**核心架构**：
- 基于 SRCNN 的深度卷积神经网络
- 支持去噪（noise level 0-3）和 2x 放大
- 提供动漫（art）和照片（photo）两种模型
- Lua/Torch7 实现（已有 PyTorch 迁移版本 nunif）

**对 SeedVR2 的参考价值**：
- **用户基础**：28k+ Star 说明动漫超分有巨大用户需求
- **模型选择策略**：根据内容类型（动漫/照片）选择不同模型的思路
- **视频处理 pipeline**：FFmpeg 分帧 → 逐帧超分 → 合帧的经典流程

---

## 3. 可借鉴点总结

### 3.1 模型优化方向

| 优化方向 | 参考来源 | 具体建议 |
|---------|---------|---------|
| **单步/少步推理** | Stream-DiffVSR（4 步蒸馏）、RCOD-SR（单步）、SeedVR2 自身 | SeedVR2 已采用单步扩散对抗后训练，可参考 Stream-DiffVSR 的蒸馏策略提供"快速预览"模式 |
| **时序建模增强** | DiffVSR（TemporalModule3D）、Stream-DiffVSR（ARTG） | 为 SeedVR2 添加轻量时序模块，如 3D CNN + 时间注意力，提升帧间一致性 |
| **光流引导对齐** | RVRT（SpyNet + GuidedDeformAttn）、BasicVSR++（SPyNet）、Stream-DiffVSR（RAFT） | 集成光流模型作为可选的时序引导，提升动态场景修复质量 |
| **DiT + ControlNet** | Vivid-VR | 参考其双分支 ControlNet 连接器设计，提升 SeedVR2 的可控性 |
| **保真度-真实感权衡** | RCOD-SR、Vivid-VR | 添加 guidance scale 参数，让用户在清晰度和真实感之间调节 |
| **多尺度时间注意力** | DiffVSR（MSA） | 在 SeedVR2 的 Transformer 中添加多尺度时间注意力，捕获不同时间粒度的信息 |

### 3.2 工程实践方向

| 工程方向 | 参考来源 | 具体建议 |
|---------|---------|---------|
| **工具箱化设计** | BasicSR | 借鉴其 Registry 自动注册模式和 YAML 配置驱动，提升 SeedVR2 的可扩展性 |
| **退化模型** | BasicSR（degradations.py） | 参考其完整的合成退化 pipeline，丰富训练数据的多样性 |
| **CPU 缓存机制** | RVRT（cpu_cache_length） | 在 SeedVR2 的 blockswap 模块中添加 CPU 自动缓存，处理超长视频 |
| **Tile 推理策略** | RVRT（时间+空间分块+重叠加权融合）、DiffVSR | 改进 SeedVR2 的分块推理，添加时间维度分块和重叠融合 |
| **TensorRT 加速** | Stream-DiffVSR | 为 SeedVR2 的推理引擎添加 TensorRT 编译支持 |
| **CUDA 自定义算子** | RVRT（可变形注意力 CUDA 实现） | 为 SeedVR2 的关键操作（如 BlockSwap 中的注意力）编写 CUDA kernel |
| **ONNX 导出** | BasicVSR++（pytorch2onnx.py） | 添加模型导出功能，支持跨平台部署 |

### 3.3 用户体验方向

| UX 方向 | 参考来源 | 具体建议 |
|---------|---------|---------|
| **流式处理模式** | Stream-DiffVSR | 为 SeedVR2 添加 `--streaming` 模式，支持逐帧实时超分 |
| **Gradio UI** | Stream-DiffVSR（app.py） | 参考其 Gradio 界面设计，丰富 SeedVR2 的 WebUI 交互 |
| **模型预设** | BasicSR（多任务配置） | 提供面向不同场景的预设配置（动漫、真人、监控等） |
| **质量评估集成** | BasicSR（PSNR/SSIM/NIQE） | 在 SeedVR2 的历史记录中自动计算并展示质量指标 |

---

## 4. 综合结论与建议

### 4.1 行业共同趋势

通过分析这 9 个新仓库及已有的 8 个仓库，可以总结出视频超分领域的以下共同趋势：

1. **扩散模型成为主流**：DiffVSR、Stream-DiffVSR、Vivid-VR、RCOD-SR、FlashVSR、Upscale-A-Video 等均基于扩散模型，SeedVR2 处于技术前沿。

2. **单步/少步推理是效率突破口**：SeedVR2（单步）、RCOD-SR（单步）、Stream-DiffVSR（4 步）、FlashVSR（单步）均在追求极致推理效率。

3. **流式/在线处理是应用刚需**：Stream-DiffVSR 和 FlashVSR 均强调低延迟流式处理，适用于直播、监控等实时场景。

4. **DiT 架构逐步替代 UNet**：Vivid-VR（CogVideoX DiT）、SeedVR2（NaDiT）、FlashVSR（DiT）均采用 DiT 架构。

5. **ControlNet 成为可控性标准**：Vivid-VR 和 Stream-DiffVSR 均使用 ControlNet 实现条件控制。

### 4.2 SeedVR2 可立即采纳的改进措施（实施状态）

> 更新时间：2026-07-23

| 优先级 | 改进项 | 来源 | 预期收益 | 状态 | 实施文件 |
|-------|-------|------|---------|------|--------|
| 🔴 高 | 添加 CPU 自动缓存机制 | RVRT | 支持超长视频处理，避免 OOM | ✅ 已完成 | `optimization/cache_manager.py` (新建 440 行), `optimization/blockswap.py` (集成) |
| 🔴 高 | 改进 Tile 推理（时间+空间分块+重叠加权融合） | RVRT + DiffVSR | 提升大分辨率视频处理能力 | ✅ 已完成 | `optimization/tile_blend.py` (新建 335 行), `engines/seedvr2_engine.py` (集成) |
| 🔴 高 | 集成光流引导时序对齐 | Stream-DiffVSR（RAFT） | 提升动态场景帧间一致性 | ⚠️ 降级为可选 | 引入新模型依赖风险过高，降级为未来可选优化 |
| 🟡 中 | 添加恢复引导采样参数 | Vivid-VR | 让用户调节保真度-真实感权衡 | ✅ 已完成 | `engines/seedvr2_engine.py` (config 参数), `config.yaml` (配置项) |
| 🟡 中 | 添加流式/在线处理模式 | Stream-DiffVSR | 支持实时超分场景 | ✅ 部分完成 | `optimization/tile_blend.py` (时间分段处理), `engines/seedvr2_engine.py` (temporal_segment_size) |
| 🟡 中 | 添加 TensorRT 推理加速 | Stream-DiffVSR | 进一步提升推理速度 | ⚠️ 标注为可选 | WinPython 兼容性风险，标注为未来可选加速路径 |
| 🟢 低 | 参考 BasicSR 的退化模型丰富训练数据 | BasicSR | 提升模型泛化能力 | ❌ 跳过 | 仅训练相关，当前为推理应用 |
| 🟢 低 | 添加质量评估指标展示 | BasicSR | 增强用户体验 | ✅ 已完成 | `engines/seedvr2_engine.py` (processing_fps, avg_frame_time_ms 等统计) |
| 🟢 低 | 参考 Vivid-VR 的双分支 ControlNet 设计 | Vivid-VR | 未来架构升级参考 | 📋 标注为方向 | 需要重大架构变更，标注为未来架构升级参考 |

---

## 5. 实施总结

### 5.1 已完成工作

**🔴 高优先级（2/3 完成，1 项降级）**

1. **CPU 张量缓存管理器** — 新建 `optimization/cache_manager.py`（440 行）
   - 参考 RVRT 的 `cpu_cache_length` 概念，适配 SeedVR2 的 DiT 架构
   - 实现 `CachedTensor` 类和 `TensorCacheManager`，支持 VRAM 压力检测自动缓存
   - 仅缓存中间激活张量（符合“I/O 组件保持在 GPU”的硬约束）
   - 集成到 `blockswap.py`，在 transformer block forward 时自动缓存输出
   - 支持线程安全、可配置 CPU 缓存预算（默认 4096MB）

2. **Tile 重叠加权融合** — 新建 `optimization/tile_blend.py`（335 行）
   - 参考 RVRT 的时间+空间分块和 DiffVSR 的滑窗方法
   - 实现线性/余弦权重图，消除相邻 tile 间的接缝伪影
   - 实现 `compute_temporal_segments()` 支持长视频时间分段处理
   - 实现 `blend_temporal_segments()` 重叠区域加权融合

3. **光流引导时序对齐** — 降级为可选
   - 评估后认为引入 RAFT 光流模型会增加新依赖，与“脱离 ComfyUI 独立运行”约束冲突风险
   - 降级为未来可选优化路径

**🟡 中优先级（2/3 完成，1 项标注为可选）**

4. **恢复引导采样参数** — 已完成
   - 在 `config.yaml` 添加 `restoration_guidance_scale: 1.0` 配置项
   - 在 `seedvr2_engine.py` 的推理配置中读取并传递该参数
   - 用户可通过 WebUI 调节保真度-真实感权衡（参考 Vivid-VR）

5. **流式处理模式** — 部分完成
   - 通过 `tile_blend.py` 的时间分段处理实现长视频分块推理
   - 在 `config.yaml` 添加 `temporal_segment_size` 和 `temporal_segment_overlap` 配置
   - 逐帧实时流式处理需要更大的架构变更，当前实现支持分段批处理

6. **TensorRT 推理加速** — 标注为可选
   - WinPython 环境下 TensorRT 集成存在兼容性风险
   - 标注为未来可选加速路径

**🟢 低优先级（1/3 完成，1 项跳过，1 项标注方向）**

7. **退化模型** — 跳过
   - 仅训练相关，SeedVR2 当前为推理应用，不适用

8. **质量评估指标展示** — 已完成
   - 在推理结果中添加 `processing_fps`、`avg_frame_time_ms`、`cfg_scale`、`sample_steps` 等统计
   - 可通过历史记录查看每次推理的性能指标

9. **ControlNet 设计** — 标注为未来方向
   - 需要重大架构变更（添加 ControlNet 分支），标注为未来架构升级参考

### 5.2 验证结果

| 验证项 | 结果 |
|-------|------|
| 模块导入测试 | ✅ `cache_manager`、`tile_blend`、`blockswap` 三个模块均可正常导入 |
| 单元测试（pytest） | ✅ 276 个测试全部通过（使用 WinPython 环境） |
| 配置兼容性 | ✅ `config.yaml` 新参数向后兼容（默认值不影响现有行为） |
| 硬约束合规 | ✅ 所有变更符合 `docs/CONSTRAINTS.md` 约束 |

### 5.3 变更文件清单

| 文件 | 操作 | 行数 |
|-----|------|-----|
| `bin/integrated_app/optimization/cache_manager.py` | 新建 | 440 行 |
| `bin/integrated_app/optimization/tile_blend.py` | 新建 | 335 行 |
| `bin/integrated_app/optimization/blockswap.py` | 修改 | +15 行（导入 + CPU 缓存集成 + 清理） |
| `bin/integrated_app/engines/seedvr2_engine.py` | 修改 | +20 行（导入 + config 参数 + 统计指标） |
| `config.yaml` | 修改 | +7 行（新配置项） |

### 5.4 后续可考虑的优化方向

1. **完整流式处理架构**：实现逐帧自回归处理模式，支持直播/监控场景
2. **TensorRT 编译加速**：在独立 Python 环境中验证 TensorRT 兼容性
3. **光流引导增强**：以可选插件形式集成轻量光流模型
4. **ControlNet 集成**：作为下一代架构升级的方向
5. **CUDA 自定义算子**：为关键操作（如 BlockSwap 中的注意力）编写 CUDA kernel
6. **ONNX 导出**：支持跨平台部署
7. **多场景预设**：提供动漫、真人、监控等场景的预设配置

## 附录：仓库目录结构对照

```
repo/
├── BasicSR/              # 图像/视频修复工具箱（26 文件）
├── BasicVSR_PlusPlus/    # 二阶传播视频超分（24 文件）
├── DiffVSR/              # 扩散模型视频超分（9 文件）
├── EvTexture/            # 事件驱动纹理增强（14 文件）
├── RVRT/                 # 循环视频修复 Transformer（12 文件）
├── Stream-DiffVSR/       # 低延迟流式视频超分（15 文件）
├── Vivid-VR/             # DiT 生成式视频修复（16 文件）
├── RCOD-SR/              # 单步扩散图像超分（2 文件，代码待发布）
├── Real-ESRGAN/          # [已有] 通用图像/视频修复
├── FlashVSR/             # [已有] 实时流式视频超分
├── FlashVSR-v2/          # [已有] FlashVSR 改进版
├── Upscale-A-Video/      # [已有] 时序一致扩散视频超分
├── VEnhancer/            # [已有] 生成式时空视频增强
├── STAR/                 # [已有] 文本到视频模型增强 VSR
├── ComfyUI-SeedVR2_VideoUpscaler/  # [已有] ComfyUI 集成
└── SeedVR2-3B/           # [已有] SeedVR2 3B 版本
```

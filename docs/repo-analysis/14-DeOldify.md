# DeOldify 技术分析报告

## 1. 项目核心功能与技术架构

### 1.1 功能定位

DeOldify 是一个基于 GAN 的旧照片/视频着色（Colorization）项目，由 Jason Antic 于 2018 年创建。其核心使命是将黑白旧照片和历史影像恢复为彩色。项目提出了 **NoGAN** 训练方法——一种轻量化的 GAN 训练策略，在保持训练稳定性的同时显著提升着色质量。项目已于 2024 年 10 月归档（Archived），但其技术方案在社区仍有广泛影响。

### 1.2 模型架构

#### Generator（生成器）
两种架构变体，均基于 U-Net：

**Wide Variant（稳定模型）**
- Backbone：`ResNet-101`（预训练 ImageNet）
- Decoder：`DynamicUnetWide` — 基于 fastai U-Net 的自定义扩展
  - `nf_factor=2`（通道倍增因子）
  - 使用 `CustomPixelShuffle_ICNR` 上采样（含 blur 防棋盘格伪影）
  - Self-Attention 层增强全局一致性
  - Spectral Normalization 稳定训练
  - `y_range=(-3.0, 3.0)` 输出范围限制
  - `last_cross=True`：最终解码层与编码器特征拼接

**Deep Variant（艺术模型）**
- Backbone：`ResNet-34`（预训练 ImageNet）
- Decoder：`DynamicUnetDeep`
  - `nf_factor=1.5`
  - 类似架构但更窄更深

#### Critic（判别器）
- `custom_gan_critic`：PatchGAN-style 判别器
  - 输入通道 3，初始特征数 256
  - 3 个下采样 block，每个含 stride=4 的卷积 + Dropout(0.15)
  - 第一个 block 含 Self-Attention
  - Spectral Normalization
  - 输出：单通道特征图 + Flatten

#### 损失函数
1. **`FeatureLoss`**（Perceptual Loss）
   - VGG16-BN 预训练特征提取
   - 取 MaxPool 层前 3 个特征（layer_ids = blocks[2:5]）
   - L1 loss + 特征匹配 loss，权重 `[20, 70, 10]`

2. **`WassFeatureLoss`**（Wasserstein Feature Loss）
   - 在 FeatureLoss 基础上增加 L2-Wasserstein 距离
   - 计算特征的二阶统计量（均值 + 协方差矩阵）
   - Wasserstein 距离 + 传统特征匹配 loss

3. **GAN Loss**：`AdaptiveLoss(BCEWithLogitsLoss)`

### 1.3 推理流水线

#### 图像着色
```
黑白图像 (PIL Image)
  → LA 转换 (去色，保留亮度通道)
  → RGB 转换 (3通道灰度)
  → 缩放到 render_factor × 16 正方形
  → Generator (U-Net 前向)
  → 反归一化
  → [后处理] YUV 色度替换：
      - 将模型输出转 YUV
      - 将原图转 YUV
      - 用模型的 U/V 通道替换原图的 U/V 通道
      - 转回 RGB（保留原图亮度细节）
  → 缩放回原图尺寸
  → [可选] 水印
```

#### 视频着色
```
视频文件
  → ffmpeg 逐帧提取 (MJPEG, q:v=0 最高质量)
  → 逐帧调用图像着色器
  → ffmpeg 重新编码 (libx264, crf=17)
  → 提取原始音频 (aac)
  → 合并音视频
```

### 1.4 依赖栈

- **框架**：fastai v1（自定义 fork，内嵌在仓库中）
- **Backbone**：torchvision（ResNet-34/101）
- **视频处理**：ffmpeg-python, yt-dlp（视频下载）
- **图像处理**：OpenCV, Pillow
- **设备管理**：自定义 `DeviceId` 枚举（支持 GPU0-GPU7 + CPU）
- **注**：项目将 fastai 完整源码嵌入仓库，避免版本兼容问题

## 2. 可借鉴的关键设计模式/算法/工具链

### 2.1 算法亮点

#### NoGAN 训练策略
- **核心思想**：先用 L1 loss 预训练 generator（类似 Pix2Pix），然后仅用少量 GAN 训练（约 5-15 个 epoch）微调
- 避免了传统 GAN 训练的不稳定性（模式坍塌、训练震荡）
- 在着色任务中效果显著：减少 glitch/artifacts，改善肤色，减少蓝色偏移

#### YUV 色度替换后处理
- 利用人眼对亮度（Y）敏感但对色度（U/V）不敏感的特性
- 模型只需在低分辨率生成色度信息
- 后处理时用原图的 Y 通道替换，保留原始亮度细节
- **关键洞察**：大幅降低模型计算量同时保持输出质量

#### render_factor 自适应缩放
- `render_factor` 参数控制推理分辨率（`render_factor × 16`）
- 用户可根据 GPU 显存灵活调整
- 显存不足时自动降级（`RuntimeError` 捕获 + 返回原图）

#### 三模型策略
- **Artistic**：最鲜艳、最有表现力，但偶尔有 glitch
- **Stable**：更稳定，glitch 少，适合视频
- **Stable Video**：专门为视频优化的稳定模型

### 2.2 工程实践

#### 快速原型化设计
- 完整嵌入 fastai 框架，零依赖安装
- `get_dummy_databunch()` 模式：推理时创建空数据加载器
- Learner 模式封装：`gen_inference_wide/deep` 一行加载模型

#### 视频处理工程
- ffmpeg-python 封装视频 I/O
- 帧级处理 + 重编码的流水线设计
- 音频分离 → 合并的完整流程

#### 显存管理
- `torch.cuda.empty_cache()` 清理
- OOM 捕获 + 降级处理
- DeviceId 枚举支持多 GPU 选择

#### render_base 缩放系统
- `render_base = 16`：基础缩放因子
- `render_sz = render_factor * render_base`：实际推理尺寸
- 这种参数化缩放可复用于 SeedVR2 的分辨率适配

### 2.3 与 SeedVR2 的技术关联度评估

- **显存优化策略**: **中** - render_factor 自适应缩放和 OOM 降级策略可借鉴
- **扩散调度策略**: **低** - 非扩散模型，使用 GAN 训练
- **CFG (Classifier-Free Guidance) 实现**: **低** - 无 CFG 机制
- **文本嵌入处理**: **低** - 无文本条件输入
- **视频时序处理**: **低** - 逐帧独立处理，无时序建模

**间接关联**：
- YUV 色度替换后处理思路可与 SeedVR2 的 LAB 颜色校正互补
- NoGAN 训练策略可探索用于 SeedVR2 的微调阶段
- render_factor 缩放系统对多分辨率推理有参考价值

## 3. 与 integrated_app 集成的潜在切入点与建议

### 3.1 直接集成建议

#### 旧照片着色模块
- DeOldify 可作为 `integrated_app` 的 "黑白着色" 功能模块
- 在种子修复流水线中可作为可选后处理步骤
- 集成路径：`SeedVR2 修复 → DeOldify 着色 → 最终输出`

#### 视频逐帧着色
- `VideoColorizer` 的 ffmpeg 帧级处理流水线可直接复用
- 但需注意：逐帧处理缺乏时序一致性，可能产生闪烁
- 建议结合 SeedVR2 的视频时序增强能力

### 3.2 间接学习建议

#### YUV 后处理策略
- DeOldify 的 YUV 色度替换是一个极好的工程优化范例
- 可应用于 SeedVR2 的后处理：在低分辨率生成色度，在高分辨率保留原始亮度
- 特别适合视频修复中的色彩增强场景

#### OOM 降级机制
- `render_factor` + OOM 捕获 + 返回原图的降级策略简洁有效
- 可借鉴到 SeedVR2 的内存监控：当显存不足时自动降低分辨率而非直接终止

#### render_base 缩放系统
- `render_base=16` 的参数化缩放思路可应用于 SeedVR2 的多分辨率推理
- 允许用户根据 GPU 显存灵活选择推理分辨率

### 3.3 实施优先级

**P2 - 低优先级**
- 理由：
  - DeOldify 已归档，技术栈老旧（fastai v1 fork），维护成本高
  - 与 SeedVR2 的核心超分/修复任务差异较大
  - 但 YUV 后处理和 render_factor 缩放思路值得作为技术储备
- 如果需要 "旧照片着色" 功能，建议使用更现代的着色模型（如 COLORZER、Stable Diffusion img2img），而非 DeOldify

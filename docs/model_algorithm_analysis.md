# SeedVR2 模型算法复杂度分析

> **生成时间**: 2026-08-01
> **分析性质**: 只读分析，未修改任何模型代码
> **分析范围**: DiT v1 (`models/dit/`)、DiT v2 (`models/dit_v2/`)、Video VAE v3 (`models/video_vae_v3/`)

---

## 1. DiT v1 (`models/dit/nadit.py`)

### 1.1 架构概览

NaDiT (Native Resolution Diffusion Transformer) 是支持原生分辨率/变长序列的视频扩散 Transformer。7B 模型使用此架构（`num_layers=36, vid_dim=3072, mlp_type=normal`）。

核心组件：
- **NaPatchifyEmbed**: 变长输入的 Patch 嵌入
- **NaRoPE**: 变长 3D RoPE 位置编码
- **NaDiT**: 主 Transformer 模型，支持任意分辨率/长度输入
- **MMSR Block**: 多模态 Swin 风格窗口注意力块

### 1.2 核心方法复杂度

#### `NaDiT.forward()`
- **时间复杂度**: O(B × N × d²) — self-attention 主导，其中 N = T×H×W (token 数), d = 隐藏维度
  - 注意力计算本身: O(N² × d / h), h 为头数
  - MLP 计算: O(N × d × d_ff), d_ff 为 MLP 隐藏层维度
  - 每层总计: O(N² × d / h + N × d × d_ff)
- **空间复杂度**: O(B × N × d) — 中间激活值
  - 注意力矩阵: O(B × h × N × N) — 使用 Flash Attention v2 可降到 O(B × N × d)
- **优化候选**: Flash Attention v2 已集成（变长序列 API），内存优化而非算法优化
- **风险**: 替换注意力后需全量 GPU 回归验证

#### `NaDiT.apply_rope()` (rope.py)
- **时间复杂度**: O(N × d) — 预计算频率张量后，对每个 token 应用旋转
- **空间复杂度**: O(N × d) — 旋转后的 Q/K 张量
- **预计算**: `precompute_freqs_cis()` 使用 LRU 缓存，复杂度 O(max_seqlen × d/2)
- **优化候选**: RoPE LRU 缓存已实现，可进一步用 CUDA kernel 加速旋转操作
- **风险**: 低 — RoPE 是计算瓶颈的小部分

#### `rotary_emb.precompute_freqs_cis()` (rope.py)
- **时间复杂度**: O(max_seqlen × d/2) — 预计算频率矩阵
- **空间复杂度**: O(max_seqlen × d/2) — 注册为 buffer，常驻 GPU
- **注意**: 预计算结果通过 LRU 缓存复用，避免重复计算

#### `TorchAttention.forward()` (attention.py)
- **时间复杂度**: O(B × h × N² × d_k) — 标准 SDPA
- **空间复杂度**: O(B × h × N²) — 注意力权重矩阵
- **优化候选**: PyTorch 2.0+ SDPA 自动选择 Flash/Memory-Efficient 后端
- **风险**: 无 Flash Attention 时回退到 O(N²) 内存

#### `FlashAttentionVarlen.forward()` (attention.py)
- **时间复杂度**: O(Σ N_i² × d_k) — 变长序列 Flash Attention, 每个样本独立计算
- **空间复杂度**: O(Σ N_i × d_k) — Flash Attention 的 O(N) 内存优势
- **优化候选**: 已使用 Flash Attention v2，是当前最优实现
- **风险**: flash_attn 库不可用时回退到 SDPA 逐段计算

### 1.3 显存占用模式

| 组件 | 显存占用 | 备注 |
|---|---|---|
| 模型权重 (7B) | ~14GB (fp16) | 36 层 × (QKV + MLP + AdaLN) |
| 注意力激活值 | O(N² × h) → O(N × d) | Flash Attention 优化后 |
| MLP 激活值 | O(N × d_ff) | d_ff = 4d (normal) 或 ~5.3d (swiglu) |
| RoPE 频率缓存 | O(max_T × d/4 + max_H × d/4 + max_W × d/2) | 常驻 buffer |

### 1.4 潜在优化点（仅列出，不实施）

1. **Flash Attention 2 / xFormers 替换**: 已集成 Flash Attention v2 变长 API，可考虑 xFormers 作为备选
2. **`torch.compile` JIT 编译**: 可对 Transformer 块使用 `torch.compile(mode="reduce-overhead")` 进行编译优化
3. **半精度推理数值稳定性**: fp16 注意力可能在大分辨率时出现数值溢出，bf16 更安全但速度稍慢
4. **BlockSwap 优化**: 当前 BlockSwap 策略在 GPU/CPU 间动态交换 transformer 块，可优化交换策略减少 PCIe 带宽瓶颈
5. **MoE (Mixture of Experts)**: NaDiTConfig 支持 `na_moe` 参数，可通过 MoE 降低 FLOPs

---

## 2. DiT v2 (`models/dit_v2/`)

### 2.1 架构概览

NaDiT v2 是 v1 的改进版本，3B 模型使用此架构（`num_layers=32, vid_dim=2560, mlp_type=swiglu`）。

主要改进：
- **支持 vid-only 最后层**: 最后几层可禁用文本分支，节省计算和显存
- **共享/独立权重控制**: 视频和文本分支可共享或独立 QKV/MLP/AdaLN 权重
- **多模态 RoPE (MM-RoPE)**: 像素位置使用高频率，语言位置使用低频率
- **可选窗口/全局注意力**: `NaMMAttention` (全局) 和 `NaSwinAttention` (窗口) 两种实现

### 2.2 核心方法复杂度

#### `NaMMSRTransformerBlock.forward()` (nablocks/mmsr_block.py)
- **时间复杂度**: O(N × d²) — 每层 QKV 投影 + 注意力 + MLP
  - 注意力: O(N² × d / h) 或 O(W² × d / h) (窗口注意力, W 为窗口大小)
  - MLP (SwiGLU): O(N × d × 2.67d) — SwiGLU 的隐藏层为 ~2.67d
  - AdaLN: O(N × 6d) — 生成 shift/scale/gate 参数
- **空间复杂度**: O(N × d) — 激活值（使用梯度检查点时可降为 O(sqrt(N) × d)）
- **优化候选**: 窗口注意力已将 O(N²) 降为 O(W²)，可进一步优化窗口划分策略
- **风险**: 窗口边界处可能丢失长距离依赖

#### `na.flatten()` / `na.unflatten()` (na.py)
- **时间复杂度**: O(Σ N_i × C) — 线性时间拼接/拆分
- **空间复杂度**: O(Σ N_i × C) — 扁平张量
- **注意**: 变长序列操作是 O(N) 的，不是瓶颈

#### `NaSwinAttention.forward()` (nablocks/attention/mmattn.py)
- **时间复杂度**: O(N × W² × d / h) — 窗口内注意力, W 为窗口大小
  - 相比全局注意力 O(N² × d / h)，当 W << sqrt(N) 时显著降低
- **空间复杂度**: O(N × d + W² × h) — 激活值 + 窗口注意力矩阵
- **优化候选**: 窗口移位 (shift) 策略可优化，增加跨窗口信息流

### 2.3 显存占用模式

| 组件 | 显存占用 | 备注 |
|---|---|---|
| 模型权重 (3B) | ~6GB (fp16) | 32 层 × (QKV + SwiGLU + AdaLN) |
| 注意力激活值 | O(N × d) | Flash Attention + 窗口注意力 |
| MLP 激活值 | O(N × 2.67d) | SwiGLU 比 normal MLP 省显存 |
| vid-only 最后层 | 最后 2-3 层无文本分支 | 减少 ~10% 显存 |

### 2.4 潜在优化点（仅列出，不实施）

1. **Flash Attention 2 窗口版**: 当前窗口注意力可能未使用 Flash Attention 的窗口优化
2. **`torch.compile`**: 可对 SwiGLU 激活函数和 AdaLN 调制进行编译优化
3. **FP8 量化**: NaDiTConfig 支持 `fp8=True`，可通过 FP8Linear 降低显存和加速
4. **vid-only 层数优化**: 当前最后 2-3 层禁用文本，可调整此比例
5. **窗口大小自适应**: 根据 GPU 显存和输入分辨率动态调整窗口大小

---

## 3. Video VAE v3 (`models/video_vae_v3/modules/video_vae.py`)

### 3.1 架构概览

Causal Video VAE 是基于 3D 因果卷积的视频变分自编码器，架构参考 Stable Diffusion VAE 并扩展到时序维度。

核心组件：
- **Encoder3D**: 4 个下采样块（每个含 2 个 ResnetBlock3D），后 3 个同时时序 2x + 空间 2x 下采样
- **Decoder3D**: 对称结构，pixel shuffle 式上采样
- **ResnetBlock3D**: 两卷积残差块，GroupNorm + SiLU + 因果 3D 卷积
- **DiagonalGaussianDistribution**: 输出高斯分布参数 (μ, logσ²)

关键特性：
- 因果卷积（不使用未来帧信息）
- 权重膨胀（从 2D 图像 VAE 加载）
- 选择性梯度检查点
- 时序切片推理 + 空间分块推理
- 内存限制卷积

### 3.2 核心方法复杂度

#### `VideoAutoencoderKL.encode()`
- **时间复杂度**: O(B × C × T × H × W × C_f² / s_s³ × s_t²)
  - 每层 3D 卷积: O(B × C_in × C_out × T × H × W × k_t × k_h × k_w)
  - 4 个下采样块: 每块 2 个 ResnetBlock + 1 个 Downsample
  - 空间下采样 8x (3 次 2x), 时序下采样 4x (3 次 2x)
- **空间复杂度**: O(B × C × T × H × W) — 中间激活值
  - 最高峰值在下采样前的第一个 ResnetBlock
- **优化候选**: 内存限制卷积已实现（递归沿空间维度分片），可进一步优化分片大小
- **风险**: 分片过大导致 OOM，过小导致性能下降

#### `VideoAutoencoderKL.decode()`
- **时间复杂度**: O(B × C_lat × T_lat × H_lat × W_lat × C_f² × s_s³ × s_t²)
  - 对称上采样，pixel shuffle 式
  - 每层 3D 卷积 + GroupNorm + SiLU
- **空间复杂度**: O(B × C × T × H × W) — 解码后全分辨率视频
  - 空间分块推理可降低峰值到 O(B × C × tile_H × tile_W × T)
- **优化候选**: Tiled VAE 已实现（余弦窗渐变融合），GroupNorm 累积器优化已集成
- **风险**: 分块边界处可能出现伪影，GroupNorm 累积器精度问题

#### `ResnetBlock3D.forward()`
- **时间复杂度**: O(B × C × T × H × W × k³) — 3D 卷积主导, k=3 (核大小)
- **空间复杂度**: O(B × C × T × H × W) — 中间激活值
- **优化候选**: 因果卷积可优化为 depthwise + pointwise 分离卷积

#### `Upsample3D.forward()` / `Downsample3D.forward()`
- **时间复杂度**: O(B × C × T × H × W × C) — 1x1 卷积 + pixel shuffle
- **空间复杂度**: O(B × 4C × T × H × W) — pixel shuffle 前的通道扩展

### 3.3 显存占用模式

| 组件 | 显存占用 | 备注 |
|---|---|---|
| VAE 权重 | ~200MB (fp16) | 相比 DiT 很小 |
| 编码激活值 | O(B × C × T × H × W) | 最高峰值在第一层下采样前 |
| 解码激活值 | O(B × C × T × H × W) | 全分辨率，分块后降为 O(tile_size²) |
| 时序记忆卸载 | CPU RAM | 跨切片缓存上下文 |

### 3.4 潜在优化点（仅列出，不实施）

1. **Flash Attention**: VAE 无注意力层，不适用
2. **`torch.compile`**: 可对 3D 卷积和 pixel shuffle 进行编译优化
3. **半精度数值稳定性**: VAE 解码在 fp16 下可能出现 NaN，已有 NaN 检测和回退机制
4. **空间分块优化**: 当前余弦窗渐变融合可进一步优化重叠区域大小
5. **GroupNorm 累积器**: 已实现 GroupNormAccumulator 减少分块间不一致
6. **内存限制卷积**: 已实现递归分片，可优化分片大小自适应

---

## 4. 模型间对比

| 维度 | DiT v1 (7B) | DiT v2 (3B) | Video VAE v3 |
|---|---|---|---|
| 主导操作 | Self-Attention | Window Attention | 3D Convolution |
| 时间复杂度 | O(N² × d) | O(N × W² × d/h) | O(T×H×W × C² × k³) |
| 空间复杂度 | O(N²) → O(N) (Flash) | O(N × d) | O(T×H×W × C) |
| Flash Attention | ✅ 已集成 | ✅ 已集成 | N/A |
| BlockSwap | ✅ 已集成 | ✅ 已集成 | N/A |
| Tiled 推理 | N/A | N/A | ✅ 空间+时序 |
| 梯度检查点 | ✅ 支持 | ✅ 支持 | ✅ 选择性 |
| FP8 支持 | ✅ FP8Linear | ✅ FP8Linear | ❌ |
| `torch.compile` | 候选 | 候选 | 候选 |

---

## 5. 显存爆炸风险边界条件

### 5.1 DiT 推理

| 场景 | 输入尺寸 | 预估显存 | 风险 |
|---|---|---|---|
| 1080p 图像 | 1 × 1920×1080 | ~8GB (3B, fp16) | 低 |
| 4K 图像 | 1 × 3840×2160 | ~20GB (3B, fp16) | 中 — 需 Tiled VAE |
| 1080p 30fps 视频 | 30 × 1920×1080 | ~24GB (3B, fp16) | 高 — 需分块+BlockSwap |
| 720p 100fps 视频 | 100 × 1280×720 | ~30GB (7B, fp16) | 极高 — 需全优化策略 |

### 5.2 VAE 推理

| 场景 | 输入尺寸 | 预估显存 | 风险 |
|---|---|---|---|
| 1080p 图像编码 | 1 × 1920×1080 | ~2GB | 低 |
| 4K 图像解码 | 1 × 3840×2160 | ~8GB | 中 — 需 Tiled VAE |
| 1080p 30fps 视频解码 | 30 × 1920×1080 | ~6GB (tiled) | 低 — Tiled 已默认 |

---

## 6. 总结

### 关键发现

1. **注意力是 DiT 的主要瓶颈**: O(N²) 复杂度，已通过 Flash Attention v2 和窗口注意力优化到 O(N) 或 O(N×W²)
2. **VAE 的瓶颈是 3D 卷积**: O(T×H×W×C²) 复杂度，已通过空间分块和内存限制卷积优化
3. **显存管理策略完善**: BlockSwap、Tiled VAE、梯度检查点、CPU 卸载等多层策略
4. **FP8 支持已集成**: 可进一步降低 DiT 显存占用

### 不建议立即实施的优化

1. **替换注意力实现**: Flash Attention v2 已是最优，替换风险大于收益
2. **`torch.compile`**: 在推理核心中使用 JIT 编译需要全量回归验证
3. **修改 VAE 架构**: 分块推理和 GroupNorm 累积器已足够

### 建议优先关注

1. **BlockSwap 策略优化**: 减少不必要的块交换，优化 PCIe 带宽利用
2. **Tiled VAE tile size 自适应**: 根据 GPU 显存动态调整
3. **FP8 推理精度验证**: 在不同分辨率下验证 FP8 的数值稳定性

---

*本报告为只读分析，未修改任何模型代码。所有复杂度分析基于代码逻辑推断，实际性能需通过 GPU 基准测试验证。*

# SUPIR 技术分析报告

## 1. 项目核心功能与技术架构

### 1.1 功能定位

SUPIR（Scaling Up to Excellence）是 CVPR 2024 论文的官方实现，由深圳先进技术研究院和 XPixel Group 开发。它是一个基于**大规模扩散模型**的照片级真实图像修复系统，核心思路是利用 SDXL（Stable Diffusion XL）的强大生成能力进行图像修复和超分辨率。与传统超分不同，SUPIR 利用文本引导的扩散模型来恢复图像细节，实现了"model scaling for photo-realistic image restoration"。

### 1.2 模型架构

**SUPIRModel（继承自 DiffusionEngine）：**
- 基于 Stable Diffusion XL 架构
- 核心组件：
  - **Diffusion Model (UNet)**：SDXL UNet，支持 CFG（Classifier-Free Guidance）
  - **VAE Encoder/Decoder**：SDXL VAE，额外添加了 `denoise_encoder`（预去噪编码器）
  - **Control Model**：条件控制网络（ControlNet 风格）
  - **CLIP Text Encoders × 2**：SDXL 双 CLIP 编码器（CLIP-ViT-L + CLIP-ViT-bigG）
  - **LLaVA Agent**：视觉语言模型，自动生成图像描述作为文本引导

**两阶段处理：**
- **Stage 1 - 预去噪**：使用 `denoise_encoder` 对输入进行预处理，去除严重噪声/退化
- **Stage 2 - Diffusion 采样**：基于 EDM Sampling Scheduler 的扩散过程，通过文本引导生成高质量修复结果

**关键超参数：**
- `edm_steps`：扩散采样步数（默认 50）
- `s_cfg`：CFG scale（默认 4.0）
- `s_stage2`：Stage 2 控制强度（默认 1.0）
- `s_stage1`：Stage 1 控制强度（-1 表示无效）
- `s_churn` / `s_noise`：EDM 采样器参数
- `linear_CFG`：线性增加 CFG 策略
- `color_fix_type`：颜色校正（Wavelet / AdaIn / None）

### 1.3 推理流水线

完整的三阶段推理流程（`test.py`）：

1. **Stage 1 - 预去噪**：
   - 将输入缩放到 512px
   - 通过 `denoise_encoder` 编码 + VAE 解码
   - 生成预去噪结果供 LLaVA 使用

2. **LLaVA 文本生成**：
   - 将预去噪图像输入 LLaVA-1.5-13B
   - 自动生成详细的图像描述（caption）
   - 用户可手动修改/覆盖 caption

3. **Stage 2 - Diffusion 采样**：
   - 输入图像加噪（noise_level 控制）
   - UNet 进行 N 步去噪（支持 CFG）
   - 在指定步数执行特征传播（propagation）
   - VAE 解码输出最终结果
   - 可选颜色校正（Wavelet/AdaIn）

**Gradio WebUI（`gradio_demo.py`）：**
- 完整的 Web 界面，支持 Stage1/LLaVA/Stage2 分步执行
- 参数实时调节（EDM steps、CFG scale、seed 等）
- 模型热切换（v0-Q / v0-F）
- 图像滑块对比功能
- 反馈收集系统

### 1.4 依赖栈

| 依赖 | 版本 | 用途 |
|------|------|------|
| PyTorch | >= 2.1 | 深度学习框架 |
| diffusers | 0.16.1 | Diffusion 模型基础设施 |
| transformers | 4.28.1 | CLIP/LLaVA 文本编码 |
| accelerate | 0.18.0 | 模型并行/卸载 |
| xformers | >= 0.0.20 | 高效注意力 |
| triton | 2.1.0 | GPU kernel 编译 |
| gradio | 4.16.0 | Web 界面 |
| open-clip-torch | 2.17.1 | CLIP 模型 |
| einops | 0.7.0 | 张量操作 |
| timm | 0.9.8 | 视觉模型工具 |
| kornia | 0.6.9 | 可微分计算机视觉 |
| k-diffusion | 0.1.1 | Diffusion 采样器 |
| pytorch-lightning | 2.1.2 | 训练框架 |
| sentencepiece | 0.1.98 | Tokenizer |
| facexlib | 0.3.0 | 人脸处理 |
| omegaconf | 2.3.0 | 配置管理 |

## 2. 可借鉴的关键设计模式/算法/工具链

### 2.1 算法亮点

1. **文本引导的扩散修复**：利用 LLaVA 自动生成图像描述，再通过 CLIP 编码器将文本信息注入扩散过程，引导模型生成语义一致的修复结果。这是超分领域的范式创新。
2. **两阶段扩散**：预去噪 → 完整扩散，先粗略清理输入再精细修复，提升了严重退化场景的处理能力。
3. **线性 CFG 策略**：CFG scale 随 sigma 线性变化，在去噪早期使用较低的 CFG（保留更多多样性），后期使用较高的 CFG（增强细节一致性）。
4. **Dual CLIP 编码**：使用两个 CLIP 编码器（ViT-L + ViT-bigG）提供多尺度文本特征，增强了文本引导能力。
5. **Tile VAE**：通过 `VAEHook` 实现 VAE 的 tile 编解码，支持大分辨率图像处理。

### 2.2 工程实践

1. **混合精度策略**：分离控制 AE 和 Diffusion 的精度（`ae_dtype` / `diff_dtype`），AE 用 bf16（避免 fp16 NaN），Diffusion 用 fp16。
2. **多 GPU 设备分配**：SUPIR model 和 LLaVA 分别放在不同 GPU 上（`cuda:0` / `cuda:1`），避免显存竞争。
3. **Gradio WebUI 架构**：分步执行（Stage1 → LLaVA → Stage2），用户可在每步检查中间结果并调整参数。
4. **模型热切换**：运行时动态加载不同 checkpoint（v0-Q / v0-F），无需重启服务。
5. **Wavelet 颜色校正**：通过小波分解将修复结果的高频细节与原始图像的低频颜色信息融合，保持颜色一致性。
6. **历史记录系统**：自动保存每张图像的处理参数和结果，支持反馈收集。

### 2.3 与 SeedVR2 的技术关联度评估

- **显存优化策略**: **高** - SUPIR 的 Tile VAE（`encoder_tile_size` / `decoder_tile_size`）和多 GPU 设备分配策略与 SeedVR2 的 BlockSwap 思想高度相关。SUPIR 的 `batchify_sample` 分批处理逻辑可直接参考。
- **时序一致性处理**: **低** - SUPIR 是纯图像修复，不涉及时序处理。但其 VAE 编解码架构与 SeedVR2 的 VideoAutoencoderKLWrapper 有相似之处。
- **推理流水线设计**: **高** - SUPIR 的三阶段推理（预处理 → LLaVA → 扩散采样）与 SeedVR2 的四阶段流水线（VAE编码 → DiT采样 → VAE解码 → 后处理）在架构层面高度相似。Gradio WebUI 的分步执行设计也与 SeedVR2 的 WebUI 有共通之处。
- **WebUI 集成模式**: **高** - SUPIR 的 Gradio WebUI 是 SeedVR2 WebUI 的直接参考对象，包括参数面板设计、分步执行、中间结果展示等。

## 3. 与 integrated_app 集成的潜在切入点与建议

### 3.1 直接集成建议

1. **Tile VAE 实现参考**：SUPIR 的 `VAEHook`（`tilevae.py`）是实现 VAE tile 编解码的成熟方案。SeedVR2 的 `VideoAutoencoderKLWrapper` 可以参考其 tile 策略，特别是在处理高分辨率视频时。
2. **混合精度策略**：SUPIR 的 AE bf16 + Diffusion fp16 的分离精度控制策略，可直接应用到 SeedVR2，避免 VAE 在 fp16 下的 NaN 问题。
3. **多 GPU 设备分配**：如果 SeedVR2 未来支持多 GPU，SUPIR 的 model/LLaVA 分设备策略是直接参考。
4. **颜色校正算法**：SUPIR 的 Wavelet/AdaIn 颜色校正实现（`colorfix.py`）可直接复用到 SeedVR2 的后处理阶段。

### 3.2 间接学习建议

1. **LLaVA 集成思路**：SeedVR2 可以集成 LLaVA 自动生成图像/视频描述，作为 DiT 推理的文本条件输入，提升修复的语义一致性。
2. **线性 CFG 策略**：SeedVR2 的 DiT 推理可以借鉴线性 CFG 的思路，动态调整 CFG scale 以平衡质量和多样性。
3. **Gradio WebUI 设计**：SUPIR 的参数面板、分步执行、滑块对比等 UI 设计可直接借鉴到 SeedVR2 的 `app_server.py` 和 `templates/`。
4. **batchify 处理模式**：`batchify_sample` 和 `batchify_denoise` 的分批处理逻辑是处理大图像的标准做法。

### 3.3 实施优先级

- **P0** - Tile VAE 和混合精度策略：对 SeedVR2 的大分辨率处理和稳定性至关重要，实施难度中等。
- **P1** - 颜色校正算法（Wavelet/AdaIn）：可直接替换或补充 SeedVR2 现有的 LAB 颜色校正，提升修复质量。
- **P1** - Gradio WebUI 设计参考：指导 SeedVR2 WebUI 的交互优化。
- **P2** - LLaVA 集成：为 SeedVR2 添加文本引导能力，提升修复的语义质量，但需要额外的 GPU 资源。
- **P2** - 线性 CFG 策略：需要修改 DiT 推理逻辑，但可能显著提升输出质量。

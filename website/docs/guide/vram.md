# 显存优化与 BlockSwap

## VRAM 预检 & 参数推荐

系统内置 VRAM 预检功能，可根据输入分辨率、模型大小和可用显存自动推荐最优参数组合：

- **估算公式**：模型基线显存 + 分辨率额外开销 + 视频帧缓冲
- **推荐逻辑**：FP16 → FP8 → FP8 + BlockSwap 逐级回退，确保不 OOM
- **UI 集成**：
  - 系统状态页面提供 VRAM 估算计算器（选择模型/分辨率/帧数 → 查看推荐参数）
  - 修复工作台参数面板提供「VRAM 预检 & 推荐参数」按钮，支持一键应用推荐值
- **API 端点**：
  - `GET /api/system/gpu/vram-estimate` — 估算指定参数下的显存需求
  - `GET /api/system/gpu/recommend-params` — 获取推荐参数组合（精度/BlockSwap/tile大小/风险等级）

## GPU Block Swap 原理

推理时将 Transformer 块在 GPU / CPU 间动态换入换出：

- 当前计算所需的 Transformer 块加载至 GPU，其余暂存于 CPU 内存
- 通过 PCIe 总线低延迟交换，显著降低显存占用
- 典型效果：7B 模型配合 BlockSwap 可在 12GB 级显存上运行

### 速度影响详解

| 配置 | 相对速度 | 适用场景 |
|---|---|---|
| 无 BlockSwap | ⚡⚡⚡ 基准 | RTX 3060 (12GB)+ |
| BlockSwap (16 块) | ⚡⚡ 慢 20-30% | RTX 3050 (8GB) |
| BlockSwap (32 块) | ⚡ 慢 50-70% | GTX 1660 Super (6GB) |

## 显存配置参考

| 模型 | 精度 | 最低显存 | 备注 |
|---|---|---|---|
| SeedVR2-3B | FP8 | 8 GB | 最低门槛 |
| SeedVR2-3B | FP16 | 16 GB | 画质最佳 |
| SeedVR2-7B | FP8 | 12 GB | 可配合 BlockSwap |
| SeedVR2-7B / Sharp | FP16 | 24 GB | 画质最佳 |

### 实际显存需求参考

| 配置 | 最低显存 | 推荐内存 | 说明 |
|---|---|---|---|
| 3B + 无 BlockSwap | 8-16GB | 16GB+ | FP8 文件小，加载后显存与 FP16 相近 |
| 3B + BlockSwap (16 块) | 6GB | 16GB+ | 平衡方案 |
| 3B + BlockSwap (32 块) | 4GB | 16GB+ | 最低配置，速度慢 |

## 相关配置（config.yaml）

```yaml
inference:
  attention_mode: sdpa        # 注意力模式（sdpa / flash_attn）
  fp8_enabled: false          # 目前仅影响权重存储格式，推理仍用 FP16/FP32
  blocks_to_swap: 32          # BlockSwap 换出块数
  offload_device: cpu         # 换出目标设备
  vae_tile_size: 1024         # VAE 分块尺寸
  torch_compile:
    enabled: false            # 是否启用 torch.compile
```

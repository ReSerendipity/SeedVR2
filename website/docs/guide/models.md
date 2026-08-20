# 模型下载与选型

## 模型格式与精度

> **模型格式：`.safetensors`**（非 GGUF、非 PTH）。SeedVR2 官方与社区仓库均以
> HuggingFace `safetensors` 格式分发，本项目仅兼容该格式。
> 精度支持 **FP16（全精度，画质最佳）** 与 **FP8（E4M3FN 量化，省显存）** 两种；
> **不兼容 GGUF / INT4 / INT8 等其他量化**（这些格式在修复类扩散模型中会明显损伤画质）。

## 资源占用与效果对比

| 模型 | 精度 | 文件直链（`huggingface.co/numz/SeedVR2_comfyUI/resolve/main/…`） | 最低显存 | 约内存 | 效果 |
|---|---|---|---|---|---|
| SeedVR2-3B | FP16 | `seedvr2_ema_3b_fp16.safetensors` | 16 GB | ~12 GB | ★★★ 最佳 |
| SeedVR2-3B | FP8 | `seedvr2_ema_3b_fp8_e4m3fn.safetensors` | 8 GB | ~8 GB | ★★☆ 略降 |
| SeedVR2-7B | FP16 | `seedvr2_ema_7b_fp16.safetensors` | 24 GB | ~20 GB | ★★★ 最佳 |
| SeedVR2-7B | FP8 | `seedvr2_ema_7b_fp8_e4m3fn.safetensors` | 12 GB | ~12 GB | ★★☆ 略降 |
| SeedVR2-7B-Sharp | FP16 | `seedvr2_ema_7b_sharp_fp16.safetensors` | 24 GB | ~20 GB | ★★★ 最佳（细节增强） |
| SeedVR2-7B-Sharp | FP8 | `seedvr2_ema_7b_sharp_fp8_e4m3fn.safetensors` | 12 GB | ~12 GB | ★★☆ 略降 |

> 配套必需文件（所有模型共用）：
> `ema_vae_fp16.safetensors`（视频 VAE）、`pos_emb.pt` / `neg_emb.pt`（文本嵌入）。

### 选型建议

- 显存 ≤ 12 GB → 选 **3B FP8**（最低 8 GB）或 7B FP8 + BlockSwap
- 显存 16–24 GB → 选 **3B FP16** 或 **7B FP8**（画质/显存均衡）
- 显存 ≥ 24 GB → 选 **7B-Sharp FP16**（三档中画质与细节最好）

> 📌 "最低显存"为模型推理所需的显卡显存下限（来自 `config.yaml` 的 `model.models.*.min_vram_*_gb`）；
> "约内存"为推理时系统 RAM 占用经验值，实际以「系统状态」页监控为准。
> 显存不足时可通过 **FP8 + BlockSwap**（GPU/CPU 动态换入换出 Transformer 块）进一步压降显存需求。

## 下载方式

### 方式 A：自动下载（推荐）

```bash
python scripts/download_model.py --size 3b        # 3B + VAE + 嵌入（默认）
python scripts/download_model.py --size 7b        # 7B + VAE + 嵌入
python scripts/download_model.py --size 7b_sharp  # 7B-Sharp + VAE + 嵌入
```

- 已存在的文件会自动跳过，可随时重跑补全，支持断点续传
- 大陆网络慢：先执行 `set HF_ENDPOINT=https://hf-mirror.com` 再重跑脚本

### 方式 B：手动下载（网络更稳时）

每个文件的**完整直链**（把 `<FILE>` 替换成下表文件名，`hf-mirror.com` 为国内加速镜像）：

```text
https://huggingface.co/numz/SeedVR2_comfyUI/resolve/main/<FILE>
https://hf-mirror.com/numz/SeedVR2_comfyUI/resolve/main/<FILE>   # 国内加速
```

| 文件 | 说明 |
|---|---|
| `seedvr2_ema_3b_fp16.safetensors` | 3B DiT（FP16） |
| `seedvr2_ema_3b_fp8_e4m3fn.safetensors` | 3B DiT（FP8） |
| `seedvr2_ema_7b_fp16.safetensors` | 7B DiT（FP16） |
| `seedvr2_ema_7b_fp8_e4m3fn.safetensors` | 7B DiT（FP8） |
| `seedvr2_ema_7b_sharp_fp16.safetensors` | 7B-Sharp DiT（FP16） |
| `seedvr2_ema_7b_sharp_fp8_e4m3fn.safetensors` | 7B-Sharp DiT（FP8） |
| `ema_vae_fp16.safetensors` | 视频 VAE（所有模型共用，必须） |
| `pos_emb.pt` / `neg_emb.pt` | 文本嵌入（所有模型共用，必须） |

把下载好的文件放到 `model/` 根目录，**文件名不要改**。

> 备选来源：官方仓库 `huggingface.co/ByteDance-Seed/SeedVR2-3B` / `SeedVR2-7B`（文件名可能略异，需对照 `config.yaml` 中的 `checkpoint_*` / `vae_checkpoint` / `pos_emb` / `neg_emb` 字段）。

## 验证放对位置

最终 `model/` 根目录下应直接看到这些文件（以 3B 为例）：

```text
model/
├── seedvr2_ema_3b_fp16.safetensors
├── seedvr2_ema_3b_fp8_e4m3fn.safetensors
├── ema_vae_fp16.safetensors
├── pos_emb.pt
└── neg_emb.pt
```

> 💡 多项目共用一套模型？把 `config.yaml` 的 `model.model_source_mode` 改为 `shared` 并指定 `model.shared_models_root` 指向共享目录即可（见「模型共享模式」章节）。

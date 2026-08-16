# SageAttention 调研备忘（SeedVR2 决策记录）

> 记录日期：2026-08-16
> 状态：**已调研，未接入**（保持 `attention_mode: sdpa` + Triton/torch.compile）
> 目的：防止遗忘，为后续是否接入留下依据。

---

## 1. 官方信息

| 项 | 内容 |
|----|------|
| 官方仓库 | [thu-ml/SageAttention](https://github.com/thu-ml/SageAttention)（清华大学 thu-ml） |
| Windows/Blackwell 轮子维护者 | [woct0rdho/SageAttention](https://github.com/woct0rdho/SageAttention)（v2.2.0-windows）、[Rogala/AI_Attention](https://github.com/Rogala/AI_Attention) |
| 论文 | SageAttention (ICLR 2025, 2410.02367)；SageAttention2 (2411.10958)；SageAttention3 (NeurIPS 2025 Spotlight)；SageAttention2++ (2505.21136) |
| 定位 | **注意力加速库**，用 INT8/FP4 等量化注意力换取速度 |

## 2. 环境要求

- `python>=3.9`、`torch>=2.3.0`、`triton>=3.0.0`
- Blackwell（sm_120）需 `CUDA>=12.8`，且 **强依赖 triton-windows**
- 官方安装：`pip install sageattention==2.2.0 --no-build-isolation`（Linux）
- Windows 需社区轮子（torch 2.13/cu132 可走 cu130 别名，SageAttention 2.2.0.post6，py3.12 有 cp312）

## 3. 用法（若未来接入）

```python
from sageattention import sageattn
attn_output = sageattn(q, k, v, tensor_layout="HND", is_causal=False)
# 一行替换：
# F.scaled_dot_product_attention = sageattn
```

- 提供 `sageattn_varlen`（变长序列 API，正好匹配本项目 `FlashAttentionVarlen` 的 cu_seqlens 模式）
- 官方警告：**并非所有模型都适合一行替换**；对图像/视频模型建议**只替换 DiT 的注意力**，需改 Attention 类

## 4. 为什么本项目**决定不接入**（重要）

1. **量化损伤画质**：SageAttention 用 INT8/FP4 量化注意力换取速度，对**视频修复**这类保真度敏感任务不友好，可能让修复画质变差。
2. **训练向定位**：它主要面向 LLM 训练/长序列注意力，对 SeedVR2 的 DiT/VAE **推理**收益存疑。
3. **无现成调用点**：项目代码里没有任何 sageattention 引用；真接入需**新写集成代码**改模型 Attention 类 + 换轮子，投入产出比低。
4. **社区在 Blackwell 上也优先推荐 SageAttention 而非 flash-attn**（见下方 flash-attn 现状），但那是针对「想要 flash 级速度」的场景，本项目因 #1 仍未采纳。

## 5. 相关背景：为何 flash-attn 也无法用

- **torch 2.13 / cu132 / py3.12 没有匹配的 flash-attn 预编译轮子**（现有轮子只到 torch 2.11，且多为 py3.13）。
- 社区（Rogala/AI_Attention）明确：**Windows 上 flash-attn 无构建、不计划做**，Blackwell(SM120) 下极难编译，且不支持 Python 3.14。
- **降级 torch 到 2.11 也拿不到**：唯一 torch 2.11 轮子是 py3.13，仍不匹配 py3.12；且降级要动整套 torch 栈 + CUDA 13.2→13.0，代价大。
- Blackwell 仅支持预编译 SASS（无 PTX JIT），torch 官方 SDPA 的 FLASH/cuDNN 内核未覆盖 sm_120（实测 `No available kernel`）——见 AGENTS.md 陷阱 #11。

## 6. 当前项目的加速方案（已生效）

- **Triton**：已装 `triton-windows 3.7.1`，`torch_compile.enabled: true`（inductor）已接入并验证启动正常。
- **注意**：torch.compile 只消除算子融合/调度开销，**治不了 12GB 显存不足导致的 CPU 换页**。若瓶颈是换页，优先调 `blocks_to_swap` / `fp8_enabled`，而不是注意力加速。

## 7. 若未来想再评估

- 先确认瓶颈是**注意力**还是**显存/CPU 换页**（用性能分析定位）。
- 若确认是注意力，二选一：a) 找 torch-当前版本 + py3.12 的 SageAttention 社区轮子并只替换 DiT 注意力；b) 等 flash-attn 官方/社区补 sm_120 Windows 轮子。
- 接入前建议先做**画质对比**（SageAttention vs SDPA），量化损失可接受再上。
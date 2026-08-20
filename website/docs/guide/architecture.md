# 技术架构

## 技术栈

| 层级 | 技术 |
|---|---|
| 推理框架 | PyTorch (CUDA)、自定义 DiT、Video VAE (SD3) |
| 后端 | Python 3.12、FastAPI、Uvicorn |
| 前端 | Jinja2 模板、HTMX、原生 CSS/JS |
| 数据 | SQLite（历史记录）、SSE 实时推送 |
| 工具链 | Ruff、Black、Mypy、Pytest、Playwright |

## 核心模块

| 模块 | 说明 |
|---|---|
| `app/integrated_app/engines/` | 推理引擎（SeedVR2 核心） |
| `app/integrated_app/optimization/` | 显存/内存优化（Block Swap、Memory Manager、VAE tiled enhance） |
| `app/integrated_app/routes/` | API 路由（修复、系统、任务） |
| `app/integrated_app/services/` | 任务状态管理与事件总线 |
| `app/integrated_app/templates/` | Jinja2 页面模板 |
| `common/` | 通用工具库（扩散调度、分布式、种子等） |
| `model_lib/` | 模型定义（DiT、Video VAE） |
| `configs_3b/` / `configs_7b/` | 模型架构配置 |

## 模型架构

- **DiT 架构**：MM-DiT（多模态 Diffusion Transformer），配合 Window Attention 与 RoPE 位置编码
- **Video VAE**：基于 SD3 架构的视频 VAE，支持时间分块与内存优化
- **单步推理**：单步扩散采样，避免多步迭代开销

## 关键特性实现

- **GPU Block Swap**：推理时 GPU/CPU 间动态换入换出 Transformer 块，大幅降低显存需求
- **批量任务断点续跑**：checkpoint 存储在 `data/checkpoints/`，崩溃后可恢复
- **实时监控**：GPU 状态、系统内存、任务进度的实时 SSE 推送
- **VRAM 预检**：根据输入分辨率、模型大小和可用显存自动推荐最优参数

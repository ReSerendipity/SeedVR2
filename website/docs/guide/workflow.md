# 工作流与 ComfyUI 对比

SeedVR2 既可以在本项目以**内置管线**一键运行，也可以在 **ComfyUI** 中以节点工作流方式使用。
二者底层模型与处理流程本质一致，差异在于组织方式与使用门槛。

## 处理管线（pipeline）

本项目把以下流程固化为一条内置管线，用户无需手动连线：

```
输入（图片/视频）
  ↓
① 预处理          —— 自动 resize 到目标分辨率、64 对齐、低质量输入增强
  ↓
② VAE 编码        —— 基于 SD3 的视频 VAE，时间分块（tiled）降低显存
  ↓
③ DiT 单步修复     —— MM-DiT + Window Attention + RoPE，单步扩散采样（FP16/FP8，可开 BlockSwap）
  ↓
④ 融合 & 色彩校正   —— 分块融合（tile blend）、LAB/AdaIN 色彩校正、时间一致性
  ↓
⑤ VAE 解码        —— 分块解码回像素域，输出高分辨率帧
  ↓
输出（高清图片/视频）
```

## 与 ComfyUI 工作流对比

| 维度 | 本项目（SeedVR2-lite） | ComfyUI 工作流 |
|---|---|---|
| 组织方式 | ✅ 一键内置 pipeline | ⚠️ 需手动连线节点 |
| 模型格式 | safetensors（FP16 / FP8） | safetensors（FP16 / FP8） |
| 安装门槛 | ✅ `install.bat` / `uv sync` | ⚠️ 需装 ComfyUI + 自定义节点 |
| 显存优化 | BlockSwap / 分块 / 精度回退自动推荐 | 需单独添加 BlockSwap 配置节点 |
| 批量 / 断点 | ✅ 内置批量 + checkpoint | 需额外脚本 / 工作流编排 |
| 可视化 | 独立 Web UI（进度 / 前后对比 / GPU 监控） | 节点画布（需自行拼装） |
| 灵活性 | 固定管线，开箱即用 | 高度可自定义 |

::: tip 结论
**二者处理流程本质一致**：本项目把 ComfyUI 里需要手动连线的节点（VAE 编码 → DiT 采样 → VAE 解码）
固化为一条内置管线，并提供 Web UI、批量断点续跑与显存自动推荐——功能对等，但开箱即用；
需要深度自定义时再选用 ComfyUI 工作流。
:::

## 在演示站查看可视化

访问 [在线模拟演示](https://reserendipity.github.io/SeedVR2-lite/) → 顶部导航「工作流」，
可以交互查看处理管线图与 ComfyUI 对比（纯前端模拟，无需 GPU）。

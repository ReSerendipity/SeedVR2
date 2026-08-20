# 常见问题（FAQ）

## 启动报错模型文件未找到（FileNotFoundError）

核对文件名与位置，见 [模型下载与选型](./models)。
最常见的坑是：把权重放进了 `model/SeedVR2-3B/` 这样的子文件夹里——**必须放在 `model/` 根目录**。

## install.bat 装 PyTorch 失败

手动执行：

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

把 `cu128` 换成你驱动支持的 CUDA 版本（`nvidia-smi` 可查看），再重跑 `install.bat`。

## 端口被占用

应用会自动寻找下一个可用端口并在日志打印实际地址，以日志为准即可。

## 显存不足（OOM）

改用 FP8 模型 / 开启 BlockSwap / 降低输出分辨率。详见 [显存优化与 BlockSwap](./vram)。

## HuggingFace 下载慢

```bash
set HF_ENDPOINT=https://hf-mirror.com     # Windows
export HF_ENDPOINT=https://hf-mirror.com  # Linux/macOS
```

然后重跑下载脚本。

## 为什么演示站没有真实推理？

GitHub Pages 只能托管静态文件，无法运行 CUDA 模型。演示站用本地模拟替代推理，用于体验完整界面与流程。

## 支持哪些模型与精度？

SeedVR2-3B / 7B / 7B-Sharp，支持 FP16 与 FP8 精度；真实运行最低需要 8GB 显存（3B + FP8）。
模型格式为 **safetensors**，不兼容 GGUF / INT4 / INT8。

## 批量断点续跑如何工作？

每处理完一个文件自动保存 checkpoint，重启后检测未完成任务并恢复，已完成文件通过路径+大小+修改时间指纹跳过。

## 对比滑块左右两边为什么不一样？

为模拟「修复前」效果，左侧对同一张示例图做了 CSS 模糊/降饱和处理；真实模型会输出真正的修复结果。

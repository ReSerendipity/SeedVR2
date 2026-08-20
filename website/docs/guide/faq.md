# 常见问题（FAQ）

## 启动报错模型文件未找到（FileNotFoundError）

核对文件名与位置，见 [模型下载与选型](./models)。
最常见的坑是：把权重放进了 `model/SeedVR2-3B/` 这样的子文件夹里——**必须放在 `model/` 根目录**。

## 项目自带 Python 吗？

**不自带！** 需要自行安装 Python 3.12+，有三种方式：

**方法 1：官方 Python（推荐）**
- 下载：https://www.python.org/downloads/
- 选择 Python 3.12.x
- **安装时务必勾选"Add Python to PATH"**

**方法 2：WinPython（完全隔离）**
- 下载：https://sourceforge.net/projects/winpython/files/
- 下载 `WPy64-312101.zip`
- 解压到项目根目录（与 `install.bat` 同级）

**方法 3：虚拟环境**
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

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

SeedVR2-3B / 7B / 7B-Sharp，支持 FP16 与 FP8 精度。

**重要说明**：当前项目的 FP8 实现**仅用于权重存储格式**。推理时权重仍按 FP16/FP32 加载，因此 **FP8 模型和 FP16 模型的推理速度基本相同**。

- **BlockSwap 开启**：降低 20-70% 速度（取决于交换块数）
- **分辨率影响**：2048×2048 比 1024×1024 慢 3-4 倍  
- **FP8 vs FP16**：几乎无差异（当前未实现真正的 FP8 计算内核）

最低显存需求：
- 4GB（3B-FP8 + BlockSwap 32 块，速度慢）
- 6GB（3B-FP8 + BlockSwap 16 块，平衡方案）
- 8GB+（3B-FP8 无 BlockSwap，速度正常）

模型格式为 **safetensors**，不兼容 GGUF / INT4 / INT8。

## 批量断点续跑如何工作？

每处理完一个文件自动保存 checkpoint，重启后检测未完成任务并恢复，已完成文件通过路径+大小+修改时间指纹跳过。

## 对比滑块左右两边为什么不一样？

为模拟「修复前」效果，左侧对同一张示例图做了 CSS 模糊/降饱和处理；真实模型会输出真正的修复结果。

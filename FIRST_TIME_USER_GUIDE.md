# 🚀 第一次使用 SeedVR2-lite？从这里开始！

> **适合人群**：从未接触过 GitHub、Python 或 AI 工具的新手用户

---

## 📥 第一步：获取项目代码（二选一）

### 方法 A：下载 ZIP（推荐给不懂 Git 的用户）

1. 点击这个链接：**[Download ZIP](https://github.com/ReSerendipity/SeedVR2-lite/archive/refs/heads/main.zip)**
2. 等待下载完成（约 50-100MB，取决于网速）
3. 找到下载的 ZIP 文件，**右键 → 解压到当前文件夹**
4. 进入解压后的文件夹 `SeedVR2-lite-main`

### 方法 B：使用 Git（推荐有技术基础的用户）

```bash
git clone https://github.com/ReSerendipity/SeedVR2-lite.git
cd SeedVR2-lite
```

> 💡 **没装 Git？** 直接使用方法 A 下载 ZIP 即可！

---

## ⚙️ 第二步：检查系统要求

在继续之前，请确认你的电脑满足以下条件：

| 要求 | 说明 | 最低配置 | 推荐配置 |
|---|---|---|---|
| **操作系统** | Windows 10/11、Linux (Ubuntu 22.04+) | Windows 10 | Ubuntu 22.04+ |
| **GPU** | NVIDIA CUDA GPU（**必须**） | RTX 3050 (4GB) + BlockSwap | RTX 3060 (12GB) 或以上 |
| **显存** | FP8 + BlockSwap 可降低需求 | 4GB (会很慢) | 8GB+ |
| **Python** | **需要自行安装** Python 3.12+ | Python 3.12 | Python 3.12+ |
| **磁盘空间** | 模型 + 依赖 + 缓存 | 20GB | 50GB SSD |
| **内存** | BlockSwap 时需要足够内存 | 16GB | 32GB+ |

> ⚠️ **重要提醒**：
> - ❌ **不要**把项目放在中文路径下（如 `C:\用户\张三\...`）
> - ✅ **建议**放在简单路径下，如 `D:\SeedVR2-lite`
> - ❌ **不要**放在 OneDrive 同步文件夹（会被锁定）

---

## 🔧 第三步：安装依赖（一键搞定）

### Windows 用户

1. **右键点击** `install.bat`
2. 选择 **"以管理员身份运行"**
3. 等待安装完成（可能需要 10-30 分钟，取决于网速）
4. 看到 `Installation complete!` 表示成功

> 💡 **如果窗口闪退**：
> - 右键 `install.bat` → 编辑
> - 在最后一行添加 `pause`
> - 保存后重新运行，这样可以看到错误信息

### 常见问题


### 常见问题

#### ❌ 报错："python: command not found" 或 "No module named pip"

**解决**：项目**不自带** Python！请先安装 Python 3.12+：

**方法 1：安装官方 Python（推荐）**
- 下载地址：https://www.python.org/downloads/
- 选择 Python 3.12.x
- **安装时务必勾选 Add Python to PATH**

**方法 2：使用 WinPython（完全隔离）**
- 下载：https://sourceforge.net/projects/winpython/files/
- 下载 WPy64-312101.zip
- 解压到项目根目录（与 install.bat 同级）

如果已安装 Python 但仍报错，尝试手动指定：
```batch
WPy64-312101\python\python.exe -m pip install -r requirements.txt
```

#### ❌ 下载太慢或失败
**解决**：使用国内镜像源：
```batch
set HF_ENDPOINT=https://hf-mirror.com
install.bat
```

---

## 🎯 第四步：下载模型权重（最关键！）

**这是最容易出错的一步！** 请仔细阅读：

### 自动下载（推荐）

```batch
python scripts\download_model.py --size 3b
```

- 这会下载 3B 模型 + VAE + 文本嵌入（约 20GB）
- 下载会自动保存到 `model/` 文件夹
- 可以中断后继续下载

### 手动下载（网络不好时用）

1. 打开 [HuggingFace 模型仓库](https://huggingface.co/numz/SeedVR2_comfyUI/tree/main)
2. 下载以下文件：
   - `seedvr2_ema_3b_fp16.safetensors` (约 6GB)
   - `ema_vae_fp16.safetensors` (约 1GB)
   - `pos_emb.pt` 和 `neg_emb.pt` (各约 100KB)
3. 把所有文件放到 `model/` 文件夹（与项目根目录同级）

> 💡 **国内用户加速**：
> - 使用 [hf-mirror.com](https://hf-mirror.com) 镜像站下载
> - 或使用百度网盘（如果有分享链接）

---

## ▶️ 第五步：启动应用

1. **双击** `start.bat`
2. 等待启动（首次启动可能需要 1-2 分钟）
3. 浏览器会自动打开 http://127.0.0.1:7870
4. 如果没有自动打开，手动访问该地址

---

## 🆘 遇到错误怎么办？

### 快速自查清单

| 问题 | 可能原因 | 解决方法 |
|---|---|---|
| **双击没反应** | 需要管理员权限 | 右键 → 以管理员身份运行 |
| **ModuleNotFoundError** | 依赖未安装 | 重新运行 `install.bat` |
| **Model file not found** | 模型未下载 | 执行第四步下载模型 |
| **CUDA out of memory** | 显存不足 | 改用 FP8 模型或减小分辨率 |
| **端口被占用** | 7870 端口已使用 | 关闭其他程序或修改 `config.yaml` |

### 获取帮助

如果以上方法都无效，请提供以下信息到 [GitHub Issues](https://github.com/ReSerendipity/SeedVR2-lite/issues)：

1. **你的操作系统版本**（Win+Pause 查看）
2. **显卡型号和显存大小**（NVIDIA 控制面板查看）
3. **完整的错误信息**（复制终端输出的所有内容）
4. **你执行的命令**（例如：`start.bat` 还是 `python app_server.py`）

---

## 📚 进阶阅读

- [完整文档站](https://reserendipity.github.io/SeedVR2-lite/docs/) - 详细的安装和使用指南
- [模型选型指南](https://reserendipity.github.io/SeedVR2-lite/docs/guide/models.html) - 根据你的显卡选择合适模型
- [常见问题 FAQ](https://reserendipity.github.io/SeedVR2-lite/docs/guide/faq.html) - 更多问题的解答

---

## 🌏 Linux/macOS 用户

虽然项目主要针对 Windows，但 Linux/macOS 用户也可以运行：

```bash
# 1. 克隆或下载项目
git clone https://github.com/ReSerendipity/SeedVR2-lite.git
cd SeedVR2-lite

# 2. 安装依赖
chmod +x install.sh
./install.sh

# 3. 下载模型
python scripts/download_model.py --size 3b

# 4. 启动
./start.sh
```

> ⚠️ 注意：Linux/macOS 可能需要额外配置 CUDA 环境，详见 [官方文档](https://reserendipity.github.io/SeedVR2-lite/docs/guide/install.html)

---


## 🔧 低配显卡用户必读

如果你的显存 < 8GB，请按以下步骤优化：

### 方案 1：使用 FP8 模型（强烈推荐）

```batch
# 下载 FP8 量化版本（显存需求减半）
python scripts\download_model.py --size 3b --precision fp8
```

- 3B-FP8 文件体积更小，下载更快（但推理显存占用与 FP16 相近）
- 画质损失很小（SSIM > 0.95）

### 方案 2：开启 BlockSwap（用内存换显存）

在 `config.yaml` 中修改：
```yaml
inference:
  blockswap_enabled: true      # 开启 BlockSwap
  blocks_to_swap: 16           # 交换块数（越多越省显存，但越慢）
```

- 4GB 显存也能运行（但速度会慢 3-5 倍）
- 需要至少 16GB 系统内存

### 方案 3：降低分辨率

在 Web UI 中设置：
- 最大分辨率：1024×1024（而不是默认的 2048×2048）
- 视频帧数：减少到 16 帧（默认 32 帧）

### 显存与速度关系说明

> ⚠️ **重要说明**：当前项目的 FP8 实现**仅用于权重存储格式**，推理时仍按 FP16/FP32 计算。
> 因此**FP8 模型和 FP16 模型的推理速度基本相同**。真正影响速度的是 BlockSwap 和分辨率。

| 配置 | 最低显存 | 系统内存要求 | 相对速度 | 适用场景 |
|---|---|---|---|---|
| 3B (无 BlockSwap) | 8-16GB | 16GB+ | ⚡⚡⚡ 基准 | RTX 3060 (12GB) 或以上 |
| 3B + BlockSwap (16 块) | 6GB | 16GB+ | ⚡⚡ 慢 20-30% | RTX 3050 (8GB) |
| 3B + BlockSwap (32 块) | 4GB | 16GB+ | ⚡ 慢 50-70% | GTX 1660 Super (6GB) |
| 7B + BlockSwap (32 块) | 8GB | 32GB+ | ⚡ 慢 60-80% | RTX 3070 (8GB) |

**速度影响因素排序**（从大到小）：
1. **BlockSwap 开启**：降低 20-70%（取决于交换块数）
2. **分辨率提高**：2048×2048 比 1024×1024 慢 3-4 倍
3. **视频帧数增加**：32 帧比 16 帧慢 1.5-2 倍
4. **FP8 vs FP16**：**几乎无差异**（当前未实现真正的 FP8 计算）

> 💡 **实用建议**：
> - **显存充足 (≥12GB)**：关闭 BlockSwap，用 3B-FP16，速度最快
> - **显存中等 (8-10GB)**：开启 BlockSwap (16 块)，平衡速度与可用性
> - **显存紧张 (4-6GB)**：开启 BlockSwap (32 块) + 降低分辨率，能跑起来最重要
## ✅ 验证安装成功

运行以下命令检查所有组件是否正常：

```batch
python scripts\verify_engine.py
```

如果看到所有绿色勾 ✓，说明安装成功！🎉

---

**祝你使用愉快！** 如有问题随时联系我们。


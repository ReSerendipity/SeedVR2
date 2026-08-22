# SeedVR2-lite

![Version](https://img.shields.io/badge/version-1.3.1-blue?style=for-the-badge) ![License](https://img.shields.io/badge/license-Apache%202.0-green?style=for-the-badge) ![Python](https://img.shields.io/badge/python-3.12+-yellow?style=for-the-badge&logo=python&logoColor=white) ![GPU](https://img.shields.io/badge/GPU-NVIDIA%20CUDA-76B900?style=for-the-badge&logo=nvidia&logoColor=white) ![Models](https://img.shields.io/badge/model-3B%20%7C%207B%20%7C%207B--Sharp-ff69b4?style=for-the-badge) [![CI](https://github.com/ReSerendipity/SeedVR2-lite/actions/workflows/ci.yml/badge.svg)](https://github.com/ReSerendipity/SeedVR2-lite/actions)

**基于 SeedVR2 扩散模型的视频与图像超分辨率修复工具箱 — 独立运行的 Web UI，一键修复，无需 ComfyUI**

> **SeedVR2-lite** — A standalone video & image super-resolution toolkit powered by SeedVR2 diffusion models. One-click restoration via Web UI, no ComfyUI dependency required.

## 📖 文档

完整文档（安装 / 模型下载 / 使用指南 / FAQ）请访问：

**<https://reserendipity.github.io/SeedVR2-lite/docs/>**

> 由 `website/` 目录的 VitePress 文档站构建，与下方在线演示一并由
> `.github/workflows/pages-deploy.yml` 部署到 GitHub Pages。

## 🧪 在线模拟演示（GitHub Pages）

无需 GPU / Python / 模型权重，纯前端仿真环境即可体验完整界面与流程模拟：

**<https://reserendipity.github.io/SeedVR2-lite/>** （由 `.github/workflows/pages-deploy.yml` 自动部署 `demo/` 目录，详见 [demo/README.md](demo/README.md)）

## 🆕 新手必看

**第一次使用？完全不懂技术？**  
👉 请先阅读 [新手引导](FIRST_TIME_USER_GUIDE.md) —— 从零开始的保姆级教程，包含：
- 如何获取代码（ZIP 下载 vs Git 克隆）
- 系统要求和环境检查清单
- 一步步安装指引（含常见问题解答）
- 模型下载和启动说明

---

## 快速导航

| 想做什么 | 去哪里 |
|---|---|
| 从零开始安装运行 | [README 快速上手 ↓](#快速上手从零开始新手保姆式教程约-5-分钟) |
| 查看完整文档 | [文档站](https://reserendipity.github.io/SeedVR2-lite/docs/) |
| 在线体验界面 | [模拟演示站](https://reserendipity.github.io/SeedVR2-lite/) |
| 模型格式 / 直链 / 显存对比 | [模型下载与选型 ↓](#模型格式精度与下载直链) |

---


---

## 界面预览

*浅色主题 — 首页仪表盘 / 修复工作台 / 历史记录 / 系统状态 / 模型设置 / 多语言切换*

![首页浅色](docs/screenshots/current/light/01-home-full.png)

![修复浅色](docs/screenshots/current/light/02-restore-single-default.png)

![历史记录浅色](docs/screenshots/current/light/06-history-table-view.png)

![系统状态浅色](docs/screenshots/current/light/08-system-status-full.png)

![设置浅色](docs/screenshots/current/light/09-settings-full.png)

![多语言切换浅色](docs/screenshots/current/light/11-locale-dropdown-open.png)

---

## 技术特点

| 特性 | 说明 |
|---|---|
| **单步扩散修复** | 基于扩散模型的单步推理，高效完成视频与图像的超分辨率修复 |
| **独立运行** | 脱离 ComfyUI，通过 FastAPI + Jinja2 提供完整 Web UI |
| **多模型配置** | 支持 3B、7B、7B-Sharp 三种模型，含 FP16 与 FP8 精度 |
| **DiT 架构** | MM-DiT（多模态 Diffusion Transformer），配合 Window Attention 与 RoPE 位置编码 |
| **Video VAE** | 基于 SD3 架构的视频 VAE，支持时间分块与内存优化 |
| **GPU Block Swap** | 推理时 GPU/CPU 间动态换入换出 Transformer 块，大幅降低显存需求 |
| **批量处理** | 支持单文件上传修复和文件夹批量扫描修复 |
| **多语言界面** | 内置中文、繁体中文、英文、日文、法文五种语言 |
| **实时监控** | GPU 状态、系统内存、任务进度的实时 SSE 推送 |

---

## 安装与使用

### 环境要求

| 项目 | 要求 |
|---|---|
| **操作系统** | Windows（推荐） |
| **GPU** | NVIDIA CUDA GPU（**必须**，不支持 CPU 推理） |
| **Python** | **两种方式均可**：<br>• **推荐**：系统 Python 3.12+（需先安装依赖，见下方）<br>• **备选**：项目内置 WinPython 3.12（位于 `WPy64-312101/`，无需系统 Python） |

#### 模型格式、精度与下载直链

> **模型格式：`.safetensors`**（非 GGUF、非 PTH）。SeedVR2 官方与社区仓库均以
> HuggingFace `safetensors` 格式分发，本项目仅兼容该格式。
> 精度支持 **FP16（全精度，画质最佳）** 与 **FP8（E4M3FN 量化，省显存）** 两种；
> **不兼容 GGUF / INT4 / INT8 等其他量化**（这些格式在修复类扩散模型中会明显损伤画质）。

各模型/精度组合的资源占用与效果对比：

| 模型 | 精度 | 文件直链（`huggingface.co/numz/SeedVR2_comfyUI/resolve/main/…`） | 最低显存 | 约内存 | 效果 |
|---|---|---|---|---|---|
| SeedVR2-3B | FP16 | `seedvr2_ema_3b_fp16.safetensors` | 16 GB | ~12 GB | ★★★ 最佳 |
| SeedVR2-3B | FP8 | `seedvr2_ema_3b_fp8_e4m3fn.safetensors` | 8 GB | ~8 GB | ★★☆ 略降 |
| SeedVR2-7B | FP16 | `seedvr2_ema_7b_fp16.safetensors` | 24 GB | ~20 GB | ★★★ 最佳 |
| SeedVR2-7B | FP8 | `seedvr2_ema_7b_fp8_e4m3fn.safetensors` | 12 GB | ~12 GB | ★★☆ 略降 |
| SeedVR2-7B-Sharp | FP16 | `seedvr2_ema_7b_sharp_fp16.safetensors` | 24 GB | ~20 GB | ★★★ 最佳（细节增强） |
| SeedVR2-7B-Sharp | FP8 | `seedvr2_ema_7b_sharp_fp8_e4m3fn.safetensors` | 12 GB | ~12 GB | ★★☆ 略降 |

> 配套必需文件（所有模型共用，文件名见下方「模型权重下载（保姆级）」）：
> `ema_vae_fp16.safetensors`（视频 VAE）、`pos_emb.pt` / `neg_emb.pt`（文本嵌入）。
> 三个文件的直链：<https://huggingface.co/numz/SeedVR2_comfyUI/resolve/main/ema_vae_fp16.safetensors> 等（把文件名替换到 URL 末尾即可）。

**选型建议**：
- 显存 ≤ 12 GB → 选 **3B FP8**（最低 8 GB）或 7B FP8 + BlockSwap
- 显存 16–24 GB → 选 **3B FP16** 或 **7B FP8**（画质/显存均衡）
- 显存 ≥ 24 GB → 选 **7B-Sharp FP16**（三档中画质与细节最好）

> 📌 上表"最低显存"为模型推理所需的显卡显存下限（来自 `config.yaml` 的 `model.models.*.min_vram_*_gb`）；
> "约内存"为推理时系统 RAM 占用经验值（含权重加载与交换缓存），实际以 `系统状态` 页监控为准。
> ⚠️ **重要说明**：当前项目的 FP8 实现**仅用于权重存储格式**。推理时权重仍按 FP16/FP32 加载，
> 因此 **FP8 模型和 FP16 模型的推理速度基本相同**。真正影响速度的是 BlockSwap、分辨率和帧数。
> - **BlockSwap 开启**：降低 20-70% 速度（取决于交换块数）
> - **分辨率提高**：2048×2048 比 1024×1024 慢 3-4 倍  
> - **FP8 vs FP16**：几乎无差异（当前未实现真正的 FP8 计算内核）
>
> 显存不足时可通过 **FP8 + BlockSwap**（GPU/CPU 动态换入换出 Transformer 块）进一步压降显存需求。

#### 环境变量配置（.env）

项目根目录支持 `.env` 文件管理环境变量，模板见 `.env.example`（复制即可）：

```bash
copy .env.example .env
```

常用变量：`KMP_DUPLICATE_LIB_OK`（Intel OpenMP 兼容，一般不用改）、
`PYTORCH_CUDA_ALLOC_CONF`（`expandable_segments:True` 减少显存碎片化）。

#### 模型共享模式（shared / portable）

`config.yaml` 中 `model.model_source_mode` 支持两种模型文件存储模式：

- **portable**（默认）：模型在项目内 `model/` 目录，完全自包含
- **shared**：模型在外部共享目录（`model.shared_models_root`），多个项目共用，节省磁盘空间

```yaml
# config.yaml
model:
  model_source_mode: shared          # 切换为 shared 模式
  shared_models_root: 'D:/shared_models'  # 外部共享目录路径
```

#### VRAM 预检 & 参数推荐

内置 VRAM 预检：根据输入分辨率、模型大小和可用显存自动推荐参数组合
（FP16 → FP8 → FP8 + BlockSwap 逐级回退）。UI 提供「VRAM 预检 & 推荐参数」按钮与估算计算器。

#### 批量任务断点续跑（Checkpoint）

文件夹批量修复支持断点续跑：每处理完一个文件自动保存 checkpoint（`data/checkpoints/`），
重启后自动检测未完成批量任务并恢复，已完成文件按路径+大小+修改时间指纹跳过。

#### 国际化（i18n）

- 翻译文件采用 JSON 格式，位于 `app/integrated_app/locales/` 目录
- 支持五种语言：中文（zh）、繁体中文（zh-TW）、英文（en）、日文（ja）、法文（fr）
- 三层回退机制：指定语言 → 英文（en）回退 → key 本身（兜底）
- 支持扁平键优先查找（含点号的键不会被误判为嵌套结构）

### 🚀 快速上手：从零开始（新手保姆式教程，约 5 分钟）

> 目标：一台 Windows 电脑，从空白到打开网页完成第一次修复。全程跟着做即可，
> 不需要任何编程基础。

**第 1 步 · 安装 Python 3.12**（已装过可跳过）

1. 打开 <https://www.python.org/downloads/> 下载 Python 3.12+ 安装包
2. 双击安装，**务必勾选底部 "Add python.exe to PATH"**，然后点 `Install Now`
3. 验证：按 `Win + R` 输入 `cmd` 回车，输入 `python --version`，看到 `Python 3.12.x` 即成功

**第 2 步 · 获取本项目代码**

```bash
git clone https://github.com/ReSerendipity/SeedVR2-lite.git
cd SeedVR2-lite
```

> 没装 Git？打开仓库主页点绿色 `Code` → `Download ZIP`，解压到本地即可（Git 非必须）。

**第 3 步 · 安装依赖**

任选一种方式：

- **方式 ① 一键脚本（新手推荐）**：Windows 双击 `install.bat`；Linux/macOS 运行 `./install.sh`。
  脚本自动检测 Python → 安装 PyTorch（CUDA 版）→ 安装其余依赖，看到 `Installation complete!` 即完成。
- **方式 ② uv（开发者推荐，跨平台体验一致）**：
  ```bash
  # 安装 uv（Windows / macOS / Linux 通用）：https://docs.astral.sh/uv/
  pip install uv

  uv sync                # 读取 pyproject.toml，自动创建 .venv 并安装全部依赖（含 CUDA PyTorch）
  .venv\Scripts\activate # Windows 激活虚拟环境（macOS/Linux：source .venv/bin/activate）
  ```
  本项目已通过 `pyproject.toml` 提供完整的 uv 配置（`[project].dependencies` + `[tool.uv]`），
  torch 默认从 CUDA cu128 源安装；驱动较旧时改 `pyproject.toml` 中 `[[tool.uv.index]]` 的 url 为
  `cu121` / `cu132` 后重跑 `uv sync`。
- 若安装报错，见下方「常见问题 FAQ」。

**第 4 步 · 下载模型权重**（最关键的一步）

```bash
python scripts/download_model.py --size 3b
```

- 这是「3B 模型 + VAE + 文本嵌入」的完整最小集合，约 20 GB
- 想用更强的 7B / 7B-Sharp，把 `--size` 换成 `7b` / `7b_sharp`
- 下载慢 / 想手动下，见下方「模型权重下载（保姆级）」

**第 5 步 · 启动**

- 双击运行 `start.bat`
- 浏览器会自动打开 <http://127.0.0.1:7870>，看到界面即成功
- 没自动打开？手动访问这个地址即可

**第 6 步 · 开始修复**

- 点击「修复工作台」→ 上传一张图片或一个视频 → 点「开始修复」
- 「系统状态」页可实时查看 GPU 占用与任务进度

---

### 📦 模型权重下载（保姆级）

> 权重文件较大（3B 约 20 GB / 7B 约 40 GB），且**文件名必须与下表完全一致**、
> 必须直接放在 `model/` **根目录**（不要建子文件夹，否则应用识别不到）。

**你需要的最小文件集合**（以 3B 为例）：

| 文件 | 用途 | 必须 |
|---|---|---|
| `seedvr2_ema_3b_fp16.safetensors` | DiT 主模型（FP16 全精度，画质最好） | 二选一（推荐 FP16） |
| `seedvr2_ema_3b_fp8_e4m3fn.safetensors` | DiT 主模型（FP8 量化，省显存） | 二选一 |
| `ema_vae_fp16.safetensors` | 视频 VAE（解码输出） | ✅ |
| `pos_emb.pt` | 正向文本嵌入 | ✅ |
| `neg_emb.pt` | 负向文本嵌入 | ✅ |

> 7B：`seedvr2_ema_7b_fp16.safetensors` / `seedvr2_ema_7b_fp8_e4m3fn.safetensors`
> 7B-Sharp：`seedvr2_ema_7b_sharp_fp16.safetensors` / `seedvr2_ema_7b_sharp_fp8_e4m3fn.safetensors`

**方式 A：自动下载（推荐）**

```bash
python scripts/download_model.py --size 3b        # 3B + VAE + 嵌入（默认）
python scripts/download_model.py --size 7b        # 7B + VAE + 嵌入
python scripts/download_model.py --size 7b_sharp  # 7B-Sharp + VAE + 嵌入
```

- 已存在的文件会自动跳过，可随时重跑补全，支持断点续传
- 大陆网络慢：先执行 `set HF_ENDPOINT=https://hf-mirror.com` 再重跑脚本

**方式 B：手动下载（网络更稳时）**

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

**验证放对位置**：最终 `model/` 根目录下应直接看到这些文件（以 3B 为例）：

```text
model/
├── seedvr2_ema_3b_fp16.safetensors
├── seedvr2_ema_3b_fp8_e4m3fn.safetensors
├── ema_vae_fp16.safetensors
├── pos_emb.pt
└── neg_emb.pt
```

> 💡 多项目共用一套模型？把 `config.yaml` 的 `model.model_source_mode` 改为 `shared`
> 并指定 `model.shared_models_root` 指向共享目录即可（见「模型共享模式」章节）。

---

### ❓ 常见问题（FAQ）

1. **启动报错模型文件未找到（`FileNotFoundError`）** → 核对文件名与位置，见「模型权重下载（保姆级）」。
   最常见的坑是：把权重放进了 `model/SeedVR2-3B/` 这样的子文件夹里——必须放在根目录。
2. **`install.bat` 装 PyTorch 失败** → 手动执行
   `pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128`
   （把 `cu128` 换成你驱动支持的 CUDA 版本，`nvidia-smi` 可查看），再重跑 `install.bat`。
3. **端口被占用** → 应用会自动寻找下一个可用端口并在日志打印实际地址，以日志为准即可。
4. **显存不足（OOM）** → 改用 FP8 模型 / 开启 BlockSwap / 降低输出分辨率。
5. **HuggingFace 下载慢** → `set HF_ENDPOINT=https://hf-mirror.com`（Windows）
   或 `export HF_ENDPOINT=https://hf-mirror.com`（Linux/macOS）后重跑下载脚本。

---

### 备选运行方式

**方式一 · 使用系统 Python（推荐，节省磁盘空间）**

`start.bat` 与 `install.bat` 会优先使用系统 Python，找不到才回退到内置 WinPython。
无需其他操作，直接按上面第 3/5 步即可。

**方式二 · 使用内置 WinPython（完全隔离，无需系统 Python）**

1. 下载并解压 [WinPython 3.12](https://github.com/winpython/winpython/releases) 到项目根目录，
   确保 `WPy64-312101/python/python.exe` 存在；或运行 `scripts\setup_winpython.py` 自动配置
2. 之后流程与上方第 3/5 步完全一致

> 💡 若你只装了 WinPython 不想装系统 Python，直接运行 `install.bat` / `start.bat` 会自动回退使用它。

### Docker

```bash
docker build -t seedvr2 .
docker run --gpus all -p 7870:7870 seedvr2
```

---

## 项目结构

```
SeedVR2/
├── app/                        # 应用入口与主程序
│   ├── clean_launch.py         # 启动清理脚本
│   └── integrated_app/         # 核心应用
│       ├── app_server.py       # FastAPI 应用创建与生命周期管理
│       ├── engines/            # 推理引擎（SeedVR2 核心）
│       ├── optimization/       # 显存/内存优化（Block Swap、Memory Manager）
│       ├── routes/             # API 路由（修复、系统、任务）
│       ├── services/           # 任务状态管理与事件总线
│       ├── templates/          # Jinja2 页面模板
│       ├── static/             # CSS / JS / 字体等前端资源
│       ├── locales/            # 国际化翻译文件（zh/zh-TW/en/ja/fr）
│       └── middleware/         # CSRF 保护、错误处理中间件
├── common/                     # 通用工具库（扩散调度、分布式、种子等）
├── model_lib/                  # 模型定义
│   ├── dit/ / dit_v2/          # DiT 架构（MM-DiT、Window Attention、RoPE）
│   └── video_vae_v3/           # 视频 VAE（基于 SD3 inflation）
├── configs_3b/                 # 3B 模型配置
├── configs_7b/                 # 7B 模型配置
├── model/                      # 预训练模型存放目录
├── data/                       # 数据处理与历史数据库
├── docs/                       # 项目文档与截图
├── website/                    # VitePress 文档站源码
├── demo/                       # GitHub Pages 在线模拟演示
├── tests/                      # 测试套件（pytest + Playwright）
├── scripts/                    # 辅助脚本（模型下载 / 备份等）
├── start.bat                   # Windows 启动脚本
├── config.yaml                 # 应用配置文件
├── requirements.txt            # 运行依赖（uv 亦可从 pyproject.toml 安装）
└── pyproject.toml              # 项目元数据、依赖与工具配置（uv 兼容）
```

---

## 技术栈

| 层级 | 技术 |
|---|---|
| 推理框架 | PyTorch (CUDA)、自定义 DiT、Video VAE (SD3) |
| 后端 | Python 3.12、FastAPI、Uvicorn |
| 前端 | Jinja2 模板、HTMX、原生 CSS/JS |
| 数据 | SQLite（历史记录）、SSE 实时推送 |
| 工具链 | Ruff、Black、Mypy、Pytest、Playwright |

---

## 安全与归属声明

### ⚠️ 网络绑定警告

SeedVR2 的 Web UI **默认仅绑定 `127.0.0.1`**（`config.yaml` 中 `server.host`），不对外暴露。
**严禁将 `server.host` 修改为 `0.0.0.0` 或公网 IP**，本应用不含用户认证与权限隔离机制，
直接暴露到公网将导致：
- 任意第三方调用推理 API 占用 GPU 资源
- 通过上传接口投递恶意文件
- 下载 outputs/ 与 uploads/ 目录内容

如需局域网共享，请在反向代理（Nginx/Caddy）后增加 Basic Auth，并启用 HTTPS。

### ©️ 归属权与版权

- **版权所有**: Copyright 2024-2026 ReSerendipity
- **开源协议**: [Apache License 2.0](LICENSE)
- **版权声明位置**:
  - [LICENSE](LICENSE) 附录版权行
  - UI 设置页版权区块（通过 `app/integrated_app/locales/*.json` 的 `settings.copyright_notice` 渲染）
  - 核心 Python 源文件 SPDX 版权头

**根据 Apache 2.0 协议第 4 条，任何再分发或衍生作品必须：**
1. 保留本项目的版权声明与 LICENSE 文件副本
2. 标注修改过的文件（声明已变更）
3. 保留所有 NOTICE 文件中的归属信息（如有）
4. 不得移除 UI 设置页、启动日志中展示的 "ReSerendipity" 版权归属

## 合规说明

使用本项目请遵守 [USER_AGREEMENT.md](USER_AGREEMENT.md)。模型权重（SeedVR/SeedVR2）为 Apache 2.0；FFmpeg 为本地开发依赖，不随仓库分发，由用户自行安装（详见 NOTICE）。


### ⚖️ 独立第三方声明

- 本项目是**独立的第三方社区工具**，基于字节跳动 Seed 团队与南洋理工大学 S-Lab 联合开源的 **SeedVR2** 模型（Apache-2.0）构建，与字节跳动及其 Seed 团队**无隶属、赞助或官方合作关系**；对 "SeedVR2" 名称的使用仅为描述性引用，该名称与模型权重的知识产权归原作者所有。
- 本项目与 seedvr2.com / seedvr2.net / seedvr2.ai / seedvr2.app 等**付费商业站点无任何关系**；本项目完全免费开源，不提供积分、订阅等任何付费模式。
- 模型权重仅从官方来源下载：Hugging Face 官方仓库 `ByteDance-Seed/SeedVR2-3B` 与 `ByteDance-Seed/SeedVR2-7B`（7B-Sharp 亦取自该官方 7B 仓库），请勿从未知来源获取权重。
## 许可证

本项目采用 [Apache License 2.0](LICENSE) 开源协议。
版权所有 Copyright 2024-2026 ReSerendipity。


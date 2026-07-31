# SeedVR2

![Version](https://img.shields.io/badge/version-1.0.0-blue?style=for-the-badge) ![License](https://img.shields.io/badge/license-Apache%202.0-green?style=for-the-badge) ![Python](https://img.shields.io/badge/python-3.12+-yellow?style=for-the-badge&logo=python&logoColor=white) ![GPU](https://img.shields.io/badge/GPU-NVIDIA%20CUDA-76B900?style=for-the-badge&logo=nvidia&logoColor=white) ![Models](https://img.shields.io/badge/model-3B%20%7C%207B%20%7C%207B--Sharp-ff69b4?style=for-the-badge)

**基于 SeedVR2 扩散模型的视频与图像超分辨率修复工具箱 — 独立运行的 Web UI，一键修复，无需 ComfyUI**

> **SeedVR2** — A standalone video & image super-resolution toolkit powered by SeedVR2 diffusion models. One-click restoration via Web UI, no ComfyUI dependency required.

---

## 界面预览

*深色主题 — 首页仪表盘 / 修复工作台 / 系统状态*

![首页深色](docs/screenshots/current/dark/01-home-full.png)

![修复深色](docs/screenshots/current/dark/02-restore-default.png)

![系统状态深色](docs/screenshots/current/dark/07-system-status-full.png)

*浅色主题 — 首页仪表盘 / 修复工作台*

![首页浅色](docs/screenshots/current/light/01-home-full.png)

![修复浅色](docs/screenshots/current/light/02-restore-default.png)

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
| **多语言界面** | 内置中文、英文、日文、法文四种语言 |
| **实时监控** | GPU 状态、系统内存、任务进度的实时 SSE 推送 |

---

## 安装与使用

### 环境要求

| 项目 | 要求 |
|---|---|
| **操作系统** | Windows（推荐） |
| **GPU** | NVIDIA CUDA GPU（**必须**，不支持 CPU 推理） |
| **Python** | 项目内置 WinPython 3.12（位于 `WPy64-312101/`），无需系统 Python |

#### 显存需求

| 模型 | 精度 | 最低显存 |
|---|---|---|
| SeedVR2-3B | FP16 | 16 GB |
| SeedVR2-3B | FP8 | 8 GB |
| SeedVR2-7B | FP16 | 24 GB |
| SeedVR2-7B | FP8 | 12 GB |
| SeedVR2-7B-Sharp | FP16 | 24 GB |
| SeedVR2-7B-Sharp | FP8 | 12 GB |

### 快速启动

1. 下载并解压 [WinPython 3.12](https://github.com/winpython/winpython/releases) 到项目根目录，确保 `WPy64-312101/python/python.exe` 存在
2. 将预训练模型放入 `pretrained_models/` 目录
3. 双击运行：

```bat
start.bat
```

4. 浏览器自动打开 `http://127.0.0.1:7870`

### Docker

```bash
docker build -t seedvr2 .
docker run --gpus all -p 7870:7870 seedvr2
```

---

## 项目结构

```
SeedVR2/
├── bin/                        # 应用入口与主程序
│   ├── clean_launch.py         # 启动清理脚本
│   └── integrated_app/         # 核心应用
│       ├── app_server.py       # FastAPI 应用创建与生命周期管理
│       ├── engines/            # 推理引擎（SeedVR2 核心）
│       ├── optimization/       # 显存/内存优化（Block Swap、Memory Manager）
│       ├── routes/             # API 路由（修复、系统、任务）
│       ├── services/           # 任务状态管理与事件总线
│       ├── templates/          # Jinja2 页面模板
│       ├── static/             # CSS / JS / 字体等前端资源
│       ├── locales/            # 国际化翻译文件（zh/en/ja/fr）
│       └── middleware/         # CSRF 保护、错误处理中间件
├── common/                     # 通用工具库（扩散调度、分布式、种子等）
├── models/                     # 模型定义
│   ├── dit/ / dit_v2/          # DiT 架构（MM-DiT、Window Attention、RoPE）
│   └── video_vae_v3/           # 视频 VAE（基于 SD3 inflation）
├── configs_3b/                 # 3B 模型配置
├── configs_7b/                 # 7B 模型配置
├── pretrained_models/          # 预训练模型存放目录
├── data/                       # 数据处理与历史数据库
├── docs/                       # 项目文档与截图
├── tests/                      # 测试套件（pytest + Playwright）
├── start.bat                   # Windows 启动脚本
├── config.yaml                 # 应用配置文件
└── pyproject.toml              # 项目元数据与工具配置
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

## 许可证

本项目采用 [Apache License 2.0](LICENSE) 开源协议。

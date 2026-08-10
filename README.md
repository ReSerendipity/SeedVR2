# SeedVR2

![Version](https://img.shields.io/badge/version-1.0.0-blue?style=for-the-badge) ![License](https://img.shields.io/badge/license-Apache%202.0-green?style=for-the-badge) ![Python](https://img.shields.io/badge/python-3.12+-yellow?style=for-the-badge&logo=python&logoColor=white) ![GPU](https://img.shields.io/badge/GPU-NVIDIA%20CUDA-76B900?style=for-the-badge&logo=nvidia&logoColor=white) ![Models](https://img.shields.io/badge/model-3B%20%7C%207B%20%7C%207B--Sharp-ff69b4?style=for-the-badge) [![CI](https://github.com/ReSerendipity/SeedVR2/actions/workflows/ci.yml/badge.svg)](https://github.com/ReSerendipity/SeedVR2/actions)

**基于 SeedVR2 扩散模型的视频与图像超分辨率修复工具箱 — 独立运行的 Web UI，一键修复，无需 ComfyUI**

> **SeedVR2** — A standalone video & image super-resolution toolkit powered by SeedVR2 diffusion models. One-click restoration via Web UI, no ComfyUI dependency required.

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

#### 显存需求

| 模型 | 精度 | 最低显存 |
|---|---|---|
| SeedVR2-3B | FP16 | 16 GB |
| SeedVR2-3B | FP8 | 8 GB |
| SeedVR2-7B | FP16 | 24 GB |
| SeedVR2-7B | FP8 | 12 GB |
| SeedVR2-7B-Sharp | FP16 | 24 GB |
| SeedVR2-7B-Sharp | FP8 | 12 GB |

#### 环境变量配置（.env）

项目根目录支持 `.env` 文件管理环境变量，模板见 `.env.example`：

```bash
# 复制模板并按需修改
copy .env.example .env
```

常用环境变量：
- `KMP_DUPLICATE_LIB_OK` — Intel OpenMP 重复库兼容（一般不需要改）
- `PYTORCH_CUDA_ALLOC_CONF` — PyTorch 显存分配器配置（`expandable_segments:True` 减少碎片化）
- `PYTORCH_ALLOC_CONF` — 同上，备用键名

> 显式系统环境变量优先级高于 `.env` 文件，不会覆盖用户在 shell 中设置的值。

#### 模型共享模式（shared / portable）

支持两种模型文件存储模式，通过 `config.yaml` 中 `model.model_source_mode` 配置：

- **portable**（默认）：模型文件存储在项目内 `pretrained_models/` 目录，完全自包含
- **shared**：模型文件存储在外部共享目录（`model.shared_models_root`），多个项目（SeedVR2 / TTS / Image）可共用同一套模型文件，节省磁盘空间

```yaml
# config.yaml
model:
  model_source_mode: shared          # 切换为 shared 模式
  shared_models_root: 'D:/shared_models'  # 外部共享目录路径
```

#### VRAM 预检 & 参数推荐

系统内置 VRAM 预检功能，可根据输入分辨率、模型大小和可用显存自动推荐最优参数组合：

- **估算公式**：模型基线显存 + 分辨率额外开销 + 视频帧缓冲
- **推荐逻辑**：FP16 → FP8 → FP8 + BlockSwap 逐级回退，确保不 OOM
- **UI 集成**：
  - 系统状态页面提供 VRAM 估算计算器（选择模型/分辨率/帧数 → 查看推荐参数）
  - 修复工作台参数面板提供"VRAM 预检 & 推荐参数"按钮，支持一键应用推荐值
- **API 端点**：
  - `GET /api/system/gpu/vram-estimate` — 估算指定参数下的显存需求
  - `GET /api/system/gpu/recommend-params` — 获取推荐参数组合（精度/BlockSwap/tile大小/风险等级）

#### 批量任务断点续跑（Checkpoint）

文件夹批量修复支持断点续跑，中途崩溃或关闭后可恢复：

- Checkpoint 文件存储在 `data/checkpoints/` 目录（可通过 `config.yaml` 配置）
- 每处理完一个文件自动保存进度（`runtime.task.checkpoint_every` 控制保存频率）
- 重启应用后自动检测未完成的批量任务，可选择恢复
- 已完成文件通过路径 + 文件大小 + 修改时间指纹匹配，避免重复处理

```yaml
# config.yaml
runtime:
  task:
    checkpoint_dir: data/checkpoints  # checkpoint 存储目录
    checkpoint_every: 1               # 每处理 N 个文件保存一次
    auto_recover: false               # 启动时是否自动恢复未完成任务
```

#### 国际化（i18n）

- 翻译文件采用 JSON 格式，位于 `bin/integrated_app/locales/` 目录
- 支持五种语言：中文（zh）、繁体中文（zh-TW）、英文（en）、日文（ja）、法文（fr）
- 三层回退机制：指定语言 → 英文（en）回退 → key 本身（兜底）
- 支持扁平键优先查找（含点号的键不会被误判为嵌套结构）

### 快速启动

#### 方式一：使用系统 Python（推荐，节省磁盘空间）

1. 安装 [Python 3.12+](https://www.python.org/downloads/)，安装时勾选 **"Add Python to PATH"**
2. 验证安装：打开命令提示符，运行 `python --version` 应显示 3.12.x
3. 双击运行 `install.bat`（会自动检测系统 Python 并安装依赖）
4. 将预训练模型放入 `pretrained_models/` 目录
5. 双击运行：

```bat
start.bat
```

6. 浏览器自动打开 `http://127.0.0.1:7870`

> 💡 **优势**：多个项目共享一套 Python 和依赖，避免每个项目都有几百 MB 到几 GB 的重复 Python 环境。

---

#### 方式二：使用内置 WinPython（完全隔离，无需系统 Python）

1. 下载并解压 [WinPython 3.12](https://github.com/winpython/winpython/releases) 到项目根目录，确保 `WPy64-312101/python/python.exe` 存在
   - 或运行 `scripts\setup_winpython.py` 自动下载配置
2. 双击运行 `install.bat`（会检测 WinPython 并安装依赖到 WinPython 内部）
3. 将预训练模型放入 `pretrained_models/` 目录
4. 双击运行：

```bat
start.bat
```

5. 浏览器自动打开 `http://127.0.0.1:7870`

> 💡 **提示**：`start.bat` 和 `install.bat` 会**优先使用系统 Python**，若找不到系统 Python 才回退到 WinPython。如果你只想用 WinPython，请确保没有安装系统 Python，或手动修改脚本的检测顺序。

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
│       ├── locales/            # 国际化翻译文件（zh/zh-TW/en/ja/fr）
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

## 安全与归属声明

### ⚠️ 网络绑定警告

SeedVR2 的 Web UI **默认仅绑定 `127.0.0.1`**（`config.yaml` 中 `server.host`），不对外暴露。
**严禁将 `server.host` 修改为 `0.0.0.0` 或公网 IP**，本应用不含用户认证与权限隔离机制，
直接暴露到公网将导致：
- 任意第三方调用推理 API 占用 GPU 资源
- 通过上传接口投递恶意文件
- 下载 outputs/ 与 uploads/ 目录内容

如需局域网共享，请在反向代理（Nginx/Caddy）后增加 Basic Auth，并启用 HTTPS。

### 🔒 模型文件与完整性

- 所有模型权重请从官方可信来源下载（ByteDance-Seed HuggingFace 组织）
- 切勿加载来源不明的 `.safetensors`、`.pt`、`.bin` 文件
- pickle 格式的 `.pt`  checkpoint 存在任意代码执行风险（CWE-502），
  本项目框架层已通过 `weights_only=True` 优先加载，并在必要回退时打印严重安全告警

### ©️ 归属权与版权

- **版权所有**: Copyright 2024-2026 ReSerendipity
- **开源协议**: [Apache License 2.0](LICENSE)
- **版权声明位置**:
  - [LICENSE](LICENSE) 附录版权行
  - UI 设置页版权区块（通过 `bin/integrated_app/locales/*.yaml` 的 `settings.copyright_notice` 渲染）
  - 核心 Python 源文件 SPDX 版权头

**根据 Apache 2.0 协议第 4 条，任何再分发或衍生作品必须：**
1. 保留本项目的版权声明与 LICENSE 文件副本
2. 标注修改过的文件（声明已变更）
3. 保留所有 NOTICE 文件中的归属信息（如有）
4. 不得移除 UI 设置页、启动日志中展示的 "SeedVR2" 品牌名与 "ReSerendipity" 版权归属

### ™️ 商标保护

"SeedVR2" 文字标识及 Logo 是 ReSerendipity 的品牌商标，计划/已申请商标注册。
未经授权，不得在以下场景中使用 "SeedVR2" 品牌标识：
- 第三方产品或服务的命名、宣传
- 应用商店、PyPI、Docker Hub 等平台的仿冒包名
- 融资材料、项目申报、商业宣传

如发现商标侵权行为，可通过输出图像中嵌入的数字水印（DCT 频域）作为技术举证手段。

### 🔐 完整性验证

本项目提供多层完整性保护：
- **模型权重 SHA256 校验**: 在 `config.yaml` 中配置 `sha256_*` 字段，加载前自动验证
- **核心模块启动自检**: `integrity_manifest.json` 记录核心安全模块哈希，启动时自动比对
- **输出数字水印**: 推理输出图像/视频自动嵌入不可感知 DCT 频域水印，可溯源到 SeedVR2
- **Release GPG 签名**: GitHub Release 自动生成 SHA256SUMS + GPG 签名，下载后可验证
- **依赖版本锁定**: `requirements-lock.txt` 固定所有依赖版本，支持 `--require-hashes` 哈希验证

---

## 许可证

本项目采用 [Apache License 2.0](LICENSE) 开源协议。
版权所有 Copyright 2024-2026 ReSerendipity。

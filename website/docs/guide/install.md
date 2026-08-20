# 安装与运行

## 环境要求

| 项目 | 要求 |
|---|---|
| **操作系统** | Windows（推荐），也支持 Linux / macOS |
| **GPU** | NVIDIA CUDA GPU（**必须**，不支持 CPU 推理） |
| **Python** | 系统 Python 3.12+，或项目内置 WinPython 3.12（`WPy64-312101/`） |

## 环境变量配置（.env）

项目根目录支持 `.env` 文件管理环境变量，模板见 `.env.example`：

```bash
# 复制模板并按需修改
copy .env.example .env
```

常用环境变量：
- `KMP_DUPLICATE_LIB_OK` — Intel OpenMP 重复库兼容（一般不需要改）
- `PYTORCH_CUDA_ALLOC_CONF` — PyTorch 显存分配器配置（`expandable_segments:True` 减少碎片化）

> 显式系统环境变量优先级高于 `.env` 文件，不会覆盖用户在 shell 中设置的值。

## 模型共享模式（shared / portable）

支持两种模型文件存储模式，通过 `config.yaml` 中 `model.model_source_mode` 配置：

- **portable**（默认）：模型文件存储在项目内 `model/` 目录，完全自包含
- **shared**：模型文件存储在外部共享目录（`model.shared_models_root`），多个项目可共用同一套模型文件，节省磁盘空间

```yaml
# config.yaml
model:
  model_source_mode: shared          # 切换为 shared 模式
  shared_models_root: 'D:/shared_models'  # 外部共享目录路径
```

## 备选运行方式

**方式一 · 使用系统 Python（推荐，节省磁盘空间）**

`start.bat` 与 `install.bat` 会优先使用系统 Python，找不到才回退到内置 WinPython。无需其他操作。

**方式二 · 使用内置 WinPython（完全隔离，无需系统 Python）**

1. 下载并解压 [WinPython 3.12](https://github.com/winpython/winpython/releases) 到项目根目录，
   确保 `WPy64-312101/python/python.exe` 存在；或运行 `scripts\setup_winpython.py` 自动配置
2. 之后流程与上方完全一致

## Docker

```bash
docker build -t seedvr2 .
docker run --gpus all -p 7870:7870 seedvr2
```

## 项目结构

```
SeedVR2/
├── app/                        # 应用入口与主程序
│   └── integrated_app/         # 核心应用（FastAPI + 引擎 + 路由 + 模板）
├── common/                     # 通用工具库（扩散调度、分布式、种子等）
├── model_lib/                  # 模型定义（DiT / Video VAE）
├── configs_3b/ / configs_7b/   # 模型配置
├── model/                      # 预训练模型存放目录
├── data/                       # 数据处理与历史数据库
├── docs/                       # 项目文档与截图
├── tests/                      # 测试套件（pytest + Playwright）
├── scripts/                    # 辅助脚本（模型下载 / 备份等）
├── start.bat / start.sh        # 启动脚本
├── config.yaml                 # 应用配置文件
└── pyproject.toml              # 项目元数据与依赖（uv 兼容）
```

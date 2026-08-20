# 快速开始（5 分钟）

> 目标：一台 Windows 电脑，从空白到打开网页完成第一次修复。全程跟着做即可，不需要任何编程基础。

## 第 1 步 · 安装 Python 3.12（已装过可跳过）

1. 打开 <https://www.python.org/downloads/> 下载 Python 3.12+ 安装包
2. 双击安装，**务必勾选底部 "Add python.exe to PATH"**，然后点 `Install Now`
3. 验证：按 `Win + R` 输入 `cmd` 回车，输入 `python --version`，看到 `Python 3.12.x` 即成功

## 第 2 步 · 获取本项目代码

```bash
git clone https://github.com/ReSerendipity/SeedVR2-lite.git
cd SeedVR2-lite
```

> 没装 Git？打开仓库主页点绿色 `Code` → `Download ZIP`，解压到本地即可（Git 非必须）。

## 第 3 步 · 安装依赖

任选一种方式：

**方式 ① 一键脚本（新手推荐）**

- Windows 双击 `install.bat`；Linux/macOS 运行 `./install.sh`
- 脚本自动检测 Python → 安装 PyTorch（CUDA 版）→ 安装其余依赖
- 看到 `Installation complete!` 即完成

**方式 ② uv（开发者推荐，跨平台体验一致）**

```bash
# 安装 uv（Windows / macOS / Linux 通用）：https://docs.astral.sh/uv/
pip install uv

uv sync                # 读取 pyproject.toml，自动创建 .venv 并安装全部依赖（含 CUDA PyTorch）
.venv\Scripts\activate # Windows 激活虚拟环境（macOS/Linux：source .venv/bin/activate）
```

本项目已通过 `pyproject.toml` 提供完整的 uv 配置（`[project].dependencies` + `[tool.uv]`），
torch 默认从 CUDA cu128 源安装；驱动较旧时改 `pyproject.toml` 中 `[[tool.uv.index]]` 的 url 为
`cu121` / `cu132` 后重跑 `uv sync`。

## 第 4 步 · 下载模型权重（最关键的一步）

```bash
python scripts/download_model.py --size 3b
```

- 这是「3B 模型 + VAE + 文本嵌入」的完整最小集合，约 20 GB
- 想用更强的 7B / 7B-Sharp，把 `--size` 换成 `7b` / `7b_sharp`
- 下载慢 / 想手动下，见 [模型下载与选型](./models)

## 第 5 步 · 启动

- Windows 双击运行 `start.bat`；Linux/macOS 运行 `./start.sh`
- 浏览器会自动打开 <http://127.0.0.1:7870>，看到界面即成功
- 没自动打开？手动访问这个地址即可

## 第 6 步 · 开始修复

- 点击「修复工作台」→ 上传一张图片或一个视频 → 点「开始修复」
- 「系统状态」页可实时查看 GPU 占用与任务进度

---

::: tip 安装报错？
见 [常见问题（FAQ）](./faq)，或直接到 [GitHub Issues](https://github.com/ReSerendipity/SeedVR2-lite/issues) 提问。
:::

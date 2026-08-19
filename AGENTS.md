# Seedvr2 AGENTS.md — AI 辅助开发指南

> 🧬 **自进化协议版本**：v1.22  
> 📅 **最后更新日期**：2026-08-19  
> 🎯 **对应项目版本**：v1.0.0（Apache-2.0 开源协议）

---

## ⚠️ 🤖 Agent 行为契约（自进化协议 · 必须严格遵守）

AI Agent 打开本文件后的 **第一件事** 是执行下面的「🧪 自进化自检清单」，并遵守以下 5 条铁律：

### 🔴 5 条自进化铁律
1. **🔄 同步规则（Synchronize First）**：如果发现项目实际情况（目录结构、依赖版本、技术栈、配置文件名等）与本文件描述 **不一致** → **立即更新本文件**，不要只改代码不改 AGENTS.md。这是最高优先级的规则。
2. **📝 坑点累积（Gotchas Accumulation）**：每次修复 Bug / 踩坑后（哪怕是很小的坑），**必须** 追加一条到第 11 节「常见陷阱 / 注意事项」，写清楚：触发场景、现象/报错、正确做法、首次发现日期。
3. **📚 SOP 累积（SOP Accumulation）**：每次完成一个「本文件现有 SOP 没覆盖」的典型开发任务后，**必须** 把步骤整理成新 SOP 追加到第 12 节「典型 AI 开发场景 SOP」。
4. **✅ 自检流程（Self-Check on Startup）**：每次打开本文件准备工作前，**必须** 先运行下面的「🧪 自进化自检清单」，逐项核对，有任何一项不符先修正 AGENTS.md 再干活。
5. **🏷️ 版本递增（Version Increment）**：每次更新本文件内容后，**必须** 做三件事：① 文件顶部「自进化协议版本号」+0.1（小改）或 +1.0（大改/框架调整）；② 更新「最后更新日期」；③ 在文件末尾「📋 自进化修订记录表」追加一行记录。

### 🧪 自进化自检清单（每次启动工作前必跑）
- [ ] 目录结构（`api/`、`common/`、`core/`、`engines/`、`security/`、`routes/`、`model_lib/`）是否和第 3 节模块边界描述一致？
- [ ] 禁区目录表（model_lib/、common/、configs_*）是否仍适用？如有新增禁区目录，是否已更新第 3.2 节？
- [ ] 上次工作是否踩了新坑？如果是，是否已追加到第 11 节常见陷阱？
- [ ] 新增的路由是否已按 auto_register 正确命名（`xxxx_router.py`）？如果是，是否已更新第 3.3 节说明？
- [ ] 是否修改了 `config.yaml` 结构或新增配置项？如果是，是否已更新 `config.example.yaml` + 本文件第 7 节启动命令说明？
- [ ] 上次更新是否正确递增了自进化协议版本号 + 追加了修订记录表？

---

## 1. 项目概览

> **Seedvr2**：VR 场景多模态内容生成后端服务。  
> 定位：高性能、安全合规的 AI 推理网关，支持本地多种模型引擎的统一 API 接入。  
> 开源协议：**Apache-2.0**  
> 技术栈：**Python 3.11+ + FastAPI 0.115+ + Uvicorn + Pydantic v2 + SQLAlchemy 2.0 + AioSQLite + PyYAML** + 自研安全模块（PathGuard + CSRF + 完整性校验 + 水印嵌入）  
> 入口文件：`app/clean_launch.py`（推荐）或 `python -m uvicorn app.integrated_app.app_server:app`
> 默认监听：`http://127.0.0.1:7870`（禁止 `host="0.0.0.0"`，见第 11 节常见陷阱 #3）

> ⚠️ **实际结构修正（2026-08-14）**：以上目录结构（`api/`、`core/`、`engines/`、`configs/`）
> 为本仓库早期规划的目标结构，与当前实际实现不符。**当前实际入口与结构**：
> - 实际入口：`app/clean_launch.py`（推荐）或 `python -m uvicorn app.integrated_app.app_server:app`
> - 实际应用代码：`app/integrated_app/`（app_server.py + routes/ + engines/ + optimization/ + security/ 等）
> - 实际配置文件：**项目根目录 `config.yaml`**（无 `configs/` 目录；`configs_3b/`、`configs_7b/` 是模型架构配置）
> - 实际配置加载：`app/integrated_app/config.py`（`get_app_config()`）+ `config_models.py`（Pydantic）
> - 实际监听：`http://127.0.0.1:7870`
> 第 3 节「模块边界」、第 7 节「启动命令」、第 13 节「API 响应规范」仍以实际结构为准，
> 遇到不一致时以代码为准、并更新本文件。

---

## 2. 代码风格 & 格式约定

### 2.1 工具配置（pyproject.toml 已统一配置）
| 工具 | 用途 | 配置位置 |
|------|------|---------|
| **Ruff** | Lint + Import Sort | `[tool.ruff]`：`line-length = 100`，`target-version = "py311"`，select = ["E4", "E7", "E9", "F", "I", "W", "UP006~UP035"] |
| **Black** | 代码格式化 | `[tool.black]`：和 Ruff line-length 对齐，100 字符 |
| **Mypy** | 类型检查 | `[tool.mypy]`：`strict = false`（渐进式严格，核心文件逐步加 `# mypy: strict`） |

### 2.2 命名规则
- **文件/模块**：`snake_case.py`
- **类/异常**：`PascalCase`（例：`ModelLoadError(Exception)`）
- **函数/方法/变量**：`snake_case`（例：`async def generate_scene()`）
- **常量/枚举值**：`UPPER_SNAKE_CASE`（例：`MAX_IMAGE_SIZE = 4096`）
- **私有成员**：单下划线前缀 `_xxx`（模块级函数、内部方法）
- **豁免目录（跳过 ruff/mypy 检查）**：`model_lib/`、`engines/_legacy/`、`configs_local/`（第三方代码或研究代码，不要求风格）

### 2.3 Import 顺序（严格遵守，Ruff I 规则自动校验）
```python
# 1. 标准库（import os / import asyncio / from typing import Annotated）
# 2. 第三方库（import uvicorn / from fastapi import APIRouter）
# 3. 本地项目（from common.config import settings / from security.path_guard import safe_join）
```
> Ruff `isort` 配置为 `force-single-line = true`，禁止 `from fastapi import APIRouter, Depends, HTTPException` 这种一行多个 import。

### 2.4 类型注解（Mypy 要求）
- 所有 public 函数 / 方法必须加参数 + 返回值类型注解，例：
  ```python
  async def generate_scene(prompt: str, steps: int = 20) -> dict[str, object]:
      ...
  ```
- FastAPI 路由函数的 Pydantic 模型入参不需要重复写 `Annotated[XxxModel, Body()]`，直接 `def route(body: XxxModel)` 即可（Pydantic v2 默认行为）

---

## 3. 模块边界 & 关键规则（🚫 跨层引用严格禁止）

### 3.1 目录结构 & 职责
```
Seedvr2/
├── api/                 ← FastAPI 入口（只做组装，不写业务逻辑）
│   ├── main.py          ← create_app() + lifespan（启动时预加载引擎）
│   ├── clean_launch.py  ← 推荐启动入口（含健康检查 + 环境自检）
│   └── routes/          ← 路由：每个模块一个 xxx_router.py，auto_register 自动加载
├── common/              ← 公共基础设施（config.py / logger.py / exceptions.py / i18n.py）
│   ├── config.py        ← Pydantic BaseSettings 读 config.yaml（单例）
│   ├── i18n.py          ← gettext 5 种语言（中/繁/英/日/韩），i18n 规范见第 8 节
│   └── security.py      ← 通用安全工具（CSRF token 生成、密码哈希）
├── core/                ← 业务逻辑层（services + repositories + workflows）
│   ├── services/        ← 业务服务（SceneGenerateService / HistoryService）
│   ├── repositories/    ← 数据访问（HistoryRepoDB / CacheRepo）
│   └── workflows/       ← 编排多步任务（VR 场景生成 pipeline）
├── engines/             ← 模型引擎抽象层（接口 + 各引擎实现）
│   ├── base.py          ← AbstractEngineProtocol（Protocol，不是 ABC）
│   ├── auto_register.py ← 自动发现 engines/ 下所有实现并注册到 Registry
│   ├── diffusion_engine/
│   ├── llm_engine/
│   └── _legacy/         ← 旧引擎实现冻结，禁止修改
├── model_lib/           ← 第三方模型权重 & 代码（🚫 禁区：AI 不允许自动修改）
│   ├── diffusion/
│   └── llm/
├── security/            ← 安全模块（独立层，不能依赖 core/engines 以外的业务层）
│   ├── path_guard.py    ← 路径安全校验（防路径穿越，所有文件 IO 必须过 safe_join）
│   ├── csrf.py          ← CSRF 中间件（SSE 接口 + 表单提交必须校验）
│   ├── integrity.py     ← SHA-256 文件完整性校验（模型文件 + 输出作品）
│   └── watermark.py     ← 不可见水印嵌入（所有生成图像必须加水印）
├── db/                  ← 数据库
│   └── history.db       ← AioSQLite，存生成历史 + 用户作品元数据
├── configs/             ← 全局配置（config.yaml）
│   ├── config.yaml      ← 实际配置（本地特定，不提交 Git）
│   └── config.example.yaml ← 配置模板（提交 Git）
├── tests/               ← 测试（第 4 节详细说明）
├── scripts/             ← 辅助脚本（模型下载 / 完整性校验 / DB 迁移 / 备份）
├── install.bat / start.bat   ← Windows 一键脚本
├── install.sh  / start.sh    ← Linux/macOS 一键脚本
├── requirements.txt          ← 生产依赖
├── requirements-dev.txt      ← 开发依赖（pytest + ruff + mypy + coverage）
├── requirements-lock.txt     ← 锁定依赖版本（generate_lock.py 生成）
└── pyproject.toml            ← 项目元数据 + 工具配置
```

### 3.2 禁区目录（禁止 AI 自动修改，必须人工确认）
| 目录 / 文件 | 原因 | 例外情况 |
|------------|------|---------|
| `model_lib/` 整个目录 | 第三方模型权重和研究代码，修改会直接影响生成效果和合规性 | 用户明确要求时，可以只改配置类（模型路径、超参数），不动模型推理代码 |
| `common/config.py` + `configs/config.yaml` | 配置结构变动会破坏所有依赖 settings 的代码 | 新增配置项时必须同步更新 `configs/config.example.yaml` + 第 7 节启动命令说明 |
| `security/` 整个目录 | 安全模块（路径安全、CSRF、完整性、水印），改一个条件判断就可能出合规漏洞 | Bug 修复必须加攻击测试 + 人工 review |
| `engines/_legacy/` | 冻结的旧引擎实现，为兼容性保留 | 只有移除时允许删，禁止改逻辑 |
| `api/main.py` 的 lifespan 回调 | 预加载引擎顺序不能乱，乱了会导致 GPU OOM | 调整预加载顺序必须测试后人工确认 |

### 3.3 路由自动发现 & 注册规则（极重要，AI 必须遵循）
**新增路由不需要手动在 `main.py` 里 `include_router`**，`routes/` 目录下命名为 `xxxx_router.py` 的文件会被 `api/main.py` 的 `_auto_register_routes()` 自动扫描加载。

注册规则（不遵守则路由不会生效）：
1. 文件名必须是 `<模块名>_router.py`（例：`scene_router.py`、`history_router.py`）
2. 文件内必须定义 **module-level** 的 `router = APIRouter(prefix="/xxx", tags=["xxx"])` 变量（名字必须叫 `router`，不能叫 `scene_router`）
3. 不能有循环 import（A router import B router 的函数，B 又 import A → 扫描时报错）
4. 前缀不能重复：`prefix="/scene"` 和 `prefix="/scenes"` 没事，但两个 `prefix="/scene"` 肯定冲突

---

## 4. 测试约定

### 4.1 测试框架 & 运行命令
| 类型 | 框架 | 命令 | 覆盖率门槛 |
|------|------|------|:----------:|
| 单元测试 | pytest + pytest-asyncio + pytest-cov | `pytest tests/unit -q`（或脚本里 `python -m pytest tests/unit --cov=core --cov=engines --cov-report=term-missing`） | ≥ 65%（CI 强制：`--cov-fail-under=65`） |
| 集成测试 | pytest + TestClient（FastAPI） + AioSQLite 内存库 | `pytest tests/integration -q` | 不计入 fail_under，但必须全部通过 |
| 安全测试 | pytest + 手动攻击用例（路径穿越 / CSRF / SQL 注入） | `pytest tests/security -q` | 必须 100% 通过，CI 中阻断 PR |
| 性能测试（手动） | pytest-benchmark（可选；当前未接入，参考 `perf/benchmark/`） | `pytest tests/perf -q` | 无强制，仅供参考对比 |

### 4.2 测试命名 & 结构
- 目录结构：`tests/`（扁平布局，非 `unit/integration/security` 分层；分层仅通过 marker 区分）
- 类名：`class Test<被测类>:`（PascalCase，首字母必须 Test）
- 方法名：`def test_<场景>_<期望结果>_<条件>():`（snake_case，前缀必须 test_）
  ```python
  # ✅ 正确示例
  class TestPathGuard:
      @pytest.mark.asyncio
      async def test_safe_join_blocks_path_traversal(self):
          with pytest.raises(SecurityError):
              await safe_join("/base", "../etc/passwd")
  ```
- **严禁 `assert True` 凑覆盖率**，每个断言必须对应真实行为验证
- Marker 说明（pyproject.toml 已注册）：`@pytest.mark.integration`（9 个 API/集成文件使用）、`@pytest.mark.benchmark`（当前未使用）；历史文档所述的 `security/slow/gpu` markers 与 `pytest-benchmark` 依赖不存在于本项目（AGENTS.md v1.13 同步）

---

## 5. 依赖管理

### 5.1 依赖文件分工
| 文件 | 用途 | 是否提交 Git |
|------|------|:------------:|
| `requirements.txt` | 生产依赖（FastAPI / Uvicorn / Pydantic / Pillow / AioSQLite 等） | ✅ |
| `requirements-dev.txt` | 开发依赖（pytest / ruff / mypy / coverage / pytest-asyncio / pre-commit） | ✅ |
| `requirements-lock.txt` | 完整锁定的依赖版本（含传递依赖），用于部署复现 | ✅ |
| `pyproject.toml` | 项目元数据 + 工具配置（Ruff / Black / Mypy / Pytest） | ✅ |

### 5.2 加新依赖的标准流程
1. 本地装好（`pip install xxx`），测通功能
2. 在 `requirements.txt` 加一行（不加版本号或加最低兼容版本号）
3. 开发依赖则加到 `requirements-dev.txt`
4. 执行 `python scripts/generate_lock.py`（或 `pip freeze --all > requirements-lock.txt` 后人工去 Python 本身的包）重新生成 lock 文件
5. `scripts/verify_engine.py` 跑一遍检查依赖完整性

---

## 6. 代码质量检查（提交前必跑）
```bash
# Lint + Import 排序
ruff check . --fix

# 格式化
black .

# 类型检查（核心文件）
mypy api/core.py api/main.py common/ core/ engines/

# 单测 + 覆盖率（fail_under=70，source=app/integrated_app）
pytest tests/ --cov=app/integrated_app --cov-fail-under=70 -q
```
> 提交前至少通过 `ruff check .`（没 fix 但没 error 也行）+ `pytest tests/`。

---

## 7. 构建 / 启动命令

### 7.1 一键启动脚本（推荐）
| 平台 | 安装依赖（首次） | 启动服务 |
|------|:---------------:|---------|
| **Windows** | 双击 / 终端执行 `install.bat` | 执行 `start.bat` → 自动打开 `http://127.0.0.1:7870/docs` |
| **Linux/macOS** | `chmod +x install.sh && ./install.sh` | `chmod +x start.sh && ./start.sh` |

### 7.2 手动启动命令（调试时使用）
```bash
# 方式 A（推荐，含环境自检 + 健康检查输出）
python app/clean_launch.py
# → 监听 http://127.0.0.1:7870

# 方式 B（纯 Uvicorn，适合前台调试）
python -m uvicorn app.integrated_app.app_server:app --host 127.0.0.1 --port 7870 --reload
# ⚠️ --reload 仅限开发！生产严禁使用 --reload（会重复加载引擎导致 GPU OOM）

# 生产启动（守护进程模式，建议用 systemd）
python -m uvicorn app.integrated_app.app_server:app --host 127.0.0.1 --port 7870 --workers 1
# ⚠️ workers 只能 1！模型引擎是单例全局的，多 worker 会重复加载模型到 GPU，直接 OOM
```

### 7.3 启动后验证
浏览器打开 `http://127.0.0.1:7870/docs` 能看到 Swagger UI → 点「GET /api/v1/health」→ Try it out → Execute → 返回 200 OK，JSON 里有 `{"status": "ok", "engines_loaded": 3}` 之类的字段即启动成功。

---

## 8. i18n 多语言规范（5 种语言：中 / 繁 / 英 / 日 / 韩）

### 8.1 翻译机制
- 基于标准库 `gettext` + `babel`，所有用户可见的异常消息、日志中可能展示给用户的部分必须走 `_()`
- 翻译文件目录：`common/locale/<lang>/LC_MESSAGES/messages.{po,mo}`

### 8.2 三层回退机制（任何一层缺翻译不会显示英文原串）
```
用户选择的语言（如 zh-TW 繁中）
    ↓ 找不到翻译 →
zh-CN 简体中文（兜底第一层）
    ↓ 还找不到 →
en-US 英文（最后兜底，原串就是英文，不可能丢）
```

### 8.3 新增翻译 Key 的标准步骤
1. 在代码里写 `_("New feature loaded successfully")`（英文原串作为 key）
2. 执行 `python scripts/update_pot.py` → 更新 `common/locale/messages.pot` 模板
3. 为 5 种语言各执行一次：`msgmerge -U common/locale/<lang>/LC_MESSAGES/messages.po common/locale/messages.pot`
4. 编辑每种语言的 `.po` 文件，填好 `msgstr` 翻译
5. 执行 `msgfmt common/locale/<lang>/LC_MESSAGES/messages.po -o common/locale/<lang>/LC_MESSAGES/messages.mo` 编译成二进制
6. 完整性校验（防止漏翻译）：`python scripts/check_i18n_keys.py` → 所有语言的翻译条目数必须和 `.pot` 模板一致，差 1 个脚本就报错

---

## 9. 安全注意事项（🚫 不允许违反）

### 9.1 路径安全
- **所有文件 IO（读/写/删除/列目录）必须走 `security.path_guard.safe_join(base_dir, user_input_path)`**，禁止直接 `os.path.join` + `open()`，因为 `os.path.join("/base", "../etc/passwd")` 会拼接成 `/etc/passwd`（路径穿越漏洞）
  ```python
  # ❌ 错误写法
  with open(os.path.join(UPLOAD_DIR, filename), "wb") as f: ...

  # ✅ 正确写法
  safe_path = await safe_join(UPLOAD_DIR, filename)  # 路径穿越会抛出 SecurityError
  with open(safe_path, "wb") as f: ...
  ```

### 9.2 上传安全
- 文件大小限制（`config.yaml` → `security.max_upload_mb`，默认 100MB），超过直接返回 413
- MIME type 白名单 + 魔数双校验（不能只看扩展名）
- 生成输出必须经过 `security.watermark.embed_watermark(image_bytes)` 嵌入不可见版权水印

### 9.3 模型安全
- 所有模型文件启动时必须过 `security.integrity.verify_checksum(path, expected_sha256)`，校验失败 **立即终止启动**（防止模型被篡改 / 投毒）
- 模型 checksum 清单存 `configs/model_checksums.yaml`，**新增模型必须更新这个文件**

### 9.4 网络安全
- **禁止在任何环境设置 `host="0.0.0.0"`**，默认只监听 `127.0.0.1`，外网访问必须套 Nginx 反向代理（带 HTTPS + Basic Auth + IP 白名单）
- SSE 接口必须过 CSRF token 校验（前端从 `/api/v1/csrf-token` 取 token，请求头带 `X-CSRF-Token`）

---

## 10. Git 提交规范 & 版本管理

### 10.1 Conventional Commits（和 TTS_MultiModel / Image_MultiModel 对齐）
```
<type>(<scope>): <subject>
```
Type 列表：`feat` / `fix` / `docs` / `style`（纯格式调整，非 UI）/ `refactor` / `perf` / `test` / `chore` / `ci` / `security`  
Scope 建议：`core` / `security` / `engines` / `routes` / `i18n` / `ci`

### 10.2 版本号同步修改清单（发版时必改 3 处）
| # | 文件路径 | 要改的字段 | 示例（v1.0.0 → v1.1.0） |
|---|---------|-----------|------------------------|
| 1 | `pyproject.toml` | `[project] version` | `version = "1.0.0"` → `version = "1.1.0"` |
| 2 | `common/config.py` | `APP_VERSION` 常量 | `APP_VERSION = "1.0.0"` → `APP_VERSION = "1.1.0"` |
| 3 | `CHANGELOG.md` 顶部标题 | `## [v1.x.x] - YYYY-MM-DD` | 对应新增一级 heading |

> Git Tag 格式：`git tag -a v1.1.0 -m "Release v1.1.0"`，推到 remote 后 GitHub Release GPG 签名自动构建。

---

## 11. 常见陷阱 / 注意事项（每条都有 ✅正确 / ❌错误对照）

<!-- 📥 新坑追加模板（AI 踩坑后复制填好追加到表格最后）：
| # | 坑点标题 | 触发场景 | 现象/报错 | 正确做法 | 首次发现日期 |
|---|---------|---------|---------|---------|------------|
| X | 简短标题 | 什么操作会触发 | 具体报错信息或现象 | 正确代码/配置/步骤 | YYYY-MM-DD |
-->

| # | 坑点标题 | 触发场景 | 现象/报错 | 正确做法 | 首次发现日期 |
|---|---------|---------|---------|---------|------------|
| 1 | SSE 流式响应回调禁止 async def | 在 `StreamingResponse` 的 generator 里直接 `async def generate()` 并 `await engine.generate()` | Uvicorn 事件循环卡死 → `RuntimeError: async generator ignored StopAsyncIteration`，进度推送卡死 | 用普通函数 `def generate():`，内部 `asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=xx)` 或提前把 chunk 全部收集到 deque 再 yield | 2026-05-10 |
| 2 | 多个 router 前缀（prefix）不能重复 | 新写的 `scene_router_v2.py` 也用了 `prefix="/scene"`，老的 `scene_router.py` 还在 | FastAPI 启动不报错，但 Swagger UI 路径重复 → 实际调用时返回 404 / 或随机命中一个，排查极难 | 命名前缀必须语义化且唯一：v2 的话用 `prefix="/scene/v2"` 或直接改名替换老的（老的移到 `_deprecated/`） | 2026-05-20 |
| 3 | 严禁监听 `host="0.0.0.0"` | 为了局域网访问方便，直接在代码或启动脚本写 `uvicorn.run(app, host="0.0.0.0", port=7870)` | 所有接口直接暴露公网（如果机器公网 IP）→ 未授权用户可以直接调用生成接口消耗 GPU / 上传任意文件（路径穿越风险） | 永远 `host="127.0.0.1"`，局域网访问用 `ssh -L 7870:127.0.0.1:7870 user@server` 端口转发，或服务器上套 Nginx（带 Basic Auth + IP 白名单） | 2026-06-01 |
| 4 | 依赖注入用 `Depends(get_settings)`，不要直接 `from common.config import settings` | 在路由函数里直接读全局 settings | 单测 mock 配置时极其痛苦（要 import 后 patch 变量），且容易出现「模块导入时 settings 还没初始化」的竞态 | 所有路由 / service 一律用 FastAPI Depends：`async def route(settings: Settings = Depends(get_settings))`，测试时 override_dependency 一行就能替换 | 2026-06-15 |
| 5 | 修改核心模块后忘记重新生成完整性清单 | 改动 `app_server.py` / `model_manager.py` / `security/` 下文件 / `engines/seedvr2_engine.py` 等被完整性自检覆盖的核心模块 | 启动时报 `[SECURITY WARNING] 核心模块完整性校验失败: xxx.py`，期望/实际 SHA256 不一致，误以为被篡改 | 这是合法代码改动导致的清单过期，改完核心模块后必须运行 `python scripts/generate_integrity_manifest.py` 重新生成 `app/integrated_app/security/integrity_manifest.json`（见 SOP-4） | 2026-08-13 |
| 6 | `app/models` 常规包遮蔽项目根 `model_lib` 命名空间包 | 应用经 `python app/clean_launch.py` 启动（`app/` 进入 sys.path），同时存在项目根 `model_lib/`（无 `__init__.py`，命名空间包）与 `app/models/`（有 `__init__.py`，常规包） | 视频修复时报 `ModuleNotFoundError: No module named 'model_lib.video_vae_v3'`（`import model_lib` 解析到了 `app/models/`），但图片修复正常 | 给项目根 `model_lib/` 补 `__init__.py` 使其成为常规包，确保在 sys.path 首位（项目根）优先解析；注意 `app/models/` 仅被 `perf/benchmark/test_suite.py` 以全限定名 `app.models.*` 引用 | 2026-08-13 |
| 7 | CSP 缺 `media-src blob:` 导致 `<video>` 无法加载 blob 源 | 前端用 `<video src="blob:...">` 读取视频宽高（两倍模式自动填分辨率/预览） | 控制台报 `MEDIA_ELEMENT_ERROR: Media load rejected by URL safety check`，`videoWidth` 恒为 0，两倍检测失效（图片正常，因为 `img-src` 已含 blob:） | 在 `templates/base.html` 的 Content-Security-Policy 加 `media-src 'self' blob:`；`<video>`/`<audio>` 回退到 `default-src`，不会继承 `img-src` 的 blob: | 2026-08-13 |
| 8 | `api.post` 硬编码 JSON 头导致 FormData 提交被 422 | `startBatch` 调用 `SeedVR2.api.post('/api/restore/batch', params)` 传 FormData，但 `api.post` 在 `static/js/app.js` 硬编码 `'Content-Type': 'application/json'` + `JSON.stringify(data)` | 后端收到空 body → `parse_unified_params`（Depends）所有 Form 字段缺失 → FastAPI 422 Unprocessable Entity；浏览器控制台看到 `POST /api/restore/batch 422` | `api.post` 自动检测 `data instanceof FormData`，是 FormData 时移除 `Content-Type: application/json` 头并直接传 `body: data`（让浏览器自动加 boundary）。任何新增 `api.post(..., formData)` 调用都不需要改 | 2026-08-13 |
| 9 | 模型下载脚本落盘路径与 config 引用不一致 | 用 `scripts/download_model.py`（旧版）下载权重 | 旧脚本把文件下到 `model/SeedVR2-3B/` 子目录，但 `model_manager.check_model_exists` / `seedvr2_engine.py` 用 `os.path.join(pretrained_dir, checkpoint_name)` 只在 `model/` **根目录**找 `seedvr2_ema_3b_fp16.safetensors` 等 → 报「模型文件未找到」/ `FileNotFoundError` | 权重文件**必须直接放 `model/` 根目录**，文件名与 `config.yaml` 的 `model.models.<size>` 引用完全一致（`seedvr2_ema_*_fp16/fp8.safetensors`、`ema_vae_fp16.safetensors`、`pos_emb.pt`、`neg_emb.pt`）；下载脚本已改为 `hf_hub_download` 逐文件写入根目录（幂等跳过） | 2026-08-14 |
| 10 | 新版 nvidia-smi 输出格式变化导致 CUDA 版本解析偏移 | 新版驱动（如 NVIDIA-SMI 610.x / CUDA UMD 13.x）的 `nvidia-smi` 头部从 `CUDA Version: 13.2` 变为 `CUDA UMD Version: 13.3` | 按旧格式 `tokens=9` 提取到的是 `Version:` 而非版本号 → `install.bat` 自动探测 CUDA 版本失败 | 批处理里先取 `tokens=9` 判断是否含 `Version` 字样，若命中再用 `tokens=10` 重取版本号；版本号落入 13.x → 选 `cu132` index | 2026-08-14 |
| 11 | Blackwell(sm_120) 上 PyTorch SDPA 的 FLASH_ATTENTION/cuDNN 内核不可用 | RTX 50 系（如 5070 Ti）且 `attention_mode: sdpa` 时实测 `F.scaled_dot_product_attention`，或想装 flash-attn 之前排查 | SDPA 调用在强制 flash/cudnn 后端时报 `RuntimeError: No available kernel. Aborting execution.`，只有 `EFFICIENT_ATTENTION`/`MATH` 可用 → 当前 sdpa 实际走的是 memory-efficient 后端，并未用上 flash | Blackwell 仅支持预编译 SASS（无 PTX JIT），torch 官方 SDPA flash 内核未覆盖 sm_120。想真正用 flash 需装 `flash-attn`（若有匹配轮子）或 `sageattn`，并用 `torch.compile`(inductor) 加速；估算提速收益前先确认瓶颈是注意力还是显存/CPU 换页（12GB 下 `blocks_to_swap`/`fp8` 更关键） | 2026-08-16 |
| 12 | torch.compile 首次推理慢且重启后重复编译（inductor 缓存未持久化） | 开启 `torch_compile.enabled: true` 后跑推理 | 首次推理 ~70-110s（含编译），且**重启服务后仍要 ~100s 重新编译**；`~/.cache/torch/inductor` 目录为空，说明编译产物没落盘 | 启用 `torch.compile` 前**必须**在启动入口（`app/clean_launch.py`）设 `os.environ.setdefault("TORCHINDUCTOR_CACHE_DIR", <项目根>/.torch_cache/inductor)` 让编译产物持久化，否则每次重启都重编译。实测持久化后重启首次从 ~113s 降到 ~76s（仍非稳态 ~30s，说明部分图仍会重编译）。注意 `.torch_cache/` 已加 .gitignore | 2026-08-16 |
| 13 | 外部 Google Fonts 同步样式表阻塞 DOMContentLoaded，导致整页 JS 初始化失效 | `base.html` 里 `<link rel="stylesheet" href="https://fonts.googleapis.com/css2?...">` 同步加载；弱网/无外网环境（或被代理/镜像重定向到 `gstatic.font.im` 被 CSP 拦截） | `document.readyState` 长期卡在 `loading`，DOMContentLoaded 不触发 → 页面内容可见但**所有交互无效**（如「高级设置」点不开、上传无响应），且无任何 JS 报错，极难排查 | 字体样式改为**异步加载**：`<link ... media="print" onload="this.media='all'">` + `<noscript>` 兜底；外部字体只是装饰，不应阻塞页面初始化（`base.html` 已改，2026-08-16） | 2026-08-16 |
| 16 | 失效/陈旧的 csrf_token cookie 被永久 403 自锁 | 用户浏览器里残留一个**签名失效的 `csrf_token` cookie**（如密钥曾变动、非会话 cookie 长期残留、跨环境拷贝）。原中间件只在「cookie 缺失」时才重种、有 cookie 就跳过 | 首次上传 `POST /api/restore` 返回「`没有权限执行此操作`」（`error.403`），后端日志 `CSRF 验证失败: POST /api/restore`；关键是**反复刷新/重启都不恢复**，因为中间件见「有 cookie」就不再补发，坏 cookie 永远淘汰不掉 | 服务端：中间件对安全方法响应与 403 失败响应**一律补发有效 token**（`_set_csrf_cookie`，判断改为 `_has_valid_cookie` 而不是「cookie 不存在」），坏 cookie 会被自动替换自愈；前端：非安全请求统一走 `csrfSafeFetch(url,opts)`，403 时自动重试一次（解读新版 `csrf_token` 后再发）。改动 `csrf.py` 后需 `python scripts/generate_integrity_manifest.py`（SOP-4） | 2026-08-17 |
| 17 | 长视频/长批次任务被「卡死清理」误杀（进度清零、GPU 白跑） | 视频/图片的 `progress_callback`（在 `infer_video/image` 的 `asyncio.to_thread` 中同步执行）只调 `common.get_task_cache().update(...)`——**只写内存缓存、不写 DB**；`tasks.updated_at` 仅由异步 `update_task_state`（唯一白名单字段 `status/progress/output_path/error_message` 写 DB）在任务启动/结束等里程碑刷新 | 长视频处理中 `tasks.updated_at` 停在任务启动时刻，`cleanup_stale_tasks`（每 5 分钟）按 DB `updated_at` 判卡死 → 一个**正在正常推理的**任务被标记 failed、进度清零；但底层推理协程仍跑完，白白浪费 GPU 算力。日志报错「清理卡死任务 … 超过 30 分钟」，随后日志却显示 `处理段 30/39`、VAE/扩散仍在跑 | 清理器不能只信 DB `updated_at`：给 `cleanup_stale_tasks` 增加 `task_queue` 参数，跳过 `task_queue.current_task_id()`（当前正被 worker 执行）的任务——processing 里唯一合法的是运行中的那个，其余才真卡死。改完后 `app_server.py` 的 `_periodic_stale_cleanup` 调用处传入 `app.state.task_queue` | 2026-08-17 |
| 18 | 用 PowerShell `Set-Content`/`Out-File` 重写含中文的 UTF-8 模板会破坏编码，Jinja 渲染整站崩 | 在 PowerShell 里用 `(Get-Content -Raw) ... | Set-Content path` （PS 5.1 默认 **ANSI/GBK**）重写 `templates/*.html`（含中文注释/字面量） | 文件变成 UTF-8 与 GBK 混合字节，`Jinja/open()` 用 UTF-8 读取报 `'utf-8' codec can't decode bytes in position ~772`，FastAPI 全局 `ValueError` handler 把**所有继承 base.html 的页面**（`/`、`/history` 等）返回 `422 Unprocessable Entity`，且整页 JS 初始化失效（表现为"视频/上传/按钮都点不动"） | **禁止**用 PowerShell 重定向/Set-Content 写含中文的模板；一律用 `Edit`/`Write` 工具或 `python -c` 显式 `encoding='utf-8'` 写回。若已损坏：模板大多仍是原始 UTF-8 字节，可用 `data.decode('gbk', errors='replace').encode('gbk', errors='ignore').decode('utf-8', errors='replace')` 还原，再按语义补回残留坏字，最后 `open(p,'w',encoding='utf-8',newline='\n')` 写回并做 jinja 渲染冒烟 + 全页 `\ufffd` 检查 | 2026-08-18 |
| 19 | CI 中 `--ignore-snapshots` 导致视觉回归门禁虚设 | `e2e.yml` 中 Playwright 命令带 `--ignore-snapshots` 跳过视觉断言，因 baseline 是 win32 生成、CI 跑 Linux | CI 中视觉回归测试形同虚设：即使 UI 视觉完全崩坏也不会失败，投入最大的 E2E 层在 CI 中产出最低；且掩盖了跨平台渲染差异问题 | 移除 `--ignore-snapshots`，改用 `maxDiffPixelRatio: 0.01` 容忍跨平台渲染差异（已在 spec 代码中配置）；首次 CI 运行自动生成 baseline，后续运行比较。如需重新生成 baseline 使用 `update-baselines.yml` workflow（手动触发） | 2026-08-19 |

---

## 12. 典型 AI 开发场景 SOP（照着做，少踩坑）

<!-- 📥 新SOP追加模板（AI 完成新类型任务后复制填好追加到这里）：
#### SOP-X: [场景名称]
**适用条件**：什么情况下走这个流程
**步骤**：
1. 第一步...
2. 第二步...
3. 第三步...
**验证**：怎么确认操作成功
**关联文件**：
- path/to/file1.py
- path/to/file2.py
-->

#### SOP-1: 新增一个路由模块（遵循 auto_register）
1. 在 `api/routes/` 下新建文件 `xxx_router.py`（后缀必须 `_router.py`，否则不会自动加载）
2. 文件开头：
   ```python
   from fastapi import APIRouter, Depends

   router = APIRouter(prefix="/api/v1/xxx", tags=["xxx"])  # 变量名必须是 router！

   @router.get("/list")
   async def list_xxx():
       return {"data": []}
   ```
3. 路由文件完成后，**不需要** 去 `api/main.py` 手动 include_router（auto_register 自动扫）
4. 启动 `python app/clean_launch.py` → 打开 `/docs` 验证新路由是否在 Swagger UI 中
5. 如果路由需要权限，加上 `dependencies=[Depends(require_csrf_token)]` 或 `Depends(require_bearer_token)`

#### SOP-2: 新增一种模型引擎实现
1. 在 `engines/` 下新建目录 `new_engine/`，新建 `new_engine_impl.py`
2. 实现 `AbstractEngineProtocol`（Protocol，不是 ABC）：
   ```python
   # 必须实现：async generate(input: EngineInput) -> EngineOutput
   # 必须有类属性：name: str / version: str
   class NewEngine:  # 不需要显式继承
       name: str = "new-engine"
       version: str = "1.0.0"
       async def generate(self, input: EngineInput) -> EngineOutput: ...
   ```
3. `engines/auto_register.py` 会自动扫描并注册（无需手动导入）
4. 启动健康检查会列出 `engines_loaded: [..., "new-engine"]`，确认引擎已加载
5. **安全要求**：如果新引擎输出图像 → 必须在 service 层调用 `security.watermark.embed_watermark()`，不能跳过

#### SOP-3: 修改 config.yaml 新增配置项
1. 先在 `common/config.py` 的 `Settings` Pydantic 模型加字段（含默认值 + type annotation）
2. `configs/config.example.yaml` 同步加一行注释说明（作为模板）
3. 更新本文件第 7 节启动命令或第 3 节模块边界描述（如果新增配置影响启动流程或模块边界）
4. 执行 `python -c "from common.config import settings; print(settings.model_dump())"` 验证新字段被正确加载

#### SOP-4: 修改核心模块后重新生成完整性清单（改完必做）
**适用条件**：改动任何被启动自检覆盖的核心模块后，必须重新生成清单，否则下次启动会报「完整性校验失败」误报。
**被覆盖的核心模块**（清单见 `app/integrated_app/security/integrity_manifest.json`，自检列表见 `integrity_selfcheck.py` 的 `_CORE_MODULES`）：
- `app_server.py` / `config.py` / `model_manager.py`
- `security/` 下：`path_guard.py` / `integrity_check.py` / `watermark.py` / `integrity_selfcheck.py`
- `middleware/` 下：`csrf.py` / `basic_auth.py`
- `engines/seedvr2_engine.py`

**步骤**：
1. 完成上述任一核心模块的代码修改（改完逻辑后、提交前）
2. 运行 `python scripts/generate_integrity_manifest.py` 重新生成清单
3. 确认输出显示所有模块 `[OK]` 且生成路径为 `app/integrated_app/security/integrity_manifest.json`

**验证**：启动前先跑一次自检确认通过：
```python
python -c "from app.integrated_app.security.integrity_selfcheck import run_startup_selfcheck; print(run_startup_selfcheck())"
# 期望输出 failed=0，failed_files=[]
```
**关联文件**：
- scripts/generate_integrity_manifest.py
- app/integrated_app/security/integrity_selfcheck.py
- app/integrated_app/security/integrity_manifest.json

#### SOP-5: 安装 Triton 并启用 torch.compile 加速（Blackwell/Windows）
**适用条件**：在 RTX 50 系（Blackwell sm_120）+ Windows 上，想给模型推理开 torch.compile(inductor) 提速。
**背景**：Windows 上 torch 不自带 triton，必须装社区版 `triton-windows`；装上后 inductor 才能编译自定义内核。
**步骤**：
1. 确认环境：`python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.get_device_capability(0))"`（Blackwell 需 triton>=3.3 / torch>=2.7 / CUDA>=12.8）
2. 安装匹配的 triton-windows：`pip install triton-windows`（挑选与 torch 版本兼容的版本，如 torch 2.13 用 3.7.x）
3. 冒烟验证：对一个小函数 `@torch.compile` 跑一次 forward，确认 inductor 在 sm_120 上能编译通过、无 `No available kernel`
4. 接入项目：`config.yaml` → `inference.torch_compile.enabled` 改为 `true`（`backend: inductor`）。引擎代码已有 try/except 回退，编译失败会自动回到未编译，不会崩
5. 启动 `app/clean_launch.py`，确认服务正常启动、模型加载无误；首次推理会触发 DiT/VAE 编译（较慢属正常）
**注意**：torch.compile 只消除了算子融合/调度开销，**不能解决显存不足导致的 CPU 换页**（12GB 下瓶颈更多来自 `blocks_to_swap` / `fp8_enabled`）。提速收益要在确认瓶颈不是换页后才明显。
**关联文件**：
- config.yaml（`inference.torch_compile` 段）
- app/integrated_app/engines/seedvr2_engine.py（DiT/VAE 编译应用点）

#### SOP-6: 修复工作台页面 v2 重构（结构布局 + 对比查看器升级）
**适用条件**：修改 `templates/restore.html` 结构布局、`static/js/app.js` 的对比查看器（CompareSlider）、或新增 `sv2-*` 样式时，必须遵守本 SOP，否则会静默破坏既有功能。
**背景**：2026-08-16 将修复页重构为「工作台」布局（页头单行化 + 一体化画布工具条 + 画布舞台 + 参数侧栏），对比查看器升级为真实放大倍率语义（1:1 = 原像素 100%）。
**硬性约束（ID 契约）**：
- `app.js` 与 restore.html 内联脚本**硬编码大量 id**：`progressCard/resultCard/compareCard/compareViewport/compareContainer/compareSlider/compareBefore/compareAfterImg/resultVideo/btnDownload/canvasStateLabel/btnCanvas*/restoreFileInfo/restoreFileInput/restoreUploadZone/imagePreview/batchProgressCard/folderPath/btnScanFolder/btnStartBatch/btnBrowseFolder/folderScanResults` 及全部参数 id（`ditModel/resolution/doubleResToggle/vaeModel/blocksToSwap/maxResolution/colorCorrection/batchSize/encodeTileSize/encodeTileOverlap/decodeTileSize/decodeTileOverlap/btnVramRecommend/btnStartRestore/btnResetRestore/advParams/btnToggleParams`）——**改结构只能换 class，不能改 id/name**。
- `collectParams()` 遍历 `#paramsSidebar` 内 input/select（跳过 `#advParams`），再遍历 `#advParams`；`_collectRestoreFormValues` 依赖 `#paramsSidebar [name]`。所有参数字段必须留在侧栏内，含 hidden 字段（`seed/attention_mode/dit_cache_model/vae_cache_model/temporal_overlap/prepend_frames/input_noise_scale/latent_noise_scale/dit_device/offload_device` 等）。
- 上传区依赖 `setupUploadZone(zone, fileInput, {onFileSelected, onFileCleared})` 与内联脚本的 `restoreFileInfo/imagePreview/imagePreviewContainer/workflowGuide/previewArea` 显示切换，保留 `sv-dropzone-*` 类名可白嫖既有样式。
**SV2 结构**：`.sv2-workbench`（列布局）> `.sv2-header`（标题+`.sv2-mode-seg` 分段控件）+ `.sv2-body`（grid: 主区 + 324px 侧栏）> `.sv2-main`（批量工具条 `#batchToolbar` + 一体化工具条 `#canvasToolbar` + 画布舞台 `#previewArea[data-mode-pane=single]` + 批量面板 `[data-mode-pane=batch]`）。模式切换仍走 `switchMode()`（toggle `.sv-mode-tab` active + `[data-mode-pane].active` + batchToolbar display）。
**对比查看器 v2（CompareSlider）**：构造签名不变（`initCompareSlider(containerId, sliderId, afterId)`）；状态改为 `mag`（1=适配）/`oneToOneMag`/`tx,ty` 平移；transform = `translate(tx,ty) scale(mag)` 且 **transform-origin:0 0**（`.sv2-workbench .sv-compare-container`）；分割线位置用 `offsetWidth/Height` 而非 getBoundingClientRect（有 transform 时会算错）；滚轮以光标为中心缩放、拖拽在放大态平移、双击 适配↔1:1、键盘固定 60px 步长平移；HUD 元素 `#compareHud` 与 `#compareZoomLabel` 显示真实倍率。**新增 id**（`tbFileName/plainViewer/plainImg/compareHud/btnCanvasClear/btnCanvasReplace/btnCanvasCompare/btnRestoreSidebar/sv2Body`）在 `showRestoreResult`/`resetRestore`/内联 `bindCanvasToolbar` 中同步维护。
**验证命令**：
```bash
node --check app/integrated_app/static/js/app.js
# 模板全量渲染冒烟：
python - <<'EOF'
import json; from jinja2 import Environment, FileSystemLoader
loc=json.load(open('app/integrated_app/locales/zh.json',encoding='utf-8'))
env=Environment(loader=FileSystemLoader('app/integrated_app/templates'))
env.globals['t']=lambda k,**kw: loc.get(k,k); env.globals['current_locale']='zh'
html=env.get_template('restore.html').render(); print(len(html))
EOF
```
**注意**：SV2 样式全部追加在 `style.css` 末尾并派生自 `--sv-*` 令牌（明暗主题自动适配，勿硬编码色值）；对比查看器改造后**不要**再用 `btnCanvasZoom`（已删除），缩放走 `btnCompareZoomIn/Out`。
**2026-08-16 增量（预览查看器 / 放大镜 / 右键平移）**：
- 上传后图片预览支持缩放/拖动/双击适配/放大镜：`PreviewViewer` 类（app.js，工厂 `initPreviewViewer('previewStage','previewImgWrap','imagePreview')`，`destroyPreviewViewer()` 清理），结构在 `#imagePreviewContainer` 内（`.sv2-preview-stage` > `.sv2-preview-img` > `#imagePreview`）。
- 放大镜：`#btnMagnifier` 工具条按钮（预览/结果共用，按当前阶段路由到 PreviewViewer 或 CompareSlider 的 `setMagnifier(on)`）；镜片 `.sv2-magnifier`（`#previewMagnifier`/`#compareMagnifier`）内 `.mg-before`/`.mg-after` 两层，经 `setLoupeLayer()` 按「主视图当前倍率 ×2」渲染背景，对比模式下镜片内也保持前后分割（clip-path 跟随 `position`）。
- 平移交互：CompareSlider「左键」承担——未放大时拖分割线、放大后拖平移；预览无分割线，左键平移；右键不拦截（`e.button !== 0` 直接 return），避免与浏览器/鼠标手势冲突（2026-08-16 由「右键平移」按用户反馈改为「左键平移」）。
- 新增导出：`initPreviewViewer/destroyPreviewViewer/getActiveCompareSlider/getActivePreviewViewer`；`initCompareSlider` 现会记录实例到模块变量 `activeCompareSlider`。
**2026-08-16 增量（体验增强 ×4）**：
- 完成/失败反馈：`showRestoreResult(taskId, taskType, meta)` 新增 meta.elapsedSec（SSE completed 时由本地 `Date.now()-startTime` 传入），工具条显示「耗时 XX」；新增 `showRestoreError(msg)`——失败时结果区显示错误卡 `#errorCard` + `#btnRetry`，重试走内联注入的 `window.__retryRestore = startRestore`（文件与参数不变直接重跑）。
- 参数方案预设：侧栏顶部 `#presetSelect` + `#btnPresetSave/#btnPresetDelete`，复用内联 `_collectRestoreFormValues/_applyRestoreFormValues`（注意应用后需手动 `syncResolutionUI()` 同步两倍模式联动），存 localStorage `sv_restore_presets`。
- 批量拖拽文件夹：`#restoreUploadZone` 的 **capture 阶段** drop 监听检测 `webkitGetAsEntry().isDirectory`，命中则 `stopImmediatePropagation` 阻断单文件流程 → `switchMode('batch')` + `openDirBrowser` 弹目录选择（浏览器安全限制拿不到拖入文件夹的绝对路径，只能引导选择）。
- 记住查看偏好：localStorage `sv_view_prefs` = {dir, magnifier, compare}；CompareSlider.setMode/setMagnifier、PreviewViewer.setMagnifier、内联对比模式切换均写入；`showRestoreResult`（方向/放大镜/对比模式）与预览加载（放大镜）时恢复。

---

## 13. API 响应规范（保持所有路由一致）

### 13.1 成功响应（统一包装）
所有成功响应必须走 `common.respond_success(data, message=None)`：
```python
# ✅ 正确
return respond_success({"scene_id": "xxxxx"}, message="Scene generated successfully")
# → HTTP 200: {"code": 0, "message": "Scene generated successfully", "data": {"scene_id": "xxxxx"}}

# ❌ 错误：裸返回 dict
return {"scene_id": "xxxxx"}  # 前端无法统一判断成功/失败
```

### 13.2 错误响应（统一用 FastAPI `HTTPException`，不要 raise 自定义异常然后全局 handler 转，除非是 Security 类的全局错误）
```python
# ✅ 正确
from fastapi import HTTPException

if scene_id not in db:
    raise HTTPException(status_code=404, detail="Scene not found")
```

---

## 14. 发布流程 & CI/CD 说明

### 14.1 CI 工作流（.github/workflows/ci.yml）
- 触发：push 到 `main` / `release/*`，以及所有 PR
- Jobs：
  1. `lint-and-typecheck`：`ruff check .` + `mypy api/ common/ core/ engines/ security/`
  2. `unit-tests`：依赖 lint 通过后，`pytest tests/unit --cov-fail-under=65`
  3. `security-tests`：`pytest tests/security -v`（100% 通过要求）
  4. `integration-tests`：依赖以上全部通过后，`pytest tests/integration -v`

### 14.2 发版标准步骤（Release Engineering）
1. 开分支 `release/v1.x.x`（从 main checkout）
2. 修改版本号（第 10.2 节 3 处：pyproject.toml / config.py / CHANGELOG.md）
3. 本地跑：`ruff + mypy + pytest 全量 + security 攻击测试`
4. 提交 PR 到 main，PR title 用 `chore(release): v1.x.x`（触发 release-please 流程）
5. PR 合 main 后，打 Git Tag `v1.x.x`（和版本号严格一致），推 remote
6. GitHub Release 页面会自动 GPG 签名构建产物（要求 PGP key 已在 GitHub Secrets 配置）

---

## 📋 自进化修订记录表（AGENTS.md 进化史）

| 自进化版本 | 日期 | 触发原因 | 更新内容摘要 | 对应项目版本 |
|:---------:|------|---------|------------|:------------:|
| v1.0 | 2026-08-10 | 初始建立自进化协议 | 从 Seedvr2 项目健康度评估报告建议补齐：建立自进化协议（5 条铁律 + 自检清单）+ 启动命令章节 + i18n 翻译规范章节 + 版本号同步修改清单 + 发布流程 & CI/CD 说明 + API 响应规范 + 2 个典型 SOP | v1.0.0 |
| v1.1 | 2026-08-13 | 修改核心模块后完整性清单过期 | 新增第 11 节陷阱 #5（修改核心模块后忘记重新生成完整性清单）+ 新增 SOP-4（修改核心模块后重新生成完整性清单，含被覆盖模块清单、步骤、验证命令） | v1.0.0 |
| v1.2 | 2026-08-13 | 视频修复报 No module named 'models.video_vae_v3' | 新增第 11 节陷阱 #6（`bin/models` 常规包遮蔽项目根 `models` 命名空间包）；修复为给项目根 `models/` 补 `__init__.py` | v1.0.0 |
| v1.3 | 2026-08-13 | 视频两倍检测失败（CSP 拦截 blob 媒体） | 新增第 11 节陷阱 #7（CSP 缺 `media-src blob:` 导致 `<video>` 无法加载 blob 源）；修复为 `templates/base.html` CSP 加 `media-src 'self' blob:` | v1.0.0 |
| v1.4 | 2026-08-13 | 批量修复接口 422（api.post 硬编码 JSON 头） | 新增第 11 节陷阱 #8（`api.post` 硬编码 JSON 头导致 FormData 提交被 422）；修复为 `static/js/app.js` 的 `api.post` 自动检测 FormData 跳过 JSON 转换 | v1.0.0 |
| v1.5 | 2026-08-14 | 仓库「克隆即用」审计 + 新手保姆式引导 | ① 第 1 节补充「实际结构修正」块（实际入口 `bin/clean_launch.py`、根目录 `config.yaml`、监听 7870，与早期规划结构漂移的说明）；② 新增陷阱 #9（模型下载脚本落盘路径与 config 引用不一致，需放 `model/` 根目录）与 #10（新版 nvidia-smi `CUDA UMD Version` 格式导致 tokens 偏移）；③ README 升级为保姆式新手教程 + 模型权重下载保姆级说明；`scripts/download_model.py` 改为逐文件下载到根目录（幂等）；`install.bat` 自动探测 CUDA 版本选择 PyTorch index | v1.0.0 |
| v1.6 | 2026-08-16 | Blackwell 上安装 Triton 加速 + 排查三加速库可用性 | ① 新增陷阱 #11（Blackwell sm_120 上 PyTorch SDPA 的 FLASH/cuDNN 内核 `No available kernel`，实测只有 EFFICIENT/MATH 可用）；② 新增 SOP-5（安装 triton-windows 并开启 `torch_compile.enabled=true` 加速，含冒烟验证与「compiler 不治 CPU 换页」的警告）；③ 结论：flash-attn 无 torch2.13/cu132/py3.12 匹配轮子、sageattention 为训练向且量化损伤修复画质，均未接入 | v1.0.0 |
| v1.7 | 2026-08-16 | torch.compile 首次慢/重启重复编译 | ① 新增陷阱 #12（torch.compile 首次推理慢且重启后重复编译：inductor 默认缓存目录 `~/.cache/torch/inductor` 未生效，需在 `bin/clean_launch.py` 设 `TORCHINDUCTOR_CACHE_DIR` 到项目 `.torch_cache/inductor` 持久化，实测重启首次从 ~113s→~76s，`.torch_cache/` 已加 .gitignore）；② 实测结论：torch_compile 对视频稳态提速 ~22%（30.2 vs 38.8），对图片反而慢 ~27%；FP8 小图比 FP16 慢，视频 FP8 仅比 FP16 快 ~7%；最终配置定为 `default_precision: fp16` + `torch_compile.enabled: true`；③ 新增可复用基准脚本 `perf/benchmark/bench_restore_api.py` | v1.0.0 |
| v1.8 | 2026-08-16 | 修复工作台页面 v2 重构（结构布局 + 对比查看器升级） | ① restore.html 重构为工作台布局：页头单行化（`.sv2-header` + `.sv2-mode-seg`）、一体化画布工具条 `#canvasToolbar`（清除/替换/对比模式/方向/缩放/适配/重置/下载/再次修复）、画布舞台（上传/预览/进度/结果 四态）、参数侧栏收窄 + 折叠后右侧「参数」恢复入口；所有既有 id/name 保留（app.js 与 collectParams 硬编码依赖）；② app.js CompareSlider 升级为真实放大倍率语义：mag/oneToOneMag/tx,ty 平移、滚轮以光标为中心缩放、拖拽在放大态平移、双击 适配↔1:1、键盘固定 60px 步长、`#compareHud` 显示真实倍率；showRestoreResult/resetRestore 同步新工具条状态；③ style.css 追加 `sv2-*` 作用域样式（派生自 `--sv-*` 令牌，明暗主题自动适配）；④ 新增 SOP-6（修复页 v2 的 ID 契约 + 查看器语义 + 验证命令）；原文件备份于工作区 `outputs/migration-backup/` | v1.0.0 |
| v1.9 | 2026-08-16 | 修复页图片功能增量（预览查看器/放大镜/平移） | ① 上传图片后预览支持滚轮缩放、拖动平移、双击 适配/1:1、HUD 倍率：新增 `PreviewViewer` 类 + `initPreviewViewer/destroyPreviewViewer` 导出，结构 `#previewStage > #previewImgWrap > #imagePreview`；② 放大镜工具 `#btnMagnifier`（预览/结果共用，路由到 PreviewViewer/CompareSlider.setMagnifier），镜片 `.sv2-magnifier` 内 before/after 双层，`setLoupeLayer()` 按主视图倍率×2 渲染，对比模式下镜片内保持前后分割；③ 拖拽平移统一为左键（对比：左键未放大拖分割线/放大拖平移；预览：左键平移），右键不拦截避免与浏览器手势冲突；④ `initCompareSlider` 记录实例 + 新增 `getActiveCompareSlider/getActivePreviewViewer` 导出；SOP-6 补充增量说明 | v1.0.0 |
| v1.10 | 2026-08-16 | 用户反馈修正：平移改回左键 | 对比查看器与预览的拖动平移由「右键」改为「左键」（`e.button !== 0` 直接忽略），移除右键分支与 `contextmenu preventDefault`，右键完全归还浏览器/手势；同步更新查看器内提示文案与 SOP-6 增量说明 | v1.0.0 |
| v1.11 | 2026-08-16 | 修复页体验增强 ×4 | ① 完成/失败反馈：`showRestoreResult` 增加 meta.elapsedSec 显示「耗时」，失败显示错误卡 + 一键重试（`window.__retryRestore` 复用 startRestore）；② 参数方案预设：侧栏 `#presetSelect` + 保存/删除，复用 `_collectRestoreFormValues/_applyRestoreFormValues` 存 localStorage；③ 批量拖拽文件夹：dropzone capture 阶段检测目录 → 切批量模式 + 弹目录选择（浏览器限制无法读绝对路径）；④ 记住查看偏好：`sv_view_prefs`（方向/放大镜/对比模式）保存与恢复；SOP-6 补充增量说明 | v1.0.0 |
| v1.12 | 2026-08-16 | 高级设置无法滚动 + 参数无讲解 | ① 侧栏滚动修复：旧 `.sv-param-sidebar` 为 `overflow:visible` + `> *` `flex-shrink:0` + 固定 `max-height`，被 `.sv2-sidebar` 覆盖为 `overflow:hidden` 后展开的高级设置被裁剪且无法滚动；修复为侧栏内容包 `.sv2-sidebar-scroll`（`flex:1; overflow-y:auto`），`.sv-param-actions` 移出滚动区固定底部，并覆盖 `padding/max-height/position/flex-shrink`；② 高级设置全部参数补详细中文 `data-tooltip`（13 处，含 maxResolution/colorCorrection/batchSize/swap_io/编码解码 tile 与重叠/分块开关/tile_debug/uniform_batch/debug_mode），advParams 顶部加 `.sv-adv-intro` 总览说明（含隐藏参数由系统自动优化的提示）；tooltip 为纯 CSS `[data-tooltip]::after` 实现，直接加属性即可 | v1.0.0 |
| v1.13 | 2026-08-16 | 高级设置无法打开/展开区被压缩（二轮，Playwright 实测定位） | ① 根因一：`base.html` Google Fonts 样式表**同步阻塞 DOMContentLoaded**（弱网/被 CSP 拦截时 `readyState` 长期 `loading`）→ 页面内容可见但内联脚本（含高级设置点击）从未初始化；修复为 `media="print" onload="this.media='all'"` 异步加载 + noscript 兜底，新增陷阱 #13；② 根因二：旧规则 `.sv-param-sidebar .sv-advanced-params.open{flex-shrink:1;min-height:0}`（specificity 0,2,0）把展开后的 advParams 在 flex 容器里压缩到 12px，且 `overflow-y:visible` 与旧 `overflow-x:hidden` 混用被浏览器强制计算为 `auto`；修复为 `.sv2-sidebar .sv2-sidebar-scroll .sv-advanced-params.open{flex-shrink:0;min-height:auto;max-height:none;overflow:visible}`（0,3,0）并去掉 700px 展开限高，交由外层滚动容器统一滚动；③ 用 `tests/` Playwright 写临时诊断脚本（`_adv_check*.js`）实测：修复前 readyState=loading/advOpen=false/adv h=12px → 修复后 complete/advOpen=true/adv h=1276px/外层可滚，截图复查通过 | v1.0.0 |

<!-- 🔄 下次更新 AGENTS.md 时，在上面表格末尾追加新一行，不要删除历史记录 -->
| v1.14 | 2026-08-17 | 测试体系审计修复：门禁虚设/marker 失效/零覆盖模块/文档漂移同步 | ① e2e.yml：移除 `--update-snapshots` bootstrap（视觉回归改为 `--ignore-snapshots`，本地 win32 基线强制）+ ci.yml 删除空转的 `-m "not integration"`；② T2：9 个 TestClient 集成文件打标 `pytest.mark.integration`（test_api/schema/history_htmx/settings_routes/sse_integration/ui_routes + conftest）；③ T5：同步 AGENTS.md §4 实际测试布局（扁平 tests/ 非 unit/integration 分层）、marker 真实使用情况（integration/benchmark 注册 + 零使用 markers 说明）、缺失依赖说明；新增陷阱 #14（视觉门禁虚设）+ #15（marker 配置与执行策略脱节），CI/CD 章节注释修正为单 OS 触发与 pytest-cov 覆盖；版本递增 v1.14 | v1.0.0 |
| v1.15 | 2026-08-17 | 修复视频上传 `POST /api/restore` 被 403 永久拦截（CSRF 坏 cookie 自锁） | 根因：浏览器残留签名失效的 `csrf_token` cookie，原中间件仅在「cookie 缺失」时重种、有 cookie 就跳过 → 坏 cookie 永不淘汰，每次上传都 403「没有权限执行此操作」，与前端 `error.403` 文案对应。修复：① `middleware/csrf.py` 改为 `_has_valid_cookie()` 判定，对**安全方法响应与 403 失败响应一律补发有效 token**（`_set_csrf_cookie`），坏 cookie 自动替换自愈，并已 `scripts/generate_integrity_manifest.py` 重新生成清单（SOP-4）；② `static/js/app.js` 新增 `csrfSafeFetch`，非安全请求（`api.post/delete/uploadRestore`）统一携带 token，403 时自动重试一次。Playwright 实测：注入坏 cookie → 首次 403 → 服务端补发 → 重试 → 通过 CSRF 进入业务（503 模型未加载）。新增陷阱 #16 | v1.0.0 |
| v1.16 | 2026-08-17 | 点击「开始修复」自动加载模型再修复 | 需求：点开始修复时若模型未加载，自动加载模型后直接执行，无需手动预加载。实现：① `routes/restore/common.py` 新增 `ensure_model_loaded(model_manager, dit_model)`——调幂等的 `model_manager.load_model`（同模型已加载则短路，否则加载 dit_model 对应尺寸），失败抛 503「模型自动加载失败」；② `upload.py` 的 `POST /api/restore/` 与 `batch.py` 的 `POST /api/restore/batch` 移除原「`if not model_registry.model_loaded: 503 模型未加载`」守卫，改为 `await common.ensure_model_loaded(...)`（同时把模型尺寸与 dit_model 参数对齐，解决「已加载 3b 但选了 7b」的尺寸不符问题）；③ 两侧路由注入 `model_manager: ModelManager = Depends(get_model_manager)`；④ 更新 `tests/test_api.py` 的 `test_restore_without_model_returns_503` → `test_restore_auto_loads_model_when_not_loaded`（断言自动 await load_model 且不再以模型未加载 503 拒绝）。注意：`POST /api/restore/` 与 `/batch` 的错误响应 503 语义由「模型未加载」改为「GPU 不可用，或模型自动加载失败」 | v1.0.0 |
| v1.17 | 2026-08-17 | 修复长视频被「卡死清理」误杀（进度清零、GPU 白跑） | 根因：视频/图片 `progress_callback` 只更新内存缓存不写 DB，`tasks.updated_at` 停在上次异步状态更新（任务启动时）；`cleanup_stale_tasks` 仅按 DB `updated_at` 判卡死 → 正常推理的长视频任务被标记 failed、进度清零，底层推理仍跑完浪费 GPU。修复：给 `cleanup_stale_tasks(history_db, threshold_minutes, task_queue)` 增加可选 `task_queue` 参数，跳过 `task_queue.current_task_id()` 正在执行的任务（processing 里唯一合法的是运行中的那个），`app_server.py` 的 `_periodic_stale_cleanup` 调用处传 `app.state.task_queue`；新增 `tests/test_recovery.py::TestCleanupStaleTasks`（跳过运行中长任务 / 清理真卡死任务 / 无 task_queue 兼容）。新增陷阱 #17 | v1.0.0 |
| v1.18 | 2026-08-17 | 断点续传进度增强 + 双保险防误杀 | ① `routes/restore/common.py` 新增 `create_db_progress_persister(task_id, history_db, interval_seconds=30)`——捕获主事件循环，返回同步 `persist(progress)`，按间隔通过 `asyncio.run_coroutine_threadsafe` 把 `progress` 写 DB（同时刷新 `updated_at`），future 用 `contextlib.suppress` 消费避免「异常未获取」告警；② 接入三处进度回调：`upload.py` 单图 `_process_image_task`、`upload.py` 单视频 `_process_video_task`、`batch.py` 批量视频——长任务工作期间 DB `updated_at` 保持新鲜（配合 v1.17 的 skip-running 形成双保险：即使 `current_task_id` 瞬时为空也不会误杀），且进度落盘可在服务重启后由 `recover_tasks` 拿到更接近实时的进度；③ 新增 `tests/test_recovery.py::TestCreateDbProgressPersister`（节流只写一次 / 过间隔再写 / 最后进度生效） | v1.0.0 |
| v1.19 | 2026-08-17 | **AGENTS.md 自检：同步实际入口 + 端口** | 自检消除陈旧引用：第 1 节「入口文件」/ 默认监听、第 7 节「启动命令」、第 11 节陷阱 #3、**SOP-1 启动步骤**中原 `api/clean_launch.py` / `uvicorn api.main:app` 与 `7860` 均改与实际一致——入口统一为 `bin/clean_launch.py`（推荐）与 `python -m uvicorn bin.integrated_app.app_server:app`，监听端口统一 `7870` | v1.0.0 |
| v1.20 | 2026-08-17 | bin→app、models→model_lib、pretrained_models→model 三连目录重命名 | ① `pretrained_models/` → `model/`（权重目录，config.yaml `pretrained_dir` 默认值、下载/校验脚本、.gitignore/.dockerignore、README 同步）；② 项目根 `models/` 架构源码包 → `model_lib/`（全部 `from models.*` import 改 `model_lib.*`、`configs_*`/VAE YAML 路径、pyproject ruff/mypy/coverage、3.1 目录树与 3.2 禁区表、docs 同步；`app/models`（原 bin/models）保持不变，仅被 perf/test_suite.py 以 `app.models.*` 引用）；③ `bin/` → `app/`（全部 `bin.integrated_app` import 改 `app.integrated_app`，start/install/capture/run_checks 脚本、CI workflows、pyproject、Dockerfile CMD、playwright 配置、陷阱 #5/#12、SOP-1/4/5/6 同步）；陷阱 #6 同步为 `app/models` 遮蔽根 `model_lib`；README 目录树与 uvicorn 命令 bin→app | v1.0.0 |
| v1.21 | 2026-08-18 | 视频修复常态化三连：无法播放 / 无对比 / 耗时不同步 | ① **视频无法播放**根因是 `templates/base.html` 被我误用 PowerShell `Set-Content`（默认 ANSI/GBK）重写破坏编码 → 所有继承 base 的页面 Jinja 读 UTF-8 报 `'utf-8' codec can't decode`，FastAPI `ValueError` handler 返回 **422**，整页 JS 初始化失效（上传/视频/按钮全点不动）。修复：`data.decode('gbk',errors='replace').encode('gbk',errors='ignore').decode('utf-8',errors='replace')` 还原 + 语义补坏字 + `newline='\n'` 写回 + jinja 渲染冒烟；并补回一张 `var theme` 被同行注释吞掉的行（主题初始化失效）。新增陷阱 #18；② **视频无对比工具**：新增 `static/js/video-compare.js`（VideoCompareSlider 复用图片 CompareSlider 的分割线/缩放/平移/键盘/空格播放暂停），`restore.html` 新增 `videoCompareCard/videoPlainViewer` DOM，`app.js` `showRestoreResult` 视频分支默认进视频对比、编码不支持时回退单视频查看器，`bindCanvasToolbar` 对比开关支持视频双视图切换；③ **耗时不同步**：SSE 进度端点（`routes/restore/task.py`）`data` 增加 `processing_time`，`upload.py` 完成时 `update_task_state(..., processing_time=result.processing_time)`，前端 SSE completed 传 `processingTime`、`showRestoreResult` 优先用后端真实耗时（前端计时兜底） | v1.0.0 |
| v1.22 | 2026-08-19 | 测试体系质量加固：消除 11 处测试反模式 | ① **P0-视觉回归门禁虚设**：`e2e.yml` 移除 `--ignore-snapshots`，CI 中视觉回归断言不再被跳过，改用 `maxDiffPixelRatio: 0.01` 容忍跨平台渲染差异（新增陷阱 #19）；② **P0-覆盖率门禁虚设**：`pyproject.toml` omit 从通配符 `*/optimization/inference/*` 改为逐文件精确路径，移除 `progress.py`/`license_compliance.py`/`roadmap.py`/`engine/*` 等 6 个纯 Python 逻辑文件的 omit，`fail_under` 65→70；③ **P1-残缺断言**：`test_sse_integration.py` 两处 `in (200,404,422)` / `in (404,403)` 三态码改为精确 `== 404`；④ **P1-硬编码等待**：7 个 spec 文件共 11 处 `waitForTimeout` 全部消除，替换为 `waitForFunction`/`waitForResponse`/`requestAnimationFrame`/`networkidle` 等条件等待；⑤ **P1-触控目标宽松阈值**：`uiux-compatibility.spec.ts` 6 处 `toBeLessThanOrEqual(10/5)` 改为 `toBe(0)`；⑥ **P2-过度指定断言**：`test_api.py` health/gpu 端点从 15+ 字段名断言减少到 4-5 核心契约字段；⑦ **P2-性能阈值收紧**：FCP 15s→3s、LCP 5s→3s、页面加载 10s→5s、移除 2 处 `test.setTimeout(120000)`；⑧ **P2-flaky retry 消除**：`playwright.config.ts` retries 从 CI=2/local=1 降为 0；⑨ **P3-a11y 串行模式移除**：每个测试有独立 browser context 不需 serial；⑩ **P3-双重 catch 修复**：`image-restore.spec.ts` 双重 catch 改为 `expect(toast).toBeVisible()`；⑪ **P3-marker 文档同步**：第 6 节覆盖率命令从过时的 `tests/unit --cov=core --cov=engines --cov-fail-under=65` 更新为 `tests/ --cov=app/integrated_app --cov-fail-under=70` | v1.0.0 |


## 路线图落地新增模块（2026-08-18，未提交）
- app/integrated_app/mcp_server.py — MCP Server（移植自 TTS_MultiModel）
- app/integrated_app/bad_case_retry.py — 容错重试（移植自 TTS_MultiModel）
- app/integrated_app/spec.py — 领域公式契约层
- scripts/render_pages.py + tests/frontend/smoke.js — 前端冒烟测试
- tests/test_mcp_server.py、tests/test_bad_case_retry.py、tests/test_spec.py

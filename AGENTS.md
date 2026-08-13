# Seedvr2 AGENTS.md — AI 辅助开发指南

> 🧬 **自进化协议版本**：v1.3  
> 📅 **最后更新日期**：2026-08-13  
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
- [ ] 目录结构（`api/`、`common/`、`core/`、`engines/`、`security/`、`routes/`、`models/`）是否和第 3 节模块边界描述一致？
- [ ] 禁区目录表（models/、common/、configs_*）是否仍适用？如有新增禁区目录，是否已更新第 3.2 节？
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
> 入口文件：`api/clean_launch.py`（推荐）或 `uvicorn api.main:app`  
> 默认监听：`http://127.0.0.1:7860`（禁止 `host="0.0.0.0"`，见第 11 节常见陷阱 #3）

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
- **豁免目录（跳过 ruff/mypy 检查）**：`models/`、`engines/_legacy/`、`configs_local/`（第三方代码或研究代码，不要求风格）

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
├── models/              ← 第三方模型权重 & 代码（🚫 禁区：AI 不允许自动修改）
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
| `models/` 整个目录 | 第三方模型权重和研究代码，修改会直接影响生成效果和合规性 | 用户明确要求时，可以只改配置类（模型路径、超参数），不动模型推理代码 |
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
| 性能测试（手动） | pytest-benchmark（可选） | `pytest tests/perf -q` | 无强制，仅供参考对比 |

### 4.2 测试命名 & 结构
- 目录结构：`tests/unit/<模块>/test_<被测文件>.py`（一一对应源文件）
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
- Marker 说明（pyproject.toml 已注册）：`@pytest.mark.security`、`@pytest.mark.slow`、`@pytest.mark.gpu`（后两个默认 CI 跳过，本地手动跑）

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

# 单测 + 覆盖率
pytest tests/unit --cov=core --cov=engines --cov-fail-under=65 -q
```
> 提交前至少通过 `ruff check .`（没 fix 但没 error 也行）+ `pytest tests/unit`。

---

## 7. 构建 / 启动命令

### 7.1 一键启动脚本（推荐）
| 平台 | 安装依赖（首次） | 启动服务 |
|------|:---------------:|---------|
| **Windows** | 双击 / 终端执行 `install.bat` | 执行 `start.bat` → 自动打开 `http://127.0.0.1:7860/docs` |
| **Linux/macOS** | `chmod +x install.sh && ./install.sh` | `chmod +x start.sh && ./start.sh` |

### 7.2 手动启动命令（调试时使用）
```bash
# 方式 A（推荐，含环境自检 + 健康检查输出）
python api/clean_launch.py
# → 监听 http://127.0.0.1:7860

# 方式 B（纯 Uvicorn，适合前台调试）
uvicorn api.main:app --host 127.0.0.1 --port 7860 --reload
# ⚠️ --reload 仅限开发！生产严禁使用 --reload（会重复加载引擎导致 GPU OOM）

# 生产启动（守护进程模式，建议用 systemd）
uvicorn api.main:app --host 127.0.0.1 --port 7860 --workers 1
# ⚠️ workers 只能 1！模型引擎是单例全局的，多 worker 会重复加载模型到 GPU，直接 OOM
```

### 7.3 启动后验证
浏览器打开 `http://127.0.0.1:7860/docs` 能看到 Swagger UI → 点「GET /api/v1/health」→ Try it out → Execute → 返回 200 OK，JSON 里有 `{"status": "ok", "engines_loaded": 3}` 之类的字段即启动成功。

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
| 3 | 严禁监听 `host="0.0.0.0"` | 为了局域网访问方便，直接在代码或启动脚本写 `uvicorn.run(app, host="0.0.0.0", port=7860)` | 所有接口直接暴露公网（如果机器公网 IP）→ 未授权用户可以直接调用生成接口消耗 GPU / 上传任意文件（路径穿越风险） | 永远 `host="127.0.0.1"`，局域网访问用 `ssh -L 7860:127.0.0.1:7860 user@server` 端口转发，或服务器上套 Nginx（带 Basic Auth + IP 白名单） | 2026-06-01 |
| 4 | 依赖注入用 `Depends(get_settings)`，不要直接 `from common.config import settings` | 在路由函数里直接读全局 settings | 单测 mock 配置时极其痛苦（要 import 后 patch 变量），且容易出现「模块导入时 settings 还没初始化」的竞态 | 所有路由 / service 一律用 FastAPI Depends：`async def route(settings: Settings = Depends(get_settings))`，测试时 override_dependency 一行就能替换 | 2026-06-15 |
| 5 | 修改核心模块后忘记重新生成完整性清单 | 改动 `app_server.py` / `model_manager.py` / `security/` 下文件 / `engines/seedvr2_engine.py` 等被完整性自检覆盖的核心模块 | 启动时报 `[SECURITY WARNING] 核心模块完整性校验失败: xxx.py`，期望/实际 SHA256 不一致，误以为被篡改 | 这是合法代码改动导致的清单过期，改完核心模块后必须运行 `python scripts/generate_integrity_manifest.py` 重新生成 `bin/integrated_app/security/integrity_manifest.json`（见 SOP-4） | 2026-08-13 |
| 6 | `bin/models` 常规包遮蔽项目根 `models` 命名空间包 | 应用经 `python bin/clean_launch.py` 启动（`bin/` 进入 sys.path），同时存在项目根 `models/`（无 `__init__.py`，命名空间包）与 `bin/models/`（有 `__init__.py`，常规包） | 视频修复时报 `ModuleNotFoundError: No module named 'models.video_vae_v3'`（`import models` 解析到了 `bin/models/`），但图片修复正常 | 给项目根 `models/` 补 `__init__.py` 使其成为常规包，确保在 sys.path 首位（项目根）优先解析；注意 `bin/models/` 仅被 `perf/benchmark/test_suite.py` 以全限定名 `bin.models.*` 引用 | 2026-08-13 |
| 7 | CSP 缺 `media-src blob:` 导致 `<video>` 无法加载 blob 源 | 前端用 `<video src="blob:...">` 读取视频宽高（两倍模式自动填分辨率/预览） | 控制台报 `MEDIA_ELEMENT_ERROR: Media load rejected by URL safety check`，`videoWidth` 恒为 0，两倍检测失效（图片正常，因为 `img-src` 已含 blob:） | 在 `templates/base.html` 的 Content-Security-Policy 加 `media-src 'self' blob:`；`<video>`/`<audio>` 回退到 `default-src`，不会继承 `img-src` 的 blob: | 2026-08-13 |

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
4. 启动 `python api/clean_launch.py` → 打开 `/docs` 验证新路由是否在 Swagger UI 中
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
**被覆盖的核心模块**（清单见 `bin/integrated_app/security/integrity_manifest.json`，自检列表见 `integrity_selfcheck.py` 的 `_CORE_MODULES`）：
- `app_server.py` / `config.py` / `model_manager.py`
- `security/` 下：`path_guard.py` / `integrity_check.py` / `watermark.py` / `integrity_selfcheck.py`
- `middleware/` 下：`csrf.py` / `basic_auth.py`
- `engines/seedvr2_engine.py`

**步骤**：
1. 完成上述任一核心模块的代码修改（改完逻辑后、提交前）
2. 运行 `python scripts/generate_integrity_manifest.py` 重新生成清单
3. 确认输出显示所有模块 `[OK]` 且生成路径为 `bin/integrated_app/security/integrity_manifest.json`

**验证**：启动前先跑一次自检确认通过：
```python
python -c "from bin.integrated_app.security.integrity_selfcheck import run_startup_selfcheck; print(run_startup_selfcheck())"
# 期望输出 failed=0，failed_files=[]
```
**关联文件**：
- scripts/generate_integrity_manifest.py
- bin/integrated_app/security/integrity_selfcheck.py
- bin/integrated_app/security/integrity_manifest.json

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

<!-- 🔄 下次更新 AGENTS.md 时，在上面表格末尾追加新一行，不要删除历史记录 -->

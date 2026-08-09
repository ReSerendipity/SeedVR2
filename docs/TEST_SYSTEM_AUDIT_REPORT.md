# SeedVR2 测试体系完整性评估报告

> **评估日期**: 2026-08-09  
> **评估范围**: CI/CD 流水线、单元测试、集成/API 测试、E2E 测试、专项测试  
> **评估方法**: 代码审查 + 配置分析 + 架构评估  

---

## 目录

1. [现状总结](#1-现状总结)
2. [维度一：CI/CD 流水线](#2-维度一cicd-流水线)
3. [维度二：单元测试框架与覆盖率](#3-维度二单元测试框架与覆盖率)
4. [维度三：集成与 API 测试](#4-维度三集成与-api-测试)
5. [维度四：E2E 端到端测试](#5-维度四e2e-端到端测试)
6. [维度五：其他专项测试](#6-维度五其他专项测试)
7. [问题诊断汇总](#7-问题诊断汇总)
8. [改进建议（按优先级排序）](#8-改进建议按优先级排序)
9. [附录：测试文件清单](#9-附录测试文件清单)

---

## 1. 现状总结

SeedVR2 项目已建立起一套**多层次、较高成熟度**的测试体系，覆盖了从后端单元测试到前端 E2E 测试的完整链路。总体评估如下：

### 1.1 核心优势

| 优势项 | 说明 |
|--------|------|
| **测试分层清晰** | 单元测试（28 个 `test_*.py`）、集成/API 测试、E2E 测试（12 个 `.spec.ts`）、性能测试、安全测试各司其职 |
| **后端覆盖面广** | 覆盖了核心模块：HistoryDB、TaskQueue、Cache（LRU/Adaptive）、Metrics、ErrorHandler、CSRF、PathGuard、FTS 转义、GPU 后端、ModelManager、VideoPipeline 等 |
| **E2E 架构成熟** | 采用 Page Object Model 设计模式，拥有完整的 API Mock 体系（`api-mocks.ts`）、测试数据工厂（`test-data.ts`）、断言辅助工具（`assertion-helpers.ts`） |
| **安全测试深入** | 覆盖 HMAC 签名 CSRF、路径遍历防护、FTS5 注入防御、XSS 防护、CSP 验证、Cookie 安全标志等 |
| **CI/CD 基础完备** | 后端质量门禁（lint + format + type check + test + coverage）、E2E 流水线、依赖审计、GPG 签名发布四条流水线并行运作 |
| **覆盖率集成到位** | 通过 `pyproject.toml` 配置了 `pytest-cov`，生成 XML/HTML/Term 三种报告并上传 Codecov，`fail_under = 65` |
| **Fixture 设计合理** | `conftest.py` 使用 `tmp_path` 隔离数据库、Mock 重依赖（model_manager）、重定向配置持久化路径，避免测试污染 |
| **多视口/多浏览器配置** | Playwright 配置了 9 个 project（Chromium/Firefox/WebKit × Desktop/Laptop/Tablet/Mobile），支持跨浏览器和响应式测试 |

### 1.2 量化概览

| 指标 | 数值 |
|------|------|
| Python 单元测试文件 | 28 个 (`test_*.py`) |
| E2E 测试规格文件 | 12 个 (`*.spec.ts`) |
| E2E Page Object 类 | 7 个 |
| CI/CD 工作流 | 4 个 |
| Playwright 项目配置 | 9 个（3 浏览器 × 4 视口，部分组合） |
| 覆盖率阈值 | 65% (`fail_under`) |
| 覆盖率源范围 | `bin/integrated_app`（排除 GPU/引擎核心） |
| 性能测试阈值 | P95 < 500ms, 错误率 < 1% |

---

## 2. 维度一：CI/CD 流水线

### 2.1 流水线总览

| 工作流 | 文件 | 触发条件 | 运行环境 | 用途 |
|--------|------|----------|----------|------|
| CI - Backend Quality Gate | `ci.yml` | PR/Push → main, develop | `windows-latest` | Lint + 类型检查 + 单元测试 + 覆盖率 |
| CI - E2E Playwright | `e2e.yml` | PR → main, develop（路径过滤） | `ubuntu-latest` | Playwright E2E 测试（仅 chromium-desktop） |
| Dependency Audit | `dependency-audit.yml` | PR 改依赖文件 + 每周一 06:00 | `ubuntu-latest` | pip-audit + safety 漏洞扫描 |
| GPG-Signed Release | `gpg-signed-release.yml` | Release published | `ubuntu-latest` | SHA256SUMS + GPG 签名 |

### 2.2 详细分析

#### 2.2.1 `ci.yml` — 后端质量门禁

**触发机制**:
- `pull_request` + `push` 到 `main` 和 `develop` 分支 ✅
- 未配置 `workflow_dispatch` 手动触发 ❌

**环境与依赖**:
- `windows-latest` 运行环境，Python 3.12，pip 缓存 ✅
- 未使用 matrix 策略跨 OS 测试 ❌（后端实际仅测 Windows）

**质量门禁步骤**:
```yaml
# 依次执行（串行）:
Ruff (lint) → Black (format check) → Mypy (type check) → Pytest + coverage
```
- Lint、Format、Type Check、Test 四重门禁 ✅
- 各步骤串行执行，无并行 job ❌

**覆盖率**:
- 生成 XML、HTML、Term 三种报告 ✅
- 上传到 Codecov（`fail_ci_if_error: false`）⚠️（上传失败不会阻断 CI）
- 使用 `actions/upload-artifact@v4` 保存报告，`if: always()` 确保即使失败也上传 ✅

**问题**:
1. **无失败重试机制** — pytest 步骤无 `retry` 逻辑，单次 flaky test 即可阻断 CI
2. **无并行执行** — 所有步骤串行在单一 job 中，无 job 级别并行
3. **无通知机制** — 无 Slack/Teams/邮件通知，仅依赖 GitHub UI
4. **无缓存策略优化** — 未缓存 mypy/ruff 的增量信息
5. **Codecov 上传不阻断** — `fail_ci_if_error: false` 意味着覆盖率上传失败被静默忽略

#### 2.2.2 `e2e.yml` — E2E Playwright

**触发机制**:
- 仅 `pull_request`，未包含 `push` ❌（直接 push 到 main 不会触发 E2E）
- 路径过滤合理：仅在修改 `bin/integrated_app/`、`tests/specs/`、`tests/pages/` 等时触发 ✅

**环境与依赖**:
- `ubuntu-latest`，Python 3.12 + Node 20，pip 和 npm 双缓存 ✅
- 仅安装 chromium 浏览器（`npx playwright install --with-deps chromium`）以加速 CI ✅

**服务启动**:
- 后台启动 `app_server.py`，使用 `curl --retry 30 --retry-delay 2 --retry-connrefused` 等待就绪 ✅
- 60 分钟超时限制 ✅

**测试执行**:
- 仅运行 `--project=chromium-desktop` ❌（放弃跨浏览器 CI 覆盖）
- 上传 HTML 报告和测试结果 artifacts ✅

**问题**:
1. **push 事件未触发** — 直接提交到 main/develop 不会运行 E2E 测试
2. **单浏览器 CI** — CI 环境仅测 Chromium，Firefox/WebKit 回归只能依赖本地
3. **无 Playwright 浏览器缓存** — 每次 CI 重新下载浏览器，增加 ~2 分钟
4. **无并行分片** — 未使用 `--shard` 分割测试以加速
5. **无通知机制** — 失败无外部通知

#### 2.2.3 `dependency-audit.yml` — 依赖审计

**触发机制**:
- PR 修改 `requirements.txt`/`requirements-lock.txt`/`pyproject.toml` 时触发 ✅
- 每周一 06:00 定时扫描 ✅

**工具**:
- `pip-audit` + `safety` 双重扫描 ✅

**问题**:
1. **无前端依赖审计** — 未对 `tests/package.json` 运行 `npm audit`
2. **无 SBOM 生成** — 未生成 Software Bill of Materials
3. **无自动化修复** — 发现漏洞仅报错，不自动创建 Issue 或 PR
4. **无 CI 缓存** — 每次重新安装 pip-audit 和 safety

#### 2.2.4 `gpg-signed-release.yml` — GPG 签名发布

**分析**: 供应链安全最佳实践，在 Release 时自动生成 SHA256SUMS 并用 GPG 签名，防 CWE-912 投毒。配置完善，包含验证说明。✅

### 2.3 CI/CD 维度问题汇总

| 编号 | 问题 | 严重程度 |
|------|------|----------|
| C1 | E2E 流水线未在 push 事件触发，直接提交到 main 无 E2E 验证 | 高 |
| C2 | 无跨 OS matrix 测试（后端仅 Windows，E2E 仅 Ubuntu） | 中 |
| C3 | CI 中仅测 chromium-desktop，跨浏览器回归无保障 | 中 |
| C4 | 无失败重试机制（pytest/Playwright flaky test 阻断 CI） | 中 |
| C5 | 无 CI 通知机制（Slack/Teams/邮件） | 低 |
| C6 | 无 Playwright 浏览器缓存，每次重新下载 | 低 |
| C7 | 前端依赖无 npm audit | 中 |
| C8 | 无 SAST/DAST 静态/动态安全扫描 | 中 |
| C9 | 性能测试未集成到 CI | 中 |

---

## 3. 维度二：单元测试框架与覆盖率

### 3.1 pytest 配置分析

**配置位置**: `pyproject.toml` → `[tool.pytest.ini_options]`

```toml
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "integration: marks integration tests (deselect with '-m \"not integration\"')",
    "benchmark: marks benchmark tests",
]
```

- `asyncio_mode = "auto"` 自动检测 async 测试 ✅
- 自定义 marker（`integration`、`benchmark`）用于测试筛选 ✅
- **无 `addopts` 默认参数** ❌（如 `--strict-markers`、`--tb=short` 等未配置）
- **无超时配置** ❌（无 `pytest-timeout`，挂起测试可阻塞 CI）

### 3.2 覆盖率配置分析

**配置位置**: `pyproject.toml` → `[tool.coverage.*]`

```toml
[tool.coverage.run]
source = ["bin/integrated_app"]
omit = [
    "*/tests/*",
    "*/optimization/gpu/*",  # GPU-only 路径
    "*/engines/_*_pipeline.py",  # 引擎管线
    # ... 共 15 条 omit 规则
]

[tool.coverage.report]
fail_under = 65
show_missing = true
```

- 覆盖率仅测量 `bin/integrated_app`，排除 GPU/引擎核心 ✅（合理：核心需真实 CUDA + 模型权重）
- `fail_under = 65` 作为最低门槛 ✅
- `show_missing = true` 显示未覆盖行 ✅
- **仅行覆盖率，无分支覆盖率** ❌（未配置 `branch = true`）
- **无分模块覆盖率阈值** ❌（全量 65% 可能掩盖关键模块覆盖率过低）
- **无覆盖率差异报告** ❌（未使用 `diff-cover` 或 Codecov PR comment）

### 3.3 Fixture 设计分析

**`conftest.py` 核心 Fixture**:

```python
@pytest.fixture
def test_app(tmp_path, monkeypatch):
    """创建用于测试的 FastAPI 应用与 TestClient"""
    # 1. 临时数据库路径 → 避免污染生产数据 ✅
    # 2. 关闭模型自动加载 → 避免真实推理依赖 ✅
    # 3. Mock model_manager → 避免触发真实模型加载 ✅
    # 4. 重定向配置持久化到 tmp_path → 避免写回 config.yaml ✅
```

- CSRF 辅助函数 `get_csrf_token()` 和 `csrf_post()` ✅
- 使用 `tmp_path`（函数级隔离）确保测试间无状态泄漏 ✅

**问题**:
1. **无 session-scoped fixture** — `test_app` 每个测试函数都重新创建 app + TestClient，对于不需要数据库隔离的只读 API 测试是性能浪费
2. **无测试数据工厂** — 缺少 `factory_boy` 或类似的数据生成模式，测试数据散落在各测试函数中
3. **无参数化 fixture** — 未使用 `@pytest.fixture(params=[...])` 进行多配置测试
4. **无 async fixture 清理验证** — 缺少对异步资源（如数据库连接）泄漏的检测

### 3.4 测试文件组织与规范

**测试文件清单**（28 个 `test_*.py`）:

| 类别 | 文件 | 测试组织方式 |
|------|------|-------------|
| 数据层 | `test_history_db.py`, `test_cache.py` | Class-based, async fixtures |
| 任务系统 | `test_task_queue.py`, `test_task_events.py`, `test_task_state.py` | Class-based, async |
| API/路由 | `test_api.py`, `test_ui_routes.py`, `test_history_htmx.py` | Class-based, TestClient |
| 安全 | `test_csrf_signed.py`, `test_path_guard.py`, `test_fts_escape.py`, `test_magic_check.py` | Class-based, 安全语义 |
| GPU/硬件 | `test_gpu_backend.py`, `test_gpu_utils.py` | Class-based, mock torch |
| 模型管理 | `test_model_manager.py`, `test_model_registry.py` | Class-based, mock engine |
| 引擎/管线 | `test_video_pipeline.py`, `test_video_processor.py` | Class-based, mock + real cv2 |
| 错误处理 | `test_error_handler.py`, `test_exceptions.py` | Class-based, TestClient |
| 其他 | `test_metrics.py`, `test_logger.py`, `test_retry.py`, `test_recovery.py`, `test_response.py`, `test_config_models.py`, `test_color_fix.py`, `test_sse_session_filter.py`, `test_refactor_e4_b2.py` | Class-based |

**规范评价**:
- 统一使用 Class-based 测试组织 ✅
- 使用 `pytest.mark.asyncio` 标注异步测试 ✅
- 使用 `tmp_path` 隔离文件系统 ✅
- 使用 `unittest.mock`（Mock/MagicMock/AsyncMock/patch）进行依赖隔离 ✅
- 每个测试类有中文 docstring 描述覆盖范围 ✅

### 3.5 Mock 策略分析

| 测试文件 | Mock 对象 | 策略评价 |
|----------|-----------|----------|
| `conftest.py` | `model_manager`（AsyncMock/MagicMock） | 区分同步/异步方法，避免 JSON 序列化失败 ✅ |
| `test_gpu_backend.py` | `_CUDAStrategy.detect`, `_CUDAStrategy.get_info` | 使用 `@patch.object` 装饰器，模拟 GPU 可用/不可用 ✅ |
| `test_model_manager.py` | `model_registry`, `torch`, `gpu_manager` | 多层 Mock，覆盖正常/异常路径 ✅ |
| `test_video_pipeline.py` | `MockVideoEngine` 继承 `_VideoPipelineMixin` | 自定义 Mock 引擎重载模型方法，保留流式管线真实逻辑 ✅ |
| `test_task_queue.py` | 无外部 Mock，使用真实 `asyncio` | 测试真实并发行为，更接近生产 ✅ |

**问题**:
1. **无 property-based testing** — 未使用 `hypothesis` 进行属性测试，边界值发现依赖人工
2. **无 mutation testing** — 未使用 `mutmut` 或 `cosmic-ray` 验证测试质量
3. **`test_video_pipeline.py` 依赖真实 cv2** — 虽然使用 Mock 模型层，但 cv2 视频读写为真实操作，增加测试脆弱性
4. **无并行测试执行** — 未使用 `pytest-xdist`（`-n auto`）加速

### 3.6 单元测试维度问题汇总

| 编号 | 问题 | 严重程度 |
|------|------|----------|
| U1 | 覆盖率仅 65% 门槛，无分支覆盖率 | 中 |
| U2 | 无 `pytest-timeout`，挂起测试可阻塞 CI | 中 |
| U3 | 无 `pytest-xdist` 并行执行，测试套件串行运行 | 低 |
| U4 | 无 property-based testing（hypothesis） | 低 |
| U5 | 无测试数据工厂模式（factory_boy） | 低 |
| U6 | `test_app` fixture 为函数级，无 session 级复用 | 低 |
| U7 | 无 `--strict-markers` 配置，typo marker 不报错 | 低 |

---

## 4. 维度三：集成与 API 测试

### 4.1 `test_api.py` 分析

**覆盖范围**: 10 个测试类，覆盖主要 API 端点

| 测试类 | 端点 | 测试要点 |
|--------|------|----------|
| `TestIndexPage` | `GET /` | 200 状态码 + 页面内容 |
| `TestHistoryAPI` | `GET /api/system/history` | JSON 结构、HTMX 片段、分页边界（page=0→422, page=9999→空, page_size=1000→422） |
| `TestUnifiedRestoreAPI` | `GET /restore`, `POST /api/restore/` | 页面加载、白名单外 403、白名单内 404、空输入 400、无模型 503 |
| `TestHealthAPI` | `GET /api/system/ping`, `GET /api/system/health` | 响应结构与字段类型验证 |
| `TestSettingsAPI` | `GET/POST /api/system/settings` | 读取配置、写入-读取 round-trip |
| `TestModelAPI` | `GET /api/system/model/status`, `POST .../load`, `POST .../unload` | 状态查询、Mock 加载/卸载 |
| `TestLocalesAPI` | `GET /api/system/locales`, `POST /api/system/locale` | 语言列表、切换语言 |
| `TestMetricsAPI` | `GET /api/system/metrics`, `GET .../inference` | 指标快照、推理历史 |
| `TestGPUAPI` | `GET /api/system/gpu`, `GET .../gpu/system` | GPU 信息字段完整性 |
| `TestRestoreTaskFlow` | `GET/POST /api/restore/{task_id}/*` | 404 路径覆盖（progress/result/download/cancel/batch） |

**优点**:
- 覆盖了分页边界条件 ✅
- 覆盖了安全语义（白名单 403、路径不存在 404）✅
- 覆盖了错误响应（400/403/404/422/503）✅
- 覆盖了 round-trip 写入验证 ✅

**问题**:
1. **无并发请求测试** — 未测试多用户同时操作时的竞态条件
2. **无 SSE/WebSocket 集成测试** — `test_sse_session_filter.py` 仅测试过滤器逻辑，未测试真实 SSE 连接
3. **无大文件上传测试** — 未测试 multipart 上传大文件时的内存/超时行为
4. **无 API Schema 验证** — 未使用 OpenAPI schema 验证响应结构（FastAPI 自动生成 schema，但测试未利用）
5. **无限流/Rate Limiting 测试** — 未验证请求频率限制
6. **模型加载全程 Mock** — `test_app` fixture Mock 了 model_manager，真实模型加载/推理流程未集成测试

### 4.2 `test_ui_routes.py` 分析

**覆盖范围**: 7 个测试类，覆盖 `/api/ui/` 下所有端点

| 测试类 | 端点 | 测试要点 |
|--------|------|----------|
| `TestGetParameters` | `GET /api/ui/parameters` | 参数定义字段、核心参数存在性、预设字段 |
| `TestGetRecommendations` | `GET /api/ui/parameters/recommendations` | 排序验证、自定义参数匹配 |
| `TestValidateParameters` | `POST /api/ui/parameters/validate` | 有效/无效值、边界值、未知参数忽略 |
| `TestLoadPreferences` | `GET /api/ui/preferences` | 默认偏好字段 |
| `TestSavePreferences` | `POST /api/ui/preferences` | 保存-重载 round-trip、部分更新保留其他字段 |
| `TestResetPreferences` | `POST /api/ui/preferences/reset` | 重置恢复默认值 |
| `TestGetLayout` | `GET /api/ui/layout` | 分组字段、排序、默认分组 |

**优点**:
- 部分更新保留其他字段测试 ✅（`test_partial_update_preserves_other_fields`）
- 推荐结果排序验证 ✅
- 核心参数存在性验证 ✅

**问题**:
1. **无无效输入类型测试** — 未测试传入错误类型（如 string 代替 number）时的 422 响应
2. **无并发偏好更新测试** — 未测试多请求同时修改偏好时的竞态
3. **无偏好字段白名单测试** — 未验证未知字段是否被正确忽略或拒绝

### 4.3 数据库隔离与清理机制

**`test_history_db.py`** 的数据库隔离策略:

```python
@pytest.fixture
async def db(tmp_path):
    """临时数据库 fixture，自动初始化与关闭"""
    db_path = tmp_path / "test_history.db"
    instance = HistoryDB(db_path=str(db_path))
    await instance.initialize()
    try:
        yield instance
    finally:
        await instance.close()
```

- 使用 `tmp_path` 创建临时数据库 ✅
- `try/finally` 确保 `close()` 总是执行 ✅
- 每个测试函数独立数据库实例 ✅

**`conftest.py`** 的应用级隔离:

```python
config.setdefault("history", {})["db_path"] = str(tmp_path / "history.db")
```

- 重定向 `history.db` 到临时路径 ✅
- 重定向 `config.yaml` 持久化到临时路径 ✅（通过 `monkeypatch.setattr`）

**问题**:
1. **无数据库迁移测试** — 未测试 schema 升级/降级
2. **无并发数据库访问测试** — 未测试多连接同时读写时的 busy_timeout 行为（虽然有 `test_busy_timeout_pragma_applied` 验证 PRAGMA，但未测试实际并发场景）
3. **无 FTS5 重建测试** — 未测试 FTS 索引损坏后的重建

### 4.4 集成/API 测试维度问题汇总

| 编号 | 问题 | 严重程度 |
|------|------|----------|
| I1 | 无 SSE/WebSocket 真实连接集成测试 | 中 |
| I2 | 无 API OpenAPI schema 自动验证 | 低 |
| I3 | 无大文件上传/下载集成测试 | 中 |
| I4 | 无并发请求/竞态条件测试 | 中 |
| I5 | 模型加载全程 Mock，真实推理流程无集成测试 | 低（需 GPU 硬件） |
| I6 | 无数据库 schema 迁移测试 | 低 |

---

## 5. 维度四：E2E 端到端测试

### 5.1 Playwright 配置分析

**`playwright.config.ts`** 核心配置:

| 配置项 | 值 | 评价 |
|--------|-----|------|
| `testDir` | `./specs` | ✅ |
| `timeout` | 120000ms (2min) | ⚠️ 较高，可能掩盖性能问题 |
| `expect.timeout` | 15000ms | ✅ 合理 |
| `fullyParallel` | `true` | ✅ |
| `forbidOnly` | `!!process.env.CI` | ✅ CI 禁止 `test.only` |
| `retries` | CI: 2, 本地: 1 | ✅ |
| `workers` | CI: 2, 本地: undefined(自动) | ✅ |
| `trace` | `on-first-retry` | ✅ |
| `screenshot` | `only-on-failure` | ✅ |
| `video` | `on-first-retry` | ✅ |
| `reporter` | `['html', 'list']` | ✅ |

**项目配置（9 个 project）**:

| 浏览器 | 视口 | 项目名 |
|--------|------|--------|
| Chromium | 1920×1080 | `chromium-desktop` |
| Firefox | 1920×1080 | `firefox-desktop` |
| WebKit | 1920×1080 | `webkit-desktop` |
| Chromium | 1366×768 | `chromium-laptop` |
| Firefox | 1366×768 | `firefox-laptop` |
| Chromium | 768×1024 (touch) | `chromium-tablet` |
| WebKit | 768×1024 (iPad) | `webkit-tablet` |
| Chromium | 375×812 (Pixel 5) | `chromium-mobile` |
| WebKit | 375×812 (iPhone 12) | `webkit-mobile` |

- 跨浏览器 × 跨视口组合覆盖 ✅
- 移动端启用 touch 和真实设备 profile ✅
- `webServer.reuseExistingServer: true` 支持本地复用已运行实例 ✅

**问题**:
1. **CI 仅运行 `chromium-desktop`** — 9 个 project 中仅 1 个在 CI 执行，其余 8 个无 CI 保障
2. **无 test tag/filter** — 未使用 `@tag` 注解区分 smoke/full 套件，无法按优先级选择性运行
3. **无 Allure reporter** — 仅 HTML + list，无更丰富的测试报告集成
4. **navigationTimeout 过高** — 60s 可能掩盖真实的性能退化

### 5.2 E2E 测试规格分析

**12 个 `.spec.ts` 文件覆盖矩阵**:

| 规格 | 覆盖内容 | 交互测试 | 视觉回归 | Mock 依赖 |
|------|----------|----------|----------|-----------|
| `navigation.spec.ts` | 侧边栏导航、直接 URL、前进/后退、活跃高亮、面包屑、404 | ✅ | ❌ | `setupAllMocks` |
| `security.spec.ts` | XSS、CSRF、路径遍历、敏感数据、CSP、内联事件、Cookie 安全、输入消毒 | ✅ | ❌ | `setupAllMocks` |
| `a11y.spec.ts` | axe-core 扫描、键盘导航、ARIA 角色、图片 alt、表单标签、颜色对比 | ✅ | ❌ | `setupAllMocks` |
| `performance.spec.ts` | FCP/LCP/CLS、页面加载时间、API 响应时间、进度条 jank、内存、Bundle 大小 | ✅ | ❌ | `setupAllMocks` |
| `uiux-compatibility.spec.ts` | 4 视口响应式、跨浏览器渲染、视觉回归截图、触控目标、内容溢出 | ✅ | ⚠️ (全部 skip) | `setupAllMocks` |
| `history.spec.ts` | 历史记录页面 | ✅ | ❌ | `setupAllMocks` |
| `image-restore.spec.ts` | 图像修复流程 | ✅ | ❌ | `setupAllMocks` |
| `video-restore.spec.ts` | 视频修复流程 | ✅ | ❌ | `setupAllMocks` |
| `settings.spec.ts` | 设置页面 | ✅ | ❌ | `setupAllMocks` |
| `system-status.spec.ts` | 系统状态 | ✅ | ❌ | `setupAllMocks` |
| `theme.spec.ts` | 主题切换 | ✅ | ❌ | `setupAllMocks` |
| `i18n.spec.ts` | 国际化 | ✅ | ❌ | `setupAllMocks` |
| `sse.spec.ts` | SSE 事件流 | ✅ | ❌ | `setupAllMocks` |

### 5.3 视觉回归测试分析

**`uiux-compatibility.spec.ts`** 中定义了 12 个视觉回归测试（6 页面 × 2 主题），但**全部使用 `test.skip()` 跳过**:

```typescript
test.skip('Home page - dark theme visual regression', async ({ page }) => {
  // ...
  await expect(page).toHaveScreenshot('home-dark.png', {
    fullPage: true,
    maxDiffPixelRatio: 0.01,
  });
});
```

- 已有基线截图目录 `uiux-compatibility.spec.ts-snapshots/`（含 12 张 PNG）✅
- 但测试被 skip，基线截图未参与比较 ❌

**问题**:
1. **视觉回归全部禁用** — 12 个 `test.skip()` 导致截图基线形同虚设
2. **触控目标使用软断言** — `toBeLessThanOrEqual(30)` 而非 `toBe(0)`，允许最多 30 个不合规元素
3. **颜色对比度使用已知问题过滤** — `knownIssuePatterns` 数组过滤掉已知违规，可能掩盖新增违规

### 5.4 API Mock 体系分析

**`fixtures/api-mocks.ts`** 提供完整的 Mock 层:

| Mock 类别 | 函数数量 | 覆盖端点 |
|-----------|---------|----------|
| System API | 13 | health, gpu, gpu/system, settings(GET/POST), model status/load/unload/switch, locales, locale, browse-dir, open-explorer |
| History API | 4 | list, statistics, delete, clear |
| Video Restore | 7 | upload, progress(SSE), result, download, batch, batch-progress, batch-retry |
| Image Restore | 7 | scan-folder, upload, result, download, batch, batch-progress, batch-retry |
| SSE Events | 1 | global SSE event stream |
| Error Scenarios | 4 | 503 model not loaded, 400 bad request, 500 server error, network timeout |
| Composite | 1 | `setupAllMocks()` 一键设置所有成功 Mock |

- SSE 事件流 Mock 支持进度模拟 ✅
- 错误场景 Mock（503/400/500/timeout）✅
- `setupAllMocks()` 统一设置 ✅

### 5.5 Page Object Model 分析

**7 个 Page Object 类**:

| 类 | 文件 | 职责 |
|----|------|------|
| `BasePage` | `base.page.ts` | 导航、侧边栏、面包屑、主题切换通用操作 |
| `IndexPage` | `index.page.ts` | 首页 |
| `VideoRestorePage` | `video-restore.page.ts` | 视频修复 |
| `ImageRestorePage` | `image-restore.page.ts` | 图像修复 |
| `HistoryPage` | `history.page.ts` | 历史记录 |
| `SystemStatusPage` | `system-status.page.ts` | 系统状态 |
| `SettingsPage` | `settings.page.ts` | 设置 |

- 继承 `BasePage` 复用通用操作 ✅
- 封装页面特定元素和操作 ✅

**问题**:
1. **无网络条件测试** — 未模拟 slow 3G/offline 等网络环境
2. **无数据驱动测试** — 未使用 `test.describe.configure({ mode: 'serial' })` 进行多用户场景串行测试
3. **无权限/角色测试** — 未测试不同用户角色的 UI 可见性差异（如果有 RBAC）

### 5.6 E2E 维度问题汇总

| 编号 | 问题 | 严重程度 |
|------|------|----------|
| E1 | 视觉回归测试全部 `test.skip()`，截图基线未生效 | 高 |
| E2 | CI 仅运行 `chromium-desktop`，8/9 project 无 CI 保障 | 高 |
| E3 | 触控目标合规使用软断言（`≤30` 而非 `=0`） | 中 |
| E4 | 颜色对比度使用 `knownIssuePatterns` 过滤，可能掩盖新增违规 | 中 |
| E5 | 性能阈值过高（FCP 15s, LCP 5s, page load 10s） | 中 |
| E6 | 无 test tag/filter 区分 smoke vs full 套件 | 低 |
| E7 | 无网络条件测试（slow 3G, offline） | 低 |
| E8 | 无 Playwright 浏览器 CI 缓存 | 低 |

---

## 6. 维度五：其他专项测试

### 6.1 性能测试

**文件**: `tests/perf/locustfile.py`

**配置**:
- 工具: Locust
- 场景: 20 用户并发，持续 5 分钟
- 覆盖接口: health(权重3), history(权重2), settings(权重2), gpu(权重1), metrics(权重1), locales(权重1)
- 阈值: P95 < 500ms, 错误率 < 1%
- 退出码: 通过=0, 失败=1

**优点**:
- 使用 `@events.quitting.add_listener` 自动检查阈值 ✅
- 使用 `catch_response=True` 进行响应体验证 ✅
- 支持无头模式和 Web UI 两种运行方式 ✅
- 测试开始/结束有格式化日志输出 ✅

**问题**:
1. **仅覆盖只读 API** — 未测试写操作（POST restore, POST settings）的性能
2. **未集成到 CI** — 性能测试为手动运行，无 CI 自动化回归检测
3. **无渐进式负载** — 固定 20 用户，无 ramp-up/ramp-down 配置
4. **无分布式压测** — 单机 Locust，未配置 Master/Worker 分布式模式
5. **无性能基线** — 无历史性能数据对比，无法检测退化趋势
6. **page=0 参数错误** — `view_history` 使用 `page=0`，但 API 要求 `page >= 1`（应为 `page=1`）

### 6.2 安全测试

#### 6.2.1 后端安全测试

| 文件 | 覆盖内容 | 评价 |
|------|----------|------|
| `test_csrf_signed.py` | HMAC 签名格式、合法 token 验证、篡改拒绝、空 token 拒绝、无分隔符拒绝、跨密钥拒绝、跨重启验证 | ✅ 全面 |
| `test_path_guard.py` | 白名单初始化、相对路径解析、空字节路径跳过、`..` 遍历攻击、绝对路径攻击、多白名单目录、`assert_safe`/`assert_safe_scan`/`assert_safe_download` 异常语义 | ✅ 全面 |
| `test_fts_escape.py` | 空查询、空格、简单词、多词 OR、FTS5 特殊字符（`"`, `*`, `()`, `+`, `-`, `:`, `^`）、FTS5 关键字中和、Unicode 保留、长查询、真实 SQLite FTS5 语法验证 | ✅ 全面 |
| `test_magic_check.py` | 文件魔数检查 | ✅ |

**亮点**:
- `test_fts_escape.py` 使用真实 SQLite FTS5 验证转义结果可被解析 ✅
- `test_csrf_signed.py` 测试跨重启 token 持久化 ✅
- `test_path_guard.py` 验证错误消息不回显用户输入（`"secret" not in exc_info.value.detail`）✅

#### 6.2.2 前端安全测试（E2E）

**`security.spec.ts`** 覆盖:

| 测试场景 | 方法 | 评价 |
|----------|------|------|
| XSS in toast | Mock API 返回含 `<script>` 的错误消息，验证不执行 | ✅ |
| XSS in directory browser | Mock browse-dir 返回含 `<img onerror>` 的文件名 | ✅ |
| XSS in file info | 上传含 `<script>` 文件名的文件 | ✅ |
| CSRF token header | 验证 POST 请求包含 `X-CSRF-Token` header | ✅ |
| Path traversal in browse-dir | 验证 `..` 请求返回 400 | ✅ |
| Path traversal in open-explorer | 验证 `..` 请求返回 400 | ✅ |
| Sensitive data in localStorage | 扫描 localStorage 中的敏感模式 | ✅ |
| Content Security Policy | 检查 CSP header 或 meta tag | ✅ |
| Inline event handlers | 扫描所有页面的 `onclick=` 等属性 | ✅ |
| Secure cookie flags | 验证 session/token cookie 的 HttpOnly/Secure/SameSite | ✅ |
| Input sanitization | 测试输入框中的恶意字符 | ✅ |

**问题**:
1. **部分 XSS 测试依赖 UI 元素可见性** — 使用 `if (await saveBtn.isVisible())` 条件跳过，可能在实际页面结构变化后静默跳过
2. **CSP 测试使用 `page.route` 拦截** — 可能与 Mock 冲突
3. **无 SSRF 测试** — 未测试服务端请求伪造防护
4. **无认证/授权测试** — 未测试未认证访问、越权访问

### 6.3 GPU/硬件测试

**`test_gpu_backend.py`** 覆盖:

| 测试场景 | Mock 策略 | 评价 |
|----------|-----------|------|
| GPU 不可用时 backend=UNAVAILABLE | `patch.object(_CUDAStrategy, "detect", return_value=False)` | ✅ |
| GPU 不可用时 can_load_model=False | 同上 | ✅ |
| CUDA 可用时 backend=CUDA | `patch.object` 模拟 RTX 4090 | ✅ |
| VRAM 充足时 can_load_model=True | 模拟 20000MB available | ✅ |
| VRAM 不足时 can_load_model=False | 模拟 500MB available | ✅ |
| GPU info 缓存 | 验证 `get_info` 仅调用一次 | ✅ |

**问题**:
1. **无真实 GPU 集成测试** — 全部使用 Mock，无真实 CUDA 环境验证
2. **无多 GPU 测试** — 未测试多 GPU 设备选择
3. **无 GPU 内存泄漏检测** — 未测试长时间运行下的显存增长
4. **无 CUDA 版本兼容性测试** — 未测试不同 CUDA 版本的行为差异
5. **无 fallback 路径测试** — 未测试 CUDA 不可用时的 CPU fallback 推理（如果有）

### 6.4 可访问性测试

**`a11y.spec.ts`** + **`wcag-contrast-test.js`**:

| 测试维度 | 工具 | 覆盖页面 | 评价 |
|----------|------|----------|------|
| axe-core 页面扫描 | axe-core | 6 页面 | ✅ 仅检查 critical violations |
| 键盘导航 | Tab 遍历 | Video Restore | ✅ 验证焦点顺序和无陷阱 |
| ARIA 角色 | 手动检查 | Settings | ✅ tablist/tab/tabpanel/aria-selected |
| 进度条 ARIA | 手动检查 | Video Restore | ✅ progressbar role + aria-valuenow |
| 图片 alt | 手动检查 | Home | ✅ |
| 表单标签 | 手动检查 | Video Restore | ✅ for/id 或 aria-labelledby |
| 颜色对比度 | axe-core wcag2aa | 3 页面 | ⚠️ 使用 knownIssuePatterns 过滤 |
| WCAG 对比度（独立脚本） | Playwright + 自实现 | 6 页面 × 2 主题 | ✅ 但未集成到 CI |

**问题**:
1. **axe-core 仅检查 critical** — `serious`/`moderate`/`minor` 违规被忽略
2. **`wcag-contrast-test.js` 未集成** — 独立脚本，不在 Playwright 或 CI 中运行
3. **颜色对比度 knownIssuePatterns** — 13 个已知问题模式被过滤，可能掩盖新增违规

### 6.5 专项测试维度问题汇总

| 编号 | 问题 | 严重程度 |
|------|------|----------|
| S1 | 性能测试未集成 CI | 中 |
| S2 | 性能测试仅覆盖只读 API | 中 |
| S3 | `locustfile.py` 中 `page=0` 参数错误（API 要求 page≥1） | 高 |
| S4 | GPU 测试全 Mock，无真实硬件验证 | 低（需硬件） |
| S5 | `wcag-contrast-test.js` 未集成到 Playwright/CI | 中 |
| S6 | axe-core 仅检查 critical 级别违规 | 中 |
| S7 | 颜色对比度 knownIssuePatterns 可能掩盖新增违规 | 中 |
| S8 | 无 SSRF/认证/授权安全测试 | 中 |

---

## 7. 问题诊断汇总

### 7.1 高优先级问题

| 编号 | 维度 | 问题 | 影响 |
|------|------|------|------|
| C1 | CI/CD | E2E 流水线未在 push 事件触发 | 直接提交到 main 无 E2E 验证，可能引入回归 |
| E1 | E2E | 视觉回归测试全部 `test.skip()` | UI 视觉变更无自动化检测，依赖人工审查 |
| E2 | E2E | CI 仅运行 `chromium-desktop` | 8/9 Playwright project 无 CI 保障，跨浏览器回归风险 |
| S3 | 专项 | `locustfile.py` 中 `page=0` 参数错误 | 性能测试中 history API 返回 422，错误率统计失真 |

### 7.2 中优先级问题

| 编号 | 维度 | 问题 | 影响 |
|------|------|------|------|
| C2 | CI/CD | 无跨 OS matrix 测试 | 后端仅测 Windows，E2E 仅测 Ubuntu，平台特异性 bug 可能遗漏 |
| C3 | CI/CD | CI 中仅测 chromium-desktop | Firefox/WebKit 回归无 CI 保障 |
| C4 | CI/CD | 无失败重试机制 | Flaky test 直接阻断 CI，开发者需手动重跑 |
| C7 | CI/CD | 前端依赖无 npm audit | 前端漏洞未自动检测 |
| C8 | CI/CD | 无 SAST/DAST 安全扫描 | 代码级安全漏洞未自动检测 |
| C9 | CI/CD | 性能测试未集成到 CI | 性能退化无自动检测 |
| U1 | 单元 | 覆盖率仅 65% 门槛，无分支覆盖率 | 关键分支可能未覆盖但总覆盖率达标 |
| U2 | 单元 | 无 `pytest-timeout` | 挂起测试阻塞 CI |
| I1 | 集成 | 无 SSE/WebSocket 真实连接测试 | 实时通信功能未端到端验证 |
| I3 | 集成 | 无大文件上传/下载测试 | 大文件处理可能存在内存/超时问题 |
| I4 | 集成 | 无并发请求/竞态条件测试 | 多用户并发场景可能存在数据竞争 |
| E3 | E2E | 触控目标合规使用软断言 | 移动端可用性问题被容忍 |
| E4 | E2E | 颜色对比度使用 knownIssuePatterns 过滤 | 新增对比度违规可能被静默忽略 |
| E5 | E2E | 性能阈值过高 | 性能退化可能未触发告警 |
| S1 | 专项 | 性能测试未集成 CI | 性能退化无自动检测 |
| S2 | 专项 | 性能测试仅覆盖只读 API | 写操作性能未验证 |
| S5 | 专项 | `wcag-contrast-test.js` 未集成 | WCAG 对比度检查不自动运行 |
| S6 | 专项 | axe-core 仅检查 critical 级别 | serious/moderate 违规被忽略 |
| S7 | 专项 | knownIssuePatterns 可能掩盖新增违规 | 对比度退化可能被静默过滤 |
| S8 | 专项 | 无 SSRF/认证/授权安全测试 | 认证/授权安全盲区 |

### 7.3 低优先级问题

| 编号 | 维度 | 问题 | 影响 |
|------|------|------|------|
| C5 | CI/CD | 无 CI 通知机制 | 失败需手动查看 GitHub UI |
| C6 | CI/CD | 无 Playwright 浏览器缓存 | CI 每次重新下载浏览器 |
| U3 | 单元 | 无 `pytest-xdist` 并行执行 | 测试套件串行运行，CI 耗时较长 |
| U4 | 单元 | 无 property-based testing | 边界值发现依赖人工 |
| U5 | 单元 | 无测试数据工厂模式 | 测试数据维护成本高 |
| U6 | 单元 | `test_app` fixture 为函数级 | 只读 API 测试重复创建 app |
| U7 | 单元 | 无 `--strict-markers` | marker typo 不报错 |
| I2 | 集成 | 无 OpenAPI schema 自动验证 | 响应结构变更可能未被发现 |
| I5 | 集成 | 模型加载全程 Mock | 真实推理流程无集成测试 |
| I6 | 集成 | 无数据库 schema 迁移测试 | 升级时可能破坏兼容性 |
| E6 | E2E | 无 test tag/filter | 无法按优先级选择性运行 |
| E7 | E2E | 无网络条件测试 | 弱网/离线行为未验证 |
| E8 | E2E | 无 Playwright 浏览器 CI 缓存 | CI 耗时增加 |
| S4 | 专项 | GPU 测试全 Mock | 真实 GPU 行为未验证 |

---

## 8. 改进建议（按优先级排序）

### 8.1 高优先级（立即执行）

#### 建议 H1：修复 E2E 流水线触发条件（对应 C1）

```yaml
# .github/workflows/e2e.yml — 增加 push 触发
on:
  pull_request:
    branches: [main, develop]
    paths:
      - 'bin/integrated_app/**'
      - 'tests/specs/**'
      - 'tests/pages/**'
      - 'tests/fixtures/**'
      - 'tests/utils/**'
      - 'tests/playwright.config.ts'
  push:
    branches: [main]
    paths:
      - 'bin/integrated_app/**'
      - 'tests/specs/**'
```

#### 建议 H2：启用视觉回归测试（对应 E1）

1. 运行 `npx playwright test --update-snapshots` 重新生成基线
2. 将 `test.skip()` 改为 `test()` 启用所有 12 个视觉回归测试
3. 在 CI 中添加 `--update-snapshots` 步骤用于基线更新 PR

```typescript
// uiux-compatibility.spec.ts — 移除 .skip
test('Home page - dark theme visual regression', async ({ page }) => {
  const basePage = new BasePage(page);
  await basePage.navigate('/');
  await basePage.switchTheme('dark');
  await expect(page).toHaveScreenshot('home-dark.png', {
    fullPage: true,
    maxDiffPixelRatio: 0.01,
  });
});
```

#### 建议 H3：扩展 CI E2E 浏览器覆盖（对应 E2）

```yaml
# .github/workflows/e2e.yml — 使用 matrix 策略
jobs:
  e2e:
    strategy:
      fail-fast: false
      matrix:
        project: [chromium-desktop, firefox-desktop, webkit-desktop]
    runs-on: ubuntu-latest
    steps:
      # ... existing steps ...
      - name: Run Playwright tests
        run: cd tests && npx playwright test --project=${{ matrix.project }}
```

#### 建议 H4：修复性能测试参数错误（对应 S3）

```python
# tests/perf/locustfile.py — 修复 page 参数
@task(2)
def view_history(self):
    """历史记录查询。"""
    with self.client.get(
        "/api/system/history?page=1&page_size=20",  # page=0 → page=1
        name="GET /api/system/history",
        catch_response=True,
    ) as response:
```

### 8.2 中优先级（近期规划）

#### 建议 M1：添加跨 OS matrix 测试（对应 C2）

```yaml
# ci.yml — 增加 matrix
jobs:
  quality-gate:
    strategy:
      fail-fast: false
      matrix:
        os: [windows-latest, ubuntu-latest]
    runs-on: ${{ matrix.os }}
```

#### 建议 M2：添加 pytest-timeout 和并行执行（对应 U2, U3）

```toml
# pyproject.toml
[tool.pytest.ini_options]
addopts = "--strict-markers --tb=short --timeout=30"
```

```diff
# requirements-dev.txt
+ pytest-timeout>=2.3
+ pytest-xdist>=3.5
```

#### 建议 M3：启用分支覆盖率（对应 U1）

```toml
# pyproject.toml
[tool.coverage.run]
branch = true
source = ["bin/integrated_app"]
```

#### 建议 M4：添加 SAST 安全扫描（对应 C8）

```yaml
# .github/workflows/security.yml
name: Security Scan
on: [pull_request]
jobs:
  semgrep:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: returntocorp/semgrep-action@v1
        with:
          config: auto
```

#### 建议 M5：集成性能测试到 CI（对应 C9, S1）

```yaml
# .github/workflows/performance.yml
name: Performance Regression
on:
  pull_request:
    branches: [main, develop]
  schedule:
    - cron: '0 2 * * *'  # 每天凌晨 2 点
jobs:
  perf:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt locust
      - name: Start app server
        run: python bin/integrated_app/app_server.py &
      - name: Wait for server
        run: sleep 5
      - name: Run performance tests
        run: |
          locust -f tests/perf/locustfile.py --headless \
            -u 20 -r 2 -t 2m \
            --host http://127.0.0.1:7870 \
            --only-summary
```

#### 建议 M6：集成 WCAG 对比度测试到 Playwright（对应 S5）

将 `wcag-contrast-test.js` 的逻辑迁移为 Playwright spec：

```typescript
// tests/specs/wcag-contrast.spec.ts
import { test, expect } from '@playwright/test';

test.describe('WCAG 2.1 AA Contrast', () => {
  test('All pages meet contrast requirements', async ({ page }) => {
    // 迁移 wcag-contrast-test.js 的逻辑
  });
});
```

#### 建议 M7：添加前端依赖审计（对应 C7）

```yaml
# dependency-audit.yml — 增加 npm audit
- name: Set up Node
  uses: actions/setup-node@v4
  with:
    node-version: '20'
- name: Run npm audit
  run: |
    cd tests
    npm audit --audit-level=moderate
```

#### 建议 M8：添加 SSE 真实连接集成测试（对应 I1）

```python
# tests/test_sse_integration.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_sse_progress_stream(test_app):
    """测试真实 SSE 连接的进度推送"""
    async with AsyncClient(app=test_app.app, base_url="http://test") as client:
        async with client.stream("GET", "/api/restore/test-task/progress") as response:
            events = []
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    events.append(line)
            assert len(events) > 0
```

#### 建议 M9：收紧触控目标和颜色对比度断言（对应 E3, E4, S7）

```typescript
// 逐步收紧阈值，从 ≤30 → ≤20 → ≤10 → =0
expect(criticalSmallTargets.length).toBeLessThanOrEqual(10); // 阶段一
// 目标：expect(criticalSmallTargets.length).toBe(0); // 最终
```

### 8.3 低优先级（长期优化）

#### 建议 L1：引入 property-based testing（对应 U4）

```python
# pip install hypothesis
from hypothesis import given, strategies as st

@given(st.integers(min_value=1, max_value=100))
def test_pagination_always_returns_valid_page(page):
    response = test_app.get(f"/api/system/history?page={page}&page_size=10")
    assert response.status_code == 200
    assert response.json()["page"] == page
```

#### 建议 L2：引入测试数据工厂（对应 U5）

```python
# pip install factory-boy
import factory

class HistoryRecordFactory(factory.Factory):
    class Meta:
        model = HistoryRecord
    task_type = "video"
    input_file = factory.Sequence(lambda n: f"/in/test_{n}.mp4")
    status = "completed"
```

#### 建议 L3：添加 OpenAPI schema 验证（对应 I2）

```python
# tests/test_api_schema.py
from fastapi.openapi.utils import get_openapi

def test_api_responses_match_openapi_schema(test_app):
    schema = test_app.app.openapi()
    # 验证所有端点的响应结构与 OpenAPI schema 一致
```

#### 建议 L4：添加网络条件测试（对应 E7）

```typescript
// tests/specs/network-conditions.spec.ts
test('Page works on slow 3G', async ({ browser }) => {
  const context = await browser.newContext({
    serviceWorkers: 'block',
  });
  await context.route('**/*', route => {
    // 模拟 slow 3G: ~400kbps, 400ms delay
  });
});
```

#### 建议 L5：添加 pytest-xdist 并行执行（对应 U3）

```bash
# CI 中使用
python -m pytest -n auto -q -m "not integration" --cov=bin/integrated_app
```

#### 建议 L6：添加 Playwright 浏览器 CI 缓存（对应 C6, E8）

```yaml
# e2e.yml
- name: Cache Playwright browsers
  uses: actions/cache@v4
  with:
    path: ~/.cache/ms-playwright
    key: ${{ runner.os }}-playwright-${{ hashFiles('tests/package-lock.json') }}
```

---

## 9. 附录：测试文件清单

### 9.1 Python 单元/集成测试

| 文件 | 测试类数 | 核心覆盖 |
|------|---------|----------|
| `test_api.py` | 10 | API 端点全面覆盖 |
| `test_ui_routes.py` | 7 | UI 参数/偏好/布局 API |
| `test_history_db.py` | 9 | 数据库 CRUD/FTS/任务/超时 |
| `test_task_queue.py` | 7 | 任务队列/取消/超时/重启/退出 |
| `test_cache.py` | 3 | FileCache/LRUCache/AdaptiveLRUCache |
| `test_metrics.py` | 2 | 指标收集/快照/线程安全 |
| `test_error_handler.py` | 4 | 异常处理/HTMX/HTTP 状态映射 |
| `test_csrf_signed.py` | 2 | HMAC CSRF 签名/密钥持久化 |
| `test_path_guard.py` | 5 | 路径白名单/遍历防护 |
| `test_fts_escape.py` | 4 | FTS5 查询转义/注入防御 |
| `test_gpu_backend.py` | 4 | GPU 后端/CUDA 可用/不可用 |
| `test_model_manager.py` | 7 | 模型加载/卸载/切换/状态 |
| `test_video_pipeline.py` | 5 | 分段流式推理/内存保护 |
| `test_config_models.py` | — | 配置模型验证 |
| `test_history_htmx.py` | — | HTMX 片段测试 |
| `test_video_processor.py` | — | 视频处理 |
| `test_exceptions.py` | — | 异常类 |
| `test_logger.py` | — | 日志 |
| `test_retry.py` | — | 重试逻辑 |
| `test_recovery.py` | — | 恢复机制 |
| `test_response.py` | — | 响应格式 |
| `test_sse_session_filter.py` | — | SSE 过滤器 |
| `test_task_events.py` | — | 任务事件 |
| `test_task_state.py` | — | 任务状态 |
| `test_gpu_utils.py` | — | GPU 工具函数 |
| `test_model_registry.py` | — | 模型注册表 |
| `test_magic_check.py` | — | 文件魔数检查 |
| `test_color_fix.py` | — | 颜色修正 |
| `test_refactor_e4_b2.py` | — | 重构验证 |

### 9.2 E2E 测试规格

| 文件 | 测试数 | 覆盖内容 |
|------|--------|----------|
| `navigation.spec.ts` | ~15 | 导航/路由/404 |
| `security.spec.ts` | ~10 | XSS/CSRF/路径遍历/CSP/Cookie |
| `a11y.spec.ts` | ~12 | axe-core/键盘/ARIA/表单/对比度 |
| `performance.spec.ts` | ~8 | Core Web Vitals/加载/内存/Bundle |
| `uiux-compatibility.spec.ts` | ~25 | 响应式/跨浏览器/触控/溢出 |
| `history.spec.ts` | — | 历史记录页 |
| `image-restore.spec.ts` | — | 图像修复流程 |
| `video-restore.spec.ts` | — | 视频修复流程 |
| `settings.spec.ts` | — | 设置页 |
| `system-status.spec.ts` | — | 系统状态 |
| `theme.spec.ts` | — | 主题切换 |
| `i18n.spec.ts` | — | 国际化 |
| `sse.spec.ts` | — | SSE 事件流 |

### 9.3 性能与专项测试

| 文件 | 类型 | 覆盖内容 |
|------|------|----------|
| `tests/perf/locustfile.py` | Locust 性能测试 | 6 个只读 API, P95/错误率阈值 |
| `tests/wcag-contrast-test.js` | 独立 WCAG 对比度 | 6 页面 × 2 主题, 20+ 元素选择器 |
| `tests/capture-screenshots.js` | 截图工具 | 页面截图采集 |

### 9.4 CI/CD 工作流

| 文件 | 用途 |
|------|------|
| `ci.yml` | 后端质量门禁 (lint+format+type+test+coverage) |
| `e2e.yml` | Playwright E2E (chromium-desktop) |
| `dependency-audit.yml` | Python 依赖安全审计 |
| `gpg-signed-release.yml` | GPG 签名发布 |

---

## 10. 总结

SeedVR2 项目的测试体系在**后端单元测试**和**前端 E2E 测试**两个维度上已达到较高成熟度，具备完整的测试分层、合理的 Fixture 设计和全面的 Mock 策略。安全测试覆盖尤为深入，涵盖 CSRF、路径遍历、FTS5 注入、XSS 等多个攻击面。

主要改进方向集中在 **CI/CD 流水线完善**（跨浏览器 CI、push 触发、性能回归集成）、**视觉回归测试启用**（当前全部 skip）、**测试阈值收紧**（触控目标软断言、颜色对比度已知问题过滤）以及**专项测试 CI 集成**（性能测试、WCAG 对比度脚本）。

按优先级执行上述改进建议后，可将测试体系从"较高成熟度"提升至"高成熟度"，实现覆盖全面、CI 自动化、阈值严格的测试质量保障闭环。

---

*报告生成时间: 2026-08-09*  
*评估工具: 代码审查 + 配置分析*  
*评估范围: SeedVR2 项目全量测试代码与 CI/CD 配置*

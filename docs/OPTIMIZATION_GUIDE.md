# SeedVR2 全面代码审查与系统性优化 — 手动执行指导

> **生成时间**: 2026-07-31
> **适用范围**: SeedVR2 视频/图像超分辨率项目（Python 3.12 + FastAPI + PyTorch CUDA）
> **使用方式**: 请按优先级从上到下依次执行每个阶段，每完成一个阶段后运行 `run_checks.bat` 确认无回归再进入下一阶段。

---

## 目录

- [0. 当前状态总览](#0-当前状态总览)
- [1. 阶段一：已完成的低风险稳定性修复（已验证）](#1-阶段一已完成的低风险稳定性修复已验证)
- [2. 阶段二：结构重构 — 大文件拆分（中高风险，需谨慎）](#2-阶段二结构重构--大文件拆分中高风险需谨慎)
- [3. 阶段三：测试覆盖率提升](#3-阶段三测试覆盖率提升)
- [4. 阶段四：模型算法只读复杂度分析报告](#4-阶段四模型算法只读复杂度分析报告)
- [5. 阶段五：配置与部署优化](#5-阶段五配置与部署优化)
- [6. 阶段六：性能监控与 KPI](#6-阶段六性能监控与-kpi)
- [7. 验证命令速查表](#7-验证命令速查表)
- [8. 风险矩阵与注意事项](#8-风险矩阵与注意事项)

---

## 0. 当前状态总览

### 质量门禁（当前全绿 ✅）

```
ruff (lint)          ✅ All checks passed
black (format)       ✅ 167 files unchanged
mypy (strict)        ✅ Success: no issues found in 69 source files
pytest (unit)        ✅ 304 passed, 1 warning (19.95s)
```

### 本次会话完成的改动（已验证，已合入工作区）

| 文件 | 改动性质 | 风险 | 验证状态 |
|---|---|---|---|
| `bin/__init__.py`（新增） | 补充 `bin` 包标记，消除 mypy 双模块解析 | 极低 | mypy 转绿 ✅ |
| `common/logger.py` | `addHandler` 幂等守卫 + `Optional` → `X \| None` | 极低 | +3 单测 ✅ |
| `bin/integrated_app/history_db.py` | `timeout=30s` + `busy_timeout` PRAGMA + `list()` 包装 | 低 | +3 单测 ✅ |
| `bin/integrated_app/app_server.py` | 删除空 `try/except` 死分支 + 类型标注清理 | 极低 | 全量回归 ✅ |
| `tests/test_logger.py`（新增） | logger 幂等性单测（3 个用例） | 无 | 通过 ✅ |
| `tests/test_history_db.py` | 连接超时单测（3 个用例）+ `real_conn.close()` 修正 | 极低 | 通过 ✅ |

### 工作区中已有的预存变更（非本次会话，需你确认是否已暂存）

`git status` 显示 133 个文件已修改（含 models/、common/、optimization/ 等）。这些变更**已包含在 `run_checks.bat` 全绿结果中**，说明它们与当前代码是一致的。建议在继续后续阶段前先 `git add` 并提交这些变更，避免后续改动与未提交状态混在一起：

```powershell
cd c:\Users\Doro\Seedvr2
git add -A
git commit -m "pre-optimization: baseline state captured before structural refactoring"
```

---

## 1. 阶段一：已完成的低风险稳定性修复（已验证）

本阶段所有改动**已经完成并验证通过**，无需再手动操作。以下仅作记录。

### 1.1 `bin/__init__.py` — 恢复 mypy 类型检查

**问题根因**: `bin/` 目录无 `__init__.py`，Python 3.12 的 PEP 420 使其成为命名空间包。mypy 在 `explicit_package_bases=true` 下同时沿两个路径解析 `blockswap.py`：

- 路径 A（沿 `__init__.py` 向上走到 `bin/` 停止）→ `integrated_app.optimization.blockswap`
- 路径 B（`mypy_path="."`）→ `bin.integrated_app.optimization.blockswap`

**修复**: 新增空 `bin/__init__.py`（仅含 docstring），使 `bin` 成为常规包，消除双模块歧义。

**文件内容**:
```python
"""``bin`` 包标记。

全项目统一以 ``from bin.integrated_app...`` 形式导入应用层代码，因此 ``bin``
应当是一个明确的常规包，而非 PEP 420 命名空间包。补齐此文件可消除 mypy 在
``explicit_package_bases`` 下将同一模块同时解析为 ``integrated_app.*`` 与
``bin.integrated_app.*`` 两个名字的歧义（"Source file found twice"）。
"""
```

### 1.2 `common/logger.py` — 防重复 addHandler

**问题根因**: `get_logger(name)` 每次调用都无条件执行 `logger.addHandler(_default_handler)`。若同一模块内多次调用（或未来重构导致重复调用），同一 handler 会被挂载多次，每条日志输出重复 N 次。

**修复**: 添加 `if _default_handler not in logger.handlers:` 守卫，确保每个 logger 最多挂一个 handler。

**关键 diff**:
```python
# BEFORE
logger.addHandler(_default_handler)

# AFTER
if _default_handler not in logger.handlers:
    logger.addHandler(_default_handler)
```

**同时**: `Optional[str]` → `str | None`（PEP 604 现代写法，移除 `from typing import Optional`）。

### 1.3 `bin/integrated_app/history_db.py` — 连接超时健壮性

**问题根因**: `aiosqlite.connect(db_path)` 使用默认 5 秒超时，高并发写入（多个 SSE 客户端同时操作历史记录）时可能因 SQLite 锁竞争直接抛出 `"database is locked"` 异常。

**修复**:
1. `HistoryDB.__init__` 新增 `timeout: float = 30.0` 参数（向后兼容，默认值更宽松）
2. `aiosqlite.connect(self.db_path, timeout=self.timeout)` 传递超时
3. 新增 `PRAGMA busy_timeout={int(timeout*1000)}` 与连接超时对齐
4. `_fetchall` 返回值包装为 `list(await cursor.fetchall())` 满足 mypy strict 类型要求

### 1.4 `bin/integrated_app/app_server.py` — 清理死分支

**问题**: `create_app` 中 `_engine_scheduler` 初始化后有一个空 `try/except` 块，仅包含 `logger.info()` 和 `logger.debug()`，无实际操作。

**修复**: 删除该空 `try/except` 块（6 行），行为无变化。

### 1.5 单元测试（6 个新用例）

| 文件 | 类名 | 用例 | 验证目标 |
|---|---|---|---|
| `tests/test_logger.py` | `TestGetLoggerIdempotent` | `test_repeated_calls_do_not_duplicate_handler` | 重复调用不重复挂 handler |
| | | `test_many_calls_keep_single_handler` | 10 次调用后仍只有 1 个 handler |
| | | `test_level_is_info` | logger 级别为 INFO |
| `tests/test_history_db.py` | `TestConnectionTimeout` | `test_default_timeout` | 默认 timeout 为 30.0 |
| | | `test_custom_timeout_stored` | 自定义 timeout 被正确存储 |
| | | `test_busy_timeout_pragma_applied` | PRAGMA busy_timeout = timeout * 1000 |

---

## 2. 阶段二：结构重构 — 大文件拆分（中高风险，需谨慎）

> **核心原则**: 纯结构调整，不改任何业务逻辑。每拆一个文件就跑一次 `run_checks.bat` 确认无回归。

### 2.1 优先拆分目标

#### A. `bin/integrated_app/engines/seedvr2_engine.py`（约 138KB，全项目最大文件）

**当前结构**: 整个文件包含 VAE 推理管线、DiT 推理管线、视频处理管线、图像处理管线、模型加载/卸载、显存管理等全部逻辑。

**建议拆分为**:
```
engines/
├── seedvr2_engine.py          # 主入口，保留 SeedVR2Engine 类骨架与 __init__/load/unload
├── _vae_pipeline.py           # VAE 编解码管线（encode/decode 方法）
├── _dit_pipeline.py           # DiT 推理管线（forward/denoise 方法）
├── _video_pipeline.py         # 视频分块处理逻辑
├── _image_pipeline.py         # 图像处理逻辑
└── _memory_utils.py           # 显存管理辅助函数
```

**拆分步骤**:
1. 先读取完整文件，按功能边界划分（搜索 `def` 和 `class` 定义）
2. 为每个子模块创建文件，将相关函数/类移入
3. 在 `seedvr2_engine.py` 中用 `from ._vae_pipeline import ...` 导入
4. 每拆一个子模块就运行 `ruff check` + `pytest -q -m "not integration"`
5. 确认 mypy 仍为 `Success`

**关键风险点**:
- 引用 `self` 的实例方法不能简单提取为独立函数——需要改为参数传递或使用 mixin
- 避免循环导入：被拆出的模块不要反向 import 主引擎

#### B. `bin/integrated_app/optimization/` 目录（多个 50KB+ 文件）

按功能域分组：
```
optimization/
├── gpu/                     # GPU 兼容性检测、显存监控
│   ├── __init__.py
│   ├── gpu_compatibility.py
│   ├── vram_monitor.py
│   └── vram_toolchain.py
├── inference/               # 推理优化
│   ├── __init__.py
│   ├── dit_optimization.py
│   ├── temporal_processing.py
│   └── diffusion_sampling.py
├── video/                   # 视频处理增强
│   ├── __init__.py
│   ├── video_processing_enhance.py
│   └── temporal_processing.py
└── engine/                  # 引擎调度与管理
    ├── __init__.py
    ├── engine_scheduler.py
    ├── specialized_engines.py
    └── framework_engineering.py
```

### 2.2 验证检查点

每完成一个文件的拆分后：

```powershell
# 格式检查
.\WPy64-312101\python\python.exe -m ruff check .
.\WPy64-312101\python\python.exe -m black --check .

# 类型检查
.\WPy64-312101\python\python.exe -m mypy bin/integrated_app

# 单元测试
.\WPy64-312101\python\python.exe -m pytest -q -m "not integration"

# 完整门禁
.\run_checks.bat
```

---

## 3. 阶段三：测试覆盖率提升

### 3.1 当前覆盖状况

| 已有测试文件 | 覆盖模块 |
|---|---|
| `test_api.py` | API 路由 |
| `test_config_models.py` | 配置模型 |
| `test_exceptions.py` | 异常层次 |
| `test_fts_escape.py` | FTS5 查询转义 |
| `test_history_db.py` | 历史数据库 |
| `test_history_htmx.py` | HTMX 历史页面 |
| `test_model_registry.py` | 模型注册中心 |
| `test_path_guard.py` | 路径安全守卫 |
| `test_refactor_e4_b2.py` | 重构验证（最大 18.6KB） |
| `test_response.py` | 统一响应格式 |
| `test_retry.py` | 重试机制 |
| `test_task_events.py` | 任务事件总线 |
| `test_task_queue.py` | 任务队列 |
| `test_task_state.py` | 任务状态存储 |
| `test_ui_routes.py` | UI 路由 |
| `test_logger.py`（新增） | logger 幂等性 |
| `tests/specs/`（13 文件） | Playwright E2E |
| `tests/wcag-contrast-test.js` | WCAG 无障碍 |

**当前覆盖率阈值**: `fail_under = 30`（`pyproject.toml`）

### 3.2 覆盖缺口（按优先级）

#### P0 — 无测试的关键模块

| 模块 | 文件 | 建议测试策略 |
|---|---|---|
| `cache.py` → `FileCache` | 文件缓存 TTL、清理任务 | mock `asyncio` + tmp_path |
| `cache.py` → `AdaptiveLRUCache` | GPU 显存自适应 | mock `_get_gpu_memory_percent` |
| `model_manager.py` | 模型加载/卸载/切换 | mock 引擎，不加载真实模型 |
| `video_processor.py` | FFmpeg 封装、视频处理 | mock subprocess |
| `gpu_backend.py` | GPU 检测、后端选择 | mock torch.cuda |
| `dependencies.py` | FastAPI 依赖注入 | FastAPI TestClient |

#### P1 — 覆盖率提升到 60%

```powershell
# 运行覆盖率报告
.\WPy64-312101\python\python.exe -m pytest --cov=bin/integrated_app --cov-report=term-missing -m "not integration"
```

重点关注 `show_missing` 输出中覆盖率低于 50% 的文件，逐一补充。

#### P2 — 覆盖率阈值升级

逐步调整 `pyproject.toml` 中的 `fail_under`：
```
30 → 40 → 50 → 60 → 70 → 80
```
每提升一次就运行 `run_checks.bat` 确认门禁仍可过。

### 3.3 编写测试的约束

- **绝对禁止**加载真实模型或占用 GPU（项目硬约束见 `docs/CONSTRAINTS.md`）
- 使用 `unittest.mock.AsyncMock` / `MagicMock` 模拟引擎、GPU、FFmpeg
- 使用 pytest fixture 中的 `tmp_path` 隔离文件系统
- 在 `conftest.py` 中注册所有共享 fixture
- 测试文件命名遵循 `test_*.py`，测试类命名 `Test*`，测试函数命名 `test_*`

---

## 4. 阶段四：模型算法只读复杂度分析报告

> **约束**: 只读分析，不修改任何模型代码。产出为书面报告。

### 4.1 分析目标文件

| 模型 | 目录 | 关键文件 |
|---|---|---|
| DiT v1 | `models/dit/` | `nadit.py`（主模型）、`attention.py`、`window.py`、`rope.py` |
| DiT v2 | `models/dit_v2/` | `na.py`（主模型）、`nablocks/mmsr_block.py`、`patch/` |
| Video VAE v3 | `models/video_vae_v3/modules/` | `video_vae.py`、`attn_video_vae.py`、`causal_inflation_lib.py` |

### 4.2 分析维度

对每个模型文件：

1. **算法复杂度**: 标注每个核心方法的时间复杂度（Big-O），特别关注：
   - 注意力计算 `O(n²d)` 是否有高效替代（flash attention、linear attention）
   - 视频分块处理的窗口大小与帧数关系
   - RoPE 旋转位置编码的预计算复杂度

2. **空间复杂度**: 标注显存占用模式：
   - 中间激活值的显存峰值估算
   - GPU Block Swap 的显存换入换出策略
   - 是否存在显存爆炸风险的边界条件

3. **潜在优化点**（仅列出，不实施）:
   - Flash Attention 2 / xFormers 替换自定义注意力
   - `torch.compile` JIT 编译可行性
   - 半精度推理的数值稳定性风险

### 4.3 产出格式

生成 `docs/model_algorithm_analysis.md`，格式示例：

```markdown
# SeedVR2 模型算法复杂度分析

## DiT v1 (models/dit/nadit.py)

### forward()
- 时间复杂度: O(B × T × H × W × d²) — self-attention 主导
- 空间复杂度: O(B × T × H × W × d) — 中间激活值
- 优化候选: Flash Attention (内存优化，非算法优化)
- 风险: 替换注意力后需全量 GPU 回归验证

### ...
```

---

## 5. 阶段五：配置与部署优化

### 5.1 `config.yaml` 审查

```powershell
# 查看当前配置结构
Get-Content config.yaml
```

**审查要点**:
- 所有配置项是否有对应的 `config.get()` 读取（无配置项被遗忘）
- `runtime.task` 下的 `max_timeout_seconds` 是否合理（当前默认 3600 = 1小时）
- `cache.ttl` 默认 86400（1天），上传文件是否需要更短的 TTL
- `i18n.default_locale` 是否与 `locales/` 下的翻译文件一致

### 5.2 `configs_3b/config.json` 与 `configs_7b/config.json`

对比两个配置文件，确认：
- 差异仅在模型大小相关的参数（如显存阈值、block swap 大小）
- 无遗漏的模型尺寸配置项
- 与 `config.yaml` 中的默认值一致

### 5.3 启动脚本

| 脚本 | 用途 | 审查要点 |
|---|---|---|
| `start.bat` | Windows 推荐入口 | 是否正确调用 WinPython，是否处理端口冲突 |
| `install.bat` | 环境安装 | 依赖安装是否使用锁定版本，是否支持离线安装 |
| `run_verify.bat` | 引擎自检 | 检查项是否覆盖配置/GPU/引擎导入三项 |
| `run_checks.bat` | 质量门禁 | 当前已验证可用 ✅ |

### 5.4 `requirements.txt` / `requirements-lock.txt` 一致性

```powershell
# 对比声明版本与锁定版本
$required = Get-Content requirements.txt | Where-Object { $_ -match '^(?!#)\S+' }
foreach ($r in $required) {
    $pkg = ($r -split '[>=<~!]')[0]
    $lock = Get-Content requirements-lock.txt | Select-String -Pattern "^$pkg=="
    if (-not $lock) { Write-Output "MISSING IN LOCK: $pkg" }
}
```

**注意**: `gunicorn>=23.0` 在 `requirements.txt` 中声明但 `requirements-lock.txt` 中缺失——Windows 上通常使用 Uvicorn 而非 Gunicorn，需确认是否真正需要。

---

## 6. 阶段六：性能监控与 KPI

### 6.1 关键性能指标

| 指标 | 建议监控方式 | 阈值 |
|---|---|---|
| 模型推理响应时间 | TaskEventBus 的时间戳差值 | 视频 < 5min/片段，图像 < 30s |
| 队列等待时间 | TaskQueue 提交到开始执行的时间差 | < 60s |
| GPU 显存占用 | `gpu_utils.get_gpu_memory_info()` | < 90% |
| 系统内存占用 | `psutil.virtual_memory()` | < 90% |
| SSE 连接数 | `event_bus.subscriber_count` | 监控峰值 |
| 数据库写延迟 | HistoryDB 操作计时 | < 100ms |
| 错误率 | 异常处理器计数 | < 1% |

### 6.2 建议实现方式

在 `bin/integrated_app/` 中新增 `metrics.py`，提供：

```python
import time
from contextlib import contextmanager

class MetricsCollector:
    """简易性能指标收集器（不引入外部依赖）。"""

    def __init__(self):
        self._timers: dict[str, list[float]] = {}
        self._counters: dict[str, int] = {}

    @contextmanager
    def timer(self, name: str):
        start = time.perf_counter()
        yield
        elapsed = time.perf_counter() - start
        self._timers.setdefault(name, []).append(elapsed)

    def increment(self, name: str):
        self._counters[name] = self._counters.get(name, 0) + 1

    def snapshot(self) -> dict:
        return {
            "timers": {
                k: {"count": len(v), "avg_ms": sum(v) / len(v) * 1000, "p95_ms": sorted(v)[int(len(v)*0.95)] * 1000 if len(v) > 1 else v[0] * 1000}
                for k, v in self._timers.items()
            },
            "counters": dict(self._counters),
        }
```

然后在关键路径（路由处理函数、引擎推理、数据库操作）中使用 `with metrics.timer("api.restore"):` 包裹。

### 6.3 SSE 暴露指标端点

在 `routes/system/` 中新增 `/api/system/metrics` 端点，返回 `metrics.snapshot()` JSON。

---

## 7. 验证命令速查表

### 日常验证（每次改动后）

```powershell
cd c:\Users\Doro\Seedvr2

# 快速门禁（跳过 mypy/pytest，仅 ruff + black）
.\run_checks.bat --fast

# 完整门禁
.\run_checks.bat

# 仅 pytest
.\WPy64-312101\python\python.exe -m pytest -q -m "not integration"

# 仅 mypy（如需单独调试类型错误）
.\WPy64-312101\python\python.exe -m mypy bin/integrated_app

# 清缓存重跑 mypy（调试缓存相关假性错误）
Remove-Item -Recurse -Force .mypy_cache
.\WPy64-312101\python\python.exe -m mypy bin/integrated_app
```

### 覆盖率分析

```powershell
# 生成覆盖率报告
.\WPy64-312101\python\python.exe -m pytest --cov=bin/integrated_app --cov-report=term-missing -m "not integration"

# 生成 HTML 报告（在 htmlcov/ 目录）
.\WPy64-312101\python\python.exe -m pytest --cov=bin/integrated_app --cov-report=html -m "not integration"
```

### 引擎自检（不加载模型）

```powershell
.\run_verify.bat
```

---

## 8. 风险矩阵与注意事项

### 高风险操作（需特别谨慎）

| 操作 | 风险等级 | 后果 | 缓解措施 |
|---|---|---|---|
| 修改 `engines/seedvr2_engine.py` | 🔴 高 | 核心推理逻辑，改错导致输出错误或 OOM | 每改 50 行就跑 pytest，GPU 环境做端到端验证 |
| 修改 `models/` 下模型代码 | 🔴 高 | 改变模型输出精度/行为 | 仅在报告中列出，不改代码 |
| 拆分 `optimization/` 大文件 | 🟡 中 | 导入路径变更可能导致运行时 ImportError | 逐步拆分，每步验证 |
| 修改 `config.yaml` 默认值 | 🟡 中 | 影响所有用户的默认行为 | 在文档中明确变更原因 |
| 增加 `fail_under` 覆盖率阈值 | 🟢 低 | 可能导致门禁暂时失败 | 每次提升不超过 10%，确保新测试可过 |

### 绝对禁止

1. **不得加载真实模型到 GPU 来运行测试** — 使用 mock/fixture
2. **不得使用 `git reset --hard`** — 除非用户明确要求
3. **不得修改 `.env`、密钥、证书等敏感文件**
4. **不得在 `optimization/` 中引入新的外部依赖** — 需先确认 PyPI 上有 Windows CUDA wheel
5. **批处理脚本保持 ASCII 英文** — 避免中文乱码

### 建议的提交粒度

每个逻辑独立的修改一个 commit，commit message 格式：

```
<type>: <简要描述>

type 类型:
  fix      — 修复 bug（如 logger 重复 handler）
  refactor — 结构重构，不改行为（如文件拆分）
  test     — 新增/补充测试
  docs     — 文档更新
  perf     — 性能优化（如 DB 连接超时）
  chore    — 工具链/配置变更
```

示例：
```
fix: logger get_logger 幂等添加 handler 防重复输出
perf: history_db 增加连接超时与 busy_timeout
test: 新增 logger 幂等性与 history_db 超时单测
chore: 补充 bin/__init__.py 修复 mypy 双模块解析
refactor: 拆分 seedvr2_engine.py 为子模块
```

---

## 附录 A：项目架构速查

```
SeedVR2/
├── bin/integrated_app/          # Web 应用层（FastAPI）
│   ├── app_server.py            # 应用入口，生命周期管理
│   ├── config.py                # 应用配置加载
│   ├── cache.py                 # FileCache / LRUCache / AdaptiveLRUCache
│   ├── history_db.py            # SQLite 异步数据库（aiosqlite + WAL + FTS5）
│   ├── task_queue.py            # 单 Worker 异步任务队列
│   ├── model_registry.py        # 模型状态注册中心（观察者模式）
│   ├── model_manager.py         # 模型加载/卸载/切换
│   ├── gpu_backend.py           # GPU 后端管理
│   ├── gpu_utils.py             # GPU 信息查询
│   ├── video_processor.py       # 视频处理（FFmpeg 封装）
│   ├── dependencies.py          # FastAPI 依赖注入
│   ├── exceptions.py            # 统一异常层次
│   ├── engines/                 # 推理引擎实现
│   ├── routes/                  # API 路由与页面路由
│   ├── services/                # 业务服务（task_state, task_events）
│   ├── middleware/               # 中间件（CORS, CSRF, error_handler）
│   ├── security/                # 安全守卫（path_guard）
│   ├── optimization/            # 优化模块（20个文件，GPU/调度/内存等）
│   ├── locales/                 # i18n 翻译文件（中/英/日/法）
│   ├── static/                  # 前端静态资源
│   └── templates/               # Jinja2 HTML 模板
├── common/                      # 共享工具层（模型训练/推理通用）
├── models/                      # 模型定义（dit/dit_v2/video_vae_v3）
├── data/                        # 运行时数据（上传文件/历史DB/transforms）
├── pretrained_models/           # 预训练权重（.safetensors）
├── tests/                       # 测试套件
├── docs/                        # 项目文档
├── configs_3b/                  # 3B 模型配置
├── configs_7b/                  # 7B 模型配置
├── WPy64-312101/                # 内嵌 WinPython（隔离环境）
├── config.yaml                  # 主配置文件
├── pyproject.toml               # 工具链配置（ruff/black/mypy/pytest）
├── requirements.txt             # 运行时依赖
├── requirements-lock.txt        # 锁定版本
└── run_checks.bat               # 质量门禁一键触发
```

## 附录 B：关键设计模式速查

| 模式 | 应用位置 | 说明 |
|---|---|---|
| 应用工厂 | `app_server.create_app()` | FastAPI 应用实例创建与配置 |
| 生命周期管理 | `app_server.lifespan()` | 异步上下文管理器，处理启动/关闭 |
| 依赖注入 | `dependencies.py` + `Depends()` | FastAPI 原生 DI，组件解耦 |
| 观察者模式 | `model_registry` + `_bridge_model_status_to_sse` | 模型状态→SSE 桥接 |
| 发布/订阅 | `event_bus`（sse.py）、`task_events.py` | 实时事件推送 |
| 单例模式 | `task_event_bus`、`task_state_store` | 全局共享实例 |
| 责任链 | `error_handler.py` 异常处理器链 | 按异常类型匹配处理 |
| 策略模式 | HTMX vs JSON 响应格式选择 | 根据请求头切换 |
| 代理模式 | `TaskStateStoreProxy` | 线程安全的缓存访问代理 |

---

*本文档由 AI 辅助生成，请结合实际代码核实关键信息后再执行。*

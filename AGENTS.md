# AGENTS.md — AI 辅助开发指南

本文件为 AI 辅助开发工具（如 CatPaw、Cursor、Copilot 等）和人类贡献者提供 SeedVR2 项目的开发约定和注意事项。

---

## 1. 项目概述

- **项目名称**：SeedVR2 — AI 视频与图像超分辨率修复工具箱
- **技术栈**：Python 3.12 + FastAPI + PyTorch + Jinja2 + htmx
- **开源协议**：Apache-2.0
- **版本**：v1.0.0

---

## 2. 代码风格

### 2.1 工具配置

| 工具 | 配置位置 | 说明 |
|------|----------|------|
| Ruff | `pyproject.toml [tool.ruff]` | Lint + Format，target py312，line-length 120 |
| Black | `pyproject.toml [tool.black]` | 格式化，line-length 120 |
| Mypy | `pyproject.toml [tool.mypy]` | 渐进式类型检查，非严格模式 |
| Pytest | `pyproject.toml [tool.pytest.ini_options]` | asyncio_mode=auto，timeout=60s |

### 2.2 命名规则

- **Python 模块/文件**：`snake_case.py`
- **类名**：`PascalCase`
- **函数/变量**：`snake_case`
- **常量**：`UPPER_SNAKE_CASE`
- **私有**：`_prefix`

**例外**（已在 `per-file-ignores` 中配置豁免）：
- `models/**` — 上游研究代码，遵循 ML/PyTorch 命名约定（`B/C/H/W/T` 维度名、`F` = `functional`、`input` 参数名等）
- `common/diffusion/**` — 扩散相关数值代码
- `bin/integrated_app/optimization/**` — GPU 优化路径

### 2.3 导入顺序

```python
# 1. 标准库
import os
import sys

# 2. 第三方库
from fastapi import APIRouter
import torch

# 3. 项目模块
from bin.integrated_app.config import load_config
from bin.integrated_app.utils.response import respond_success
```

---

## 3. 目录结构与修改规则

### 3.1 不可随意修改的目录

| 目录 | 原因 | 修改条件 |
|------|------|----------|
| `models/` | 上游 ByteDance 研究代码镜像（Apache-2.0） | 仅同步上游更新，不自行修改 |
| `common/` | 通用深度学习组件 | 需充分理解扩散模型原理后修改 |
| `configs_3b/` `configs_7b/` | 模型配置文件 | 仅在模型版本变更时修改 |

### 3.2 可修改的核心目录

| 目录 | 职责 | 修改注意事项 |
|------|------|--------------|
| `bin/integrated_app/routes/` | API 路由 | 新增路由文件放入此目录，定义 `router = APIRouter(...)` 即可自动注册 |
| `bin/integrated_app/services/` | 业务服务 | 保持单一职责 |
| `bin/integrated_app/middleware/` | 中间件 | 在 `app_server.py create_app()` 中注册 |
| `bin/integrated_app/security/` | 安全模块 | 修改需评估安全影响 |
| `bin/integrated_app/templates/` | HTML 模板 | 保持 i18n key 一致性 |
| `bin/integrated_app/static/` | 前端资源 | CSS/JS 变更需清理浏览器缓存 |
| `bin/integrated_app/locales/` | 翻译文件 | JSON 格式，5 种语言同步更新 |
| `tests/` | 测试 | 新功能必须补测试 |

### 3.3 路由自动发现

`routes/__init__.py` 使用 `pkgutil` 递归扫描 `routes/` 包，自动发现带 `router` 属性的模块。

**新增路由步骤**：
1. 在 `routes/` 下创建新文件（如 `routes/system/new_feature.py`）
2. 定义 `router = APIRouter(prefix="/api/system", tags=["新功能"])`
3. 编写端点函数
4. 无需修改任何注册代码，路由自动生效

---

## 4. 测试约定

### 4.1 测试要求

- **新功能必须补测试**：新增的 API 端点、服务方法、工具函数都需有对应测试
- **覆盖率不低于 65%**：`pyproject.toml` 中 `fail_under=65`，CI 会检查
- **覆盖率统计范围**：仅 `bin/integrated_app`（排除 `models/` 和 GPU 推理路径）

### 4.2 测试文件命名

| 类型 | 命名 | 位置 |
|------|------|------|
| 单元测试 | `test_*.py` | `tests/` |
| 集成测试 | `test_*.py`（标记 `@pytest.mark.integration`） | `tests/` |
| E2E 测试 | `*.spec.ts` | `tests/specs/` |
| 性能测试 | `locustfile.py` | `tests/perf/` |

### 4.3 运行测试

```bash
# 全部 Python 测试
pytest

# 仅单元测试（排除集成测试）
pytest -m "not integration"

# 带覆盖率
pytest --cov=bin/integrated_app --cov-report=html

# 特定测试文件
pytest tests/test_history_db.py -v

# E2E 测试（需要服务运行）
npx playwright test

# 类型检查
mypy bin/integrated_app/

# Lint
ruff check .
ruff format .
```

### 4.4 测试编写规范

```python
# tests/test_example.py
import pytest

class TestExample:
    """测试类使用 PascalCase，以 Test 前缀。"""

    @pytest.mark.asyncio
    async def test_async_function(self):
        """异步测试方法使用 test_ 前缀。"""
        result = await some_async_function()
        assert result is not None

    def test_sync_function(self):
        """同步测试方法。"""
        assert 1 + 1 == 2
```

---

## 5. API 响应格式

### 5.1 统一响应包装

使用 `bin/integrated_app/utils/response.py` 中的 `respond_success`：

```python
from bin.integrated_app.utils.response import respond_success

@router.get("/example")
async def example():
    return respond_success({"key": "value"})
    # 返回: {"success": true, "data": {"key": "value"}, "error": null}
```

### 5.2 错误响应

使用 HTTPException：

```python
from fastapi import HTTPException

raise HTTPException(status_code=404, detail="资源不存在")
# 返回: {"detail": "资源不存在"}
```

---

## 6. 安全注意事项

### 6.1 路径安全

- 所有文件操作必须通过 `PathGuard` 白名单校验
- 拒绝包含 `..` 的路径
- 使用 `os.path.realpath()` 解析符号链接
- `follow_symlinks=False` 防止绕过白名单

### 6.2 上传安全

- 使用 `validate_upload_magic()` 校验文件魔数
- 限制文件大小（图片 50MB，视频 500MB）
- 速率限制：30 次/分钟

### 6.3 模型安全

- 优先使用 `weights_only=True` 加载权重
- SHA256 校验模型文件完整性
- 切勿加载来源不明的权重文件

### 6.4 网络安全

- **严禁**将 `server.host` 修改为 `0.0.0.0`
- 公网部署必须通过 Nginx + Basic Auth + HTTPS
- CSRF 中间件已全局启用

---

## 7. 依赖管理

### 7.1 依赖文件

| 文件 | 用途 |
|------|------|
| `requirements.txt` | 运行依赖 |
| `requirements-dev.txt` | 开发依赖（测试、lint 工具等） |
| `requirements-lock.txt` | 锁定精确版本（支持 `--require-hashes`） |
| `pyproject.toml` | 项目元数据 + 工具配置 |

### 7.2 添加新依赖

1. 添加到 `requirements.txt`（运行依赖）或 `requirements-dev.txt`（开发依赖）
2. 运行 `python scripts/generate_lock.py` 重新生成锁文件
3. 在 `pyproject.toml` 的 `[[tool.mypy.overrides]]` 中添加无类型存根的第三方模块

---

## 8. 国际化 (i18n)

### 8.1 翻译文件

- 位置：`bin/integrated_app/locales/`
- 格式：JSON
- 语言：`zh`、`zh-TW`、`en`、`ja`、`fr`

### 8.2 使用翻译

```python
# 在路由中
i18n = request.app.state.i18n
translated = i18n.t("settings.copyright_notice")

# 在模板中
{{ t("key.name") }}
```

### 8.3 三层回退

1. 指定语言的翻译
2. 英文 (`en`) 翻译
3. key 本身（兜底）

### 8.4 添加新翻译

1. 在所有 5 个语言文件中添加相同的 key
2. 使用 `python scripts/check_i18n_keys.py` 验证 key 完整性
3. 扁平键（含点号）不会被误判为嵌套结构

---

## 9. Git 提交规范

### 9.1 提交信息格式

```
<type>: <简短描述>

<详细说明（可选）>
```

类型：
- `feat`：新功能
- `fix`：Bug 修复
- `docs`：文档变更
- `style`：代码格式（不影响功能）
- `refactor`：重构（无新功能、无 Bug 修复）
- `test`：测试相关
- `chore`：构建、工具、依赖等杂项
- `security`：安全相关

### 9.2 分支策略

- `main`：稳定发布分支
- `dev`：开发分支（如有）
- `feature/*`：功能分支
- `fix/*`：修复分支

---

## 10. 常见陷阱

### 10.1 进度回调必须为同步函数

推理在 `asyncio.to_thread` 中同步执行，进度回调被同步调用。若注册 async 函数，其函数体不会被执行。

```python
# ✅ 正确：同步回调
def progress_callback(current_frame, total_frames, progress, **kwargs):
    common.get_task_cache().update(task_id, progress=round(progress, 1))

# ❌ 错误：async 回调（不会执行）
async def progress_callback(current_frame, total_frames, progress, **kwargs):
    await common.update_cache(task_id, progress=progress)
```

### 10.2 路由 prefix 重复

每个路由模块的 `APIRouter(prefix=...)` 已自带前缀，不要在端点路径中重复：

```python
# ✅ 正确
router = APIRouter(prefix="/api/restore")

@router.post("/batch")  # 实际路径: /api/restore/batch
async def batch_restore(): ...

# ❌ 错误
router = APIRouter(prefix="/api/restore")

@router.post("/api/restore/batch")  # 实际路径: /api/restore/api/restore/batch
async def batch_restore(): ...
```

### 10.3 依赖注入

使用 FastAPI 的 `Depends()` 获取共享实例，不要直接导入全局变量：

```python
# ✅ 正确
from bin.integrated_app.dependencies import get_history_db

@router.get("/example")
async def example(history_db: HistoryDB = Depends(get_history_db)):
    ...

# ❌ 不推荐（绕过依赖注入，难以测试）
from bin.integrated_app.app_server import app
history_db = app.state.history_db
```

---

*文档更新时间：2026-08-10*

# SeedVR2 项目上下文

本文件用于给代理和维护者提供当前项目的高频背景信息。
它不是最高优先级规则文档；执行时仍以 `AGENTS.md` 和当前代码为准。

---

## 1. 项目概览

SeedVR2 是一个脱离 ComfyUI 独立运行的视频/图像修复工具箱，提供基于 FastAPI 的 Web UI，支持图像修复、视频修复、批量处理、历史记录、系统状态与设置管理。

当前维护时应注意：

- 文档中的项目事实必须以仓库现状为准
- 旧文档里关于分离的图像/视频页面和路由的描述已不再适用
- 需要优先参考运行中的代码路径，而不是历史设计稿

---

## 2. 当前入口与运行方式

### 2.1 Windows 推荐启动链路

```text
start.bat
  -> bin/clean_launch.py
  -> bin/integrated_app/app_server.py
```

### 2.2 默认运行参数

- 默认地址：`127.0.0.1`
- 默认端口：`7870`
- 默认运行时假设：优先使用项目内 WinPython，避免与系统 Python 混用

### 2.3 启动阶段典型流程

应用启动后通常会执行以下步骤：

1. 加载配置
2. 创建 FastAPI 应用
3. 初始化数据库、任务队列、缓存、国际化、模型管理器等组件
4. 恢复未完成任务
5. 依据配置执行模型自动加载
6. 可选自动打开浏览器

---

## 3. 当前页面与路由

### 3.1 页面路由

- `/`
- `/restore`
- `/settings`
- `/history`
- `/system-status`

### 3.2 API 路由

- 修复接口前缀：`/api/restore`
- 系统接口前缀：`/api/system`

### 3.3 当前路由实现要点

- 图像修复与视频修复已统一到 `bin/integrated_app/routes/restore/unified.py`
- 页面模板当前以 `restore.html` 为统一修复页
- 不应再假设存在 `image_restore.html`、`video_restore.html` 或 `/image-restore`、`/video-restore`

---

## 4. 关键模块速查

### 4.1 应用层

- `bin/integrated_app/app_server.py`
  - 创建应用
  - 注册中间件、路由、模板环境
  - 管理启动与关闭生命周期

- `bin/integrated_app/dependencies.py`
  - 提供基于 `app.state` 的依赖注入

### 4.2 推理与模型

- `bin/integrated_app/engines/seedvr2_engine.py`
  - 核心推理逻辑
  - 分阶段模型处理与显存/内存控制

- `bin/integrated_app/model_manager.py`
  - 负责模型加载、卸载、切换与相关校验

- `bin/integrated_app/model_registry.py`
  - 保存当前模型状态
  - 为其他模块提供当前模型信息

- `bin/integrated_app/gpu_backend.py`
  - GPU 后端抽象
  - 修改前必须以当前实现为准，不要根据旧文档假设支持矩阵

### 4.3 任务与状态

- `bin/integrated_app/task_queue.py`
  - 单 worker 串行执行任务，避免并发推理导致 OOM

- `bin/integrated_app/history_db.py`
  - 持久化历史记录、任务状态与恢复信息

- `bin/integrated_app/progress.py`
  - 进度追踪相关能力

### 4.4 系统与界面

- `bin/integrated_app/routes/system/`
  - 系统健康、GPU、设置、历史、SSE 等接口

- `bin/integrated_app/templates/`
  - Jinja2 页面模板

- `bin/integrated_app/static/`
  - CSS、JavaScript 和前端静态资源

---

## 5. 当前实现中的稳定约束

这些约束来自当前代码与 `docs/CONSTRAINTS.md`，属于高频注意事项：

- 应用必须独立运行，不依赖 ComfyUI 运行时
- WebUI 设置应与工作流参数一一对应
- 默认参数应尽量与工作流默认值一致
- 模型加载前要做内存预检，可用内存至少为模型大小的 1.5 倍
- 内存使用超过 90% 时应立即终止相关推理
- I/O 组件不应被卸载到 CPU RAM
- Windows 批处理脚本应避免中文，尽量保持 ASCII 英文

---

## 6. 测试与质量工具

### 6.1 Python 测试

- 使用 `pytest`
- 现有测试位于 `tests/`
- 常见场景包括 API、配置模型、异常、历史记录等

### 6.2 前端 E2E

- 使用 Playwright + TypeScript
- 工作目录在 `tests/`
- 常用命令：`npx playwright test`

### 6.3 代码质量

- `ruff`
- `black`
- `mypy`

在修改 Python 代码后，应至少做与改动范围相匹配的检查；文档修改则重点核对事实准确性与结构一致性。

---

## 7. 容易过时的信息

以下内容最容易因为项目演进而失效，引用前必须重新核对：

- 页面名称与页面路由
- 图像/视频修复入口是否拆分
- GPU 支持矩阵
- 默认语言与设置是否允许运行时修改
- 历史记录是否允许删除
- Docker 启动方式与应用入口

如果某项信息需要写回文档，优先先读当前代码，再更新文档。

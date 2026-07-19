# AGENTS.md - SeedVR2 代理工作规范

本文件只保留代理执行任务时必须遵循的规则，以及少量高频项目速查信息。

- 详细项目背景请看 `docs/PROJECT_CONTEXT.md`
- 项目硬约束请看 `docs/CONSTRAINTS.md`
- 当这三个文件冲突时，优先级为：本文件 > `docs/CONSTRAINTS.md` > 其他项目文档

---

## 1. 最高优先级规则

1. **任务未真正完成前，禁止主动结束。**
2. **需要用户确认、补充信息或做选择时，必须使用 `AskUserQuestion`，不能在普通消息末尾抛出问题后结束。**
3. **涉及用户手动步骤时，必须等待用户确认完成，并主动验证结果。**
4. **遇到权限不足时，先尝试提权或其他可行自动化方案，再考虑转为手动步骤。**
5. **禁止编造信息；不确定时必须明确说明不确定性。**
6. **所有面对用户的说明默认使用中文。**

---

## 2. 标准工作流

### 2.1 先澄清，再执行

出现以下情况时必须先澄清：

- 需求目标不明确，例如"优化性能""修一下"
- 规格缺失，例如接口字段、输出格式、兼容范围不明确
- 指令冲突，例如既要"最少改动"又要"大规模重构"
- 存在多种合理实现且结果差异明显

澄清要求：

- 问题要具体，不要笼统说"请澄清需求"
- 尽量给出可选项，并说明不同选项的影响
- 未澄清前不要自行假设关键需求

### 2.2 先搜索，再下结论

遇到以下情况时必须联网或查资料验证：

- 报错、兼容性问题、版本差异超出已知知识范围
- 明显依赖时效性的事实，例如最新版本、API 变更、安全公告
- 需要准确数值、配置语法、兼容矩阵

搜索原则：

- 优先官方文档、官方仓库、可靠 issue、权威技术资料
- 关键结论尽量交叉验证
- 引用外部事实时尽量附来源

### 2.3 先读取，再修改

- 修改文件前先阅读当前内容，禁止盲改
- 优先用专用工具读取、搜索、编辑，不用命令行替代
- 变更后必须做最小充分验证

### 2.4 先验证，再交付

- 代码修改后至少做与改动范围匹配的验证
- 文档修改后至少检查结构、术语、链接和事实是否一致
- 遇到错误不能静默跳过，必须告知用户并继续处理或明确阻塞点

---

## 3. 工具使用规则

### 3.1 工具选择

- `AskUserQuestion`：仅用于用户决策、确认、补充信息
- `Read` / `Grep` / `Glob` / `SearchCodebase`：优先于 `RunCommand`
- `Task`：用于大型任务拆解、并行搜索、多模块探索
- `WebSearch` / `WebFetch`：用于知识缺口、时效信息、事实校验
- `GetDiagnostics`：在实质性编辑后检查最近修改文件

### 3.2 使用顺序

- 先搜索/读取，再编辑
- 先澄清，再执行
- 先验证，再交付
- 独立任务可以并行，但有依赖时必须串行

### 3.3 用户沟通

- 执行过程中要持续汇报进展、发现和阻塞
- 发现意外结果要立即说明，不能悄悄改策略
- 如果回复末尾需要用户回答，而任务尚未完成，则必须使用 `AskUserQuestion`

### 3.4 上下文与记忆

- 优先复用现有上下文，不要重复读取同一文件
- 涉及项目约定、历史决策、用户偏好时先查 memory
- 用户说"记住"时，区分用户级记忆与项目级记忆分别存放

---

## 4. 安全与变更边界

### 4.1 禁止行为

- 不得编造事实或把猜测当成结论
- 不得在需求模糊时跳过澄清
- 不得在需要确认时用普通消息提问后直接结束
- 不得让用户手动执行后不验证就结束
- 不得在未获授权时执行高风险或破坏性操作

### 4.2 敏感信息

- 不主动读取、改写或传播敏感文件，例如 `.env`、密钥、证书、凭据文件
- 如确需处理，先说明风险并获得明确授权
- 联网搜索时不得带出敏感信息

### 4.3 Git 与工作区

- 不回滚用户未要求回滚的修改
- 不覆盖你未理解的现有改动
- 工作过程中如果发现异常变更，立即暂停并询问用户
- 禁止使用 `git reset --hard`、`git checkout --` 等破坏性回滚，除非用户明确要求

---

## 5. 编码与文档约定

### 5.1 语言与表达

- 面向用户的文字统一使用中文
- 代码、命名、注释遵循对应语言惯例
- 注释保持简洁，只解释不明显的逻辑

### 5.2 命名规范

- JavaScript / TypeScript：变量与函数用 `camelCase`，类名用 `PascalCase`
- Python：变量、函数、文件名用 `snake_case`
- 常量：使用全大写加下划线
- 文件名避免空格与特殊字符

### 5.3 脚本编码

- `.bat`：尽量只写 ASCII 英文，避免中文乱码
- `.ps1`：使用 UTF-8 with BOM
- `.py`：使用 UTF-8，必要时保留编码声明
- JSON / YAML / TOML：使用 UTF-8

---

## 6. SeedVR2 项目速查

### 6.1 运行与入口

- Windows 推荐入口：`start.bat`
- 启动链路：`start.bat` -> `bin/clean_launch.py` -> `bin/integrated_app/app_server.py`
- 默认地址：`127.0.0.1:7870`
- 默认假设：优先使用项目内 WinPython，避免与系统 Python 混用
- 启动阶段：加载配置 -> 创建应用 -> 初始化数据库/任务队列/缓存/国际化/模型管理器 -> 注册模型状态 SSE 桥接 -> 恢复未完成任务 -> 缓存清理任务 -> GPU 检测 -> 可选模型预加载 -> 可选自动打开浏览器

### 6.2 当前页面与 API

- 页面路由：`/`、`/restore`、`/settings`、`/history`、`/system-status`
- 修复 API 前缀：`/api/restore`
- 系统 API 前缀：`/api/system`
- 修复路由已统一聚合到 `bin/integrated_app/routes/restore/unified.py`，其下按职责拆分为子路由：
  - `scan.py`：文件夹扫描（受 `security/path_guard.py` 白名单约束）
  - `batch.py`：批量文件夹修复，带指数退避重试
  - `upload.py`：单文件上传修复
  - `task.py`：任务查询/控制
  - `recovery.py`：启动时从数据库恢复未完成任务并重新入队
  - `common.py`：参数解析与公共辅助
- 系统路由位于 `bin/integrated_app/routes/system/`：`health.py`、`gpu.py`、`settings.py`、`history.py`、`sse.py`（SSE 事件推送）

### 6.3 核心模块

应用层：

- `app_server.py`：应用创建、中间件/路由注册、生命周期管理
- `dependencies.py`：基于 `app.state` 的依赖注入
- `config.py` / `config_models.py`：配置加载（`config.yaml`），经 Pydantic 校验（忽略未知字段、范围校验），失败时回退原始 YAML 加载
- `i18n.py`：国际化，支持 `zh` / `en` / `ja` / `fr` 四语言，翻译文件在 `locales/`
- `middleware/csrf.py`：CSRF 保护中间件，写请求校验 token，对 SSE/进度/扫描等安全 GET 放行
- `middleware/error_handler.py`：统一 JSON 错误响应（区分 HTMX 请求）

推理与模型：

- `engines/seedvr2_engine.py`：核心推理实现
- `engine_interface.py`：`RestoreEngine` 抽象基类 + `RestoreResult`，定义所有引擎统一契约（`SeedVR2Engine` 继承）
- `model_manager.py`：模型加载、卸载、切换与校验
- `model_registry.py`：当前模型状态注册，状态变更通过监听器桥接到 SSE 事件总线
- `gpu_backend.py` / `gpu_utils.py`：GPU 后端抽象与工具，仅支持 NVIDIA CUDA，未检测到则降级报错
- `optimization/memory_manager.py`：VRAM/内存预检、缓存与设备调度
- `optimization/blockswap.py`：推理时 GPU/CPU 间动态换入换出 transformer 块（含 RoPE OOM 回退、I/O 组件卸载）
- `video_processor.py`：FFmpeg 分帧/合帧与视频元信息
- `color_fix.py`：LAB 颜色匹配后处理

任务与状态：

- `task_queue.py`：单 worker 串行任务队列，避免并发推理 OOM
- `history_db.py`：历史记录与任务状态持久化
- `progress.py`：进度追踪
- `services/task_state.py`：线程安全的任务状态双层存储（内存缓存 + 数据库，数据库为唯一可信源）
- `services/task_events.py`：按 task_id 的进度事件总线，替代高频 DB 轮询，支持跨线程发布与背压
- `cache.py`：上传文件缓存与过期清理
- `security/path_guard.py`：路径白名单守卫，防止路径遍历泄露文件清单
- `utils/response.py`：统一响应包装 `{success, data, error}`
- `utils/retry.py`、`utils/fts.py`：重试退避、全文检索辅助

### 6.4 项目硬约束

- 应用必须脱离 ComfyUI 独立运行
- **SeedVR2 模型仅支持 NVIDIA CUDA GPU 推理，不支持 CPU 推理**
- WebUI 参数与默认值必须与工作流约束保持一致
- 模型加载前做内存预检，可用内存至少为模型大小的 1.5 倍
- 内存超过 90% 时必须立即终止相关推理
- I/O 组件不应被卸载到 CPU RAM
- 批处理脚本保持 ASCII 英文
- 文件夹扫描必须经 `security/path_guard.py` 白名单校验，禁止任意目录遍历
- 所有 API 响应统一收敛为 `{success, data, error}` 结构

### 6.5 当前实现注意点

- GPU 后端仅支持 NVIDIA CUDA，启动时会自动检测，未检测到则报错退出
- 默认语言配置以 `config.yaml` 为准，修改前先核对运行时代码
- 历史记录、设置、页面结构等信息必须以当前代码为准，不要照抄旧文档
- i18n 当前支持中/英/日/法四语言，新增文案需同步更新 `locales/` 下对应翻译
- 模型状态通过 `model_registry` 监听器桥接到 SSE 事件总线，模块间解耦，不要直接 import event_bus

### 6.6 测试与质量

- Python 测试：`pytest`
- 前端 E2E：在 `tests/` 下运行 `npx playwright test`
- 代码质量：`ruff`、`black`、`mypy`
- 测试场景中应避免真实模型自动加载，优先使用 mock 或现有测试夹具

---

## 7. 交付前自检

- [ ] 我是否已经真正完成任务，而不是停在建议阶段？
- [ ] 是否还有必须由用户确认的信息未通过 `AskUserQuestion` 获取？
- [ ] 我是否区分了事实、推断和不确定项？
- [ ] 我是否先读取再修改，并验证了关键变更？
- [ ] 我是否遵守了安全边界，没有误动敏感文件或高风险操作？
- [ ] 如果涉及项目事实，我是否以当前代码和当前配置为准？

---

## 8. 参考文档

- `docs/PROJECT_CONTEXT.md`：项目结构、模块职责、运行链路、当前路由
- `docs/CONSTRAINTS.md`：长期有效的项目硬约束

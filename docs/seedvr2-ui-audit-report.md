# SeedVR2 Web UI/UX 与代码质量审计报告

> 审计日期：2026-06-24
> 审计环境：Windows 11, CPU 模式（无 GPU），浏览器内截图
> 审计范围：前端 HTML 模板（7 个）、CSS（style.css ~3000 行）、JS（app.js ~1400 行）

---

## 一、审计概览

### 1.1 审计方法

1. **视觉检查**：启动 Web 服务器，对所有 5 个页面（首页、修复、设置、历史记录、系统状态）进行 Dark/Light 双主题截图，并采集移动端响应式截图
2. **代码审查**：对 HTML 模板、CSS 样式表、JavaScript 脚本进行静态分析，重点关注安全、国际化、性能和代码质量
3. **交叉验证**：将视觉发现与代码实现对照，确认问题根源

### 1.2 技术栈概览

| 维度 | 现状 |
|------|------|
| 后端框架 | FastAPI + Uvicorn |
| 模板引擎 | Jinja2（服务端渲染） |
| CSS 框架 | Bootstrap 5.3.3 + 自定义 CSS 变量设计系统（~3000 行） |
| JS 框架 | 无框架，IIFE 模式 + SeedVR2 命名空间（~1400 行） |
| 交互增强 | HTMX 2.0.4（部分动态加载）+ Alpine.js（仅设置页 Tab） |
| 图标库 | Bootstrap Icons 1.11.3 |
| 字体 | Google Fonts Inter（400/500/600/700/800） |
| 主题系统 | CSS 变量驱动，Dark/Light 双主题，localStorage 持久化 |

---

## 二、视觉审查结果

### 2.1 整体视觉印象

**优势：**
- 设计系统完整度高，Dark/Light 双主题切换流畅，无闪烁（head 中内联主题初始化脚本）
- 卡片式布局清晰，视觉层次分明，紫色主色调统一
- 导航栏、状态栏、面包屑导航一致性好
- 底部状态栏提供实时系统信息（版本、GPU 状态、时间），信息密度合理

**问题：**
- 首页功能卡片区域仅 3 个卡片（修复、系统状态、历史记录），第 4 个位置为空白，布局不对称
- 首页 Hero 区域与功能卡片之间缺少视觉过渡，整体页面显得内容偏少
- 历史记录页表格行数较多时（20 条/页），页面纵向拉伸较长，缺少 sticky 表头

### 2.2 布局与间距

| 页面 | 观察结果 | 问题 |
|------|---------|------|
| 首页 | Hero 标题居中，3 个功能卡片 2x2 网格（第 4 格空白） | 网格不对称，建议改为 3 列或添加第 4 个功能入口 |
| 修复页 | 左侧文件上传区 + 右侧参数面板双栏布局 | 布局合理，但在 1366px 笔记本屏幕上右侧面板可能偏窄 |
| 设置页 | 左侧 Tab 导航（220px）+ 右侧内容区 | 布局清晰，Tab 切换流畅 |
| 历史记录 | 全宽表格 + 顶部搜索/筛选栏 | 表格列数多（8 列），小屏幕下需要横向滚动 |
| 系统状态 | 2x2 卡片网格（GPU/模型/内存/运行信息） | 布局合理，信息密度适中 |

### 2.3 排版

- **字体栈**：`Inter, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Noto Sans SC, sans-serif` — 选择合理，中文回退到 Noto Sans SC
- **标题层级**：页面标题 h1（1.6rem/700）→ 区块标题 h3（0.95rem/600），缺少 h2 层级，存在层级跳跃
- **首页 Hero 标题**（2.25rem/800）与页面标题（1.6rem/700）权重差异明显，视觉节奏合理
- **表格文字**（0.85rem）和**状态栏文字**（0.75rem）偏小，但在桌面端可接受

### 2.4 颜色一致性

- **Dark 主题**：深色背景（`#0f0f1a`）+ 紫色主色（`#8b7cf5`）+ 绿色语义色，对比度良好
- **Light 主题**：白色背景 + 紫色主色（`#5b4cd5`）+ 灰色辅助色，整体清爽
- **语义色**：成功（绿色）、警告（黄色）、错误（红色）在双主题下均可辨识
- **Badge 颜色**：已完成（绿色）、处理中（蓝色）、等待中（黄色）、失败（红色），区分度高

### 2.5 响应式行为

- **桌面端（>992px）**：双栏布局正常，导航栏水平排列
- **平板端（768-992px）**：修复页参数面板默认折叠，设置页 Tab 变为横向滚动
- **移动端（<576px）**：导航栏变为汉堡菜单，所有网格变单列，功能卡片堆叠
- **触摸目标**：按钮最小尺寸满足 44px 要求

### 2.6 无障碍

**已实现的无障碍特性：**
- Skip-to-content 链接
- ARIA roles：`tablist`, `tab`, `menu`, `progressbar`, `status`
- `aria-label`, `aria-expanded`, `aria-selected`, `aria-hidden` 属性
- `focus-visible` 样式
- `prefers-reduced-motion` 媒体查询
- 模态框焦点陷阱

**待改进：**
- 颜色对比度未进行 WCAG AA 定量验证
- 历史记录表格操作列的图标按钮缺少 tooltip 文本（仅有 `aria-label`）

---

## 三、代码质量审查结果

### 3.1 HTML 问题

#### P0 - 严重

**[H-01] innerHTML XSS 漏洞 — 历史记录表格**
- 文件：`templates/history.html:188-231`
- 问题：`records.map(r => ...)` 中 `r.input_file`、`r.output_file` 等字段直接拼入 HTML 模板字符串，未经 `escapeHtml()` 转义
- 影响：如果文件名包含 `<script>` 等恶意内容，可导致 XSS 攻击
- 修复：所有动态数据插入前调用 `SeedVR2.escapeHtml()`

**[H-02] innerHTML XSS 漏洞 — 文件夹扫描结果**
- 文件：`templates/restore.html:423`
- 问题：`scannedFiles.slice(0,10).map(f => ...)` 中 `f.relative` 直接拼入 HTML，未经转义
- 影响：恶意文件名可导致 XSS
- 修复：`<div class="sv-text-sm sv-text-secondary">${SeedVR2.escapeHtml(f.relative)}</div>`

#### P1 - 高

**[H-03] `lang="zh"` 硬编码**
- 文件：`templates/base.html:2`
- 问题：`<html lang="zh">` 未根据 `current_locale` 动态设置
- 影响：非中文用户屏幕阅读器会以中文朗读页面
- 修复：`<html lang="{{ current_locale }}" data-theme="dark">`

**[H-04] CSP `unsafe-inline`**
- 文件：`templates/base.html:6`
- 问题：`script-src 'self' 'unsafe-inline'` 允许任意内联脚本执行，削弱了 CSP 的 XSS 防护能力
- 影响：降低了整体安全性
- 修复：使用 nonce 或 hash 替代 `'unsafe-inline'`

**[H-05] 硬编码中文 — 系统状态页**
- 文件：`templates/system_status.html:238-239`
- 问题：`innerHTML = '<span class="sv-text-xs sv-text-muted">CPU 模式</span>'` 中 "CPU 模式" 硬编码
- 修复：使用 `I["system.cpu_mode"]` 替代

#### P2 - 中

**[H-06] Alpine.js 仅设置页使用**
- 文件：`templates/settings.html:16`
- 问题：`x-data="{ tab: 'paths' }"` 仅在设置页使用 Alpine.js，其他页面未引入
- 影响：技术栈不一致，增加了不必要的依赖
- 建议：改用纯 JS 实现 Tab 切换（app.js 中已有 `initSettingsTabs` 函数）

**[H-07] `oncontextmenu` 内联事件**
- 文件：`templates/history_table.html:3`
- 问题：`oncontextmenu="SeedVR2.showRowContextMenu(event, this)"` 使用内联事件处理器
- 建议：改用事件委托

**[H-08] 缺少 favicon 的 Apple touch icon**
- 文件：`templates/base.html:17`
- 问题：仅有 SVG data URI favicon，缺少 `apple-touch-icon`
- 影响：iOS 添加到主屏幕时显示默认图标

### 3.2 CSS 问题

#### P2 - 中

**[C-01] 单文件体量过大**
- 文件：`static/css/style.css`（~3000 行）
- 问题：所有样式集中在单个文件中，包含基础样式、组件样式、页面特定样式、工具类、响应式样式
- 建议：按模块拆分为 `base.css`、`components.css`、`pages/`、`utilities.css`，通过构建工具合并

**[C-02] 硬编码颜色值**
- 位置：多处
- 问题：`.bg-success` 中 `#6ee7b7`（~983 行）、`.sv-badge-completed` 中 `#0f6b32`（~2784 行）等颜色值硬编码，未使用 CSS 变量
- 影响：主题切换时这些颜色不会跟随变化
- 修复：提取为 CSS 变量（如 `--sv-success-bg`, `--sv-completed-color`）

**[C-03] Light 主题特殊覆盖散落**
- 位置：~2749-2785 行
- 问题：Light 主题的特殊颜色覆盖集中在文件末尾，而非与 Dark 主题定义放在一起
- 建议：将 Dark/Light 主题变量定义集中在 `:root` 和 `[data-theme="light"]` 块中

#### P3 - 低

**[C-04] `[x-cloak]` 重复定义**
- 位置：第 383 行 vs 第 2097 行
- 问题：同一规则定义了两次
- 修复：删除重复定义

**[C-05] `.sv-card.interactive` 未使用**
- 问题：CSS 中定义了 `.sv-card.interactive:hover` 样式，但 HTML 中未找到 `.interactive` 类的使用
- 修复：删除未使用样式或添加对应 HTML

**[C-06] 缺少 `@media print`**
- 问题：无打印样式，用户打印页面时导航栏、状态栏等无关元素也会被打印
- 建议：添加基础打印样式，隐藏导航栏和状态栏

### 3.3 JavaScript 问题

#### P0 - 严重

**[J-01] `startRestoreProgressSSE` 引用未定义变量 `I`**
- 文件：`static/js/app.js:423`
- 问题：`const typeLabel = taskType === 'video' ? (I['history.video'] || '视频') : (I['history.image'] || '图像');` 中 `I` 未在 `app.js` 作用域内定义
- `I` 仅在 `restore.html` 中定义为 `const I = window.__I18N__ || {};`
- 影响：当 SSE 进度推送触发时，`I` 为 `undefined`，`I['history.video']` 会抛出 `TypeError: Cannot read properties of undefined`
- 修复：改为 `const I = window.__I18N__ || {};` 或使用 `t()` 函数

**[J-02] `escapeHtml` 已定义但 innerHTML 中未使用**
- 文件：`static/js/app.js:1372-1376` 定义了 `escapeHtml` 函数
- 问题：`history.html:188-231` 和 `restore.html:423` 的 innerHTML 拼接中均未调用此函数
- 修复：在所有 innerHTML 模板中对用户数据调用 `SeedVR2.escapeHtml()`

#### P1 - 高

**[J-03] `formatUptime` 硬编码中文时间单位**
- 文件：`static/js/app.js:807-811`
- 问题：`天`、`时`、`分`、`秒` 硬编码
- 修复：使用 i18n 翻译键

**[J-04] `formatDuration` 硬编码中文时间单位**
- 文件：`static/js/app.js:815-817`
- 问题：`秒`、`分钟`、`小时` 硬编码
- 修复：使用 i18n 翻译键

**[J-05] `deleteHistoryRecord` 硬编码中文**
- 文件：`static/js/app.js:708-718`
- 问题：`'删除记录'`、`'确定要删除此记录吗？'`、`'记录已删除'`、`'删除失败'` 硬编码
- 修复：使用 `t()` 函数或 `window.__I18N__` 键

**[J-06] `cancelRestoreTask` 硬编码中文**
- 文件：`static/js/app.js:532-535`
- 问题：`'任务已取消'`、`'取消失败'` 硬编码
- 修复：使用 i18n 翻译键

**[J-07] `switchLocale` 硬编码中文**
- 文件：`static/js/app.js:826-830`
- 问题：`'语言已切换'`、`'语言切换失败'` 硬编码
- 修复：使用 i18n 翻译键

**[J-08] `formatTimestamp` 硬编码 locale**
- 文件：`static/js/app.js:786`
- 问题：`'zh-CN'` 硬编码，未使用 `window.__LOCALE__`
- 修复：使用 locale 映射（app.js:1053 已有 `localeMap`，可复用）

**[J-09] HTMX 错误处理硬编码中文**
- 文件：`static/js/app.js:887-897`
- 问题：`'请求失败'`、`'发送请求失败'`、`'网络错误'` 硬编码
- 修复：使用 `t()` 函数

**[J-10] `console.error` 硬编码中文**
- 文件：`static/js/app.js:493, 702`
- 问题：`'SSE 数据解析错误'`、`'加载设置失败'` 硬编码
- 影响：非中文开发者调试不便
- 修复：使用英文或 i18n 键

#### P2 - 中

**[J-11] `setInterval` 无清除机制 — 系统状态页**
- 文件：`templates/system_status.html:284`
- 问题：`setInterval(loadStatus, 10000)` 无对应的 `clearInterval`，页面离开后定时器仍在运行
- 影响：内存泄漏，不必要的网络请求
- 修复：在 `beforeunload` 事件中清除，或使用 `AbortController` 模式

**[J-12] `pollBatchProgress` 仅在 `resetRestore` 时清除**
- 文件：`templates/restore.html:518`
- 问题：`batchInterval` 的 `setInterval` 仅在 `resetRestore()` 中清除，如果用户直接导航离开则不会清除
- 修复：在 `beforeunload` 中清除

**[J-13] `openDirBrowser` 每次重新绑定 onclick**
- 文件：`static/js/app.js:1243-1268`
- 问题：每次调用 `openDirBrowser` 都重新给 `dirBrowserGoBtn`、`dirBrowserOpenExplorerBtn` 等绑定 `onclick`
- 影响：虽然功能正常，但不符合最佳实践
- 修复：使用事件委托或一次性绑定

**[J-14] `loadHistory` 使用原生 `fetch` 而非 `SeedVR2.api.get`**
- 文件：`templates/history.html:160`
- 问题：`history.html` 中 `loadHistory` 使用原生 `fetch`，而其他页面使用 `SeedVR2.api.get`
- 影响：API 风格不一致，且缺少统一的错误处理和 CSRF token 注入
- 修复：改用 `SeedVR2.api.get`

#### P3 - 低

**[J-15] 客户端 i18n 字典与 `window.__I18N__` 双轨并行**
- 问题：`app.js` 中有 `_translations` 字典（用于错误码等），`base.html` 中注入 `window.__I18N__`（用于 UI 文本），两套 i18n 机制并存
- 建议：统一为一套机制

### 3.4 安全问题汇总

| 编号 | 问题 | 严重程度 | 文件 | 行号 |
|------|------|---------|------|------|
| S-01 | innerHTML XSS（历史记录表格） | P0 | history.html | 188-231 |
| S-02 | innerHTML XSS（文件夹扫描结果） | P0 | restore.html | 423 |
| S-03 | CSP `unsafe-inline` | P1 | base.html | 6 |
| S-04 | `escapeHtml` 已定义但未使用 | P0 | app.js | 1372-1376 |
| S-05 | Cookie 安全属性需确认 | P1 | middleware/csrf.py | — |

### 3.5 性能问题汇总

| 编号 | 问题 | 严重程度 | 说明 |
|------|------|---------|------|
| P-01 | Google Fonts Inter 在中国大陆可能不可达 | P1 | 建议提供本地 fallback 或使用国内 CDN 镜像 |
| P-02 | Bootstrap 全量引入（~230KB） | P2 | 大部分样式被自定义 CSS 覆盖，可考虑按需引入 |
| P-03 | CSS/JS 单文件所有页面共享 | P2 | 所有页面加载全部样式和脚本，可按页面拆分 |
| P-04 | 系统状态页每 10s 全量 DOM 刷新 | P2 | 可改为仅更新变化的字段 |
| P-05 | `window.__I18N__` 注入 ~130 个翻译键 | P3 | 每个页面都加载全部翻译，可按页面按需注入 |

### 3.6 国际化完整性

#### 硬编码中文清单（app.js）

| 行号 | 硬编码文本 | 上下文 |
|------|-----------|--------|
| 423 | `'视频'`, `'图像'` | SSE 进度 typeLabel |
| 459 | `'排队中...'` | 状态文本 |
| 460 | `'正在处理'` | 状态文本 |
| 462 | `'处理中...'` | 状态文本 |
| 469 | `'修复完成'` | 任务完成 |
| 472 | `'已完成'` | 状态文本 |
| 478 | `'修复完成'` | Toast 通知 |
| 485 | `'修复失败'` | 任务失败 |
| 487 | `'失败'` | 状态文本 |
| 490 | `'修复失败'` | Toast 通知 |
| 500 | `'连接已断开，请检查网络'` | SSE 错误 |
| 532 | `'任务已取消'` | Toast 通知 |
| 534 | `'取消失败'` | Toast 通知 |
| 708 | `'删除记录'` | 确认对话框标题 |
| 708 | `'确定要删除此记录吗？'` | 确认对话框消息 |
| 711 | `'记录已删除'` | Toast 通知 |
| 716 | `'删除失败'` | Toast 通知 |
| 786 | `'zh-CN'` | formatTimestamp locale |
| 807-810 | `'天'`, `'时'`, `'分'`, `'秒'` | formatUptime |
| 815-817 | `'秒'`, `'分钟'`, `'小时'` | formatDuration |
| 826 | `'语言已切换'` | Toast 通知 |
| 830 | `'语言切换失败'` | Toast 通知 |
| 887 | `'请求失败'` | HTMX 错误 |
| 897 | `'发送请求失败'`, `'网络错误'` | HTMX 错误 |

#### 硬编码中文清单（模板文件）

| 文件 | 行号 | 硬编码文本 |
|------|------|-----------|
| system_status.html | 238-239 | `'CPU 模式'` |

#### i18n 覆盖率评估

- **服务端模板**：i18n 覆盖率约 95%，绝大部分文本通过 `{{ t('key') }}` 渲染
- **客户端 JS**：i18n 覆盖率约 60%，大量 toast 消息、确认对话框文本、时间格式化仍硬编码中文
- **`window.__I18N__` 注入**：约 130 个键，覆盖了主要 UI 文本，但 app.js 中许多函数未使用这些键

---

## 四、综合评估

### 4.1 优势总结

1. **完整的设计系统**：CSS 变量驱动的 Dark/Light 双主题，主题切换无闪烁，视觉一致性好
2. **良好的无障碍基础**：Skip-to-content、ARIA 属性、焦点陷阱、`prefers-reduced-motion` 全面支持
3. **安全意识**：CSRF 保护、SRI integrity、CSP 策略（虽然 `unsafe-inline` 降低了效果）
4. **实时通信**：SSE 事件推送进度更新，用户体验流畅
5. **键盘快捷键**：Alt+1-5 快速导航，提升效率
6. **主题闪烁防护**：head 中内联主题初始化脚本，避免 Dark→Light 闪烁
7. **Skeleton 加载状态**：历史记录表格有骨架屏加载效果
8. **事件监听器清理**：`AbortController` 模式清理事件监听器，避免内存泄漏
9. **HTMX 全局错误联动**：HTMX 请求失败自动触发 Toast 通知
10. **响应式设计**：4 个断点覆盖桌面到移动端，触摸目标满足 44px

### 4.2 问题优先级矩阵

#### P0 - 严重（必须立即修复）

| 编号 | 问题 | 类型 | 影响 |
|------|------|------|------|
| H-01 | innerHTML XSS — 历史记录表格 | 安全 | 恶意文件名可执行任意脚本 |
| H-02 | innerHTML XSS — 文件夹扫描结果 | 安全 | 恶意文件名可执行任意脚本 |
| J-01 | `startRestoreProgressSSE` 引用未定义 `I` | 功能 | SSE 进度推送时会抛出 TypeError |
| S-04 | `escapeHtml` 已定义但未使用 | 安全 | XSS 防护函数形同虚设 |

#### P1 - 高（应尽快修复）

| 编号 | 问题 | 类型 |
|------|------|------|
| H-03 | `lang="zh"` 硬编码 | 无障碍 |
| H-04 | CSP `unsafe-inline` | 安全 |
| H-05 | 系统状态页硬编码中文 | 国际化 |
| J-03~J-10 | app.js 中 8 处硬编码中文 | 国际化 |
| P-01 | Google Fonts 在中国大陆不可达 | 性能 |

#### P2 - 中（建议修复）

| 编号 | 问题 | 类型 |
|------|------|------|
| C-01 | CSS 单文件 3000+ 行 | 架构 |
| C-02 | 硬编码颜色值 | 一致性 |
| C-03 | Light 主题覆盖散落 | 可维护性 |
| H-06 | Alpine.js 仅设置页使用 | 技术栈一致性 |
| H-07 | `oncontextmenu` 内联事件 | 最佳实践 |
| J-11 | `setInterval` 无清除 | 内存泄漏 |
| J-12 | `pollBatchProgress` 清除不完整 | 内存泄漏 |
| J-13 | `openDirBrowser` 重复绑定 | 最佳实践 |
| J-14 | `loadHistory` API 风格不一致 | 一致性 |
| P-02~P-04 | Bootstrap 全量引入等性能问题 | 性能 |

#### P3 - 低（可选修复）

| 编号 | 问题 |
|------|------|
| C-04 | `[x-cloak]` 重复定义 |
| C-05 | `.sv-card.interactive` 未使用 |
| C-06 | 缺少 `@media print` |
| H-08 | 缺少 Apple touch icon |
| J-15 | 双轨 i18n 机制 |
| P-05 | `__I18N__` 全量注入 |

### 4.3 改进建议

#### 建议 1：修复安全问题（P0）

1. 在 `history.html:188-231` 的 `records.map()` 中，对所有用户数据字段（`r.input_file`、`r.output_file`、`r.model_size`、`r.status`）调用 `SeedVR2.escapeHtml()`
2. 在 `restore.html:423` 的 `scannedFiles.map()` 中，对 `f.relative` 调用 `SeedVR2.escapeHtml()`
3. 修复 `app.js:423` 的未定义变量 `I`，改为 `const I = window.__I18N__ || {};`

#### 建议 2：完善国际化（P1）

1. 将 `app.js` 中所有硬编码中文提取为 i18n 键，添加到 `base.html` 的 `window.__I18N__` 注入中
2. 将 `formatTimestamp` 的 `'zh-CN'` 改为基于 `window.__LOCALE__` 的动态 locale
3. 将 `formatUptime` 和 `formatDuration` 的时间单位改为 i18n 键
4. 将 `system_status.html:238-239` 的 `'CPU 模式'` 改为 `I["system.cpu_mode"]`

#### 建议 3：优化 CSS 架构（P2）

1. 将 `style.css` 按功能拆分为多个模块文件
2. 将硬编码颜色值提取为 CSS 变量
3. 将 Light 主题覆盖集中到 `[data-theme="light"]` 选择器块中

#### 建议 4：修复内存泄漏（P2）

1. 在 `system_status.html` 中为 `setInterval(loadStatus, 10000)` 添加 `beforeunload` 清除
2. 在 `restore.html` 中为 `batchInterval` 添加 `beforeunload` 清除

#### 建议 5：统一 API 调用风格（P2）

1. 将 `history.html` 中的原生 `fetch` 改为 `SeedVR2.api.get`
2. 统一所有页面的 API 调用方式

#### 建议 6：字体加载优化（P1）

1. 为 Google Fonts Inter 添加国内 CDN 镜像（如 `fonts.loli.net`）
2. 或将 Inter 字体文件打包到本地 `static/fonts/` 目录

---

## 五、附录

### 附录 A：截图索引

| 截图 | 页面 | 主题 | 视口 |
|------|------|------|------|
| home-dark.png | 首页 | Dark | 桌面 |
| home-light.png | 首页 | Light | 桌面 |
| restore-dark.png | 修复页 | Dark | 桌面 |
| restore-light.png | 修复页 | Light | 桌面 |
| restore-advanced.png | 修复页（高级参数展开） | Dark | 桌面 |
| settings-dark.png | 设置页 | Dark | 桌面 |
| settings-light.png | 设置页 | Light | 桌面 |
| history-dark.png | 历史记录 | Dark | 桌面 |
| history-light.png | 历史记录 | Light | 桌面 |
| system-dark.png | 系统状态 | Dark | 桌面 |
| system-light.png | 系统状态 | Light | 桌面 |
| home-mobile.png | 首页 | Dark | 移动端 (375x812) |
| restore-mobile.png | 修复页 | Dark | 移动端 (375x812) |

### 附录 B：完整问题清单

| 编号 | 优先级 | 类型 | 文件 | 行号 | 问题描述 |
|------|--------|------|------|------|---------|
| H-01 | P0 | 安全 | history.html | 188-231 | innerHTML XSS |
| H-02 | P0 | 安全 | restore.html | 423 | innerHTML XSS |
| H-03 | P1 | 无障碍 | base.html | 2 | lang 属性硬编码 |
| H-04 | P1 | 安全 | base.html | 6 | CSP unsafe-inline |
| H-05 | P1 | 国际化 | system_status.html | 238-239 | 硬编码中文 |
| H-06 | P2 | 架构 | settings.html | 16 | Alpine.js 仅单页使用 |
| H-07 | P2 | 最佳实践 | history_table.html | 3 | 内联事件处理器 |
| H-08 | P3 | 完善 | base.html | 17 | 缺少 Apple touch icon |
| C-01 | P2 | 架构 | style.css | 全文件 | 单文件 3000+ 行 |
| C-02 | P2 | 一致性 | style.css | ~983, ~2784 | 硬编码颜色值 |
| C-03 | P2 | 可维护性 | style.css | ~2749-2785 | Light 主题覆盖散落 |
| C-04 | P3 | 代码质量 | style.css | 383, 2097 | 重复定义 |
| C-05 | P3 | 代码质量 | style.css | — | 未使用样式 |
| C-06 | P3 | 完善 | style.css | — | 缺少 print 样式 |
| J-01 | P0 | 功能 | app.js | 423 | 引用未定义变量 I |
| J-02 | P0 | 安全 | app.js | 1372-1376 | escapeHtml 未使用 |
| J-03 | P1 | 国际化 | app.js | 807-811 | formatUptime 硬编码 |
| J-04 | P1 | 国际化 | app.js | 815-817 | formatDuration 硬编码 |
| J-05 | P1 | 国际化 | app.js | 708-718 | deleteHistoryRecord 硬编码 |
| J-06 | P1 | 国际化 | app.js | 532-535 | cancelRestoreTask 硬编码 |
| J-07 | P1 | 国际化 | app.js | 826-830 | switchLocale 硬编码 |
| J-08 | P1 | 国际化 | app.js | 786 | formatTimestamp 硬编码 locale |
| J-09 | P1 | 国际化 | app.js | 887-897 | HTMX 错误处理硬编码 |
| J-10 | P1 | 国际化 | app.js | 493, 702 | console.error 硬编码 |
| J-11 | P2 | 内存泄漏 | system_status.html | 284 | setInterval 无清除 |
| J-12 | P2 | 内存泄漏 | restore.html | 518 | batchInterval 清除不完整 |
| J-13 | P2 | 最佳实践 | app.js | 1243-1268 | 重复绑定 onclick |
| J-14 | P3 | 一致性 | history.html | 160 | API 风格不一致 |
| J-15 | P3 | 架构 | app.js | — | 双轨 i18n 机制 |
| P-01 | P1 | 性能 | base.html | 156 | Google Fonts 不可达 |
| P-02 | P2 | 性能 | base.html | 151-152 | Bootstrap 全量引入 |
| P-03 | P2 | 性能 | style.css, app.js | — | 单文件共享 |
| P-04 | P2 | 性能 | system_status.html | 284 | 全量 DOM 刷新 |
| P-05 | P3 | 性能 | base.html | 22-147 | __I18N__ 全量注入 |

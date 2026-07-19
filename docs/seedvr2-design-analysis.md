# SeedVR2 Web 应用设计分析报告

---

## 1. 设计风格定位分析

### 1.1 整体风格分类

SeedVR2 的 Web 界面属于 **"开发者工具仪表盘"（Developer Tool Dashboard）** 风格，兼具 **本地 AI 工具** 和 **系统监控面板** 的双重特征。其设计语言可进一步细分为以下子类：

| 维度 | 风格特征 | 典型代表 |
|------|---------|---------|
| **视觉基调** | 深色优先（Dark-first） | VS Code, Linear, Vercel Dashboard |
| **色彩方案** | 紫色强调色体系 | Discord, Twitch, Figma |
| **信息架构** | 卡片式布局（Card-based） | Vercel, Raycast, Linear |
| **设计哲学** | 功能极简主义（Functional Minimalism） | Grafana, Netdata |
| **产品定位** | 本地 AI 工具 UI | Stable Diffusion WebUI, ComfyUI |

### 1.2 与同类产品的差异化

相较于 Stable Diffusion WebUI（AUTOMATIC1111）和 ComfyUI 这类典型的本地 AI 工具界面，SeedVR2 在视觉精致度上有显著提升：

- **AUTOMATIC1111** 采用 Gradio 框架，UI 风格偏"工程师原型"，缺乏统一的设计语言
- **ComfyUI** 采用节点式画布交互，UI 极简但学习曲线陡峭
- **SeedVR2** 则以产品级标准构建界面，拥有完整的设计系统（Design Token、组件规范、响应式断点），在同类本地 AI 工具中属于设计完成度较高的产品

### 1.3 目标用户画像

从设计特征推断，SeedVR2 的目标用户为：
- 有一定技术背景的视频/图像创作者
- 需要本地化部署 AI 推理能力的用户
- 重视效率与可控性的专业用户（大量参数暴露、文件夹路径输入等交互模式印证了这一点）

---

## 2. 视觉设计特征总结

### 2.1 色彩系统

#### 2.1.1 双主题架构

SeedVR2 实现了完整的 Dark / Light 双主题切换，通过 `data-theme` 属性和 CSS 自定义属性驱动：

**Dark 主题（默认）：**
- 基础背景色 `#0f1117`，表面色 `#161822`，提升色 `#1e2030`
- 主色调 `#8b7ef5`（柔和紫），hover 态 `#a89ffa`
- 文字层级：主文字 `#e2e8f0`，次文字 `#94a3b8`，弱文字 `#8899aa`
- 边框采用低透明度白色 `rgba(255, 255, 255, 0.06)`

**Light 主题：**
- 基础背景色 `#f8fafc`，表面色 `#ffffff`，提升色 `#f1f5f9`
- 主色调 `#5b4cd5`（更深沉的紫），hover 态 `#7c6cf1`
- 文字层级：主文字 `#1e293b`，次文字 `#475569`，弱文字 `#546478`
- 边框采用低透明度黑色 `rgba(0, 0, 0, 0.08)`

#### 2.1.2 语义色系统

四个语义色均配有 `-dim` 低透明度变体，用于背景色/徽章底色：

| 语义 | Dark 主题 | Light 主题 | dim 变体 |
|------|----------|-----------|---------|
| 成功 | `#34d399` | `#15803d` | 18% / 12% 透明度 |
| 警告 | `#fbbf24` | `#b45309` | 18% / 12% 透明度 |
| 危险 | `#f87171` | `#dc2626` | 18% / 12% 透明度 |
| 信息 | `#60a5fa` | `#1d4ed8` | 18% / 12% 透明度 |

#### 2.1.3 品牌辅助色

除主色外还定义了两个辅助色：
- `--sv-accent-purple: #a78bfa` / `#7c3aed`（Light）
- `--sv-accent-pink: #f472b6` / `#be185d`（Light）

这两个辅助色与主色组合形成了 Hero 区域的渐变效果：`linear-gradient(135deg, primary, accent-purple, accent-pink)`，用于首页标题的文字渐变和品牌图标背景。

#### 2.1.4 色彩评价

**优点：**
- 双主题色彩映射关系清晰，Dark/Light 不是简单的反色，而是针对各自背景做了独立的对比度优化
- 语义色系统完整，dim 变体设计避免了纯色背景的刺眼感
- 主色选择（紫色系）在开发者工具领域有较高的品牌辨识度

**不足：**
- Dark 主题下语义色饱和度偏高（如 `#34d399` 绿色），长时间使用可能造成视觉疲劳
- 缺少中性色梯度（如 gray-50 到 gray-900 的完整色阶），仅有 3 级背景色和 3 级文字色

### 2.2 排版系统

#### 2.2.1 字体栈

```css
font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", sans-serif;
```

- 主字体：Inter（Google Fonts，400-800 五档字重）
- 系统回退：Apple 系统字体、Segoe UI（Windows）、Roboto（Android）
- 中文字体：Noto Sans SC
- 备用 CDN：fonts.googleapis.com + fonts.loli.net（国内镜像）

#### 2.2.2 字重层级

| 用途 | 字号 | 字重 | letter-spacing |
|------|------|------|--------------|
| Hero 标题 | 2.25rem | 800 | -0.03em |
| 页面标题 | 1.6rem | 700 | -0.02em |
| 区块标题 | 1.2rem | 700 | -- |
| 卡片标题 | 0.95rem | 600 | -- |
| 参数区段标题 | 0.78rem | 600 | 0.05em, uppercase |
| 正文 | 0.85rem | 400 | -- |
| 辅助文字 | 0.8rem | 500 | -- |
| 弱文字/标签 | 0.75rem | 500-600 | 0.02em-0.05em |

#### 2.2.3 排版评价

**优点：**
- 字重层级分明，从 400 到 800 覆盖了足够的对比度范围
- Hero 标题使用负 letter-spacing（-0.03em），营造出现代感的紧凑视觉
- 参数区段标题使用 uppercase + letter-spacing，形成了与内容文字的明确区分

**不足：**
- 行高仅在 body 上设置了 `1.6`，缺少针对不同字号/场景的行高变量
- 缺少标题与正文之间的间距规范（目前依赖 margin-bottom 的硬编码值）
- 中文字体 Noto Sans SC 与 Inter 的字重匹配可能不够精确（Noto Sans SC 的 700/800 字重在视觉上可能偏细）

### 2.3 间距与布局系统

#### 2.3.1 间距令牌

采用 4px 基数的间距系统，定义了 9 级间距变量：

| Token | 值 | 典型用途 |
|-------|-----|---------|
| `--sv-space-1` | 4px | 微间距 |
| `--sv-space-1-5` | 6px | 紧凑间距 |
| `--sv-space-2` | 8px | 小间距 |
| `--sv-space-2-5` | 10px | -- |
| `--sv-space-3` | 12px | 表单元素间距 |
| `--sv-space-4` | 16px | 卡片内边距（小） |
| `--sv-space-5` | 20px | 卡片内边距（标准） |
| `--sv-space-6` | 24px | 区块间距 |
| `--sv-space-7` | 32px | 页面级间距 |
| `--sv-space-8` | 40px | 上传区域内边距 |
| `--sv-space-9` | 48px | Hero 区域上下间距 |

#### 2.3.2 圆角系统

| Token | 值 | 用途 |
|-------|-----|------|
| `--sv-radius-sm` | 6px | 按钮、输入框、标签 |
| `--sv-radius` | 10px | 卡片（概览项）、对比容器 |
| `--sv-radius-lg` | 14px | 主卡片、上传区域 |
| `--sv-radius-xl` | 20px | -- |

#### 2.3.3 布局常量

| Token | 值 | 用途 |
|-------|-----|------|
| `--sv-navbar-height` | 56px | 顶部导航栏高度 |
| `--sv-statusbar-height` | 32px | 底部状态栏高度 |
| `--sv-sidebar-width` | 260px | 侧边栏宽度（定义但未使用） |
| 内容最大宽度 | 1440px | 首页内容区域 |

#### 2.3.4 页面布局模式

| 页面 | 布局方式 | 关键尺寸 |
|------|---------|---------|
| 首页 | 居中单列（Hero + 卡片网格 + 概览网格） | 卡片 `minmax(280px, 1fr)` auto-fit |
| 修复页 | 双栏网格（左：上传+结果，右：参数面板） | 右栏 `minmax(360px, 480px)`，参数面板 sticky |
| 设置页 | 左侧标签导航 + 右侧内容 | 左栏 220px，标签导航 sticky |
| 历史页 | 全宽卡片（工具栏 + 数据表格） | 表格支持横向滚动 |
| 系统状态 | 自适应卡片网格 | `minmax(320px, 1fr)` auto-fit |

### 2.4 组件设计

#### 2.4.1 卡片组件

卡片是整个应用的核心容器组件，设计规范：

- 背景：`--sv-bg-surface`
- 边框：`1px solid var(--sv-border)`
- 圆角：`--sv-radius-lg`（14px）
- 阴影：`--sv-shadow-sm`（`0 1px 3px rgba(0,0,0,0.3)` Dark / `0.08` Light）
- 内边距：header `16px 20px`，body `20px`，footer `14px 20px`
- 可交互卡片 hover 时 `translateY(-1px)` + 边框高亮 + 阴影提升
- 首页快捷卡片 hover 时有 `--sv-shadow-glow`（主色辉光阴影）

#### 2.4.2 按钮组件

按钮系统包含以下变体：

| 变体 | 背景 | 边框 | 文字 | Hover 效果 |
|------|------|------|------|-----------|
| Primary | `--sv-primary` | `--sv-primary` | Dark 主题: `#0f1117` / Light: `#fff` | 辉光阴影 + translateY(-1px) |
| Secondary | `--sv-bg-overlay` | `--sv-border` | `--sv-text-primary` | 背景加深 |
| Success | `--sv-btn-success-bg` | 同左 | `--sv-btn-success-text` | brightness(1.1) |
| Danger | `--sv-btn-danger-bg` | 同左 | `--sv-btn-danger-text` | brightness(1.1) |
| Outline | transparent | `--sv-border` | `--sv-text-secondary` | 边框+背景高亮 |

按钮尺寸规范：
- 默认：`padding: 8px 18px`，`min-height: 44px`
- Small：`padding: 4.8px 12px`，`min-width: 44px`
- Large：`padding: 10px 24px`
- Icon：`44px x 44px` 正方形

Active 态：`scale(0.97)` + `opacity: 0.9`，提供明确的按压反馈。

#### 2.4.3 表单组件

- 输入框：背景 `--sv-bg-elevated`，圆角 `--sv-radius-sm`，focus 时主色边框 + `0 0 0 3px` 主色 dim 光晕
- 下拉框：自定义箭头图标（SVG data URI），option 元素适配深色背景
- 范围滑块：自定义 thumb 样式（16px 圆形，主色），hover 时 `scale(1.1)`
- 开关：40x22px 轨道，16px 圆形 thumb，左白右绿的过渡动画

#### 2.4.4 导航组件

- 顶部导航栏：固定定位，`backdrop-filter: blur(12px)` 毛玻璃效果
- 导航链接：图标 + 文字 + 快捷键提示（Alt+1~5），active 态使用主色 dim 背景
- 品牌标识：28x28px 渐变背景方块 + "S2" 文字，带主色辉光阴影
- 移动端：汉堡菜单 + 下拉导航面板 + 遮罩层

#### 2.4.5 状态指示组件

- 状态圆点（Status Dot）：8px 圆形，4 种状态（online/offline/warning/error），warning 和 error 带脉冲动画
- 状态徽章（Badge）：pill 形状，6 种变体（pending/processing/completed/failed/primary/secondary）
- 进度条：8px 高度，带渐变填充、条纹动画（shimmer）、完成时的弹跳+辉光动画

#### 2.4.6 特殊组件

- **前后对比滑块**：3px 分割线 + 36px 圆形拖拽手柄，支持触摸和鼠标拖拽
- **上传区域**：虚线边框，支持拖拽高亮（`scale(1.01)` + 实线边框），文件就绪后切换为绿色实线
- **Toast 通知**：右侧滑入/滑出动画，左侧彩色边框标识类型
- **骨架屏**：为表格设计了完整的骨架屏占位状态
- **目录浏览器**：模态框内的文件树浏览组件
- **右键菜单**：历史记录行的上下文菜单
- **Workflow Node**：模拟 ComfyUI 工作流节点的可折叠组件

### 2.5 动效系统

#### 2.5.1 缓动函数

| Token | 值 | 用途 |
|-------|-----|------|
| `--sv-easing-standard` | `cubic-bezier(0.4, 0, 0.2, 1)` | 通用过渡 |
| `--sv-easing-decelerate` | `cubic-bezier(0, 0, 0.2, 1)` | 进入动画 |
| `--sv-easing-accelerate` | `cubic-bezier(0.4, 0, 1, 1)` | 退出动画 |
| `--sv-easing-bounce` | `cubic-bezier(0.34, 1.56, 0.64, 1)` | 弹性效果 |

#### 2.5.2 过渡时长

- 标准过渡：`0.2s`
- 慢速过渡：`0.35s`
- 主题切换：`0.3s`（背景色和文字色）

#### 2.5.3 关键帧动画

| 动画 | 用途 | 特征 |
|------|------|------|
| `spin` | 加载旋转器 | 0.7s 线性循环 |
| `pulse` | 状态指示 | 2s 淡入淡出循环 |
| `toastIn/toastOut` | 通知弹出 | 0.3s 右侧滑入/滑出 |
| `progressShimmer` | 进度条条纹 | 1.5s 线性无限移动 |
| `progressComplete` | 进度完成 | 0.6s scaleX 弹跳 |
| `progressGlow` | 完成辉光 | 1.5s 单次辉光脉冲 |
| `fadeIn` | 淡入 | 0.3s 上移 + 透明度 |
| `emptyFloat` | 空状态图标 | 1.5s 浮动动画 |

### 2.6 响应式设计

#### 2.6.1 断点体系

| 断点 | 触发条件 | 主要变化 |
|------|---------|---------|
| 992px | 平板横屏 | 修复页双栏变单栏，设置页标签变横向滚动 |
| 768px | 平板竖屏 | 导航变汉堡菜单，Hero 标题缩小，参数面板默认折叠 |
| 576px | 手机 | 概览网格变单列，快捷卡片变单列，工具栏变纵向堆叠 |

#### 2.6.2 移动端适配策略

- 导航：绝对定位下拉面板 + 半透明遮罩层，带 translateY + opacity 过渡
- 参数面板：默认折叠，标题可点击展开（通过 CSS `::after` 伪元素添加展开箭头）
- 触摸目标：所有按钮 `min-height: 44px`，图标按钮 `44x44px`
- 内容区：padding 从 `24px 32px` 缩减为 `16px`

### 2.7 无障碍设计

- **Skip-to-content 链接**：隐藏在视口外，focus 时显示在左上角
- **ARIA 属性**：导航使用 `role="tablist/tab/tabpanel"`，模态框使用 `aria-label`，进度条使用 `role="progressbar"` + `aria-valuenow`
- **Focus 样式**：开关组件有 `focus-visible` 样式（2px 主色 outline + 2px offset）
- **语义 HTML**：使用 `<nav>`, `<main>`, `<footer>` 等语义标签
- **键盘快捷键**：Alt+1~5 快速导航到各页面

---

## 3. 设计优势与不足

### 3.1 设计优势

#### (1) 完整的 Design Token 系统

这是 SeedVR2 最突出的设计优势。整个 UI 通过 `--sv-*` 前缀的 CSS 自定义属性驱动，涵盖了颜色、间距、圆角、阴影、缓动函数、布局尺寸等维度。这意味着：
- 主题切换仅需修改 `data-theme` 属性，无需覆盖具体样式
- 全局风格调整可通过修改 Token 值实现，而非逐个修改组件
- 为未来的设计系统化奠定了坚实基础

#### (2) 双主题的一致性

Dark/Light 主题不是简单的颜色反转，而是各自独立优化的色彩方案。例如 Dark 主题的语义色使用了更高饱和度的亮色（`#34d399`），而 Light 主题使用了更深沉的色调（`#15803d`），确保在各自背景上都有足够的对比度和舒适度。

#### (3) 信息层级清晰

通过字重（400-800）、字号（0.75rem-2.25rem）、颜色（3 级文字色）、间距（9 级间距令牌）四个维度的组合，建立了清晰的信息层级。用户可以快速区分 Hero 标题、页面标题、区块标题、卡片标题、正文和辅助文字。

#### (4) 交互反馈丰富

从微观到宏观，SeedVR2 提供了多层次的交互反馈：
- **微观**：按钮 hover 辉光 + translateY，active scale(0.97)，输入框 focus 光晕
- **中观**：卡片 hover 边框高亮 + 阴影提升，Toast 滑入/滑出，进度条 shimmer 动画
- **宏观**：页面级 HTMX 加载指示器（顶部 2px 进度条），SSE 实时进度推送

#### (5) 功能导向的布局设计

修复页的双栏布局（左：输入与结果，右：参数面板 sticky）充分考虑了用户的核心工作流——用户在左侧上传文件、查看进度和结果，同时可以在右侧调整参数而无需滚动。这种布局在视频/图像处理工具中非常实用。

#### (6) 骨架屏加载状态

历史记录表格和系统状态页面都实现了骨架屏（Skeleton Loading）占位，避免了内容加载时的布局跳动和空白闪烁，提升了感知性能。

#### (7) 前后对比组件

修复结果页内置了 Before/After 对比滑块，这是图像/视频修复工具的核心交互组件，实现质量较高（支持拖拽手柄、标签显示、触摸操作）。

### 3.2 设计不足

#### (1) 首页布局不对称

首页的快捷卡片使用 `grid-template-columns: repeat(auto-fit, minmax(280px, 1fr))`，在宽屏下会呈现 3 列布局，但只有 3 张卡片，导致第 4 个位置为空。更优的方案可以是：
- 使用 3 列固定网格 + `justify-content: center` 居中
- 或增加第 4 张卡片（如"设置"快捷入口）

#### (2) 缺少品牌视觉资产

当前的品牌标识仅为一个 28x28px 的 CSS 渐变方块内嵌 "S2" 文字，缺少：
- SVG Logo 文件（当前 favicon 使用内联 data URI）
- 品牌插画或图形元素
- Hero 区域的视觉焦点（当前仅有渐变文字标题 + 纯文字副标题）

作为 AI 视频/图像修复工具，Hero 区域可以加入修复效果的视觉展示（如 Before/After 缩略图或动态预览）。

#### (3) 参数面板信息密度过高

修复页的参数面板暴露了大量技术参数（BlockSwap、Tiled VAE、注意力模式等），对于非专业用户而言信息过载。虽然采用了可折叠的 Workflow Node 设计，但默认展开状态下参数数量仍然很多。建议：
- 提供"简单模式"和"高级模式"的切换
- 简单模式下仅暴露最常用的 3-5 个参数（分辨率、模型大小、颜色校正）
- 高级模式下展示完整参数列表

#### (4) 缺少空状态引导

虽然定义了 `.sv-empty-state` 样式，但首页的系统概览网格在数据加载前仅显示 "--" 占位文字，缺少引导用户进行首次操作的空状态设计（如"点击开始你的第一次修复"）。

#### (5) 表格在移动端的体验

历史记录表格在移动端仅通过 `overflow-x: auto` 实现横向滚动，缺少移动端友好的替代方案（如卡片式列表视图）。

#### (6) 动画可访问性

虽然定义了 `prefers-reduced-motion` 的支持意图（通过 CSS 变量系统可以方便地禁用动画），但在实际 CSS 中未发现 `@media (prefers-reduced-motion: reduce)` 的规则，意味着对运动敏感的用户无法关闭动画。

#### (7) 颜色对比度

Dark 主题下部分弱文字色（`#8899aa` 在 `#0f1117` 背景上）的对比度约为 4.8:1，勉强满足 WCAG AA 标准（4.5:1），但在小字号（0.75rem）下可能不够清晰。Light 主题下的弱文字色（`#546478` 在 `#f8fafc` 背景上）对比度约为 5.2:1，相对较好。

#### (8) `--sv-sidebar-width` 未使用

CSS 中定义了 `--sv-sidebar-width: 260px`，但实际布局并未使用侧边栏（导航在顶部），这个 Token 属于冗余定义。

---

## 4. 推荐学习参考网站

### 4.1 直接设计参考（同类产品）

#### 1. Vercel Dashboard
- **网址**：https://vercel.com/dashboard
- **推荐理由**：卡片式信息架构、深色主题、紫色强调色的典范。其项目列表、部署详情页的布局模式与 SeedVR2 的系统状态页和修复结果页有高度相似性。特别值得学习其卡片 hover 效果和状态徽章的设计。
- **可借鉴点**：卡片阴影层级、状态指示器设计、数据表格的交互模式

#### 2. Linear
- **网址**：https://linear.app
- **推荐理由**：被誉为"最美项目管理工具"，其深色主题的配色方案（深灰背景 + 紫色强调色）与 SeedVR2 高度一致。Linear 在信息密度与视觉舒适度之间取得了极佳的平衡。
- **可借鉴点**：键盘快捷键系统、列表/表格的交互细节、侧边栏导航的动画过渡

#### 3. Raycast
- **网址**：https://raycast.com
- **推荐理由**：开发者效率工具，拥有非常精致的深色 UI。其设置页面的布局（左侧标签导航 + 右侧内容区）与 SeedVR2 的设置页几乎一致。Raycast 在组件的微交互（开关、下拉菜单、滑块）上做得非常出色。
- **可借鉴点**：设置页面的交互模式、开关组件的设计、命令面板的搜索交互

#### 4. Resend
- **网址**：https://resend.com
- **推荐理由**：Email API 服务，其 Dashboard 的卡片布局和色彩方案与 SeedVR2 类似。Resend 的首页 Hero 区域设计简洁有力，是"功能极简主义"风格的好参考。
- **可借鉴点**：Hero 区域的视觉设计、空状态引导、API 密钥管理的 UI 模式

### 4.2 设计系统参考

#### 5. Radix Themes
- **网址**：https://www.radix-ui.com/themes
- **推荐理由**：Radix Themes 提供了完整的 Dark/Light 主题系统实现，其 CSS 变量的组织方式（颜色、间距、半径、字体）与 SeedVR2 的 Token 系统非常相似。值得学习其主题切换的实现机制和语义色系统。
- **可借鉴点**：主题 Token 的组织架构、组件级别的主题适配、响应式断点策略

#### 6. Shadcn/ui
- **网址**：https://ui.shadcn.com
- **推荐理由**：基于 Radix 的组件库，其设计哲学（功能优先、可定制、无样式锁定）与 SeedVR2 的自定义组件系统一致。Shadcn/ui 的组件代码可以直接作为参考，帮助 SeedVR2 优化现有组件的实现。
- **可借鉴点**：组件 API 设计、表单组件的交互细节、Toast/Dialog/Command 等复合组件的实现

#### 7. Vercel Geist Font
- **网址**：https://vercel.com/font/geist
- **推荐理由**：Vercel 出品的字体系统，专为开发者工具设计。Geist 字体在可读性、字重分布和字符宽度上比 Inter 更适合代码密集型界面。如果 SeedVR2 希望进一步提升排版品质，可以考虑从 Inter 切换到 Geist。
- **可借鉴点**：字体选择策略、开发者工具的排版最佳实践

### 4.3 AI 工具 UI 参考

#### 8. Stable Diffusion WebUI (AUTOMATIC1111)
- **网址**：https://github.com/AUTOMATIC1111/stable-diffusion-webui
- **推荐理由**：最流行的本地 AI 图像生成工具，其参数面板的组织方式（标签页分组 + 可折叠区块）值得参考。SeedVR2 的 Workflow Node 设计已经是对这类参数面板的改良版本。
- **可借鉴点**：参数分组策略、批量处理的工作流设计、用户预设（Preset）的保存/加载机制

#### 9. ComfyUI
- **网址**：https://github.com/comfyanonymous/ComfyUI
- **推荐理由**：节点式 AI 工具界面，其 Workflow Node 的概念已被 SeedVR2 借鉴（`.sv-workflow-node` 组件）。ComfyUI 的节点连接、参数折叠、拖拽交互等设计值得深入研究。
- **可借鉴点**：节点式参数面板的交互模式、工作流可视化、节点状态指示

#### 10. Pinokio
- **网址**：https://pinokio.computer
- **推荐理由**：AI 应用浏览器，拥有非常精致的安装/管理界面。其卡片式应用列表、进度指示器和状态管理 UI 与 SeedVR2 的历史记录页和任务管理有相似之处。
- **可借鉴点**：安装/下载进度的 UI 设计、应用卡片的信息展示、状态切换的动画

### 4.4 仪表盘与数据可视化参考

#### 11. Grafana
- **网址**：https://grafana.com
- **推荐理由**：开源系统监控仪表盘，其系统状态页面的设计（GPU 信息、内存使用、运行时间等指标的展示方式）与 SeedVR2 的系统状态页高度相关。Grafana 的仪表盘面板（Panel）组件和阈值颜色映射值得学习。
- **可借鉴点**：系统指标的可视化方式、仪表盘面板的布局、告警阈值颜色

#### 12. Netdata
- **网址**：https://netdata.cloud
- **推荐理由**：实时系统监控工具，其 GPU/内存/CPU 的实时图表展示方式可以为 SeedVR2 的系统状态页提供参考。Netdata 在数据密度和可读性之间取得了很好的平衡。
- **可借鉴点**：实时数据刷新策略、紧凑型指标展示、图表的颜色编码

---

## 5. 设计改进方向建议

### 5.1 短期优化（低成本高收益）

#### (1) 修复首页卡片网格不对称

将快捷卡片的网格改为 3 列固定布局并居中：

```css
.sv-quick-cards {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    max-width: 960px;
    margin-left: auto;
    margin-right: auto;
}
```

或增加第 4 张卡片（如"设置"快捷入口），使 2x2 网格更完整。

#### (2) 添加 prefers-reduced-motion 支持

```css
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
    }
}
```

#### (3) 优化弱文字对比度

将 Dark 主题的弱文字色从 `#8899aa` 提升到 `#94a3b8`（与次文字色统一），或引入第 4 级文字色用于真正需要弱化的场景。

#### (4) 清理冗余 Token

移除未使用的 `--sv-sidebar-width`，或将其重命名为更通用的布局 Token。

### 5.2 中期改进（中等成本中等收益）

#### (1) 设计参数面板的"简单/高级"模式

为修复页参数面板增加模式切换：
- **简单模式**：仅暴露模型大小、分辨率、颜色校正 3 个核心参数
- **高级模式**：展示完整的 Workflow Node 参数列表

这可以通过 Alpine.js 的 `x-show` 指令实现，无需后端改动。

#### (2) 增强 Hero 区域的视觉表现

- 添加一个 Before/After 的动态预览图或短视频作为 Hero 背景
- 或使用抽象的渐变动画/粒子效果作为视觉焦点
- 考虑使用 AI 生成的修复效果对比图作为视觉锚点

#### (3) 移动端表格优化

为历史记录表格增加移动端的卡片式替代视图：

```html
<!-- 移动端卡片视图 -->
<div class="sv-history-card sv-md-visible">
    <div class="card-header">
        <span class="sv-badge">...</span>
        <span class="time">...</span>
    </div>
    <div class="card-body">
        <div class="filename">...</div>
        <div class="meta">模型: 3B | 耗时: 45s</div>
    </div>
</div>
```

#### (4) 引入 SVG Logo

设计一个正式的 SVG Logo，替代当前的 CSS 渐变方块。Logo 应包含：
- 简洁的图形符号（如"种子发芽"的抽象图形，呼应 "Seed" 品牌名）
- "SeedVR2" 文字标识
- 适配 favicon、导航栏、空状态等多种使用场景

### 5.3 长期规划（高成本高收益）

#### (1) 构建完整的设计系统文档

将现有的 CSS Token 和组件规范整理为设计系统文档，包括：
- Token 速查表（颜色、间距、圆角、阴影、字体）
- 组件使用指南（卡片、按钮、表单、表格等）
- 页面布局模板
- 交互规范（hover/focus/active/disabled 状态）
- 响应式适配指南

#### (2) 引入组件化前端框架

当前使用 Jinja2 模板 + 原生 JS 的方式在组件复用性上有限制。长期来看，可以考虑：
- 使用 Web Components 封装核心 UI 组件（与 Jinja2 兼容）
- 或引入轻量级前端框架（如 Preact + HTMX 的增强模式）

#### (3) 增加用户引导系统

为新用户设计首次使用引导（Onboarding）：
- 首次访问时的功能介绍（Tooltip Tour）
- 空状态下的操作引导（如"上传你的第一个视频开始修复"）
- 参数面板的上下文帮助（每个参数的 tooltip 解释）

#### (4) 数据可视化增强

系统状态页的指标展示可以从纯文字升级为可视化图表：
- GPU 显存使用率：环形进度图
- 推理速度趋势：折线图（记录历史推理任务的耗时）
- 模型加载/卸载时间线

#### (5) 主题自定义扩展

在现有 Dark/Light 双主题基础上，可以考虑：
- 允许用户自定义强调色（从预设的几种颜色中选择）
- 提供紧凑/舒适两种密度模式
- 支持字体大小缩放（小/中/大）

---

## 附录：技术栈概览

| 层级 | 技术 | 版本 |
|------|------|------|
| 后端框架 | FastAPI | -- |
| 模板引擎 | Jinja2 | -- |
| CSS 框架 | Bootstrap 5 | 5.3.3 |
| 图标库 | Bootstrap Icons | 1.11.3 |
| 字体 | Inter (Google Fonts) | 400/500/600/700/800 |
| 前端交互 | HTMX | 2.0.4 |
| 响应式增强 | Alpine.js（设置页标签） | -- |
| 实时通信 | SSE（Server-Sent Events） | -- |
| 国际化 | 自建 i18n 系统（YAML + Jinja2） | -- |
| 安全 | CSP + CSRF 中间件 | -- |

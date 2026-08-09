# SeedVR2 Design System

> 本文档与实际实现（`bin/integrated_app/static/css/style.css`）保持一致，最后核对：2026-08-08。
> 主题机制：`<html data-theme="dark|light">`（默认 dark），`localStorage('sv-theme')` 持久化。
> 设计规范：Warm Print 暖暮（深色）/ 暖纸（浅色），苔绿主色 + 陶土/金/珊瑚辅助。

## 1. Color Tokens

### 1.1 Primary（苔绿主色）

| Token | Dark | Light | Usage |
|-------|------|-------|-------|
| `--sv-primary` | `#94b88f` | `#5e7d5a` | 主按钮、导航激活、链接、focus ring |
| `--sv-primary-hover` | `#a8c9a3` | `#506c4d` | 主按钮 hover |
| `--sv-primary-active` | `#b8d4b3` | `#435a40` | 主按钮 active |
| `--sv-primary-300` | `#a5c29f` | `#9fbb9a` | 浅绿底/选中底（soft） |
| `--sv-primary-600` | `#7aa375` | `#506c4d` | 深绿强调 |
| `--sv-primary-700` | `#5e7d5a` | `#435a40` | 文字绿、可点击文字（对比达标） |
| `--sv-primary-900` | `#334030` | `#2b3828` | 最深绿 |
| `--sv-primary-dim` | `rgba(148,184,143,.18)` | `rgba(94,125,90,.08)` | 徽标/标签底色 |
| `--sv-primary-glow` | `rgba(148,184,143,.32)` | `rgba(94,125,90,.15)` | 辉光/选中 |

> 品牌收敛规则：全站只使用 `--sv-primary` 家族，禁止在模板/JS 中写死其它绿色（历史遗留 `#4ade80`/`#a3c9a8`/`#6b8e6d` 已废弃）。

### 1.2 Semantic（语义色）

| Token | Dark | Light | Usage |
|-------|------|-------|-------|
| `--sv-success` | `#94b88f` | `#4f7049` | 已完成、在线 |
| `--sv-warning` | `#c9a55a` | `#a6823a` | 内存偏高、处理中、警示 |
| `--sv-danger` | `#c96a5a` | `#b85a4a` | 失败、删除 |
| `--sv-info` | `#6e90ac` | `#52707c` | 信息提示 |
| `--sv-success/warning/danger/info-soft` | 各色 10-12% alpha | 同 | 徽标底色 |

> 语义状态必须「圆点 + 文字」双通道表达，不得只靠颜色。

### 1.3 Accent（品牌辅助色，Warm Print）

| Token | Dark | Light | Usage |
|-------|------|-------|-------|
| `--sv-accent-moss` | `#82a87e` | `#5e7d5a` | 次要强调 |
| `--sv-accent-terracotta` | `#c48870` | `#905040` | 陶土 |
| `--sv-accent-coral` | `#c99580` | `#a06050` | 珊瑚 |
| `--sv-accent-gold` | `#c9a878` | `#967a4d` | 金（hero kicker 可用） |

### 1.4 Neutrals（中性色）

| Token | Dark | Light | Usage |
|-------|------|-------|-------|
| `--sv-bg-base` | `#1e1c19` | `#faf7f2` | 页面底（暖灰/暖纸，非纯黑纯白） |
| `--sv-bg-surface` / `--sv-surface-1` | `#272421` | `#ffffff` | 卡片面 |
| `--sv-surface-2` | `#302d29` | `#f0ebe3` | 嵌入控件面 |
| `--sv-border` | `rgba(234,230,225,.18)` | `rgba(44,36,32,.14)` | 默认描边 |
| `--sv-border-hover` | `rgba(234,230,225,.26)` | `rgba(44,36,32,.22)` | hover 描边 |
| `--sv-border-focus` | `var(--sv-primary)` | 同 | focus ring |
| `--sv-text-primary` | `#e8e4de` | `#2c2420` | 正文 |
| `--sv-text-secondary` | `#c8c1b9` | `#4a3f38` | 次要 |
| `--sv-text-muted` | `#9e958c` | `#7a6f66` | 弱化 |
| `--sv-text-placeholder` | `#756d66` | `#9a918a` | 占位 |

## 2. Shape / Type / Space Tokens

| Token | 值 | 说明 |
|-------|-----|------|
| `--sv-radius-sm` | `6px` | 控件、徽标、输入框 |
| `--sv-radius` | `8px` | 卡片 |
| `--sv-radius-lg` / `--sv-radius-xl` | `12px` / `16px` | 大容器/弹层 |
| `--sv-space-1..9` | `4/6/8/10/12/16/20/24/32/40/48px` | 8px 基数间距尺 |
| `--sv-font-display` | `Instrument Serif, Georgia, ...` | hero 衬线标题 |
| `--sv-font-body` | `DM Sans, ...` | 正文/UI |
| `--sv-font-mono` | `SF Mono, Cascadia Code, ...` | 代码/数值 |

## 3. Component Conventions

- 主按钮 `.sv-btn-primary`：`--sv-primary` 底 + `--sv-btn-primary-text`（dark `#1a1917` / light `#ffffff`）。
- 徽标 `.sv-badge-*`：语义色 soft 底 + 主色文字 + 圆点（`--sv-success/warning/danger`）。
- 卡片 `.sv-card`：`--sv-bg-surface` + `--sv-border` + `--sv-radius`，阴影用 `--sv-shadow-*`（暗色轻、浅色稍重）。
- 导航激活项：`--sv-primary` 文字/描边；毛玻璃用 `--sv-glass-*`。
- 对比滑块/预览：`--sv-compare-*` 系列（毛玻璃 + 苔绿点缀线）。
- 强调克制：每屏主色可见 ≤2 处（导航激活 + 主 CTA 或一处数据强调），其余用中性色。
- 新增颜色必须先在 token 段定义并双主题同步，禁止页面内直接写 hex（除 `#fff`/`#000` 极端兜底）。

## 4. A11y Notes

- 正文文字对底色 ≥4.5:1；大号文字 ≥3:1；组件与相邻面 ≥3:1（Warm Print 色板已按此校准）。
- 深色主题使用暖灰 `#1e1c19` 而非纯黑；浅色使用 `#faf7f2` 而非纯白。
- 交互元素必须有 `:focus-visible` 可见焦点态（`--sv-border-focus`）。

## 5. i18n & 静态资源

- 界面文案经 `t('key')`（模板）与 `window.__I18N__`（JS）获取；新增文案同步 `locales/{zh,zh-TW,en,ja,fr}.yaml` + `base.html` 注入块。
- CSS/JS 经 `VersionedStaticFiles` 以 `no-cache, must-revalidate` 提供，改动无需清缓存；`?v=` 版本号在 `base.html` 集中维护。

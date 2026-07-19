# WCAG 2.1 AA 对比度合规报告

**测试时间**: 2026/6/20 00:27:43
**测试工具**: Playwright + Node.js
**测试页面**: 6 个
**测试主题**: Dark / Light

---

## 1. 总体合规率

| 指标 | 数值 |
|------|------|
| 总测试元素数 | 410 |
| 合规数 | 404 |
| 不合规数 | 6 |
| **总体合规率** | **98.5%** |

### 按主题统计

| 主题 | 测试数 | 合规 | 不合规 | 合规率 |
|------|--------|------|--------|--------|
| DARK | 205 | 205 | 0 | 100.0% |
| LIGHT | 205 | 199 | 6 | 97.1% |

### 按页面统计

| 页面 | Dark 合规率 | Light 合规率 |
|------|------------|-------------|
| 首页 | 100.0% | 100.0% |
| 视频修复 | 100.0% | 97.7% |
| 图像修复 | 100.0% | 97.7% |
| 设置 | 100.0% | 100.0% |
| 历史记录 | 100.0% | 91.2% |
| 系统状态 | 100.0% | 96.6% |

---

## 2. 不合规项汇总

共发现 **1** 类不合规项（去重后）：

### LIGHT 主题

| 页面 | 类别 | 选择器 | 文字颜色 | 背景颜色 | 对比度 | 阈值 | 字号 | 字重 |
|------|------|--------|----------|----------|--------|------|------|------|
| 视频修复 | 徽章 completed | `.sv-badge-completed` | rgb(21,128,61) | rgb(214,232,223) | 3.93:1 | 4.5:1 | 11.52px | 600 |

---

## 3. 详细测试结果

### DARK 主题

#### 首页

| 类别 | 选择器 | 文字颜色 | 背景颜色 | 对比度 | 阈值 | 合规 | 字号 | 字重 |
|------|--------|----------|----------|--------|------|------|------|------|
| 页面标题 h1 | `.sv-page-header h1, .sv-hero h1`[0] | rgb(226,232,240) | rgb(15,17,23) | 15.31:1 | 3:1 | ✅ | 36px | 800 |
| 页面标题 h1 | `.sv-page-header h1, .sv-hero h1`[1] | rgb(226,232,240) | rgb(15,17,23) | 15.31:1 | 3:1 | ✅ | 25.6px | 700 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[0] | rgb(148,163,184) | rgb(15,17,23) | 7.36:1 | 4.5:1 | ✅ | 16px | 400 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[1] | rgb(226,232,240) | rgb(22,24,34) | 14.34:1 | 4.5:1 | ✅ | 16px | 600 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[2] | rgb(226,232,240) | rgb(22,24,34) | 14.34:1 | 4.5:1 | ✅ | 16px | 600 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[0] | rgb(148,163,184) | rgb(30,32,48) | 6.28:1 | 4.5:1 | ✅ | 12px | 400 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[1] | rgb(148,163,184) | rgb(30,32,48) | 6.28:1 | 4.5:1 | ✅ | 12px | 400 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[2] | rgb(148,163,184) | rgb(30,32,48) | 6.28:1 | 4.5:1 | ✅ | 12px | 400 |
| 导航链接 | `.sv-nav-link`[0] | rgb(139,126,245) | rgb(37,37,63) | 4.52:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[1] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[2] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接(活跃) | `.sv-nav-link.active`[0] | rgb(139,126,245) | rgb(37,37,63) | 4.52:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 primary | `.sv-btn-primary`[0] | rgb(15,17,23) | rgb(139,126,245) | 5.75:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 按钮 primary | `.sv-btn-primary`[1] | rgb(15,17,23) | rgb(139,126,245) | 5.75:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 danger | `.sv-btn-danger`[0] | rgb(15,17,23) | rgb(248,113,113) | 6.82:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[0] | rgb(226,232,240) | rgb(37,40,64) | 11.7:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[1] | rgb(226,232,240) | rgb(37,40,64) | 11.7:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[0] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 按钮 outline | `.sv-btn-outline`[1] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[2] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 表单控件 | `.sv-form-control`[0] | rgb(226,232,240) | rgb(30,32,48) | 13.06:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 状态栏 | `.sv-statusbar`[0] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12px | 400 |

#### 视频修复

| 类别 | 选择器 | 文字颜色 | 背景颜色 | 对比度 | 阈值 | 合规 | 字号 | 字重 |
|------|--------|----------|----------|--------|------|------|------|------|
| 页面标题 h1 | `.sv-page-header h1, .sv-hero h1`[0] | rgb(226,232,240) | rgb(15,17,23) | 15.31:1 | 3:1 | ✅ | 25.6px | 700 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[0] | rgb(226,232,240) | rgb(22,24,34) | 14.34:1 | 3:1 | ✅ | 15.2px | 600 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[1] | rgb(226,232,240) | rgb(22,24,34) | 14.34:1 | 3:1 | ✅ | 15.2px | 600 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[2] | rgb(226,232,240) | rgb(22,24,34) | 14.34:1 | 3:1 | ✅ | 15.2px | 600 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[0] | rgb(148,163,184) | rgb(15,17,23) | 7.36:1 | 4.5:1 | ✅ | 14.4px | 400 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[1] | rgb(226,232,240) | rgb(30,32,48) | 13.06:1 | 4.5:1 | ✅ | 13.6px | 600 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[2] | rgb(226,232,240) | rgb(30,32,48) | 13.06:1 | 4.5:1 | ✅ | 13.6px | 600 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[0] | rgb(136,153,170) | rgb(30,32,48) | 5.51:1 | 4.5:1 | ✅ | 12.8px | 400 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[1] | rgb(136,153,170) | rgb(22,24,34) | 6.05:1 | 4.5:1 | ✅ | 12px | 400 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[2] | rgb(136,153,170) | rgb(22,24,34) | 6.05:1 | 4.5:1 | ✅ | 12px | 400 |
| 导航链接 | `.sv-nav-link`[0] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[1] | rgb(139,126,245) | rgb(37,37,63) | 4.52:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[2] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接(活跃) | `.sv-nav-link.active`[0] | rgb(139,126,245) | rgb(37,37,63) | 4.52:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 primary | `.sv-btn-primary`[0] | rgb(15,17,23) | rgb(139,126,245) | 5.75:1 | 4.5:1 | ✅ | 15.2px | 500 |
| 按钮 primary | `.sv-btn-primary`[1] | rgb(15,17,23) | rgb(139,126,245) | 5.75:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 primary | `.sv-btn-primary`[2] | rgb(15,17,23) | rgb(139,126,245) | 5.75:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 按钮 danger | `.sv-btn-danger`[0] | rgb(15,17,23) | rgb(248,113,113) | 6.82:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[0] | rgb(226,232,240) | rgb(37,40,64) | 11.7:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[1] | rgb(226,232,240) | rgb(37,40,64) | 11.7:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[2] | rgb(226,232,240) | rgb(37,40,64) | 11.7:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[0] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 按钮 outline | `.sv-btn-outline`[1] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[2] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 按钮 warning | `.sv-btn-warning`[0] | rgb(15,17,23) | rgb(251,191,36) | 11.3:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 表单标签 | `.sv-form-label, .sv-range-header label`[0] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 表单标签 | `.sv-form-label, .sv-range-header label`[1] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 表单标签 | `.sv-form-label, .sv-range-header label`[2] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 表单控件 | `.sv-form-control`[0] | rgb(226,232,240) | rgb(30,32,48) | 13.06:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 表单控件 | `.sv-form-control`[1] | rgb(226,232,240) | rgb(30,32,48) | 13.06:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 表单控件 | `.sv-form-control`[2] | rgb(226,232,240) | rgb(37,40,64) | 11.7:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 徽章 processing | `.sv-badge-processing`[0] | rgb(96,165,250) | rgb(30,44,64) | 5.55:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 徽章 processing | `.sv-badge-processing`[1] | rgb(96,165,250) | rgb(30,44,64) | 5.55:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 徽章 completed | `.sv-badge-completed`[0] | rgb(52,211,153) | rgb(22,52,46) | 6.98:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 徽章 secondary | `.sv-badge-secondary`[0] | rgb(148,163,184) | rgb(37,40,64) | 5.62:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 状态栏 | `.sv-statusbar`[0] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12px | 400 |
| 面包屑当前 | `.sv-breadcrumb .current`[0] | rgb(226,232,240) | rgb(15,17,23) | 15.31:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 面包屑链接 | `.sv-breadcrumb a`[0] | rgb(148,163,184) | rgb(15,17,23) | 7.36:1 | 4.5:1 | ✅ | 12.8px | 400 |
| 开关标签 | `.sv-form-switch .switch-label`[0] | rgb(226,232,240) | rgb(22,24,34) | 14.34:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 开关标签 | `.sv-form-switch .switch-label`[1] | rgb(226,232,240) | rgb(22,24,34) | 14.34:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 开关标签 | `.sv-form-switch .switch-label`[2] | rgb(226,232,240) | rgb(22,24,34) | 14.34:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 上传区域标题 | `.sv-upload-zone .upload-title`[0] | rgb(226,232,240) | rgb(30,32,48) | 13.06:1 | 4.5:1 | ✅ | 15.2px | 600 |
| 输入模式标签 | `.sv-input-mode-tab`[0] | rgb(15,17,23) | rgb(139,126,245) | 5.75:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 输入模式标签 | `.sv-input-mode-tab`[1] | rgb(136,153,170) | rgb(30,32,48) | 5.51:1 | 4.5:1 | ✅ | 12.8px | 500 |

#### 图像修复

| 类别 | 选择器 | 文字颜色 | 背景颜色 | 对比度 | 阈值 | 合规 | 字号 | 字重 |
|------|--------|----------|----------|--------|------|------|------|------|
| 页面标题 h1 | `.sv-page-header h1, .sv-hero h1`[0] | rgb(226,232,240) | rgb(15,17,23) | 15.31:1 | 3:1 | ✅ | 25.6px | 700 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[0] | rgb(226,232,240) | rgb(22,24,34) | 14.34:1 | 3:1 | ✅ | 15.2px | 600 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[1] | rgb(226,232,240) | rgb(22,24,34) | 14.34:1 | 3:1 | ✅ | 15.2px | 600 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[2] | rgb(226,232,240) | rgb(22,24,34) | 14.34:1 | 3:1 | ✅ | 15.2px | 600 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[0] | rgb(148,163,184) | rgb(15,17,23) | 7.36:1 | 4.5:1 | ✅ | 14.4px | 400 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[0] | rgb(136,153,170) | rgb(30,32,48) | 5.51:1 | 4.5:1 | ✅ | 12.8px | 400 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[1] | rgb(136,153,170) | rgb(22,24,34) | 6.05:1 | 4.5:1 | ✅ | 12.48px | 600 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[2] | rgb(136,153,170) | rgb(22,24,34) | 6.05:1 | 4.5:1 | ✅ | 12px | 400 |
| 导航链接 | `.sv-nav-link`[0] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[1] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[2] | rgb(139,126,245) | rgb(37,37,63) | 4.52:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接(活跃) | `.sv-nav-link.active`[0] | rgb(139,126,245) | rgb(37,37,63) | 4.52:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 primary | `.sv-btn-primary`[0] | rgb(15,17,23) | rgb(139,126,245) | 5.75:1 | 4.5:1 | ✅ | 15.2px | 500 |
| 按钮 primary | `.sv-btn-primary`[1] | rgb(15,17,23) | rgb(139,126,245) | 5.75:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 primary | `.sv-btn-primary`[2] | rgb(15,17,23) | rgb(139,126,245) | 5.75:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 按钮 danger | `.sv-btn-danger`[0] | rgb(15,17,23) | rgb(248,113,113) | 6.82:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[0] | rgb(226,232,240) | rgb(37,40,64) | 11.7:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[1] | rgb(226,232,240) | rgb(37,40,64) | 11.7:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[2] | rgb(226,232,240) | rgb(37,40,64) | 11.7:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[0] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 按钮 outline | `.sv-btn-outline`[1] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[2] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 按钮 warning | `.sv-btn-warning`[0] | rgb(15,17,23) | rgb(251,191,36) | 11.3:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 表单标签 | `.sv-form-label, .sv-range-header label`[0] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 表单标签 | `.sv-form-label, .sv-range-header label`[1] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 表单标签 | `.sv-form-label, .sv-range-header label`[2] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 表单控件 | `.sv-form-control`[0] | rgb(226,232,240) | rgb(30,32,48) | 13.06:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 表单控件 | `.sv-form-control`[1] | rgb(226,232,240) | rgb(30,32,48) | 13.06:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 表单控件 | `.sv-form-control`[2] | rgb(226,232,240) | rgb(30,32,48) | 13.06:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 徽章 processing | `.sv-badge-processing`[0] | rgb(96,165,250) | rgb(30,44,64) | 5.55:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 徽章 processing | `.sv-badge-processing`[1] | rgb(96,165,250) | rgb(30,44,64) | 5.55:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 徽章 completed | `.sv-badge-completed`[0] | rgb(52,211,153) | rgb(22,52,46) | 6.98:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 徽章 primary | `.sv-badge-primary`[0] | rgb(139,126,245) | rgb(37,37,63) | 4.52:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 徽章 primary | `.sv-badge-primary`[1] | rgb(139,126,245) | rgb(37,37,63) | 4.52:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 徽章 primary | `.sv-badge-primary`[2] | rgb(139,126,245) | rgb(37,37,63) | 4.52:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 徽章 secondary | `.sv-badge-secondary`[0] | rgb(148,163,184) | rgb(37,40,64) | 5.62:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 徽章 secondary | `.sv-badge-secondary`[1] | rgb(148,163,184) | rgb(37,40,64) | 5.62:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 状态栏 | `.sv-statusbar`[0] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12px | 400 |
| 面包屑当前 | `.sv-breadcrumb .current`[0] | rgb(226,232,240) | rgb(15,17,23) | 15.31:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 面包屑链接 | `.sv-breadcrumb a`[0] | rgb(148,163,184) | rgb(15,17,23) | 7.36:1 | 4.5:1 | ✅ | 12.8px | 400 |
| 开关标签 | `.sv-form-switch .switch-label`[0] | rgb(226,232,240) | rgb(22,24,34) | 14.34:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 开关标签 | `.sv-form-switch .switch-label`[1] | rgb(226,232,240) | rgb(22,24,34) | 14.34:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 开关标签 | `.sv-form-switch .switch-label`[2] | rgb(226,232,240) | rgb(22,24,34) | 14.34:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 上传区域标题 | `.sv-upload-zone .upload-title`[0] | rgb(226,232,240) | rgb(30,32,48) | 13.06:1 | 4.5:1 | ✅ | 15.2px | 600 |

#### 设置

| 类别 | 选择器 | 文字颜色 | 背景颜色 | 对比度 | 阈值 | 合规 | 字号 | 字重 |
|------|--------|----------|----------|--------|------|------|------|------|
| 页面标题 h1 | `.sv-page-header h1, .sv-hero h1`[0] | rgb(226,232,240) | rgb(15,17,23) | 15.31:1 | 3:1 | ✅ | 25.6px | 700 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[0] | rgb(226,232,240) | rgb(15,17,23) | 15.31:1 | 3:1 | ✅ | 17.6px | 600 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[1] | rgb(226,232,240) | rgb(15,17,23) | 15.31:1 | 3:1 | ✅ | 17.6px | 600 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[2] | rgb(226,232,240) | rgb(15,17,23) | 15.31:1 | 3:1 | ✅ | 17.6px | 600 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[0] | rgb(148,163,184) | rgb(15,17,23) | 7.36:1 | 4.5:1 | ✅ | 14.4px | 400 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[0] | rgb(136,153,170) | rgb(22,24,34) | 6.05:1 | 4.5:1 | ✅ | 16px | 400 |
| 导航链接 | `.sv-nav-link`[0] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[1] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[2] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接(活跃) | `.sv-nav-link.active`[0] | rgb(139,126,245) | rgb(37,37,63) | 4.52:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 primary | `.sv-btn-primary`[0] | rgb(15,17,23) | rgb(139,126,245) | 5.75:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 按钮 primary | `.sv-btn-primary`[1] | rgb(15,17,23) | rgb(139,126,245) | 5.75:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 按钮 primary | `.sv-btn-primary`[2] | rgb(15,17,23) | rgb(139,126,245) | 5.75:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 按钮 danger | `.sv-btn-danger`[0] | rgb(15,17,23) | rgb(248,113,113) | 6.82:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[0] | rgb(226,232,240) | rgb(37,40,64) | 11.7:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[1] | rgb(226,232,240) | rgb(37,40,64) | 11.7:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[2] | rgb(226,232,240) | rgb(37,40,64) | 11.7:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[0] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 按钮 outline | `.sv-btn-outline`[1] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[2] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 表单标签 | `.sv-form-label, .sv-range-header label`[0] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 表单标签 | `.sv-form-label, .sv-range-header label`[1] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 表单标签 | `.sv-form-label, .sv-range-header label`[2] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 表单控件 | `.sv-form-control`[0] | rgb(226,232,240) | rgb(30,32,48) | 13.06:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 表单控件 | `.sv-form-control`[1] | rgb(226,232,240) | rgb(30,32,48) | 13.06:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 表单控件 | `.sv-form-control`[2] | rgb(226,232,240) | rgb(30,32,48) | 13.06:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 状态栏 | `.sv-statusbar`[0] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12px | 400 |
| 面包屑当前 | `.sv-breadcrumb .current`[0] | rgb(226,232,240) | rgb(15,17,23) | 15.31:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 面包屑链接 | `.sv-breadcrumb a`[0] | rgb(148,163,184) | rgb(15,17,23) | 7.36:1 | 4.5:1 | ✅ | 12.8px | 400 |
| 设置导航 | `.sv-settings-nav .nav-item`[0] | rgb(148,163,184) | rgb(15,17,23) | 7.36:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 设置导航 | `.sv-settings-nav .nav-item`[1] | rgb(148,163,184) | rgb(15,17,23) | 7.36:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 设置导航 | `.sv-settings-nav .nav-item`[2] | rgb(148,163,184) | rgb(15,17,23) | 7.36:1 | 4.5:1 | ✅ | 13.6px | 400 |

#### 历史记录

| 类别 | 选择器 | 文字颜色 | 背景颜色 | 对比度 | 阈值 | 合规 | 字号 | 字重 |
|------|--------|----------|----------|--------|------|------|------|------|
| 页面标题 h1 | `.sv-page-header h1, .sv-hero h1`[0] | rgb(226,232,240) | rgb(15,17,23) | 15.31:1 | 3:1 | ✅ | 25.6px | 700 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[0] | rgb(148,163,184) | rgb(15,17,23) | 7.36:1 | 4.5:1 | ✅ | 14.4px | 400 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[0] | rgb(136,153,170) | rgb(30,32,48) | 5.51:1 | 4.5:1 | ✅ | 12px | 600 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[1] | rgb(136,153,170) | rgb(30,32,48) | 5.51:1 | 4.5:1 | ✅ | 12px | 600 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[2] | rgb(136,153,170) | rgb(30,32,48) | 5.51:1 | 4.5:1 | ✅ | 12px | 600 |
| 导航链接 | `.sv-nav-link`[0] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[1] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[2] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接(活跃) | `.sv-nav-link.active`[0] | rgb(139,126,245) | rgb(37,37,63) | 4.52:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 primary | `.sv-btn-primary`[0] | rgb(15,17,23) | rgb(139,126,245) | 5.75:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 按钮 primary | `.sv-btn-primary`[1] | rgb(15,17,23) | rgb(139,126,245) | 5.75:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 danger | `.sv-btn-danger`[0] | rgb(15,17,23) | rgb(248,113,113) | 6.82:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 danger | `.sv-btn-danger`[1] | rgb(15,17,23) | rgb(248,113,113) | 6.82:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[0] | rgb(226,232,240) | rgb(37,40,64) | 11.7:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[1] | rgb(226,232,240) | rgb(37,40,64) | 11.7:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[2] | rgb(226,232,240) | rgb(37,40,64) | 11.7:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[0] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 按钮 outline | `.sv-btn-outline`[1] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[2] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 表单控件 | `.sv-form-control`[0] | rgb(226,232,240) | rgb(30,32,48) | 13.06:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 表单控件 | `.sv-form-control`[1] | rgb(226,232,240) | rgb(30,32,48) | 13.06:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 表单控件 | `.sv-form-control`[2] | rgb(226,232,240) | rgb(30,32,48) | 13.06:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 徽章 completed | `.sv-badge-completed`[0] | rgb(52,211,153) | rgb(22,52,46) | 6.98:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 徽章 completed | `.sv-badge-completed`[1] | rgb(52,211,153) | rgb(22,52,46) | 6.98:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 徽章 completed | `.sv-badge-completed`[2] | rgb(52,211,153) | rgb(22,52,46) | 6.98:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 状态栏 | `.sv-statusbar`[0] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12px | 400 |
| 面包屑当前 | `.sv-breadcrumb .current`[0] | rgb(226,232,240) | rgb(15,17,23) | 15.31:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 面包屑链接 | `.sv-breadcrumb a`[0] | rgb(148,163,184) | rgb(15,17,23) | 7.36:1 | 4.5:1 | ✅ | 12.8px | 400 |
| 表格内容 | `.sv-table tbody td`[0] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 表格内容 | `.sv-table tbody td`[1] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 表格内容 | `.sv-table tbody td`[2] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 分页按钮 | `.sv-pagination .page-btn`[0] | rgb(148,163,184) | rgb(30,32,48) | 6.28:1 | 4.5:1 | ✅ | 12.8px | 400 |
| 分页按钮 | `.sv-pagination .page-btn`[1] | rgb(148,163,184) | rgb(30,32,48) | 6.28:1 | 4.5:1 | ✅ | 12.8px | 400 |
| 分页信息 | `.sv-pagination .page-info`[0] | rgb(136,153,170) | rgb(22,24,34) | 6.05:1 | 4.5:1 | ✅ | 12.8px | 400 |

#### 系统状态

| 类别 | 选择器 | 文字颜色 | 背景颜色 | 对比度 | 阈值 | 合规 | 字号 | 字重 |
|------|--------|----------|----------|--------|------|------|------|------|
| 页面标题 h1 | `.sv-page-header h1, .sv-hero h1`[0] | rgb(226,232,240) | rgb(15,17,23) | 15.31:1 | 3:1 | ✅ | 25.6px | 700 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[0] | rgb(226,232,240) | rgb(22,24,34) | 14.34:1 | 3:1 | ✅ | 15.2px | 600 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[1] | rgb(226,232,240) | rgb(22,24,34) | 14.34:1 | 3:1 | ✅ | 15.2px | 600 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[2] | rgb(226,232,240) | rgb(22,24,34) | 14.34:1 | 3:1 | ✅ | 15.2px | 600 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[0] | rgb(148,163,184) | rgb(15,17,23) | 7.36:1 | 4.5:1 | ✅ | 14.4px | 400 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[1] | rgb(226,232,240) | rgb(22,24,34) | 14.34:1 | 4.5:1 | ✅ | 13.6px | 600 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[2] | rgb(226,232,240) | rgb(22,24,34) | 14.34:1 | 4.5:1 | ✅ | 13.6px | 600 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[0] | rgb(136,153,170) | rgb(22,24,34) | 6.05:1 | 4.5:1 | ✅ | 12px | 600 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[1] | rgb(136,153,170) | rgb(22,24,34) | 6.05:1 | 4.5:1 | ✅ | 12px | 600 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[2] | rgb(136,153,170) | rgb(22,24,34) | 6.05:1 | 4.5:1 | ✅ | 16px | 400 |
| 导航链接 | `.sv-nav-link`[0] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[1] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[2] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接(活跃) | `.sv-nav-link.active`[0] | rgb(139,126,245) | rgb(37,37,63) | 4.52:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 primary | `.sv-btn-primary`[0] | rgb(15,17,23) | rgb(139,126,245) | 5.75:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 按钮 primary | `.sv-btn-primary`[1] | rgb(15,17,23) | rgb(139,126,245) | 5.75:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 danger | `.sv-btn-danger`[0] | rgb(15,17,23) | rgb(248,113,113) | 6.82:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[0] | rgb(226,232,240) | rgb(37,40,64) | 11.7:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[1] | rgb(226,232,240) | rgb(37,40,64) | 11.7:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[2] | rgb(226,232,240) | rgb(37,40,64) | 11.7:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[0] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 按钮 outline | `.sv-btn-outline`[1] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[2] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 表单控件 | `.sv-form-control`[0] | rgb(226,232,240) | rgb(30,32,48) | 13.06:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 徽章 completed | `.sv-badge-completed`[0] | rgb(52,211,153) | rgb(22,52,46) | 6.98:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 徽章 secondary | `.sv-badge-secondary`[0] | rgb(148,163,184) | rgb(37,40,64) | 5.62:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 状态栏 | `.sv-statusbar`[0] | rgb(148,163,184) | rgb(22,24,34) | 6.89:1 | 4.5:1 | ✅ | 12px | 400 |
| 面包屑当前 | `.sv-breadcrumb .current`[0] | rgb(226,232,240) | rgb(15,17,23) | 15.31:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 面包屑链接 | `.sv-breadcrumb a`[0] | rgb(148,163,184) | rgb(15,17,23) | 7.36:1 | 4.5:1 | ✅ | 12.8px | 400 |

### LIGHT 主题

#### 首页

| 类别 | 选择器 | 文字颜色 | 背景颜色 | 对比度 | 阈值 | 合规 | 字号 | 字重 |
|------|--------|----------|----------|--------|------|------|------|------|
| 页面标题 h1 | `.sv-page-header h1, .sv-hero h1`[0] | rgb(30,41,59) | rgb(248,250,252) | 13.98:1 | 3:1 | ✅ | 36px | 800 |
| 页面标题 h1 | `.sv-page-header h1, .sv-hero h1`[1] | rgb(30,41,59) | rgb(248,250,252) | 13.98:1 | 3:1 | ✅ | 25.6px | 700 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[0] | rgb(71,85,105) | rgb(248,250,252) | 7.24:1 | 4.5:1 | ✅ | 16px | 400 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[1] | rgb(30,41,59) | rgb(255,255,255) | 14.63:1 | 4.5:1 | ✅ | 16px | 600 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[2] | rgb(30,41,59) | rgb(255,255,255) | 14.63:1 | 4.5:1 | ✅ | 16px | 600 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[0] | rgb(71,85,105) | rgb(241,245,249) | 6.92:1 | 4.5:1 | ✅ | 12px | 400 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[1] | rgb(71,85,105) | rgb(241,245,249) | 6.92:1 | 4.5:1 | ✅ | 12px | 400 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[2] | rgb(71,85,105) | rgb(241,245,249) | 6.92:1 | 4.5:1 | ✅ | 12px | 400 |
| 导航链接 | `.sv-nav-link`[0] | rgb(91,76,213) | rgb(229,229,247) | 4.91:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[1] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[2] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接(活跃) | `.sv-nav-link.active`[0] | rgb(91,76,213) | rgb(229,229,247) | 4.91:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 primary | `.sv-btn-primary`[0] | rgb(255,255,255) | rgb(91,76,213) | 6.11:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 按钮 primary | `.sv-btn-primary`[1] | rgb(255,255,255) | rgb(91,76,213) | 6.11:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 danger | `.sv-btn-danger`[0] | rgb(255,255,255) | rgb(220,38,38) | 4.83:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[0] | rgb(30,41,59) | rgb(226,232,240) | 11.87:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[1] | rgb(30,41,59) | rgb(226,232,240) | 11.87:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[0] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 按钮 outline | `.sv-btn-outline`[1] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[2] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 表单控件 | `.sv-form-control`[0] | rgb(30,41,59) | rgb(241,245,249) | 13.35:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 状态栏 | `.sv-statusbar`[0] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12px | 400 |

#### 视频修复

| 类别 | 选择器 | 文字颜色 | 背景颜色 | 对比度 | 阈值 | 合规 | 字号 | 字重 |
|------|--------|----------|----------|--------|------|------|------|------|
| 页面标题 h1 | `.sv-page-header h1, .sv-hero h1`[0] | rgb(30,41,59) | rgb(248,250,252) | 13.98:1 | 3:1 | ✅ | 25.6px | 700 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[0] | rgb(30,41,59) | rgb(255,255,255) | 14.63:1 | 3:1 | ✅ | 15.2px | 600 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[1] | rgb(30,41,59) | rgb(255,255,255) | 14.63:1 | 3:1 | ✅ | 15.2px | 600 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[2] | rgb(30,41,59) | rgb(255,255,255) | 14.63:1 | 3:1 | ✅ | 15.2px | 600 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[0] | rgb(71,85,105) | rgb(248,250,252) | 7.24:1 | 4.5:1 | ✅ | 14.4px | 400 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[1] | rgb(30,41,59) | rgb(241,245,249) | 13.35:1 | 4.5:1 | ✅ | 13.6px | 600 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[2] | rgb(30,41,59) | rgb(241,245,249) | 13.35:1 | 4.5:1 | ✅ | 13.6px | 600 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[0] | rgb(84,100,120) | rgb(241,245,249) | 5.52:1 | 4.5:1 | ✅ | 12.8px | 400 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[1] | rgb(84,100,120) | rgb(255,255,255) | 6.05:1 | 4.5:1 | ✅ | 12px | 400 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[2] | rgb(84,100,120) | rgb(255,255,255) | 6.05:1 | 4.5:1 | ✅ | 12px | 400 |
| 导航链接 | `.sv-nav-link`[0] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[1] | rgb(91,76,213) | rgb(229,229,247) | 4.91:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[2] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接(活跃) | `.sv-nav-link.active`[0] | rgb(91,76,213) | rgb(229,229,247) | 4.91:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 primary | `.sv-btn-primary`[0] | rgb(255,255,255) | rgb(91,76,213) | 6.11:1 | 4.5:1 | ✅ | 15.2px | 500 |
| 按钮 primary | `.sv-btn-primary`[1] | rgb(255,255,255) | rgb(91,76,213) | 6.11:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 primary | `.sv-btn-primary`[2] | rgb(255,255,255) | rgb(91,76,213) | 6.11:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 按钮 danger | `.sv-btn-danger`[0] | rgb(255,255,255) | rgb(220,38,38) | 4.83:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[0] | rgb(30,41,59) | rgb(226,232,240) | 11.87:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[1] | rgb(30,41,59) | rgb(226,232,240) | 11.87:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[2] | rgb(30,41,59) | rgb(226,232,240) | 11.87:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[0] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 按钮 outline | `.sv-btn-outline`[1] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[2] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 按钮 warning | `.sv-btn-warning`[0] | rgb(255,255,255) | rgb(180,83,9) | 5.02:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 表单标签 | `.sv-form-label, .sv-range-header label`[0] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 表单标签 | `.sv-form-label, .sv-range-header label`[1] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 表单标签 | `.sv-form-label, .sv-range-header label`[2] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 表单控件 | `.sv-form-control`[0] | rgb(30,41,59) | rgb(241,245,249) | 13.35:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 表单控件 | `.sv-form-control`[1] | rgb(30,41,59) | rgb(241,245,249) | 13.35:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 表单控件 | `.sv-form-control`[2] | rgb(30,41,59) | rgb(226,232,240) | 11.87:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 徽章 processing | `.sv-badge-processing`[0] | rgb(29,78,216) | rgb(222,229,248) | 5.32:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 徽章 processing | `.sv-badge-processing`[1] | rgb(29,78,216) | rgb(222,229,248) | 5.32:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 徽章 completed | `.sv-badge-completed`[0] | rgb(21,128,61) | rgb(214,232,223) | 3.93:1 | 4.5:1 | ❌ | 11.52px | 600 |
| 徽章 secondary | `.sv-badge-secondary`[0] | rgb(71,85,105) | rgb(226,232,240) | 6.15:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 状态栏 | `.sv-statusbar`[0] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12px | 400 |
| 面包屑当前 | `.sv-breadcrumb .current`[0] | rgb(30,41,59) | rgb(248,250,252) | 13.98:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 面包屑链接 | `.sv-breadcrumb a`[0] | rgb(71,85,105) | rgb(248,250,252) | 7.24:1 | 4.5:1 | ✅ | 12.8px | 400 |
| 开关标签 | `.sv-form-switch .switch-label`[0] | rgb(30,41,59) | rgb(255,255,255) | 14.63:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 开关标签 | `.sv-form-switch .switch-label`[1] | rgb(30,41,59) | rgb(255,255,255) | 14.63:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 开关标签 | `.sv-form-switch .switch-label`[2] | rgb(30,41,59) | rgb(255,255,255) | 14.63:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 上传区域标题 | `.sv-upload-zone .upload-title`[0] | rgb(30,41,59) | rgb(241,245,249) | 13.35:1 | 4.5:1 | ✅ | 15.2px | 600 |
| 输入模式标签 | `.sv-input-mode-tab`[0] | rgb(255,255,255) | rgb(91,76,213) | 6.11:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 输入模式标签 | `.sv-input-mode-tab`[1] | rgb(84,100,120) | rgb(241,245,249) | 5.52:1 | 4.5:1 | ✅ | 12.8px | 500 |

#### 图像修复

| 类别 | 选择器 | 文字颜色 | 背景颜色 | 对比度 | 阈值 | 合规 | 字号 | 字重 |
|------|--------|----------|----------|--------|------|------|------|------|
| 页面标题 h1 | `.sv-page-header h1, .sv-hero h1`[0] | rgb(30,41,59) | rgb(248,250,252) | 13.98:1 | 3:1 | ✅ | 25.6px | 700 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[0] | rgb(30,41,59) | rgb(255,255,255) | 14.63:1 | 3:1 | ✅ | 15.2px | 600 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[1] | rgb(30,41,59) | rgb(255,255,255) | 14.63:1 | 3:1 | ✅ | 15.2px | 600 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[2] | rgb(30,41,59) | rgb(255,255,255) | 14.63:1 | 3:1 | ✅ | 15.2px | 600 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[0] | rgb(71,85,105) | rgb(248,250,252) | 7.24:1 | 4.5:1 | ✅ | 14.4px | 400 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[0] | rgb(84,100,120) | rgb(241,245,249) | 5.52:1 | 4.5:1 | ✅ | 12.8px | 400 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[1] | rgb(84,100,120) | rgb(255,255,255) | 6.05:1 | 4.5:1 | ✅ | 12.48px | 600 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[2] | rgb(84,100,120) | rgb(255,255,255) | 6.05:1 | 4.5:1 | ✅ | 12px | 400 |
| 导航链接 | `.sv-nav-link`[0] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[1] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[2] | rgb(91,76,213) | rgb(229,229,247) | 4.91:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接(活跃) | `.sv-nav-link.active`[0] | rgb(91,76,213) | rgb(229,229,247) | 4.91:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 primary | `.sv-btn-primary`[0] | rgb(255,255,255) | rgb(91,76,213) | 6.11:1 | 4.5:1 | ✅ | 15.2px | 500 |
| 按钮 primary | `.sv-btn-primary`[1] | rgb(255,255,255) | rgb(91,76,213) | 6.11:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 primary | `.sv-btn-primary`[2] | rgb(255,255,255) | rgb(91,76,213) | 6.11:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 按钮 danger | `.sv-btn-danger`[0] | rgb(255,255,255) | rgb(220,38,38) | 4.83:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[0] | rgb(30,41,59) | rgb(226,232,240) | 11.87:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[1] | rgb(30,41,59) | rgb(226,232,240) | 11.87:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[2] | rgb(30,41,59) | rgb(226,232,240) | 11.87:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[0] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 按钮 outline | `.sv-btn-outline`[1] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[2] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 按钮 warning | `.sv-btn-warning`[0] | rgb(255,255,255) | rgb(180,83,9) | 5.02:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 表单标签 | `.sv-form-label, .sv-range-header label`[0] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 表单标签 | `.sv-form-label, .sv-range-header label`[1] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 表单标签 | `.sv-form-label, .sv-range-header label`[2] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 表单控件 | `.sv-form-control`[0] | rgb(30,41,59) | rgb(241,245,249) | 13.35:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 表单控件 | `.sv-form-control`[1] | rgb(30,41,59) | rgb(241,245,249) | 13.35:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 表单控件 | `.sv-form-control`[2] | rgb(30,41,59) | rgb(241,245,249) | 13.35:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 徽章 processing | `.sv-badge-processing`[0] | rgb(29,78,216) | rgb(222,229,248) | 5.32:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 徽章 processing | `.sv-badge-processing`[1] | rgb(29,78,216) | rgb(222,229,248) | 5.32:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 徽章 completed | `.sv-badge-completed`[0] | rgb(21,128,61) | rgb(214,232,223) | 3.93:1 | 4.5:1 | ❌ | 11.52px | 600 |
| 徽章 primary | `.sv-badge-primary`[0] | rgb(91,76,213) | rgb(229,229,247) | 4.91:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 徽章 primary | `.sv-badge-primary`[1] | rgb(91,76,213) | rgb(229,229,247) | 4.91:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 徽章 primary | `.sv-badge-primary`[2] | rgb(91,76,213) | rgb(229,229,247) | 4.91:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 徽章 secondary | `.sv-badge-secondary`[0] | rgb(71,85,105) | rgb(226,232,240) | 6.15:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 徽章 secondary | `.sv-badge-secondary`[1] | rgb(71,85,105) | rgb(226,232,240) | 6.15:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 状态栏 | `.sv-statusbar`[0] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12px | 400 |
| 面包屑当前 | `.sv-breadcrumb .current`[0] | rgb(30,41,59) | rgb(248,250,252) | 13.98:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 面包屑链接 | `.sv-breadcrumb a`[0] | rgb(71,85,105) | rgb(248,250,252) | 7.24:1 | 4.5:1 | ✅ | 12.8px | 400 |
| 开关标签 | `.sv-form-switch .switch-label`[0] | rgb(30,41,59) | rgb(255,255,255) | 14.63:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 开关标签 | `.sv-form-switch .switch-label`[1] | rgb(30,41,59) | rgb(255,255,255) | 14.63:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 开关标签 | `.sv-form-switch .switch-label`[2] | rgb(30,41,59) | rgb(255,255,255) | 14.63:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 上传区域标题 | `.sv-upload-zone .upload-title`[0] | rgb(30,41,59) | rgb(241,245,249) | 13.35:1 | 4.5:1 | ✅ | 15.2px | 600 |

#### 设置

| 类别 | 选择器 | 文字颜色 | 背景颜色 | 对比度 | 阈值 | 合规 | 字号 | 字重 |
|------|--------|----------|----------|--------|------|------|------|------|
| 页面标题 h1 | `.sv-page-header h1, .sv-hero h1`[0] | rgb(30,41,59) | rgb(248,250,252) | 13.98:1 | 3:1 | ✅ | 25.6px | 700 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[0] | rgb(30,41,59) | rgb(248,250,252) | 13.98:1 | 3:1 | ✅ | 17.6px | 600 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[1] | rgb(30,41,59) | rgb(248,250,252) | 13.98:1 | 3:1 | ✅ | 17.6px | 600 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[2] | rgb(30,41,59) | rgb(248,250,252) | 13.98:1 | 3:1 | ✅ | 17.6px | 600 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[0] | rgb(71,85,105) | rgb(248,250,252) | 7.24:1 | 4.5:1 | ✅ | 14.4px | 400 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[0] | rgb(84,100,120) | rgb(255,255,255) | 6.05:1 | 4.5:1 | ✅ | 16px | 400 |
| 导航链接 | `.sv-nav-link`[0] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[1] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[2] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接(活跃) | `.sv-nav-link.active`[0] | rgb(91,76,213) | rgb(229,229,247) | 4.91:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 primary | `.sv-btn-primary`[0] | rgb(255,255,255) | rgb(91,76,213) | 6.11:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 按钮 primary | `.sv-btn-primary`[1] | rgb(255,255,255) | rgb(91,76,213) | 6.11:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 按钮 primary | `.sv-btn-primary`[2] | rgb(255,255,255) | rgb(91,76,213) | 6.11:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 按钮 danger | `.sv-btn-danger`[0] | rgb(255,255,255) | rgb(220,38,38) | 4.83:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[0] | rgb(30,41,59) | rgb(226,232,240) | 11.87:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[1] | rgb(30,41,59) | rgb(226,232,240) | 11.87:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[2] | rgb(30,41,59) | rgb(226,232,240) | 11.87:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[0] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 按钮 outline | `.sv-btn-outline`[1] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[2] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 表单标签 | `.sv-form-label, .sv-range-header label`[0] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 表单标签 | `.sv-form-label, .sv-range-header label`[1] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 表单标签 | `.sv-form-label, .sv-range-header label`[2] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 表单控件 | `.sv-form-control`[0] | rgb(30,41,59) | rgb(241,245,249) | 13.35:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 表单控件 | `.sv-form-control`[1] | rgb(30,41,59) | rgb(241,245,249) | 13.35:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 表单控件 | `.sv-form-control`[2] | rgb(30,41,59) | rgb(241,245,249) | 13.35:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 状态栏 | `.sv-statusbar`[0] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12px | 400 |
| 面包屑当前 | `.sv-breadcrumb .current`[0] | rgb(30,41,59) | rgb(248,250,252) | 13.98:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 面包屑链接 | `.sv-breadcrumb a`[0] | rgb(71,85,105) | rgb(248,250,252) | 7.24:1 | 4.5:1 | ✅ | 12.8px | 400 |
| 设置导航 | `.sv-settings-nav .nav-item`[0] | rgb(71,85,105) | rgb(248,250,252) | 7.24:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 设置导航 | `.sv-settings-nav .nav-item`[1] | rgb(71,85,105) | rgb(248,250,252) | 7.24:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 设置导航 | `.sv-settings-nav .nav-item`[2] | rgb(71,85,105) | rgb(248,250,252) | 7.24:1 | 4.5:1 | ✅ | 13.6px | 400 |

#### 历史记录

| 类别 | 选择器 | 文字颜色 | 背景颜色 | 对比度 | 阈值 | 合规 | 字号 | 字重 |
|------|--------|----------|----------|--------|------|------|------|------|
| 页面标题 h1 | `.sv-page-header h1, .sv-hero h1`[0] | rgb(30,41,59) | rgb(248,250,252) | 13.98:1 | 3:1 | ✅ | 25.6px | 700 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[0] | rgb(71,85,105) | rgb(248,250,252) | 7.24:1 | 4.5:1 | ✅ | 14.4px | 400 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[0] | rgb(84,100,120) | rgb(241,245,249) | 5.52:1 | 4.5:1 | ✅ | 12px | 600 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[1] | rgb(84,100,120) | rgb(241,245,249) | 5.52:1 | 4.5:1 | ✅ | 12px | 600 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[2] | rgb(84,100,120) | rgb(241,245,249) | 5.52:1 | 4.5:1 | ✅ | 12px | 600 |
| 导航链接 | `.sv-nav-link`[0] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[1] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[2] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接(活跃) | `.sv-nav-link.active`[0] | rgb(91,76,213) | rgb(229,229,247) | 4.91:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 primary | `.sv-btn-primary`[0] | rgb(255,255,255) | rgb(91,76,213) | 6.11:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 按钮 primary | `.sv-btn-primary`[1] | rgb(255,255,255) | rgb(91,76,213) | 6.11:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 danger | `.sv-btn-danger`[0] | rgb(255,255,255) | rgb(220,38,38) | 4.83:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 danger | `.sv-btn-danger`[1] | rgb(255,255,255) | rgb(220,38,38) | 4.83:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[0] | rgb(30,41,59) | rgb(226,232,240) | 11.87:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[1] | rgb(30,41,59) | rgb(226,232,240) | 11.87:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[2] | rgb(30,41,59) | rgb(226,232,240) | 11.87:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[0] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 按钮 outline | `.sv-btn-outline`[1] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[2] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 表单控件 | `.sv-form-control`[0] | rgb(30,41,59) | rgb(241,245,249) | 13.35:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 表单控件 | `.sv-form-control`[1] | rgb(30,41,59) | rgb(241,245,249) | 13.35:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 表单控件 | `.sv-form-control`[2] | rgb(30,41,59) | rgb(241,245,249) | 13.35:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 徽章 completed | `.sv-badge-completed`[0] | rgb(21,128,61) | rgb(214,232,223) | 3.93:1 | 4.5:1 | ❌ | 11.52px | 600 |
| 徽章 completed | `.sv-badge-completed`[1] | rgb(21,128,61) | rgb(214,232,223) | 3.93:1 | 4.5:1 | ❌ | 11.52px | 600 |
| 徽章 completed | `.sv-badge-completed`[2] | rgb(21,128,61) | rgb(214,232,223) | 3.93:1 | 4.5:1 | ❌ | 11.52px | 600 |
| 状态栏 | `.sv-statusbar`[0] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12px | 400 |
| 面包屑当前 | `.sv-breadcrumb .current`[0] | rgb(30,41,59) | rgb(248,250,252) | 13.98:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 面包屑链接 | `.sv-breadcrumb a`[0] | rgb(71,85,105) | rgb(248,250,252) | 7.24:1 | 4.5:1 | ✅ | 12.8px | 400 |
| 表格内容 | `.sv-table tbody td`[0] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 表格内容 | `.sv-table tbody td`[1] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 表格内容 | `.sv-table tbody td`[2] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 分页按钮 | `.sv-pagination .page-btn`[0] | rgb(71,85,105) | rgb(241,245,249) | 6.92:1 | 4.5:1 | ✅ | 12.8px | 400 |
| 分页按钮 | `.sv-pagination .page-btn`[1] | rgb(71,85,105) | rgb(241,245,249) | 6.92:1 | 4.5:1 | ✅ | 12.8px | 400 |
| 分页信息 | `.sv-pagination .page-info`[0] | rgb(84,100,120) | rgb(255,255,255) | 6.05:1 | 4.5:1 | ✅ | 12.8px | 400 |

#### 系统状态

| 类别 | 选择器 | 文字颜色 | 背景颜色 | 对比度 | 阈值 | 合规 | 字号 | 字重 |
|------|--------|----------|----------|--------|------|------|------|------|
| 页面标题 h1 | `.sv-page-header h1, .sv-hero h1`[0] | rgb(30,41,59) | rgb(248,250,252) | 13.98:1 | 3:1 | ✅ | 25.6px | 700 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[0] | rgb(30,41,59) | rgb(255,255,255) | 14.63:1 | 3:1 | ✅ | 15.2px | 600 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[1] | rgb(30,41,59) | rgb(255,255,255) | 14.63:1 | 3:1 | ✅ | 15.2px | 600 |
| 区块标题 h2/h3 | `.sv-section-title, .sv-card-header h3, .sv-settings-section-title`[2] | rgb(30,41,59) | rgb(255,255,255) | 14.63:1 | 3:1 | ✅ | 15.2px | 600 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[0] | rgb(71,85,105) | rgb(248,250,252) | 7.24:1 | 4.5:1 | ✅ | 14.4px | 400 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[1] | rgb(30,41,59) | rgb(255,255,255) | 14.63:1 | 4.5:1 | ✅ | 13.6px | 600 |
| 正文文字 | `.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title`[2] | rgb(30,41,59) | rgb(255,255,255) | 14.63:1 | 4.5:1 | ✅ | 13.6px | 600 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[0] | rgb(84,100,120) | rgb(255,255,255) | 6.05:1 | 4.5:1 | ✅ | 12px | 600 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[1] | rgb(84,100,120) | rgb(255,255,255) | 6.05:1 | 4.5:1 | ✅ | 12px | 600 |
| 辅助文字 | `.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label`[2] | rgb(84,100,120) | rgb(255,255,255) | 6.05:1 | 4.5:1 | ✅ | 16px | 400 |
| 导航链接 | `.sv-nav-link`[0] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[1] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接 | `.sv-nav-link`[2] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 导航链接(活跃) | `.sv-nav-link.active`[0] | rgb(91,76,213) | rgb(229,229,247) | 4.91:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 primary | `.sv-btn-primary`[0] | rgb(255,255,255) | rgb(91,76,213) | 6.11:1 | 4.5:1 | ✅ | 12.48px | 500 |
| 按钮 primary | `.sv-btn-primary`[1] | rgb(255,255,255) | rgb(91,76,213) | 6.11:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 danger | `.sv-btn-danger`[0] | rgb(255,255,255) | rgb(220,38,38) | 4.83:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[0] | rgb(30,41,59) | rgb(226,232,240) | 11.87:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[1] | rgb(30,41,59) | rgb(226,232,240) | 11.87:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 secondary | `.sv-btn-secondary`[2] | rgb(30,41,59) | rgb(226,232,240) | 11.87:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[0] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 按钮 outline | `.sv-btn-outline`[1] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 按钮 outline | `.sv-btn-outline`[2] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 13.6px | 500 |
| 表单控件 | `.sv-form-control`[0] | rgb(30,41,59) | rgb(241,245,249) | 13.35:1 | 4.5:1 | ✅ | 13.6px | 400 |
| 徽章 completed | `.sv-badge-completed`[0] | rgb(21,128,61) | rgb(214,232,223) | 3.93:1 | 4.5:1 | ❌ | 11.52px | 600 |
| 徽章 secondary | `.sv-badge-secondary`[0] | rgb(71,85,105) | rgb(226,232,240) | 6.15:1 | 4.5:1 | ✅ | 11.52px | 600 |
| 状态栏 | `.sv-statusbar`[0] | rgb(71,85,105) | rgb(255,255,255) | 7.58:1 | 4.5:1 | ✅ | 12px | 400 |
| 面包屑当前 | `.sv-breadcrumb .current`[0] | rgb(30,41,59) | rgb(248,250,252) | 13.98:1 | 4.5:1 | ✅ | 12.8px | 500 |
| 面包屑链接 | `.sv-breadcrumb a`[0] | rgb(71,85,105) | rgb(248,250,252) | 7.24:1 | 4.5:1 | ✅ | 12.8px | 400 |

---

## 4. 合规标准说明

- **正常文字**（< 18px 且非粗体，或 < 14px 粗体）：对比度 ≥ **4.5:1**
- **大文字**（≥ 18px，或 ≥ 14px 粗体）：对比度 ≥ **3:1**
- 标题元素（h1/h2/h3）默认按大文字标准（3:1）判定


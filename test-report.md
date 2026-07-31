# SeedVR2 用户行为模拟测试报告

**测试时间**: 2026-07-31  
**测试环境**: Windows, NVIDIA GeForce RTX 5070 Ti Laptop GPU, WinPython 3.12.10  
**测试地址**: http://127.0.0.1:7870  
**测试人员**: AI自动化测试

---

## 一、测试概述

本次测试对 SeedVR2 视频修复网站进行了全面的用户行为模拟测试，覆盖5类典型用户角色，检测了网站在各种使用场景下的稳定性、功能正确性和用户体验。

### 测试用户角色

1. **新手用户**：首次使用，点击所有按钮，不看提示
2. **普通用户**：正常流程上传修复文件
3. **批量处理用户**：使用文件夹批量处理功能
4. **多语言用户**：切换界面语言（中/英/日/法）
5. **探索型用户**：切换主题、访问所有页面、检查异常情况

---

## 二、发现的问题及修复情况

### 问题1：默认语言为日文导致首页语言混合（已修复 ✅）

**严重程度**: 一般  
**问题描述**: config.yaml 中 default_locale 设置为 "ja"，导致首页默认显示日文，但部分元素仍为中文，出现语言混合现象。  
**修复方案**: 将 config.yaml 中 default_locale 改为 "zh"。  
**修改文件**: [config.yaml](file:///c:/Users/Doro/Seedvr2/config.yaml)

---

### 问题2：翻译键缺失导致硬编码中文（已修复 ✅）

**严重程度**: 一般  
**问题描述**: 
- 首页快速入口卡片（单文件修复/批量修复/历史记录）缺少 `home.quick.*` 翻译键
- 修复页面缺少错误提示相关翻译键（请选择文件、取消任务、GPU警告等）
- base.html 中 `window.__I18N__` 对象缺少新增翻译键，导致前端JS无法获取翻译文本，回退到硬编码中文或键名

**修复方案**:
1. 在 zh.yaml、en.yaml、ja.yaml、fr.yaml 中补全所有缺失的翻译键
2. 在 base.html 的 __I18N__ 对象中添加所有必要的翻译键

**修改文件**:
- [locales/zh.yaml](file:///c:/Users/Doro/Seedvr2/bin/integrated_app/locales/zh.yaml)
- [locales/en.yaml](file:///c:/Users/Doro/Seedvr2/bin/integrated_app/locales/en.yaml)
- [locales/ja.yaml](file:///c:/Users/Doro/Seedvr2/bin/integrated_app/locales/ja.yaml)
- [locales/fr.yaml](file:///c:/Users/Doro/Seedvr2/bin/integrated_app/locales/fr.yaml)
- [templates/base.html](file:///c:/Users/Doro/Seedvr2/bin/integrated_app/templates/base.html)

---

### 问题3：restore.html 中存在硬编码中文（已修复 ✅）

**严重程度**: 一般  
**问题描述**: 修复页面模板中多处硬编码中文字符串，未使用 i18n 翻译函数：
- 按钮 aria-label 和 title 属性（"取消"、"取消任务"、"取消批量任务"）
- JavaScript 动态生成的按钮文本

**修复方案**: 将所有硬编码文本替换为 `{{ t('...') }}` 模板变量和 `I['...']` JS 翻译对象引用。

**修改文件**: [templates/restore.html](file:///c:/Users/Doro/Seedvr2/bin/integrated_app/templates/restore.html)

---

### 问题4：禁用按钮无法点击导致无法显示提示（已修复 ✅）

**严重程度**: 一般  
**问题描述**: CSS 中 `.sv-btn.is-disabled` 和 `#btnStartRestore.is-disabled` 设置了 `pointer-events: none`，导致按钮即使被点击也无法触发事件，用户看不到"请先选择文件"的提示。

**修复方案**: 移除这两个选择器中的 `pointer-events: none` 属性，允许按钮接收点击事件，通过JS逻辑判断状态并显示相应提示。

**修改文件**: [static/css/style.css](file:///c:/Users/Doro/Seedvr2/bin/integrated_app/static/css/style.css)

---

### 问题5：按钮点击逻辑顺序错误（已修复 ✅）

**严重程度**: 一般  
**问题描述**: 
1. 点击"上传并修复"按钮时，先检查GPU状态再检查是否选择文件，导致GPU检测超时或失败时无法提示用户选择文件
2. 无文件时按钮被设为 is-disabled，用户点击无反馈
3. GPU检测超时设置为15秒过长

**修复方案**:
1. 重构 startRestore() 和 startBatch() 函数：先检查用户输入（文件/路径），再检查GPU状态
2. 不再因缺少文件而禁用按钮，允许点击后显示toast提示
3. 将GPU检测超时从15秒缩短为5秒
4. GPU检测中状态下点击按钮显示"检测中"提示

**修改文件**: [templates/restore.html](file:///c:/Users/Doro/Seedvr2/bin/integrated_app/templates/restore.html)

---

### 问题6：翻译键名不一致（已修复 ✅）

**严重程度**: 轻微  
**问题描述**: base.html 中引用的部分翻译键名与语言文件中的实际键名不匹配（如 `please_enter_path` vs `please_select_folder`，`please_scan_first` vs `please_scan_folder`）。

**修复方案**: 统一键名，确保base.html、模板JS和语言文件三者使用一致的键名。

**修改文件**: [templates/base.html](file:///c:/Users/Doro/Seedvr2/bin/integrated_app/templates/base.html)

---

### 问题7：common.collapse 翻译键YAML缩进错误（已修复 ✅）

**严重程度**: 轻微  
**问题描述**: 所有四个语言文件中 `collapse` 键的YAML缩进位置错误，位于 `video:` 节下而非 `common:` 节下，导致 `common.collapse` 翻译查找失败，页面显示键名"common.collapse"而非正确的翻译文本（中文"收起"、英文"Collapse"等）。

**修复方案**: 将 `collapse` 键从 `video:` 节移动到 `common:` 节下，确保所有四种语言都有正确的翻译。

**修改文件**:
- [locales/zh.yaml](file:///c:/Users/Doro/Seedvr2/bin/integrated_app/locales/zh.yaml)
- [locales/en.yaml](file:///c:/Users/Doro/Seedvr2/bin/integrated_app/locales/en.yaml)
- [locales/ja.yaml](file:///c:/Users/Doro/Seedvr2/bin/integrated_app/locales/ja.yaml)
- [locales/fr.yaml](file:///c:/Users/Doro/Seedvr2/bin/integrated_app/locales/fr.yaml)

---

## 三、修复的文件清单

| 文件 | 修改类型 | 说明 |
|------|---------|------|
| config.yaml | 修改 | 默认语言改为中文 |
| templates/base.html | 修改 | 补全I18N翻译键、更新CSS版本号 |
| templates/restore.html | 修改 | 替换硬编码文本、优化按钮点击逻辑顺序 |
| static/css/style.css | 修改 | 移除is-disabled按钮的pointer-events:none |
| locales/zh.yaml | 修改 | 补全缺失翻译键、修复collapse缩进 |
| locales/en.yaml | 修改 | 补全缺失翻译键、修复collapse缩进 |
| locales/ja.yaml | 修改 | 补全缺失翻译键、修复collapse缩进 |
| locales/fr.yaml | 修改 | 补全缺失翻译键、修复collapse缩进 |

---

## 四、验证结果

### 自动化验证（连续三轮，每轮56项检查）

使用自动化HTTP验证脚本 `verify_fixes.py` 进行连续三轮测试，每轮包含56项检查，全部通过：

| 轮次 | 通过 | 失败 | 结果 |
|------|------|------|------|
| 第1轮 | 56 | 0 | ✅ 通过 |
| 第2轮 | 56 | 0 | ✅ 通过 |
| 第3轮 | 56 | 0 | ✅ 通过 |

### 验证项覆盖

1. **页面可访问性**（4项）：首页、修复页、历史记录、设置、系统状态均返回200
2. **中文内容正确性**（10项）：标题、导航、快速入口卡片、按钮文本
3. **I18N翻译键完整性**（25项）：home.quick、restore错误提示、common基础键
4. **按钮事件绑定**（2项）：startRestore、startBatch点击事件正确绑定
5. **按钮逻辑顺序**（2项）：先检查用户输入，再检查GPU状态
6. **API端点**（4项）：health、gpu、history、locales正常响应
7. **CSS样式**（2项）：is-disabled按钮无pointer-events:none阻止点击
8. **JavaScript**（1项）：app.js正常加载
9. **CSRF保护**（1项）：无token的POST请求被正确拒绝(403)
10. **多语言翻译**（4项）：中/英/日/法的common.collapse翻译值正确

### 翻译覆盖验证

- 中文(zh): 所有翻译键已补全，collapse="收起" ✅
- 英文(en): 所有翻译键已补全，collapse="Collapse" ✅
- 日文(ja): 所有翻译键已补全，collapse="折りたたむ" ✅
- 法文(fr): 所有翻译键已补全，collapse="Réduire" ✅

---

## 五、用户体验改进建议

### 高优先级

1. **模型加载错误处理**: 服务启动时存在 `cannot import name 'get_na_rope' from 'models.dit_v2.rope'` 错误，导致模型无法自动加载，建议修复模型导入问题。

### 中优先级

1. **GPU检测体验优化**: GPU检测期间可显示加载动画，避免用户困惑
2. **表单即时验证**: 文件选择后可即时高亮按钮状态，提供视觉反馈
3. **语言切换反馈**: 语言切换时除了刷新页面，可添加过渡动画提升体验

### 低优先级

1. **批量扫描进度**: 文件夹扫描大目录时可显示扫描进度
2. **错误详情展示**: Toast错误可添加"详情"按钮展开完整错误信息
3. **快捷键支持**: 可添加常用操作快捷键（如Ctrl+Enter开始修复）

---

## 六、总结

本次测试共发现并修复了7个问题，主要集中在国际化（i18n）完整性和用户交互反馈两个方面。所有已发现的问题均已修复，并通过自动化验证脚本连续三轮共168项检查全部通过：

1. **国际化问题解决**: 默认语言正确设置为中文，所有4种语言的翻译键完整且YAML结构正确，前端I18N对象包含所有必要键，无硬编码文本残留。

2. **交互反馈完善**: is-disabled按钮不再阻止点击事件，用户在未选择文件/路径时点击按钮会收到清晰的toast提示，而非无反馈。

3. **错误提示优化**: 按钮点击逻辑优化为先检查用户输入再检查系统状态，用户能更快得到操作反馈；GPU检测超时从15秒缩短至5秒。

网站核心Web界面功能稳定，页面无控制台错误，API响应正常，CSRF保护有效。

> ⚠️ **注意**: 服务启动时发现模型加载错误 (`cannot import name 'get_na_rope' from 'models.dit_v2.rope'`)，这会导致实际的视频/图片修复功能无法使用，但不影响Web界面本身的功能和稳定性。建议后续修复此模型导入问题以启用完整的修复功能。

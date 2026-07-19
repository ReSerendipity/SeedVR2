# SeedVR2 缺陷报告模板

> 使用说明：复制本模板填写具体缺陷信息，文件命名格式为 `BUG-XXXX-简短描述.md`（如 `BUG-0001-cors-misconfig.md`）。

---

## 缺陷信息

| 字段 | 内容 |
|------|------|
| **Bug ID** | BUG-[XXXX] |
| **标题** | [简要描述缺陷] |
| **优先级 (Priority)** | [P0 / P1 / P2 / P3] |
| **严重程度 (Severity)** | [Critical / Major / Minor / Trivial] |
| **状态 (Status)** | [New / Confirmed / Fixed / Verified / Closed] |
| **指派给 (Assignee)** | [开发者姓名] |
| **报告人 (Reporter)** | [报告人姓名] |
| **报告日期 (Date)** | [YYYY-MM-DD] |
| **关联测试用例 ID** | [TC-XXXX] |

### 优先级定义

| 等级 | 含义 |
|------|------|
| **P0** | 紧急 — 系统崩溃、数据丢失、安全漏洞，必须立即修复 |
| **P1** | 高 — 核心功能不可用，影响主要业务流程 |
| **P2** | 中 — 功能受限或有明显缺陷，存在替代方案 |
| **P3** | 低 — 界面瑕疵、文案错误、体验优化建议 |

### 严重程度定义

| 等级 | 含义 |
|------|------|
| **Critical** | 系统崩溃、数据损坏、安全漏洞 |
| **Major** | 核心功能失效，无替代方案 |
| **Minor** | 功能受限，有替代方案 |
| **Trivial** | 界面/文案问题，不影响功能 |

---

## 环境

| 项目 | 值 |
|------|-----|
| **操作系统 (OS)** | [如：Windows 11 23H2] |
| **浏览器 (Browser)** | [如：Chrome 126.0] |
| **应用版本 (Version)** | [如：v1.2.0] |
| **访问地址 (URL)** | [如：http://localhost:7860/video-restore] |
| **Python 版本** | [如：3.12.1] |
| **Node 版本** | [如：20.11.0] |

---

## 前置条件 (Preconditions)

1. [前置条件 1，如：已启动 SeedVR2 WebUI 服务]
2. [前置条件 2，如：已配置模型路径]
3. [……]

---

## 复现步骤 (Reproduction Steps)

1. [步骤 1，如：打开浏览器访问 http://localhost:7860]
2. [步骤 2，如：点击侧边栏 "视频修复" 导航项]
3. [步骤 3，如：上传测试视频文件]
4. [步骤 4，如：点击 "开始修复" 按钮]
5. [……]

---

## 预期结果 (Expected Result)

[描述预期行为，如：修复任务应正常提交并显示进度条]

---

## 实际结果 (Actual Result)

[描述实际行为，如：页面弹出 alert 对话框，显示注入的脚本内容]

---

## 错误日志 / 控制台输出 (Error Logs / Console Output)

```
[粘贴浏览器控制台错误、网络请求错误、服务端日志等]
```

---

## 截图 / 视频 (Screenshots / Video)

| 类型 | 文件 |
|------|------|
| 截图 | [截图文件路径或占位图，如：`./screenshots/BUG-0001-01.png`] |
| 录屏 | [录屏文件路径或链接，如：`./videos/BUG-0001-repro.mp4`] |

---

## 临时解决方案 (Workaround)

[如有临时规避方法请填写，如：手动在浏览器控制台执行 `document.cookie` 前检查域名；若无则填写"无"]

---

## 备注 (Notes)

[其他补充信息，如：关联缺陷、讨论链接、影响范围等]

---

---

# 示例缺陷报告

---

## 示例 1：CORS 配置错误导致跨域请求失败

| 字段 | 内容 |
|------|------|
| **Bug ID** | BUG-0001 |
| **标题** | API 跨域请求被浏览器拦截 — CORS 配置未正确设置 Access-Control-Allow-Origin |
| **优先级 (Priority)** | P1 |
| **严重程度 (Severity)** | Major |
| **状态 (Status)** | Confirmed |
| **指派给 (Assignee)** | [待分配] |
| **报告人 (Reporter)** | 张三 |
| **报告日期 (Date)** | 2026-06-15 |
| **关联测试用例 ID** | TC-SEC-005 |

### 环境

| 项目 | 值 |
|------|-----|
| **操作系统 (OS)** | Windows 11 23H2 |
| **浏览器 (Browser)** | Chrome 126.0.6478.127 |
| **应用版本 (Version)** | v1.0.0 |
| **访问地址 (URL)** | http://localhost:7860/video-restore |
| **Python 版本** | 3.12.1 |
| **Node 版本** | 20.11.0 |

### 前置条件

1. SeedVR2 WebUI 服务已启动（默认端口 7860）
2. 前端页面与后端 API 部署在不同端口或域名下（如前端 3000，后端 7860）

### 复现步骤

1. 在 3000 端口启动前端开发服务器
2. 在 7860 端口启动后端 API 服务
3. 打开浏览器访问 `http://localhost:3000`
4. 点击侧边栏 "视频修复" 导航项
5. 上传测试视频文件并点击 "开始修复"

### 预期结果

前端应成功向后端 API 发起跨域 POST 请求，视频修复任务正常提交并返回任务 ID。

### 实际结果

浏览器控制台报 CORS 错误，请求被拦截，前端页面显示网络错误提示。视频修复功能完全不可用。

### 错误日志 / 控制台输出

```
Access to XMLHttpRequest at 'http://localhost:7860/api/restore/video'
from origin 'http://localhost:3000' has been blocked by CORS policy:
Response to preflight request doesn't pass access control check:
No 'Access-Control-Allow-Origin' header is present on the requested resource.
```

### 截图 / 视频

| 类型 | 文件 |
|------|------|
| 截图 | `./screenshots/BUG-0001-cors-error.png` |
| 录屏 | — |

### 临时解决方案

在后端 FastAPI 应用中添加 `CORSMiddleware` 中间件：

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 备注

生产环境应将 `allow_origins` 限制为实际域名，不应使用 `["*"]`。此问题在前后端同源部署时不出现，仅在开发环境或跨域部署时触发。

---

## 示例 2：innerHTML 使用导致 XSS 风险

| 字段 | 内容 |
|------|------|
| **Bug ID** | BUG-0002 |
| **标题** | 目录浏览器使用 innerHTML 渲染文件名，存在 XSS 注入风险 |
| **优先级 (Priority)** | P0 |
| **严重程度 (Severity)** | Critical |
| **状态 (Status)** | New |
| **指派给 (Assignee)** | [待分配] |
| **报告人 (Reporter)** | 李四 |
| **报告日期 (Date)** | 2026-06-15 |
| **关联测试用例 ID** | TC-SEC-002 |

### 环境

| 项目 | 值 |
|------|-----|
| **操作系统 (OS)** | Windows 11 23H2 |
| **浏览器 (Browser)** | Chrome 126.0.6478.127 |
| **应用版本 (Version)** | v1.0.0 |
| **访问地址 (URL)** | http://localhost:7860/video-restore |
| **Python 版本** | 3.12.1 |
| **Node 版本** | 20.11.0 |

### 前置条件

1. SeedVR2 WebUI 服务已启动
2. 后端 `/api/system/browse-dir` 接口可返回包含特殊字符的文件名

### 复现步骤

1. 打开浏览器访问 `http://localhost:7860/video-restore`
2. 点击 "选择文件夹" 按钮触发目录浏览器
3. 后端返回包含恶意文件名的目录列表，如文件名为 `<img src=x onerror=alert("xss-dir")>`
4. 前端使用 `innerHTML` 将文件名渲染到页面 DOM 中

### 预期结果

文件名应以纯文本形式显示，HTML 标签应被转义（如 `&lt;img src=x onerror=alert("xss-dir")&gt;`），不应被执行。

### 实际结果

`innerHTML` 将恶意 HTML 标签直接插入 DOM，`onerror` 事件处理器被触发，执行了注入的 JavaScript 代码。浏览器弹出 `alert` 对话框。

### 错误日志 / 控制台输出

```javascript
// 前端代码中的问题代码示例
entryList.innerHTML += `<div class="entry">${entry.name}</div>`;
// entry.name 包含 <img src=x onerror=alert("xss-dir")>
// 导致 onerror 脚本被执行
```

### 截图 / 视频

| 类型 | 文件 |
|------|------|
| 截图 | `./screenshots/BUG-0002-xss-alert.png` |
| 录屏 | `./videos/BUG-0002-xss-repro.mp4` |

### 临时解决方案

将 `innerHTML` 替换为 `textContent` 或使用 DOM API 创建元素：

```javascript
// 修复方案 1：使用 textContent
const div = document.createElement('div');
div.className = 'entry';
div.textContent = entry.name;  // 自动转义 HTML
entryList.appendChild(div);

// 修复方案 2：使用模板转义函数
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
entryList.innerHTML += `<div class="entry">${escapeHtml(entry.name)}</div>`;
```

### 备注

此缺陷影响范围包括目录浏览器、文件信息展示、Toast 通知等所有使用 `innerHTML` 渲染用户可控内容的场景。建议全局搜索 `innerHTML` 用法并逐一审查。关联安全测试用例：`security.spec.ts` 中的 XSS Prevention 测试套件。

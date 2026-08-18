# tests/frontend — 前端冒烟测试（jsdom）

## 是什么

SeedVR2 前端由 FastAPI + Jinja2 单端口直出（`app/integrated_app/templates/`），
本目录提供一套**不依赖真实后端**的结构冒烟测试：

1. `scripts/render_pages.py`（仓库根 `scripts/` 下）
   用与 `app_server.render_page` 相同的 I18n + Jinja2 环境，
   把 4 个关键页面（restore / index / history / settings）渲染为静态 HTML，
   输出到本目录 `_rendered/`。

2. `smoke.js`
   用 jsdom 解析渲染产物，做结构断言（~30 条），覆盖：
   - 无残留 Jinja2 语法（`{{ }}` / `{% %}`）
   - restore 工作台核心 id 契约（SOP-6：`#paramsSidebar`、`#canvasToolbar`、
     `#previewArea`、`#compareHud`、`#advParams` 等）
   - 全部参数字段 `[name]` 留在 `#paramsSidebar` 内（`collectParams` 依赖）
   - CSP 含 `media-src blob:`（AGENTS.md 陷阱 #7）、字体异步加载（陷阱 #13）
   - i18n 注入 `window.__I18N__` / `window.__LOCALE__` 且翻译已展开
   - 跨页面导航互链、html[lang]/data-theme 一致

## 运行

```bash
# 1. 渲染页面（依赖 jinja2，应用环境已具备）
python scripts/render_pages.py

# 2. 安装 jsdom（已在 tests/package.json 声明为 devDependency，与 Playwright 共存）
cd tests && npm install

# 3. 运行冒烟
cd tests && npm run test:frontend
# 或直接: node smoke.js
```

`node smoke.js` 在 jsdom 未安装时会输出安装提示并退出（exit 2）；
渲染产物缺失时提示先跑 `scripts/render_pages.py`。

## 语法检查（无需安装依赖）

```bash
node --check smoke.js
```

## 与 Playwright E2E 的关系

- `tests/` 根目录的 Playwright（`playwright.config.ts`、`*.spec.ts`）负责
  **真实浏览器**端到端 + 视觉回归，需要启动真实服务。
- 本目录的 jsdom 冒烟只做**静态结构断言**，秒级完成，适合 CI 快速门禁。
- 两者共用 `tests/package.json`；jsdom 仅增加一个 devDependency，
  不影响 Playwright 依赖树（Playwright 自带浏览器下载）。

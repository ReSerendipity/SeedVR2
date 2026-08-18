// SeedVR2 前端冒烟测试（Jinja2 渲染产物结构校验）
// 运行：先 `python scripts/render_pages.py` 生成渲染产物，
//       再 `npm install`（安装 jsdom）后执行 `node smoke.js`。
// 模拟静态渲染产物，不依赖真实后端服务；断言失败 exit 1。
//
// 断言覆盖（按 SOP-6 ID 契约 + 历史陷阱）：
//   1. 渲染产物无残留 Jinja2 语法
//   2. restore.html 工作台核心 id 齐全（paramsSidebar/canvasToolbar/previewArea/compareHud…）
//   3. 全部参数字段（[name]）必须留在 #paramsSidebar 内（ID 契约）
//   4. 模式分段（sv-mode-tab single/batch）与批量工具条
//   5. CSP 含 media-src blob:（陷阱 #7）与字体异步加载（陷阱 #13）
//   6. i18n 注入脚本 window.__I18N__ 与主题初始化（data-theme）
//   7. 跨页面 html[lang]/data-theme 一致、导航互链
const fs = require('fs');
const path = require('path');

let JSDOM;
try {
  ({ JSDOM } = require('jsdom'));
} catch (e) {
  console.error('jsdom 未安装。请执行: npm install（package.json 已声明 jsdom devDependency）');
  process.exit(2);
}

const RENDERED = path.join(__dirname, '_rendered');
const PAGES = ['restore', 'index', 'history', 'settings'];

function load(page) {
  const file = path.join(RENDERED, page + '.html');
  if (!fs.existsSync(file)) {
    throw new Error(`渲染产物缺失: ${file}。请先运行 python scripts/render_pages.py`);
  }
  const html = fs.readFileSync(file, 'utf-8');
  // 只解析 DOM 结构，不执行内联脚本（页面内联 JS 依赖真实后端/浏览器 API）
  const dom = new JSDOM(html, { runScripts: 'outside-only', pretendToBeVisual: true, url: 'http://localhost/' });
  return { dom, html };
}

let pass = 0;
let fail = 0;
function assert(c, m) {
  if (c) { pass++; console.log('  ok - ' + m); } else { fail++; console.log('  FAIL - ' + m); }
}
function $(d, sel) { return d.querySelector(sel); }
function $$(d, sel) { return [...d.querySelectorAll(sel)]; }

/* ============ 全页面：无 Jinja 残留 + html 属性 ============ */
console.log('[all-pages]');
{
  for (const page of PAGES) {
    const { dom, html } = load(page);
    const d = dom.window.document;
    assert(!/{{\s*[\w.]+\s*}}/.test(html) && !/{%\s*/.test(html), `${page}: 无残留 Jinja2 语法`);
    assert(d.documentElement.getAttribute('lang') === 'zh', `${page}: <html lang="zh">`);
    assert(d.documentElement.hasAttribute('data-theme'), `${page}: <html data-theme> 存在`);
    assert(d.querySelector('title') && d.querySelector('title').textContent.trim().length > 0, `${page}: <title> 非空`);
  }
}

/* ============ restore.html：工作台核心结构（SOP-6 ID 契约） ============ */
console.log('[restore]');
{
  const { dom, html } = load('restore');
  const d = dom.window.document;

  assert(d.title.includes('SeedVR2'), '标题含 SeedVR2');

  // 工作台骨架
  assert($(d, '#paramsSidebar'), '#paramsSidebar 存在（参数侧栏）');
  assert($(d, '#sv2Body'), '#sv2Body 存在（工作台主体）');
  assert($(d, '#canvasToolbar'), '#canvasToolbar 存在（一体化画布工具条）');
  assert($(d, '#previewArea'), '#previewArea 存在（画布舞台）');
  assert($(d, '#batchToolbar'), '#batchToolbar 存在（批量工具条）');
  assert($(d, '#compareHud'), '#compareHud 存在（对比 HUD）');
  assert($(d, '#btnStartRestore'), '#btnStartRestore 存在（开始修复按钮）');
  assert($(d, '#btnStartBatch'), '#btnStartBatch 存在（批量开始按钮）');
  assert($(d, '#restoreUploadZone'), '#restoreUploadZone 存在（上传区）');
  assert($(d, '#advParams'), '#advParams 存在（高级参数区）');

  // 模式分段
  const tabs = $$(d, '.sv-mode-tab');
  assert(tabs.length === 2, `模式分段 2 个 tab（实际 ${tabs.length}）`);
  assert(tabs.some(t => t.dataset.mode === 'single') && tabs.some(t => t.dataset.mode === 'batch'), 'single/batch 两种模式');
  assert(tabs.some(t => t.classList.contains('active')), '默认模式 tab 高亮');

  // 隐藏参数字段留在侧栏（collectParams 契约）
  const hiddenNames = ['seed', 'attention_mode', 'dit_cache_model', 'vae_cache_model', 'temporal_overlap', 'prepend_frames', 'input_noise_scale', 'latent_noise_scale', 'dit_device', 'offload_device'];
  const inSidebar = $$(d, '#paramsSidebar [name]').map(i => i.getAttribute('name'));
  for (const n of hiddenNames) {
    assert(inSidebar.includes(n), `隐藏参数字段 ${n} 在 #paramsSidebar 内`);
  }
}

/* ============ restore.html：CSP 与字体异步加载（陷阱 #7/#13） ============ */
console.log('[restore-csp]');
{
  const { dom, html } = load('restore');
  const d = dom.window.document;

  const cspEl = $(d, 'meta[http-equiv="Content-Security-Policy"]');
  const csp = cspEl ? cspEl.getAttribute('content') : '';
  assert(/media-src[^;]*blob:/.test(csp), `CSP 含 media-src blob:（陷阱 #7，实际: ${csp.slice(0, 120)}…）`);
  assert(/img-src[^;]*blob:/.test(csp), 'CSP 含 img-src blob:');

  const fontLinks = $$(d, 'link[href*="fonts.googleapis.com"]');
  assert(fontLinks.length >= 1, '存在 Google Fonts 链接');
  assert(fontLinks.every(l => l.getAttribute('media') === 'print' && l.getAttribute('onload')), '字体样式表异步加载（media="print" onload，陷阱 #13）');

  // 主题初始化脚本
  const themeScript = $$(d, 'script').find(s => s.textContent.includes('sv-theme'));
  assert(!!themeScript, '主题初始化脚本存在（data-theme 防闪烁）');
}

/* ============ restore.html：i18n 注入 ============ */
console.log('[restore-i18n]');
{
  const { dom, html } = load('restore');
  const d = dom.window.document;

  assert(html.includes('window.__I18N__'), 'window.__I18N__ 注入存在');
  assert(html.includes('window.__LOCALE__'), 'window.__LOCALE__ 注入存在');
  const localeMatch = html.match(/window\.__LOCALE__ = "([a-zA-Z-]+)"/);
  assert(!!localeMatch && localeMatch[1] === 'zh', `__LOCALE__ 为 zh（实际 ${localeMatch && localeMatch[1]}）`);
  // 翻译必须已展开（无未翻译的英文 key 裸串）
  assert(!/\{\{\s*t\(['"]/.test(html), '翻译函数调用已展开（无未渲染 t() 调用）');
}

/* ============ index.html：首页导航互链 ============ */
console.log('[index]');
{
  const { dom, html } = load('index');
  const d = dom.window.document;

  const links = $$(d, 'a[href]').map(a => a.getAttribute('href'));
  assert(links.includes('/restore') || links.some(l => l.startsWith('/restore')), '首页导航含 /restore');
  assert(links.some(l => l.includes('/settings')), '首页导航含 /settings');
  assert(links.some(l => l.includes('/history')), '首页导航含 /history');
}

/* ============ history.html：历史页结构 ============ */
console.log('[history]');
{
  const { dom, html } = load('history');
  const d = dom.window.document;

  assert(!!$(d, '#btnRefresh') || html.includes('btnRefresh'), '历史页含 #btnRefresh');
  assert(html.includes('htmx') || $(d, '[hx-get]') || $(d, '[hx-on]'), '历史页含 HTMX 声明（hx-get/hx-on）');
  assert(!!$(d, 'table') || html.includes('<table'), '历史页含表格结构');
}

/* ============ settings.html：设置页结构 ============ */
console.log('[settings]');
{
  const { dom, html } = load('settings');
  const d = dom.window.document;

  const inputs = $$(d, 'input, select');
  assert(inputs.length >= 3, `设置页含 ≥3 个 input/select（实际 ${inputs.length}）`);
  const forms = $$(d, 'form');
  assert(forms.length >= 1, '设置页含表单');
  assert(html.includes('sv-theme') || html.includes('theme'), '设置页含主题相关标记');
}

console.log(`\nRESULT: pass=${pass} fail=${fail}`);
process.exit(fail ? 1 : 0);

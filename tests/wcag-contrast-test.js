/**
 * WCAG 2.1 AA 对比度自动化测试
 * 使用 Playwright 测试 SeedVR2 所有页面的 Dark/Light 主题对比度合规性
 */

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

// ===== 配置 =====
const BASE_URL = 'http://127.0.0.1:7870';
const PAGES = [
  { name: '首页', path: '/' },
  { name: '视频修复', path: '/video-restore' },
  { name: '图像修复', path: '/image-restore' },
  { name: '设置', path: '/settings' },
  { name: '历史记录', path: '/history' },
  { name: '系统状态', path: '/system-status' },
];

const THEMES = ['dark', 'light'];

// 元素选择器定义
const ELEMENT_SELECTORS = [
  // 页面标题 h1
  { selector: '.sv-page-header h1, .sv-hero h1', category: '页面标题 h1', type: 'heading' },
  // 区块标题 h2/h3
  { selector: '.sv-section-title, .sv-card-header h3, .sv-settings-section-title', category: '区块标题 h2/h3', type: 'heading' },
  // 正文文字
  { selector: '.sv-page-header p, .sv-hero p, .sv-stat-item .stat-value, .sv-overview-item .item-value, .sv-quick-card h3, .sv-card-body p, .sv-workflow-node .node-header .node-title', category: '正文文字', type: 'normal' },
  // 辅助文字
  { selector: '.sv-text-muted, .sv-form-hint, .sv-upload-zone .upload-hint, .sv-param-section-title, .sv-workflow-node .node-header .node-type, .sv-table thead th, .sv-overview-item .item-label', category: '辅助文字', type: 'small' },
  // 导航链接
  { selector: '.sv-nav-link', category: '导航链接', type: 'normal' },
  // 导航链接 - 活跃
  { selector: '.sv-nav-link.active', category: '导航链接(活跃)', type: 'normal' },
  // 按钮文字 - primary
  { selector: '.sv-btn-primary', category: '按钮 primary', type: 'normal' },
  // 按钮文字 - success
  { selector: '.sv-btn-success', category: '按钮 success', type: 'normal' },
  // 按钮文字 - danger
  { selector: '.sv-btn-danger', category: '按钮 danger', type: 'normal' },
  // 按钮文字 - secondary
  { selector: '.sv-btn-secondary', category: '按钮 secondary', type: 'normal' },
  // 按钮文字 - outline
  { selector: '.sv-btn-outline', category: '按钮 outline', type: 'normal' },
  // 按钮文字 - warning
  { selector: '.sv-btn-warning', category: '按钮 warning', type: 'normal' },
  // 表单标签
  { selector: '.sv-form-label, .sv-range-header label', category: '表单标签', type: 'small' },
  // 表单控件文字
  { selector: '.sv-form-control', category: '表单控件', type: 'normal' },
  // 徽章文字
  { selector: '.sv-badge-pending', category: '徽章 pending', type: 'small' },
  { selector: '.sv-badge-processing', category: '徽章 processing', type: 'small' },
  { selector: '.sv-badge-completed', category: '徽章 completed', type: 'small' },
  { selector: '.sv-badge-failed', category: '徽章 failed', type: 'small' },
  { selector: '.sv-badge-primary', category: '徽章 primary', type: 'small' },
  { selector: '.sv-badge-secondary', category: '徽章 secondary', type: 'small' },
  // 状态栏文字
  { selector: '.sv-statusbar', category: '状态栏', type: 'small' },
  // 面包屑
  { selector: '.sv-breadcrumb .current', category: '面包屑当前', type: 'small' },
  { selector: '.sv-breadcrumb a', category: '面包屑链接', type: 'small' },
  // 表格内容
  { selector: '.sv-table tbody td', category: '表格内容', type: 'normal' },
  // 开关标签
  { selector: '.sv-form-switch .switch-label', category: '开关标签', type: 'normal' },
  // 上传区域标题
  { selector: '.sv-upload-zone .upload-title', category: '上传区域标题', type: 'normal' },
  // 分页
  { selector: '.sv-pagination .page-btn', category: '分页按钮', type: 'small' },
  { selector: '.sv-pagination .page-info', category: '分页信息', type: 'small' },
  // 设置导航
  { selector: '.sv-settings-nav .nav-item', category: '设置导航', type: 'normal' },
  // 输入模式标签
  { selector: '.sv-input-mode-tab', category: '输入模式标签', type: 'small' },
  // Toast 文字
  { selector: '.sv-toast', category: 'Toast 通知', type: 'normal' },
];

// ===== 对比度计算 =====
function luminance(r, g, b) {
  const [rs, gs, bs] = [r, g, b].map(c => {
    c = c / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * rs + 0.7152 * gs + 0.0722 * bs;
}

function contrastRatio(color1, color2) {
  const l1 = luminance(...color1);
  const l2 = luminance(...color2);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

function parseColor(colorStr) {
  if (!colorStr || colorStr === 'transparent' || colorStr === 'rgba(0, 0, 0, 0)') return null;

  // 处理 rgb/rgba
  const rgbaMatch = colorStr.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+))?\)/);
  if (rgbaMatch) {
    const r = parseInt(rgbaMatch[1]);
    const g = parseInt(rgbaMatch[2]);
    const b = parseInt(rgbaMatch[3]);
    const a = rgbaMatch[4] !== undefined ? parseFloat(rgbaMatch[4]) : 1.0;
    return { r, g, b, a };
  }

  // 处理 hex
  const hexMatch = colorStr.match(/#([0-9a-fA-F]{3,8})/);
  if (hexMatch) {
    let hex = hexMatch[1];
    if (hex.length === 3) hex = hex[0]+hex[0]+hex[1]+hex[1]+hex[2]+hex[2];
    if (hex.length >= 6) {
      const r = parseInt(hex.slice(0,2), 16);
      const g = parseInt(hex.slice(2,4), 16);
      const b = parseInt(hex.slice(4,6), 16);
      const a = hex.length >= 8 ? parseInt(hex.slice(6,8), 16) / 255 : 1.0;
      return { r, g, b, a };
    }
  }

  return null;
}

// 将半透明颜色与背景色混合，得到最终不透明颜色
function blendColors(fg, bg) {
  if (!fg || !bg) return null;
  const a = fg.a !== undefined ? fg.a : 1.0;
  const bgA = bg.a !== undefined ? bg.a : 1.0;
  // 简单 alpha 混合
  const outA = a + bgA * (1 - a);
  if (outA === 0) return [0, 0, 0];
  const r = Math.round((fg.r * a + bg.r * bgA * (1 - a)) / outA);
  const g = Math.round((fg.g * a + bg.g * bgA * (1 - a)) / outA);
  const b = Math.round((fg.b * a + bg.b * bgA * (1 - a)) / outA);
  return [r, g, b];
}

// 判断是否为大文字
function isLargeText(fontSize, fontWeight) {
  const size = parseFloat(fontSize);
  const weight = parseInt(fontWeight) || 400;
  // 大文字：≥ 18px 或 ≥ 14px 粗体
  return size >= 18 || (size >= 14 && weight >= 700);
}

// 获取合规阈值
function getThreshold(type, fontSize, fontWeight) {
  if (type === 'heading') return 3.0; // 标题通常是大文字
  if (isLargeText(fontSize, fontWeight)) return 3.0;
  return 4.5;
}

// ===== 主测试逻辑 =====
async function runTests() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  const results = [];
  const errors = [];

  // 预热：先加载一次首页确保服务就绪
  console.log('预热：加载首页...');
  try {
    await page.goto(`${BASE_URL}/`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(2000);
    console.log('预热完成');
  } catch (e) {
    console.log(`预热失败: ${e.message}，继续测试...`);
  }

  for (const theme of THEMES) {
    console.log(`\n${'='.repeat(60)}`);
    console.log(`测试主题: ${theme.toUpperCase()}`);
    console.log(`${'='.repeat(60)}`);

    for (const pageInfo of PAGES) {
      console.log(`\n--- 页面: ${pageInfo.name} (${pageInfo.path}) ---`);

      try {
        await page.goto(`${BASE_URL}${pageInfo.path}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
        // 等待主要内容渲染完成
        await page.waitForSelector('.sv-navbar, .sv-main', { timeout: 10000 }).catch(() => {});
        await page.waitForTimeout(1000);

        // 切换主题
        await page.evaluate((t) => {
          document.documentElement.setAttribute('data-theme', t);
          localStorage.setItem('sv-theme', t);
        }, theme);
        await page.waitForTimeout(300);

        // 确认主题已应用
        const currentTheme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
        if (currentTheme !== theme) {
          console.log(`  ⚠ 主题切换失败，当前: ${currentTheme}，期望: ${theme}`);
        }

        for (const elemDef of ELEMENT_SELECTORS) {
          const elements = await page.$$(elemDef.selector);
          if (elements.length === 0) continue;

          // 最多取前 3 个元素（避免重复数据）
          const sampleElements = elements.slice(0, 3);

          for (let i = 0; i < sampleElements.length; i++) {
            const el = sampleElements[i];
            try {
              // 在浏览器端获取完整的颜色信息，包括背景色堆栈
              const styleData = await el.evaluate((node) => {
                const computed = window.getComputedStyle(node);
                const result = {
                  color: computed.color,
                  backgroundColor: computed.backgroundColor,
                  fontSize: computed.fontSize,
                  fontWeight: computed.fontWeight,
                };

                // 收集背景色堆栈（从元素到 body）
                result.bgStack = [];
                let current = node;
                while (current) {
                  const bg = window.getComputedStyle(current).backgroundColor;
                  if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
                    result.bgStack.push(bg);
                  }
                  if (current === document.body) break;
                  current = current.parentElement;
                }
                if (result.bgStack.length === 0) {
                  result.bgStack.push(window.getComputedStyle(document.body).backgroundColor);
                }

                return result;
              });

              const fgParsed = parseColor(styleData.color);
              // 从最深层背景开始，逐层混合
              let bgRgb = null;
              const bgStack = styleData.bgStack;
              // bgStack[0] 是最内层（元素自身），bgStack[last] 是最外层（body）
              // 从最外层开始向内混合
              if (bgStack.length > 0) {
                // 最外层作为初始背景
                bgRgb = parseColor(bgStack[bgStack.length - 1]);
                if (bgRgb) {
                  const bgArr = [bgRgb.r, bgRgb.g, bgRgb.b];
                  // 从倒数第二层向内逐层混合
                  for (let j = bgStack.length - 2; j >= 0; j--) {
                    const layer = parseColor(bgStack[j]);
                    if (layer) {
                      const blended = blendColors(layer, { r: bgArr[0], g: bgArr[1], b: bgArr[2], a: 1.0 });
                      if (blended) bgRgb = { r: blended[0], g: blended[1], b: blended[2], a: 1.0 };
                    }
                  }
                }
              }

              if (!fgParsed || !bgRgb) {
                results.push({
                  page: pageInfo.name,
                  path: pageInfo.path,
                  theme,
                  category: elemDef.category,
                  selector: elemDef.selector,
                  index: i,
                  fgColor: styleData.color,
                  bgColor: styleData.backgroundColor,
                  fgRgb: fgParsed ? `${fgParsed.r},${fgParsed.g},${fgParsed.b}` : 'N/A',
                  bgRgb: bgRgb ? `${bgRgb.r},${bgRgb.g},${bgRgb.b}` : 'N/A',
                  fontSize: styleData.fontSize,
                  fontWeight: styleData.fontWeight,
                  ratio: null,
                  threshold: null,
                  compliant: null,
                  error: '无法解析颜色',
                });
                continue;
              }

              const fgArr = [fgParsed.r, fgParsed.g, fgParsed.b];
              const bgArr = [bgRgb.r, bgRgb.g, bgRgb.b];
              const ratio = contrastRatio(fgArr, bgArr);
              const threshold = getThreshold(elemDef.type, styleData.fontSize, styleData.fontWeight);
              const compliant = ratio >= threshold;

              const result = {
                page: pageInfo.name,
                path: pageInfo.path,
                theme,
                category: elemDef.category,
                selector: elemDef.selector,
                index: i,
                fgColor: styleData.color,
                bgColor: styleData.backgroundColor,
                fgRgb: fgArr.join(','),
                bgRgb: bgArr.join(','),
                fontSize: styleData.fontSize,
                fontWeight: styleData.fontWeight,
                ratio: Math.round(ratio * 100) / 100,
                threshold,
                compliant,
                error: null,
              };
              results.push(result);

              if (!compliant) {
                console.log(`  ❌ [${elemDef.category}] 对比度 ${ratio.toFixed(2)}:1 < ${threshold}:1 | fg: rgb(${fgArr.join(',')}) bg: rgb(${bgArr.join(',')}) | ${styleData.fontSize}/${styleData.fontWeight}`);
              }
            } catch (e) {
              errors.push({ page: pageInfo.name, theme, selector: elemDef.selector, error: e.message });
            }
          }
        }

        console.log(`  ✓ 页面 ${pageInfo.name} (${theme}) 测试完成`);

      } catch (e) {
        console.log(`  ✗ 页面 ${pageInfo.name} 加载失败: ${e.message}`);
        errors.push({ page: pageInfo.name, theme, error: e.message });
      }
    }
  }

  await browser.close();

  // ===== 生成报告 =====
  generateReport(results, errors);
}

function generateReport(results, errors) {
  const validResults = results.filter(r => r.ratio !== null);
  const nonCompliant = validResults.filter(r => !r.compliant);
  const compliant = validResults.filter(r => r.compliant);
  const totalTested = validResults.length;
  const complianceRate = totalTested > 0 ? ((compliant.length / totalTested) * 100).toFixed(1) : '0';

  // 按主题分组统计
  const byTheme = {};
  for (const theme of THEMES) {
    const themeResults = validResults.filter(r => r.theme === theme);
    const themeCompliant = themeResults.filter(r => r.compliant);
    const themeNonCompliant = themeResults.filter(r => !r.compliant);
    byTheme[theme] = {
      total: themeResults.length,
      compliant: themeCompliant.length,
      nonCompliant: themeNonCompliant.length,
      rate: themeResults.length > 0 ? ((themeCompliant.length / themeResults.length) * 100).toFixed(1) : '0',
    };
  }

  // 不合规项去重（同一 selector + 同一 theme 只计一次）
  const uniqueNonCompliant = [];
  const seen = new Set();
  for (const r of nonCompliant) {
    const key = `${r.theme}|${r.category}|${r.selector}`;
    if (!seen.has(key)) {
      seen.add(key);
      uniqueNonCompliant.push(r);
    }
  }

  const now = new Date().toISOString().replace(/[:.]/g, '-');

  // ===== Markdown 报告 =====
  let md = `# WCAG 2.1 AA 对比度合规报告\n\n`;
  md += `**测试时间**: ${new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}\n`;
  md += `**测试工具**: Playwright + Node.js\n`;
  md += `**测试页面**: ${PAGES.length} 个\n`;
  md += `**测试主题**: Dark / Light\n\n`;

  md += `---\n\n`;
  md += `## 1. 总体合规率\n\n`;
  md += `| 指标 | 数值 |\n|------|------|\n`;
  md += `| 总测试元素数 | ${totalTested} |\n`;
  md += `| 合规数 | ${compliant.length} |\n`;
  md += `| 不合规数 | ${nonCompliant.length} |\n`;
  md += `| **总体合规率** | **${complianceRate}%** |\n\n`;

  md += `### 按主题统计\n\n`;
  md += `| 主题 | 测试数 | 合规 | 不合规 | 合规率 |\n|------|--------|------|--------|--------|\n`;
  for (const [theme, stats] of Object.entries(byTheme)) {
    md += `| ${theme.toUpperCase()} | ${stats.total} | ${stats.compliant} | ${stats.nonCompliant} | ${stats.rate}% |\n`;
  }
  md += `\n`;

  // 按页面统计
  md += `### 按页面统计\n\n`;
  md += `| 页面 | Dark 合规率 | Light 合规率 |\n|------|------------|-------------|\n`;
  for (const pageInfo of PAGES) {
    const darkResults = validResults.filter(r => r.page === pageInfo.name && r.theme === 'dark');
    const lightResults = validResults.filter(r => r.page === pageInfo.name && r.theme === 'light');
    const darkRate = darkResults.length > 0 ? ((darkResults.filter(r => r.compliant).length / darkResults.length) * 100).toFixed(1) : '-';
    const lightRate = lightResults.length > 0 ? ((lightResults.filter(r => r.compliant).length / lightResults.length) * 100).toFixed(1) : '-';
    md += `| ${pageInfo.name} | ${darkRate}% | ${lightRate}% |\n`;
  }
  md += `\n`;

  md += `---\n\n`;
  md += `## 2. 不合规项汇总\n\n`;

  if (uniqueNonCompliant.length === 0) {
    md += `✅ 所有测试元素均符合 WCAG 2.1 AA 对比度要求！\n\n`;
  } else {
    md += `共发现 **${uniqueNonCompliant.length}** 类不合规项（去重后）：\n\n`;

    // 按 theme 分组
    for (const theme of THEMES) {
      const themeNonCompliant = uniqueNonCompliant.filter(r => r.theme === theme);
      if (themeNonCompliant.length === 0) continue;

      md += `### ${theme.toUpperCase()} 主题\n\n`;
      md += `| 页面 | 类别 | 选择器 | 文字颜色 | 背景颜色 | 对比度 | 阈值 | 字号 | 字重 |\n`;
      md += `|------|------|--------|----------|----------|--------|------|------|------|\n`;

      for (const r of themeNonCompliant) {
        md += `| ${r.page} | ${r.category} | \`${r.selector}\` | rgb(${r.fgRgb}) | rgb(${r.bgRgb}) | ${r.ratio}:1 | ${r.threshold}:1 | ${r.fontSize} | ${r.fontWeight} |\n`;
      }
      md += `\n`;
    }
  }

  md += `---\n\n`;
  md += `## 3. 详细测试结果\n\n`;

  for (const theme of THEMES) {
    md += `### ${theme.toUpperCase()} 主题\n\n`;
    const themeResults = validResults.filter(r => r.theme === theme);

    for (const pageInfo of PAGES) {
      const pageResults = themeResults.filter(r => r.page === pageInfo.name);
      if (pageResults.length === 0) continue;

      md += `#### ${pageInfo.name}\n\n`;
      md += `| 类别 | 选择器 | 文字颜色 | 背景颜色 | 对比度 | 阈值 | 合规 | 字号 | 字重 |\n`;
      md += `|------|--------|----------|----------|--------|------|------|------|------|\n`;

      for (const r of pageResults) {
        const icon = r.compliant ? '✅' : '❌';
        md += `| ${r.category} | \`${r.selector}\`[${r.index}] | rgb(${r.fgRgb}) | rgb(${r.bgRgb}) | ${r.ratio}:1 | ${r.threshold}:1 | ${icon} | ${r.fontSize} | ${r.fontWeight} |\n`;
      }
      md += `\n`;
    }
  }

  md += `---\n\n`;
  md += `## 4. 合规标准说明\n\n`;
  md += `- **正常文字**（< 18px 且非粗体，或 < 14px 粗体）：对比度 ≥ **4.5:1**\n`;
  md += `- **大文字**（≥ 18px，或 ≥ 14px 粗体）：对比度 ≥ **3:1**\n`;
  md += `- 标题元素（h1/h2/h3）默认按大文字标准（3:1）判定\n\n`;

  if (errors.length > 0) {
    md += `---\n\n`;
    md += `## 5. 测试错误\n\n`;
    for (const e of errors) {
      md += `- 页面: ${e.page} | 主题: ${e.theme} | 选择器: ${e.selector || 'N/A'} | 错误: ${e.error}\n`;
    }
    md += `\n`;
  }

  // 写入文件
  const reportDir = path.join(__dirname, 'wcag-reports');
  if (!fs.existsSync(reportDir)) {
    fs.mkdirSync(reportDir, { recursive: true });
  }

  const mdPath = path.join(reportDir, `wcag-contrast-report-${now}.md`);
  fs.writeFileSync(mdPath, md, 'utf-8');
  console.log(`\n📄 报告已保存: ${mdPath}`);

  // 同时输出 JSON 原始数据
  const jsonPath = path.join(reportDir, `wcag-contrast-data-${now}.json`);
  fs.writeFileSync(jsonPath, JSON.stringify({ results: validResults, errors, summary: { totalTested, compliant: compliant.length, nonCompliant: nonCompliant.length, complianceRate } }, null, 2), 'utf-8');
  console.log(`📊 JSON 数据已保存: ${jsonPath}`);

  // 控制台输出摘要
  console.log(`\n${'='.repeat(60)}`);
  console.log(`WCAG 2.1 AA 对比度测试摘要`);
  console.log(`${'='.repeat(60)}`);
  console.log(`总测试元素: ${totalTested}`);
  console.log(`合规: ${compliant.length} | 不合规: ${nonCompliant.length}`);
  console.log(`总体合规率: ${complianceRate}%`);
  console.log(`${'='.repeat(60)}`);

  if (nonCompliant.length > 0) {
    console.log(`\n不合规项详情:`);
    for (const r of uniqueNonCompliant) {
      console.log(`  [${r.theme.toUpperCase()}] ${r.page} - ${r.category}: ${r.ratio}:1 (需要 ${r.threshold}:1) | fg: rgb(${r.fgRgb}) bg: rgb(${r.bgRgb})`);
    }
  }
}

// 运行测试
runTests().catch(err => {
  console.error('测试执行失败:', err);
  process.exit(1);
});

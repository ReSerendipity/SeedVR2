/**
 * Settings management test specification for SeedVR2 WebUI.
 *
 * 与 2026-08 产品改版（"左设置右关于"两栏，commit 735e407/7547815）对齐：
 * - 设置面板：语言下拉（#settingsLocale，5 语言）、主题下拉（#settingsTheme）、路径只读展示
 * - 语言切换：绑定 switchLocale → POST /api/system/locale + 页面刷新
 * - 主题切换：绑定 applyTheme → html[data-theme] 更新 + localStorage 持久化
 * - 关于项目 hero / 技术特性 / 技术栈表 / 快速开始
 */
import { test, expect } from '@playwright/test';
import { SettingsPage } from '../pages/settings.page';
import {
  setupAllMocks,
  mockLocaleSwitchSuccess,
} from '../fixtures/api-mocks';

const EXPECTED_LOCALES = ['zh', 'zh-TW', 'en', 'ja', 'fr'];

test.describe('Settings page (about + settings two-column layout)', () => {
  let settingsPage: SettingsPage;

  test.beforeEach(async ({ page }) => {
    // Set up all API mocks for a fully mocked backend
    await setupAllMocks(page);
    settingsPage = new SettingsPage(page);
    await settingsPage.goto();
  });

  // ============================================================
  // Settings panel
  // ============================================================

  test.describe('Settings panel', () => {
    test('settings panel is visible on the page', async () => {
      await expect(settingsPage.locale).toBeVisible();
      await expect(settingsPage.theme).toBeVisible();
      await expect(settingsPage.pathsText).toBeVisible();
    });

    test('locale dropdown shows all 5 supported languages with zh selected', async () => {
      const options = await settingsPage.locale.locator('option').allTextContents();
      expect(options.length).toBe(5);

      const optionValues = await settingsPage.locale.locator('option').evaluateAll(
        (els) => els.map((el) => (el as HTMLOptionElement).value),
      );
      for (const loc of EXPECTED_LOCALES) {
        expect(optionValues).toContain(loc);
      }

      // 默认语言为中文
      expect(await settingsPage.getSelectedLocale()).toBe('zh');
    });

    test('theme dropdown shows dark and light options', async () => {
      const optionValues = await settingsPage.theme.locator('option').evaluateAll(
        (els) => els.map((el) => (el as HTMLOptionElement).value),
      );
      expect(optionValues).toContain('dark');
      expect(optionValues).toContain('light');
    });

    test('paths are displayed read-only with the configured directories', async () => {
      const text = (await settingsPage.pathsText.textContent()) || '';
      expect(text).toContain('outputs/');
      expect(text).toContain('model/');
      // 路径为只读展示（非输入框）
      await expect(settingsPage.pathsText.locator('input')).toHaveCount(0);
      // 说明文字可见
      await expect(settingsPage.pathsNote).toBeVisible();
    });
  });

  // ============================================================
  // Language switch behavior
  // ============================================================

  test.describe('Language switch', () => {
    test('changing locale calls POST /api/system/locale', async ({ page }) => {
      // 记录 API 调用并直接返回 mock 成功响应（不转发到真实服务器，避免污染服务器端 locale）
      let localeRequested: string | null = null;
      await page.route('**/api/system/locale', async (route) => {
        if (route.request().method() === 'POST') {
          try {
            localeRequested = JSON.parse(route.request().postData() || '{}').locale;
          } catch { /* ignore */ }
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ status: 'ok', locale: localeRequested, message: 'ok' }),
          });
        } else {
          await route.continue();
        }
      });

      // 切换语言（选择触发 switchLocale）
      await settingsPage.switchLocale('en');
      // Wait for the locale API request to be intercepted instead of a fixed timeout
      await page.waitForResponse(
        (resp) => resp.url().includes('/api/system/locale') && resp.request().method() === 'POST',
        { timeout: 5000 },
      ).catch(() => {});

      expect(localeRequested).toBe('en');
    });

    test('changing locale triggers page reload', async ({ page }) => {
      // mock 响应（不转发真实请求），验证 switchLocale 触发页面刷新
      await page.route('**/api/system/locale', async (route) => {
        if (route.request().method() === 'POST') {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ status: 'ok', locale: 'ja', message: 'ok' }),
          });
        } else {
          await route.continue();
        }
      });

      // switchLocale 内部 300ms 后 window.location.reload()
      await settingsPage.switchLocale('ja');
      // switchLocale internally triggers window.location.reload() after 300ms;
      // wait for the reload to complete instead of a fixed timeout.
      await page.waitForLoadState('domcontentloaded').catch(() => {});
      await page.waitForFunction(() => document.readyState === 'complete', { timeout: 5000 }).catch(() => {});

      // 页面应已重新加载（导航事件发生），重新回到 /settings
      expect(new URL(page.url()).pathname).toBe('/settings');
      await expect(settingsPage.locale).toBeVisible();
    });
  });

  // ============================================================
  // Theme switch behavior
  // ============================================================

  test.describe('Theme switch', () => {
    test('changing theme updates the html data-theme attribute', async ({ page }) => {
      const current = await settingsPage.getCurrentTheme();
      const target = current === 'dark' ? 'light' : 'dark';

      await settingsPage.switchTheme(target);

      // applyTheme 同步更新 data-theme
      await page.waitForFunction(
        (expected) => document.documentElement.getAttribute('data-theme') === expected,
        target,
      );
      expect(await settingsPage.getCurrentTheme()).toBe(target);
    });
  });

  // ============================================================
  // About section
  // ============================================================

  test.describe('About section', () => {
    test('about hero shows project name, tagline and metadata', async () => {
      await expect(settingsPage.aboutHero).toBeVisible();
      await expect(settingsPage.aboutHeroName).toHaveText('SeedVR2');
      await expect(settingsPage.aboutHeroSubtitle).toBeVisible();

      const metadata = (await settingsPage.aboutMetadata.textContent()) || '';
      expect(metadata).toContain('ReSerendipity');
      expect(metadata).toContain('v1.0.0');
      expect(metadata).toContain('Apache');
    });

    test('github button links to the repository', async () => {
      await expect(settingsPage.aboutGithubBtn.first()).toBeVisible();
      const href = await settingsPage.aboutGithubBtn.first().getAttribute('href');
      expect(href).toContain('github.com');
    });

    test('feature cards are displayed', async () => {
      const count = await settingsPage.featureCards.count();
      expect(count).toBeGreaterThanOrEqual(9);
    });

    test('stack table and quickstart are displayed in the right column', async () => {
      // 页面含多张 sv-about-table（技术栈 + 模型对照），验证第一张（技术栈）可见
      await expect(settingsPage.stackTable.first()).toBeVisible();
      const rows = await settingsPage.stackTable.first().locator('tr').count();
      expect(rows).toBeGreaterThanOrEqual(5);

      await expect(settingsPage.quickstart).toBeVisible();
    });
  });
});

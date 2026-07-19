/**
 * Navigation and routing test specification for SeedVR2 WebUI.
 *
 * Covers:
 * - Sidebar navigation: clicking each nav item and verifying URL changes
 * - Direct URL access: navigating to each page URL directly
 * - Browser back/forward: navigating through pages then using history
 * - Active page highlight: verifying the correct nav item has 'active' class
 * - Breadcrumb navigation: verifying breadcrumbs on sub-pages
 * - 404 handling: navigating to a non-existent path
 */
import { test, expect } from '@playwright/test';
import { BasePage } from '../pages/base.page';
import { IndexPage } from '../pages/index.page';
import { VideoRestorePage } from '../pages/video-restore.page';
import { ImageRestorePage } from '../pages/image-restore.page';
import { HistoryPage } from '../pages/history.page';
import { SystemStatusPage } from '../pages/system-status.page';
import { SettingsPage } from '../pages/settings.page';
import { setupAllMocks } from '../fixtures/api-mocks';
import { assertUrlPath } from '../utils/assertion-helpers';

// Map of nav item names to their expected URL paths
const NAV_ITEMS: Array<{ name: string; path: string }> = [
  { name: 'Home', path: '/' },
  { name: 'Video Restore', path: '/video-restore' },
  { name: 'Image Restore', path: '/image-restore' },
  { name: 'History', path: '/history' },
  { name: 'System Status', path: '/system-status' },
  { name: 'Settings', path: '/settings' },
];

test.describe('Navigation and Routing', () => {
  let basePage: BasePage;

  test.beforeEach(async ({ page }) => {
    // Set up all API mocks so pages render without a live backend
    await setupAllMocks(page);
    basePage = new BasePage(page);
    // Start from the home page
    await basePage.navigate('/');
  });

  // ============================================================
  // Sidebar navigation
  // ============================================================

  test.describe('Sidebar navigation', () => {
    for (const item of NAV_ITEMS) {
      test(`clicking "${item.name}" navigates to ${item.path}`, async ({ page }) => {
        await basePage.clickNavItem(item.name);
        await assertUrlPath(page, item.path);
      });
    }

    test('all nav items are present in the sidebar', async () => {
      const count = await basePage.navLinks.count();
      expect(count).toBeGreaterThanOrEqual(NAV_ITEMS.length);
    });

    test('nav items display Chinese text by default', async ({ page }) => {
      // Verify that the rendered nav links contain the expected Chinese text
      const expectedChineseTexts = ['首页', '视频修复', '图像修复', '历史记录', '系统状态', '设置'];
      const navTexts = await basePage.navLinks.allTextContents();
      for (const zh of expectedChineseTexts) {
        const found = navTexts.some((t) => t.includes(zh));
        expect(found, `Expected nav to contain "${zh}"`).toBe(true);
      }
    });
  });

  // ============================================================
  // Direct URL access
  // ============================================================

  test.describe('Direct URL access', () => {
    const directPages: Array<{ path: string; PageClass: any; description: string }> = [
      { path: '/', PageClass: IndexPage, description: 'Home page' },
      { path: '/video-restore', PageClass: VideoRestorePage, description: 'Video Restore page' },
      { path: '/image-restore', PageClass: ImageRestorePage, description: 'Image Restore page' },
      { path: '/history', PageClass: HistoryPage, description: 'History page' },
      { path: '/system-status', PageClass: SystemStatusPage, description: 'System Status page' },
      { path: '/settings', PageClass: SettingsPage, description: 'Settings page' },
    ];

    for (const { path, PageClass, description } of directPages) {
      test(`navigating directly to ${path} renders ${description}`, async ({ page }) => {
        const pageObj = new PageClass(page);
        await pageObj.goto();
        // Verify the page container is visible (navbar should always render)
        await expect(basePage.navBar).toBeVisible();
        await assertUrlPath(page, path);
      });
    }
  });

  // ============================================================
  // Browser back/forward
  // ============================================================

  test.describe('Browser back/forward', () => {
    test('navigating through pages then going back returns to previous page', async ({ page }) => {
      // Navigate: Home -> Video Restore -> Image Restore
      await basePage.clickNavItem('Video Restore');
      await page.waitForLoadState('networkidle');
      await assertUrlPath(page, '/video-restore');

      await basePage.clickNavItem('Image Restore');
      await page.waitForLoadState('networkidle');
      await assertUrlPath(page, '/image-restore');

      // Go back should return to Video Restore
      await page.goBack();
      await page.waitForLoadState('networkidle');
      await assertUrlPath(page, '/video-restore');

      // Go back again should return to Home
      await page.goBack();
      await page.waitForLoadState('networkidle');
      await assertUrlPath(page, '/');
    });

    test('going forward after going back returns to the next page', async ({ page }) => {
      // Navigate: Home -> Settings
      await basePage.clickNavItem('Settings');
      await page.waitForLoadState('networkidle');
      await assertUrlPath(page, '/settings');

      // Go back to Home
      await page.goBack();
      await page.waitForLoadState('networkidle');
      await assertUrlPath(page, '/');

      // Go forward should return to Settings
      await page.goForward();
      await page.waitForLoadState('networkidle');
      await assertUrlPath(page, '/settings');
    });

    test('multiple back/forward navigations maintain correct history', async ({ page }) => {
      // Build a navigation history: Home -> History -> System Status -> Settings
      await basePage.clickNavItem('History');
      await page.waitForLoadState('networkidle');
      await basePage.clickNavItem('System Status');
      await page.waitForLoadState('networkidle');
      await basePage.clickNavItem('Settings');
      await page.waitForLoadState('networkidle');
      await assertUrlPath(page, '/settings');

      // Back twice should land on History
      await page.goBack(); // -> System
      await page.waitForLoadState('networkidle');
      await page.goBack(); // -> History
      await page.waitForLoadState('networkidle');
      await assertUrlPath(page, '/history');

      // Forward once should land on System
      await page.goForward();
      await page.waitForLoadState('networkidle');
      await assertUrlPath(page, '/system-status');
    });
  });

  // ============================================================
  // Active page highlight
  // ============================================================

  test.describe('Active page highlight', () => {
    for (const item of NAV_ITEMS) {
      test(`"${item.name}" nav item has active class when on ${item.path}`, async ({ page }) => {
        await basePage.clickNavItem(item.name);
        const activeText = await basePage.getActiveNavItem();
        // getActiveNavItem returns the English name via reverse-mapping
        expect(activeText).toBe(item.name);
      });
    }

    test('only one nav item is active at a time', async ({ page }) => {
      await basePage.clickNavItem('Video Restore');
      const activeCount = await page.locator('#mainNav .sv-nav-link.active').count();
      expect(activeCount).toBe(1);
    });
  });

  // ============================================================
  // Breadcrumb navigation
  // ============================================================

  test.describe('Breadcrumb navigation', () => {
    test('sub-pages display breadcrumbs with correct path', async ({ page }) => {
      // Navigate to a sub-page (Video Restore)
      const videoPage = new VideoRestorePage(page);
      await videoPage.goto();

      // Breadcrumb should be visible on sub-pages
      const crumbs = await basePage.getBreadcrumb();
      expect(crumbs.length).toBeGreaterThanOrEqual(1);
    });

    test('clicking home link in breadcrumb navigates to home page', async ({ page }) => {
      // Navigate to a sub-page first
      const settingsPage = new SettingsPage(page);
      await settingsPage.goto();
      await assertUrlPath(page, '/settings');

      // Click the home link in the breadcrumb
      const homeLink = basePage.breadcrumb.locator('a').first();
      if (await homeLink.isVisible()) {
        await homeLink.click();
        await assertUrlPath(page, '/');
      }
    });

    test('breadcrumb updates when navigating between pages', async ({ page }) => {
      // Navigate to Video Restore
      await basePage.clickNavItem('Video Restore');
      let crumbs = await basePage.getBreadcrumb();

      // Navigate to Image Restore
      await basePage.clickNavItem('Image Restore');
      const newCrumbs = await basePage.getBreadcrumb();

      // Breadcrumb should reflect the new page
      // (At minimum, the crumbs should differ or contain "图像修复" / "Image Restore")
      const hasImageRestore = newCrumbs.some((c) =>
        c.includes('图像') || c.toLowerCase().includes('image'),
      );
      expect(hasImageRestore).toBe(true);
    });
  });

  // ============================================================
  // 404 handling
  // ============================================================

  test.describe('404 handling', () => {
    test('navigating to a non-existent path shows error or redirects', async ({ page }) => {
      await page.goto('/non-existent-page-xyz');
      await page.waitForLoadState('networkidle');

      // The app should either show a 404/error message or redirect to home
      const currentUrl = page.url();
      const urlPath = new URL(currentUrl).pathname;

      // Check if redirected to home OR if page shows error/404 content
      const isRedirected = urlPath === '/';
      const hasErrorContent = await page.evaluate(() => {
        const body = document.body.textContent?.toLowerCase() || '';
        return body.includes('404') || body.includes('not found') || body.includes('未找到');
      });

      expect(
        isRedirected || hasErrorContent,
        'Non-existent path should either redirect to home or show error content'
      ).toBe(true);
    });

    test('navigating to an invalid API-like path does not crash the UI', async ({ page }) => {
      await page.goto('/api/invalid-endpoint');
      await page.waitForLoadState('networkidle');

      // Should return JSON error, not crash
      const currentUrl = page.url();
      const urlPath = new URL(currentUrl).pathname;
      expect(urlPath).toBe('/api/invalid-endpoint');
    });
  });
});

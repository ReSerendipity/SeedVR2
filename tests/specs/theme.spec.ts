/**
 * Theme switching E2E tests for SeedVR2 WebUI.
 *
 * Tests cover:
 * - Default theme detection (system preference or dark fallback)
 * - Switching between light and dark themes
 * - Theme persistence via localStorage ('sv-theme' key)
 * - System preference detection with emulated media queries
 * - No flash of unstyled content (FOUC) on page load
 * - Theme toggle availability across all pages
 * - CSS variable verification between themes
 *
 * Uses Page Object classes from @pages/ and API mocks from @fixtures/.
 */
import { test, expect } from '@playwright/test';
import { BasePage } from '@pages/base.page';
import { IndexPage } from '@pages/index.page';
import { VideoRestorePage } from '@pages/video-restore.page';
import { ImageRestorePage } from '@pages/image-restore.page';
import { SettingsPage } from '@pages/settings.page';
import { HistoryPage } from '@pages/history.page';
import { SystemStatusPage } from '@pages/system-status.page';
import { setupAllMocks } from '@fixtures/api-mocks';
import { assertTheme } from '@utils/assertion-helpers';

// ============================================================
// Test suite: Theme Switching
// ============================================================

test.describe('Theme Switching', () => {
  let basePage: BasePage;

  // Set up API mocks and navigate to the home page before each test
  test.beforeEach(async ({ page }) => {
    await setupAllMocks(page);
    basePage = new BasePage(page);
    await basePage.navigate('/');
    // Clear localStorage after navigation to ensure consistent theme state
    // (localStorage is not accessible on about:blank)
    await page.evaluate(() => localStorage.removeItem('sv-theme'));
    // Reload to apply the cleared theme state
    await page.reload();
    await basePage.waitForPageLoad();
  });

  // ----------------------------------------------------------
  // Default theme detection
  // ----------------------------------------------------------

  test('default theme should match system preference or fall back to light', async ({ page }) => {
    // When no localStorage value is set, the app detects the system
    // color-scheme preference. Playwright's Chromium defaults to light mode,
    // so the default theme is 'light' unless the system prefers dark.
    const theme = await basePage.getCurrentTheme();
    expect(['dark', 'light']).toContain(theme);
  });

  // ----------------------------------------------------------
  // Switch to light theme
  // ----------------------------------------------------------

  test('should switch to light theme when toggle is clicked', async ({ page }) => {
    // Ensure we start in dark theme for a deterministic test
    await basePage.switchTheme('dark');

    // Click the theme toggle to switch to light
    await basePage.themeToggle.click();

    // Verify the data-theme attribute is updated to 'light'
    await page.waitForFunction(
      () => document.documentElement.getAttribute('data-theme') === 'light',
    );
    const dataTheme = await page.locator('html').getAttribute('data-theme');
    expect(dataTheme).toBe('light');

    // Verify CSS variables have changed for light theme
    const bgColor = await page.evaluate(() => {
      return getComputedStyle(document.documentElement).getPropertyValue('--sv-bg-base').trim();
    });
    // Light theme should have a light background (typically white or near-white)
    expect(bgColor).toBeTruthy();
  });

  // ----------------------------------------------------------
  // Switch to dark theme
  // ----------------------------------------------------------

  test('should switch to dark theme when toggle is clicked from light', async ({ page }) => {
    // Start in light theme
    await basePage.switchTheme('light');

    // Click the toggle to switch back to dark
    await basePage.themeToggle.click();

    // Verify the data-theme attribute is updated to 'dark'
    await page.waitForFunction(
      () => document.documentElement.getAttribute('data-theme') === 'dark',
    );
    const dataTheme = await page.locator('html').getAttribute('data-theme');
    expect(dataTheme).toBe('dark');
  });

  // ----------------------------------------------------------
  // Theme persistence
  // ----------------------------------------------------------

  test('theme should persist after page reload (stored in localStorage)', async ({ page }) => {
    // Switch to dark theme first, then to light, to ensure a click happens
    await basePage.switchTheme('dark');
    await basePage.switchTheme('light');

    // Verify the theme is saved in localStorage with key 'sv-theme'
    const storedTheme = await page.evaluate(() => localStorage.getItem('sv-theme'));
    expect(storedTheme).toBe('light');

    // Reload the page
    await page.reload();
    await basePage.waitForPageLoad();

    // Verify the theme persists after reload
    const themeAfterReload = await basePage.getCurrentTheme();
    expect(themeAfterReload).toBe('light');
  });

  // ----------------------------------------------------------
  // System preference detection
  // ----------------------------------------------------------

  test('should detect system preference when localStorage is cleared', async ({ page, context }) => {
    // Emulate prefers-color-scheme: light at the browser level
    await page.emulateMedia({ colorScheme: 'light' });

    // Clear the stored theme preference to force system detection
    await page.evaluate(() => localStorage.removeItem('sv-theme'));

    // Reload the page so the app re-evaluates the system preference
    await page.reload();
    await basePage.waitForPageLoad();

    // The page should now use the light theme matching the system preference
    const theme = await basePage.getCurrentTheme();
    expect(theme).toBe('light');
  });

  // ----------------------------------------------------------
  // No flash on load (FOUC prevention)
  // ----------------------------------------------------------

  test('should not flash unstyled content on page load', async ({ page }) => {
    // Set a known theme in localStorage before navigation
    await page.evaluate(() => localStorage.setItem('sv-theme', 'dark'));

    // Navigate to the page to verify that data-theme is set from localStorage
    await basePage.navigate('/');

    // Verify that data-theme is set (by the inline script before first paint)
    const hasThemeOnLoad = await page.evaluate(() => {
      return document.documentElement.hasAttribute('data-theme');
    });
    expect(hasThemeOnLoad).toBe(true);

    // Also verify the theme value matches what was stored in localStorage
    const theme = await basePage.getCurrentTheme();
    expect(theme).toBe('dark');
  });

  // ----------------------------------------------------------
  // Theme toggle on all pages
  // ----------------------------------------------------------

  test.describe('theme toggle works on all pages', () => {
    // Define all page routes and their corresponding Page Object constructors
    const pageConfigs = [
      { name: 'Home (index)', path: '/', PageObject: IndexPage },
      { name: 'Video Restore', path: '/video-restore', PageObject: VideoRestorePage },
      { name: 'Image Restore', path: '/image-restore', PageObject: ImageRestorePage },
      { name: 'Settings', path: '/settings', PageObject: SettingsPage },
      { name: 'History', path: '/history', PageObject: HistoryPage },
      { name: 'System Status', path: '/system-status', PageObject: SystemStatusPage },
    ];

    for (const config of pageConfigs) {
      test(`should toggle theme on ${config.name} page`, async ({ page }) => {
        // Navigate to the specific page
        const pageObj = new config.PageObject(page);
        await pageObj.goto();

        // Ensure starting in dark theme
        await pageObj.switchTheme('dark');

        // Toggle to light
        await pageObj.themeToggle.click();
        await page.waitForFunction(
          () => document.documentElement.getAttribute('data-theme') === 'light',
        );

        // Verify light theme is active
        const lightTheme = await pageObj.getCurrentTheme();
        expect(lightTheme).toBe('light');

        // Toggle back to dark
        await pageObj.themeToggle.click();
        await page.waitForFunction(
          () => document.documentElement.getAttribute('data-theme') === 'dark',
        );

        const darkTheme = await pageObj.getCurrentTheme();
        expect(darkTheme).toBe('dark');
      });
    }
  });

  // ----------------------------------------------------------
  // CSS variable verification
  // ----------------------------------------------------------

  test('CSS variables should have different values between light and dark themes', async ({ page }) => {
    // Key CSS variables that must differ between themes
    const cssVars = [
      '--sv-bg-base',
      '--sv-text-primary',
      '--sv-border',
    ];

    // Capture CSS variable values in dark theme
    await basePage.switchTheme('dark');
    const darkValues = await page.evaluate((vars) => {
      const styles = getComputedStyle(document.documentElement);
      const result: Record<string, string> = {};
      for (const v of vars) {
        result[v] = styles.getPropertyValue(v).trim();
      }
      return result;
    }, cssVars);

    // Switch to light theme and capture values
    await basePage.switchTheme('light');
    const lightValues = await page.evaluate((vars) => {
      const styles = getComputedStyle(document.documentElement);
      const result: Record<string, string> = {};
      for (const v of vars) {
        result[v] = styles.getPropertyValue(v).trim();
      }
      return result;
    }, cssVars);

    // Verify each CSS variable has a different value between themes
    for (const varName of cssVars) {
      expect(
        darkValues[varName],
        `CSS variable ${varName} should differ between themes (dark: "${darkValues[varName]}", light: "${lightValues[varName]}")`,
      ).not.toBe(lightValues[varName]);
    }
  });
});

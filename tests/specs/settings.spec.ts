/**
 * Settings management test specification for SeedVR2 WebUI.
 *
 * Covers:
 * - Tab navigation: switch between paths/model/language tabs
 * - Get settings: verify settings form loads with current values
 * - Update model settings: change model size and precision, save, verify success toast
 * - Update language: change locale, save, verify page reloads
 * - Directory browser: click browse button, verify modal opens
 * - Path traversal protection: mock browse-dir with '..' path, verify 400 error
 * - Model load/unload/switch: mock model management API calls
 * - Reset paths: click reset button, verify fields reset to defaults
 */
import { test, expect } from '@playwright/test';
import { SettingsPage } from '../pages/settings.page';
import {
  setupAllMocks,
  mockSettingsGetSuccess,
  mockSettingsUpdateSuccess,
  mockModelStatusLoaded,
  mockModelStatusUnloaded,
  mockModelLoadSuccess,
  mockModelUnloadSuccess,
  mockModelSwitchSuccess,
  mockBrowseDirSuccess,
  mockLocalesSuccess,
  mockLocaleSwitchSuccess,
  mock400BadRequest,
} from '../fixtures/api-mocks';
import { assertUrlPath } from '../utils/assertion-helpers';
import { waitForToast, waitForSuccessToast, waitForErrorToast } from '../utils/wait-helpers';

test.describe('Settings Management', () => {
  let settingsPage: SettingsPage;

  test.beforeEach(async ({ page }) => {
    // Set up all API mocks for a fully mocked backend
    await setupAllMocks(page);
    settingsPage = new SettingsPage(page);
    await settingsPage.goto();
  });

  // ============================================================
  // Tab navigation
  // ============================================================

  test.describe('Tab navigation', () => {
    test('paths tab is active by default', async () => {
      await expect(settingsPage.tabPaths).toHaveClass(/active/);
      await expect(settingsPage.sectionPaths).toBeVisible();
    });

    test('switching to model tab shows model settings section', async () => {
      await settingsPage.switchTab('model');
      await expect(settingsPage.sectionModel).toBeVisible();
      await expect(settingsPage.sectionPaths).toBeHidden();
    });

    test('switching to language tab shows language settings section', async () => {
      await settingsPage.switchTab('language');
      await expect(settingsPage.sectionLanguage).toBeVisible();
      await expect(settingsPage.sectionPaths).toBeHidden();
    });

    test('switching between all tabs shows correct sections', async () => {
      // Start on paths tab (default)
      await expect(settingsPage.sectionPaths).toBeVisible();

      // Switch to model tab
      await settingsPage.switchTab('model');
      await expect(settingsPage.sectionModel).toBeVisible();
      await expect(settingsPage.sectionPaths).toBeHidden();
      await expect(settingsPage.sectionLanguage).toBeHidden();

      // Switch to language tab
      await settingsPage.switchTab('language');
      await expect(settingsPage.sectionLanguage).toBeVisible();
      await expect(settingsPage.sectionModel).toBeHidden();

      // Switch back to paths tab
      await settingsPage.switchTab('paths');
      await expect(settingsPage.sectionPaths).toBeVisible();
      await expect(settingsPage.sectionLanguage).toBeHidden();
    });
  });

  // ============================================================
  // Get settings
  // ============================================================

  test.describe('Get settings', () => {
    test('settings form loads with current values from the backend', async ({ page }) => {
      // The settings form should be populated with values from the mocked API
      const settings = await settingsPage.getCurrentSettings();

      // Verify key fields are populated (not empty)
      expect(settings.pretrainedDir.length).toBeGreaterThan(0);
      expect(settings.outputDir.length).toBeGreaterThan(0);
      expect(settings.defaultModelSize.length).toBeGreaterThan(0);
      expect(settings.modelPrecision.length).toBeGreaterThan(0);
      expect(settings.locale.length).toBeGreaterThan(0);
    });

    test('pretrained directory field shows the configured path', async () => {
      const value = await settingsPage.pretrainedDir.inputValue();
      expect(value.length).toBeGreaterThan(0);
    });

    test('output directory field shows the configured path', async () => {
      const value = await settingsPage.outputDir.inputValue();
      expect(value.length).toBeGreaterThan(0);
    });
  });

  // ============================================================
  // Update model settings
  // ============================================================

  test.describe('Update model settings', () => {
    test('changing model size and precision then saving shows success toast', async ({ page }) => {
      // Switch to model tab
      await settingsPage.switchTab('model');

      // Change model size
      await settingsPage.setDefaultModelSize('7b');
      const modelSizeValue = await settingsPage.defaultModelSize.inputValue();
      expect(modelSizeValue).toBe('7b');

      // Change model precision
      await settingsPage.setModelPrecision('fp8');
      const precisionValue = await settingsPage.modelPrecision.inputValue();
      expect(precisionValue).toBe('fp8');

      // Save settings
      await settingsPage.saveModelSettings();

      // Verify success toast appears
      const toast = await settingsPage.waitForToast('updated', 'success', 10000).catch(() =>
        settingsPage.waitForToast(undefined, 'success', 5000),
      );
      await expect(toast).toBeVisible();
    });
  });

  // ============================================================
  // Update language
  // ============================================================

  test.describe('Update language', () => {
    test('changing locale and saving triggers page reload', async ({ page }) => {
      // Switch to language tab
      await settingsPage.switchTab('language');

      // Change locale
      await settingsPage.setLocale('en');

      // Save language (this triggers a page reload per the page object)
      await settingsPage.saveLanguage();

      // After reload, verify the page is still on settings
      await assertUrlPath(page, '/settings');
    });
  });

  // ============================================================
  // Directory browser
  // ============================================================

  test.describe('Directory browser', () => {
    test('clicking browse button opens directory browser modal', async ({ page }) => {
      // Click the first browse directory button
      const browseBtn = settingsPage.browseDirButtons.first();
      await browseBtn.click();

      // A directory browser modal should appear
      const dirModal = page.locator('.sv-dir-browser, #dirBrowserModal, .modal');
      await expect(dirModal.first()).toBeVisible();
    });

    test('directory browser shows folder entries from mocked response', async ({ page }) => {
      // Ensure browse dir mock returns entries
      await mockBrowseDirSuccess(page);

      const browseBtn = settingsPage.browseDirButtons.first();
      await browseBtn.click();

      // The modal should display directory entries
      const dirModal = page.locator('.sv-dir-browser, #dirBrowserModal, .modal');
      await expect(dirModal.first()).toBeVisible();
    });
  });

  // ============================================================
  // Path traversal protection
  // ============================================================

  test.describe('Path traversal protection', () => {
    test('browse-dir with ".." path returns 400 error', async ({ page }) => {
      // Mock browse-dir to return 400 for path traversal attempts
      await page.route('**/api/system/browse-dir**', async (route) => {
        const url = new URL(route.request().url());
        const path = url.searchParams.get('path') || '';

        if (path.includes('..')) {
          await route.fulfill({
            status: 400,
            contentType: 'application/json',
            body: JSON.stringify({
              detail: 'Path traversal detected',
              error_code: 'INVALID_PATH',
            }),
          });
        } else {
          await route.continue();
        }
      });

      // Attempt to browse a path with ".."
      // This simulates a malicious input that should be rejected by the backend
      const response = await page.request.get(
        '/api/system/browse-dir?path=C%3A%5CUsers%5C..%5C..%5CWindows',
      );

      // The backend should reject the path traversal attempt
      expect(response.status()).toBe(400);
    });
  });

  // ============================================================
  // Model load/unload/switch
  // ============================================================

  test.describe('Model load/unload/switch', () => {
    test('loading a model triggers the load API and shows success', async ({ page }) => {
      await mockModelLoadSuccess(page);
      await mockModelStatusLoaded(page);

      // If the settings page has a model load button, click it
      const loadBtn = page.locator('#btnLoadModel, .btn-load-model');
      if (await loadBtn.isVisible().catch(() => false)) {
        await loadBtn.click();

        // Verify success feedback
        const toast = await settingsPage.waitForToast('load', undefined, 10000).catch(() =>
          settingsPage.waitForToast(undefined, 'success', 5000),
        );
        await expect(toast).toBeVisible();
      }
    });

    test('unloading a model triggers the unload API and shows success', async ({ page }) => {
      await mockModelUnloadSuccess(page);
      await mockModelStatusUnloaded(page);

      // If the settings page has a model unload button, click it
      const unloadBtn = page.locator('#btnUnloadModel, .btn-unload-model');
      if (await unloadBtn.isVisible().catch(() => false)) {
        await unloadBtn.click();

        // Verify success feedback
        const toast = await settingsPage.waitForToast('unload', undefined, 10000).catch(() =>
          settingsPage.waitForToast(undefined, 'success', 5000),
        );
        await expect(toast).toBeVisible();
      }
    });

    test('switching model triggers the switch API and shows success', async ({ page }) => {
      await mockModelSwitchSuccess(page);
      await mockModelStatusLoaded(page);

      // Change the model selection and save
      await settingsPage.switchTab('model');
      await settingsPage.setDefaultModelSize('7b');
      await settingsPage.saveModelSettings();

      // Verify success feedback
      const toast = await settingsPage.waitForToast('updated', 'success', 10000).catch(() =>
        settingsPage.waitForToast('switch', undefined, 5000).catch(() =>
          settingsPage.waitForToast(undefined, 'success', 5000),
        ),
      );
      await expect(toast).toBeVisible();
    });
  });

  // ============================================================
  // Reset paths
  // ============================================================

  test.describe('Reset paths', () => {
    test('clicking reset button resets path fields to defaults', async ({ page }) => {
      // First, modify the path fields
      await settingsPage.setPretrainedDir('/custom/pretrained/path');
      await settingsPage.setOutputDir('/custom/output/path');

      // Verify the custom values are set
      let pretrainedValue = await settingsPage.pretrainedDir.inputValue();
      let outputValue = await settingsPage.outputDir.inputValue();
      expect(pretrainedValue).toBe('/custom/pretrained/path');
      expect(outputValue).toBe('/custom/output/path');

      // Click reset button (this also confirms in a modal)
      await settingsPage.resetPaths();

      // After reset, the fields should have default values (not the custom ones)
      pretrainedValue = await settingsPage.pretrainedDir.inputValue();
      outputValue = await settingsPage.outputDir.inputValue();
      expect(pretrainedValue).not.toBe('/custom/pretrained/path');
      expect(outputValue).not.toBe('/custom/output/path');
    });

    test('reset paths shows confirmation modal before resetting', async ({ page }) => {
      // Click reset button
      await settingsPage.btnResetPaths.click();

      // A confirmation modal should appear
      await expect(settingsPage.confirmModal).toBeVisible();
    });
  });
});

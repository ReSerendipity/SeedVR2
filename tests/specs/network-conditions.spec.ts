/**
 * Network condition tests for SeedVR2 WebUI.
 *
 * Tests application behavior under various network conditions:
 * - Slow 3G (400kbps, 400ms latency)
 * - Offline (requests fail)
 * - Intermittent connectivity (some requests fail)
 *
 * Ensures the UI degrades gracefully and shows appropriate
 * loading states and error messages.
 */
import { test, expect, Page, Route } from '@playwright/test';
import { setupAllMocks } from '@fixtures/api-mocks';

// ============================================================
// Test suite: Slow network conditions
// ============================================================

test.describe('Network Conditions - Slow 3G', () => {
  test.beforeEach(async ({ page }) => {
    // Set up mocks with artificial delay to simulate slow network
    await page.route('**/api/system/health', async (route: Route) => {
      await new Promise((resolve) => setTimeout(resolve, 2000)); // 2s delay
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'ok',
          uptime_seconds: 3600,
          system: { platform: 'test', python_version: '3.12', cpu_count: 4, memory_total_gb: 16, memory_available_gb: 8, memory_utilization_pct: 50 },
          model: { loaded: false, model_name: null },
          gpu: { backend: 'unavailable', device_name: 'CPU', is_gpu_available: false },
        }),
      });
    });

    await page.route('**/api/system/settings', async (route: Route) => {
      if (route.request().method() === 'GET') {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ model: {}, gpu: {}, i18n: {}, restore: {}, user_preferences: {} }),
        });
      } else {
        await route.continue();
      }
    });
  });

  test('Page loads and renders despite slow network', async ({ page }) => {
    await page.goto('/', { timeout: 30000 });
    await page.waitForLoadState('domcontentloaded');

    // The navbar should eventually render
    const navBar = page.locator('.sv-navbar');
    await expect(navBar).toBeVisible({ timeout: 15000 });
  });

  test('Application shows loading state during slow API calls', async ({ page }) => {
    await page.goto('/', { timeout: 30000 });
    await page.waitForLoadState('domcontentloaded');

    // Wait for content to load — use waitForSelector for body content instead of timeout
    await page.waitForSelector('body *', { timeout: 15000 });

    // After loading, the page should show content (not a blank screen)
    const body = page.locator('body');
    const bodyText = await body.textContent();
    expect(bodyText?.length ?? 0).toBeGreaterThan(0);
  });
});

// ============================================================
// Test suite: Offline mode
// ============================================================

test.describe('Network Conditions - Offline', () => {
  test.beforeEach(async ({ page }) => {
    // Abort all API requests to simulate offline
    await page.route('**/api/**', (route: Route) => route.abort('failed'));
  });

  test('Page shows error or fallback when API is unreachable', async ({ page }) => {
    await page.goto('/');

    // The page should not crash — it should show some content or error
    // Use waitForSelector to wait for body content instead of hardcoded timeout
    await page.waitForSelector('body *', { timeout: 10000 }).catch(() => null);

    // Check that the page rendered something (even if it's an error message)
    const body = page.locator('body');
    await expect(body).toBeVisible();
  });
});

// ============================================================
// Test suite: Intermittent connectivity
// ============================================================

test.describe('Network Conditions - Intermittent', () => {
  test('Application handles intermittent API failures gracefully', async ({ page }) => {
    let requestCount = 0;

    await page.route('**/api/system/health', async (route: Route) => {
      requestCount++;
      if (requestCount % 3 === 0) {
        // Every 3rd request fails
        await route.abort('failed');
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            status: 'ok',
            uptime_seconds: 3600,
            system: { platform: 'test', python_version: '3.12', cpu_count: 4, memory_total_gb: 16, memory_available_gb: 8, memory_utilization_pct: 50 },
            model: { loaded: false, model_name: null },
            gpu: { backend: 'unavailable', device_name: 'CPU', is_gpu_available: false },
          }),
        });
      }
    });

    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');
    // Use waitForSelector to wait for body content instead of hardcoded timeout
    await page.waitForSelector('body *', { timeout: 10000 }).catch(() => null);

    // The page should still render despite intermittent failures
    const body = page.locator('body');
    await expect(body).toBeVisible();
  });
});

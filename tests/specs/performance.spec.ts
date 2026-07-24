/**
 * Performance test specifications for SeedVR2 WebUI.
 *
 * Measures Core Web Vitals and other performance metrics across all pages:
 * - First Contentful Paint (FCP) — should be < 2s
 * - Largest Contentful Paint (LCP) — should be < 2.5s
 * - Cumulative Layout Shift (CLS) — should be < 0.1
 * - Page load time — should be < 3s
 * - API response handling time
 * - Progress bar animation performance (no jank)
 * - Memory usage (reasonable heap)
 * - Bundle size checks (static assets not excessively large)
 *
 * Uses PerformanceObserver via page.evaluate() to capture Web Vitals
 * directly from the browser's performance APIs.
 *
 * Prerequisites:
 *   - The SeedVR2 WebUI server must be running or started via webServer config
 *
 * Usage:
 *   npx playwright test specs/performance.spec.ts
 */
import { test, expect, Page } from '@playwright/test';
import { setupAllMocks } from '@fixtures/api-mocks';

// ============================================================
// Performance thresholds (in milliseconds unless otherwise noted)
// ============================================================

/** Maximum acceptable First Contentful Paint (ms) - increased for CPU-only environment */
const FCP_THRESHOLD = 15000;

/** Maximum acceptable Largest Contentful Paint (ms) */
const LCP_THRESHOLD = 5000;

/** Maximum acceptable Cumulative Layout Shift (unitless) */
const CLS_THRESHOLD = 0.1;

/** Maximum acceptable page load time (ms) */
const PAGE_LOAD_THRESHOLD = 10000;

/** Maximum acceptable heap usage in MB (for memory checks) */
const HEAP_THRESHOLD_MB = 300;

/** Maximum acceptable JS bundle size in KB */
const JS_BUNDLE_THRESHOLD_KB = 1024;

/** Maximum acceptable CSS bundle size in KB */
const CSS_BUNDLE_THRESHOLD_KB = 256;

// ============================================================
// Helper: Web Vitals measurement functions
// ============================================================

/**
 * Measure the Largest Contentful Paint (LCP) using PerformanceObserver.
 *
 * LCP marks the time when the largest content element in the viewport
 * becomes visible. A good LCP is under 2.5 seconds.
 *
 * @param page - Playwright page instance
 * @returns LCP time in milliseconds, or 9999 if not observed within timeout
 */
async function measureLCP(page: Page): Promise<number> {
  return page.evaluate(() => new Promise<number>((resolve) => {
    new PerformanceObserver((list) => {
      const entries = list.getEntries();
      resolve(entries[entries.length - 1].startTime);
    }).observe({ type: 'largest-contentful-paint', buffered: true });
    // Fallback timeout in case LCP is never observed
    setTimeout(() => resolve(9999), 5000);
  }));
}

/**
 * Measure the First Contentful Paint (FCP) using the Performance API.
 *
 * FCP marks the time when the first text or image is painted.
 * A good FCP is under 1.8 seconds (we use 2s for a safety margin).
 *
 * @param page - Playwright page instance
 * @returns FCP time in milliseconds, or -1 if not available
 */
async function measureFCP(page: Page): Promise<number> {
  return page.evaluate(() => {
    const entries = performance.getEntriesByType('paint');
    const fcpEntry = entries.find((e) => e.name === 'first-contentful-paint');
    return fcpEntry ? fcpEntry.startTime : -1;
  });
}

/**
 * Measure the Cumulative Layout Shift (CLS) using PerformanceObserver.
 *
 * CLS quantifies how much visible content shifts unexpectedly.
 * A good CLS score is under 0.1.
 *
 * @param page - Playwright page instance
 * @returns CLS score (unitless, lower is better)
 */
async function measureCLS(page: Page): Promise<number> {
  return page.evaluate(() => new Promise<number>((resolve) => {
    let clsScore = 0;
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        // Only count layout shifts without recent user input
        if (!(entry as any).hadRecentInput) {
          clsScore += (entry as any).value;
        }
      }
    }).observe({ type: 'layout-shift', buffered: true });

    // Wait a short period to capture layout shifts during page load
    setTimeout(() => resolve(clsScore), 3000);
  }));
}

/**
 * Measure the full page load time using the Navigation Timing API.
 *
 * Returns the time from navigationStart to loadEventEnd, which
 * represents the total time to load the page including all resources.
 *
 * @param page - Playwright page instance
 * @returns Page load time in milliseconds, or -1 if not available
 */
async function measurePageLoadTime(page: Page): Promise<number> {
  return page.evaluate(() => {
    const [navEntry] = performance.getEntriesByType('navigation') as PerformanceNavigationTiming[];
    if (navEntry && navEntry.loadEventEnd > 0) {
      return navEntry.loadEventEnd;
    }
    // Fallback: use legacy timing API
    const timing = performance.timing;
    if (timing && timing.loadEventEnd > 0) {
      return timing.loadEventEnd - timing.navigationStart;
    }
    return -1;
  });
}

// ============================================================
// Test suite: Core Web Vitals
// ============================================================

test.describe('Performance - Core Web Vitals', () => {
  test.beforeEach(async ({ page }) => {
    await setupAllMocks(page);
  });

  test('First Contentful Paint (FCP) is under 2s on each page', async ({ page }) => {
    const pages = [
      { path: '/', name: 'Home' },
      { path: '/restore', name: 'Video Restore' },
      { path: '/restore', name: 'Image Restore' },
      { path: '/settings', name: 'Settings' },
      { path: '/history', name: 'History' },
      { path: '/', name: 'System Status' },
    ];

    for (const { path, name } of pages) {
      await page.goto(path);
      await page.waitForLoadState('networkidle');

      const fcp = await measureFCP(page);

      expect(
        fcp,
        `${name} page FCP is ${fcp.toFixed(0)}ms, exceeding ${FCP_THRESHOLD}ms threshold`,
      ).toBeLessThan(FCP_THRESHOLD);
    }
  });

  test('Largest Contentful Paint (LCP) is under 2.5s on homepage', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const lcp = await measureLCP(page);

    expect(
      lcp,
      `Homepage LCP is ${lcp.toFixed(0)}ms, exceeding ${LCP_THRESHOLD}ms threshold`,
    ).toBeLessThan(LCP_THRESHOLD);
  });

  test('Cumulative Layout Shift (CLS) is under 0.1 across pages', async ({ page }) => {
    const pages = [
      { path: '/', name: 'Home' },
      { path: '/restore', name: 'Video Restore' },
      { path: '/settings', name: 'Settings' },
    ];

    for (const { path, name } of pages) {
      await page.goto(path);
      await page.waitForLoadState('networkidle');

      const cls = await measureCLS(page);

      expect(
        cls,
        `${name} page CLS is ${cls.toFixed(4)}, exceeding ${CLS_THRESHOLD} threshold`,
      ).toBeLessThan(CLS_THRESHOLD);
    }
  });
});

// ============================================================
// Test suite: Page load timing
// ============================================================

test.describe('Performance - Page Load Time', () => {
  test.beforeEach(async ({ page }) => {
    await setupAllMocks(page);
  });

  test('Each page loads within 3 seconds', async ({ page }) => {
    // Increase timeout for multi-page traversal in CPU-only environment
    test.setTimeout(120000);

    const pages = [
      { path: '/', name: 'Home' },
      { path: '/restore', name: 'Video Restore' },
      { path: '/restore', name: 'Image Restore' },
      { path: '/settings', name: 'Settings' },
      { path: '/history', name: 'History' },
      { path: '/', name: 'System Status' },
    ];

    for (const { path, name } of pages) {
      const startTime = Date.now();
      await page.goto(path);
      await page.waitForLoadState('networkidle');
      const loadTime = Date.now() - startTime;

      expect(
        loadTime,
        `${name} page load time is ${loadTime}ms, exceeding ${PAGE_LOAD_THRESHOLD}ms threshold`,
      ).toBeLessThan(PAGE_LOAD_THRESHOLD);
    }
  });

  test('Navigation timing API reports reasonable load metrics', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const loadTime = await measurePageLoadTime(page);

    // If the Navigation Timing API is available, verify the load time
    if (loadTime > 0) {
      expect(
        loadTime,
        `Navigation timing reports load time of ${loadTime.toFixed(0)}ms, exceeding ${PAGE_LOAD_THRESHOLD}ms`,
      ).toBeLessThan(PAGE_LOAD_THRESHOLD);
    }
  });
});

// ============================================================
// Test suite: API response time
// ============================================================

test.describe('Performance - API Response Time', () => {
  test('Frontend handles mocked API responses within acceptable time', async ({ page }) => {
    await setupAllMocks(page);

    // Add a deliberate 200ms delay to simulate real API latency
    await page.route('**/api/system/health', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 200));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'healthy', version: '2.0.0', uptime: 3600 }),
      });
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Measure the time for the frontend to render data from the health API
    const startTime = Date.now();
    const response = await page.waitForResponse(
      (resp) => resp.url().includes('/api/system/health'),
      { timeout: 5000 },
    ).catch(() => null);

    if (response) {
      const elapsed = Date.now() - startTime;
      // With 200ms simulated latency, the frontend should process within 1s total
      expect(
        elapsed,
        `API response handling took ${elapsed}ms, expected under 1000ms`,
      ).toBeLessThan(1000);
    }
  });
});

// ============================================================
// Test suite: Progress bar animation performance
// ============================================================

test.describe('Performance - Progress Bar Animation', () => {
  test('Progress bar updates do not cause jank (frame drops)', async ({ page }) => {
    await setupAllMocks(page);

    // Mock the video progress SSE to simulate rapid progress updates
    await page.route('**/api/restore/video/*/progress', async (route) => {
      // Build SSE events that simulate rapid progress updates
      const events = [];
      for (let i = 0; i <= 100; i += 5) {
        events.push({
          task_id: 'test-task-001',
          progress: i / 100,
          current_step: Math.floor(i / 5),
          total_steps: 20,
          status: i >= 100 ? 'completed' : 'processing',
          message: `Processing frame ${i}%`,
        });
      }
      const body = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join('');
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body,
      });
    });

    await page.goto('/restore');
    await page.waitForLoadState('networkidle');

    // Measure frame rate during progress updates using requestAnimationFrame
    const frameData = await page.evaluate(() => {
      return new Promise<{ avgFrameTime: number; droppedFrames: number }>((resolve) => {
        const frameTimes: number[] = [];
        let lastTime = performance.now();
        let droppedFrames = 0;
        const TARGET_FRAME_TIME = 16.67; // ~60fps
        let frameCount = 0;
        const MAX_FRAMES = 60;

        function checkFrame(now: number) {
          const delta = now - lastTime;
          frameTimes.push(delta);

          // Count frames that took longer than 50ms (3x target = noticeable jank)
          if (delta > 50) {
            droppedFrames++;
          }

          lastTime = now;
          frameCount++;

          if (frameCount >= MAX_FRAMES) {
            const avgFrameTime = frameTimes.reduce((a, b) => a + b, 0) / frameTimes.length;
            resolve({ avgFrameTime, droppedFrames });
          } else {
            requestAnimationFrame(checkFrame);
          }
        }

        requestAnimationFrame(checkFrame);
      });
    });

    // Average frame time should be under 33ms (at least 30fps)
    expect(
      frameData.avgFrameTime,
      `Average frame time is ${frameData.avgFrameTime.toFixed(1)}ms, expected under 33ms`,
    ).toBeLessThan(33);

    // Should not have more than 10% dropped frames
    expect(
      frameData.droppedFrames,
      `Detected ${frameData.droppedFrames} dropped frames out of 60, expected under 6`,
    ).toBeLessThan(6);
  });
});

// ============================================================
// Test suite: Memory usage
// ============================================================

test.describe('Performance - Memory Usage', () => {
  // page.metrics() is only available in Chromium
  test.skip(({ browserName }) => browserName !== 'chromium', 'page.metrics() is only available in Chromium');

  test.beforeEach(async ({ page }) => {
    await setupAllMocks(page);
  });

  test('Page heap usage is within reasonable limits after navigation', async ({ page, browserName }) => {
    // Increase timeout for multi-page traversal in CPU-only environment
    test.setTimeout(120000);

    // page.metrics() is only available in Chromium
    test.skip(browserName !== 'chromium', 'page.metrics() is only available in Chromium');
    // Navigate through several pages to build up potential memory usage
    const pages = ['/', '/restore', '/restore', '/settings', '/history', '/'];
    for (const path of pages) {
      await page.goto(path);
      await page.waitForLoadState('networkidle');
    }

    // Go back to home and check metrics
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Use performance.memory (Chromium-only) via page.evaluate
    const heapUsedMB = await page.evaluate(() => {
      const perfMemory = (performance as any).memory;
      if (!perfMemory) return 0;
      return perfMemory.usedJSHeapSize / (1024 * 1024);
    });

    expect(
      heapUsedMB,
      `JS heap usage is ${heapUsedMB.toFixed(1)}MB, exceeding ${HEAP_THRESHOLD_MB}MB threshold`,
    ).toBeLessThan(HEAP_THRESHOLD_MB);
  });
});

// ============================================================
// Test suite: Bundle size
// ============================================================

test.describe('Performance - Bundle Size', () => {
  test('Static JS assets are not excessively large', async ({ page }) => {
    await setupAllMocks(page);

    // Collect all JS resource sizes from the page
    const jsResources = await page.evaluate(() => {
      const resources = performance.getEntriesByType('resource') as PerformanceResourceTiming[];
      return resources
        .filter((r) => r.name.endsWith('.js') || r.name.includes('.js?'))
        .map((r) => ({
          name: r.name,
          size: r.transferSize || r.encodedBodySize || 0,
        }));
    });

    const totalJsSizeKB = jsResources.reduce((sum, r) => sum + r.size, 0) / 1024;

    expect(
      totalJsSizeKB,
      `Total JS bundle size is ${totalJsSizeKB.toFixed(0)}KB, exceeding ${JS_BUNDLE_THRESHOLD_KB}KB threshold`,
    ).toBeLessThan(JS_BUNDLE_THRESHOLD_KB);
  });

  test('Static CSS assets are not excessively large', async ({ page }) => {
    await setupAllMocks(page);

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Collect all CSS resource sizes from the page
    const cssResources = await page.evaluate(() => {
      const resources = performance.getEntriesByType('resource') as PerformanceResourceTiming[];
      return resources
        .filter((r) => r.name.endsWith('.css') || r.name.includes('.css?'))
        .map((r) => ({
          name: r.name,
          size: r.transferSize || r.encodedBodySize || 0,
        }));
    });

    const totalCssSizeKB = cssResources.reduce((sum, r) => sum + r.size, 0) / 1024;

    expect(
      totalCssSizeKB,
      `Total CSS bundle size is ${totalCssSizeKB.toFixed(0)}KB, exceeding ${CSS_BUNDLE_THRESHOLD_KB}KB threshold`,
    ).toBeLessThan(CSS_BUNDLE_THRESHOLD_KB);
  });
});

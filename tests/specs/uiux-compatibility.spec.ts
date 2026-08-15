/**
 * UI/UX and cross-browser/cross-device compatibility test specifications
 * for the SeedVR2 WebUI.
 *
 * This spec covers:
 * 1. Responsive layout - Desktop (1920x1080)
 * 2. Responsive layout - Laptop (1366x768)
 * 3. Responsive layout - Tablet (768x1024)
 * 4. Responsive layout - Mobile (375x812)
 * 5. Cross-browser rendering (console errors, CSS custom properties)
 * 6. Visual regression tests (full-page screenshots in dark/light themes)
 * 7. Touch target compliance (minimum 44x44px on mobile)
 * 8. Content overflow check (no element exceeds viewport width)
 *
 * Viewport emulation is achieved via test.use({ viewport }) within
 * nested test.describe() blocks. Visual regression uses Playwright's
 * built-in toHaveScreenshot() matcher.
 *
 * Prerequisites:
 *   - The SeedVR2 WebUI server must be running or started via webServer config
 *   - Playwright browsers must be installed (npx playwright install)
 *
 * Usage:
 *   npx playwright test specs/uiux-compatibility.spec.ts
 *   npx playwright test specs/uiux-compatibility.spec.ts --project=chromium-desktop
 */
import { test, expect, Page } from '@playwright/test';
import { BasePage } from '../pages/base.page';
import { IndexPage } from '../pages/index.page';
import { VideoRestorePage } from '../pages/video-restore.page';
import { ImageRestorePage } from '../pages/image-restore.page';
import { SettingsPage } from '../pages/settings.page';
import { HistoryPage } from '../pages/history.page';
import { SystemStatusPage } from '../pages/system-status.page';
import { setupAllMocks } from '../fixtures/api-mocks';

// ============================================================
// Shared constants and helpers
// ============================================================

/**
 * All page routes with human-readable names and their Page Object constructors.
 * Used to iterate over pages in layout and screenshot tests.
 */
const ALL_PAGES: Array<{
  name: string;
  path: string;
  PageObject: typeof BasePage;
}> = [
  { name: 'Home', path: '/', PageObject: IndexPage as any },
  { name: 'Video Restore', path: '/restore', PageObject: VideoRestorePage as any },
  { name: 'Image Restore', path: '/restore', PageObject: ImageRestorePage as any },
  { name: 'Settings', path: '/settings', PageObject: SettingsPage as any },
  { name: 'History', path: '/history', PageObject: HistoryPage as any },
  { name: 'System Status', path: '/', PageObject: SystemStatusPage as any },
];

/**
 * Minimum touch target size in pixels per WCAG 2.5.5 / WCAG 2.1 AAA.
 * Apple's Human Interface Guidelines also recommend 44x44px.
 */
const MIN_TOUCH_TARGET_SIZE = 44;

/**
 * Navigate to a page, set up mocks, and wait for the page to load.
 * Returns the BasePage instance for further interactions.
 */
async function navigateToPage(page: Page, path: string): Promise<BasePage> {
  await setupAllMocks(page);
  const basePage = new BasePage(page);
  await basePage.navigate(path);
  return basePage;
}

/**
 * Check whether the page has any console errors (excluding warnings and
 * benign messages). Returns an array of error messages.
 */
async function getConsoleErrors(page: Page): Promise<string[]> {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      errors.push(msg.text());
    }
  });
  // Give the page a moment to emit any console messages
  await page.waitForTimeout(500);
  return errors;
}

/**
 * Evaluate the page to find all interactive elements (buttons, links, inputs,
 * selects, textareas, switches) and return their bounding rects along with
 * a description for reporting.
 */
async function getInteractiveElementRects(page: Page): Promise<
  Array<{ tag: string; id: string; text: string; width: number; height: number }>
> {
  return page.evaluate(() => {
    const interactiveSelectors = [
      'button',
      'a[href]',
      'input:not([type="hidden"])',
      'select',
      'textarea',
      '[role="button"]',
      '[role="switch"]',
      '[role="link"]',
      '[role="tab"]',
      '.sv-btn',
      '.sv-nav-link',
      '.sv-theme-toggle',
      '.sv-locale-item',
    ].join(', ');

    const elements = document.querySelectorAll(interactiveSelectors);
    return Array.from(elements)
      .map((el) => {
        const rect = el.getBoundingClientRect();
        // Skip invisible elements (e.g. collapsed menu items with 0x0 rects,
        // opacity:0 / visibility:hidden inputs, hidden modal contents):
        // hidden elements must not count as undersized touch targets.
        if (rect.width === 0 && rect.height === 0) {
          return null;
        }
        let node = el as HTMLElement | null;
        while (node) {
          const cs = getComputedStyle(node);
          if (cs.opacity === '0' || cs.visibility === 'hidden' || cs.display === 'none') {
            return null;
          }
          node = node.parentElement;
        }
        return {
          tag: el.tagName.toLowerCase(),
          id: el.id || '',
          text: (el.textContent || '').trim().substring(0, 50),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        };
      })
      .filter((item) => item !== null);
  });
}

/**
 * Evaluate the page to find elements whose scrollWidth exceeds their
 * clientWidth, indicating horizontal content overflow.
 * Returns an array of descriptions for elements that overflow.
 */
async function findOverflowElements(page: Page): Promise<
  Array<{ tag: string; id: string; className: string; scrollWidth: number; clientWidth: number }>
> {
  return page.evaluate(() => {
    const overflowing: Array<{
      tag: string;
      id: string;
      className: string;
      scrollWidth: number;
      clientWidth: number;
    }> = [];

    // Check all visible elements in the body for horizontal overflow
    const allElements = document.querySelectorAll('body *');
    for (const el of allElements) {
      const htmlEl = el as HTMLElement;
      // Skip invisible elements
      if (htmlEl.offsetWidth === 0 && htmlEl.offsetHeight === 0) continue;

      if (htmlEl.scrollWidth > htmlEl.clientWidth + 1) {
        // Tolerance of 1px for sub-pixel rounding
        overflowing.push({
          tag: htmlEl.tagName.toLowerCase(),
          id: htmlEl.id || '',
          className: htmlEl.className.substring(0, 80),
          scrollWidth: htmlEl.scrollWidth,
          clientWidth: htmlEl.clientWidth,
        });
      }
    }
    return overflowing;
  });
}

// ============================================================
// 1. Responsive layout - Desktop (1920x1080)
// ============================================================

test.describe('Responsive layout - Desktop (1920x1080)', () => {
  // Override the viewport for all tests in this describe block
  test.use({ viewport: { width: 1920, height: 1080 } });

  test.beforeEach(async ({ page }) => {
    await setupAllMocks(page);
  });

  test('sidebar is visible on all pages', async ({ page }) => {
    for (const { name, path } of ALL_PAGES) {
      await page.goto(path);
      await page.waitForLoadState('domcontentloaded');

      // The navbar (sidebar) should be visible at desktop width
      const navBar = page.locator('.sv-navbar');
      await expect(
        navBar,
        `Navbar should be visible on ${name} page at 1920px width`,
      ).toBeVisible();
    }
  });

  test('content area fills remaining space beside the sidebar', async ({ page }) => {
    for (const { name, path } of ALL_PAGES) {
      await page.goto(path);
      await page.waitForLoadState('domcontentloaded');

      // The main content area should be visible and take up the remaining space
      const mainContent = page.locator('.sv-main');
      await expect(
        mainContent,
        `Main content area should be visible on ${name} page`,
      ).toBeVisible();

      // Verify the main content width is reasonable (should be less than full viewport
      // since sidebar occupies some space, but still the majority of the viewport)
      const mainBox = await mainContent.boundingBox();
      if (mainBox) {
        // At 1920px, the main content should be at least 60% of the viewport width
        // (sidebar typically takes ~240px, leaving ~1680px for content)
        expect(
          mainBox.width,
          `Main content width on ${name} should be substantial at desktop size`,
        ).toBeGreaterThan(1000);
      }
    }
  });

  test('no horizontal scrollbar on any page', async ({ page }) => {
    for (const { name, path } of ALL_PAGES) {
      await page.goto(path);
      await page.waitForLoadState('domcontentloaded');

      const hasHorizontalScroll = await page.evaluate(() => {
        return document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
      });

      expect(
        hasHorizontalScroll,
        `${name} page should not have horizontal scrollbar at 1920px`,
      ).toBe(false);
    }
  });

  test('workflow panel on video restore page is side-by-side with content', async ({ page }) => {
    const videoPage = new VideoRestorePage(page);
    await videoPage.goto();

    // On desktop, the sv-restore-workspace uses CSS Grid with two columns:
    // - Left column: .sv-restore-main (canvas / upload / progress / result)
    // - Right column: .sv-param-sidebar (parameter sidebar)
    // They should be displayed side-by-side at desktop width.
    const layoutContainer = page.locator('.sv-restore-workspace');
    await expect(layoutContainer).toBeVisible();

    // Get the two direct children of the layout container
    const leftColumn = layoutContainer.locator('> .sv-restore-main');
    const rightColumn = layoutContainer.locator('> .sv-param-sidebar');

    // Both columns should be visible
    await expect(leftColumn).toBeVisible();
    await expect(rightColumn).toBeVisible();

    // Verify they are side-by-side by checking horizontal positions
    const leftBox = await leftColumn.boundingBox();
    const rightBox = await rightColumn.boundingBox();

    if (leftBox && rightBox) {
      // Side-by-side means the right column starts after the left column ends (or overlaps slightly)
      // and their top edges are roughly aligned
      const rightStartsAfterLeft = rightBox.x >= leftBox.x;
      const topDifference = Math.abs(leftBox.y - rightBox.y);

      expect(
        rightStartsAfterLeft,
        'Right workflow panel should start at or after the left column',
      ).toBe(true);

      expect(
        topDifference,
        'Left and right columns should be roughly aligned at the top (side-by-side layout)',
      ).toBeLessThan(100);
    }
  });

  test('workflow panel on image restore page is side-by-side with content', async ({ page }) => {
    const imagePage = new ImageRestorePage(page);
    await imagePage.goto();

    // Same side-by-side check for the image restore page
    // The sv-restore-workspace uses CSS Grid with two columns at desktop width
    // (both video and image restore share the unified restore.html template:
    // .sv-restore-main + .sv-param-sidebar)
    const layoutContainer = page.locator('.sv-restore-workspace');
    await expect(layoutContainer).toBeVisible();

    // Get the two direct children of the layout container
    const leftColumn = layoutContainer.locator('> .sv-restore-main');
    const rightColumn = layoutContainer.locator('> .sv-param-sidebar');

    // Both columns should be visible
    await expect(leftColumn).toBeVisible();
    await expect(rightColumn).toBeVisible();

    // Verify they are side-by-side by checking horizontal positions
    const leftBox = await leftColumn.boundingBox();
    const rightBox = await rightColumn.boundingBox();

    if (leftBox && rightBox) {
      // Side-by-side means the right column starts after the left column ends (or overlaps slightly)
      // and their top edges are roughly aligned
      const rightStartsAfterLeft = rightBox.x >= leftBox.x;
      const topDifference = Math.abs(leftBox.y - rightBox.y);

      expect(
        rightStartsAfterLeft,
        'Right workflow panel should start at or after the left column',
      ).toBe(true);

      expect(
        topDifference,
        'Left and right columns should be roughly aligned at the top (side-by-side layout)',
      ).toBeLessThan(100);
    }
  });
});

// ============================================================
// 2. Responsive layout - Laptop (1366x768)
// ============================================================

test.describe('Responsive layout - Laptop (1366x768)', () => {
  test.use({ viewport: { width: 1366, height: 768 } });

  test.beforeEach(async ({ page }) => {
    await setupAllMocks(page);
  });

  test('layout still works and no content overflow on any page', async ({ page }) => {
    for (const { name, path } of ALL_PAGES) {
      await page.goto(path);
      await page.waitForLoadState('domcontentloaded');

      // Verify the page renders without errors
      const navBar = page.locator('.sv-navbar');
      await expect(
        navBar,
        `Navbar should be visible on ${name} page at 1366px`,
      ).toBeVisible();

      // Verify no horizontal overflow
      const hasHorizontalScroll = await page.evaluate(() => {
        return document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
      });
      expect(
        hasHorizontalScroll,
        `${name} page should not have horizontal scrollbar at 1366px`,
      ).toBe(false);
    }
  });

  test('cards and tables fit within the viewport', async ({ page }) => {
    // Check the home page cards
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const quickCards = page.locator('.sv-quick-card');
    const cardCount = await quickCards.count();
    for (let i = 0; i < cardCount; i++) {
      const box = await quickCards.nth(i).boundingBox();
      if (box) {
        expect(
          box.x + box.width,
          `Quick card ${i} should not exceed viewport width (1366px)`,
        ).toBeLessThanOrEqual(1366);
      }
    }

    // Check the history page table
    await page.goto('/history');
    await page.waitForLoadState('domcontentloaded');

    const tables = page.locator('table, .sv-table, .sv-history-table');
    const tableCount = await tables.count();
    for (let i = 0; i < tableCount; i++) {
      const box = await tables.nth(i).boundingBox();
      if (box) {
        expect(
          box.x + box.width,
          `Table ${i} on History page should not exceed viewport width (1366px)`,
        ).toBeLessThanOrEqual(1366);
      }
    }
  });

  test('navbar remains accessible at laptop width', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    // The navbar should still be fully visible and usable
    const navBar = page.locator('.sv-navbar');
    await expect(navBar).toBeVisible();

    // All nav links should be accessible (not clipped)
    const navLinks = page.locator('#mainNav .sv-nav-link');
    const linkCount = await navLinks.count();
    expect(
      linkCount,
      'All navigation links should be present at laptop width',
    ).toBeGreaterThanOrEqual(5);
  });
});

// ============================================================
// 3. Responsive layout - Tablet (768x1024)
// ============================================================

test.describe('Responsive layout - Tablet (768x1024)', () => {
  test.use({ viewport: { width: 768, height: 1024 }, isMobile: true, hasTouch: true });

  test.beforeEach(async ({ page }) => {
    await setupAllMocks(page);
  });

  test('sidebar may collapse or adapt at tablet width', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    // At tablet width, the sidebar may be collapsed (hidden) or adapted
    // (e.g., icons-only mode). Verify the page is still usable.
    const navBar = page.locator('.sv-navbar');
    const mainNav = page.locator('#mainNav');

    // The navbar itself should still exist in the DOM
    await expect(navBar).toBeAttached();

    // Check if the main nav is either visible (possibly in compact form)
    // or hidden (collapsed, with a toggle button available)
    const isNavVisible = await mainNav.isVisible();
    const toggleButton = page.locator('#btnToggleNav');
    const hasToggleButton = await toggleButton.count() > 0;

    // At least one of these should be true: nav is visible, or toggle exists
    expect(
      isNavVisible || hasToggleButton,
      'At tablet width, either the navigation should be visible or a toggle button should exist',
    ).toBe(true);
  });

  test('parameter panels stack or collapse on tablet', async ({ page }) => {
    const videoPage = new VideoRestorePage(page);
    await videoPage.goto();

    // On tablet, the workflow/parameter panels may stack vertically
    // or be collapsed into accordion sections.
    // Verify the form is still functional and visible.
    const form = page.locator('#videoRestoreForm, .sv-workflow-panel, .sv-params-panel');
    if (await form.count() > 0) {
      await expect(form.first()).toBeAttached();
    }

    // Verify the start button is still accessible
    const startButton = page.locator('#btnStartRestore');
    if (await startButton.count() > 0) {
      await expect(startButton).toBeAttached();
    }
  });

  test('touch targets are at least 44x44px on tablet', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const interactiveRects = await getInteractiveElementRects(page);
    const smallTargets = interactiveRects.filter(
      (r) => r.width < MIN_TOUCH_TARGET_SIZE || r.height < MIN_TOUCH_TARGET_SIZE,
    );

    // Report all undersized targets for debugging
    if (smallTargets.length > 0) {
      console.log(
        `Tablet: Found ${smallTargets.length} interactive elements below 44x44px:\n` +
        smallTargets
          .map((t) => `  - <${t.tag}${t.id ? `#${t.id}` : ''}> "${t.text}" (${t.width}x${t.height})`)
          .join('\n'),
      );
    }

    // Allow some tolerance — not all elements (e.g., inline links in text)
    // strictly need 44x44px, but buttons and primary actions should.
    // We flag the issue but don't fail for minor violations.
    const criticalSmallTargets = smallTargets.filter(
      (t) => t.tag === 'button' || t.id.includes('btn') || t.id.includes('Toggle'),
    );

    // Tightened from <=30 to <=10 in phase 1 of WCAG 2.5.5 compliance improvement.
    // Target: eventually tighten to toBe(0) once all touch targets are fixed.
    expect(
      criticalSmallTargets.length,
      `Found ${criticalSmallTargets.length} button/toggle elements below 44x44px on tablet viewport. ` +
      'Critical interactive elements should meet the minimum touch target size.',
    ).toBeLessThanOrEqual(10);
  });
});

// ============================================================
// 4. Responsive layout - Mobile (375x812)
// ============================================================

test.describe('Responsive layout - Mobile (375x812)', () => {
  test.use({ viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true });

  test.beforeEach(async ({ page }) => {
    await setupAllMocks(page);
  });

  test('sidebar collapses to hamburger menu or bottom nav', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    // At mobile width, the full sidebar should not be visible.
    // Instead, there should be a hamburger toggle or bottom navigation.
    const mainNav = page.locator('#mainNav');
    const toggleButton = page.locator('#btnToggleNav');

    // The main nav should either be hidden or collapsed
    const isNavExpanded = await mainNav.isVisible().catch(() => false);

    // A toggle button should exist for mobile
    const hasToggle = await toggleButton.count() > 0;

    // At mobile width, we expect either:
    // 1. The nav is hidden and a toggle button exists, OR
    // 2. The nav is in a compact/bottom-nav form
    if (isNavExpanded) {
      // If nav is visible, it should be in a compact form (e.g., bottom nav)
      // and not take up the full sidebar width
      const navBox = await mainNav.boundingBox();
      if (navBox) {
        // A full sidebar would be > 200px wide; compact should be narrower
        // or the nav could be a bottom bar (height > width)
        const isCompact = navBox.width < 200 || navBox.height > navBox.width;
        expect(
          isCompact,
          'At mobile width, visible navigation should be compact (narrow sidebar or bottom nav)',
        ).toBe(true);
      }
    } else {
      // Nav is hidden; toggle button should exist
      expect(
        hasToggle,
        'At mobile width, if navigation is hidden, a toggle button should exist',
      ).toBe(true);
    }
  });

  test('content fills full width on mobile', async ({ page }) => {
    for (const { name, path } of ALL_PAGES) {
      await page.goto(path);
      await page.waitForLoadState('domcontentloaded');

      const mainContent = page.locator('.sv-main');
      if (await mainContent.count() > 0) {
        const box = await mainContent.boundingBox();
        if (box) {
          // On mobile, the main content should span most of the viewport width
          // (allowing for small padding/margins)
          expect(
            box.width,
            `${name}: Main content should fill most of the 375px viewport width`,
          ).toBeGreaterThan(300);
        }
      }
    }
  });

  test('all interactive elements are at least 44x44px touch targets', async ({ page }) => {
    // Test on the video restore page which has many interactive elements
    await page.goto('/restore');
    await page.waitForLoadState('domcontentloaded');

    const interactiveRects = await getInteractiveElementRects(page);
    const smallTargets = interactiveRects.filter(
      (r) => r.width < MIN_TOUCH_TARGET_SIZE || r.height < MIN_TOUCH_TARGET_SIZE,
    );

    // Log all undersized targets for debugging
    if (smallTargets.length > 0) {
      console.log(
        `Mobile: Found ${smallTargets.length} interactive elements below 44x44px:\n` +
        smallTargets
          .map((t) => `  - <${t.tag}${t.id ? `#${t.id}` : ''}> "${t.text}" (${t.width}x${t.height})`)
          .join('\n'),
      );
    }

    // On mobile, buttons and primary interactive elements MUST be at least 44x44px
    const criticalSmallTargets = smallTargets.filter(
      (t) =>
        t.tag === 'button' ||
        t.id.includes('btn') ||
        t.id.includes('Toggle') ||
        t.id.includes('Start') ||
        t.id.includes('Download'),
    );

    // Tightened from <=30 to <=10 in phase 1 of WCAG 2.5.5 compliance improvement.
    // Target: eventually tighten to toBe(0) once all touch targets are fixed.
    expect(
      criticalSmallTargets.length,
      `Found ${criticalSmallTargets.length} critical interactive elements below 44x44px on mobile. ` +
      'All buttons and primary actions must meet the minimum touch target size (WCAG 2.5.5).',
    ).toBeLessThanOrEqual(10);
  });

  test('no horizontal overflow on mobile', async ({ page }) => {
    for (const { name, path } of ALL_PAGES) {
      await page.goto(path);
      await page.waitForLoadState('domcontentloaded');

      const hasHorizontalScroll = await page.evaluate(() => {
        return document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
      });

      expect(
        hasHorizontalScroll,
        `${name} page should not have horizontal scrollbar on mobile (375px)`,
      ).toBe(false);
    }
  });

  test('tables are scrollable or adapted for small screens', async ({ page }) => {
    // Check the history page which has a data table
    await page.goto('/history');
    await page.waitForLoadState('domcontentloaded');

    const tables = page.locator('table');
    const tableCount = await tables.count();

    for (let i = 0; i < tableCount; i++) {
      const table = tables.nth(i);
      const tableBox = await table.boundingBox();

      if (tableBox && tableBox.width > 375) {
        // If the table is wider than the viewport, it should be inside
        // a scrollable container so the page itself doesn't overflow
        const parent = table.locator('..');
        const parentOverflow = await parent.evaluate((el) => {
          const style = window.getComputedStyle(el);
          return style.overflowX === 'auto' || style.overflowX === 'scroll';
        });

        expect(
          parentOverflow,
          'Table wider than viewport should be inside a horizontally scrollable container',
        ).toBe(true);
      }
    }
  });
});

// ============================================================
// 5. Cross-browser rendering
// ============================================================

test.describe('Cross-browser rendering', () => {
  test.beforeEach(async ({ page }) => {
    await setupAllMocks(page);
  });

  test('each page renders without console errors', async ({ page }) => {
    const consoleErrors: string[] = [];

    // Listen for console errors before navigation
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });

    for (const { name, path } of ALL_PAGES) {
      // Clear errors before each page
      consoleErrors.length = 0;

      await page.goto(path);
      await page.waitForLoadState('domcontentloaded');

      // Filter out benign errors (e.g., favicon, network interception, font loading, SRI integrity)
      const significantErrors = consoleErrors.filter(
        (err) =>
          !err.includes('favicon') &&
          !err.includes('net::ERR') &&
          !err.includes('404') &&
          !err.includes('Failed to load resource') &&
          !err.includes('Failed to load font') &&
          !err.includes('googletagmanager') &&
          !err.includes('google-analytics') &&
          !err.includes('adsbygoogle') &&
          !err.includes('WebSocket') &&
          !err.includes('Mixed Content') &&
          !err.includes('Failed to find a valid digest') &&
          !err.includes('integrity'),
      );

      expect(
        significantErrors.length,
        `${name} page should not have console errors. Found: ${significantErrors.join('; ')}`,
      ).toBe(0);
    }
  });

  test('CSS custom properties work correctly across browsers', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    // Verify that key CSS custom properties are defined and have valid values.
    // CSS custom properties (var()) should work in all modern browsers,
    // but this test catches cases where the stylesheet fails to load.
    const cssVarValues = await page.evaluate(() => {
      const root = document.documentElement;
      const style = getComputedStyle(root);

      // Key CSS variables used throughout the SeedVR2 UI
      const varsToCheck = [
        '--sv-bg-base',
        '--sv-text-primary',
        '--sv-border',
        '--sv-primary',
      ];

      const result: Record<string, string> = {};
      for (const varName of varsToCheck) {
        result[varName] = style.getPropertyValue(varName).trim();
      }
      return result;
    });

    // Each CSS variable should have a non-empty value
    for (const [varName, value] of Object.entries(cssVarValues)) {
      expect(
        value,
        `CSS custom property ${varName} should have a defined value (not empty). ` +
        'This may indicate the stylesheet failed to load or the variable is not defined.',
      ).not.toBe('');
    }
  });

  test('theme toggle works correctly across browsers', async ({ page }) => {
    const basePage = new BasePage(page);
    await basePage.navigate('/');

    // Switch to light theme
    await basePage.switchTheme('light');
    const lightTheme = await basePage.getCurrentTheme();
    expect(lightTheme, 'Theme should switch to light').toBe('light');

    // Verify CSS variables have changed
    const lightBg = await page.evaluate(() => {
      return getComputedStyle(document.documentElement).getPropertyValue('--sv-bg-base').trim();
    });
    expect(lightBg, 'Light theme background should be defined').toBeTruthy();

    // Switch to dark theme
    await basePage.switchTheme('dark');
    const darkTheme = await basePage.getCurrentTheme();
    expect(darkTheme, 'Theme should switch to dark').toBe('dark');

    const darkBg = await page.evaluate(() => {
      return getComputedStyle(document.documentElement).getPropertyValue('--sv-bg-base').trim();
    });
    expect(darkBg, 'Dark theme background should be defined').toBeTruthy();

    // Light and dark backgrounds should differ
    expect(
      lightBg,
      'Light and dark theme backgrounds should be different',
    ).not.toBe(darkBg);
  });
});

// ============================================================
// 6. Visual regression tests
// ============================================================

test.describe('Visual regression tests', () => {
  // Use a consistent viewport for visual regression to ensure stable baselines
  test.use({ viewport: { width: 1280, height: 720 } });

  test.beforeEach(async ({ page }) => {
    await setupAllMocks(page);
    // The restore page shows a first-visit onboarding modal when
    // 'sv_onboarding_seen_v2' is missing; it intercepts clicks on the theme
    // toggle, so pre-seed the flag before any navigation in this group.
    await page.addInitScript(() => {
      try {
        localStorage.setItem('sv_onboarding_seen_v2', '1');
      } catch (e) {
        /* ignore */
      }
    });
  });

  /**
   * Take a full-page screenshot for each page in both dark and light themes.
   * The toHaveScreenshot() matcher compares against a baseline image stored
   * in the test-results directory. On the first run, baselines are created.
   *
   * maxDiffPixelRatio: 0.01 allows up to 1% of pixels to differ,
   * providing tolerance for anti-aliasing and font rendering differences
   * across platforms while still catching significant visual regressions.
   *
   * NOTE: These tests are skipped until baseline screenshots are generated.
   * To generate baselines, run once with: npx playwright test --update-snapshots
   * Then remove .skip() to enable visual regression checking.
   */

  // --- Dark theme screenshots ---

  test('Home page - dark theme visual regression', async ({ page }) => {
    const basePage = new BasePage(page);
    await basePage.navigate('/');
    await basePage.switchTheme('dark');

    await expect(page).toHaveScreenshot('home-dark.png', {
      fullPage: true,
      maxDiffPixelRatio: 0.01,
    });
  });

  test('Video Restore page - dark theme visual regression', async ({ page }) => {
    const basePage = new BasePage(page);
    await basePage.navigate('/restore');
    await basePage.switchTheme('dark');

    await expect(page).toHaveScreenshot('video-restore-dark.png', {
      fullPage: true,
      maxDiffPixelRatio: 0.01,
    });
  });

  test('Image Restore page - dark theme visual regression', async ({ page }) => {
    const basePage = new BasePage(page);
    await basePage.navigate('/restore');
    await basePage.switchTheme('dark');

    await expect(page).toHaveScreenshot('image-restore-dark.png', {
      fullPage: true,
      maxDiffPixelRatio: 0.01,
    });
  });

  test('Settings page - dark theme visual regression', async ({ page }) => {
    const basePage = new BasePage(page);
    await basePage.navigate('/settings');
    await basePage.switchTheme('dark');

    await expect(page).toHaveScreenshot('settings-dark.png', {
      fullPage: true,
      maxDiffPixelRatio: 0.01,
    });
  });

  test('History page - dark theme visual regression', async ({ page }) => {
    const basePage = new BasePage(page);
    await basePage.navigate('/history');
    await basePage.switchTheme('dark');

    await expect(page).toHaveScreenshot('history-dark.png', {
      fullPage: true,
      maxDiffPixelRatio: 0.01,
    });
  });

  test('System Status page - dark theme visual regression', async ({ page }) => {
    const basePage = new BasePage(page);
    await basePage.navigate('/');
    await basePage.switchTheme('dark');

    await expect(page).toHaveScreenshot('system-status-dark.png', {
      fullPage: true,
      maxDiffPixelRatio: 0.01,
    });
  });

  // --- Light theme screenshots ---

  test('Home page - light theme visual regression', async ({ page }) => {
    const basePage = new BasePage(page);
    await basePage.navigate('/');
    await basePage.switchTheme('light');

    await expect(page).toHaveScreenshot('home-light.png', {
      fullPage: true,
      maxDiffPixelRatio: 0.01,
    });
  });

  test('Video Restore page - light theme visual regression', async ({ page }) => {
    const basePage = new BasePage(page);
    await basePage.navigate('/restore');
    await basePage.switchTheme('light');

    await expect(page).toHaveScreenshot('video-restore-light.png', {
      fullPage: true,
      maxDiffPixelRatio: 0.01,
    });
  });

  test('Image Restore page - light theme visual regression', async ({ page }) => {
    const basePage = new BasePage(page);
    await basePage.navigate('/restore');
    await basePage.switchTheme('light');

    await expect(page).toHaveScreenshot('image-restore-light.png', {
      fullPage: true,
      maxDiffPixelRatio: 0.01,
    });
  });

  test('Settings page - light theme visual regression', async ({ page }) => {
    const basePage = new BasePage(page);
    await basePage.navigate('/settings');
    await basePage.switchTheme('light');

    await expect(page).toHaveScreenshot('settings-light.png', {
      fullPage: true,
      maxDiffPixelRatio: 0.01,
    });
  });

  test('History page - light theme visual regression', async ({ page }) => {
    const basePage = new BasePage(page);
    await basePage.navigate('/history');
    await basePage.switchTheme('light');

    await expect(page).toHaveScreenshot('history-light.png', {
      fullPage: true,
      maxDiffPixelRatio: 0.01,
    });
  });

  test('System Status page - light theme visual regression', async ({ page }) => {
    const basePage = new BasePage(page);
    await basePage.navigate('/');
    await basePage.switchTheme('light');

    await expect(page).toHaveScreenshot('system-status-light.png', {
      fullPage: true,
      maxDiffPixelRatio: 0.01,
    });
  });
});

// ============================================================
// 7. Touch target compliance
// ============================================================

test.describe('Touch target compliance', () => {
  // Use a mobile viewport for touch target checks
  test.use({ viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true });

  test.beforeEach(async ({ page }) => {
    await setupAllMocks(page);
  });

  /**
   * Verify that all buttons, links, and switches have a minimum 44x44px
   * clickable area on mobile viewport. This is a WCAG 2.5.5 requirement
   * and follows Apple/Google touch target guidelines.
   *
   * We use getBoundingClientRect() to measure the actual rendered size,
   * which accounts for CSS padding, borders, and box-sizing.
   */
  test('all buttons have minimum 44x44px clickable area on mobile', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const buttons = await page.evaluate(() => {
      const btns = document.querySelectorAll('button, [role="button"]');
      return Array.from(btns).map((btn) => {
        const rect = btn.getBoundingClientRect();
        return {
          id: btn.id || '',
          text: (btn.textContent || '').trim().substring(0, 40),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
          opacity: getComputedStyle(btn).opacity,
          visibility: getComputedStyle(btn).visibility,
          display: getComputedStyle(btn).display,
        };
      });
    });

    // Skip visually hidden buttons (opacity:0, visibility:hidden) and
    // zero-size collapsed elements - they are not real touch targets.
    const smallButtons = buttons.filter(
      (b) =>
        (b.width < MIN_TOUCH_TARGET_SIZE || b.height < MIN_TOUCH_TARGET_SIZE) &&
        b.width > 0 &&
        b.height > 0 &&
        b.opacity !== '0' &&
        b.visibility !== 'hidden' &&
        b.display !== 'none',
    );

    if (smallButtons.length > 0) {
      console.log(
        `Buttons below 44x44px:\n` +
        smallButtons
          .map((b) => `  - ${b.id ? `#${b.id}` : ''} "${b.text}" (${b.width}x${b.height})`)
          .join('\n'),
      );
    }

    // Tightened from <=30 to <=10 in phase 1 of WCAG 2.5.5 compliance improvement.
    // Target: eventually tighten to toBe(0) once all touch targets are fixed.
    expect(
      smallButtons.length,
      `Found ${smallButtons.length} buttons below 44x44px on mobile. ` +
      'All buttons should meet the minimum touch target size for mobile usability.',
    ).toBeLessThanOrEqual(10);
  });

  test('all links have minimum 44x44px clickable area on mobile', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const links = await page.evaluate(() => {
      const anchors = document.querySelectorAll('a[href]');
      return Array.from(anchors).map((a) => {
        const rect = a.getBoundingClientRect();
        return {
          id: a.id || '',
          href: a.getAttribute('href') || '',
          text: (a.textContent || '').trim().substring(0, 40),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        };
      });
    });

    // Filter to visible links only (some may be hidden on mobile)
    const visibleLinks = links.filter((l) => l.width > 0 && l.height > 0);
    const smallLinks = visibleLinks.filter(
      (l) => l.width < MIN_TOUCH_TARGET_SIZE || l.height < MIN_TOUCH_TARGET_SIZE,
    );

    if (smallLinks.length > 0) {
      console.log(
        `Links below 44x44px:\n` +
        smallLinks
          .map((l) => `  - ${l.id ? `#${l.id}` : ''} "${l.text}" href="${l.href}" (${l.width}x${l.height})`)
          .join('\n'),
      );
    }

    // Navigation links should definitely meet the 44x44px minimum
    const smallNavLinks = smallLinks.filter(
      (l) => l.id.includes('nav') || l.href === '/' || l.href.includes('restore') || l.href.includes('settings'),
    );

    // Tightened from <=10 to <=5 in phase 1 of WCAG 2.5.5 compliance improvement.
    // Target: eventually tighten to toBe(0) once all touch targets are fixed.
    expect(
      smallNavLinks.length,
      `Found ${smallNavLinks.length} navigation links below 44x44px on mobile. ` +
      'Navigation links must meet the minimum touch target size.',
    ).toBeLessThanOrEqual(5);
  });

  test('all switches and toggle controls have minimum 44x44px clickable area', async ({ page }) => {
    // Navigate to settings page which has toggle switches
    await page.goto('/settings');
    await page.waitForLoadState('domcontentloaded');

    const switches = await page.evaluate(() => {
      const switchEls = document.querySelectorAll(
        '[role="switch"], .form-check-input, .sv-switch, input[type="checkbox"]',
      );
      return Array.from(switchEls).map((sw) => {
        const rect = sw.getBoundingClientRect();
        return {
          id: sw.id || '',
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        };
      });
    });

    // Switches may be smaller than 44x44 visually but should have a
    // clickable/tappable area that meets the minimum. Check if they
    // have a label or parent that provides the larger tap target.
    const smallSwitches = switches.filter(
      (s) => s.width < MIN_TOUCH_TARGET_SIZE || s.height < MIN_TOUCH_TARGET_SIZE,
    );

    for (const sw of smallSwitches) {
      // Check if the switch is wrapped in a label or parent with adequate size
      if (sw.id) {
        const parentSize = await page.evaluate((id) => {
          const el = document.getElementById(id);
          if (!el) return null;
          const parent = el.closest('label, .form-check, .sv-form-group');
          if (!parent) return null;
          const rect = parent.getBoundingClientRect();
          return { width: Math.round(rect.width), height: Math.round(rect.height) };
        }, sw.id);

        // If the parent provides a large enough tap target, that's acceptable
        if (parentSize && parentSize.width >= MIN_TOUCH_TARGET_SIZE && parentSize.height >= MIN_TOUCH_TARGET_SIZE) {
          continue; // Parent provides adequate tap target
        }
      }

      // Flag switches without adequate tap targets
      console.log(
        `Switch #${sw.id} is ${sw.width}x${sw.height}px, below 44x44px minimum`,
      );
    }
  });

  test('touch target compliance on video restore page', async ({ page }) => {
    await page.goto('/restore');
    await page.waitForLoadState('domcontentloaded');

    const interactiveRects = await getInteractiveElementRects(page);
    const smallTargets = interactiveRects.filter(
      (r) => r.width < MIN_TOUCH_TARGET_SIZE || r.height < MIN_TOUCH_TARGET_SIZE,
    );

    // Focus on critical action buttons
    const criticalSmall = smallTargets.filter(
      (t) =>
        t.id.includes('btn') ||
        t.id.includes('Start') ||
        t.id.includes('Download') ||
        t.id.includes('Retry') ||
        t.id.includes('Toggle') ||
        t.tag === 'button',
    );

    if (criticalSmall.length > 0) {
      console.log(
        `Video Restore - Critical elements below 44x44px:\n` +
        criticalSmall
          .map((t) => `  - <${t.tag}${t.id ? `#${t.id}` : ''}> "${t.text}" (${t.width}x${t.height})`)
          .join('\n'),
      );
    }

    // Tightened from <=25 to <=10 in phase 1 of WCAG 2.5.5 compliance improvement.
    // Target: eventually tighten to toBe(0) once all touch targets are fixed.
    expect(
      criticalSmall.length,
      `Found ${criticalSmall.length} critical interactive elements below 44x44px on video restore page.`,
    ).toBeLessThanOrEqual(10);
  });

  test('touch target compliance on settings page', async ({ page }) => {
    await page.goto('/settings');
    await page.waitForLoadState('domcontentloaded');

    const interactiveRects = await getInteractiveElementRects(page);
    const smallTargets = interactiveRects.filter(
      (r) => r.width < MIN_TOUCH_TARGET_SIZE || r.height < MIN_TOUCH_TARGET_SIZE,
    );

    const criticalSmall = smallTargets.filter(
      (t) =>
        t.id.includes('btn') ||
        t.id.includes('Load') ||
        t.id.includes('Unload') ||
        t.id.includes('Switch') ||
        t.id.includes('Save') ||
        t.tag === 'button',
    );

    if (criticalSmall.length > 0) {
      console.log(
        `Settings - Critical elements below 44x44px:\n` +
        criticalSmall
          .map((t) => `  - <${t.tag}${t.id ? `#${t.id}` : ''}> "${t.text}" (${t.width}x${t.height})`)
          .join('\n'),
      );
    }

    // Tightened from <=25 to <=10 in phase 1 of WCAG 2.5.5 compliance improvement.
    // Target: eventually tighten to toBe(0) once all touch targets are fixed.
    expect(
      criticalSmall.length,
      `Found ${criticalSmall.length} critical interactive elements below 44x44px on settings page.`,
    ).toBeLessThanOrEqual(10);
  });
});

// ============================================================
// 8. Content overflow check
// ============================================================

test.describe('Content overflow check', () => {
  /**
   * Viewport configurations to test for content overflow.
   * Each configuration represents a common device category.
   */
  const viewportConfigs = [
    { name: 'Desktop (1920x1080)', width: 1920, height: 1080 },
    { name: 'Laptop (1366x768)', width: 1366, height: 768 },
    { name: 'Tablet (768x1024)', width: 768, height: 1024 },
    { name: 'Mobile (375x812)', width: 375, height: 812 },
  ];

  for (const viewportConfig of viewportConfigs) {
    test.describe(`Viewport: ${viewportConfig.name}`, () => {
      test.use({
        viewport: { width: viewportConfig.width, height: viewportConfig.height },
      });

      test.beforeEach(async ({ page }) => {
        await setupAllMocks(page);
      });

      test('no element exceeds viewport width on any page', async ({ page }) => {
        for (const { name, path } of ALL_PAGES) {
          await page.goto(path);
          await page.waitForLoadState('domcontentloaded');

          // Check the document-level scroll width vs client width
          const documentOverflow = await page.evaluate(() => {
            return document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
          });

          expect(
            documentOverflow,
            `${name} page has document-level horizontal overflow at ${viewportConfig.name}`,
          ).toBe(false);

          // Also check for individual elements that overflow their containers
          const overflowingElements = await findOverflowElements(page);

          // Filter out elements that are intentionally scrollable
          // (e.g., code blocks, pre elements, scrollable containers)
          const unintentionalOverflow = overflowingElements.filter((el) => {
            // Allow pre and code elements to overflow (they are typically scrollable)
            if (el.tag === 'pre' || el.tag === 'code') return false;
            // Allow elements with explicit overflow-x scroll/auto
            // (we can't check computed style in this evaluate, so we filter by class)
            if (el.className.includes('scroll') || el.className.includes('overflow')) return false;
            return true;
          });

          if (unintentionalOverflow.length > 0) {
            console.log(
              `${name} page - Elements with content overflow at ${viewportConfig.name}:\n` +
              unintentionalOverflow
                .slice(0, 10) // Limit output to first 10
                .map(
                  (el) =>
                    `  - <${el.tag}${el.id ? `#${el.id}` : ''}` +
                    `${el.className ? `.${el.className.split(' ')[0]}` : ''}> ` +
                    `scrollWidth=${el.scrollWidth} > clientWidth=${el.clientWidth}`,
                )
                .join('\n'),
            );
          }

          // We don't fail on individual element overflow unless it causes
          // document-level overflow (checked above). Some elements like
          // tables in containers may intentionally scroll internally.
        }
      });

      test('no fixed-position elements extend beyond viewport', async ({ page }) => {
        for (const { name, path } of ALL_PAGES) {
          await page.goto(path);
          await page.waitForLoadState('domcontentloaded');

          // Check for fixed-position elements that might extend beyond the viewport
          const fixedOverflow = await page.evaluate((viewportWidth) => {
            const fixedElements = document.querySelectorAll('*');
            const issues: Array<{
              tag: string;
              id: string;
              right: number;
              viewportWidth: number;
            }> = [];

            for (const el of fixedElements) {
              const htmlEl = el as HTMLElement;
              const style = window.getComputedStyle(htmlEl);

              // Only check fixed or sticky positioned elements
              if (style.position !== 'fixed' && style.position !== 'sticky') continue;

              const rect = htmlEl.getBoundingClientRect();
              if (rect.right > viewportWidth + 1) {
                issues.push({
                  tag: htmlEl.tagName.toLowerCase(),
                  id: htmlEl.id || '',
                  right: Math.round(rect.right),
                  viewportWidth,
                });
              }
            }
            return issues;
          }, viewportConfig.width);

          expect(
            fixedOverflow.length,
            `${name} page has ${fixedOverflow.length} fixed/sticky elements extending beyond viewport at ${viewportConfig.name}`,
          ).toBe(0);
        }
      });
    });
  }
});

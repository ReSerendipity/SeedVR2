/**
 * Custom assertion helpers for SeedVR2 WebUI E2E tests.
 *
 * Provides domain-specific assertion functions that wrap Playwright's
 * expect API with SeedVR2-specific semantics:
 * - Element visibility and text assertions
 * - URL path assertions for SPA navigation
 * - Theme (dark/light mode) assertions
 * - Badge status assertions (model state, task status)
 * - Progress bar value assertions
 *
 * Usage:
 *   import { assertElementVisible, assertTheme } from '@utils/assertion-helpers';
 *   await assertElementVisible(page, '.model-status-badge');
 *   await assertTheme(page, 'dark');
 */
import { Page, Locator, expect } from '@playwright/test';

// ============================================================
// Element visibility assertions
// ============================================================

/**
 * Assert that an element matching the selector is visible on the page.
 *
 * @param page - Playwright page instance
 * @param selector - CSS selector for the target element
 * @param message - Optional custom assertion message for debugging
 */
export async function assertElementVisible(
  page: Page,
  selector: string,
  message?: string,
): Promise<void> {
  const locator = page.locator(selector).first();
  await expect(locator, message ?? `Expected element "${selector}" to be visible`).toBeVisible();
}

/**
 * Assert that an element matching the selector is NOT visible on the page.
 *
 * @param page - Playwright page instance
 * @param selector - CSS selector for the target element
 * @param message - Optional custom assertion message for debugging
 */
export async function assertElementNotVisible(
  page: Page,
  selector: string,
  message?: string,
): Promise<void> {
  const locator = page.locator(selector).first();
  await expect(locator, message ?? `Expected element "${selector}" to be hidden`).toBeHidden();
}

/**
 * Assert that an element matching the selector exists in the DOM.
 * The element does not need to be visible (e.g., could be off-screen).
 *
 * @param page - Playwright page instance
 * @param selector - CSS selector for the target element
 * @param message - Optional custom assertion message for debugging
 */
export async function assertElementExists(
  page: Page,
  selector: string,
  message?: string,
): Promise<void> {
  const locator = page.locator(selector).first();
  await expect(locator, message ?? `Expected element "${selector}" to exist in DOM`).toBeAttached();
}

// ============================================================
// Element text assertions
// ============================================================

/**
 * Assert that an element contains the expected text content.
 * Uses a substring match by default.
 *
 * @param page - Playwright page instance
 * @param selector - CSS selector for the target element
 * @param expectedText - Text that the element should contain
 * @param options - Optional: { exact: true } for exact match
 * @param message - Optional custom assertion message for debugging
 */
export async function assertElementText(
  page: Page,
  selector: string,
  expectedText: string,
  options?: { exact?: boolean },
  message?: string,
): Promise<void> {
  const locator = page.locator(selector).first();
  const assertionMessage = message ?? `Expected element "${selector}" to contain text "${expectedText}"`;

  if (options?.exact) {
    await expect(locator, assertionMessage).toHaveText(expectedText);
  } else {
    await expect(locator, assertionMessage).toContainText(expectedText);
  }
}

/**
 * Assert that an element's text content matches a regular expression.
 *
 * @param page - Playwright page instance
 * @param selector - CSS selector for the target element
 * @param pattern - Regular expression to match against the element's text
 * @param message - Optional custom assertion message for debugging
 */
export async function assertElementTextMatches(
  page: Page,
  selector: string,
  pattern: RegExp,
  message?: string,
): Promise<void> {
  const locator = page.locator(selector).first();
  await expect(locator, message ?? `Expected element "${selector}" text to match ${pattern}`).toHaveText(pattern);
}

// ============================================================
// URL path assertions
// ============================================================

/**
 * Assert that the current page URL path matches the expected path.
 * Useful for verifying SPA navigation without caring about the base URL.
 *
 * @param page - Playwright page instance
 * @param expectedPath - Expected URL path (e.g., '/settings', '/video-restore')
 * @param message - Optional custom assertion message for debugging
 */
export async function assertUrlPath(
  page: Page,
  expectedPath: string,
  message?: string,
): Promise<void> {
  const currentUrl = page.url();
  const url = new URL(currentUrl);
  const actualPath = url.pathname;

  const assertionMessage = message
    ?? `Expected URL path to be "${expectedPath}", but got "${actualPath}"`;

  expect(actualPath, assertionMessage).toBe(expectedPath);
}

/**
 * Assert that the current page URL path starts with the given prefix.
 * Useful for parameterized routes.
 *
 * @param page - Playwright page instance
 * @param pathPrefix - Expected URL path prefix
 * @param message - Optional custom assertion message for debugging
 */
export async function assertUrlPathStartsWith(
  page: Page,
  pathPrefix: string,
  message?: string,
): Promise<void> {
  const currentUrl = page.url();
  const url = new URL(currentUrl);
  const actualPath = url.pathname;

  const assertionMessage = message
    ?? `Expected URL path to start with "${pathPrefix}", but got "${actualPath}"`;

  expect(actualPath.startsWith(pathPrefix), assertionMessage).toBe(true);
}

// ============================================================
// Theme assertions
// ============================================================

/**
 * Assert that the application is using the specified theme.
 *
 * The SeedVR2 UI supports dark and light themes, typically controlled
 * via a CSS class on the <html> or <body> element, or a data attribute.
 *
 * @param page - Playwright page instance
 * @param expectedTheme - Expected theme: 'dark' or 'light'
 * @param message - Optional custom assertion message for debugging
 */
export async function assertTheme(
  page: Page,
  expectedTheme: 'dark' | 'light',
  message?: string,
): Promise<void> {
  const assertionMessage = message ?? `Expected theme to be "${expectedTheme}"`;

  // Check for theme class or data attribute on the root element
  const rootLocator = page.locator('html');

  // Strategy 1: Check for class-based theme (e.g., class="dark" or class="light")
  const hasThemeClass = await rootLocator.evaluate((el, theme) => {
    return el.classList.contains(theme) || el.classList.contains(`theme-${theme}`);
  }, expectedTheme);

  if (hasThemeClass) {
    expect(hasThemeClass, assertionMessage).toBe(true);
    return;
  }

  // Strategy 2: Check for data-theme attribute (e.g., data-theme="dark")
  const dataTheme = await rootLocator.getAttribute('data-theme');
  if (dataTheme !== null) {
    expect(dataTheme, assertionMessage).toBe(expectedTheme);
    return;
  }

  // Strategy 3: Check for color-scheme CSS media query or property
  const colorScheme = await rootLocator.evaluate((el) => {
    return getComputedStyle(el).colorScheme || getComputedStyle(document.body).colorScheme;
  });
  expect(colorScheme, assertionMessage).toContain(expectedTheme);
}

// ============================================================
// Badge status assertions
// ============================================================

/**
 * Assert that a status badge element displays the expected status text
 * and optionally has the correct status class/color.
 *
 * Common badge statuses in SeedVR2:
 * - Model: 'loaded', 'loading', 'unloaded', 'error'
 * - Task: 'completed', 'processing', 'failed', 'pending'
 *
 * @param page - Playwright page instance
 * @param selector - CSS selector for the badge element
 * @param expectedStatus - Expected status text displayed in the badge
 * @param options - Optional: { statusClass: 'badge-success' } to also verify the CSS class
 * @param message - Optional custom assertion message for debugging
 */
export async function assertBadgeStatus(
  page: Page,
  selector: string,
  expectedStatus: string,
  options?: { statusClass?: string },
  message?: string,
): Promise<void> {
  const locator = page.locator(selector).first();

  // Assert the badge is visible
  await expect(
    locator,
    message ?? `Expected badge "${selector}" to be visible`,
  ).toBeVisible();

  // Assert the badge text matches the expected status
  await expect(
    locator,
    message ?? `Expected badge "${selector}" to show status "${expectedStatus}"`,
  ).toContainText(expectedStatus, { ignoreCase: true });

  // Optionally assert the badge has the correct status class
  if (options?.statusClass) {
    const hasClass = await locator.evaluate(
      (el, cls) => el.classList.contains(cls),
      options.statusClass,
    );
    expect(
      hasClass,
      message ?? `Expected badge "${selector}" to have class "${options.statusClass}"`,
    ).toBe(true);
  }
}

/**
 * Assert the model status badge shows the expected model state.
 * Convenience wrapper around assertBadgeStatus for the model status badge.
 *
 * @param page - Playwright page instance
 * @param expectedState - Expected model state: 'loaded', 'loading', 'unloaded', 'error'
 */
export async function assertModelStatus(
  page: Page,
  expectedState: 'loaded' | 'loading' | 'unloaded' | 'error',
): Promise<void> {
  const statusClassMap: Record<string, string> = {
    loaded: 'badge-success',
    loading: 'badge-warning',
    unloaded: 'badge-secondary',
    error: 'badge-danger',
  };

  await assertBadgeStatus(
    page,
    '.model-status-badge, [data-testid="model-status"]',
    expectedState,
    { statusClass: statusClassMap[expectedState] },
    `Expected model status badge to show "${expectedState}"`,
  );
}

// ============================================================
// Progress value assertions
// ============================================================

/**
 * Assert that a progress bar element has the expected progress value.
 *
 * Supports multiple progress bar implementations:
 * - HTML <progress> element with value attribute
 * - ARIA progressbar with aria-valuenow attribute
 * - CSS-based progress bars with width percentage
 *
 * @param page - Playwright page instance
 * @param selector - CSS selector for the progress element
 * @param expectedValue - Expected progress value (0-100 for percentage, 0-1 for ratio)
 * @param options - Optional: { tolerance: 0.5 } for floating point comparison
 * @param message - Optional custom assertion message for debugging
 */
export async function assertProgressValue(
  page: Page,
  selector: string,
  expectedValue: number,
  options?: { tolerance?: number },
  message?: string,
): Promise<void> {
  const locator = page.locator(selector).first();
  const tolerance = options?.tolerance ?? 1.0;

  // Ensure the progress element is visible
  await expect(locator, `Expected progress element "${selector}" to be visible`).toBeVisible();

  // Try to read the progress value from aria-valuenow
  const ariaValue = await locator.getAttribute('aria-valuenow').catch(() => null);
  if (ariaValue !== null) {
    const actualValue = parseFloat(ariaValue);
    const assertionMessage = message
      ?? `Expected progress value to be ${expectedValue}, but got ${actualValue}`;
    expect(Math.abs(actualValue - expectedValue), assertionMessage).toBeLessThanOrEqual(tolerance);
    return;
  }

  // Try to read the value attribute (for <progress> elements)
  const valueAttr = await locator.getAttribute('value').catch(() => null);
  const maxAttr = await locator.getAttribute('max').catch(() => null);
  if (valueAttr !== null) {
    const value = parseFloat(valueAttr);
    const max = maxAttr ? parseFloat(maxAttr) : 1;
    const actualPercent = (value / max) * 100;
    const expectedPercent = expectedValue <= 1 ? expectedValue * 100 : expectedValue;
    const assertionMessage = message
      ?? `Expected progress to be ${expectedPercent}%, but got ${actualPercent}%`;
    expect(Math.abs(actualPercent - expectedPercent), assertionMessage).toBeLessThanOrEqual(tolerance);
    return;
  }

  // Try to read the width percentage from CSS
  const widthPercent = await locator.evaluate((el: Element) => {
    const inner = el.querySelector('.progress-bar-fill, .ant-progress-bg, .el-progress-bar__inner')
      ?? el;
    const width = (inner as HTMLElement).style.width
      || (inner as HTMLElement).style.getPropertyValue('width');
    const match = width.match(/(\d+(?:\.\d+)?)%/);
    return match ? parseFloat(match[1]) : null;
  });

  if (widthPercent !== null) {
    const expectedPercent = expectedValue <= 1 ? expectedValue * 100 : expectedValue;
    const assertionMessage = message
      ?? `Expected progress width to be ${expectedPercent}%, but got ${widthPercent}%`;
    expect(Math.abs(widthPercent - expectedPercent), assertionMessage).toBeLessThanOrEqual(tolerance);
    return;
  }

  throw new Error(
    `Could not determine progress value for element "${selector}". ` +
    'Ensure the element has aria-valuenow, value/max attributes, or a width style.',
  );
}

/**
 * Assert that a progress bar is at 100% (complete).
 *
 * @param page - Playwright page instance
 * @param selector - CSS selector for the progress element
 * @param message - Optional custom assertion message for debugging
 */
export async function assertProgressComplete(
  page: Page,
  selector: string,
  message?: string,
): Promise<void> {
  await assertProgressValue(page, selector, 100, { tolerance: 0.5 }, message ?? 'Expected progress to be complete (100%)');
}

/**
 * Assert that a progress bar is at 0% (not started).
 *
 * @param page - Playwright page instance
 * @param selector - CSS selector for the progress element
 * @param message - Optional custom assertion message for debugging
 */
export async function assertProgressNotStarted(
  page: Page,
  selector: string,
  message?: string,
): Promise<void> {
  await assertProgressValue(page, selector, 0, { tolerance: 0.5 }, message ?? 'Expected progress to be 0%');
}

/**
 * Explicit wait utilities for SeedVR2 WebUI E2E tests.
 *
 * Provides higher-level wait functions that go beyond Playwright's
 * built-in auto-waiting, specifically tailored for the SeedVR2 UI:
 * - Waiting for API responses after user actions
 * - Waiting for UI elements to become visible/hidden
 * - Waiting for toast notifications
 * - Waiting for progress bars to complete
 * - Waiting for loading indicators to disappear
 *
 * Usage:
 *   import { waitForApiResponse, waitForToast } from '@utils/wait-helpers';
 *   await waitForApiResponse(page, '/api/system/model/status');
 *   await waitForToast(page, 'Model loaded successfully');
 */
import { Page, Response, Locator } from '@playwright/test';

// ============================================================
// API response waits
// ============================================================

/**
 * Wait for an API response matching the specified URL pattern.
 *
 * Useful for verifying that a user action (e.g., clicking a button)
 * triggers the expected backend request.
 *
 * @param page - Playwright page instance
 * @param urlPattern - Substring or regex to match the request URL
 * @param timeout - Maximum wait time in milliseconds (default: 10000)
 * @returns The matching Response object
 * @throws TimeoutError if no matching response is received within the timeout
 */
export async function waitForApiResponse(
  page: Page,
  urlPattern: string | RegExp,
  timeout = 10000,
): Promise<Response> {
  return page.waitForResponse(
    (response) => {
      const url = response.url();
      if (typeof urlPattern === 'string') {
        return url.includes(urlPattern);
      }
      return urlPattern.test(url);
    },
    { timeout },
  );
}

/**
 * Wait for a successful (2xx) API response matching the URL pattern.
 *
 * @param page - Playwright page instance
 * @param urlPattern - Substring or regex to match the request URL
 * @param timeout - Maximum wait time in milliseconds (default: 10000)
 * @returns The matching Response object
 */
export async function waitForSuccessfulApiResponse(
  page: Page,
  urlPattern: string | RegExp,
  timeout = 10000,
): Promise<Response> {
  return page.waitForResponse(
    (response) => {
      const url = response.url();
      const matchesUrl = typeof urlPattern === 'string'
        ? url.includes(urlPattern)
        : urlPattern.test(url);
      return matchesUrl && response.status() >= 200 && response.status() < 300;
    },
    { timeout },
  );
}

// ============================================================
// Element visibility waits
// ============================================================

/**
 * Wait for an element to become visible in the DOM.
 *
 * @param locator - Playwright locator for the target element
 * @param timeout - Maximum wait time in milliseconds (default: 10000)
 */
export async function waitForElementVisible(
  locator: Locator,
  timeout = 10000,
): Promise<void> {
  await locator.waitFor({ state: 'visible', timeout });
}

/**
 * Wait for an element to become hidden or detached from the DOM.
 *
 * @param locator - Playwright locator for the target element
 * @param timeout - Maximum wait time in milliseconds (default: 10000)
 */
export async function waitForElementHidden(
  locator: Locator,
  timeout = 10000,
): Promise<void> {
  await locator.waitFor({ state: 'hidden', timeout });
}

// ============================================================
// Toast notification waits
// ============================================================

/**
 * Wait for a toast notification to appear with specific text.
 *
 * The SeedVR2 UI uses toast notifications for success/error messages.
 * This function waits for a toast element containing the expected text.
 *
 * @param page - Playwright page instance
 * @param expectedText - Text content to look for in the toast (substring match)
 * @param timeout - Maximum wait time in milliseconds (default: 10000)
 * @returns The toast locator for further assertions
 */
export async function waitForToast(
  page: Page,
  expectedText?: string,
  timeout = 10000,
): Promise<Locator> {
  // Common toast/notification selectors used in the SeedVR2 UI
  const toastSelectors = [
    '.sv-toast',
    '#toastContainer .sv-toast',
    '.toast',
    '[role="alert"]',
    '.notification',
  ];

  // Wait for any toast element to appear
  const toastLocator = page.locator(toastSelectors.join(', ')).first();
  await toastLocator.waitFor({ state: 'visible', timeout });

  // If specific text is expected, further filter the toast
  if (expectedText) {
    const textToast = page.locator(toastSelectors.join(', ')).filter({ hasText: expectedText }).first();
    await textToast.waitFor({ state: 'visible', timeout });
    return textToast;
  }

  return toastLocator;
}

/**
 * Wait for a success toast notification to appear.
 *
 * @param page - Playwright page instance
 * @param expectedText - Optional text to match in the success toast
 * @param timeout - Maximum wait time in milliseconds (default: 10000)
 */
export async function waitForSuccessToast(
  page: Page,
  expectedText?: string,
  timeout = 10000,
): Promise<Locator> {
  const successSelectors = [
    '.sv-toast.toast-success',
    '#toastContainer .sv-toast.toast-success',
    '.toast.success',
    '.toast.toast-success',
  ];

  let locator = page.locator(successSelectors.join(', ')).first();

  if (expectedText) {
    locator = page.locator(successSelectors.join(', ')).filter({ hasText: expectedText }).first();
  }

  await locator.waitFor({ state: 'visible', timeout });
  return locator;
}

/**
 * Wait for an error toast notification to appear.
 *
 * @param page - Playwright page instance
 * @param expectedText - Optional text to match in the error toast
 * @param timeout - Maximum wait time in milliseconds (default: 10000)
 */
export async function waitForErrorToast(
  page: Page,
  expectedText?: string,
  timeout = 10000,
): Promise<Locator> {
  const errorSelectors = [
    '.sv-toast.toast-error',
    '#toastContainer .sv-toast.toast-error',
    '.toast.error',
    '.toast.toast-error',
  ];

  let locator = page.locator(errorSelectors.join(', ')).first();

  if (expectedText) {
    locator = page.locator(errorSelectors.join(', ')).filter({ hasText: expectedText }).first();
  }

  await locator.waitFor({ state: 'visible', timeout });
  return locator;
}

// ============================================================
// Progress bar waits
// ============================================================

/**
 * Wait for a progress bar or progress indicator to reach 100% (complete).
 *
 * Polls the progress element's value or width style until it reaches
 * completion, or until the progress element disappears (indicating
 * the task is done).
 *
 * @param page - Playwright page instance
 * @param progressSelector - CSS selector for the progress element
 * @param timeout - Maximum wait time in milliseconds (default: 60000)
 */
export async function waitForProgressComplete(
  page: Page,
  progressSelector = '.progress-bar, [role="progressbar"], .ant-progress, .el-progress',
  timeout = 60000,
): Promise<void> {
  const progressLocator = page.locator(progressSelector).first();
  const startTime = Date.now();

  while (Date.now() - startTime < timeout) {
    // Check if the progress element still exists
    const isVisible = await progressLocator.isVisible().catch(() => false);

    if (!isVisible) {
      // Progress element disappeared — task likely completed
      return;
    }

    // Try to read the progress value from aria-valuenow attribute
    const ariaValue = await progressLocator.getAttribute('aria-valuenow').catch(() => null);
    if (ariaValue !== null) {
      const progress = parseFloat(ariaValue);
      if (progress >= 100 || progress >= 1.0) {
        return;
      }
    }

    // Try to read the progress from the element's width style
    const widthStyle = await progressLocator.evaluate((el: Element) => {
      const inner = el.querySelector('.progress-bar-fill, .ant-progress-bg, .el-progress-bar__inner')
        ?? el;
      return (inner as HTMLElement).style.width || (inner as HTMLElement).style.getPropertyValue('width');
    }).catch(() => '');

    if (widthStyle) {
      const percentMatch = widthStyle.match(/(\d+(?:\.\d+)?)%/);
      if (percentMatch) {
        const percent = parseFloat(percentMatch[1]);
        if (percent >= 100) {
          return;
        }
      }
    }

    // Wait before polling again
    await page.waitForTimeout(500);
  }

  throw new Error(`Progress did not complete within ${timeout}ms`);
}

// ============================================================
// Loading indicator waits
// ============================================================

/**
 * Wait for all loading indicators to disappear from the page.
 *
 * This is useful as a pre-condition before interacting with the UI,
 * ensuring that the page has finished loading data.
 *
 * @param page - Playwright page instance
 * @param loadingSelector - CSS selector for loading indicators
 * @param timeout - Maximum wait time in milliseconds (default: 30000)
 */
export async function waitForLoadingComplete(
  page: Page,
  loadingSelector = '.loading, .spinner, .ant-spin, .el-loading-mask, [data-loading="true"], .skeleton',
  timeout = 30000,
): Promise<void> {
  const loadingLocator = page.locator(loadingSelector);
  const count = await loadingLocator.count();

  if (count === 0) {
    // No loading indicators found, page is ready
    return;
  }

  // Wait for all loading indicators to become hidden
  await loadingLocator.last().waitFor({ state: 'hidden', timeout });
}

/**
 * Wait for a specific network idle state after triggering an action.
 *
 * Uses Playwright's waitForLoadState to ensure the page has finished
 * loading network resources.
 *
 * @param page - Playwright page instance
 * @param state - Load state to wait for: 'load', 'domcontentloaded', or 'networkidle'
 * @param timeout - Maximum wait time in milliseconds (default: 30000)
 */
export async function waitForNetworkIdle(
  page: Page,
  state: 'load' | 'domcontentloaded' | 'networkidle' = 'networkidle',
  timeout = 30000,
): Promise<void> {
  await page.waitForLoadState(state, { timeout });
}

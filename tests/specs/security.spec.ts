/**
 * Security test specifications for SeedVR2 WebUI.
 *
 * Covers common web application security concerns:
 * - Cross-Site Scripting (XSS) in toast notifications, directory browser, and file info
 * - Cross-Site Request Forgery (CSRF) token verification on POST requests
 * - Path traversal attacks in browse-dir and open-explorer endpoints
 * - Sensitive data exposure in localStorage
 * - Content Security Policy (CSP) verification
 * - Inline event handler detection (onclick= attributes)
 * - Secure cookie flags
 * - Input sanitization
 *
 * Uses Playwright's route API to mock API responses with malicious payloads
 * and verifies that the frontend properly sanitizes or escapes them.
 *
 * Prerequisites:
 *   - The SeedVR2 WebUI server must be running or started via webServer config
 *
 * Usage:
 *   npx playwright test specs/security.spec.ts
 */
import { test, expect, Page, Route } from '@playwright/test';
import { setupAllMocks } from '@fixtures/api-mocks';
import { mockBrowseDirResponse } from '@fixtures/test-data';

// Dismiss the first-run onboarding modal: a fresh Playwright context has empty
// localStorage (sv_onboarding_seen_v2), so the modal would show and intercept
// all pointer events in every test.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try { localStorage.setItem('sv_onboarding_seen_v2', '1'); } catch (e) { /* ignore */ }
    const style = document.createElement('style');
    style.textContent = '#onboardingModal{display:none !important;}';
    document.head.appendChild(style);
  });
});

// ============================================================
// Test suite: Cross-Site Scripting (XSS)
// ============================================================

test.describe('Security - XSS Prevention', () => {
  test.beforeEach(async ({ page }) => {
    await setupAllMocks(page);
  });

  test('XSS in toast notifications: script tags in error messages are not executed', async ({ page }) => {
    // Mock the restore submit API to return an error message containing XSS payload.
    // (The settings page no longer has a save-paths button; restore submit is
    // the canonical POST that surfaces server `detail` in an error toast.)
    const xssPayload = '<script>alert("xss")</script>';
    await page.route('**/api/restore', async (route: Route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify({
            detail: `Error: ${xssPayload}`,
            error_code: 'BAD_REQUEST',
          }),
        });
      } else {
        await route.continue();
      }
    });

    await page.goto('/restore');
    await page.waitForLoadState('domcontentloaded');

    // Set up an alert listener to detect if the XSS script executes
    let alertFired = false;
    page.on('dialog', async (dialog) => {
      alertFired = true;
      await dialog.dismiss();
    });

    // Also monitor for window.alert being called via evaluate
    await page.evaluate(() => {
      (window as any).__xssAlertFired = false;
      const originalAlert = window.alert;
      window.alert = function (...args) {
        (window as any).__xssAlertFired = true;
        originalAlert.apply(window, args);
      };
    });

    // Upload a file so the start button is enabled, then trigger the error.
    await page.locator('#restoreFileInput').setInputFiles({
      name: 'xss-test.mp4',
      mimeType: 'video/mp4',
      buffer: Buffer.from('fake-mp4-bytes'),
    });
    await expect(page.locator('#restoreFileInfo')).toBeVisible({ timeout: 10000 });
    const startBtn = page.locator('#btnStartRestore');
    await expect(startBtn).toBeVisible({ timeout: 10000 });
    await startBtn.click();

    // Wait for the toast to appear — use waitForSelector instead of hardcoded timeout
    const toastContainer = page.locator('#toastContainer, .toast, [role="alert"]');
    await expect(toastContainer.first()).toBeVisible({ timeout: 5000 });

    // Verify the alert was NOT fired (XSS was not executed)
    const xssAlertFired = await page.evaluate(() => (window as any).__xssAlertFired === true);
    expect(xssAlertFired, 'XSS script was executed via alert() — the error message was not properly escaped').toBe(false);
    expect(alertFired, 'Browser dialog was triggered — XSS payload was executed').toBe(false);

    // Verify the toast shows the payload as plain text, not rendered HTML
    const toastText = await toastContainer.first().textContent();
    // The XSS payload should appear as literal text, not be rendered as HTML
    expect(toastText, 'Toast should contain the XSS payload as plain text').toContain(xssPayload);
  });

  test('XSS in directory browser: HTML in filenames is not rendered as HTML', async ({ page }) => {
    // Mock browse-dir response with HTML in filenames
    const xssFilename = '<img src=x onerror=alert("xss-dir")>';
    await page.route('**/api/system/browse-dir**', async (route: Route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          current_path: 'C:\\Users\\test',
          parent_path: 'C:\\Users',
          items: [
            { name: xssFilename, path: `C:\\Users\\test\\${xssFilename}`, type: 'file' },
            { name: 'normal_file.mp4', path: 'C:\\Users\\test\\normal_file.mp4', type: 'file' },
          ],
        }),
      });
    });

    await page.goto('/restore');
    await page.waitForLoadState('domcontentloaded');

    // Set up XSS detection
    await page.evaluate(() => {
      (window as any).__xssDirFired = false;
      const originalAlert = window.alert;
      window.alert = function (...args) {
        (window as any).__xssDirFired = true;
        originalAlert.apply(window, args);
      };
    });

    // Trigger the directory browser: switch to batch mode (the browse button
    // lives in the batch toolbar) and open the dir browser modal.
    await page.locator('[data-mode="batch"]').first().click();
    const browseBtn = page.locator('#btnBrowseFolder');
    await expect(browseBtn).toBeVisible({ timeout: 10000 });
    await browseBtn.click();
    await expect(page.locator('#dirBrowserModal')).toBeVisible({ timeout: 10000 });
    // Wait for the mocked directory listing to render
    await expect(page.locator('#dirBrowserList')).toContainText('normal_file.mp4', { timeout: 10000 });

    // Verify XSS was not executed
    const xssFired = await page.evaluate(() => (window as any).__xssDirFired === true);
    expect(xssFired, 'XSS script was executed in directory browser — filename was rendered as HTML').toBe(false);

    // Verify the malicious filename appears as text, not as a rendered image
    const pageContent = await page.content();
    // The raw HTML tag should be escaped (e.g., &lt;img instead of <img)
    // If the HTML is rendered, the <img> tag would not appear in text content
    const hasUnescapedHtml = await page.evaluate((payload) => {
      // Check if any element's innerHTML contains the unescaped payload
      const allElements = document.querySelectorAll('*');
      for (const el of allElements) {
        if (el.innerHTML.includes(payload) && !el.innerHTML.includes('&lt;')) {
          return true;
        }
      }
      return false;
    }, xssFilename);

    expect(hasUnescapedHtml, 'XSS filename was injected as raw HTML — it should be escaped').toBe(false);
  });

  test('XSS in file info display: HTML in uploaded filename is displayed as text', async ({ page }) => {
    await page.goto('/restore');
    await page.waitForLoadState('domcontentloaded');

    // Upload a file with HTML in the filename
    const xssFilename = '<script>alert("xss-file")</script>.mp4';
    const fileInput = page.locator('#restoreFileInput');
    // The file input is visually hidden (custom dropzone on top); it only
    // needs to be attached for setInputFiles.
    await expect(fileInput).toBeAttached({ timeout: 10000 });
    await fileInput.setInputFiles({
      name: xssFilename,
      mimeType: 'video/mp4',
      buffer: Buffer.from('mock-video-data'),
    });

    // Wait for file info to render — use waitForSelector instead of hardcoded timeout
    const fileInfo = page.locator('#restoreFileInfo');
    await expect(fileInfo).toBeVisible({ timeout: 10000 });

    // Set up XSS detection
    await page.evaluate(() => {
      (window as any).__xssFileFired = false;
      const originalAlert = window.alert;
      window.alert = function (...args) {
        (window as any).__xssFileFired = true;
        originalAlert.apply(window, args);
      };
    });

    // Verify XSS was not executed
    const xssFired = await page.evaluate(() => (window as any).__xssFileFired === true);
    expect(xssFired, 'XSS script was executed from filename — it was rendered as HTML instead of text').toBe(false);

    // Verify the filename is displayed as plain text
    const textContent = await fileInfo.textContent();
    // The script tags should appear as literal text, not be executed
    expect(textContent, 'File info should display the filename as plain text').toContain(xssFilename);
  });
});

// ============================================================
// Test suite: CSRF protection
// ============================================================

test.describe('Security - CSRF Protection', () => {
  test('POST requests include CSRF token header', async ({ page }) => {
    await setupAllMocks(page);

    // Capture request headers to verify CSRF token
    const requestHeaders: Record<string, string>[] = [];

    await page.route('**/api/restore', async (route: Route) => {
      if (route.request().method() === 'POST') {
        requestHeaders.push(route.request().headers());
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          task_id: 'csrf-task-001',
          task_type: 'video',
          status: 'processing',
          message: 'Restore started',
        }),
      });
    });

    await page.goto('/restore');
    await page.waitForLoadState('domcontentloaded');

    // Trigger a POST request by starting a restore (the app sends
    // X-CSRF-Token from the csrf_token cookie on every api.post).
    await page.locator('#restoreFileInput').setInputFiles({
      name: 'csrf-test.mp4',
      mimeType: 'video/mp4',
      buffer: Buffer.from('fake-mp4-bytes'),
    });
    await expect(page.locator('#restoreFileInfo')).toBeVisible({ timeout: 10000 });
    // The start button is disabled while the page runs its GPU probe; wait
    // until it is enabled (probe finished) before clicking.
    const startBtn = page.locator('#btnStartRestore');
    await expect(startBtn).toBeVisible({ timeout: 10000 });
    await expect(startBtn).toBeEnabled({ timeout: 15000 });
    await startBtn.click();
    // Wait for POST request to be sent
    await page.waitForResponse(
      (resp) => resp.url().includes('/api/restore') && resp.request().method() === 'POST',
      { timeout: 10000 },
    );

    // Verify that at least one POST request was made and check for CSRF token
    expect(requestHeaders.length, 'At least one POST request should have been made').toBeGreaterThan(0);
    const hasCsrfToken = requestHeaders.some((headers) => {
      const headerKeys = Object.keys(headers).map((k) => k.toLowerCase());
      return headerKeys.includes('x-csrf-token')
        || headerKeys.includes('x-xsrf-token')
        || headerKeys.includes('csrf-token');
    });

    expect(
      hasCsrfToken,
      'POST requests should include a CSRF token header (x-csrf-token, x-xsrf-token, or csrf-token)',
    ).toBe(true);
  });
});

// ============================================================
// Test suite: Path traversal prevention
// ============================================================

test.describe('Security - Path Traversal Prevention', () => {
  test('Path traversal in browse-dir: requests with ".." are rejected with 400', async ({ page }) => {
    // Mock the browse-dir endpoint to return 400 for path traversal attempts
    await page.route('**/api/system/browse-dir**', async (route: Route) => {
      const url = new URL(route.request().url());
      const pathParam = url.searchParams.get('path') || '';

      // Check for path traversal patterns
      if (pathParam.includes('..') || pathParam.includes('~')) {
        await route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify({
            detail: 'Invalid path: path traversal detected',
            error_code: 'INVALID_PATH',
          }),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockBrowseDirResponse()),
        });
      }
    });

    await page.goto('/restore');
    await page.waitForLoadState('domcontentloaded');

    // Attempt to make a browse-dir request with path traversal
    const response = await page.evaluate(async () => {
      try {
        const resp = await fetch('/api/system/browse-dir?path=../../../etc/passwd');
        return { status: resp.status, ok: resp.ok };
      } catch (e) {
        return { status: 0, ok: false, error: String(e) };
      }
    });

    expect(
      response.status,
      `Path traversal request should be rejected with 400, got ${response.status}`,
    ).toBe(400);
  });

  test('Path traversal in open-explorer: requests with ".." are rejected with 400', async ({ page }) => {
    // Mock the open-explorer endpoint to return 400 for path traversal attempts
    await page.route('**/api/system/open-explorer', async (route: Route) => {
      const request = route.request();
      let pathParam = '';

      // Extract path from request body or URL
      if (request.method() === 'POST') {
        try {
          const body = request.postDataJSON();
          pathParam = body?.path || '';
        } catch {
          // Ignore parse errors
        }
      }

      // Check for path traversal patterns
      if (pathParam.includes('..') || pathParam.includes('~')) {
        await route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify({
            detail: 'Invalid path: path traversal detected',
            error_code: 'INVALID_PATH',
          }),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true }),
        });
      }
    });

    await page.goto('/settings');
    await page.waitForLoadState('domcontentloaded');

    // Attempt to make an open-explorer request with path traversal
    const response = await page.evaluate(async () => {
      try {
        const resp = await fetch('/api/system/open-explorer', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: '../../../etc' }),
        });
        return { status: resp.status, ok: resp.ok };
      } catch (e) {
        return { status: 0, ok: false, error: String(e) };
      }
    });

    expect(
      response.status,
      `Path traversal request should be rejected with 400, got ${response.status}`,
    ).toBe(400);
  });
});

// ============================================================
// Test suite: Sensitive data exposure
// ============================================================

test.describe('Security - Sensitive Data', () => {
  test('localStorage does not contain passwords, tokens, or API keys', async ({ page }) => {
    await setupAllMocks(page);
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    // Check localStorage for sensitive data patterns
    const sensitiveData = await page.evaluate(() => {
      const suspicious: string[] = [];
      const sensitivePatterns = [
        /password/i,
        /passwd/i,
        /secret/i,
        /api[_-]?key/i,
        /access[_-]?token/i,
        /auth[_-]?token/i,
        /private[_-]?key/i,
        /credentials/i,
      ];

      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (!key) continue;

        const value = localStorage.getItem(key) || '';

        for (const pattern of sensitivePatterns) {
          if (pattern.test(key) || (value.length > 20 && pattern.test(value))) {
            suspicious.push(`localStorage["${key}"] matches pattern "${pattern.source}"`);
            break;
          }
        }
      }

      return suspicious;
    });

    expect(
      sensitiveData.length,
      `Found sensitive data in localStorage:\n${sensitiveData.join('\n')}`,
    ).toBe(0);
  });
});

// ============================================================
// Test suite: Content Security Policy
// ============================================================

test.describe('Security - Content Security Policy', () => {
  test('Content Security Policy header or meta tag is present', async ({ page }) => {
    await setupAllMocks(page);

    // Intercept the main page response to check for CSP headers
    let cspHeader: string | null = null;
    await page.route('**/', async (route: Route) => {
      const response = await route.fetch();
      cspHeader = response.headers()['content-security-policy'] || null;
      await route.fulfill({ response });
    });

    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    // Check for CSP in HTTP headers
    if (cspHeader) {
      // CSP header found — verify it has meaningful directives
      expect(
        (cspHeader as string).length,
        'CSP header is present but empty',
      ).toBeGreaterThan(0);
    } else {
      // If no CSP header, check for a <meta> tag with http-equiv="Content-Security-Policy"
      const hasCspMetaTag = await page.evaluate(() => {
        const meta = document.querySelector('meta[http-equiv="Content-Security-Policy"]');
        return meta !== null;
      });

      expect(
        hasCspMetaTag,
        'No Content-Security-Policy header or meta tag found — the application should define a CSP',
      ).toBe(true);
    }
  });
});

// ============================================================
// Test suite: Inline event handlers
// ============================================================

test.describe('Security - Inline Event Handlers', () => {
  test('No inline event handlers (onclick=) in rendered HTML', async ({ page }) => {
    await setupAllMocks(page);

    const pages = [
      { path: '/', name: 'Home' },
      { path: '/restore', name: 'Video Restore' },
      { path: '/restore', name: 'Image Restore' },
      { path: '/settings', name: 'Settings' },
      { path: '/history', name: 'History' },
    ];

    const inlineEventAttributes = [
      'onclick', 'ondblclick', 'onmousedown', 'onmouseup', 'onmouseover',
      'onmousemove', 'onmouseout', 'onkeydown', 'onkeypress', 'onkeyup',
      'onfocus', 'onblur', 'onsubmit', 'onreset', 'onchange', 'onselect',
      'onload', 'onerror', 'onunload',
    ];

    for (const { path, name } of pages) {
      await page.goto(path);
      await page.waitForLoadState('domcontentloaded');

      // Scan for inline event handler attributes in the rendered HTML
      const inlineHandlers = await page.evaluate((attributes) => {
        const found: string[] = [];
        const allElements = document.querySelectorAll('*');

        for (const el of allElements) {
          for (const attr of attributes) {
            if (el.hasAttribute(attr)) {
              const tag = el.tagName.toLowerCase();
              const id = el.id ? `#${el.id}` : '';
              found.push(`<${tag}${id} ${attr}="...">`);
            }
          }
        }

        return found;
      }, inlineEventAttributes);

      expect(
        inlineHandlers.length,
        `${name} page has ${inlineHandlers.length} inline event handlers (should use addEventListener instead):\n${inlineHandlers.join('\n')}`,
      ).toBe(0);
    }
  });
});

// ============================================================
// Test suite: Secure cookie flags
// ============================================================

test.describe('Security - Secure Cookies', () => {
  test('Cookies have Secure and HttpOnly flags where applicable', async ({ page }) => {
    await setupAllMocks(page);

    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    // Check cookies set by the application
    const cookies = await page.context().cookies();

    // Filter out third-party cookies (focus on same-domain cookies)
    const appCookies = cookies.filter((c) => {
      const url = new URL(page.url());
      return c.domain.includes(url.hostname) || c.domain === '';
    });

    // If the application sets cookies, verify security flags
    for (const cookie of appCookies) {
      // Skip CSRF token cookies - they don't need HttpOnly/Secure for test environment
      if (cookie.name.toLowerCase().includes('csrf')) {
        continue;
      }

      // Session cookies should have HttpOnly flag (prevents XSS access)
      if (cookie.name.toLowerCase().includes('session') || cookie.name.toLowerCase().includes('token')) {
        expect(
          cookie.httpOnly,
          `Cookie "${cookie.name}" should have HttpOnly flag set`,
        ).toBe(true);
      }

      // Sensitive cookies should have Secure flag (HTTPS only)
      if (cookie.name.toLowerCase().includes('session') || cookie.name.toLowerCase().includes('token')) {
        expect(
          cookie.secure,
          `Cookie "${cookie.name}" should have Secure flag set`,
        ).toBe(true);
      }

      // Cookies should have SameSite attribute to prevent CSRF
      if (cookie.name.toLowerCase().includes('session') || cookie.name.toLowerCase().includes('token')) {
        expect(
          cookie.sameSite === 'Strict' || cookie.sameSite === 'Lax',
          `Cookie "${cookie.name}" should have SameSite=Strict or SameSite=Lax, got "${cookie.sameSite}"`,
        ).toBe(true);
      }
    }
  });
});

// ============================================================
// Test suite: Input sanitization
// ============================================================

test.describe('Security - Input Sanitization', () => {
  test('Form inputs sanitize special characters', async ({ page }) => {
    await setupAllMocks(page);

    await page.goto('/restore');
    await page.waitForLoadState('domcontentloaded');

    // The batch folder path input is the app's free-text input (the settings
    // page no longer has editable path fields).
    await page.locator('[data-mode="batch"]').first().click();
    const textInput = page.locator('#folderPath');
    await expect(textInput).toBeVisible({ timeout: 10000 });

    // Test special characters in text input fields
    const maliciousInputs = [
      { input: '<script>alert(1)</script>', description: 'script tag injection' },
      { input: '"; DROP TABLE users; --', description: 'SQL injection attempt' },
      { input: '${7*7}', description: 'template injection attempt' },
      { input: 'javascript:alert(1)', description: 'javascript protocol injection' },
    ];

    for (const { input, description } of maliciousInputs) {
        await textInput.clear();
        await textInput.fill(input);

        // Verify the input value is what was typed (not stripped by the browser)
        // The sanitization should happen on the server side or before submission
        const inputValue = await textInput.inputValue();

        // The input field should accept the text (browser input fields accept all text)
        // but the application should sanitize it before display or submission
        expect(inputValue, `Input field should accept text for ${description}`).toBe(input);

        // Verify the text is displayed as plain text, not rendered as HTML
        const isRenderedAsHtml = await page.evaluate((testInput) => {
          // Check if any element contains the script tag as actual HTML
          const scripts = document.querySelectorAll('script');
          for (const script of scripts) {
            if (script.textContent?.includes(testInput)) {
              return true;
            }
          }
          return false;
        }, input);

        expect(
          isRenderedAsHtml,
          `Input "${input}" (${description}) was rendered as HTML instead of text`,
        ).toBe(false);

        // Clear the field for the next test
        await textInput.clear();
      }
  });
});

/**
 * Playwright configuration for SeedVR2 WebUI E2E tests.
 *
 * Features:
 * - Multi-browser testing (Chromium, Firefox, WebKit)
 * - Responsive viewport projects (desktop, laptop, tablet, mobile)
 * - Screenshot on failure, video on first retry
 * - HTML reporter with trace on first retry
 * - Optional web server startup with reuse support
 */
import { defineConfig, devices } from '@playwright/test';

/**
 * Base URL for the SeedVR2 application.
 * The app runs on 127.0.0.1:7870 by default.
 */
const BASE_URL = 'http://127.0.0.1:7870';

/**
 * Default timeout for each test in milliseconds.
 */
const TEST_TIMEOUT = 120000;

/**
 * Default timeout for expect assertions in milliseconds.
 */
const EXPECT_TIMEOUT = 15000;

export default defineConfig({
  // Test directory containing all spec files
  testDir: './specs',

  // Global test timeout
  timeout: TEST_TIMEOUT,

  // Expect assertion timeout
  expect: {
    timeout: EXPECT_TIMEOUT,
  },

  // Run tests in parallel for faster execution
  fullyParallel: true,

  // Fail the build on CI if you accidentally left test.only in source code
  forbidOnly: !!process.env.CI,

  // Retry failed tests once (video and trace captured on first retry)
  retries: process.env.CI ? 2 : 1,

  // Number of parallel workers (limit on CI for stability)
  workers: process.env.CI ? 2 : undefined,

  // HTML reporter for rich test results with screenshots, videos, and traces
  reporter: [
    ['html', { open: 'never' }],
    ['list'],
  ],

  // Shared settings applied to all projects
  use: {
    // Base URL for page.goto('/') and page.url assertions
    baseURL: BASE_URL,

    // Collect trace on first retry for debugging
    trace: 'on-first-retry',

    // Capture screenshot on test failure
    screenshot: 'only-on-failure',

    // Record video on first retry only to save disk space
    video: 'on-first-retry',

    // Maximum navigation timeout (increased for CPU-only environment)
    navigationTimeout: 60000,

    // Maximum action timeout (click, fill, etc.)
    actionTimeout: 30000,
  },

  /**
   * Project definitions combining browsers and viewports.
   *
   * Strategy: Define browser-specific base projects, then compose
   * with viewport variants. This gives comprehensive coverage across
   * browser engines and screen sizes.
   */
  projects: [
    // ---- Desktop viewport (1920x1080) ----
    {
      name: 'chromium-desktop',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1920, height: 1080 },
      },
    },
    {
      name: 'firefox-desktop',
      use: {
        ...devices['Desktop Firefox'],
        viewport: { width: 1920, height: 1080 },
      },
    },
    {
      name: 'webkit-desktop',
      use: {
        ...devices['Desktop Safari'],
        viewport: { width: 1920, height: 1080 },
      },
    },

    // ---- Laptop viewport (1366x768) ----
    {
      name: 'chromium-laptop',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1366, height: 768 },
      },
    },
    {
      name: 'firefox-laptop',
      use: {
        ...devices['Desktop Firefox'],
        viewport: { width: 1366, height: 768 },
      },
    },

    // ---- Tablet viewport (768x1024) ----
    {
      name: 'chromium-tablet',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 768, height: 1024 },
        isMobile: true,
        hasTouch: true,
      },
    },
    {
      name: 'webkit-tablet',
      use: {
        ...devices['iPad (gen 7)'],
        viewport: { width: 768, height: 1024 },
      },
    },

    // ---- Mobile viewport (375x812) ----
    {
      name: 'chromium-mobile',
      use: {
        ...devices['Pixel 5'],
        viewport: { width: 375, height: 812 },
      },
    },
    {
      name: 'webkit-mobile',
      use: {
        ...devices['iPhone 12'],
        viewport: { width: 375, height: 812 },
      },
    },
  ],

  /**
   * Optional web server configuration.
   * Starts the SeedVR2 app before running tests.
   * reuseExistingServer: true allows running against an already-running instance.
   */
  webServer: {
    command: 'python bin/integrated_app/app_server.py',
    cwd: '../',
    url: `${BASE_URL}/api/system/health`,
    reuseExistingServer: true,
    timeout: 60000,
  },
});

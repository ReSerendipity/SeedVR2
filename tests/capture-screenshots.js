/**
 * SeedVR2 - Full Website Screenshot Capture
 *
 * Prerequisites:
 *   - SeedVR2 server running (default http://127.0.0.1:7870), start with start.bat
 *   - Playwright chromium installed: npm install && npx playwright install chromium
 *
 * Usage:
 *   node capture-screenshots.js
 *
 * Optional env overrides:
 *   SEEDVR2_BASE_URL  e.g. http://127.0.0.1:7870
 *   SEEDVR2_OUT_DIR   e.g. ./screenshots
 *
 * Output: screenshots/<viewport>/<theme>/<NN>-<name>.png
 *
 * NOTE: All selectors below are verified against the real templates in
 *       bin/integrated_app/templates/. Only UI-state toggles are clicked
 *       (advanced params, mode tabs, help panel, view toggle, FAQ details,
 *       locale dropdown, mobile nav). Action buttons that trigger real
 *       backend work (start restore, scan folder, start batch) are NOT
 *       clicked because they require preconditions (file selected / GPU).
 */
const { chromium } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

const BASE_URL = process.env.SEEDVR2_BASE_URL || 'http://127.0.0.1:7870';
const OUTPUT_DIR = process.env.SEEDVR2_OUT_DIR
  ? path.resolve(process.env.SEEDVR2_OUT_DIR)
  : path.join(__dirname, '..', 'screenshots');

const VIEWPORTS = {
  desktop: { width: 1920, height: 1080 },
  tablet: { width: 768, height: 1024, isMobile: true, hasTouch: true },
  mobile: { width: 375, height: 812, isMobile: true, hasTouch: true },
};

const THEMES = ['dark', 'light'];

function ensureDir(dir) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

async function screenshotPage(page, name, options = {}) {
  const {
    fullPage = true,
    waitFor = null,
    viewportName = 'desktop',
    theme = 'dark',
  } = options;

  const dir = path.join(OUTPUT_DIR, viewportName, theme);
  ensureDir(dir);

  const filePath = path.join(dir, `${name}.png`);

  if (waitFor) {
    await page.waitForTimeout(waitFor);
  }

  await page.screenshot({ path: filePath, fullPage });
  console.log(`  Captured: ${filePath}`);
}

async function setTheme(page, theme) {
  // Theme key 'sv-theme' is the real key used by base.html inline script
  // and static/js/app.js. Setting it before navigation + data-theme attr
  // is enough for a correct visual capture.
  await page.evaluate((t) => {
    localStorage.setItem('sv-theme', t);
    document.documentElement.setAttribute('data-theme', t);
  }, theme);
  await page.waitForTimeout(300);
}

async function safe(label, viewportName, theme, fn) {
  try {
    await fn();
  } catch (e) {
    console.error(`  [SKIP] ${label} (${viewportName}, ${theme}): ${e.message}`);
  }
}

async function captureHomePage(page, viewportName, theme) {
  console.log(`Capturing Home Page (${viewportName}, ${theme})...`);
  await page.goto(`${BASE_URL}/`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(3000);

  await screenshotPage(page, '01-home-full', { viewportName, theme });
}

async function captureRestorePage(page, viewportName, theme) {
  console.log(`Capturing Restore Page (${viewportName}, ${theme})...`);
  await page.goto(`${BASE_URL}/restore`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(3000);

  await screenshotPage(page, '02-restore-single-default', { viewportName, theme });

  // Advanced params expand: #advToggle toggles .open on #advParams.
  // JS click avoids any overlay interception; the onboarding modal is
  // suppressed globally via addInitScript (see main entry).
  await safe('restore-advanced-params', viewportName, theme, async () => {
    const advToggle = page.locator('#advToggle');
    if (await advToggle.count()) {
      await page.evaluate(() => {
        const el = document.getElementById('advToggle');
        if (el) el.click();
      });
      await page.waitForSelector('#advParams.open', { timeout: 5000 });
      await page.waitForTimeout(400);
      await screenshotPage(page, '03-restore-advanced-params-expanded', { viewportName, theme });
    }
  });

  // Batch mode: click [data-mode="batch"] tab to reveal batch pane
  await safe('restore-batch-mode', viewportName, theme, async () => {
    // re-enter single mode first to keep a clean starting state
    await page.goto(`${BASE_URL}/restore`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(1500);
    const batchTab = page.locator('[data-mode="batch"]');
    if (await batchTab.count()) {
      await batchTab.click();
      await page.waitForTimeout(500);
      await screenshotPage(page, '04-restore-batch-mode', { viewportName, theme });
    }
  });

  // Float help panel: #helpToggle toggles .sv-float-help--open on #floatHelp.
  // Use a JS click because on tablet/mobile the floating system-status widget
  // (#sysWidgetToggle) overlaps #helpToggle and intercepts real pointer clicks.
  await safe('restore-help-panel', viewportName, theme, async () => {
    const helpToggle = page.locator('#helpToggle');
    if (await helpToggle.count()) {
      await page.evaluate(() => {
        const el = document.getElementById('helpToggle');
        if (el) el.click();
      });
      await page.waitForSelector('#floatHelp.sv-float-help--open', { timeout: 5000 });
      await page.waitForTimeout(400);
      await screenshotPage(page, '05-restore-help-panel-open', { viewportName, theme, fullPage: false });
      // close it again
      await page.evaluate(() => {
        const el = document.getElementById('helpToggle');
        if (el) el.click();
      }).catch(() => {});
      await page.waitForTimeout(200);
    }
  });
}

async function captureHistoryPage(page, viewportName, theme) {
  console.log(`Capturing History Page (${viewportName}, ${theme})...`);
  await page.goto(`${BASE_URL}/history`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(3000);

  // Default view is table
  await screenshotPage(page, '06-history-table-view', { viewportName, theme });

  // Cards view: #btnViewCards toggles the layout. JS click is used because on
  // tablet/mobile the button can be visually hidden / off-screen (responsive
  // toolbar), but its click handler still works when invoked directly.
  await safe('history-cards-view', viewportName, theme, async () => {
    const cardsBtn = page.locator('#btnViewCards');
    if (await cardsBtn.count()) {
      await page.evaluate(() => {
        const el = document.getElementById('btnViewCards');
        if (el) el.click();
      });
      await page.waitForTimeout(600);
      await screenshotPage(page, '07-history-cards-view', { viewportName, theme });
    }
  });
}

async function captureSystemStatusPage(page, viewportName, theme) {
  console.log(`Capturing System Status Page (${viewportName}, ${theme})...`);
  // FIXED: original script navigated to '/' here; the real dedicated route is /system-status
  await page.goto(`${BASE_URL}/system-status`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(4000);

  await screenshotPage(page, '08-system-status-full', { viewportName, theme });
}

async function captureSettingsPage(page, viewportName, theme) {
  console.log(`Capturing Settings Page (${viewportName}, ${theme})...`);
  // settings.html is a single scrolling About page (no tabs). The original
  // script's [data-tab="model"] / [data-tab="language"] clicks were no-ops
  // because those tabs do not exist.
  await page.goto(`${BASE_URL}/settings`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(2000);

  await screenshotPage(page, '09-settings-full', { viewportName, theme });

  // FAQ expand: open the first <details> (native disclosure widget)
  await safe('settings-faq-expanded', viewportName, theme, async () => {
    const firstSummary = page.locator('details.sv-about-faq-item > summary').first();
    if (await firstSummary.count()) {
      await firstSummary.click();
      await page.waitForTimeout(400);
      await screenshotPage(page, '10-settings-faq-expanded', { viewportName, theme });
    }
  });
}

async function captureNavInteractions(page, viewportName, theme) {
  console.log(`Capturing Navigation Interactions (${viewportName}, ${theme})...`);
  await page.goto(`${BASE_URL}/`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(2000);

  // Locale dropdown: #btnLocaleSwitch opens the language menu
  await safe('locale-dropdown-open', viewportName, theme, async () => {
    const localeBtn = page.locator('#btnLocaleSwitch');
    if (await localeBtn.count()) {
      await localeBtn.click();
      await page.waitForTimeout(400);
      await screenshotPage(page, '11-locale-dropdown-open', { viewportName, theme, fullPage: false });
      // close: click again or press Escape
      await page.keyboard.press('Escape').catch(() => {});
      await localeBtn.click({ force: true }).catch(() => {});
      await page.waitForTimeout(200);
    }
  });

  // Mobile nav: #btnToggleNav (.sv-md-hidden) is only visible on the mobile
  // viewport. On tablet width the full nav still shows, so the hamburger
  // button is hidden and should not be attempted.
  const isMobile = viewportName === 'mobile';
  if (isMobile) {
    await safe('mobile-nav-open', viewportName, theme, async () => {
      const navToggle = page.locator('#btnToggleNav');
      if (await navToggle.count()) {
        await navToggle.click();
        await page.waitForTimeout(400);
        await screenshotPage(page, '12-mobile-nav-open', { viewportName, theme, fullPage: false });
        await navToggle.click({ force: true }).catch(() => {});
        await page.waitForTimeout(200);
      }
    });
  }
}

async function captureAllViewports(page, viewports, themes) {
  for (const [vpName, vpSize] of Object.entries(viewports)) {
    console.log(`\n=== Viewport: ${vpName} (${vpSize.width}x${vpSize.height}) ===`);
    await page.setViewportSize({ width: vpSize.width, height: vpSize.height });

    for (const theme of themes) {
      console.log(`\n--- Theme: ${theme} ---`);
      await setTheme(page, theme);

      await captureHomePage(page, vpName, theme);
      await captureRestorePage(page, vpName, theme);
      await captureHistoryPage(page, vpName, theme);
      await captureSystemStatusPage(page, vpName, theme);
      await captureSettingsPage(page, vpName, theme);
      await captureNavInteractions(page, vpName, theme);
    }
  }
}

(async () => {
  console.log('SeedVR2 - Full Website Screenshot Capture');
  console.log('=========================================');
  console.log(`Base URL: ${BASE_URL}`);
  console.log(`Output Dir: ${OUTPUT_DIR}`);
  console.log('');

  ensureDir(OUTPUT_DIR);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  // Suppress the first-visit onboarding modal on the restore page. The modal
  // (restore.html #onboardingModal) shows when localStorage key
  // 'sv_onboarding_seen_v2' is unset and would intercept all pointer events.
  // addInitScript runs before any page script on every navigation.
  await page.addInitScript(() => {
    try {
      localStorage.setItem('sv_onboarding_seen_v2', '1');
    } catch (e) {
      // localStorage may be unavailable on some pages (e.g. health JSON) - ignore
    }
  });

  try {
    console.log('Checking if server is running...');
    try {
      await page.goto(`${BASE_URL}/api/system/health`, { timeout: 10000 });
      console.log('Server is running!');
    } catch (e) {
      console.error('ERROR: Server is not running at', BASE_URL);
      console.error('Please start the server first with: start.bat');
      process.exit(1);
    }

    await captureAllViewports(page, VIEWPORTS, THEMES);

    console.log('\n=========================================');
    console.log('Screenshot capture complete!');
    console.log(`All screenshots saved to: ${OUTPUT_DIR}`);

  } catch (error) {
    console.error('Error:', error);
    process.exit(1);
  } finally {
    await browser.close();
  }
})();

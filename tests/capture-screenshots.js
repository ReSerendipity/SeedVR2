const { chromium } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

const BASE_URL = 'http://127.0.0.1:7870';
const OUTPUT_DIR = path.join(__dirname, '..', 'screenshots');

const VIEWPORTS = {
  desktop: { width: 1920, height: 1080 },
};

const THEMES = ['dark', 'light'];

function ensureDir(dir) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

async function screenshotPage(page, name, options = {}) {
  const { fullPage = true, waitFor = null, clickBefore = null, viewportName = 'desktop', theme = 'dark' } = options;
  
  const dir = path.join(OUTPUT_DIR, viewportName, theme);
  ensureDir(dir);
  
  const filePath = path.join(dir, `${name}.png`);
  
  if (clickBefore) {
    await page.click(clickBefore);
    await page.waitForTimeout(500);
  }
  
  if (waitFor) {
    await page.waitForTimeout(waitFor);
  }
  
  await page.screenshot({ path: filePath, fullPage });
  console.log(`  Captured: ${filePath}`);
}

async function setTheme(page, theme) {
  await page.evaluate((t) => {
    localStorage.setItem('sv-theme', t);
    document.documentElement.setAttribute('data-theme', t);
  }, theme);
  await page.waitForTimeout(300);
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
  
  await screenshotPage(page, '02-restore-default', { viewportName, theme });
  
  const hasAdvancedParams = await page.locator('#advancedParamsCard .sv-card-header').count() > 0;
  if (hasAdvancedParams) {
    await page.evaluate(() => {
      const card = document.getElementById('advancedParamsCard');
      if (card) {
        card.classList.add('expanded');
        const header = card.querySelector('.sv-card-header');
        const body = card.querySelector('.sv-card-body');
        if (header) header.setAttribute('aria-expanded', 'true');
        if (body) body.style.display = 'block';
      }
    });
    await page.waitForTimeout(500);
    await screenshotPage(page, '03-restore-advanced-params-expanded', { viewportName, theme });
  }
  
  const hasFileSidebarToggle = await page.locator('#btnToggleFileSidebar').count() > 0;
  if (hasFileSidebarToggle) {
    await page.evaluate(() => {
      const sidebar = document.getElementById('fileSidebar');
      if (sidebar) sidebar.classList.add('sv-sidebar-collapsed');
    });
    await page.waitForTimeout(300);
    await screenshotPage(page, '04-restore-left-sidebar-collapsed', { viewportName, theme });
    await page.evaluate(() => {
      const sidebar = document.getElementById('fileSidebar');
      if (sidebar) sidebar.classList.remove('sv-sidebar-collapsed');
    });
    await page.waitForTimeout(300);
  }
  
  const hasParamsSidebarToggle = await page.locator('#btnToggleParamsSidebar').count() > 0;
  if (hasParamsSidebarToggle) {
    await page.evaluate(() => {
      const sidebar = document.getElementById('paramsSidebar');
      if (sidebar) sidebar.classList.add('sv-sidebar-collapsed');
    });
    await page.waitForTimeout(300);
    await screenshotPage(page, '05-restore-right-sidebar-collapsed', { viewportName, theme });
    await page.evaluate(() => {
      const sidebar = document.getElementById('paramsSidebar');
      if (sidebar) sidebar.classList.remove('sv-sidebar-collapsed');
    });
    await page.waitForTimeout(300);
  }
}

async function captureHistoryPage(page, viewportName, theme) {
  console.log(`Capturing History Page (${viewportName}, ${theme})...`);
  await page.goto(`${BASE_URL}/history`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(3000);
  
  await screenshotPage(page, '06-history-full', { viewportName, theme });
}

async function captureSystemStatusPage(page, viewportName, theme) {
  console.log(`Capturing System Status Page (${viewportName}, ${theme})...`);
  await page.goto(`${BASE_URL}/system-status`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(4000);
  
  await screenshotPage(page, '07-system-status-full', { viewportName, theme });
}

async function captureSettingsPage(page, viewportName, theme) {
  console.log(`Capturing Settings Page (${viewportName}, ${theme})...`);
  await page.goto(`${BASE_URL}/settings`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(2000);
  
  await screenshotPage(page, '08-settings-paths-tab', { viewportName, theme });
  
  const hasModelTab = await page.locator('[data-tab="model"]').count() > 0;
  if (hasModelTab) {
    await page.click('[data-tab="model"]');
    await page.waitForTimeout(300);
    await screenshotPage(page, '09-settings-model-tab', { viewportName, theme });
  }
  
  const hasLangTab = await page.locator('[data-tab="language"]').count() > 0;
  if (hasLangTab) {
    await page.click('[data-tab="language"]');
    await page.waitForTimeout(300);
    await screenshotPage(page, '10-settings-language-tab', { viewportName, theme });
  }
}

async function captureNavInteractions(page, viewportName, theme) {
  console.log(`Capturing Navigation Interactions (${viewportName}, ${theme})...`);
  await page.goto(`${BASE_URL}/`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(2000);
  
  const hasLocaleDropdown = await page.locator('#btnLocaleSwitch').count() > 0;
  if (hasLocaleDropdown) {
    await page.click('#btnLocaleSwitch');
    await page.waitForTimeout(300);
    await screenshotPage(page, '11-locale-dropdown-open', { viewportName, theme, fullPage: false });
    await page.click('#btnLocaleSwitch');
    await page.waitForTimeout(200);
  }
  
  const hasMobileNavToggle = await page.locator('#btnToggleNav').count() > 0;
  const isMobile = viewportName === 'mobile' || viewportName === 'tablet';
  if (hasMobileNavToggle && isMobile) {
    await page.evaluate(() => {
      const btn = document.getElementById('btnToggleNav');
      if (btn) {
        const nav = document.getElementById('mainNav');
        if (nav) nav.classList.add('sv-mobile-nav-open');
      }
    });
    await page.waitForTimeout(300);
    await screenshotPage(page, '12-mobile-nav-open', { viewportName, theme, fullPage: false });
  }
}

async function captureAllViewports(page, viewports, themes) {
  for (const [vpName, vpSize] of Object.entries(viewports)) {
    console.log(`\n=== Viewport: ${vpName} (${vpSize.width}x${vpSize.height}) ===`);
    await page.setViewportSize(vpSize);
    
    for (const theme of themes) {
      console.log(`\n--- Theme: ${theme} ---`);
      await setTheme(page, theme);
      
      try {
        await captureHomePage(page, vpName, theme);
      } catch (e) { console.error(`Error capturing home page: ${e.message}`); }
      
      try {
        await captureRestorePage(page, vpName, theme);
      } catch (e) { console.error(`Error capturing restore page: ${e.message}`); }
      
      try {
        await captureHistoryPage(page, vpName, theme);
      } catch (e) { console.error(`Error capturing history page: ${e.message}`); }
      
      try {
        await captureSystemStatusPage(page, vpName, theme);
      } catch (e) { console.error(`Error capturing system status page: ${e.message}`); }
      
      try {
        await captureSettingsPage(page, vpName, theme);
      } catch (e) { console.error(`Error capturing settings page: ${e.message}`); }
      
      try {
        await captureNavInteractions(page, vpName, theme);
      } catch (e) { console.error(`Error capturing nav interactions: ${e.message}`); }
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

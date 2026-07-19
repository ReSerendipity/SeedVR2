import { Page, Locator, expect } from '@playwright/test';

export class BasePage {
  readonly page: Page;

  // Mapping English nav names to Chinese text rendered in the UI
  private static readonly NAV_TEXT_MAP: Record<string, string> = {
    'Home': '首页',
    'Video Restore': '视频修复',
    'Image Restore': '图像修复',
    'History': '历史记录',
    'System Status': '系统状态',
    'Settings': '设置',
  };

  // Reverse mapping: Chinese → English
  private static readonly NAV_TEXT_MAP_REVERSE: Record<string, string> = Object.fromEntries(
    Object.entries(BasePage.NAV_TEXT_MAP).map(([en, zh]) => [zh, en]),
  );

  // Shared locators from base.html
  readonly navBar: Locator;
  readonly mainNav: Locator;
  readonly navLinks: Locator;
  readonly themeToggle: Locator;
  readonly toastContainer: Locator;
  readonly confirmModal: Locator;
  readonly breadcrumb: Locator;

  constructor(page: Page) {
    this.page = page;

    this.navBar = page.locator('.sv-navbar');
    this.mainNav = page.locator('#mainNav');
    this.navLinks = page.locator('#mainNav .sv-nav-link');
    this.themeToggle = page.locator('#btnThemeToggle');
    this.toastContainer = page.locator('#toastContainer');
    this.confirmModal = page.locator('#confirmModal');
    this.breadcrumb = page.locator('.sv-breadcrumb');
  }

  async navigate(path: string): Promise<void> {
    await this.page.goto(path);
    await this.waitForPageLoad();
  }

  async waitForPageLoad(): Promise<void> {
    await this.page.waitForLoadState('domcontentloaded');
    await this.page.waitForLoadState('networkidle');
  }

  async getPageTitle(): Promise<string> {
    return await this.page.title();
  }

  async getCurrentTheme(): Promise<string> {
    return await this.page.evaluate(() => {
      return document.documentElement.getAttribute('data-theme') || 'dark';
    });
  }

  async switchTheme(theme: 'dark' | 'light'): Promise<void> {
    const currentTheme = await this.getCurrentTheme();
    if (currentTheme !== theme) {
      await this.themeToggle.click();
      // Wait for theme attribute to update
      await this.page.waitForFunction(
        (expected) => document.documentElement.getAttribute('data-theme') === expected,
        theme
      );
    }
  }

  async takeScreenshot(name: string): Promise<void> {
    await this.page.screenshot({ path: `screenshots/${name}.png`, fullPage: true });
  }

  async getToastMessages(): Promise<string[]> {
    const toasts = this.toastContainer.locator('.sv-toast');
    const count = await toasts.count();
    const messages: string[] = [];
    for (let i = 0; i < count; i++) {
      const text = await toasts.nth(i).textContent();
      if (text) messages.push(text.trim());
    }
    return messages;
  }

  async waitForToast(message?: string, type?: string, timeout = 10000): Promise<Locator> {
    // Toast elements have classes like "sv-toast toast-error" on the same element
    let locator = type
      ? this.toastContainer.locator(`.sv-toast.toast-${type}`)
      : this.toastContainer.locator('.sv-toast');
    if (message) {
      locator = locator.filter({ hasText: message });
    }
    await locator.waitFor({ state: 'visible', timeout });
    return locator.first();
  }

  async dismissToast(): Promise<void> {
    const closeBtn = this.toastContainer.locator('.sv-toast button[aria-label="Close"]').first();
    if (await closeBtn.isVisible()) {
      await closeBtn.click();
    }
  }

  async getActiveNavItem(): Promise<string> {
    // The .active class is on the <a> tag itself: <a class="sv-nav-link active">
    const activeLink = this.page.locator('#mainNav .sv-nav-link.active');
    // The nav link structure is: <a class="sv-nav-link"><i class="nav-icon"></i><span>中文文本</span><span class="nav-shortcut">Alt+N</span></a>
    // Get just the <span> text (not the shortcut span)
    const navText = await activeLink.locator('span:not(.nav-shortcut)').textContent();
    const trimmedText = navText?.trim() || '';
    // Reverse-map Chinese text back to English name
    return BasePage.NAV_TEXT_MAP_REVERSE[trimmedText] || trimmedText;
  }

  async clickNavItem(name: string): Promise<void> {
    // Translate English name to Chinese text that appears in the rendered UI
    const displayText = BasePage.NAV_TEXT_MAP[name] || name;
    const link = this.navLinks.filter({ hasText: displayText });
    await link.click();
    await this.waitForPageLoad();
  }

  async getBreadcrumb(): Promise<string[]> {
    const items = this.breadcrumb.locator('a, .current');
    const count = await items.count();
    const crumbs: string[] = [];
    for (let i = 0; i < count; i++) {
      const text = await items.nth(i).textContent();
      if (text) crumbs.push(text.trim());
    }
    return crumbs;
  }
}

import { Page, Locator } from '@playwright/test';
import { BasePage } from './base.page';

/**
 * SettingsPage - 匹配 settings.html（"左设置右关于"两栏改版）的页面对象。
 *
 * 页面结构（2026-08 产品改版后）：
 * - 设置面板（.sv-settings-panel）：语言下拉 #settingsLocale、主题下拉 #settingsTheme、路径只读展示 .sv-settings-paths
 * - 关于项目（.sv-about-hero）：名称/标语/作者/版本/许可证/社交按钮
 * - 技术特性（.sv-about-feature-card × 9）
 * - 右侧栏：技术栈表 .sv-about-table、快速开始 .sv-about-setup、FAQ、链接、版权
 */
export class SettingsPage extends BasePage {
  // 设置面板
  readonly locale: Locator; // #settingsLocale
  readonly theme: Locator; // #settingsTheme
  readonly pathsText: Locator; // .sv-settings-paths
  readonly pathsNote: Locator;

  // 关于项目 hero
  readonly aboutHero: Locator;
  readonly aboutHeroName: Locator;
  readonly aboutHeroSubtitle: Locator;
  readonly aboutMetadata: Locator; // 作者/版本/许可证元数据块
  readonly aboutGithubBtn: Locator;

  // 技术特性
  readonly featureCards: Locator;

  // 右侧栏
  readonly stackTable: Locator; // .sv-about-table
  readonly quickstart: Locator; // .sv-about-setup

  readonly path = '/settings';

  constructor(page: Page) {
    super(page);

    // 设置面板
    this.locale = page.locator('#settingsLocale');
    this.theme = page.locator('#settingsTheme');
    this.pathsText = page.locator('.sv-settings-paths');
    this.pathsNote = page.locator('.sv-settings-panel p.sv-text-muted');

    // 关于项目 hero
    this.aboutHero = page.locator('.sv-about-hero');
    this.aboutHeroName = page.locator('.sv-about-hero-name');
    this.aboutHeroSubtitle = page.locator('.sv-about-hero-subtitle');
    this.aboutMetadata = page.locator('.sv-about-metadata');
    this.aboutGithubBtn = page.locator('.sv-about-github-btn');

    // 技术特性
    this.featureCards = page.locator('.sv-about-feature-card');

    // 右侧栏
    this.stackTable = page.locator('.sv-about-table');
    this.quickstart = page.locator('.sv-about-setup');
  }

  async goto(): Promise<void> {
    await this.navigate(this.path);
  }

  /** 读取语言下拉的当前值 */
  async getSelectedLocale(): Promise<string> {
    return await this.locale.inputValue();
  }

  /** 读取主题下拉的当前值 */
  async getSelectedTheme(): Promise<string> {
    return await this.theme.inputValue();
  }

  /** 切换语言：选择后触发 switchLocale（POST /api/system/locale + 页面刷新） */
  async switchLocale(localeCode: string): Promise<void> {
    await this.locale.selectOption(localeCode);
  }

  /** 切换主题：选择后触发 applyTheme（html[data-theme] 更新 + localStorage 持久化） */
  async switchTheme(theme: 'dark' | 'light'): Promise<void> {
    await this.theme.selectOption(theme);
  }
}

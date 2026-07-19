import { Page, Locator } from '@playwright/test';
import { BasePage } from './base.page';

export class SettingsPage extends BasePage {
  // Navigation
  readonly settingsNav: Locator;

  // Tab selectors
  readonly tabPaths: Locator;
  readonly tabModel: Locator;
  readonly tabLanguage: Locator;

  // Section selectors
  readonly sectionPaths: Locator;
  readonly sectionModel: Locator;
  readonly sectionLanguage: Locator;

  // Path settings
  readonly pretrainedDir: Locator;
  readonly outputDir: Locator;
  readonly btnSavePaths: Locator;
  readonly btnResetPaths: Locator;
  readonly browseDirButtons: Locator;

  // Model settings
  readonly defaultModelSize: Locator;
  readonly modelPrecision: Locator;
  readonly gpuBackend: Locator;
  readonly btnSaveModelSettings: Locator;

  // Language settings
  readonly locale: Locator;
  readonly btnSaveLanguage: Locator;

  readonly path = '/settings';

  constructor(page: Page) {
    super(page);

    // Navigation
    this.settingsNav = page.locator('#settingsNav');

    // Tabs
    this.tabPaths = page.locator('#tab-paths');
    this.tabModel = page.locator('#tab-model');
    this.tabLanguage = page.locator('#tab-language');

    // Sections
    this.sectionPaths = page.locator('#section-paths');
    this.sectionModel = page.locator('#section-model');
    this.sectionLanguage = page.locator('#section-language');

    // Path settings
    this.pretrainedDir = page.locator('#pretrainedDir');
    this.outputDir = page.locator('#outputDir');
    this.btnSavePaths = page.locator('#btnSavePaths');
    this.btnResetPaths = page.locator('#btnResetPaths');
    this.browseDirButtons = page.locator('.btn-browse-dir');

    // Model settings
    this.defaultModelSize = page.locator('#defaultModelSize');
    this.modelPrecision = page.locator('#modelPrecision');
    this.gpuBackend = page.locator('#gpuBackend');
    this.btnSaveModelSettings = page.locator('#btnSaveModelSettings');

    // Language settings
    this.locale = page.locator('#locale');
    this.btnSaveLanguage = page.locator('#btnSaveLanguage');
  }

  async goto(): Promise<void> {
    await this.navigate(this.path);
  }

  async switchTab(tabName: 'paths' | 'model' | 'language'): Promise<void> {
    const tabMap: Record<string, Locator> = {
      paths: this.tabPaths,
      model: this.tabModel,
      language: this.tabLanguage,
    };
    const tab = tabMap[tabName];
    if (!tab) throw new Error(`Unknown tab: ${tabName}`);
    await tab.click();
    // Wait for the corresponding section to become visible
    const sectionMap: Record<string, Locator> = {
      paths: this.sectionPaths,
      model: this.sectionModel,
      language: this.sectionLanguage,
    };
    await sectionMap[tabName].waitFor({ state: 'visible' });
  }

  async setPretrainedDir(path: string): Promise<void> {
    await this.pretrainedDir.fill(path);
  }

  async setOutputDir(path: string): Promise<void> {
    await this.outputDir.fill(path);
  }

  async savePaths(): Promise<void> {
    await this.btnSavePaths.click();
  }

  async resetPaths(): Promise<void> {
    await this.btnResetPaths.click();
    // Confirm in the modal
    const confirmBtn = this.page.locator('#confirmAction');
    await confirmBtn.click();
  }

  async setDefaultModelSize(size: string): Promise<void> {
    await this.defaultModelSize.selectOption(size);
  }

  async setModelPrecision(precision: string): Promise<void> {
    await this.modelPrecision.selectOption(precision);
  }

  async setGpuBackend(backend: string): Promise<void> {
    await this.gpuBackend.selectOption(backend);
  }

  async saveModelSettings(): Promise<void> {
    await this.btnSaveModelSettings.click();
  }

  async setLocale(locale: string): Promise<void> {
    await this.locale.selectOption(locale);
  }

  async saveLanguage(): Promise<void> {
    await this.btnSaveLanguage.click();
    // Language save triggers a page reload
    await this.page.waitForLoadState('domcontentloaded');
  }

  async getCurrentSettings(): Promise<Record<string, string>> {
    // Read values from each tab - switch tabs as needed since hidden elements
    // may not be interactable in some browsers/frameworks.
    const result: Record<string, string> = {};

    // Paths tab (default)
    result.pretrainedDir = await this.pretrainedDir.inputValue();
    result.outputDir = await this.outputDir.inputValue();

    // Model tab
    await this.switchTab('model');
    result.defaultModelSize = await this.defaultModelSize.inputValue();
    result.modelPrecision = await this.modelPrecision.inputValue();
    result.gpuBackend = await this.gpuBackend.inputValue();

    // Language tab
    await this.switchTab('language');
    result.locale = await this.locale.inputValue();

    // Return to paths tab (default)
    await this.switchTab('paths');

    return result;
  }
}

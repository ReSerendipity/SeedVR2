import { Page, Locator } from '@playwright/test';
import { BasePage } from './base.page';

export class IndexPage extends BasePage {
  // Page-specific selectors
  readonly hero: Locator;
  readonly quickCards: Locator;
  readonly overviewGrid: Locator;
  readonly overviewGpu: Locator;
  readonly overviewVram: Locator;
  readonly overviewModel: Locator;
  readonly overviewMemory: Locator;
  readonly overviewUptime: Locator;
  readonly overviewTasks: Locator;

  readonly path = '/';

  constructor(page: Page) {
    super(page);

    this.hero = page.locator('.sv-hero');
    this.quickCards = page.locator('.sv-quick-card');
    this.overviewGrid = page.locator('#overviewGrid');
    this.overviewGpu = page.locator('#overviewGpu');
    this.overviewVram = page.locator('#overviewVram');
    this.overviewModel = page.locator('#overviewModel');
    this.overviewMemory = page.locator('#overviewMemory');
    this.overviewUptime = page.locator('#overviewUptime');
    this.overviewTasks = page.locator('#overviewTasks');
  }

  async goto(): Promise<void> {
    await this.navigate(this.path);
  }

  async getQuickCards(): Promise<Locator[]> {
    const count = await this.quickCards.count();
    const cards: Locator[] = [];
    for (let i = 0; i < count; i++) {
      cards.push(this.quickCards.nth(i));
    }
    return cards;
  }

  async clickQuickCard(name: string): Promise<void> {
    const card = this.quickCards.filter({ hasText: name });
    await card.click();
    await this.waitForPageLoad();
  }

  async getOverviewValue(id: string): Promise<string> {
    const el = this.page.locator(`#${id}`);
    await el.waitFor({ state: 'visible', timeout: 15000 });
    const text = await el.textContent();
    return text?.trim() || '';
  }

  async waitForOverviewLoad(): Promise<void> {
    // Wait for the overview grid to be visible and skeleton loaders to be replaced
    await this.overviewGrid.waitFor({ state: 'visible' });
    // Wait for GPU info to load (skeleton replaced with actual content)
    await this.page.waitForFunction(() => {
      const el = document.getElementById('overviewGpu');
      return el && !el.querySelector('.sv-skeleton');
    }, { timeout: 15000 });
  }
}

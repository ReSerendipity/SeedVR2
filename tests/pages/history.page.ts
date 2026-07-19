import { Page, Locator } from '@playwright/test';
import { BasePage } from './base.page';

export class HistoryPage extends BasePage {
  // Toolbar selectors
  readonly searchInput: Locator;
  readonly filterType: Locator;
  readonly filterStatus: Locator;
  readonly btnRefresh: Locator;
  readonly btnClearHistory: Locator;

  // Table selectors
  readonly historyBody: Locator;
  readonly table: Locator;

  // Pagination selectors
  readonly pagination: Locator;
  readonly btnPrevPage: Locator;
  readonly btnNextPage: Locator;
  readonly pageInfo: Locator;

  // Empty state
  readonly emptyState: Locator;

  readonly path = '/history';

  constructor(page: Page) {
    super(page);

    this.searchInput = page.locator('#searchInput');
    this.filterType = page.locator('#filterType');
    this.filterStatus = page.locator('#filterStatus');
    this.btnRefresh = page.locator('#btnRefresh');
    this.btnClearHistory = page.locator('#btnClearHistory');

    this.historyBody = page.locator('#historyBody');
    this.table = page.locator('.sv-table');

    this.pagination = page.locator('#pagination');
    this.btnPrevPage = page.locator('#btnPrevPage');
    this.btnNextPage = page.locator('#btnNextPage');
    this.pageInfo = page.locator('#pageInfo');

    this.emptyState = page.locator('.sv-empty-state');
  }

  async goto(): Promise<void> {
    await this.navigate(this.path);
  }

  async searchHistory(query: string): Promise<void> {
    await this.searchInput.fill(query);
    // Wait for the search to trigger (500ms debounce in the app)
    await this.page.waitForTimeout(600);
    await this.page.waitForLoadState('networkidle');
  }

  async filterByType(type: string): Promise<void> {
    await this.filterType.selectOption(type);
    await this.page.waitForLoadState('networkidle');
  }

  async filterByStatus(status: string): Promise<void> {
    await this.filterStatus.selectOption(status);
    await this.page.waitForLoadState('networkidle');
  }

  async refreshHistory(): Promise<void> {
    await this.btnRefresh.click();
    await this.page.waitForLoadState('networkidle');
  }

  async clearHistory(): Promise<void> {
    await this.btnClearHistory.click();
    // Wait for the confirm modal to appear
    await this.confirmModal.waitFor({ state: 'visible', timeout: 5000 });
    // Confirm in the modal
    const confirmBtn = this.page.locator('#confirmAction');
    await confirmBtn.click();
    await this.page.waitForLoadState('networkidle');
  }

  async getHistoryRows(): Promise<Locator[]> {
    // Exclude skeleton rows and empty-state rows
    const rows = this.historyBody.locator('tr:not(.sv-skeleton-row):not(.empty-row)');
    const count = await rows.count();
    const result: Locator[] = [];
    for (let i = 0; i < count; i++) {
      result.push(rows.nth(i));
    }
    return result;
  }

  async getRowCount(): Promise<number> {
    const rows = this.historyBody.locator('tr:not(.sv-skeleton-row):not(.empty-row)');
    return await rows.count();
  }

  async goToPage(pageNum: number): Promise<void> {
    // Navigate to a specific page by clicking next/prev
    const currentPage = await this.getCurrentPage();
    if (pageNum === currentPage) return;

    if (pageNum > currentPage) {
      for (let i = currentPage; i < pageNum; i++) {
        await this.btnNextPage.click();
        await this.page.waitForLoadState('networkidle');
      }
    } else {
      for (let i = currentPage; i > pageNum; i--) {
        await this.btnPrevPage.click();
        await this.page.waitForLoadState('networkidle');
      }
    }
  }

  async getCurrentPage(): Promise<number> {
    const text = await this.pageInfo.textContent();
    if (!text) return 1;
    const match = text.match(/(\d+)\s*\/\s*\d+/);
    return match ? parseInt(match[1], 10) : 1;
  }

  async getTotalPages(): Promise<number> {
    const text = await this.pageInfo.textContent();
    if (!text) return 1;
    const match = text.match(/\d+\s*\/\s*(\d+)/);
    return match ? parseInt(match[1], 10) : 1;
  }

  async deleteRecord(id: number): Promise<void> {
    const deleteBtn = this.historyBody.locator(`button[onclick="SeedVR2.deleteHistoryRecord(${id})"]`);
    await deleteBtn.click();
    // Confirm in the modal
    const confirmBtn = this.page.locator('#confirmAction');
    await confirmBtn.click();
    await this.page.waitForLoadState('networkidle');
  }

  async getEmptyStateMessage(): Promise<string> {
    const title = this.emptyState.locator('.empty-title');
    await title.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {});
    const text = await title.textContent();
    return text?.trim() || '';
  }
}

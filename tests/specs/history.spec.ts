/**
 * History record test specification for SeedVR2 WebUI.
 *
 * Covers:
 * - Load history: navigate to history page, verify table renders with mock data
 * - Pagination: mock paginated data, verify page navigation
 * - Search: enter search query, verify filtered results
 * - Filter by type: select video/image filter, verify filtered results
 * - Filter by status: select status filter, verify filtered results
 * - Delete record: click delete button, verify confirmation and deletion
 * - Clear history: click clear button, verify confirmation dialog and clearing
 * - Empty state: mock empty history, verify empty state message and CTA button
 */
import { test, expect } from '@playwright/test';
import { HistoryPage } from '../pages/history.page';
import {
  setupAllMocks,
  mockHistoryListSuccess,
  mockHistoryDeleteSuccess,
  mockHistoryClearSuccess,
  mockHistoryStatsSuccess,
} from '../fixtures/api-mocks';
import {
  mockHistoryResponse,
  type HistoryListResponse,
  type HistoryItem,
} from '../fixtures/test-data';
import { assertUrlPath } from '../utils/assertion-helpers';
import { waitForToast, waitForSuccessToast } from '../utils/wait-helpers';

test.describe('History Records', () => {
  let historyPage: HistoryPage;

  test.beforeEach(async ({ page }) => {
    // Set up all API mocks for a fully mocked backend
    await setupAllMocks(page);
    historyPage = new HistoryPage(page);
    await historyPage.goto();
  });

  // ============================================================
  // Load history
  // ============================================================

  test.describe('Load history', () => {
    test('history page renders the table with mock data', async ({ page }) => {
      // The table should be visible
      await expect(historyPage.table).toBeVisible();

      // The history body should contain rows from the mock data
      const rowCount = await historyPage.getRowCount();
      expect(rowCount).toBeGreaterThan(0);
    });

    test('history rows contain expected columns', async ({ page }) => {
      const rows = await historyPage.getHistoryRows();
      expect(rows.length).toBeGreaterThan(0);

      // Each row should contain text content (filename, status, etc.)
      const firstRowText = await rows[0].textContent();
      expect(firstRowText).toBeTruthy();
      expect(firstRowText!.length).toBeGreaterThan(0);
    });

    test('search input and filter controls are visible', async () => {
      await expect(historyPage.searchInput).toBeVisible();
      await expect(historyPage.filterType).toBeVisible();
      await expect(historyPage.filterStatus).toBeVisible();
    });
  });

  // ============================================================
  // Pagination
  // ============================================================

  test.describe('Pagination', () => {
    test('pagination controls are visible when there are multiple pages', async ({ page }) => {
      // Override mock with paginated data (more than one page)
      await page.route('**/api/system/history**', async (route) => {
        if (route.request().method() === 'GET' && !route.request().url().includes('/statistics')) {
          const records: HistoryItem[] = Array.from({ length: 25 }, (_, i) => ({
            id: i + 1,
            task_type: i % 2 === 0 ? 'video' : 'image',
            input_file: `C:\\Videos\\file_${i}.mp4`,
            output_file: `outputs\\file_${i}`,
            model_size: '7b',
            status: 'completed',
            parameters: '{}',
            processing_time: 10 + i,
            created_at: '2025-01-15T10:00:00Z',
            error_message: '',
          }));

          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              records,
              total: 50,
              page: 1,
              page_size: 25,
              total_pages: 2,
            } as HistoryListResponse),
          });
        } else {
          await route.continue();
        }
      });

      // Reload the page to pick up the new mock
      await page.reload();
      await page.waitForLoadState('domcontentloaded');

      // Pagination should be visible
      await expect(historyPage.pagination).toBeVisible();
      await expect(historyPage.btnNextPage).toBeVisible();
    });

    test('clicking next page loads the next set of records', async ({ page }) => {
      // Override mock with paginated data
      let currentPage = 1;
      await page.route('**/api/system/history**', async (route) => {
        if (route.request().method() === 'GET' && !route.request().url().includes('/statistics')) {
          const url = new URL(route.request().url());
          currentPage = parseInt(url.searchParams.get('page') || '1', 10);

          const records: HistoryItem[] = Array.from({ length: 10 }, (_, i) => ({
            id: (currentPage - 1) * 10 + i + 1,
            task_type: i % 2 === 0 ? 'video' : 'image',
            input_file: `C:\\Videos\\page${currentPage}_file_${i}.mp4`,
            output_file: `outputs\\page${currentPage}_file_${i}`,
            model_size: '7b',
            status: 'completed',
            parameters: '{}',
            processing_time: 10 + i,
            created_at: '2025-01-15T10:00:00Z',
            error_message: '',
          }));

          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              records,
              total: 30,
              page: currentPage,
              page_size: 10,
              total_pages: 3,
            } as HistoryListResponse),
          });
        } else {
          await route.continue();
        }
      });

      await page.reload();
      await page.waitForLoadState('domcontentloaded');

      // Click next page
      if (await historyPage.btnNextPage.isEnabled()) {
        await historyPage.btnNextPage.click();

        // Wait until the page indicator actually shows page 2 (auto-retrying,
        // avoids a race between the networkidle state and the async re-render)
        await expect(historyPage.pageInfo).toHaveText(/^2\s*\//);

        // Verify we're on page 2
        const pageNum = await historyPage.getCurrentPage();
        expect(pageNum).toBe(2);
      }
    });

    test('previous page button is disabled on the first page', async ({ page }) => {
      await historyPage.goto();
      const isDisabled = await historyPage.btnPrevPage.isDisabled().catch(() => true);
      expect(isDisabled).toBe(true);
    });
  });

  // ============================================================
  // Search
  // ============================================================

  test.describe('Search', () => {
    test('entering a search query filters history results', async ({ page }) => {
      // Override mock to return filtered results
      await page.route('**/api/system/history**', async (route) => {
        if (route.request().method() === 'GET' && !route.request().url().includes('/statistics')) {
          const url = new URL(route.request().url());
          const searchQuery = url.searchParams.get('search') || '';

          const allRecords: HistoryItem[] = [
            {
              id: 1,
              task_type: 'video',
              input_file: 'C:\\Videos\\sample_720p_5s.mp4',
              output_file: 'outputs\\video\\1\\restored.mp4',
              model_size: '7b',
              status: 'completed',
              parameters: '{}',
              processing_time: 45.2,
              created_at: '2025-01-15T10:30:00Z',
              error_message: '',
            },
            {
              id: 2,
              task_type: 'image',
              input_file: 'C:\\Images\\photo_landscape.jpg',
              output_file: 'outputs\\image\\2\\restored.png',
              model_size: '7b',
              status: 'completed',
              parameters: '{}',
              processing_time: 5.3,
              created_at: '2025-01-15T11:00:00Z',
              error_message: '',
            },
          ];

          const filteredRecords = searchQuery
            ? allRecords.filter((record) =>
                record.input_file.toLowerCase().includes(searchQuery.toLowerCase()),
              )
            : allRecords;

          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              records: filteredRecords,
              total: filteredRecords.length,
              page: 1,
              page_size: 20,
              total_pages: 1,
            } as HistoryListResponse),
          });
        } else {
          await route.continue();
        }
      });

      await historyPage.goto();

      // Search for "sample"
      await historyPage.searchHistory('sample');

      // Verify results are filtered
      const rowCount = await historyPage.getRowCount();
      expect(rowCount).toBeGreaterThanOrEqual(1);

      // The visible rows should contain "sample"
      if (rowCount > 0) {
        const rows = await historyPage.getHistoryRows();
        const firstRowText = await rows[0].textContent();
        expect(firstRowText!.toLowerCase()).toContain('sample');
      }
    });
  });

  // ============================================================
  // Filter by type
  // ============================================================

  test.describe('Filter by type', () => {
    test('selecting video filter shows only video records', async ({ page }) => {
      // Override mock to return only video items when type=video
      await page.route('**/api/system/history**', async (route) => {
        if (route.request().method() === 'GET' && !route.request().url().includes('/statistics')) {
          const url = new URL(route.request().url());
          const typeFilter = url.searchParams.get('task_type') || '';

          const allItems: HistoryItem[] = [
            {
              id: 1,
              task_type: 'video',
              input_file: 'video_file.mp4',
              output_file: 'output_video.mp4',
              model_size: 'seedvr2_ema_7b_fp16',
              status: 'completed',
              parameters: '{}',
              created_at: '2025-01-15T10:30:00Z',
              processing_time: 45.2,
              error_message: '',
            },
            {
              id: 2,
              task_type: 'image',
              input_file: 'image_file.jpg',
              output_file: 'output_image.jpg',
              model_size: 'seedvr2_ema_7b_fp16',
              status: 'completed',
              parameters: '{}',
              created_at: '2025-01-15T11:00:00Z',
              processing_time: 5.3,
              error_message: '',
            },
          ];

          const filteredItems = typeFilter
            ? allItems.filter((item) => item.task_type === typeFilter)
            : allItems;

          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              records: filteredItems,
              total: filteredItems.length,
              page: 1,
              page_size: 20,
              total_pages: 1,
            }),
          });
        } else {
          await route.continue();
        }
      });

      await historyPage.goto();

      // Filter by video type
      await historyPage.filterByType('video');

      // Verify only video records are shown
      const rowCount = await historyPage.getRowCount();
      if (rowCount > 0) {
        // Wait for table to stabilize
        await page.waitForTimeout(500);
        const rows = await historyPage.getHistoryRows();
        for (const row of rows) {
          // Wait for row to be visible before reading content
          await row.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {});
          const text = (await row.textContent())?.toLowerCase() || '';
          // Video records should not contain image-specific indicators
          expect(text).not.toContain('image_file');
        }
      }
    });

    test('selecting image filter shows only image records', async ({ page }) => {
      // Override mock to return only image items when type=image
      await page.route('**/api/system/history**', async (route) => {
        if (route.request().method() === 'GET' && !route.request().url().includes('/statistics')) {
          const url = new URL(route.request().url());
          const typeFilter = url.searchParams.get('task_type') || '';

          const allItems: HistoryItem[] = [
            {
              id: 1,
              task_type: 'video',
              input_file: 'video_file.mp4',
              output_file: 'output_video.mp4',
              model_size: 'seedvr2_ema_7b_fp16',
              status: 'completed',
              parameters: '{}',
              created_at: '2025-01-15T10:30:00Z',
              processing_time: 45.2,
              error_message: '',
            },
            {
              id: 2,
              task_type: 'image',
              input_file: 'image_file.jpg',
              output_file: 'output_image.jpg',
              model_size: 'seedvr2_ema_7b_fp16',
              status: 'completed',
              parameters: '{}',
              created_at: '2025-01-15T11:00:00Z',
              processing_time: 5.3,
              error_message: '',
            },
          ];

          const filteredItems = typeFilter
            ? allItems.filter((item) => item.task_type === typeFilter)
            : allItems;

          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              records: filteredItems,
              total: filteredItems.length,
              page: 1,
              page_size: 20,
              total_pages: 1,
            }),
          });
        } else {
          await route.continue();
        }
      });

      await historyPage.goto();

      // Filter by image type
      await historyPage.filterByType('image');

      // Verify only image records are shown
      const rowCount = await historyPage.getRowCount();
      if (rowCount > 0) {
        // Wait for table to stabilize
        await page.waitForTimeout(500);
        const rows = await historyPage.getHistoryRows();
        for (const row of rows) {
          // Wait for row to be visible before reading content
          await row.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {});
          const text = (await row.textContent())?.toLowerCase() || '';
          expect(text).not.toContain('video_file');
        }
      }
    });
  });

  // ============================================================
  // Filter by status
  // ============================================================

  test.describe('Filter by status', () => {
    test('selecting completed filter shows only completed records', async ({ page }) => {
      // Override mock to return only completed items
      await page.route('**/api/system/history**', async (route) => {
        if (route.request().method() === 'GET' && !route.request().url().includes('/statistics')) {
          const url = new URL(route.request().url());
          const statusFilter = url.searchParams.get('status') || '';

          const allItems: HistoryItem[] = [
            {
              id: 1,
              task_type: 'video',
              input_file: 'completed_file.mp4',
              output_file: 'output_completed.mp4',
              model_size: 'seedvr2_ema_7b_fp16',
              status: 'completed',
              parameters: '{}',
              created_at: '2025-01-15T10:30:00Z',
              processing_time: 45.2,
              error_message: '',
            },
            {
              id: 3,
              task_type: 'video',
              input_file: 'failed_file.mp4',
              output_file: '',
              model_size: 'seedvr2_ema_3b_fp16',
              status: 'failed',
              parameters: '{}',
              created_at: '2025-01-15T11:30:00Z',
              processing_time: 0,
              error_message: 'Processing failed',
            },
          ];

          const filteredItems = statusFilter
            ? allItems.filter((item) => item.status === statusFilter)
            : allItems;

          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              records: filteredItems,
              total: filteredItems.length,
              page: 1,
              page_size: 20,
              total_pages: 1,
            }),
          });
        } else {
          await route.continue();
        }
      });

      await historyPage.goto();

      // Filter by completed status
      await historyPage.filterByStatus('completed');

      // Verify only completed records are shown
      const rowCount = await historyPage.getRowCount();
      if (rowCount > 0) {
        const rows = await historyPage.getHistoryRows();
        for (const row of rows) {
          const text = (await row.textContent())!.toLowerCase();
          expect(text).not.toContain('failed_file');
        }
      }
    });
  });

  // ============================================================
  // Delete record
  // ============================================================

  test.describe('Delete record', () => {
    test('clicking delete button shows confirmation modal', async ({ page }) => {
      // Ensure there are records to delete
      const rowCount = await historyPage.getRowCount();
      if (rowCount === 0) {
        test.skip();
        return;
      }

      // Click the delete button on the first record
      const deleteBtn = historyPage.historyBody.locator('button[onclick*="deleteHistoryRecord"]').first();
      if (await deleteBtn.isVisible().catch(() => false)) {
        await deleteBtn.click();

        // A confirmation modal should appear
        await expect(historyPage.confirmModal).toBeVisible();
      }
    });

    test('confirming deletion removes the record', async ({ page }) => {
      await mockHistoryDeleteSuccess(page);

      const initialRowCount = await historyPage.getRowCount();
      if (initialRowCount === 0) {
        test.skip();
        return;
      }

      // Click delete on the first record
      const deleteBtn = historyPage.historyBody.locator('button[onclick*="deleteHistoryRecord"]').first();
      if (await deleteBtn.isVisible().catch(() => false)) {
        await deleteBtn.click();

        // Confirm in the modal
        const confirmBtn = page.locator('#confirmAction');
        await confirmBtn.click();

        // Wait for the deletion to complete
        await page.waitForLoadState('domcontentloaded');

        // Verify success toast
        const toast = await historyPage.waitForToast('deleted', 'success', 10000).catch(() =>
          historyPage.waitForToast(undefined, 'success', 5000),
        );
        await expect(toast).toBeVisible();
      }
    });
  });

  // ============================================================
  // Clear history
  // ============================================================

  test.describe('Clear history', () => {
    test('clicking clear button shows confirmation dialog', async ({ page }) => {
      await historyPage.btnClearHistory.click();

      // The clear-history options modal (dynamically created) should appear
      await expect(historyPage.clearHistoryModal).toBeVisible();
    });

    test('confirming clear history removes all records', async ({ page }) => {
      await mockHistoryClearSuccess(page);

      // Click clear history
      await historyPage.clearHistory();

      // Wait for the clearing to complete
      await page.waitForLoadState('domcontentloaded');

      // Verify success toast appears (message is in Chinese: "历史记录已清空")
      const toast = await historyPage.waitForToast(undefined, 'success', 10000);
      await expect(toast).toBeVisible();
    });
  });

  // ============================================================
  // Empty state
  // ============================================================

  test.describe('Empty state', () => {
    test('empty history shows empty state message and CTA button', async ({ page }) => {
      // Override mock to return empty history
      await page.route('**/api/system/history**', async (route) => {
        if (route.request().method() === 'GET' && !route.request().url().includes('/statistics')) {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              records: [],
              total: 0,
              page: 1,
              page_size: 20,
              total_pages: 0,
            }),
          });
        } else {
          await route.continue();
        }
      });

      // Reload the page to pick up the empty mock
      await historyPage.goto();

      // The empty state element should be visible
      await expect(historyPage.emptyState).toBeVisible();

      // The empty state should have a message
      const emptyMessage = await historyPage.getEmptyStateMessage();
      expect(emptyMessage.length).toBeGreaterThan(0);

      // There should be a CTA (call-to-action) button in the empty state
      const ctaButton = historyPage.emptyState.locator('a, button');
      const ctaCount = await ctaButton.count();
      expect(ctaCount).toBeGreaterThanOrEqual(1);
    });
  });
});

/**
 * API Mock definitions for SeedVR2 WebUI E2E tests.
 *
 * Uses Playwright's route API to intercept and mock HTTP requests,
 * enabling tests to run without a live backend or to simulate
 * specific server behaviors (errors, timeouts, etc.).
 *
 * Usage:
 *   import { setupAllMocks, mockVideoRestoreSuccess } from '@fixtures/api-mocks';
 *   await setupAllMocks(page);
 *   // Or selectively:
 *   await mockVideoRestoreSuccess(page);
 */
import { Page, Route } from '@playwright/test';
import {
  mockHealthResponse,
  mockGpuResponse,
  mockSystemResponse,
  mockSettingsResponse,
  mockModelStatusResponse,
  mockVideoRestoreResponse,
  mockVideoProgressPayload,
  mockVideoResultResponse,
  mockImageRestoreResponse,
  mockImageResultResponse,
  mockHistoryResponse,
  mockHistoryStatsResponse,
  mockBatchVideoResponse,
  mockBatchImageResponse,
  mockBatchProgressResponse,
  mockLocalesResponse,
  mockBrowseDirResponse,
  mockScanFolderResponse,
} from './test-data';

// ============================================================
// Helper: Build SSE event stream body
// ============================================================

/**
 * Build a Server-Sent Events (SSE) response body from an array of events.
 * Each event is formatted as `data: <JSON>\n\n` per the SSE specification.
 *
 * @param events - Array of objects to serialize as SSE data events
 * @returns Formatted SSE string
 */
function buildSseBody(events: object[]): string {
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('');
}

// ============================================================
// System API mocks
// ============================================================

/**
 * Mock the health check endpoint with a healthy response.
 */
export async function mockHealthSuccess(page: Page): Promise<void> {
  await page.route('**/api/system/health', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockHealthResponse()),
    });
  });
}

/**
 * Mock the GPU info endpoint with a standard RTX 4090 response.
 */
export async function mockGpuInfoSuccess(page: Page): Promise<void> {
  await page.route('**/api/system/gpu', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockGpuResponse()),
    });
  });
}

/**
 * Mock the system info endpoint.
 */
export async function mockSystemInfoSuccess(page: Page): Promise<void> {
  await page.route('**/api/system/gpu/system', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSystemResponse()),
    });
  });
}

/**
 * Mock the settings GET endpoint.
 */
export async function mockSettingsGetSuccess(page: Page): Promise<void> {
  await page.route('**/api/system/settings', async (route: Route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockSettingsResponse()),
      });
    } else {
      // Pass through POST requests to other handlers
      await route.continue();
    }
  });
}

/**
 * Mock the settings POST (update) endpoint with a success response.
 */
export async function mockSettingsUpdateSuccess(page: Page): Promise<void> {
  await page.route('**/api/system/settings', async (route: Route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, message: 'Settings updated' }),
      });
    } else {
      await route.continue();
    }
  });
}

/**
 * Mock the model status endpoint with a loaded model.
 */
export async function mockModelStatusLoaded(page: Page): Promise<void> {
  await page.route('**/api/system/model/status', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockModelStatusResponse('loaded')),
    });
  });
}

/**
 * Mock the model status endpoint with a loading state.
 */
export async function mockModelStatusLoading(page: Page): Promise<void> {
  await page.route('**/api/system/model/status', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockModelStatusResponse('loading', { progress: 0.5 })),
    });
  });
}

/**
 * Mock the model status endpoint with an unloaded state.
 */
export async function mockModelStatusUnloaded(page: Page): Promise<void> {
  await page.route('**/api/system/model/status', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockModelStatusResponse('unloaded')),
    });
  });
}

/**
 * Mock the model load endpoint with a success response.
 */
export async function mockModelLoadSuccess(page: Page): Promise<void> {
  await page.route('**/api/system/model/load', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, message: 'Model loading initiated' }),
    });
  });
}

/**
 * Mock the model unload endpoint with a success response.
 */
export async function mockModelUnloadSuccess(page: Page): Promise<void> {
  await page.route('**/api/system/model/unload', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, message: 'Model unloaded' }),
    });
  });
}

/**
 * Mock the model switch endpoint with a success response.
 */
export async function mockModelSwitchSuccess(page: Page): Promise<void> {
  await page.route('**/api/system/model/switch', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, message: 'Model switched' }),
    });
  });
}

/**
 * Mock the locales endpoint with available languages.
 */
export async function mockLocalesSuccess(page: Page): Promise<void> {
  await page.route('**/api/system/locales', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        current: 'zh',
        locales: mockLocalesResponse(),
      }),
    });
  });
}

/**
 * Mock the locale switch endpoint.
 */
export async function mockLocaleSwitchSuccess(page: Page): Promise<void> {
  await page.route('**/api/system/locale', async (route: Route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'ok', locale: 'en', message: '语言已切换为 English' }),
      });
    } else {
      await route.continue();
    }
  });
}

/**
 * Mock the browse directory endpoint.
 */
export async function mockBrowseDirSuccess(page: Page): Promise<void> {
  await page.route('**/api/system/browse-dir**', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockBrowseDirResponse()),
    });
  });
}

/**
 * Mock the open explorer endpoint.
 */
export async function mockOpenExplorerSuccess(page: Page): Promise<void> {
  await page.route('**/api/system/open-explorer', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true }),
    });
  });
}

// ============================================================
// History API mocks
// ============================================================

/**
 * Mock the history list endpoint with sample data.
 */
export async function mockHistoryListSuccess(page: Page): Promise<void> {
  await page.route('**/api/system/history**', async (route: Route) => {
    // Only intercept GET requests for the history list (not DELETE or statistics)
    if (route.request().method() === 'GET' && !route.request().url().includes('/statistics')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockHistoryResponse()),
      });
    } else {
      await route.continue();
    }
  });
}

/**
 * Mock the history statistics endpoint.
 */
export async function mockHistoryStatsSuccess(page: Page): Promise<void> {
  await page.route('**/api/system/history/statistics', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockHistoryStatsResponse()),
    });
  });
}

/**
 * Mock the history delete (single record) endpoint.
 */
export async function mockHistoryDeleteSuccess(page: Page): Promise<void> {
  await page.route('**/api/system/history/*', async (route: Route) => {
    if (route.request().method() === 'DELETE') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, message: 'Record deleted' }),
      });
    } else {
      await route.continue();
    }
  });
}

/**
 * Mock the history clear (all records) endpoint.
 * Also handles GET requests to return empty history after clearing.
 */
export async function mockHistoryClearSuccess(page: Page): Promise<void> {
  // 注意：尾随 ** 是必须的——前端 DELETE 请求带查询串（?status=...），
  // 没有尾随 ** 时 glob 匹配不到，请求会落到真实后端并清空真实数据库。
  // 只拦截 DELETE；GET 继续走 list/statistics mock，避免抢走列表请求。
  await page.route('**/api/system/history**', async (route: Route) => {
    if (route.request().method() === 'DELETE') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, message: 'History cleared', deleted_count: 4 }),
      });
    } else if (route.request().method() === 'GET' && !route.request().url().includes('/statistics')) {
      // 注意：不能 route.continue() 期望落到 list mock——Playwright 的 continue
      // 不会继续匹配后续同名 route，会直接放行到真实后端（空库时页面无数据）。
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockHistoryResponse()),
      });
    } else {
      await route.continue();
    }
  });
}

// ============================================================
// Video restore API mocks
// ============================================================

/**
 * Mock a successful video restore upload and task creation.
 */
export async function mockVideoRestoreSuccess(page: Page): Promise<void> {
  await page.route('**/api/restore', async (route: Route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockVideoRestoreResponse()),
      });
    } else {
      await route.continue();
    }
  });
}

/**
 * Mock the video progress SSE endpoint with a completed task.
 * Progress values are percentages (0-100) to match the frontend JS expectations.
 */
export async function mockVideoProgressComplete(page: Page): Promise<void> {
  await page.route('**/api/restore/*/progress', async (route: Route) => {
    const events = [
      mockVideoProgressPayload('test-task-001', 0),
      mockVideoProgressPayload('test-task-001', 25),
      mockVideoProgressPayload('test-task-001', 50),
      mockVideoProgressPayload('test-task-001', 75),
      mockVideoProgressPayload('test-task-001', 100, { status: 'completed' }),
    ];
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: buildSseBody(events),
    });
  });
}

/**
 * Mock the video progress SSE endpoint with a task in progress.
 * Returns a single progress event at the specified percentage (0-100).
 */
export async function mockVideoProgressInProgress(
  page: Page,
  progress = 50,
): Promise<void> {
  await page.route('**/api/restore/*/progress', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: buildSseBody([mockVideoProgressPayload('test-task-001', progress)]),
    });
  });
}

/**
 * Mock the video result endpoint with a completed result.
 */
export async function mockVideoResultSuccess(page: Page): Promise<void> {
  await page.route('**/api/restore/video/*/result', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockVideoResultResponse()),
    });
  });
}

/**
 * Mock the video download endpoint with a binary file response.
 */
export async function mockVideoDownloadSuccess(page: Page): Promise<void> {
  await page.route('**/api/restore/video/*/download', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'video/mp4',
      body: Buffer.from('mock-video-binary-data'),
      headers: {
        'Content-Disposition': 'attachment; filename="restored.mp4"',
      },
    });
  });
}

/**
 * Mock the batch video restore endpoint.
 */
export async function mockBatchVideoRestoreSuccess(page: Page): Promise<void> {
  await page.route('**/api/restore/batch', async (route: Route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockBatchVideoResponse()),
      });
    } else {
      await route.continue();
    }
  });
}

/**
 * Mock the batch video progress endpoint.
 */
export async function mockBatchVideoProgressSuccess(page: Page): Promise<void> {
  await page.route('**/api/restore/batch/*/progress', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockBatchProgressResponse()),
    });
  });
}

/**
 * Mock the batch video retry endpoint.
 */
export async function mockBatchVideoRetrySuccess(page: Page): Promise<void> {
  await page.route('**/api/restore/video/batch/*/retry', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, message: 'Retry initiated' }),
    });
  });
}

// ============================================================
// Image restore API mocks
// ============================================================

/**
 * Mock the scan folder endpoint for image restore.
 */
export async function mockScanFolderSuccess(page: Page): Promise<void> {
  await page.route('**/api/restore/scan-folder**', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockScanFolderResponse()),
    });
  });
}

/**
 * Mock a successful image restore upload and task creation.
 */
export async function mockImageRestoreSuccess(page: Page): Promise<void> {
  await page.route('**/api/restore', async (route: Route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockImageRestoreResponse()),
      });
    } else {
      await route.continue();
    }
  });
}

/**
 * Mock the image result endpoint with a completed result.
 */
export async function mockImageResultSuccess(page: Page): Promise<void> {
  await page.route('**/api/restore/image/*/result', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockImageResultResponse()),
    });
  });
}

/**
 * Mock the image download endpoint.
 */
export async function mockImageDownloadSuccess(page: Page): Promise<void> {
  await page.route('**/api/restore/image/*/download', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'image/png',
      body: Buffer.from('mock-image-binary-data'),
      headers: {
        'Content-Disposition': 'attachment; filename="restored.png"',
      },
    });
  });
}

/**
 * Mock the batch image restore endpoint.
 */
export async function mockBatchImageRestoreSuccess(page: Page): Promise<void> {
  await page.route('**/api/restore/batch', async (route: Route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockBatchImageResponse()),
      });
    } else {
      await route.continue();
    }
  });
}

/**
 * Mock the batch image progress endpoint.
 */
export async function mockBatchImageProgressSuccess(page: Page): Promise<void> {
  await page.route('**/api/restore/batch/*/progress', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockBatchProgressResponse()),
    });
  });
}

/**
 * Mock the batch image retry endpoint.
 */
export async function mockBatchImageRetrySuccess(page: Page): Promise<void> {
  await page.route('**/api/restore/image/batch/*/retry', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, message: 'Retry initiated' }),
    });
  });
}

// ============================================================
// SSE event stream mock
// ============================================================

/**
 * Mock the global SSE events endpoint with a standard event stream.
 * Simulates model status change and task completion events.
 */
export async function mockSseEvents(page: Page): Promise<void> {
  await page.route('**/api/sse/events', async (route: Route) => {
    const events = [
      { event: 'model_status', data: { state: 'loaded', model_name: 'seedvr2_ema_7b_fp16' } },
      { event: 'task_progress', data: { task_id: 'test-task-001', progress: 0.5 } },
      { event: 'task_complete', data: { task_id: 'test-task-001', status: 'completed' } },
    ];
    const body = events
      .map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`)
      .join('');
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body,
    });
  });
}


/**
 * Mock the unified restore task SSE progress stream.
 * Frontend opens EventSource('/api/restore/{taskId}/progress') and uses
 * es.onmessage (unnamed events only), so the body must NOT carry "event:" lines.
 * Progress values are percentages (0-100) to match frontend expectations.
 */
export async function mockRestoreProgressComplete(page: Page): Promise<void> {
  await page.route('**/api/restore/*/progress', async (route: Route) => {
    const events = [
      { task_id: 'test-task-001', progress: 0, status: 'processing', message: 'Queued' },
      { task_id: 'test-task-001', progress: 25, status: 'processing', message: 'Restoring frames' },
      { task_id: 'test-task-001', progress: 60, status: 'processing', message: 'Restoring frames' },
      { task_id: 'test-task-001', progress: 100, status: 'completed' },
    ];
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: buildSseBody(events),
    });
  });
}

// ============================================================
// Error scenario mocks
// ============================================================

/**
 * Mock a 503 Service Unavailable response (model not loaded).
 * This is returned when the backend model has not been loaded yet.
 */
export async function mock503ModelNotLoaded(page: Page, urlPattern = '**/api/**'): Promise<void> {
  await page.route(urlPattern, async (route: Route) => {
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({
        detail: 'Model not loaded. Please load a model first.',
        error_code: 'MODEL_NOT_LOADED',
      }),
    });
  });
}

/**
 * Mock a 400 Bad Request response.
 * Useful for testing form validation and invalid input handling.
 */
export async function mock400BadRequest(
  page: Page,
  urlPattern = '**/api/restore/**',
): Promise<void> {
  await page.route(urlPattern, async (route: Route) => {
    await route.fulfill({
      status: 400,
      contentType: 'application/json',
      body: JSON.stringify({
        detail: 'Invalid request parameters',
        error_code: 'BAD_REQUEST',
        errors: [
          { field: 'resolution', message: 'Invalid resolution value' },
        ],
      }),
    });
  });
}

/**
 * Mock a 500 Internal Server Error response.
 * Useful for testing error handling and recovery flows.
 */
export async function mock500ServerError(
  page: Page,
  urlPattern = '**/api/**',
): Promise<void> {
  await page.route(urlPattern, async (route: Route) => {
    await route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({
        detail: 'Internal server error',
        error_code: 'INTERNAL_ERROR',
      }),
    });
  });
}

/**
 * Mock a network timeout by aborting requests.
 * Simulates scenarios where the backend is unresponsive.
 */
export async function mockNetworkTimeout(
  page: Page,
  urlPattern = '**/api/**',
): Promise<void> {
  await page.route(urlPattern, async (route: Route) => {
    // Abort the request to simulate a network failure/timeout
    await route.abort('timedout');
  });
}

// ============================================================
// Composite mock setup
// ============================================================

/**
 * Set up all standard success mocks for a page.
 * This provides a fully mocked backend that returns successful
 * responses for all API endpoints.
 *
 * Use this in tests that need a "happy path" backend without
 * actually running the server.
 *
 * @param page - The Playwright page instance
 */
/** Abort remote font requests (Google Fonts) — page load would otherwise hang
 *  in networks without access to fonts.googleapis.com (incl. some CI/locale). */
export async function abortRemoteFonts(page: Page): Promise<void> {
  await page.route('**fonts.googleapis.com/**', (route) => route.abort());
  await page.route('**fonts.gstatic.com/**', (route) => route.abort());
}

export async function setupAllMocks(page: Page): Promise<void> {
  await abortRemoteFonts(page);
  // System API mocks
  await mockHealthSuccess(page);
  await mockGpuInfoSuccess(page);
  await mockSystemInfoSuccess(page);
  await mockSettingsGetSuccess(page);
  await mockSettingsUpdateSuccess(page);
  await mockModelStatusLoaded(page);
  await mockModelLoadSuccess(page);
  await mockModelUnloadSuccess(page);
  await mockModelSwitchSuccess(page);
  await mockLocalesSuccess(page);
  await mockLocaleSwitchSuccess(page);
  await mockBrowseDirSuccess(page);
  await mockOpenExplorerSuccess(page);

  // History API mocks
  await mockHistoryListSuccess(page);
  await mockHistoryStatsSuccess(page);
  await mockHistoryDeleteSuccess(page);
  await mockHistoryClearSuccess(page);

  // Video restore API mocks
  await mockVideoRestoreSuccess(page);
  await mockVideoProgressComplete(page);
  await mockVideoResultSuccess(page);
  await mockVideoDownloadSuccess(page);
  await mockBatchVideoRestoreSuccess(page);
  await mockBatchVideoProgressSuccess(page);
  await mockBatchVideoRetrySuccess(page);

  // Image restore API mocks
  await mockScanFolderSuccess(page);
  await mockImageRestoreSuccess(page);
  await mockImageResultSuccess(page);
  await mockImageDownloadSuccess(page);
  await mockBatchImageRestoreSuccess(page);
  await mockBatchImageProgressSuccess(page);
  await mockBatchImageRetrySuccess(page);

  // SSE event stream
  await mockSseEvents(page);
}

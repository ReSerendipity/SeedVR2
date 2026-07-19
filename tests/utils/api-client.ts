/**
 * Backend API client for SeedVR2 WebUI E2E test data setup/teardown.
 *
 * Provides typed methods for interacting with the SeedVR2 REST API
 * during test setup (e.g., loading a model, configuring settings)
 * and teardown (e.g., clearing history, unloading the model).
 *
 * This client uses Node.js built-in fetch and is intended for use
 * in Playwright test fixtures and beforeAll/beforeEach hooks.
 *
 * Usage:
 *   import { ApiClient } from '@utils/api-client';
 *   const client = new ApiClient('http://127.0.0.1:7870');
 *   const health = await client.healthCheck();
 */

/** Default base URL matching the SeedVR2 application server */
const DEFAULT_BASE_URL = 'http://127.0.0.1:7870';

/** Default request timeout in milliseconds */
const DEFAULT_TIMEOUT = 10000;

export class ApiClient {
  private readonly baseUrl: string;
  private readonly timeout: number;

  /**
   * Create a new API client instance.
   *
   * @param baseUrl - Base URL of the SeedVR2 server (default: http://127.0.0.1:7870)
   * @param timeout - Request timeout in milliseconds (default: 10000)
   */
  constructor(baseUrl = DEFAULT_BASE_URL, timeout = DEFAULT_TIMEOUT) {
    this.baseUrl = baseUrl.replace(/\/+$/, ''); // Remove trailing slash
    this.timeout = timeout;
  }

  // ============================================================
  // Generic HTTP methods
  // ============================================================

  /**
   * Perform a GET request to the specified path.
   *
   * @param path - API path (e.g., '/api/system/health')
   * @param options - Optional fetch options (query params, headers, etc.)
   * @returns Parsed JSON response
   */
  async get<T = unknown>(path: string, options?: { params?: Record<string, string> }): Promise<T> {
    const url = new URL(`${this.baseUrl}${path}`);
    if (options?.params) {
      Object.entries(options.params).forEach(([key, value]) => {
        url.searchParams.set(key, value);
      });
    }

    const response = await fetch(url.toString(), {
      method: 'GET',
      headers: { 'Accept': 'application/json' },
      signal: AbortSignal.timeout(this.timeout),
    });

    if (!response.ok) {
      throw new ApiClientError(`GET ${path} failed: ${response.status} ${response.statusText}`, response.status);
    }

    return response.json() as Promise<T>;
  }

  /**
   * Perform a POST request to the specified path.
   *
   * @param path - API path
   * @param body - Request body (will be JSON-serialized)
   * @returns Parsed JSON response
   */
  async post<T = unknown>(path: string, body?: unknown): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(this.timeout),
    });

    if (!response.ok) {
      throw new ApiClientError(`POST ${path} failed: ${response.status} ${response.statusText}`, response.status);
    }

    return response.json() as Promise<T>;
  }

  /**
   * Perform a DELETE request to the specified path.
   *
   * @param path - API path
   * @returns Parsed JSON response
   */
  async delete<T = unknown>(path: string): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: 'DELETE',
      headers: { 'Accept': 'application/json' },
      signal: AbortSignal.timeout(this.timeout),
    });

    if (!response.ok) {
      throw new ApiClientError(`DELETE ${path} failed: ${response.status} ${response.statusText}`, response.status);
    }

    return response.json() as Promise<T>;
  }

  // ============================================================
  // Health check
  // ============================================================

  /**
   * Check the health of the SeedVR2 backend.
   * Returns the health status or throws if the server is unreachable.
   */
  async healthCheck(): Promise<{ status: string; version: string; uptime: number }> {
    return this.get('/api/system/health');
  }

  /**
   * Wait for the backend to become healthy by polling the health endpoint.
   *
   * @param maxRetries - Maximum number of retry attempts (default: 10)
   * @param intervalMs - Interval between retries in milliseconds (default: 2000)
   * @throws Error if the backend does not become healthy within the retry limit
   */
  async waitForHealthy(maxRetries = 10, intervalMs = 2000): Promise<void> {
    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        const health = await this.healthCheck();
        if (health.status === 'healthy') {
          return;
        }
      } catch {
        // Server not ready yet, continue polling
      }
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
    throw new Error(`Backend did not become healthy after ${maxRetries} attempts`);
  }

  // ============================================================
  // Settings API
  // ============================================================

  /**
   * Get the current application settings.
   */
  async getSettings(): Promise<Record<string, unknown>> {
    return this.get('/api/system/settings');
  }

  /**
   * Update application settings.
   *
   * @param settings - Partial settings object to merge with existing settings
   */
  async updateSettings(settings: Record<string, unknown>): Promise<{ success: boolean; message: string }> {
    return this.post('/api/system/settings', settings);
  }

  // ============================================================
  // Model management API
  // ============================================================

  /**
   * Get the current model status (loaded, loading, unloaded, error).
   */
  async getModelStatus(): Promise<{
    state: string;
    model_name?: string;
    progress?: number;
    error?: string;
    vram_usage: number;
  }> {
    return this.get('/api/system/model/status');
  }

  /**
   * Load a model by name.
   *
   * @param modelName - Name of the model to load (e.g., 'seedvr2_ema_7b_fp16')
   */
  async loadModel(modelName?: string): Promise<{ success: boolean; message: string }> {
    return this.post('/api/system/model/load', modelName ? { model_name: modelName } : undefined);
  }

  /**
   * Unload the currently loaded model.
   */
  async unloadModel(): Promise<{ success: boolean; message: string }> {
    return this.post('/api/system/model/unload');
  }

  /**
   * Switch to a different model.
   *
   * @param modelName - Name of the model to switch to
   */
  async switchModel(modelName: string): Promise<{ success: boolean; message: string }> {
    return this.post('/api/system/model/switch', { model_name: modelName });
  }

  /**
   * Wait for a model to finish loading by polling the model status.
   *
   * @param maxRetries - Maximum number of retry attempts (default: 30)
   * @param intervalMs - Interval between retries in milliseconds (default: 2000)
   * @throws Error if the model does not reach 'loaded' state within the retry limit
   */
  async waitForModelLoaded(maxRetries = 30, intervalMs = 2000): Promise<void> {
    for (let attempt = 0; attempt < maxRetries; attempt++) {
      const status = await this.getModelStatus();
      if (status.state === 'loaded') {
        return;
      }
      if (status.state === 'error') {
        throw new Error(`Model loading failed: ${status.error ?? 'Unknown error'}`);
      }
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
    throw new Error(`Model did not load after ${maxRetries} attempts`);
  }

  // ============================================================
  // History API
  // ============================================================

  /**
   * Get history records with optional pagination, filter, and search.
   *
   * @param options - Pagination and filter options
   */
  async getHistory(options?: {
    page?: number;
    page_size?: number;
    type?: 'video' | 'image';
    status?: string;
    search?: string;
  }): Promise<{
    items: Array<Record<string, unknown>>;
    total: number;
    page: number;
    page_size: number;
  }> {
    const params: Record<string, string> = {};
    if (options?.page) params.page = String(options.page);
    if (options?.page_size) params.page_size = String(options.page_size);
    if (options?.type) params.type = options.type;
    if (options?.status) params.status = options.status;
    if (options?.search) params.search = options.search;
    return this.get('/api/system/history', { params });
  }

  /**
   * Get history statistics.
   */
  async getHistoryStatistics(): Promise<Record<string, unknown>> {
    return this.get('/api/system/history/statistics');
  }

  /**
   * Delete a single history record by ID.
   *
   * @param id - History record ID
   */
  async deleteHistoryRecord(id: string): Promise<{ success: boolean; message: string }> {
    return this.delete(`/api/system/history/${id}`);
  }

  /**
   * Clear all history records.
   */
  async clearHistory(): Promise<{ success: boolean; message: string }> {
    return this.delete('/api/system/history');
  }

  // ============================================================
  // GPU / System info
  // ============================================================

  /**
   * Get GPU information (backend, device name, VRAM, etc.).
   */
  async getGpuInfo(): Promise<Record<string, unknown>> {
    return this.get('/api/system/gpu');
  }

  /**
   * Get system information (OS, CPU, RAM, Python version, etc.).
   */
  async getSystemInfo(): Promise<Record<string, unknown>> {
    return this.get('/api/system/gpu/system');
  }

  // ============================================================
  // Locale API
  // ============================================================

  /**
   * Get available locales.
   */
  async getLocales(): Promise<Array<{ code: string; name: string; native_name: string }>> {
    return this.get('/api/system/locales');
  }

  /**
   * Switch the application locale.
   *
   * @param locale - Locale code (e.g., 'zh', 'en')
   */
  async switchLocale(locale: string): Promise<{ success: boolean; message: string }> {
    return this.post('/api/system/locale', { locale });
  }
}

/**
 * Custom error class for API client errors.
 * Includes the HTTP status code for programmatic error handling.
 */
export class ApiClientError extends Error {
  readonly statusCode: number;

  constructor(message: string, statusCode: number) {
    super(message);
    this.name = 'ApiClientError';
    this.statusCode = statusCode;
  }
}

/**
 * Pre-configured API client instance using default settings.
 * Import this for quick access in test files.
 *
 * Usage:
 *   import { apiClient } from '@utils/api-client';
 *   await apiClient.healthCheck();
 */
export const apiClient = new ApiClient();

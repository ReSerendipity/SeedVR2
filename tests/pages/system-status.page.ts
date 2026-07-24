import { Page, Locator } from '@playwright/test';
import { BasePage } from './base.page';

export class SystemStatusPage extends BasePage {
  // Refresh button
  readonly btnRefreshStatus: Locator;
  readonly refreshIcon: Locator;

  // GPU info selectors
  readonly gpuBackendBadge: Locator;
  readonly gpuName: Locator;
  readonly gpuVramTotal: Locator;
  readonly gpuVramAvail: Locator;
  readonly gpuVramPct: Locator;
  readonly gpuVramBar: Locator;
  readonly gpuUtil: Locator;
  readonly gpuUtilBar: Locator;
  readonly gpuCudaVer: Locator;
  readonly gpuDriverVer: Locator;

  // Model status selectors
  readonly modelStatusBadge: Locator;
  readonly modelLoaded: Locator;
  readonly currentModel: Locator;
  readonly availableModels: Locator;
  readonly modelVramUsage: Locator;

  // Memory selectors
  readonly memTotal: Locator;
  readonly memAvail: Locator;
  readonly memPct: Locator;
  readonly memBar: Locator;
  readonly cpuCount: Locator;

  // Runtime selectors
  readonly uptime: Locator;
  readonly platform: Locator;
  readonly pythonVer: Locator;
  readonly serviceStatus: Locator;

  readonly path = '/';

  constructor(page: Page) {
    super(page);

    // Refresh
    this.btnRefreshStatus = page.locator('#btnRefreshStatus');
    this.refreshIcon = page.locator('#refreshIcon');

    // GPU info
    this.gpuBackendBadge = page.locator('#gpuBackendBadge');
    this.gpuName = page.locator('#gpuName');
    this.gpuVramTotal = page.locator('#gpuVramTotal');
    this.gpuVramAvail = page.locator('#gpuVramAvail');
    this.gpuVramPct = page.locator('#gpuVramPct');
    this.gpuVramBar = page.locator('#gpuVramBar');
    this.gpuUtil = page.locator('#gpuUtil');
    this.gpuUtilBar = page.locator('#gpuUtilBar');
    this.gpuCudaVer = page.locator('#gpuCudaVer');
    this.gpuDriverVer = page.locator('#gpuDriverVer');

    // Model status
    this.modelStatusBadge = page.locator('#modelStatusBadge');
    this.modelLoaded = page.locator('#modelLoaded');
    this.currentModel = page.locator('#currentModel');
    this.availableModels = page.locator('#availableModels');
    this.modelVramUsage = page.locator('#modelVramUsage');

    // Memory
    this.memTotal = page.locator('#memTotal');
    this.memAvail = page.locator('#memAvail');
    this.memPct = page.locator('#memPct');
    this.memBar = page.locator('#memBar');
    this.cpuCount = page.locator('#cpuCount');

    // Runtime
    this.uptime = page.locator('#uptime');
    this.platform = page.locator('#platform');
    this.pythonVer = page.locator('#pythonVer');
    this.serviceStatus = page.locator('#serviceStatus');
  }

  async goto(): Promise<void> {
    await this.navigate(this.path);
  }

  async refreshStatus(): Promise<void> {
    await this.btnRefreshStatus.click();
    await this.page.waitForLoadState('networkidle');
  }

  async getGpuName(): Promise<string> {
    const text = await this.gpuName.textContent();
    return text?.trim() || '';
  }

  async getVramTotal(): Promise<string> {
    const text = await this.gpuVramTotal.textContent();
    return text?.trim() || '';
  }

  async getVramAvailable(): Promise<string> {
    const text = await this.gpuVramAvail.textContent();
    return text?.trim() || '';
  }

  async getModelStatus(): Promise<string> {
    const text = await this.modelStatusBadge.textContent();
    return text?.trim() || '';
  }

  async getMemoryTotal(): Promise<string> {
    const text = await this.memTotal.textContent();
    return text?.trim() || '';
  }

  async getUptime(): Promise<string> {
    const text = await this.uptime.textContent();
    return text?.trim() || '';
  }

  async getServiceStatus(): Promise<string> {
    const text = await this.serviceStatus.textContent();
    return text?.trim() || '';
  }

  async waitForStatusLoad(): Promise<void> {
    // Wait for skeleton loaders to be replaced with actual data.
    // Use waitForSelector for each key element first, then verify no skeletons remain.
    await this.page.waitForSelector('#gpuName', { state: 'attached', timeout: 30000 });
    await this.page.waitForSelector('#memTotal', { state: 'attached', timeout: 30000 });
    await this.page.waitForSelector('#uptime', { state: 'attached', timeout: 30000 });

    // Now wait for the skeletons inside these elements to be removed
    await this.page.waitForFunction(() => {
      const gpuEl = document.getElementById('gpuName');
      const memEl = document.getElementById('memTotal');
      const uptimeEl = document.getElementById('uptime');
      return (
        gpuEl && !gpuEl.querySelector('.sv-skeleton') &&
        memEl && !memEl.querySelector('.sv-skeleton') &&
        uptimeEl && !uptimeEl.querySelector('.sv-skeleton')
      );
    }, { timeout: 30000 });
  }
}

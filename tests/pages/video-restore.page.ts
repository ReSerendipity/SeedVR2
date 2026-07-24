import { Page, Locator } from '@playwright/test';
import { BasePage } from './base.page';

export class VideoRestorePage extends BasePage {
  // Upload selectors
  readonly videoUploadZone: Locator;
  readonly videoFileInput: Locator;
  readonly videoFileInfo: Locator;
  readonly uploadStatus: Locator;
  readonly inputModeTabs: Locator;
  readonly panelFile: Locator;
  readonly panelFolder: Locator;
  readonly folderPath: Locator;
  readonly btnPickVideoFolder: Locator;

  // Form & action selectors
  readonly videoRestoreForm: Locator;
  readonly btnStartRestore: Locator;

  // Progress selectors
  readonly progressCard: Locator;
  readonly progressBar: Locator;
  readonly progressText: Locator;
  readonly progressPct: Locator;
  readonly progressFrames: Locator;
  readonly progressEta: Locator;

  // Batch progress selectors
  readonly batchProgressCard: Locator;
  readonly batchProgressBar: Locator;
  readonly batchProgressLabel: Locator;
  readonly batchProgressPct: Locator;
  readonly batchCompletedCount: Locator;
  readonly batchFailedCount: Locator;
  readonly batchCurrentFile: Locator;
  readonly batchCurrentName: Locator;
  readonly batchFileList: Locator;
  readonly batchRetrySection: Locator;
  readonly btnRetryFailed: Locator;

  // Result selectors
  readonly resultCard: Locator;
  readonly resultVideo: Locator;
  readonly btnDownload: Locator;

  // Compare selectors
  readonly compareCard: Locator;
  readonly compareContainer: Locator;
  readonly compareSlider: Locator;

  // Workflow node selectors - Shrink
  readonly shrinkNode: Locator;
  readonly shrinkEnabled: Locator;
  readonly shrinkAlgorithm: Locator;
  readonly shrinkRatio: Locator;

  // Workflow node selectors - DiT
  readonly ditModel: Locator;
  readonly ditDevice: Locator;
  readonly ditBlocksToSwap: Locator;
  readonly ditSwapIo: Locator;
  readonly ditOffloadDevice: Locator;
  readonly ditCacheModel: Locator;
  readonly ditAttentionMode: Locator;

  // Workflow node selectors - VAE
  readonly vaeModel: Locator;
  readonly vaeDevice: Locator;
  readonly vaeEncodeTiled: Locator;
  readonly vaeEncodeTileSize: Locator;
  readonly vaeEncodeTileOverlap: Locator;
  readonly vaeDecodeTiled: Locator;
  readonly vaeDecodeTileSize: Locator;
  readonly vaeDecodeTileOverlap: Locator;
  readonly vaeTileDebug: Locator;
  readonly vaeOffloadDevice: Locator;
  readonly vaeCacheModel: Locator;

  // Workflow node selectors - Upscaler
  readonly upscalerSeed: Locator;
  readonly upscalerResolution: Locator;
  readonly upscalerBatchSize: Locator;
  readonly upscalerColorCorrection: Locator;
  readonly upscalerMaxResolution: Locator;
  readonly upscalerUniformBatch: Locator;
  readonly upscalerTemporalOverlap: Locator;
  readonly upscalerPrependFrames: Locator;
  readonly upscalerInputNoiseScale: Locator;
  readonly upscalerLatentNoiseScale: Locator;
  readonly upscalerOffloadDevice: Locator;
  readonly upscalerDebug: Locator;

  // Workflow node selectors - Output
  readonly outputFormat: Locator;
  readonly outputCrf: Locator;

  readonly path = '/restore';

  constructor(page: Page) {
    super(page);

    // Upload
    this.videoUploadZone = page.locator('#videoUploadZone');
    this.videoFileInput = page.locator('#videoFileInput');
    this.videoFileInfo = page.locator('#videoFileInfo');
    this.uploadStatus = page.locator('#uploadStatus');
    this.inputModeTabs = page.locator('.sv-input-mode-tab');
    this.panelFile = page.locator('#panelFile');
    this.panelFolder = page.locator('#panelFolder');
    this.folderPath = page.locator('#folderPath');
    this.btnPickVideoFolder = page.locator('#btnPickVideoFolder');

    // Form & actions
    this.videoRestoreForm = page.locator('#videoRestoreForm');
    this.btnStartRestore = page.locator('#btnStartRestore');

    // Progress
    this.progressCard = page.locator('#progressCard');
    this.progressBar = page.locator('#progressBar');
    this.progressText = page.locator('#progressText');
    this.progressPct = page.locator('#progressPct');
    this.progressFrames = page.locator('#progressFrames');
    this.progressEta = page.locator('#progressEta');

    // Batch progress
    this.batchProgressCard = page.locator('#batchProgressCard');
    this.batchProgressBar = page.locator('#batchProgressBar');
    this.batchProgressLabel = page.locator('#batchProgressLabel');
    this.batchProgressPct = page.locator('#batchProgressPct');
    this.batchCompletedCount = page.locator('#batchCompletedCount');
    this.batchFailedCount = page.locator('#batchFailedCount');
    this.batchCurrentFile = page.locator('#batchCurrentFile');
    this.batchCurrentName = page.locator('#batchCurrentName');
    this.batchFileList = page.locator('#batchFileList');
    this.batchRetrySection = page.locator('#batchRetrySection');
    this.btnRetryFailed = page.locator('#btnRetryFailed');

    // Result
    this.resultCard = page.locator('#resultCard');
    this.resultVideo = page.locator('#resultVideo');
    this.btnDownload = page.locator('#btnDownload');

    // Compare
    this.compareCard = page.locator('#compareCard');
    this.compareContainer = page.locator('#compareContainer');
    this.compareSlider = page.locator('#compareSlider');

    // Shrink node
    this.shrinkNode = page.locator('#shrinkNode');
    this.shrinkEnabled = page.locator('#shrinkEnabled');
    this.shrinkAlgorithm = page.locator('#shrinkAlgorithm');
    this.shrinkRatio = page.locator('#shrinkRatio');

    // DiT node
    this.ditModel = page.locator('#ditModel');
    this.ditDevice = page.locator('#ditDevice');
    this.ditBlocksToSwap = page.locator('#ditBlocksToSwap');
    this.ditSwapIo = page.locator('#ditSwapIo');
    this.ditOffloadDevice = page.locator('#ditOffloadDevice');
    this.ditCacheModel = page.locator('#ditCacheModel');
    this.ditAttentionMode = page.locator('#ditAttentionMode');

    // VAE node
    this.vaeModel = page.locator('#vaeModel');
    this.vaeDevice = page.locator('#vaeDevice');
    this.vaeEncodeTiled = page.locator('#vaeEncodeTiled');
    this.vaeEncodeTileSize = page.locator('#vaeEncodeTileSize');
    this.vaeEncodeTileOverlap = page.locator('#vaeEncodeTileOverlap');
    this.vaeDecodeTiled = page.locator('#vaeDecodeTiled');
    this.vaeDecodeTileSize = page.locator('#vaeDecodeTileSize');
    this.vaeDecodeTileOverlap = page.locator('#vaeDecodeTileOverlap');
    this.vaeTileDebug = page.locator('#vaeTileDebug');
    this.vaeOffloadDevice = page.locator('#vaeOffloadDevice');
    this.vaeCacheModel = page.locator('#vaeCacheModel');

    // Upscaler node
    this.upscalerSeed = page.locator('#upscalerSeed');
    this.upscalerResolution = page.locator('#upscalerResolution');
    this.upscalerBatchSize = page.locator('#upscalerBatchSize');
    this.upscalerColorCorrection = page.locator('#upscalerColorCorrection');
    this.upscalerMaxResolution = page.locator('#upscalerMaxResolution');
    this.upscalerUniformBatch = page.locator('#upscalerUniformBatch');
    this.upscalerTemporalOverlap = page.locator('#upscalerTemporalOverlap');
    this.upscalerPrependFrames = page.locator('#upscalerPrependFrames');
    this.upscalerInputNoiseScale = page.locator('#upscalerInputNoiseScale');
    this.upscalerLatentNoiseScale = page.locator('#upscalerLatentNoiseScale');
    this.upscalerOffloadDevice = page.locator('#upscalerOffloadDevice');
    this.upscalerDebug = page.locator('#upscalerDebug');

    // Output node
    this.outputFormat = page.locator('#outputFormat');
    this.outputCrf = page.locator('#outputCrf');
  }

  async goto(): Promise<void> {
    await this.navigate(this.path);
  }

  async uploadVideo(filePath: string): Promise<void> {
    // setInputFiles works on hidden file inputs directly
    await this.videoFileInput.setInputFiles(filePath);
    // Wait for file info to appear
    await this.videoFileInfo.waitFor({ state: 'visible' });
  }

  async switchInputMode(mode: 'file' | 'folder'): Promise<void> {
    // The data-mode attribute is on the button element itself, not a child.
    // Use a direct attribute selector rather than filter({ has: ... }).
    const tab = this.page.locator(`.sv-input-mode-tab[data-mode="${mode}"]`);
    await tab.click();
    // Wait for the corresponding panel to become active
    const targetPanel = mode === 'file' ? this.panelFile : this.panelFolder;
    await targetPanel.waitFor({ state: 'visible' });
  }

  async setFolderPath(path: string): Promise<void> {
    // Ensure we are in folder mode so the folder path input is visible
    const isFolderPanelVisible = await this.panelFolder.isVisible();
    if (!isFolderPanelVisible) {
      await this.switchInputMode('folder');
    }
    await this.folderPath.fill(path);
  }

  async clickBrowseFolder(): Promise<void> {
    // Ensure we are in folder mode so the browse button is visible
    const isFolderPanelVisible = await this.panelFolder.isVisible();
    if (!isFolderPanelVisible) {
      await this.switchInputMode('folder');
    }
    await this.btnPickVideoFolder.click();
  }

  async setShrinkEnabled(enabled: boolean): Promise<void> {
    // When the shrink node is disabled, the node-body has pointer-events: none,
    // so the checkbox cannot be clicked normally. Use force or evaluate to toggle.
    const isChecked = await this.shrinkEnabled.isChecked();
    if (isChecked !== enabled) {
      await this.shrinkEnabled.click({ force: true });
      // Wait for the node-disabled class to be toggled by the change handler
      if (enabled) {
        await this.shrinkNode.evaluate(el => !el.classList.contains('node-disabled'));
      }
    }
  }

  async setShrinkAlgorithm(algo: string): Promise<void> {
    await this.shrinkAlgorithm.selectOption(algo);
  }

  async setShrinkRatio(ratio: number): Promise<void> {
    await this.shrinkRatio.fill(String(ratio));
  }

  async setDitModel(model: string): Promise<void> {
    await this.ditModel.selectOption(model);
  }

  async setDitDevice(device: string): Promise<void> {
    await this.ditDevice.selectOption(device);
  }

  async setBlocksToSwap(value: number): Promise<void> {
    await this.ditBlocksToSwap.fill(String(value));
  }

  async setSeed(value: number): Promise<void> {
    await this.upscalerSeed.fill(String(value));
  }

  async setResolution(value: number): Promise<void> {
    await this.upscalerResolution.fill(String(value));
  }

  async startRestore(): Promise<void> {
    await this.btnStartRestore.click();
  }

  async waitForProgress(timeout = 60000): Promise<void> {
    await this.progressCard.waitFor({ state: 'visible', timeout });
  }

  async waitForResult(timeout = 300000): Promise<void> {
    await this.resultCard.waitFor({ state: 'visible', timeout });
  }

  async waitForBatchComplete(timeout = 600000): Promise<void> {
    await this.batchProgressCard.waitFor({ state: 'visible', timeout });
    // Wait for the batch status badge to show completed
    const badge = this.page.locator('#batchStatusBadge.sv-badge-completed');
    await badge.waitFor({ state: 'visible', timeout });
  }

  async getProgressPercent(): Promise<number> {
    const text = await this.progressPct.textContent();
    return parseFloat(text?.replace('%', '') || '0');
  }

  async getResultDownloadUrl(): Promise<string> {
    const href = await this.btnDownload.getAttribute('href');
    return href || '';
  }

  async clickRetryFailed(): Promise<void> {
    await this.btnRetryFailed.click();
  }

  async resetRestore(): Promise<void> {
    await this.page.evaluate(() => {
      if (typeof (window as any).SeedVR2?.resetVideoRestore === 'function') {
        (window as any).SeedVR2.resetVideoRestore();
      }
    });
  }

  async toggleAllNodes(expand: boolean): Promise<void> {
    await this.page.evaluate((shouldExpand) => {
      if (typeof (window as any).toggleAllNodes === 'function') {
        (window as any).toggleAllNodes(shouldExpand);
      }
    }, expand);
  }

  async randomizeSeed(): Promise<void> {
    await this.page.locator('#btnRandomizeSeed').click();
  }
}

import { Page, Locator } from '@playwright/test';
import { BasePage } from './base.page';

export class ImageRestorePage extends BasePage {
  // Upload selectors
  readonly imageUploadZone: Locator;
  readonly imageFileInput: Locator;
  readonly imageFileInfo: Locator;
  readonly uploadStatus: Locator;
  readonly imagePreview: Locator;

  // Folder selectors
  readonly folderDetails: Locator;
  readonly folderPath: Locator;
  readonly btnPickFolder: Locator;
  readonly btnScanFolder: Locator;
  readonly scanResult: Locator;
  readonly scanResultText: Locator;

  // Form & action selectors
  readonly imageRestoreForm: Locator;
  readonly btnStartRestore: Locator;

  // Processing selectors
  readonly processingCard: Locator;

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

  // Compare selectors
  readonly compareCard: Locator;
  readonly compareContainer: Locator;
  readonly compareSlider: Locator;
  readonly compareBefore: Locator;
  readonly compareAfterImg: Locator;
  readonly btnDownload: Locator;

  // Parameter selectors - Shrink
  readonly shrinkAlgorithm: Locator;
  readonly shrinkScale: Locator;
  readonly shrinkEnabled: Locator;

  // Parameter selectors - DiT
  readonly ditModel: Locator;
  readonly ditDevice: Locator;
  readonly blocksToSwap: Locator;
  readonly swapIoComponents: Locator;
  readonly ditOffloadDevice: Locator;
  readonly ditCacheModel: Locator;
  readonly attentionMode: Locator;

  // Parameter selectors - VAE
  readonly vaeModel: Locator;
  readonly vaeDevice: Locator;
  readonly encodeTiled: Locator;
  readonly encodeTileSize: Locator;
  readonly encodeTileOverlap: Locator;
  readonly decodeTiled: Locator;
  readonly decodeTileSize: Locator;
  readonly decodeTileOverlap: Locator;
  readonly tileDebug: Locator;
  readonly vaeOffloadDevice: Locator;
  readonly vaeCacheModel: Locator;

  // Parameter selectors - Upscaler
  readonly seed: Locator;
  readonly resolution: Locator;
  readonly batchSize: Locator;
  readonly colorCorrection: Locator;
  readonly maxResolution: Locator;
  readonly uniformBatchSize: Locator;
  readonly temporalOverlap: Locator;
  readonly prependFrames: Locator;
  readonly inputNoiseScale: Locator;
  readonly latentNoiseScale: Locator;
  readonly offloadDevice: Locator;
  readonly enableDebug: Locator;

  readonly path = '/restore';

  constructor(page: Page) {
    super(page);

    // Upload
    this.imageUploadZone = page.locator('#imageUploadZone');
    this.imageFileInput = page.locator('#imageFileInput');
    this.imageFileInfo = page.locator('#imageFileInfo');
    this.uploadStatus = page.locator('#uploadStatus');
    this.imagePreview = page.locator('#imagePreview');

    // Folder - the <details> element wrapping the folder section
    this.folderDetails = page.locator('details:has(#folder_path)');
    this.folderPath = page.locator('#folder_path');
    this.btnPickFolder = page.locator('#btnPickFolder');
    this.btnScanFolder = page.locator('#btnScanFolder');
    this.scanResult = page.locator('#scanResult');
    this.scanResultText = page.locator('#scanResultText');

    // Form & actions
    this.imageRestoreForm = page.locator('#imageRestoreForm');
    this.btnStartRestore = page.locator('#btnStartRestore');

    // Processing
    this.processingCard = page.locator('#processingCard');

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

    // Compare
    this.compareCard = page.locator('#compareCard');
    this.compareContainer = page.locator('#compareContainer');
    this.compareSlider = page.locator('#compareSlider');
    this.compareBefore = page.locator('#compareBefore');
    this.compareAfterImg = page.locator('#compareAfterImg');
    this.btnDownload = page.locator('#btnDownload');

    // Shrink parameters
    this.shrinkAlgorithm = page.locator('#shrink_algorithm');
    this.shrinkScale = page.locator('#shrink_scale');
    this.shrinkEnabled = page.locator('#shrink_enabled');

    // DiT parameters
    this.ditModel = page.locator('#dit_model');
    this.ditDevice = page.locator('#dit_device');
    this.blocksToSwap = page.locator('#blocks_to_swap');
    this.swapIoComponents = page.locator('#swap_io_components');
    this.ditOffloadDevice = page.locator('#dit_offload_device');
    this.ditCacheModel = page.locator('#dit_cache_model');
    this.attentionMode = page.locator('#attention_mode');

    // VAE parameters
    this.vaeModel = page.locator('#vae_model');
    this.vaeDevice = page.locator('#vae_device');
    this.encodeTiled = page.locator('#encode_tiled');
    this.encodeTileSize = page.locator('#encode_tile_size');
    this.encodeTileOverlap = page.locator('#encode_tile_overlap');
    this.decodeTiled = page.locator('#decode_tiled');
    this.decodeTileSize = page.locator('#decode_tile_size');
    this.decodeTileOverlap = page.locator('#decode_tile_overlap');
    this.tileDebug = page.locator('#tile_debug');
    this.vaeOffloadDevice = page.locator('#vae_offload_device');
    this.vaeCacheModel = page.locator('#vae_cache_model');

    // Upscaler parameters
    this.seed = page.locator('#seed');
    this.resolution = page.locator('#resolution');
    this.batchSize = page.locator('#batch_size');
    this.colorCorrection = page.locator('#color_correction');
    this.maxResolution = page.locator('#max_resolution');
    this.uniformBatchSize = page.locator('#uniform_batch_size');
    this.temporalOverlap = page.locator('#temporal_overlap');
    this.prependFrames = page.locator('#prepend_frames');
    this.inputNoiseScale = page.locator('#input_noise_scale');
    this.latentNoiseScale = page.locator('#latent_noise_scale');
    this.offloadDevice = page.locator('#offload_device');
    this.enableDebug = page.locator('#enable_debug');
  }

  async goto(): Promise<void> {
    await this.navigate(this.path);
  }

  async uploadImage(filePath: string): Promise<void> {
    await this.imageFileInput.setInputFiles(filePath);
    // Wait for file info to appear
    await this.imageFileInfo.waitFor({ state: 'visible' });
  }

  async setFolderPath(path: string): Promise<void> {
    // The folder_path input is inside a <details> element that may be collapsed.
    // Use JavaScript to expand because summary may be hidden by CSS in certain viewports
    await this.page.evaluate(() => {
      const details = document.querySelector('details:has(#folder_path)');
      if (details && !details.hasAttribute('open')) {
        details.setAttribute('open', '');
      }
    });
    await this.folderPath.waitFor({ state: 'visible' });
    await this.folderPath.fill(path);
  }

  async clickBrowseFolder(): Promise<void> {
    await this.btnPickFolder.click();
  }

  async clickScanFolder(): Promise<void> {
    // Ensure the folder details section is expanded before clicking scan
    // Use JavaScript to expand because summary may be hidden by CSS in certain viewports
    await this.page.evaluate(() => {
      const details = document.querySelector('details:has(#folder_path)');
      if (details && !details.hasAttribute('open')) {
        details.setAttribute('open', '');
      }
    });
    await this.btnScanFolder.waitFor({ state: 'visible' });
    await this.btnScanFolder.click();
    // Wait for scan result to appear
    await this.scanResult.waitFor({ state: 'visible', timeout: 15000 });
  }

  async getScanResult(): Promise<string> {
    const text = await this.scanResultText.textContent();
    return text?.trim() || '';
  }

  async setDitModel(model: string): Promise<void> {
    await this.ditModel.selectOption(model);
  }

  async setDitDevice(device: string): Promise<void> {
    await this.ditDevice.selectOption(device);
  }

  async setSeed(value: number): Promise<void> {
    await this.seed.fill(String(value));
  }

  async setResolution(value: number): Promise<void> {
    await this.resolution.fill(String(value));
  }

  async startRestore(): Promise<void> {
    await this.btnStartRestore.click();
  }

  async waitForProcessingComplete(timeout = 300000): Promise<void> {
    await this.processingCard.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {});
    // Wait for processing card to disappear (processing done)
    await this.processingCard.waitFor({ state: 'hidden', timeout });
  }

  async waitForResult(timeout = 300000): Promise<void> {
    await this.compareCard.waitFor({ state: 'visible', timeout });
  }

  async waitForBatchComplete(timeout = 600000): Promise<void> {
    await this.batchProgressCard.waitFor({ state: 'visible', timeout: 10000 });
    // Wait for the batch status badge to show completed
    const badge = this.page.locator('#batchStatusBadge.sv-badge-completed');
    await badge.waitFor({ state: 'visible', timeout });
  }

  async clickRetryFailed(): Promise<void> {
    await this.btnRetryFailed.click();
  }

  async resetRestore(): Promise<void> {
    await this.page.evaluate(() => {
      if (typeof (window as any).SeedVR2?.resetImageRestore === 'function') {
        (window as any).SeedVR2.resetImageRestore();
      }
    });
  }
}

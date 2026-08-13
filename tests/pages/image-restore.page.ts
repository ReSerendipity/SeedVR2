/**
 * Image Restore page object for the SeedVR2 WebUI.
 *
 * NOTE: The product has been reworked into a single unified restore
 * workbench (restore.html). Image restore lives on the "single file"
 * mode tab of `/restore`; this page object targets the current template
 * ids (camelCase), replacing the legacy snake_case selectors.
 */
import type { Locator, Page } from '@playwright/test';
import { BasePage } from './base.page';

export class ImageRestorePage extends BasePage {
  readonly path = '/restore';

  // Upload zone (unified restore upload)
  readonly uploadZone: Locator;
  readonly fileInput: Locator;
  readonly fileInfo: Locator;
  readonly fileDuration: Locator;
  readonly btnChangeFile: Locator;

  // Preview
  readonly previewContainer: Locator;
  readonly imagePreview: Locator;
  readonly btnClearImage: Locator;

  // Progress
  readonly progressCard: Locator;
  readonly taskStatus: Locator;
  readonly btnCancelRestore: Locator;
  readonly progressBar: Locator;
  readonly progressText: Locator;
  readonly progressPct: Locator;
  readonly progressFrames: Locator;
  readonly progressEta: Locator;

  // Result
  readonly resultCard: Locator;
  readonly resultStatus: Locator;
  readonly btnDownload: Locator;
  readonly btnRestoreAgain: Locator;

  // Compare
  readonly compareCard: Locator;
  readonly btnCompareHorizontal: Locator;
  readonly btnCompareVertical: Locator;
  readonly compareSlider: Locator;
  readonly compareContainer: Locator;
  readonly compareBefore: Locator;
  readonly compareAfter: Locator;

  // Batch (folder mode)
  readonly modeTabs: Locator;
  readonly batchToolbar: Locator;
  readonly folderPath: Locator;
  readonly btnBrowseFolder: Locator;
  readonly btnScanFolder: Locator;
  readonly btnStartBatch: Locator;
  readonly folderScanResults: Locator;
  readonly batchProgressCard: Locator;
  readonly batchProgressBar: Locator;
  readonly batchProgressText: Locator;
  readonly batchPercentText: Locator;
  readonly batchCompleted: Locator;
  readonly batchFailed: Locator;
  readonly batchCurrentFile: Locator;
  readonly batchEta: Locator;
  readonly btnCancelBatch: Locator;

  // Parameters
  readonly paramsSidebar: Locator;
  readonly btnToggleParams: Locator;
  readonly ditModel: Locator;
  readonly resolution: Locator;
  readonly doubleResToggle: Locator;
  readonly vaeModel: Locator;
  readonly advToggle: Locator;
  readonly advParams: Locator;
  readonly maxResolution: Locator;
  readonly colorCorrection: Locator;
  readonly blocksToSwap: Locator;
  readonly batchSize: Locator;
  readonly encodeTileSize: Locator;
  readonly encodeTileOverlap: Locator;
  readonly decodeTileSize: Locator;
  readonly decodeTileOverlap: Locator;

  // Actions
  readonly btnStartRestore: Locator;
  readonly btnResetRestore: Locator;

  // Onboarding / help / confirm dialog
  readonly onboardingModal: Locator;
  readonly onboardingClose: Locator;
  readonly confirmAction: Locator;

  constructor(page: Page) {
    super(page);

    this.uploadZone = page.locator('#restoreUploadZone');
    this.fileInput = page.locator('#restoreFileInput');
    this.fileInfo = page.locator('#restoreFileInfo');
    this.fileDuration = page.locator('#fileDuration');
    this.btnChangeFile = page.locator('#btnChangeFile');

    this.previewContainer = page.locator('#imagePreviewContainer');
    this.imagePreview = page.locator('#imagePreview');
    this.btnClearImage = page.locator('#btnClearImage');

    this.progressCard = page.locator('#progressCard');
    this.taskStatus = page.locator('#taskStatus');
    this.btnCancelRestore = page.locator('#btnCancelRestore');
    this.progressBar = page.locator('#progressBar');
    this.progressText = page.locator('#progressText');
    this.progressPct = page.locator('#progressPct');
    this.progressFrames = page.locator('#progressFrames');
    this.progressEta = page.locator('#progressEta');

    this.resultCard = page.locator('#resultCard');
    this.resultStatus = page.locator('#resultStatus');
    this.btnDownload = page.locator('#btnDownload');
    this.btnRestoreAgain = page.locator('#btnRestoreAgain');

    this.compareCard = page.locator('#compareCard');
    this.btnCompareHorizontal = page.locator('#btnCompareHorizontal');
    this.btnCompareVertical = page.locator('#btnCompareVertical');
    this.compareSlider = page.locator('#compareSlider');
    this.compareContainer = page.locator('#compareContainer');
    this.compareBefore = page.locator('#compareBefore');
    this.compareAfter = page.locator('#compareAfter');

    this.modeTabs = page.locator('.sv-mode-tab');
    this.batchToolbar = page.locator('#batchToolbar');
    this.folderPath = page.locator('#folderPath');
    this.btnBrowseFolder = page.locator('#btnBrowseFolder');
    this.btnScanFolder = page.locator('#btnScanFolder');
    this.btnStartBatch = page.locator('#btnStartBatch');
    this.folderScanResults = page.locator('#folderScanResults');
    this.batchProgressCard = page.locator('#batchProgressCard');
    this.batchProgressBar = page.locator('#batchProgressBar');
    this.batchProgressText = page.locator('#batchProgressText');
    this.batchPercentText = page.locator('#batchPercentText');
    this.batchCompleted = page.locator('#batchCompleted');
    this.batchFailed = page.locator('#batchFailed');
    this.batchCurrentFile = page.locator('#batchCurrentFile');
    this.batchEta = page.locator('#batchEta');
    this.btnCancelBatch = page.locator('#btnCancelBatch');

    this.paramsSidebar = page.locator('#paramsSidebar');
    this.btnToggleParams = page.locator('#btnToggleParams');
    this.ditModel = page.locator('#ditModel');
    this.resolution = page.locator('#resolution');
    this.doubleResToggle = page.locator('#doubleResToggle');
    this.vaeModel = page.locator('#vaeModel');
    this.advToggle = page.locator('#advToggle');
    this.advParams = page.locator('#advParams');
    this.maxResolution = page.locator('#maxResolution');
    this.colorCorrection = page.locator('#colorCorrection');
    this.blocksToSwap = page.locator('#blocksToSwap');
    this.batchSize = page.locator('#batchSize');
    this.encodeTileSize = page.locator('#encodeTileSize');
    this.encodeTileOverlap = page.locator('#encodeTileOverlap');
    this.decodeTileSize = page.locator('#decodeTileSize');
    this.decodeTileOverlap = page.locator('#decodeTileOverlap');

    this.btnStartRestore = page.locator('#btnStartRestore');
    this.btnResetRestore = page.locator('#btnResetRestore');

    this.onboardingModal = page.locator('#onboardingModal');
    this.onboardingClose = page.locator('#onboardingClose');
    this.confirmAction = page.locator('#confirmAction');
  }

  async goto(): Promise<void> {
    await this.navigate(this.path);
  }

  /** Upload an image file through the unified restore file input. */
  async uploadImage(filePath: string): Promise<void> {
    await this.fileInput.setInputFiles(filePath);
  }

  /** Switch to the batch (folder) mode tab. */
  async switchToBatchMode(): Promise<void> {
    await this.modeTabs.filter({ hasText: '批量修复' }).click();
  }

  /** Switch to the single-file mode tab. */
  async switchToSingleMode(): Promise<void> {
    await this.modeTabs.filter({ hasText: '单文件修复' }).click();
  }

  /** Expand the advanced parameter section. */
  async expandAdvanced(): Promise<void> {
    await this.advToggle.click();
    await this.advParams.waitFor({ state: 'visible' });
  }
}

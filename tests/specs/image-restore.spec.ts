/**
 * Image restore flow test specification for SeedVR2 WebUI.
 *
 * Re-written for the unified restore workbench (restore.html):
 * - single-file mode: upload image -> configure params -> start -> view result
 * - batch mode: set folder path -> scan -> start batch -> poll progress
 * - negative: model not loaded (503), no file/folder selected
 * - parameter configuration on the current template ids
 * - image preview for jpeg/png/webp uploads
 */
import { test, expect } from '@playwright/test';
import { ImageRestorePage } from '../pages/image-restore.page';
import {
  setupAllMocks,
  mockImageRestoreSuccess,
  mockImageResultSuccess,
  mockScanFolderSuccess,
  mockBatchImageRestoreSuccess,
  mockBatchImageProgressSuccess,
  mock503ModelNotLoaded,
  mockBrowseDirSuccess,
} from '../fixtures/api-mocks';
import { IMAGE_FILES } from '../fixtures/test-data';
import { waitForToast, waitForErrorToast } from '../utils/wait-helpers';

test.describe('Image Restore Flow', () => {
  let imagePage: ImageRestorePage;

  test.beforeEach(async ({ page }) => {
    await setupAllMocks(page);
    imagePage = new ImageRestorePage(page);
    // Dismiss the first-run onboarding modal: a fresh Playwright context has
    // empty localStorage (sv_onboarding_seen_v2), so the modal would show
    // on every test and intercept all pointer events.
    await imagePage.goto();
    // Dismiss the first-run onboarding modal: a fresh Playwright context has
    // empty localStorage (sv_onboarding_seen_v2), so the modal would show
    // on every test and intercept all pointer events.
    await page.evaluate(() => {
      localStorage.setItem('sv_onboarding_seen_v2', '1');
      const modal = document.getElementById('onboardingModal');
      if (modal) {
        modal.classList.remove('show');
        modal.style.display = 'none';
      }
    });
  });

  // ============================================================
  // Positive flow: full image restore pipeline
  // ============================================================

  test.describe('Positive flow (with API mock)', () => {
    test('complete image restore: upload -> configure -> start -> view result', async ({ page }) => {
      // Override the default mock to return completed status with output_path
      await page.route('**/api/restore', async (route) => {
        if (route.request().method() === 'POST') {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              task_id: 'test-task-001',
              status: 'completed',
              output_path: 'outputs/image/test-img-001/restored.png',
              message: 'Image restore completed',
            }),
          });
        } else {
          await route.continue();
        }
      });

      // Step 1: Upload an image file
      await imagePage.uploadImage(IMAGE_FILES.jpeg);
      await expect(imagePage.fileInfo).toHaveCSS('display', 'flex');
      // 上传后画布切到预览区，拖拽占位（含 fileInfo 的父容器）被隐藏属产品行为

      // Step 2: Configure parameters
      // 两倍模式默认勾选会禁用分辨率输入，先关闭
      await page.evaluate(() => {
      const toggle = document.getElementById('doubleResToggle') as HTMLInputElement;
      if (toggle && toggle.checked) {
        toggle.checked = false;
        toggle.dispatchEvent(new Event('change', { bubbles: true }));
      }
    });
      await imagePage.resolution.fill('1920');

      // Step 3: Start the restore process
      await imagePage.btnStartRestore.click();

      // Step 4: Wait for the result (compare card with before/after)
      await expect(imagePage.compareCard).toBeVisible({ timeout: 15000 });

      // Step 5: Verify download button is available
      await expect(imagePage.btnDownload).toBeVisible();
    });
  });

  // ============================================================
  // Batch from folder
  // ============================================================

  test.describe('Batch from folder', () => {
    test('batch image restore: set folder -> scan -> start -> batch progress appears', async ({ page }) => {
      await mockBatchImageRestoreSuccess(page);
      await mockBatchImageProgressSuccess(page);
      await mockScanFolderSuccess(page);

      await imagePage.switchToBatchMode();
      await expect(imagePage.batchToolbar).toBeVisible();

      // Step 1: Set folder path
      await imagePage.folderPath.fill('C:\\Users\\test\\Images');
      await mockBrowseDirSuccess(page);

      // Step 2: Scan the folder and verify results
      await imagePage.btnScanFolder.click();
      await expect(imagePage.folderScanResults).toBeVisible();
      const scanText = await imagePage.folderScanResults.textContent();
      expect(scanText!.length).toBeGreaterThan(0);

      // Step 3: Start batch restore (confirm dialog appears first)
      await imagePage.btnStartBatch.click();
      await imagePage.confirmAction.click();

      // Step 4: Verify batch progress card appears
      await expect(imagePage.batchProgressCard).toBeVisible();
      await expect(imagePage.batchProgressBar).toBeVisible();
      await expect(imagePage.batchPercentText).toBeVisible();
    });
  });

  // ============================================================
  // Folder scan
  // ============================================================

  test.describe('Folder scan', () => {
    test('entering folder path and clicking scan shows scan result', async ({ page }) => {
      await mockScanFolderSuccess(page);

      await imagePage.switchToBatchMode();
      await imagePage.folderPath.fill('C:\\Users\\test\\Images');
      await imagePage.btnScanFolder.click();

      const resultText = await imagePage.folderScanResults.textContent();
      expect(resultText!.length).toBeGreaterThan(0);
    });

    test('scan result shows the number of images found', async ({ page }) => {
      await mockScanFolderSuccess(page);

      await imagePage.switchToBatchMode();
      await imagePage.folderPath.fill('C:\\Users\\test\\Images');
      await imagePage.btnScanFolder.click();

      // Use expect auto-retry: the scan is async and shows a "Scanning..." placeholder first
      await expect(imagePage.folderScanResults).toContainText(/\d+/, { timeout: 10000 });
    });
  });

  // ============================================================
  // Negative: Model not loaded (503)
  // ============================================================

  test.describe('Negative: Model not loaded (503)', () => {
    test('starting restore when model is not loaded shows error toast', async ({ page }) => {
      await mock503ModelNotLoaded(page, '**/api/restore**');

      await imagePage.uploadImage(IMAGE_FILES.jpeg);
      await imagePage.btnStartRestore.click();

      const errorToast = await waitForErrorToast(page, undefined, 10000).catch(() =>
        waitForToast(page, undefined, 5000).catch(() => null),
      );
      expect(errorToast).not.toBeNull();
    });
  });

  // ============================================================
  // Negative: No file or folder selected
  // ============================================================

  test.describe('Negative: No file or folder selected', () => {
    test('clicking start without selecting a file or folder shows warning', async ({ page }) => {
      const isButtonDisabled = await imagePage.btnStartRestore.isDisabled().catch(() => false);

      if (isButtonDisabled) {
        expect(isButtonDisabled).toBe(true);
      } else {
        await imagePage.btnStartRestore.click();
        const warningToast = await waitForToast(page, undefined, 5000).catch(() => null);
        expect(warningToast).not.toBeNull();
      }
    });
  });

  // ============================================================
  // Parameter configuration
  // ============================================================

  test.describe('Parameter configuration', () => {
    test('changing DiT model updates the select value', async ({ page }) => {
      await imagePage.ditModel.selectOption('3b_fp8');
      await expect(imagePage.ditModel).toHaveValue('3b_fp8');
    });

    test('changing VAE model updates the select value', async ({ page }) => {
      await imagePage.expandAdvanced();
      await imagePage.vaeModel.selectOption('ema_vae_fp8');
      await expect(imagePage.vaeModel).toHaveValue('ema_vae_fp8');
    });

    test('changing VAE decode tile size updates the input value', async ({ page }) => {
      await imagePage.expandAdvanced();
      // 两倍模式默认勾选会禁用 tile 参数，先关闭
      await page.evaluate(() => {
        const toggle = document.getElementById('doubleResToggle') as HTMLInputElement;
        if (toggle && toggle.checked) {
          toggle.checked = false;
          toggle.dispatchEvent(new Event('change', { bubbles: true }));
        }
      });
      await imagePage.decodeTileSize.fill('256');
      await expect(imagePage.decodeTileSize).toHaveValue('256');
    });

    test('changing VAE encode tile overlap updates the input value', async ({ page }) => {
      await imagePage.expandAdvanced();
      // 两倍模式默认勾选会禁用 tile 参数，先关闭
      await page.evaluate(() => {
        const toggle = document.getElementById('doubleResToggle') as HTMLInputElement;
        if (toggle && toggle.checked) {
          toggle.checked = false;
          toggle.dispatchEvent(new Event('change', { bubbles: true }));
        }
      });
      await imagePage.encodeTileOverlap.fill('32');
      await expect(imagePage.encodeTileOverlap).toHaveValue('32');
    });

    test('changing upscale resolution updates the input value', async ({ page }) => {
      // 两倍模式默认勾选会禁用分辨率输入，先关闭
      await page.evaluate(() => {
      const toggle = document.getElementById('doubleResToggle') as HTMLInputElement;
      if (toggle && toggle.checked) {
        toggle.checked = false;
        toggle.dispatchEvent(new Event('change', { bubbles: true }));
      }
    });
      await imagePage.resolution.fill('3840');
      await expect(imagePage.resolution).toHaveValue('3840');
    });

    test('changing max resolution updates the input value', async ({ page }) => {
      await imagePage.expandAdvanced();
      await imagePage.maxResolution.fill('2048');
      await expect(imagePage.maxResolution).toHaveValue('2048');
    });

    test('changing blocks to swap updates the input value', async ({ page }) => {
      await imagePage.expandAdvanced();
      await imagePage.blocksToSwap.fill('16');
      await expect(imagePage.blocksToSwap).toHaveValue('16');
    });

    test('changing batch size updates the input value', async ({ page }) => {
      await imagePage.expandAdvanced();
      await imagePage.batchSize.fill('4');
      await expect(imagePage.batchSize).toHaveValue('4');
    });

    test('changing color correction select updates the value', async ({ page }) => {
      await imagePage.expandAdvanced();
      const initialValue = await imagePage.colorCorrection.inputValue();
      const newValue = initialValue === 'lab' ? 'none' : 'lab';
      await imagePage.colorCorrection.selectOption(newValue);
      await expect(imagePage.colorCorrection).toHaveValue(newValue);
    });

    test('advanced toggle expands and collapses the advanced params', async ({ page }) => {
      await expect(imagePage.advParams).toBeHidden();
      await imagePage.advToggle.click();
      await expect(imagePage.advParams).toBeVisible();
      await imagePage.advToggle.click();
      await expect(imagePage.advParams).toBeHidden();
    });
  });

  // ============================================================
  // Image preview
  // ============================================================

  test.describe('Image preview', () => {
    test('uploading an image shows a preview', async ({ page }) => {
      await imagePage.uploadImage(IMAGE_FILES.jpeg);
      await expect(imagePage.imagePreview).toBeVisible();
    });

    test('uploading a PNG image shows a preview', async ({ page }) => {
      await imagePage.uploadImage(IMAGE_FILES.png);
      await expect(imagePage.imagePreview).toBeVisible();
    });

    test('uploading a WebP image shows a preview', async ({ page }) => {
      await imagePage.uploadImage(IMAGE_FILES.webp);
      await expect(imagePage.imagePreview).toBeVisible();
    });

    test('file info displays the uploaded filename', async ({ page }) => {
      await imagePage.uploadImage(IMAGE_FILES.jpeg);
      const fileInfoText = await imagePage.fileInfo.textContent();
      expect(fileInfoText).toBeTruthy();
      expect(fileInfoText!.length).toBeGreaterThan(0);
    });

    test('clear image button hides the preview', async ({ page }) => {
      await imagePage.uploadImage(IMAGE_FILES.jpeg);
      await expect(imagePage.imagePreview).toBeVisible();
      await imagePage.btnClearImage.click();
      await expect(imagePage.imagePreview).toBeHidden();
    });
  });
});

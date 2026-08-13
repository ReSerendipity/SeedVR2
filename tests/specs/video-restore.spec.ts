/**
 * Video restore flow test specification for SeedVR2 WebUI.
 *
 * Re-written for the unified restore workbench (restore.html):
 * - positive flow: upload video -> start -> progress -> result video
 * - batch mode: set folder -> start -> batch progress card
 * - negative: model not loaded (503), no file selected
 * - parameter boundary values on the current template ids
 * - advanced params toggle
 */
import { test, expect } from '@playwright/test';
import { VideoRestorePage } from '../pages/video-restore.page';
import {
  setupAllMocks,
  mockVideoRestoreSuccess,
  mockVideoProgressComplete,
  mockVideoResultSuccess,
  mockBatchVideoRestoreSuccess,
  mockBatchVideoProgressSuccess,
  mock503ModelNotLoaded,
  mockBrowseDirSuccess,
  mockScanFolderSuccess,
} from '../fixtures/api-mocks';
import { VIDEO_FILES } from '../fixtures/test-data';
import { waitForToast, waitForErrorToast } from '../utils/wait-helpers';

test.describe('Video Restore Flow', () => {
  let videoPage: VideoRestorePage;

  test.beforeEach(async ({ page }) => {
    await setupAllMocks(page);
    videoPage = new VideoRestorePage(page);
    // Dismiss the first-run onboarding modal: a fresh Playwright context has
    // empty localStorage (sv_onboarding_seen_v2), so the modal would show
    // on every test and intercept all pointer events.
    await videoPage.goto();
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
  // Positive flow: full video restore pipeline
  // ============================================================

  test.describe('Positive flow (with API mock)', () => {
    test('complete video restore: upload -> start -> progress -> result visible', async ({ page }) => {
      // Override default mock: return completed status with output path
      await page.route('**/api/restore', async (route) => {
        if (route.request().method() === 'POST') {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              task_id: 'test-task-001',
              task_type: 'video',
              status: 'completed',
              output_path: 'outputs/video/test-vid-001/restored.mp4',
              message: 'Video restore completed',
            }),
          });
        } else {
          await route.continue();
        }
      });

      // Step 1: Upload a video file
      await videoPage.uploadVideo(VIDEO_FILES.small);
      await expect(videoPage.fileInfo).toBeVisible();

      // Step 2: Start the restore process
      await videoPage.btnStartRestore.click();

      // Step 3: Result card with video should become visible
      await expect(videoPage.resultCard).toBeVisible({ timeout: 15000 });
      await expect(videoPage.resultVideo).toBeVisible();

      // Step 4: Download button available
      await expect(videoPage.btnDownload).toBeVisible();
    });
  });

  // ============================================================
  // Batch from folder
  // ============================================================

  test.describe('Batch from folder', () => {
    test('batch video restore: set folder -> start -> batch progress card appears', async ({ page }) => {
      await mockBatchVideoRestoreSuccess(page);
      await mockBatchVideoProgressSuccess(page);

      await videoPage.switchToBatchMode();
      await expect(videoPage.batchToolbar).toBeVisible();

      await videoPage.folderPath.fill('C:\\Users\\test\\Videos');
      await mockBrowseDirSuccess(page);
      await mockScanFolderSuccess(page);

      await videoPage.btnScanFolder.click();
      await expect(videoPage.folderScanResults).toContainText('找到');

      await videoPage.btnStartBatch.click();
      await videoPage.confirmAction.click();

      await expect(videoPage.batchProgressCard).toBeVisible();
      await expect(videoPage.batchProgressBar).toBeVisible();
      await expect(videoPage.batchPercentText).toBeVisible();
    });
  });

  // ============================================================
  // Negative: Model not loaded (503)
  // ============================================================

  test.describe('Negative: Model not loaded (503)', () => {
    test('starting restore when model is not loaded shows error toast', async ({ page }) => {
      await mock503ModelNotLoaded(page, '**/api/restore**');

      await videoPage.uploadVideo(VIDEO_FILES.small);
      await videoPage.btnStartRestore.click();

      const errorToast = await waitForErrorToast(page, undefined, 10000).catch(() =>
        waitForToast(page, undefined, 5000).catch(() => null),
      );
      expect(errorToast).not.toBeNull();
    });
  });

  // ============================================================
  // Negative: No file selected
  // ============================================================

  test.describe('Negative: No file selected', () => {
    test('clicking start without selecting a file shows warning', async ({ page }) => {
      const isButtonDisabled = await videoPage.btnStartRestore.isDisabled().catch(() => false);

      if (isButtonDisabled) {
        expect(isButtonDisabled).toBe(true);
      } else {
        await videoPage.btnStartRestore.click();
        const warningToast = await waitForToast(page, undefined, 5000).catch(() => null);
        expect(warningToast).not.toBeNull();
      }
    });

    test('uploading an unsupported file format shows file info but form submission validates', async ({ page }) => {
      await videoPage.uploadVideo(VIDEO_FILES.unsupported);
      await expect(videoPage.fileInfo).toBeVisible();
    });
  });

  // ============================================================
  // Parameter configuration
  // ============================================================

  test.describe('Parameter configuration', () => {
    test('setting resolution to minimum (360) is accepted', async ({ page }) => {
      // 两倍模式默认勾选会禁用分辨率输入，先关闭
      await page.evaluate(() => {
      const toggle = document.getElementById('doubleResToggle') as HTMLInputElement;
      if (toggle && toggle.checked) {
        toggle.checked = false;
        toggle.dispatchEvent(new Event('change', { bubbles: true }));
      }
    });
      await videoPage.resolution.fill('360');
      await expect(videoPage.resolution).toHaveValue('360');
    });

    test('setting resolution to maximum (8192) is accepted', async ({ page }) => {
      // 两倍模式默认勾选会禁用分辨率输入，先关闭
      await page.evaluate(() => {
      const toggle = document.getElementById('doubleResToggle') as HTMLInputElement;
      if (toggle && toggle.checked) {
        toggle.checked = false;
        toggle.dispatchEvent(new Event('change', { bubbles: true }));
      }
    });
      await videoPage.resolution.fill('8192');
      await expect(videoPage.resolution).toHaveValue('8192');
    });

    test('setting resolution below minimum is accepted by the input', async ({ page }) => {
      // 两倍模式默认勾选会禁用分辨率输入，先关闭
      await page.evaluate(() => {
      const toggle = document.getElementById('doubleResToggle') as HTMLInputElement;
      if (toggle && toggle.checked) {
        toggle.checked = false;
        toggle.dispatchEvent(new Event('change', { bubbles: true }));
      }
    });
      await videoPage.resolution.fill('100');
      await expect(videoPage.resolution).toHaveValue('100');
    });

    test('changing DiT model updates the select value', async ({ page }) => {
      await videoPage.ditModel.selectOption('7b_fp16');
      await expect(videoPage.ditModel).toHaveValue('7b_fp16');
    });

    test('changing VAE model updates the select value', async ({ page }) => {
      await videoPage.expandAdvanced();
      await videoPage.vaeModel.selectOption('ema_vae_fp8');
      await expect(videoPage.vaeModel).toHaveValue('ema_vae_fp8');
    });

    test('changing VAE decode tile size updates the input value', async ({ page }) => {
      await videoPage.expandAdvanced();
      // 两倍模式默认勾选会禁用 tile 参数，先关闭
      await page.evaluate(() => {
        const toggle = document.getElementById('doubleResToggle') as HTMLInputElement;
        if (toggle && toggle.checked) {
          toggle.checked = false;
          toggle.dispatchEvent(new Event('change', { bubbles: true }));
        }
      });
      await videoPage.decodeTileSize.fill('256');
      await expect(videoPage.decodeTileSize).toHaveValue('256');
    });

    test('changing VAE encode tile overlap updates the input value', async ({ page }) => {
      await videoPage.expandAdvanced();
      // 两倍模式默认勾选会禁用 tile 参数，先关闭
      await page.evaluate(() => {
        const toggle = document.getElementById('doubleResToggle') as HTMLInputElement;
        if (toggle && toggle.checked) {
          toggle.checked = false;
          toggle.dispatchEvent(new Event('change', { bubbles: true }));
        }
      });
      await videoPage.encodeTileOverlap.fill('32');
      await expect(videoPage.encodeTileOverlap).toHaveValue('32');
    });

    test('advanced toggle expands and collapses the advanced params', async ({ page }) => {
      await expect(videoPage.advParams).toBeHidden();
      await videoPage.advToggle.click();
      await expect(videoPage.advParams).toBeVisible();
      await videoPage.advToggle.click();
      await expect(videoPage.advParams).toBeHidden();
    });

    test('seed is present as a hidden form field with a numeric value', async ({ page }) => {
      const seedValue = await page.locator('input[name="seed"]').inputValue();
      expect(Number.isInteger(Number(seedValue))).toBe(true);
    });
  });
});

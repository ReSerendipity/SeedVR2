/**
 * WCAG 2.1 AA contrast compliance test for SeedVR2 WebUI.
 *
 * Migrated from the standalone wcag-contrast-test.js script into a
 * proper Playwright spec so it runs in CI alongside other E2E tests.
 *
 * Tests color contrast ratios for all key UI elements across all pages
 * in both dark and light themes. Uses WCAG 2.1 AA thresholds:
 * - Normal text (< 18px or < 14px bold): contrast ratio >= 4.5:1
 * - Large text (>= 18px, or >= 14px bold): contrast ratio >= 3.0:1
 * - Headings (h1-h3): treated as large text, threshold 3.0:1
 */
import { test, expect, Page } from '@playwright/test';
import { setupAllMocks } from '@fixtures/api-mocks';

// ============================================================
// Configuration
// ============================================================

const BASE_URL_PATH = '/';

const PAGES = [
  { name: 'Home', path: '/' },
  { name: 'Video Restore', path: '/restore' },
  { name: 'Settings', path: '/settings' },
  { name: 'History', path: '/history' },
];

const THEMES = ['dark', 'light'] as const;

const ELEMENT_SELECTORS = [
  { selector: '.sv-page-header h1, .sv-hero h1', category: 'Page heading h1', type: 'heading' },
  { selector: '.sv-section-title, .sv-card-header h3', category: 'Section heading h2/h3', type: 'heading' },
  { selector: '.sv-quick-card h3, .sv-card-body p', category: 'Body text', type: 'normal' },
  { selector: '.sv-text-muted, .sv-form-hint', category: 'Muted/hint text', type: 'small' },
  { selector: '.sv-nav-link', category: 'Navigation link', type: 'normal' },
  { selector: '.sv-btn-primary', category: 'Button primary', type: 'normal' },
  { selector: '.sv-btn-secondary', category: 'Button secondary', type: 'normal' },
  { selector: '.sv-form-label', category: 'Form label', type: 'small' },
  { selector: '.sv-form-control', category: 'Form control', type: 'normal' },
  { selector: '.sv-badge', category: 'Badge', type: 'small' },
  { selector: '.sv-statusbar', category: 'Status bar', type: 'small' },
  { selector: '.sv-table thead th', category: 'Table header', type: 'small' },
  { selector: '.sv-table tbody td', category: 'Table content', type: 'normal' },
];

// ============================================================
// Color contrast calculation helpers
// ============================================================

function luminance(r: number, g: number, b: number): number {
  const [rs, gs, bs] = [r, g, b].map((c) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * rs + 0.7152 * gs + 0.0722 * bs;
}

function contrastRatio(fg: [number, number, number], bg: [number, number, number]): number {
  const l1 = luminance(...fg);
  const l2 = luminance(...bg);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

function parseColor(colorStr: string): { r: number; g: number; b: number; a: number } | null {
  if (!colorStr || colorStr === 'transparent' || colorStr === 'rgba(0, 0, 0, 0)') return null;

  const rgbaMatch = colorStr.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+))?\)/);
  if (rgbaMatch) {
    return {
      r: parseInt(rgbaMatch[1]),
      g: parseInt(rgbaMatch[2]),
      b: parseInt(rgbaMatch[3]),
      a: rgbaMatch[4] !== undefined ? parseFloat(rgbaMatch[4]) : 1.0,
    };
  }

  const hexMatch = colorStr.match(/#([0-9a-fA-F]{3,8})/);
  if (hexMatch) {
    let hex = hexMatch[1];
    if (hex.length === 3) hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
    if (hex.length >= 6) {
      return {
        r: parseInt(hex.slice(0, 2), 16),
        g: parseInt(hex.slice(2, 4), 16),
        b: parseInt(hex.slice(4, 6), 16),
        a: hex.length >= 8 ? parseInt(hex.slice(6, 8), 16) / 255 : 1.0,
      };
    }
  }

  return null;
}

function blendColors(fg: { r: number; g: number; b: number; a?: number }, bg: { r: number; g: number; b: number; a?: number }): [number, number, number] | null {
  if (!fg || !bg) return null;
  const a = fg.a ?? 1.0;
  const bgA = bg.a ?? 1.0;
  const outA = a + bgA * (1 - a);
  if (outA === 0) return [0, 0, 0];
  return [
    Math.round((fg.r * a + bg.r * bgA * (1 - a)) / outA),
    Math.round((fg.g * a + bg.g * bgA * (1 - a)) / outA),
    Math.round((fg.b * a + bg.b * bgA * (1 - a)) / outA),
  ];
}

function isLargeText(fontSize: string, fontWeight: string): boolean {
  const size = parseFloat(fontSize);
  const weight = parseInt(fontWeight) || 400;
  return size >= 18 || (size >= 14 && weight >= 700);
}

function getThreshold(type: string, fontSize: string, fontWeight: string): number {
  if (type === 'heading') return 3.0;
  if (isLargeText(fontSize, fontWeight)) return 3.0;
  return 4.5;
}

// ============================================================
// Test suite
// ============================================================

test.describe('WCAG 2.1 AA Contrast Compliance', () => {
  test.beforeEach(async ({ page }) => {
    await setupAllMocks(page);
  });

  for (const theme of THEMES) {
    test.describe(`${theme.toUpperCase()} theme`, () => {
      for (const pageInfo of PAGES) {
        test(`${pageInfo.name} page meets WCAG 2.1 AA contrast requirements`, async ({ page }) => {
          await page.goto(pageInfo.path);
          await page.waitForLoadState('networkidle');

          // Switch theme
          await page.evaluate((t) => {
            document.documentElement.setAttribute('data-theme', t);
            localStorage.setItem('sv-theme', t);
          }, theme);
          await page.waitForFunction(
            () => {
              const style = getComputedStyle(document.documentElement);
              return style.getPropertyValue('--sv-bg-base').trim() !== '';
            },
            undefined,
            { timeout: 5000 },
          );

          const failures: string[] = [];

          for (const elemDef of ELEMENT_SELECTORS) {
            const elements = await page.$$(elemDef.selector);
            const sampleElements = elements.slice(0, 3);

            for (let i = 0; i < sampleElements.length; i++) {
              const el = sampleElements[i];
              try {
                const styleData = await el.evaluate((node) => {
                  const computed = window.getComputedStyle(node);
                  const result = {
                    color: computed.color,
                    backgroundColor: computed.backgroundColor,
                    fontSize: computed.fontSize,
                    fontWeight: computed.fontWeight,
                    bgStack: [] as string[],
                  };

                  // Collect background color stack
                  let current: Element | null = node;
                  while (current) {
                    const bg = window.getComputedStyle(current).backgroundColor;
                    if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
                      result.bgStack.push(bg);
                    }
                    if (current === document.body) break;
                    current = current.parentElement;
                  }
                  if (result.bgStack.length === 0) {
                    result.bgStack.push(window.getComputedStyle(document.body).backgroundColor);
                  }

                  return result;
                });

                const fgParsed = parseColor(styleData.color);
                let bgRgb = null;

                const bgStack = styleData.bgStack;
                if (bgStack.length > 0) {
                  bgRgb = parseColor(bgStack[bgStack.length - 1]);
                  if (bgRgb) {
                    const bgArr: [number, number, number] = [bgRgb.r, bgRgb.g, bgRgb.b];
                    for (let j = bgStack.length - 2; j >= 0; j--) {
                      const layer = parseColor(bgStack[j]);
                      if (layer) {
                        const blended = blendColors(layer, { r: bgArr[0], g: bgArr[1], b: bgArr[2], a: 1.0 });
                        if (blended) {
                          bgRgb = { r: blended[0], g: blended[1], b: blended[2], a: 1.0 };
                        }
                      }
                    }
                  }
                }

                if (!fgParsed || !bgRgb) continue;

                const fgArr: [number, number, number] = [fgParsed.r, fgParsed.g, fgParsed.b];
                const bgArr: [number, number, number] = [bgRgb.r, bgRgb.g, bgRgb.b];
                const ratio = contrastRatio(fgArr, bgArr);
                const threshold = getThreshold(elemDef.type, styleData.fontSize, styleData.fontWeight);

                if (ratio < threshold) {
                  failures.push(
                    `[${elemDef.category}] ratio ${ratio.toFixed(2)}:1 < ${threshold}:1 | ` +
                    `fg: rgb(${fgArr.join(',')}) bg: rgb(${bgArr.join(',')}) | ` +
                    `${styleData.fontSize}/${styleData.fontWeight}`,
                  );
                }
              } catch (err) {
                // Log elements that can't be evaluated for debugging, but don't fail the test
                // as some elements may be detached or hidden during evaluation
                if (err instanceof Error) {
                  console.warn(`Skipping element evaluation: ${err.message}`);
                }
              }
            }
          }

          expect(
            failures.length,
            `${pageInfo.name} (${theme}) has ${failures.length} contrast violations:\n${failures.join('\n')}`,
          ).toBe(0);
        });
      }
    });
  }
});

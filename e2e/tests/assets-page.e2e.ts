import { test } from '@e2e-dev/web';
import { expect } from 'e2e';

// The workspace asset library (spec 2026-11-13). Read-only: nothing is uploaded, renamed or deleted.
const DRAFT = process.env.THOTH_E2E_NARRATED_DRAFT ?? '';

for (const [width, height] of [[1280, 800], [390, 844]] as const) {
  test(`${width} Assets: the page lists the library and offers a bulk upload without a sideways scroll`, async ({ app, browser, screen }) => {
    await browser.setViewport({ width, height });
    await app.open('/assets');
    await expect(screen.getByText('Upload files')).toBeVisible();
    await expect(screen.getByRole('button', 'All')).toBeVisible();
    await expect(screen.getByLabel('Search assets')).toBeVisible();
    const overflow = await browser.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
}

test('1440 Timeline: the workspace library sits in the asset column', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await app.open(DRAFT);
  await screen.getByRole('group', 'Editor mode').getByRole('button', 'Timeline').tap();
  await expect(screen.getByRole('region', 'Library')).toBeVisible();
});

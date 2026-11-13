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
  await screen.getByRole('tab', 'Library').tap();
  await expect(screen.getByRole('region', 'Library')).toBeVisible();
});

// Layout checks from the 2026-11-13 look (read-only): rows line up, phones keep the search wide,
// and the Timeline's library shows more than one row.
const edges = ({ prefix, side }: { prefix: string; side: 'left' | 'right' }) =>
  [...document.querySelectorAll(`[aria-label^="${prefix}"]`)].map((node) => Math.round(node.getBoundingClientRect()[side]));

test('1280 Assets: every row puts its name and kind in the same columns', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1280, height: 800 });
  await app.open('/assets');
  await expect(screen.getByRole('list', 'Library')).toBeVisible();
  const names = await browser.evaluate(edges, { prefix: 'Name of ', side: 'left' });
  const kinds = await browser.evaluate(edges, { prefix: 'Kind of ', side: 'right' });
  expect(names.length).toBeGreaterThan(1);
  expect(new Set(names).size).toBe(1);
  expect(new Set(kinds).size).toBe(1);
});

test('390 Assets: the search spans the row and every kind select ends at the same edge', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 390, height: 844 });
  await app.open('/assets');
  await expect(screen.getByRole('list', 'Library')).toBeVisible();
  const search = await browser.evaluate(() => document.querySelector('[aria-label="Search assets"]')!.getBoundingClientRect().width);
  expect(search).toBeGreaterThanOrEqual(300);
  const kinds = await browser.evaluate(edges, { prefix: 'Kind of ', side: 'right' });
  expect(new Set(kinds).size).toBe(1);
});

test('1440 Timeline: the library tab shows at least eight whole rows', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await app.open(DRAFT);
  await screen.getByRole('group', 'Editor mode').getByRole('button', 'Timeline').tap();
  await screen.getByRole('tab', 'Library').tap();
  await expect(screen.getByRole('region', 'Library')).toBeVisible();
  // A row counts when the points near its top and bottom belong to it: nothing clips or covers it.
  const shown = await browser.evaluate(() =>
    [...document.querySelectorAll('section[aria-label="Library"] li')].filter((row) => {
      const box = row.getBoundingClientRect();
      if (box.height === 0) return false;
      const x = box.left + box.width / 2;
      return row.contains(document.elementFromPoint(x, box.top + 2)) && row.contains(document.elementFromPoint(x, box.bottom - 2));
    }).length,
  );
  expect(shown).toBeGreaterThanOrEqual(8);
});

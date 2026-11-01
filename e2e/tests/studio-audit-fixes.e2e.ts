import { test } from '@e2e-dev/web';
import { expect } from 'e2e';

// The findings of the first e2e audit of Studio (2026-11-02), each pinned on the narrated draft.
// Read-only and model-free: screens are opened and panes switched; nothing is saved, voiced or rendered.
const DRAFT = process.env.THOTH_E2E_NARRATED_DRAFT ?? '';

test('430 header: the title keeps its row and Request review is in the menu', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 430, height: 932 });
  await app.open(DRAFT);
  await expect(screen.getByRole('navigation', 'Studio jobs')).toBeVisible();
  const width = await browser.evaluate(() => document.querySelector('.studio-topbar span[title]')!.getBoundingClientRect().width);
  expect(width).toBeGreaterThan(150);
  await screen.getByLabel('Studio workspace menu').tap();
  await expect(screen.getByRole('button', 'Request review')).toBeVisible();
});

test('800 tablet: the title keeps its row and nothing scrolls sideways', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 800, height: 1000 });
  await app.open(DRAFT);
  await expect(screen.getByRole('navigation', 'Studio jobs')).toBeVisible();
  const layout = await browser.evaluate(() => ({
    title: document.querySelector('.studio-topbar span[title]')!.getBoundingClientRect().width,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(layout.title).toBeGreaterThan(200);
  expect(layout.scroll).toBeLessThanOrEqual(800);
});

test('430 panes: the pane fills the screen with the beats pinned under it', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 430, height: 932 });
  await app.open(DRAFT);
  const strip = await screen.getByRole('toolbar', 'Story beats').boundingBox();
  expect(strip!.y + strip!.height).toBeGreaterThan(880);
  const scroll = await browser.evaluate(() => document.documentElement.scrollWidth);
  expect(scroll).toBeLessThanOrEqual(430);
});

test('430 Timeline: lane names stay in sight and take a quarter of the screen', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 430, height: 932 });
  await app.open(DRAFT);
  await screen.getByRole('group', 'Editor mode').getByRole('button', 'Timeline').tap();
  await screen.getByRole('navigation', 'Studio panes').getByRole('button', 'Timeline').tap();
  await expect(screen.getByText(/^Best on a larger screen/)).toBeVisible();
  const lane = await browser.evaluate(() => {
    const name = [...document.querySelectorAll('[data-track-id] span')].find((node) => node.textContent === 'main_video')!;
    const style = getComputedStyle(name.parentElement!);
    return { position: style.position, width: name.parentElement!.getBoundingClientRect().width };
  });
  expect(lane.position).toBe('sticky');
  expect(lane.width).toBeLessThan(110);
});

test('1440 Story: the labels, the seconds and the media tell the truth', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await app.open(DRAFT);
  await expect(screen.getByText(/^Beat 1 of 4 · 8\.9 s/, { visible: true })).toBeVisible();
  const materials = screen.getByRole('complementary', 'Materials');
  await expect(materials.getByText('Post card · @kabinet_rakyat', { visible: true })).toBeVisible();
  await expect(materials.getByText('Profile card · @kabinet_rakyat', { visible: true })).toBeVisible();
  await expect(materials.getByRole('region', /^Narration/)).toBeVisible();
  await expect(screen.getByText('No media attached', { visible: true })).toHaveCount(0);
  await expect(screen.getByText(/^9:16 · 1080×1920 · /, { visible: true })).toBeVisible();
  await expect(screen.getByText(/asset_|clip_/, { visible: true })).toHaveCount(0);
});

test('1440: nothing is focused on load, and the top bar counts only real runs', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await app.open(DRAFT);
  await expect(screen.getByRole('toolbar', 'Story beats')).toBeVisible();
  await expect(screen.getByText('Space to play/pause', { exact: false, visible: true })).toBeVisible();
  const focused = await browser.evaluate(() => document.activeElement?.tagName ?? null);
  expect(focused).not.toBe('BUTTON');
  await expect(screen.getByText('20 running', { visible: true })).toHaveCount(0);
});

test('1440 Timeline: this draft\'s assets list before other drafts\' uploads, each with its picture or icon', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await app.open(DRAFT);
  await screen.getByRole('button', 'Timeline').tap();
  await expect(screen.getByRole('region', 'Asset library')).toBeVisible();
  await expect(screen.getByRole('region', 'Asset library').getByText('Narration · Main', { visible: true })).toBeVisible();
  const rows = await browser.evaluate(() =>
    [...document.querySelectorAll('[aria-label="Asset library"] li')].map((row) => ({
      label: row.querySelector('span.font-medium')?.textContent ?? '',
      visual: Boolean(row.querySelector('svg, img, video')),
    })),
  );
  expect(rows.length).toBeGreaterThan(0);
  expect(rows.every((row) => row.visual)).toBe(true);
  const uploads = rows.map((row) => row.label.startsWith('Upload'));
  expect(uploads.lastIndexOf(false)).toBeLessThan(uploads.indexOf(true) === -1 ? rows.length : uploads.indexOf(true));
});

test('1024: one script button in the menu, and the side panel named Materials', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1024, height: 820 });
  await app.open(DRAFT);
  await screen.getByLabel('Studio workspace menu').tap();
  await expect(screen.getByRole('button', 'Open script')).toBeVisible();
  await expect(screen.getByRole('button', 'Script')).toHaveCount(0);
  await expect(screen.getByRole('button', 'Materials panel')).toBeVisible();
  await expect(screen.getByRole('button', 'Scene board panel')).toHaveCount(0);
});

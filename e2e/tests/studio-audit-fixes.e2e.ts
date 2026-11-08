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
    // Tier 1 (2026-11-08): the name is a plain-language button, no longer the raw `main_video`.
    const name = document.querySelector('[data-track-id] [data-track-name]')!;
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
  await expect(screen.getByText(/^9:16 · 1080×1920/, { visible: true })).toBeVisible();
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

test('1440 Timeline and Review: the canvas size stays in sight under the preview', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await app.open(DRAFT);
  await screen.getByRole('group', 'Editor mode').getByRole('button', 'Timeline').tap();
  await expect(screen.getByRole('region', 'Asset library')).toBeVisible();
  await expect(screen.getByText(/^9:16 · 1080×1920/, { visible: true })).toBeVisible();
  await screen.getByRole('navigation', 'Studio jobs').getByRole('button', 'Review').tap();
  await expect(screen.getByText(/^9:16 · 1080×1920/, { visible: true })).toBeVisible();
});

test('430 Render: the header stays put while the panel scrolls', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 430, height: 932 });
  await app.open(DRAFT);
  await screen.getByRole('navigation', 'Studio jobs').getByRole('button', 'Render').tap();
  await expect(screen.getByRole('heading', 'Readiness')).toBeVisible();
  const layout = await browser.evaluate(() => {
    const panel = document.querySelector('.studio-render-workspace')!;
    panel.scrollTop = 99999;
    document.querySelector('#workspace')!.scrollTop = 99999;
    window.scrollTo(0, 99999);
    return {
      scrolled: panel.scrollTop,
      header: document.querySelector('.studio-topbar')!.getBoundingClientRect().top,
    };
  });
  expect(layout.scrolled).toBeGreaterThan(0);
  expect(layout.header).toBeGreaterThanOrEqual(0);
});

// Failed only on the dev server, whose StrictMode runs effects twice; run it on a dev target to mean anything.
test('1440 Render: the options finish loading', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await app.open(DRAFT);
  await screen.getByRole('navigation', 'Studio jobs').getByRole('button', 'Render').tap();
  await expect(screen.getByRole('heading', 'Readiness')).toBeVisible();
  await expect(screen.getByText('Loading render options…', { visible: true })).toHaveCount(0, { timeout: 15000 });
});

test('1440: the script panel opens from the narration chip', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await app.open(DRAFT);
  await screen.getByText(/^Narrated · \d+ beats/).first().tap();
  await screen.getByRole('button', 'Open script').tap();
  // The chip's menu closed itself, so Close script is one more tap away.
  await expect(screen.getByRole('button', 'Safe zone')).toBeVisible();
  const lines = await browser.evaluate(() =>
    [...document.querySelectorAll('textarea')]
      .filter((node) => node.closest('section[aria-label="Script"]'))
      .map((node) => node.scrollHeight - node.clientHeight),
  );
  expect(lines.length).toBe(4);
  // Every line reads whole, without scrolling inside its field.
  expect(Math.max(...lines)).toBeLessThanOrEqual(1);
  // A long script scrolls in its column and never runs under the beats.
  const column = await browser.evaluate(() => {
    const panel = document.querySelector('section[aria-label="Script"]')!;
    let box: Element = panel;
    while (box.parentElement && getComputedStyle(box).overflowY !== 'auto') box = box.parentElement;
    return {
      bottom: box.getBoundingClientRect().bottom,
      beats: document.querySelector('[aria-label="Story beats"]')!.getBoundingClientRect().top,
      scrolls: box.scrollHeight > box.clientHeight,
    };
  });
  expect(column.bottom).toBeLessThanOrEqual(column.beats);
  expect(column.scrolls).toBe(true);
  await app.screenshot('script-open-1440');
});

test('430 Timeline: the preview pane gives the player room, its clock whole', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 430, height: 932 });
  await app.open(DRAFT);
  await screen.getByRole('group', 'Editor mode').getByRole('button', 'Timeline').tap();
  await screen.getByRole('navigation', 'Studio panes').getByRole('button', 'Preview').tap();
  await expect(screen.getByRole('button', 'Play video')).toBeVisible();
  const width = await browser.evaluate(() => document.querySelector('[aria-label="Studio preview"] > div')!.getBoundingClientRect().width);
  expect(width).toBeGreaterThan(220);
  await expect(screen.getByText('0:00 / 0:34', { visible: true })).toBeVisible();
  await app.screenshot('timeline-preview-430');
});

test('1024 Timeline: the last lane can be reached', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1024, height: 820 });
  await app.open(DRAFT);
  await screen.getByRole('group', 'Editor mode').getByRole('button', 'Timeline').tap();
  await expect(screen.getByRole('group', 'SFX track')).toBeVisible();
  const lane = await browser.evaluate(() => {
    const track = document.querySelector('[aria-label="SFX track"]')!;
    track.scrollIntoView({ block: 'end' });
    return {
      bottom: track.getBoundingClientRect().bottom,
      bar: document.querySelector('[aria-label="Timeline issues"]')!.getBoundingClientRect().top,
    };
  });
  expect(lane.bottom).toBeLessThanOrEqual(lane.bar + 1);
});

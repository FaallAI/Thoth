import { test } from '@e2e-dev/web';
import { expect } from 'e2e';

// Studio shell v2 audit (spec 2026-11-01), read-only and model-free: screens are opened and modes
// or panes switched; nothing is saved, voiced or rendered. Visual judgments happen live over
// `e2e mcp`, by the coding agent reading screenshots (AGENTS.md, E2E audits).
const DRAFT = process.env.THOTH_E2E_NARRATED_DRAFT ?? '';

test('1440 Story: tier 1 controls, the narration chip and a beat total that matches the canvas', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await app.open(DRAFT);
  for (const name of ['Back to Studio', 'Undo', 'Redo', 'Request review', 'Add beat']) {
    await expect(screen.getByRole('button', name)).toBeVisible();
  }
  await expect(screen.getByRole('navigation', 'Studio jobs')).toBeVisible();
  await expect(screen.getByText('Narrated · 4 beats', { visible: true })).toBeVisible();
  // The draft's own total, which must match its canvas (Tier 2 follow-up, 2026-11-08).
  await expect(screen.getByText(/^Total \d+\.\d s$/)).toBeVisible();
  await expect(screen.getByText('matches canvas')).toBeVisible();
  await expect(screen.getByRole('button', /^Main \d+\.\d s Narrated$/)).toBeVisible();
  await expect(screen.getByText(/asset_|clip_/, { visible: true })).toHaveCount(0);
});

test('1440 Timeline: every tool and the clip inspector fields stay, named in words', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await app.open(DRAFT);
  await screen.getByRole('button', 'Timeline').tap();
  await expect(screen.getByRole('region', 'Asset library')).toBeVisible();
  await expect(screen.getByRole('region', 'Sound effects')).toBeVisible();
  for (const name of ['Move clip to playhead', 'Trim start to playhead', 'Trim end to playhead', 'Split clip at playhead', 'Zoom in', 'Zoom out']) {
    await expect(screen.getByRole('button', name)).toBeVisible();
  }
  await expect(screen.getByRole('switch', 'Ripple')).toBeVisible();
  await expect(screen.getByRole('switch', 'Snap')).toBeVisible();
  await screen.getByRole('button', 'Main Video clip').tap();
  await expect(screen.getByRole('heading', 'Main video · @kabinet_rakyat')).toBeVisible();
  for (const name of ['Start frame', 'End frame', 'Fit', 'Crop', 'Hidden', 'Locked', 'Edited by']) {
    await expect(screen.getByLabel(name)).toBeVisible();
  }
  await expect(screen.getByText(/asset_|clip_/, { visible: true })).toHaveCount(0);
});

test('1024: the menu holds the narration, the script and Assist', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1024, height: 820 });
  await app.open(DRAFT);
  await screen.getByLabel('Studio workspace menu').tap();
  for (const name of ['Recreate narration…', 'Open script', 'Assist']) {
    await expect(screen.getByRole('button', name)).toBeVisible();
  }
});

test('430 Story: panes and beat chips', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 430, height: 932 });
  await app.open(DRAFT);
  const panes = screen.getByRole('navigation', 'Studio panes');
  for (const name of ['Materials', 'Preview', 'Inspector']) {
    await expect(panes.getByRole('button', name)).toBeVisible();
  }
  await expect(screen.getByRole('toolbar', 'Story beats')).toBeVisible();
  await panes.getByRole('button', 'Inspector').tap();
  await expect(screen.getByRole('button', 'Edit heading')).toBeVisible();
});

test('430 Timeline: menu-only lanes with a how-to note and Inspect', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 430, height: 932 });
  await app.open(DRAFT);
  await screen.getByRole('group', 'Editor mode').getByRole('button', 'Timeline').tap();
  await screen.getByRole('navigation', 'Studio panes').getByRole('button', 'Timeline').tap();
  // Tier 3a (operator, 2026-11-09): phones edit by long-press menu; drag, trim and toggles stay off.
  await expect(screen.getByText(/^Tap a clip to select it/)).toBeVisible();
  await expect(screen.getByRole('group', 'Clip actions')).toHaveCount(0);
  await expect(screen.getByRole('button', /^(Hide|Mute|Lock) /)).toHaveCount(0);
  await expect(screen.getByRole('button', /^Trim (start|end) of /)).toHaveCount(0);
  await screen.getByRole('button', 'Main Video clip').tap();
  await expect(screen.getByRole('button', 'Inspect')).toBeVisible();
});

test('1440 Timeline: a video clip shows the Effects section', async ({ app, browser, screen }) => {
  // Studio effects layer (spec 2026-11-09): the controls are looked at, never used here.
  await browser.setViewport({ width: 1440, height: 900 });
  await app.open(DRAFT);
  await screen.getByRole('button', 'Timeline').tap();
  await screen.getByRole('button', 'Main Video clip').tap();
  await expect(screen.getByLabel('Background')).toBeVisible();
  await expect(screen.getByLabel('Dim')).toBeVisible();
  for (const name of ['Moves', 'Marks']) await expect(screen.getByRole('group', name)).toBeVisible();
  for (const name of ['Punch in at playhead', 'Push in', 'Add box', 'Add arrow']) {
    await expect(screen.getByRole('button', name)).toBeVisible();
  }
});

test('1440: the Style control asks before applying, and Cancel changes nothing', async ({ app, browser, screen }) => {
  // Style templates (spec 2026-11-10): looked at only; the read scope never applies a style.
  await browser.setViewport({ width: 1440, height: 900 });
  await app.open(DRAFT);
  const before = await browser.evaluate(() => document.body.innerText.match(/Saved revision \d+/)?.[0] ?? '');
  await expect(screen.getByRole('option', 'Style A')).toHaveCount(1);
  await screen.getByLabel('Style').selectOption('Style A');
  await expect(screen.getByText('Apply Style A?')).toBeVisible();
  await expect(screen.getByText(/replaces every edit you made by hand/)).toBeVisible();
  await screen.getByRole('button', 'Cancel').tap();
  await expect(screen.getByText('Apply Style A?')).toHaveCount(0);
  const after = await browser.evaluate(() => document.body.innerText.match(/Saved revision \d+/)?.[0] ?? '');
  expect(after).toBe(before);
});

test('1440 Timeline: a video clip shows its filmstrip and narration its waveform', async ({ app, browser, screen }) => {
  // Tier 3b: the glance is a GET, so the read scope sees it; the first look may build it.
  await browser.setViewport({ width: 1440, height: 900 });
  await app.open(DRAFT);
  await screen.getByRole('button', 'Timeline').tap();
  await expect(screen.getByRole('button', 'Main Video clip').getByTestId('clip-filmstrip')).toBeVisible({ timeout: 30000 });
  await expect(screen.getByRole('button', 'Narration clip').first().getByTestId('clip-waveform')).toBeVisible({ timeout: 30000 });
});

// Full-width timeline (spec 2026-11-09). Sizes stay in this browser; nothing is saved to the server.
async function openWideTimeline({ app, browser, screen }: { app: any; browser: any; screen: any }) {
  await browser.setViewport({ width: 1440, height: 900 });
  await app.open(DRAFT);
  await screen.getByRole('button', 'Timeline').tap();
  await expect(screen.getByRole('separator', 'Resize timeline')).toBeVisible();
}
const box = (browser: any, selector: string) =>
  browser.evaluate((query: string) => {
    const rect = document.querySelector(query)!.getBoundingClientRect();
    return { top: rect.top, bottom: rect.bottom, width: rect.width, height: rect.height };
  }, selector);

test('1440 Timeline: the timeline spans the window under the preview', async ({ app, browser, screen }) => {
  await openWideTimeline({ app, browser, screen });
  const timeline = await box(browser, 'section[aria-label="Timeline"]');
  const preview = await box(browser, 'section[aria-label="Studio preview"]');
  expect(timeline.width).toBeGreaterThanOrEqual(1438);
  expect(timeline.top).toBeGreaterThanOrEqual(preview.bottom);
  await app.screenshot('wide-timeline-1440');
});

test('1440 Timeline: the divider resizes, is remembered, and resets', async ({ app, browser, screen }) => {
  await openWideTimeline({ app, browser, screen });
  const before = await box(browser, 'section[aria-label="Timeline"]');
  const divider = await screen.getByRole('separator', 'Resize timeline').boundingBox();
  const y = divider.y + divider.height / 2;
  await browser.mouse.move(700, y);
  await browser.mouse.down();
  await browser.mouse.move(700, y - 100);
  await browser.mouse.up();
  const taller = await box(browser, 'section[aria-label="Timeline"]');
  expect(Math.abs(taller.height - before.height - 100)).toBeLessThanOrEqual(2);
  await openWideTimeline({ app, browser, screen });
  const again = await box(browser, 'section[aria-label="Timeline"]');
  expect(Math.abs(again.height - taller.height)).toBeLessThanOrEqual(2);
  await screen.getByRole('separator', 'Resize timeline').doubleTap();
  await expect
    .poll(async () => Math.round((await box(browser, 'section[aria-label="Timeline"]')).height), { timeout: 3000 })
    .toBe(392);
});

test('1440 Timeline: the player bar sits under the video', async ({ app, browser, screen }) => {
  await openWideTimeline({ app, browser, screen });
  const play = await screen.getByRole('button', 'Play video').boundingBox();
  const video = await box(browser, 'section[aria-label="Studio preview"] > div:first-child');
  expect(play.y).toBeGreaterThanOrEqual(video.bottom);
  // One row: the controls stay beside each other, as approved on the mock-up.
  const fullscreen = await screen.getByRole('button', 'Enter Fullscreen').boundingBox();
  expect(Math.abs(fullscreen.y - play.y)).toBeLessThanOrEqual(4);
  expect(fullscreen.x - play.x).toBeGreaterThan(40);
  // Comfortable to hit in either language, and the play button in the middle of the bar.
  expect(Math.min(play.width, play.height, fullscreen.width, fullscreen.height)).toBeGreaterThanOrEqual(24);
  const bar = await browser.evaluate(() => {
    const rect = document.querySelector('.studio-preview-bar')!.getBoundingClientRect();
    return rect.left + rect.width / 2;
  });
  expect(Math.abs(play.x + play.width / 2 - bar)).toBeLessThanOrEqual(1);
});

test('1440 Timeline: the clips fill the width on opening', async ({ app, browser, screen }) => {
  await openWideTimeline({ app, browser, screen });
  const lanes = await browser.evaluate(() => {
    const box = document.querySelector('[data-testid="timeline-lanes"]')!;
    const clips = [...document.querySelectorAll('button[aria-label="Narration clip"]')];
    return { spill: box.scrollWidth - box.clientWidth, end: clips.at(-1)!.getBoundingClientRect().right };
  });
  expect(lanes.spill).toBeLessThanOrEqual(2);
  expect(lanes.end).toBeGreaterThanOrEqual(1380);
});

test('1440 Timeline: every standard track fits at the default height', async ({ app, browser, screen }) => {
  await openWideTimeline({ app, browser, screen });
  const lane = await box(browser, '[aria-label="SFX track"]');
  const lanes = await box(browser, '[data-testid="timeline-lanes"]');
  expect(lane.bottom).toBeLessThanOrEqual(lanes.bottom + 1);
});

test('1440: text cannot be selected, fields still can', async ({ app, browser, screen }) => {
  await openWideTimeline({ app, browser, screen });
  const selectable = await browser.evaluate(() => ({
    heading: getComputedStyle(document.querySelector('.studio-shell h2, .studio-shell h3')!).userSelect,
    field: getComputedStyle(document.querySelector('input[aria-label="Search assets"]')!).userSelect,
  }));
  expect(selectable).toEqual({ heading: 'none', field: 'text' });
});

test('1440 Timeline: the same player stays through Review and back', async ({ app, browser, screen }) => {
  await openWideTimeline({ app, browser, screen });
  await browser.evaluate(() => {
    (window as any).__player = document.querySelector('.__remotion-player');
    return null;
  });
  await screen.getByRole('navigation', 'Studio jobs').getByRole('button', 'Review').tap();
  expect(await browser.evaluate(() => Boolean((window as any).__player?.isConnected))).toBe(true);
  await screen.getByRole('navigation', 'Studio jobs').getByRole('button', 'Edit').tap();
  expect(await browser.evaluate(() => Boolean((window as any).__player?.isConnected))).toBe(true);
});

test('1280 Timeline: a long sound list leaves Assets its share of the top row', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1280, height: 720 });
  await app.open(DRAFT);
  await screen.getByRole('button', 'Timeline').tap();
  await expect(screen.getByRole('region', 'Sound effects')).toBeVisible({ timeout: 20000 });
  const share = await browser.evaluate(() => {
    const sounds = document.querySelector('[aria-label="Sound effects"]')!;
    const tall = document.createElement('div');
    tall.style.height = '900px';
    sounds.appendChild(tall);
    const assets = document.querySelector('[aria-label="Asset library"]')!;
    return assets.getBoundingClientRect().height / assets.parentElement!.getBoundingClientRect().height;
  });
  expect(share).toBeGreaterThanOrEqual(0.6);
});

for (const mode of ['Story', 'Review'] as const) {
  test(`1440 ${mode}: the player bar sits under the video in one row`, async ({ app, browser, screen }) => {
    await browser.setViewport({ width: 1440, height: 900 });
    await app.open(DRAFT);
    if (mode === 'Review') await screen.getByRole('navigation', 'Studio jobs').getByRole('button', 'Review').tap();
    const play = await screen.getByRole('button', 'Play video').boundingBox();
    const fullscreen = await screen.getByRole('button', 'Enter Fullscreen').boundingBox();
    const video = await box(browser, 'section[aria-label="Studio preview"] > div:first-child');
    expect(play.y).toBeGreaterThanOrEqual(video.bottom);
    expect(Math.abs(fullscreen.y - play.y)).toBeLessThanOrEqual(4);
    await app.screenshot(`bar-${mode}`);
  });
}

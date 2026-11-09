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

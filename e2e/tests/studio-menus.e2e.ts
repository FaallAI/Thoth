import { test } from '@e2e-dev/web';
import { expect } from 'e2e';

// Studio Timeline track, Tier 1 (spec 2026-11-08): the right-click menus and the shortcut list on the
// narrated draft. Read-only and model-free: menus open and modes switch; no entry that edits is chosen.
const DRAFT = process.env.THOTH_E2E_NARRATED_DRAFT ?? '';

test('1440 Story: a Shown item\'s menu opens the Timeline on that clip', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await app.open(DRAFT);
  await screen.getByRole('region', 'Shown').getByRole('listitem').first().secondaryTap();
  await expect(screen.getByRole('menuitem', 'Show in Timeline')).toBeVisible();
  await screen.getByRole('menuitem', 'Show in Timeline').tap();
  await expect(screen.getByRole('group', 'Editor mode').getByRole('button', 'Timeline')).toHaveAttribute('aria-pressed', 'true');
  await expect(screen.getByRole('complementary', 'Timeline inspector').getByRole('textbox', 'Start time')).toBeVisible();
});

test('1440 Timeline: a clip\'s menu lists the editing entries', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await app.open(DRAFT);
  await screen.getByRole('group', 'Editor mode').getByRole('button', 'Timeline').tap();
  await screen.getByRole('button', 'Main Video clip').secondaryTap();
  for (const name of ['Split at playhead', 'Delete', 'Ripple delete', 'Replace media…', 'Show in Story']) {
    await expect(screen.getByRole('menuitem', name)).toBeVisible();
  }
  await app.screenshot('timeline-menu-1440');
  await browser.keyboard.press('Escape');
  await expect(screen.getByRole('menu')).toHaveCount(0);
});

test('1440 Timeline: ? opens the shortcut list', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await app.open(DRAFT);
  await screen.getByRole('group', 'Editor mode').getByRole('button', 'Timeline').tap();
  await screen.getByRole('slider', 'Playhead').focus();
  await browser.keyboard.press('?');
  await expect(screen.getByRole('dialog', 'Keyboard shortcuts')).toBeVisible();
  await app.screenshot('shortcuts-1440');
});

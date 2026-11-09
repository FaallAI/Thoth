import { test } from '@e2e-dev/web';
import { expect } from 'e2e';

// Tier 3a (operator, 2026-11-09): phones edit through the menus. Read-only: a menu is opened and
// closed, and nothing is chosen, saved, voiced or rendered.
const DRAFT = process.env.THOTH_E2E_NARRATED_DRAFT ?? '';

test('430 Timeline: the preview sits above the lanes, and a long press opens the clip menu', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 430, height: 932 });
  await app.open(DRAFT);
  await screen.getByRole('group', 'Editor mode').getByRole('button', 'Timeline').tap();
  await screen.getByRole('navigation', 'Studio panes').getByRole('button', 'Timeline').tap();
  await expect(screen.getByText('Tap a clip to select it. Press and hold for its menu. Drag and trim on a wider screen.')).toBeVisible();
  const order = await browser.evaluate(() => {
    const preview = document.querySelector('section[aria-label="Studio preview"]');
    const lanes = document.querySelector('[data-testid="timeline-lanes"]');
    if (!preview || !lanes) return 'missing';
    return preview.getBoundingClientRect().bottom <= lanes.getBoundingClientRect().top + 1 ? 'above' : 'not above';
  });
  expect(order).toBe('above');
  await browser.evaluate(() => {
    const clip = document.querySelector('[aria-label="Main Video clip"]')!;
    const box = clip.getBoundingClientRect();
    const at = { bubbles: true, pointerType: 'touch', button: 0, clientX: box.x + 4, clientY: box.y + box.height / 2 };
    clip.dispatchEvent(new PointerEvent('pointerdown', at));
    return new Promise((done) => setTimeout(() => done(null), 700));
  });
  await expect(screen.getByRole('menuitem', 'Split at playhead')).toBeVisible();
  await browser.keyboard.press('Escape');
});

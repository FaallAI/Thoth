import { test } from '@e2e-dev/web';
import { expect } from 'e2e';

// Run on an Indonesian target (dev1440id): the language comes from the signed-in user, which that
// target's browser rewrites. No English the operator's words would replace is left on these screens.
const DRAFT = process.env.THOTH_E2E_NARRATED_DRAFT ?? '';

test('Story reads Indonesian', async ({ app, screen }) => {
  await app.open(DRAFT);
  await expect(screen.getByRole('button', 'Minta tinjauan')).toBeVisible();
  await expect(screen.getByText('Spasi untuk putar/jeda', { exact: false, visible: true })).toBeVisible();
  await expect(screen.getByText('Space to play/pause', { exact: false })).toHaveCount(0);
  await expect(screen.getByText('Judul', { visible: true })).toBeVisible();
  await expect(screen.getByText('Heading', { exact: true })).toHaveCount(0);
  await expect(screen.getByText('Replace', { exact: true })).toHaveCount(0);
});

test('Timeline reads Indonesian', async ({ app, browser, screen }) => {
  await app.open(DRAFT);
  await screen.getByRole('group', 'Mode editor').getByRole('button', 'Timeline').tap();
  await expect(screen.getByRole('heading', 'Aset')).toBeVisible();
  await expect(screen.getByRole('button', 'Pratinjau Narasi · Utama')).toBeVisible();
  const labels = await browser.evaluate(() => [...document.querySelectorAll('[aria-label="Asset library"] li button')].map((node) => node.textContent ?? ''));
  expect(labels).not.toContain('Add');
  expect(labels).not.toContain('Preview');
});

test('the phone panes call Timeline by the name the mode uses', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 430, height: 932 });
  await app.open(DRAFT);
  await screen.getByRole('group', 'Mode editor').getByRole('button', 'Timeline').tap();
  await expect(screen.getByRole('button', 'Inspektor')).toBeVisible();
  await expect(screen.getByText('Linimasa')).toHaveCount(0);
});

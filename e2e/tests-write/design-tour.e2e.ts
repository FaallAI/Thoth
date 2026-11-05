import { test } from '@e2e-dev/web';
import { expect } from 'e2e';

// Screenshots of every Studio screen for a person to judge; the write guard keeps the real draft safe.
const DRAFT = process.env.THOTH_E2E_NARRATED_DRAFT ?? '';

test('1440 tour', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await app.open('/studio');
  await browser.evaluate((project: string) => {
    localStorage.setItem('thoth.activeProject', project);
    return null;
  }, DRAFT.split('/')[2]);
  await app.open('/studio');
  await expect(screen.getByRole('heading', 'Studio')).toBeVisible();
  await app.screenshot('t1440-1-documents');
  await app.open(DRAFT);
  await expect(screen.getByRole('toolbar', 'Story beats')).toBeVisible();
  await browser.evaluate(() => new Promise((done) => setTimeout(() => done(null), 2500)));
  await app.screenshot('t1440-2-story');
  await screen.getByRole('group', 'Editor mode').getByRole('button', 'Timeline').tap();
  await expect(screen.getByRole('region', 'Asset library')).toBeVisible();
  await browser.evaluate(() => new Promise((done) => setTimeout(() => done(null), 2000)));
  await app.screenshot('t1440-3-timeline');
  await screen.getByRole('button', 'Main Video clip').first().tap();
  await app.screenshot('t1440-4-timeline-clip');
  await screen.getByRole('navigation', 'Studio jobs').getByRole('button', 'Review').tap();
  await app.screenshot('t1440-5-review');
  await screen.getByRole('navigation', 'Studio jobs').getByRole('button', 'Render').tap();
  await browser.evaluate(() => new Promise((done) => setTimeout(() => done(null), 800)));
  await app.screenshot('t1440-6-render');
});

test('1024 tour', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1024, height: 820 });
  await app.open(DRAFT);
  await expect(screen.getByRole('toolbar', 'Story beats')).toBeVisible();
  await browser.evaluate(() => new Promise((done) => setTimeout(() => done(null), 2000)));
  await app.screenshot('t1024-1-story');
  await screen.getByRole('group', 'Editor mode').getByRole('button', 'Timeline').tap();
  await browser.evaluate(() => new Promise((done) => setTimeout(() => done(null), 2000)));
  await app.screenshot('t1024-2-timeline');
});

test('430 tour', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 430, height: 932 });
  await app.open(DRAFT);
  await expect(screen.getByRole('toolbar', 'Story beats')).toBeVisible();
  await browser.evaluate(() => new Promise((done) => setTimeout(() => done(null), 2000)));
  await app.screenshot('t430-1-story');
  await screen.getByRole('group', 'Editor mode').getByRole('button', 'Timeline').tap();
  await screen.getByRole('navigation', 'Studio panes').getByRole('button', 'Timeline').tap();
  await browser.evaluate(() => new Promise((done) => setTimeout(() => done(null), 1000)));
  await app.screenshot('t430-2-timeline');
});

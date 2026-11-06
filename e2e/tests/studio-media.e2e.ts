import { test, type Browser } from '@e2e-dev/web';
import { expect } from 'e2e';
import { fileURLToPath } from 'node:url';

// Playback and pictures. The read-scope token cannot ask for previews, so the browser answers those
// requests with local fixtures: this proves the Player and the rows, not the server's media.
const DRAFT = process.env.THOTH_E2E_NARRATED_DRAFT ?? '';
const PROJECT = DRAFT.split('/')[2]!;
const fixture = (name: string) => fileURLToPath(new URL(`./fixtures/${name}`, import.meta.url));

/** Opens the draft with every preview answered locally, a picture for an image and a clip otherwise. */
async function openWithLocalMedia(app: { open(path: string): Promise<unknown> }, browser: Browser) {
  await app.open('/studio');
  const images: string[] = await browser.evaluate(async (project: string) => {
    const found: string[] = [];
    let cursor: string | null = null;
    do {
      const query = `limit=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`;
      const page: { assets: { asset_id: string; kind: string }[]; next_cursor: string | null } = await (
        await fetch(`/api/v1/projects/${project}/editor-assets?${query}`)
      ).json();
      found.push(...page.assets.filter((asset) => asset.kind === 'image').map((asset) => asset.asset_id));
      cursor = page.next_cursor;
    } while (cursor);
    return found;
  }, PROJECT);
  // The real shape of a preview address: Studio refuses any other.
  await browser.route('**/editor-assets/*/preview-capability', (route) =>
    route.fulfill({
      json: { preview_url: new URL(route.request.url).pathname.replace(/-capability$/, ''), expires_at: '2099-01-01T00:00:00Z' },
    }),
  );
  await browser.route('**/editor-assets/*/preview', (route) => {
    const assetId = route.request.url.split('/editor-assets/')[1]!.split('/')[0]!;
    return images.includes(assetId)
      ? route.fulfill({ path: fixture('picture.png'), contentType: 'image/png' })
      : route.fulfill({ path: fixture('media.webm'), contentType: 'video/webm' });
  });
  await app.open(DRAFT);
}

test('1440 Story: Play moves the clock and the media loads', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await openWithLocalMedia(app, browser);
  await expect(screen.getByText('Post card · @kabinet_rakyat', { visible: true })).toBeVisible();
  await screen.getByRole('button', 'Play video').tap();
  await expect(screen.getByText(/^0:0[1-9] \/ 0:34/)).toBeVisible({ timeout: 15000 });
  await expect(screen.getByTestId('preview-unavailable')).toHaveCount(0);
  await app.screenshot('story-playing-1440');
});

test('1440 Story: Space plays and pauses when nothing else holds focus', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await openWithLocalMedia(app, browser);
  await expect(screen.getByRole('button', 'Play video')).toBeVisible();
  await browser.keyboard.press('Space');
  await expect(screen.getByRole('button', 'Pause video')).toBeVisible();
  await browser.keyboard.press('Space');
  await expect(screen.getByRole('button', 'Play video')).toBeVisible();
});

test('1440 Story: Space in a text field types and leaves the player alone', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await openWithLocalMedia(app, browser);
  await screen.getByRole('searchbox', 'Search materials').tap();
  await browser.keyboard.press('Space');
  await expect(screen.getByRole('button', 'Play video')).toBeVisible();
  await expect(screen.getByRole('button', 'Pause video')).toHaveCount(0);
});

test('1440 Materials: rows show their pictures', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await openWithLocalMedia(app, browser);
  const materials = screen.getByRole('complementary', 'Materials');
  await expect(materials.getByText('Post card · @kabinet_rakyat', { visible: true })).toBeVisible();
  await expect.poll(() =>
    browser.evaluate(() =>
      [...document.querySelectorAll('[aria-label="Materials"] img')].filter((node) => (node as HTMLImageElement).naturalWidth > 0).length,
    ),
  ).toBeGreaterThan(3);
  await app.screenshot('materials-pictures-1440');
});

test('1440 Timeline: Preview plays the chosen narration', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await openWithLocalMedia(app, browser);
  await screen.getByRole('group', 'Editor mode').getByRole('button', 'Timeline').tap();
  await screen.getByRole('button', 'Preview Narration · Main').tap();
  await screen.getByRole('button', 'Play video').tap();
  await expect(screen.getByText(/^0:0[1-9] \/ 0:34/)).toBeVisible({ timeout: 15000 });
  await expect(screen.getByTestId('preview-unavailable')).toHaveCount(0);
  await app.screenshot('timeline-playing-1440');
});

test('1440 Story: a narrated caption sits low on the canvas, clear of the platform buttons', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await openWithLocalMedia(app, browser);
  await screen.getByRole('button', 'Play video').tap();
  await expect(screen.getByText(/^0:0[2-9] \/ 0:34/)).toBeVisible({ timeout: 15000 });
  await browser.keyboard.press('Space');
  const place = await browser.evaluate(() => {
    const canvas = document.querySelector('.__remotion-player')!.getBoundingClientRect();
    const cue = document.querySelector('[data-testid="caption-cue"]')!.getBoundingClientRect();
    return {
      height: cue.height / canvas.height,
      bottom: (cue.bottom - canvas.top) / canvas.height,
      centre: (cue.left + cue.width / 2 - canvas.left) / canvas.width,
    };
  });
  // The box is the words' size, not the canvas': it once ran the whole height and covered the title.
  expect(place.height).toBeLessThan(0.2);
  expect(place.bottom).toBeGreaterThan(0.6);
  expect(place.bottom).toBeLessThan(0.825);
  expect(Math.abs(place.centre - 0.5)).toBeLessThan(0.02);
  await app.screenshot('caption-placed-1440');
});

test('1440 Story: the beat tiles draw no broken picture for a voice', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await openWithLocalMedia(app, browser);
  await expect(screen.getByRole('toolbar', 'Story beats')).toBeVisible();
  await expect.poll(() =>
    browser.evaluate(() => document.querySelectorAll('[aria-label="Story beats"] img, [aria-label="Story beats"] video').length),
  ).toBeGreaterThan(0);
  const broken = await browser.evaluate(() =>
    [...document.querySelectorAll('[aria-label="Story beats"] img')].filter((node) => (node as HTMLImageElement).complete && (node as HTMLImageElement).naturalWidth === 0).length,
  );
  expect(broken).toBe(0);
});

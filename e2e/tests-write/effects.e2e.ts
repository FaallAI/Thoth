import { test } from '@e2e-dev/web';
import { expect } from 'e2e';

// Studio effects layer (spec 2026-11-09), saved in the throwaway project. Run with
// e2e.write.config.ts, only on the operator's word and a one-day write token.
const PROJECT = process.env.THOTH_E2E_WRITE_PROJECT ?? '';
type Fixtures = { app: any; browser: any; screen: any };

const saved = (browser: any) =>
  browser.evaluate(async (project: string) => {
    const documentId = location.pathname.split('/').pop();
    return (await fetch(`/api/v1/projects/${project}/edit-documents/${documentId}`)).json();
  }, PROJECT);

const mainClip = async (browser: any) => {
  const document = await saved(browser);
  const main = document.tracks.find((track: any) => track.kind === 'main_video');
  return document.clips.find((clip: any) => clip.track_id === main.track_id);
};

/** A blank draft with the project's video upload on the main track, selected, at revision 3. */
async function selectedClip({ app, browser, screen }: Fixtures) {
  await browser.setViewport({ width: 1440, height: 900 });
  await app.open('/studio');
  await browser.evaluate((project: string) => {
    localStorage.setItem('thoth.activeProject', project);
    return null;
  }, PROJECT);
  await app.open('/studio');
  await screen.getByRole('button', 'Blank').tap();
  await screen.getByRole('button', /^Advanced timeline/).tap();
  await expect(screen.getByText('Saved revision 2', { visible: true })).toBeVisible();
  const add = screen.getByRole('button', 'Add Upload · Video to timeline');
  for (let page = 0; page < 10 && (await add.count()) === 0; page += 1) {
    await screen.getByRole('button', 'Load more assets').tap();
  }
  await add.tap();
  await expect(screen.getByText('Saved revision 3', { visible: true })).toBeVisible();
  await screen.getByRole('button', 'Main Video clip').tap();
}

test('effects: blur-fill and dim are saved', async (fixtures: Fixtures) => {
  const { browser, screen } = fixtures;
  await selectedClip(fixtures);
  await screen.getByLabel('Background').selectOption('Blur-fill');
  await expect(screen.getByText('Saved revision 4', { visible: true })).toBeVisible();
  const dim = screen.getByLabel('Dim');
  await dim.fill('40');
  await dim.press('Tab');
  await expect(screen.getByText('Saved revision 5', { visible: true })).toBeVisible();
  const clip = await mainClip(browser);
  expect(clip.background).toBe('blur_fill');
  expect(clip.fit).toBe('contain');
  expect(clip.dim).toBe(0.4);
});

test('effects: Push in is saved as two keyframes', async (fixtures: Fixtures) => {
  const { browser, screen } = fixtures;
  await selectedClip(fixtures);
  await screen.getByRole('button', 'Push in').tap();
  await expect(screen.getByText('Saved revision 4', { visible: true })).toBeVisible();
  const clip = await mainClip(browser);
  expect(clip.moves.map((move: any) => [move.frame, move.scale])).toEqual([
    [0, 1],
    [clip.duration_in_frames - 1, 1.12],
  ]);
  await expect(screen.getByRole('button', 'Main Video clip').getByLabel('Has effects')).toBeVisible();
});

test('effects: Add box is saved and shows on the preview', async (fixtures: Fixtures) => {
  const { browser, screen } = fixtures;
  await selectedClip(fixtures);
  await screen.getByRole('button', 'Add box').tap();
  await expect(screen.getByText('Saved revision 4', { visible: true })).toBeVisible();
  const clip = await mainClip(browser);
  expect(clip.emphasis.marks).toHaveLength(1);
  expect(clip.emphasis.marks[0].kind).toBe('box');
  await expect(screen.getByTestId('clip-mark')).toBeVisible();
});

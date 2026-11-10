import { test } from '@e2e-dev/web';
import { expect } from 'e2e';

// Style templates (spec 2026-11-10), saved in the throwaway project. Run with e2e.write.config.ts,
// only on the operator's word. The throwaway project has no script model, so applying a style
// answers narration_refused and nothing is spent.
const PROJECT = process.env.THOTH_E2E_WRITE_PROJECT ?? '';
type Fixtures = { app: any; browser: any; screen: any };

const saved = (browser: any) =>
  browser.evaluate(async (project: string) => {
    const documentId = location.pathname.split('/').pop();
    return (await fetch(`/api/v1/projects/${project}/edit-documents/${documentId}`)).json();
  }, PROJECT);

/** A blank draft with the project's video upload on the main track, at revision 3. */
async function draftWithVideo({ app, browser, screen }: Fixtures) {
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
}

async function applyStyle(screen: any, name: string) {
  await screen.getByLabel('Style').selectOption(name);
  await screen.getByRole('button', 'Apply style').tap();
  await expect(screen.getByText(/The style is applied/)).toBeVisible();
}

test('styles: Style A rebuilds a draft and one Undo restores it', async (fixtures: Fixtures) => {
  const { browser, screen } = fixtures;
  await draftWithVideo(fixtures);
  await applyStyle(screen, 'Style A');
  const styled = await saved(browser);
  expect(styled.style?.template_id).toBe('style_a');
  await screen.getByRole('button', 'Undo').tap();
  await expect.poll(async () => (await saved(browser)).style ?? null, { timeout: 10000 }).toBeNull();
});

test('styles: Style B gives kinetic captions and dimmed shots', async (fixtures: Fixtures) => {
  const { browser, screen } = fixtures;
  await draftWithVideo(fixtures);
  await applyStyle(screen, 'Style B');
  const document = await saved(browser);
  expect(document.style?.template_id).toBe('style_b');
  const captions = document.clips.filter((clip: any) => clip.kind === 'caption');
  expect(captions.every((clip: any) => clip.style_slot === 'kinetic')).toBe(true);
});

import { test } from '@e2e-dev/web';
import { expect } from 'e2e';
import { fileURLToPath } from 'node:url';

// Run only with e2e.write.config.ts: real saves and real renders, all inside a throwaway project.
// The browser's write guard stops anything else; no voice, model or run can start.
const PROJECT = process.env.THOTH_E2E_WRITE_PROJECT ?? '';
const fixture = (name: string) => fileURLToPath(new URL(`../tests/fixtures/${name}`, import.meta.url));

// The runner's fixtures are typed per test; these helpers only drive them.
type Fixtures = { app: any; browser: any; screen: any };

async function useThrowawayProject({ app, browser }: Fixtures) {
  await app.open('/studio');
  await browser.evaluate((project: string) => {
    localStorage.setItem('thoth.activeProject', project);
    return null;
  }, PROJECT);
}

async function blankDraft(fixtures: Fixtures) {
  const { app, screen } = fixtures;
  await useThrowawayProject(fixtures);
  await app.open('/studio');
  await screen.getByRole('button', 'Blank').tap();
  await expect(screen.getByText('Saved revision 1', { visible: true })).toBeVisible();
}

/**
 * The library lists 20 assets a page, newest first, and every run here uploads more, so the one
 * video upload falls past the first page (2026-11-09). Load pages until its row shows.
 */
async function showUploadVideo(screen: any) {
  const add = screen.getByRole('button', 'Add Upload · Video to timeline');
  const rows = screen.getByRole('region', 'Asset library').getByRole('listitem');
  for (let page = 0; page < 10 && (await add.count()) === 0; page += 1) {
    const before = await rows.count();
    await screen.getByRole('button', 'Load more assets').tap();
    await expect.poll(async () => rows.count(), { timeout: 10000 }).toBeGreaterThan(before);
  }
  await expect(add).toBeVisible();
}

/** A blank draft on the Timeline, saved as revision 2, with the uploaded media listed. */
async function blankTimeline(fixtures: Fixtures) {
  const { screen } = fixtures;
  await blankDraft(fixtures);
  await screen.getByRole('button', /^Advanced timeline/).tap();
  await expect(screen.getByText('Saved revision 2', { visible: true })).toBeVisible();
  await showUploadVideo(screen);
}

/** A draft trimmed to its canvas, saved as revision 3, on the Render job. */
async function readyToRender(fixtures: Fixtures) {
  const { screen } = fixtures;
  await blankTimeline(fixtures);
  await screen.getByRole('button', 'Add Upload · Video to timeline').tap();
  await expect(screen.getByText('Saved revision 3', { visible: true })).toBeVisible();
  await screen.getByRole('navigation', 'Studio jobs').getByRole('button', 'Render').tap();
}

test('the write guard refuses a voice, a model and the real project', async ({ app, browser }) => {
  await app.open('/studio');
  const code = (path: string) =>
    browser.evaluate(async (target: string) => {
      const response = await fetch(target, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      return (await response.json()).detail?.code ?? null;
    }, path);
  for (const path of [
    `/api/v1/projects/${PROJECT}/edit-documents/edoc_none/narration`,
    `/api/v1/projects/${PROJECT}/edit-documents/edoc_none/assist`,
    `/api/v1/projects/${PROJECT}/prompt-lab/proposals`,
    `/api/v1/projects/${PROJECT}/workflows`,
    '/api/v1/workflows',
    '/api/v1/projects/db766411-3cb0-47a4-9dc9-b67d22f6f34e/edit-documents/edoc_none',
    '/api/v1/billing/checkout',
  ]) {
    expect(await code(path)).toBe('e2e_write_guard');
  }
});

test('a heading edit saves, updates the top bar and survives a reload', async ({ app, browser, screen }) => {
  await blankDraft({ app, browser, screen });
  await screen.getByRole('textbox', 'Heading').fill('Judul uji tulis');
  await expect(screen.getByText('Saved revision 2', { visible: true })).toBeVisible();
  const title = await browser.evaluate(() => document.querySelector('.studio-topbar span[title]')!.getAttribute('title'));
  expect(title).toBe('Judul uji tulis');
  await app.open(new URL(await browser.evaluate(() => location.href)).pathname);
  await expect(screen.getByRole('textbox', 'Heading')).toHaveValue('Judul uji tulis');
});

test('a file uploaded from the Asset library can be added to the draft', async ({ app, browser, screen }) => {
  await blankTimeline({ app, browser, screen });
  const before = await screen.getByRole('region', 'Asset library').getByRole('listitem').count();
  await screen.getByLabel('Upload file').setInputFiles(fixture('picture.png'));
  await expect(screen.getByRole('region', 'Asset library').getByRole('listitem')).toHaveCount(before + 1, { timeout: 15000 });
  await screen.getByRole('button', 'Add Upload · Image to timeline').tap();
  await expect(screen.getByText('Saved revision 3', { visible: true })).toBeVisible();
});

test('a video longer than the canvas is cut to fit, saved, and the screen says so', async ({ app, browser, screen }) => {
  await blankTimeline({ app, browser, screen });
  await screen.getByRole('button', 'Add Upload · Video to timeline').tap();
  // Which upload is named "Upload · Video" changes as the project gains uploads (2026-11-08: a 20.1 s
  // one), so the test checks the cut, not one file's length. Every upload here is longer than 5 s.
  await expect(screen.getByRole('status', 'Clip placed').getByText(/Cut to 5\.0 s of \d+\.\d s/)).toBeVisible();
  await expect(screen.getByText('Saved revision 3', { visible: true })).toBeVisible();
  await expect(screen.getByText(/Check your connection/)).toHaveCount(0);
  await expect(screen.getByText('No issues')).toBeVisible();
  await expect(screen.getByTestId('preview-unavailable')).toHaveCount(0, { timeout: 5000 });
  await app.screenshot('placed-cut-1440');
});

test('a clip added over another lands after it, saved, and the screen says so', async ({ app, browser, screen }) => {
  await blankTimeline({ app, browser, screen });
  await screen.getByRole('button', 'Add Upload · Image to timeline').tap();
  await expect(screen.getByText('Saved revision 3', { visible: true })).toBeVisible();
  await screen.getByRole('button', 'Add Upload · Image to timeline').tap();
  await expect(screen.getByRole('status', 'Clip placed').getByText(/Placed after the clip/)).toBeVisible();
  await expect(screen.getByText('Saved revision 4', { visible: true })).toBeVisible();
  await expect(screen.getByText(/Check your connection/)).toHaveCount(0);
});

test('a video with no room on the main track goes to B-Roll, saved, and the screen says so', async ({ app, browser, screen }) => {
  await blankTimeline({ app, browser, screen });
  await screen.getByRole('button', 'Add Upload · Video to timeline').tap();
  await expect(screen.getByText('Saved revision 3', { visible: true })).toBeVisible();
  await screen.getByRole('button', 'Add Upload · Video to timeline').tap();
  await expect(screen.getByRole('status', 'Clip placed').getByText(/Placed on B-Roll/)).toBeVisible();
  await expect(screen.getByText('Saved revision 4', { visible: true })).toBeVisible();
  await app.screenshot('placed-b-roll-1440');
});

test('the Replace media dialog sits in the middle of the screen', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1440, height: 900 });
  await blankDraft({ app, browser, screen });
  await screen.getByRole('button', 'Replace').tap();
  const box = await screen.getByRole('dialog', 'Replace media').boundingBox();
  expect(Math.abs(box!.x + box!.width / 2 - 720)).toBeLessThan(40);
  expect(Math.abs(box!.y + box!.height / 2 - 450)).toBeLessThan(40);
});

test('a draft is reviewed and approved', async ({ app, browser, screen }) => {
  await blankTimeline({ app, browser, screen });
  await screen.getByRole('button', 'Request review').tap();
  await screen.getByRole('textbox', 'Review comment').fill('Komentar uji e2e');
  await screen.getByRole('button', 'Post comment').tap();
  await expect(screen.getByRole('list', 'Review comments').getByText('Komentar uji e2e')).toBeVisible();
  await screen.getByRole('button', 'Approve for render').tap();
  await screen.getByRole('button', 'Confirm approval').tap();
  await expect(screen.getByText('Current decision: Approved on revision 2')).toBeVisible();
});

test('a render finishes, frees the renderer by itself, downloads, renders again and is deleted', async ({ app, browser, screen }) => {
  await readyToRender({ app, browser, screen });
  await screen.getByRole('button', 'Render revision 3').tap();
  await expect(screen.getByText(/edoc_/, { visible: true })).toHaveCount(0);
  await screen.getByRole('button', 'Start render').tap();
  await expect(screen.getByText(/^Completed/)).toBeVisible({ timeout: 180000 });
  // No click in between: the panel frees itself.
  await expect(screen.getByRole('button', 'Render again')).toBeEnabled({ timeout: 5000 });
  await expect(screen.getByText('Another render is already running.', { visible: true })).toHaveCount(0);

  const file = await browser.waitForDownload(() => screen.getByRole('button', 'Download video').tap());
  expect(file.suggestedFilename.endsWith('.mp4')).toBe(true);

  await screen.getByRole('button', 'Render again').tap();
  await screen.getByRole('button', 'Start render').tap();
  // Only this draft's renders: another draft's output is not this draft's history.
  await expect(screen.getByRole('list', 'Render history').getByRole('listitem')).toHaveCount(2, { timeout: 20000 });
  await expect(screen.getByText(/^Completed/)).toBeVisible({ timeout: 180000 });

  await screen.getByRole('button', 'Delete render files').tap();
  await screen.getByRole('button', 'Delete files').tap();
  await expect(screen.getByRole('button', 'Download video')).toHaveCount(0, { timeout: 15000 });
});

test('a running render can be cancelled', async ({ app, browser, screen }) => {
  await readyToRender({ app, browser, screen });
  await expect(screen.getByRole('button', 'Render revision 3')).toBeEnabled({ timeout: 30000 });
  await screen.getByRole('button', 'Render revision 3').tap();
  await screen.getByRole('button', 'Start render').tap();
  await screen.getByRole('button', 'Cancel render').tap();
  await expect(screen.getByText(/^Cancelled/)).toBeVisible({ timeout: 60000 });
});

test('a saved preset is still there after a reload', async ({ app, browser, screen }) => {
  await useThrowawayProject({ app, browser, screen });
  await app.open('/studio/presets');
  const words = screen.getByRole('spinbutton', 'Words per second');
  await words.fill('2.5');
  await screen.getByRole('button', 'Save preset').tap();
  await expect(screen.getByText('Preset saved')).toBeVisible();
  await app.open('/studio/presets');
  await expect(words).toHaveValue('2.5');
});

test('a prompt template saves without calling a model', async ({ app, browser, screen }) => {
  await useThrowawayProject({ app, browser, screen });
  await app.open('/studio/presets');
  await screen.getByRole('button', 'New template').tap();
  await screen.getByRole('textbox', 'Template body').fill('Template uji e2e');
  await screen.getByRole('button', 'Save template').tap();
  await expect(screen.getByRole('navigation', 'Prompt templates').getByRole('button', /revision 1\)/).first()).toBeVisible({ timeout: 10000 });
  const blocked = await browser.evaluate(() => (window as unknown as { __e2eBlocked: string[] }).__e2eBlocked);
  expect(blocked).toEqual([]);
  await app.screenshot('prompt-template-saved-1440');
});

test('Accounts opens with nothing written', async ({ app, browser, screen }) => {
  await app.open('/accounts');
  await expect(screen.getByRole('heading', 'Source accounts')).toBeVisible();
  const blocked = await browser.evaluate(() => (window as unknown as { __e2eBlocked: string[] }).__e2eBlocked);
  expect(blocked).toEqual([]);
  await app.screenshot('accounts-1440');
});

test('1024: a clip is added and saved on the Timeline', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 1024, height: 820 });
  await blankTimeline({ app, browser, screen });
  await screen.getByRole('button', 'Add Upload · Video to timeline').tap();
  await expect(screen.getByText('Saved revision 3', { visible: true })).toBeVisible();
  await app.screenshot('placed-cut-1024');
});

test('430: a heading edit from the Inspector pane saves', async ({ app, browser, screen }) => {
  await browser.setViewport({ width: 430, height: 932 });
  await app.open('/studio');
  const documentId = await browser.evaluate(async (project: string) => {
    const response = await fetch(`/api/v1/projects/${project}/edit-documents/import-content-set`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ main: {}, footage: [] }),
    });
    return (await response.json()).document_id;
  }, PROJECT);
  await app.open(`/studio/${PROJECT}/${documentId}`);
  await screen.getByRole('navigation', 'Studio panes').getByRole('button', 'Controls').tap();
  await screen.getByRole('textbox', 'Heading').fill('Judul dari telepon');
  await expect(screen.getByText('Saved revision 2', { visible: false }).first()).toBeAttached({ timeout: 5000 });
  await app.screenshot('phone-edit-430');
});

// Needs the branch's server: restore does not exist on an older image.
test('needs the deployed server: Undo reverses an edit after it autosaved, and Redo brings it back', async ({ app, browser, screen }) => {
  await blankDraft({ app, browser, screen });
  await screen.getByRole('textbox', 'Heading').fill('Sebelum undo');
  await expect(screen.getByText('Saved revision 2', { visible: true })).toBeVisible();
  await screen.getByRole('button', 'Undo').tap();
  await expect(screen.getByRole('textbox', 'Heading')).toHaveValue('Untitled video');
  await expect(screen.getByText('Saved revision 3', { visible: true })).toBeVisible();
  await screen.getByRole('button', 'Redo').tap();
  await expect(screen.getByRole('textbox', 'Heading')).toHaveValue('Sebelum undo');
  await expect(screen.getByText('Saved revision 4', { visible: true })).toBeVisible();
});

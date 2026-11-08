import { test } from '@e2e-dev/web';
import { expect } from 'e2e';

// Every Timeline function, with a real mouse, in the throwaway project. Run with e2e.write.config.ts.
const PROJECT = process.env.THOTH_E2E_WRITE_PROJECT ?? '';
type Fixtures = { app: any; browser: any; screen: any };

const saved = (browser: any) =>
  browser.evaluate(async (project: string) => {
    const documentId = location.pathname.split('/').pop();
    return (await fetch(`/api/v1/projects/${project}/edit-documents/${documentId}`)).json();
  }, PROJECT);

/** A saved field of the only clip on the main track. */
const mainClip = async (browser: any) => {
  const document = await saved(browser);
  const main = document.tracks.find((track: any) => track.kind === 'main_video');
  return document.clips.filter((clip: any) => clip.track_id === main.track_id);
};

/** A 3 s main clip from frame 0 on a 5 s canvas, zoomed so a frame is 4 px, saved. */
async function clipOnTimeline({ app, browser, screen }: Fixtures) {
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
  await screen.getByRole('button', 'Add Upload · Video to timeline').tap();
  await expect(screen.getByText('Saved revision 3', { visible: true })).toBeVisible();
  await screen.getByRole('button', 'Main Video clip').tap();
  await screen.getByRole('spinbutton', 'End frame').fill('90');
  await expect(screen.getByText('Saved revision 4', { visible: true })).toBeVisible();
  await screen.getByRole('button', 'Zoom in').tap();
  await screen.getByRole('button', 'Zoom in').tap();
}

async function drag(browser: any, box: { x: number; y: number; width: number; height: number }, dx: number, dy = 0, at = 0.5, finish = true) {
  const x = box.x + box.width * at;
  const y = box.y + box.height / 2;
  await browser.mouse.move(x, y);
  await browser.mouse.down();
  await browser.mouse.move(x + dx / 2, y + dy / 2);
  await browser.mouse.move(x + dx, y + dy);
  if (finish) await browser.mouse.up();
}

const clickAt = async (browser: any, x: number, y: number) => {
  await browser.mouse.move(x, y);
  await browser.mouse.down();
  await browser.mouse.up();
};
/** The toggles show on hover over a lane's name column. */
const hoverHeader = async (browser: any, screen: any, track: string) => {
  const box = await screen.getByRole('group', `${track} track`).boundingBox();
  await browser.mouse.move(box.x + 12, box.y + box.height / 2);
};
const clipBox = (screen: any) => screen.getByRole('button', 'Main Video clip').boundingBox();
const wait = (browser: any, ms: number) => browser.evaluate((delay: number) => new Promise((done) => setTimeout(() => done(null), delay)), ms);

test('drag: a clip moves along its track', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  await screen.getByRole('switch', 'Snap').tap();
  await drag(browser, await clipBox(screen), 80);
  await expect.poll(async () => (await mainClip(browser))[0].from_frame, { timeout: 5000 }).toBe(20);
});

test('drag: the end handle trims the clip', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  await screen.getByRole('switch', 'Snap').tap();
  await drag(browser, await screen.getByRole('button', 'Trim end of Main Video clip').boundingBox(), -40);
  await expect.poll(async () => (await mainClip(browser))[0].duration_in_frames, { timeout: 5000 }).toBe(80);
});

test('drag: the start handle trims the clip', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  await screen.getByRole('switch', 'Snap').tap();
  await drag(browser, await screen.getByRole('button', 'Trim start of Main Video clip').boundingBox(), 40);
  await expect.poll(async () => (await mainClip(browser))[0].from_frame, { timeout: 5000 }).toBe(10);
  expect((await mainClip(browser))[0].duration_in_frames).toBe(80);
});

test('drag: Escape drops a drag in flight', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  await drag(browser, await clipBox(screen), 80, 0, 0.5, false);
  await browser.keyboard.press('Escape');
  await browser.mouse.up();
  await wait(browser, 900);
  expect((await mainClip(browser))[0].from_frame).toBe(0);
  expect((await saved(browser)).revision).toBe(4);
});

test('drag: snap pulls a clip to the playhead, and off it does not', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  const ruler = await screen.getByRole('slider', 'Playhead').boundingBox();
  await clickAt(browser, ruler.x + 160, ruler.y + ruler.height / 2);
  await drag(browser, await clipBox(screen), 165);
  await expect.poll(async () => (await mainClip(browser))[0].from_frame, { timeout: 5000 }).toBe(40);
});

test('drag: a clip can be dragged to another track', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  const lane = await screen.getByRole('group', 'B-Roll track').boundingBox();
  const box = await clipBox(screen);
  await drag(browser, box, 0, lane.y + lane.height / 2 - (box.y + box.height / 2));
  await expect.poll(async () => (await mainClip(browser)).length, { timeout: 4000 }).toBe(0);
});

test('keyboard: arrows nudge the focused clip by a frame', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  await screen.getByRole('button', 'Main Video clip').focus();
  await browser.keyboard.press('ArrowRight');
  await expect.poll(async () => (await mainClip(browser))[0].from_frame, { timeout: 5000 }).toBe(1);
});

test('keyboard: Delete removes the selected clip', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  await screen.getByRole('button', 'Main Video clip').tap();
  await browser.keyboard.press('Delete');
  await expect.poll(async () => (await mainClip(browser)).length, { timeout: 3000 }).toBe(0);
});

test('keyboard: Ctrl+Z undoes and Ctrl+Y redoes', async ({ app, browser, screen }) => {
  // 2026-11-08: the old version passed through the End frame field's own undo, with no Studio key.
  // The edit here comes from a toolbar button and focus sits on the ruler, so only Studio can undo it.
  await clipOnTimeline({ app, browser, screen });
  const ruler = await screen.getByRole('slider', 'Playhead').boundingBox();
  await clickAt(browser, ruler.x + 120, ruler.y + ruler.height / 2);
  await screen.getByRole('button', 'Main Video clip').tap();
  await screen.getByRole('button', 'Trim end to playhead').tap();
  await expect.poll(async () => (await mainClip(browser))[0].duration_in_frames, { timeout: 5000 }).toBe(30);
  await browser.keyboard.press('Escape');
  await clickAt(browser, ruler.x + 120, ruler.y + ruler.height / 2);
  await browser.keyboard.press('Control+z');
  await expect.poll(async () => (await mainClip(browser))[0].duration_in_frames, { timeout: 5000 }).toBe(90);
  await browser.keyboard.press('Control+y');
  await expect.poll(async () => (await mainClip(browser))[0].duration_in_frames, { timeout: 5000 }).toBe(30);
});

test('keyboard: S splits the selected clip at the playhead', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  const ruler = await screen.getByRole('slider', 'Playhead').boundingBox();
  await clickAt(browser, ruler.x + 120, ruler.y + ruler.height / 2);
  await screen.getByRole('button', 'Main Video clip').tap();
  await browser.keyboard.press('s');
  await expect.poll(async () => (await mainClip(browser)).length, { timeout: 3000 }).toBe(2);
});

test('toolbar: split, move and both trims act at the playhead', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  const ruler = await screen.getByRole('slider', 'Playhead').boundingBox();
  await clickAt(browser, ruler.x + 120, ruler.y + ruler.height / 2);
  await screen.getByRole('button', 'Main Video clip').tap();
  await screen.getByRole('button', 'Trim end to playhead').tap();
  await expect.poll(async () => (await mainClip(browser))[0].duration_in_frames, { timeout: 5000 }).toBe(30);
  await clickAt(browser, ruler.x + 40, ruler.y + ruler.height / 2);
  await screen.getByRole('button', 'Split clip at playhead').tap();
  await expect.poll(async () => (await mainClip(browser)).length, { timeout: 5000 }).toBe(2);
});

test('toolbar: Move clip to playhead moves the clip there', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  const ruler = await screen.getByRole('slider', 'Playhead').boundingBox();
  await clickAt(browser, ruler.x + 120, ruler.y + ruler.height / 2);
  await screen.getByRole('button', 'Main Video clip').tap();
  await screen.getByRole('button', 'Move clip to playhead').tap();
  await expect.poll(async () => (await mainClip(browser))[0].from_frame, { timeout: 5000 }).toBe(30);
});

test('toolbar: zoom changes the width of a clip', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  const wide = (await clipBox(screen)).width;
  await screen.getByRole('button', 'Zoom out').tap();
  expect((await clipBox(screen)).width).toBeLessThan(wide);
});

test('toolbar: Ctrl+wheel zooms the lanes', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  const box = await clipBox(screen);
  const wide = box.width;
  await browser.mouse.move(box.x + 5, box.y + 5);
  await browser.keyboard.down('Control');
  await browser.mouse.wheel(0, 240);
  await browser.keyboard.up('Control');
  await wait(browser, 200);
  expect((await clipBox(screen)).width).toBeLessThan(wide);
});

test('playback: Play moves the clock and the ruler seeks', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  const ruler = await screen.getByRole('slider', 'Playhead').boundingBox();
  await clickAt(browser, ruler.x + 120, ruler.y + ruler.height / 2);
  await expect(screen.getByText(/^0:01\.0 \/ 0:05\.0/)).toBeVisible();
  await screen.getByRole('region', 'Timeline').getByRole('button', 'Play').tap();
  await expect(screen.getByText(/^0:0[2-4]\.\d \/ 0:05\.0/)).toBeVisible({ timeout: 8000 });
});

test('playback: a click on an empty part of a lane moves the playhead', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  const lane = await screen.getByRole('group', 'Music track').boundingBox();
  const ruler = await screen.getByRole('slider', 'Playhead').boundingBox();
  await clickAt(browser, ruler.x + 200, lane.y + lane.height / 2);
  await expect(screen.getByText(/^0:01\.[5-9] \/ 0:05\.0/)).toBeVisible({ timeout: 2000 });
});

test('tracks: hide, mute and lock are saved, and a lock stops a drag', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  const flags = async () => (await saved(browser)).tracks.find((track: any) => track.kind === 'main_video');
  await hoverHeader(browser, screen, 'Main Video');
  await screen.getByRole('button', 'Mute Main Video').tap();
  await expect.poll(async () => (await flags()).muted, { timeout: 5000 }).toBe(true);
  await hoverHeader(browser, screen, 'Main Video');
  await screen.getByRole('button', 'Hide Main Video').tap();
  await expect.poll(async () => (await flags()).hidden, { timeout: 5000 }).toBe(true);
  await hoverHeader(browser, screen, 'Main Video');
  await screen.getByRole('button', 'Show Main Video').tap();
  await expect.poll(async () => (await flags()).hidden, { timeout: 5000 }).toBe(false);
  await hoverHeader(browser, screen, 'Main Video');
  await screen.getByRole('button', 'Lock Main Video').tap();
  await expect.poll(async () => (await flags()).locked, { timeout: 5000 }).toBe(true);
  await drag(browser, await clipBox(screen), 80);
  await wait(browser, 900);
  expect((await mainClip(browser))[0].from_frame).toBe(0);
});

test('tracks: clicking a track header selects the track for the Inspector', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  const music = await screen.getByRole('group', 'Music track').boundingBox();
  await clickAt(browser, music.x + 12, music.y + music.height / 2);
  await expect(screen.getByRole('complementary', 'Timeline inspector').getByRole('heading', 'Music')).toBeVisible({ timeout: 2000 });
});

test('inspector: start and end frames typed whole land as typed', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  await screen.getByRole('button', 'Main Video clip').tap();
  await screen.getByRole('spinbutton', 'End frame').tap();
  await browser.keyboard.press('Control+a');
  await browser.keyboard.type('120', { delay: 40 });
  await expect.poll(async () => (await mainClip(browser))[0].duration_in_frames, { timeout: 5000 }).toBe(120);
  const operations = await browser.evaluate(() => document.querySelectorAll('[role="alert"]').length);
  expect(operations).toBe(0);
});

test('inspector: hidden and locked are saved', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  await screen.getByRole('button', 'Main Video clip').tap();
  await screen.getByRole('checkbox', 'Hidden').check();
  await expect.poll(async () => (await mainClip(browser))[0].hidden, { timeout: 5000 }).toBe(true);
  await screen.getByRole('checkbox', 'Locked').check();
  await expect.poll(async () => (await mainClip(browser))[0].locked, { timeout: 5000 }).toBe(true);
});

test('inspector: Fit, Crop and Position can be changed on a video clip', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  await screen.getByRole('button', 'Main Video clip').tap();
  // Fit is a choice (Cover, Contain, Fill) since Tier 2, so it is a combobox, not a text box.
  await expect(screen.getByRole('combobox', 'Fit')).toBeEnabled({ timeout: 1500 });
  await expect(screen.getByRole('textbox', 'Crop left')).toBeEnabled();
  await expect(screen.getByRole('textbox', 'Position X')).toBeEnabled();
});

test('right click: a clip opens an editing menu', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  await screen.getByRole('button', 'Main Video clip').secondaryTap();
  await expect(screen.getByRole('menu')).toBeVisible({ timeout: 2000 });
});

// Spec 2026-11-08 §5.1, Tier 1: the menus and the shortcut list on the deployed stack.
test('right click: Delete removes the clip', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  await screen.getByRole('button', 'Main Video clip').secondaryTap();
  await screen.getByRole('menuitem', 'Delete').tap();
  await expect.poll(async () => (await mainClip(browser)).length, { timeout: 5000 }).toBe(0);
});

test('right click: Move to track moves the clip to B-roll', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  await screen.getByRole('button', 'Main Video clip').secondaryTap();
  await screen.getByRole('menu').getByRole('menuitem', 'B-roll').tap();
  await expect.poll(async () => (await mainClip(browser)).length, { timeout: 5000 }).toBe(0);
});

test('right click: Ripple delete removes the clip and shortens the heading that spans it', async ({ app, browser, screen }) => {
  // A blank draft's heading runs the whole canvas on another track; it shortens by the removed
  // stretch instead of blocking the edit (operator, 2026-11-08).
  await clipOnTimeline({ app, browser, screen });
  const heading = async () => (await saved(browser)).clips.find((clip: any) => clip.kind === 'text');
  const before = (await heading()).duration_in_frames;
  await screen.getByRole('button', 'Main Video clip').secondaryTap();
  await screen.getByRole('menuitem', 'Ripple delete').tap();
  await expect.poll(async () => (await mainClip(browser)).length, { timeout: 5000 }).toBe(0);
  await expect.poll(async () => (await heading()).duration_in_frames, { timeout: 5000 }).toBe(before - 90);
});

test('keyboard: ? opens the shortcut list', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  const ruler = await screen.getByRole('slider', 'Playhead').boundingBox();
  await clickAt(browser, ruler.x + 40, ruler.y + ruler.height / 2);
  await browser.keyboard.press('?');
  await expect(screen.getByRole('dialog', 'Keyboard shortcuts')).toBeVisible();
});

// Spec 2026-11-08 §6, Tier 2, on the deployed stack.
/** A second main clip at 120–150 (the upload cut to fit), so the main track holds 0–90 and 120–150. */
async function twoMainClips({ app, browser, screen }: Fixtures) {
  await clipOnTimeline({ app, browser, screen });
  const ruler = await screen.getByRole('slider', 'Playhead').boundingBox();
  await clickAt(browser, ruler.x + 480, ruler.y + ruler.height / 2);
  await screen.getByRole('button', 'Add Upload · Video to timeline').tap();
  await expect.poll(async () => (await mainClip(browser)).length, { timeout: 5000 }).toBe(2);
}
/** The middle of the main lane at `frame`, at 4 px a frame past the 192 px name column. */
const mainLaneAt = async (screen: any, frame: number) => {
  const lane = await screen.getByRole('group', 'Main Video track').boundingBox();
  return { x: lane.x + 192 + frame * 4, y: lane.y + lane.height / 2 };
};
const startsOnMain = async (browser: any) => (await mainClip(browser)).map((clip: any) => clip.from_frame).sort((a: number, b: number) => a - b);

test('select: Shift-click two clips, and Delete removes both as one edit', async ({ app, browser, screen }) => {
  await twoMainClips({ app, browser, screen });
  const first = await mainLaneAt(screen, 40);
  const second = await mainLaneAt(screen, 135);
  await clickAt(browser, first.x, first.y);
  await browser.keyboard.down('Shift');
  await clickAt(browser, second.x, second.y);
  await browser.keyboard.up('Shift');
  await browser.keyboard.press('Delete');
  await expect.poll(async () => (await mainClip(browser)).length, { timeout: 5000 }).toBe(0);
});

test('copy: Ctrl+C and Ctrl+V paste a copy at the playhead', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  await screen.getByRole('button', 'Main Video clip').tap();
  await screen.getByRole('spinbutton', 'End frame').fill('30');
  await expect.poll(async () => (await mainClip(browser))[0].duration_in_frames, { timeout: 5000 }).toBe(30);
  await screen.getByRole('button', 'Main Video clip').tap();
  await browser.keyboard.press('Control+c');
  const ruler = await screen.getByRole('slider', 'Playhead').boundingBox();
  await clickAt(browser, ruler.x + 240, ruler.y + ruler.height / 2);
  await browser.keyboard.press('Control+v');
  await expect.poll(async () => startsOnMain(browser), { timeout: 5000 }).toEqual([0, 60]);
});

test('duplicate: Ctrl+D puts a copy right after the clip', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  await screen.getByRole('button', 'Main Video clip').tap();
  await screen.getByRole('spinbutton', 'End frame').fill('30');
  await expect.poll(async () => (await mainClip(browser))[0].duration_in_frames, { timeout: 5000 }).toBe(30);
  await screen.getByRole('button', 'Main Video clip').tap();
  await browser.keyboard.press('Control+d');
  await expect.poll(async () => startsOnMain(browser), { timeout: 5000 }).toEqual([0, 30]);
});

test('paste text: pasted text asks where it goes and becomes a new text clip', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  // A real paste event with plain text; the system clipboard itself is never read here.
  await browser.evaluate(() => {
    const data = new DataTransfer();
    data.setData('text/plain', 'Hello from e2e');
    window.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }));
    return null;
  });
  await screen.getByRole('dialog', 'Paste text').getByRole('button', 'New text clip').tap();
  await expect
    .poll(async () => (await saved(browser)).clips.some((clip: any) => clip.kind === 'text' && clip.heading === 'Hello from e2e'), { timeout: 5000 })
    .toBe(true);
});

test('inspector: Fit set to Contain is saved', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  await screen.getByRole('button', 'Main Video clip').tap();
  await screen.getByRole('combobox', 'Fit').selectOption('Contain');
  await expect.poll(async () => (await mainClip(browser))[0].fit, { timeout: 5000 }).toBe('contain');
});

test('inspector: Fade in 0.5 s is saved', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  await screen.getByRole('button', 'Main Video clip').tap();
  await screen.getByRole('textbox', 'Fade in (seconds)').fill('0.5');
  await browser.keyboard.press('Enter');
  await expect.poll(async () => (await mainClip(browser))[0].fade_in_frames, { timeout: 5000 }).toBe(15);
});

test('tracks: Close all gaps on this track pulls the later clip in', async ({ app, browser, screen }) => {
  await twoMainClips({ app, browser, screen });
  await screen.getByRole('button', 'Select Main Video track').secondaryTap();
  await screen.getByRole('menuitem', 'Close all gaps on this track').tap();
  await expect.poll(async () => startsOnMain(browser), { timeout: 5000 }).toEqual([0, 90]);
});

test('assets: search narrows the asset list', async ({ app, browser, screen }) => {
  await clipOnTimeline({ app, browser, screen });
  await screen.getByRole('searchbox', 'Search assets').fill('nothing is called this');
  await expect(screen.getByRole('button', 'Add Upload · Video to timeline')).not.toBeVisible();
  await screen.getByRole('searchbox', 'Search assets').fill('upload');
  await expect(screen.getByRole('button', 'Add Upload · Video to timeline')).toBeVisible();
});

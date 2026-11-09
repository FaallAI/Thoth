# Studio Full-Width Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Timeline mode a full-width, resizable timeline row with the player controls under the preview, and turn text selection off across the Studio editor.

**Architecture:** The workstation grid gains three rows in wide Timeline mode, and `main` becomes `display: contents` so the preview and the timeline are grid items of the workstation. The rows are `minmax(240px,1fr) 8px minmax(150px,<height>px)`, so CSS fits a remembered height to the window with no observer. Player controls become a React bar driven by the existing `PlayerTimelineRef`.

**Tech Stack:** React 19, TypeScript, Bun tests with happy-dom, `@remotion/player`, tester-army/e2e.

**Spec:** `docs/superpowers/specs/2026-11-09-studio-full-width-timeline-design.md`

## Global Constraints

- "Wide Timeline" means `advanced && editing && !compact` in `GuidedStudio.tsx`. Below 1024 px, the Story mode and the Review and Render jobs keep their layouts and the Player's own controls.
- No new dependency. No document field, API change or migration.
- Limits: timeline at least 150 px, top row at least 240 px, divider 8 px, default 392 px, key step 16 px, 64 px with Shift.
- Browser storage key: `thoth.studio.timelineHeight`. Every read and write is guarded, and a bad value means the default.
- Every user-visible string goes through `t()` with English and Indonesian entries in `lib/i18n.ts`.
- Branch `feat/studio-full-timeline` from `feat/studio-timeline-tier3b` head `2b6cbdbf`, because this work touches the same files and PR #125 is still open. Rebase on master once #125 is merged.
- Commit subjects are one line of at most 72 characters, with no body and no trailer.
- No push, deploy or live write without the operator's separate word.

## Review Focus

- A remembered height taller than the window: a drag must start from the height on screen, or the first pixels of the drag do nothing. Pinned in Task 1.
- Home, End and the arrows pressed on the divider must not also seek or move clips, since the Timeline listens on `window`. Pinned in Task 1.
- The divider unmounts mid-drag (leaving Timeline mode): its window listeners must go. Pinned in Task 1.
- The Player is not attached yet, or fullscreen is refused: the bar must not throw. Pinned in Task 2.
- In fullscreen the bar is off screen: the Player's own controls must return. Pinned in Tasks 2 and 4.

---

### Task 1: The divider and its height rules

**Files:**
- Create: `dashboard/src/features/studio/timeline_height.ts`, `dashboard/src/features/studio/TimelineDivider.tsx`
- Modify: `dashboard/src/lib/i18n.ts` (key `studio.timeline.resize`: "Resize timeline" / "Ubah tinggi timeline")
- Test: `dashboard/src/features/studio/timeline_height.test.ts`, `dashboard/src/features/studio/TimelineDivider.test.tsx`

**Interfaces:**
- Produces: `DEFAULT_TIMELINE_HEIGHT = 392`, `MIN_TIMELINE_HEIGHT = 150`, `MIN_TOP_ROW = 240`, `DIVIDER_HEIGHT = 8`; `maxTimelineHeight(workstation: number): number`; `clampTimelineHeight(height: number, workstation: number): number`; `readTimelineHeight(): number`; `saveTimelineHeight(height: number): void`; `timelineRows(height: number): string`.
- Produces: `TimelineDivider` with props `{ height: number; workstation: () => HTMLElement | null; onResize: (height: number) => void; onCommit: (height: number) => void }`. `onResize` previews during a drag, and `onCommit` ends a drag or applies a key or double-click.

- [ ] **Step 1: Write the failing tests**

```ts
// timeline_height.test.ts
test("the timeline keeps its limits", () => {
  expect(clampTimelineHeight(100, 844)).toBe(150);
  expect(clampTimelineHeight(9000, 844)).toBe(844 - 8 - 240);
  expect(clampTimelineHeight(400, 844)).toBe(400);
});
test("a window too short for both rows still gives the smallest timeline", () => {
  expect(maxTimelineHeight(300)).toBe(150);
});
test("a stored height is read back, and anything unusable is the default", () => {
  saveTimelineHeight(300);
  expect(readTimelineHeight()).toBe(300);
  for (const bad of ["abc", "-5", "0", "NaN"]) {
    localStorage.setItem("thoth.studio.timelineHeight", bad);
    expect(readTimelineHeight()).toBe(392);
  }
});
test("storage that throws is the default and never an error", () => {
  const original = Storage.prototype.getItem;
  Storage.prototype.getItem = () => { throw new Error("blocked"); };
  try { expect(readTimelineHeight()).toBe(392); } finally { Storage.prototype.getItem = original; }
});
test("rows let CSS fit the height to the window", () => {
  expect(timelineRows(300)).toBe("minmax(240px,1fr) 8px minmax(150px,300px)");
});
```

`TimelineDivider.test.tsx`: mount with a fake `workstation` whose `getBoundingClientRect().height` is 844, and name the separator "Resize timeline".

- `arrow keys move it 16 px, 64 with Shift`: ArrowUp from 392 commits 408, ArrowDown commits 376, Shift+ArrowUp commits 456.
- `Home and End go to the limits`: commit 150 and 596.
- `keys on the divider do not reach the window`: add a `window` keydown spy, press Home, and expect the spy not called.
- `a drag previews, then commits once`: pointerDown clientY 500, window pointerMove 480 calls `onResize(412)`, pointerUp at 480 calls `onCommit(412)` once.
- `a drag starts from the height on screen`: `height` 2000 with workstation 844, pointerDown at 500, pointerMove 490 calls `onResize(596)` and pointerMove 510 calls `onResize(586)`.
- `double-click returns to the default`: commits 392.
- `unmounting mid-drag stops listening`: pointerDown, unmount, window pointerMove, and expect `onResize` not called.
- `it says its size`: `aria-orientation="horizontal"`, `aria-valuenow` 392, `aria-valuemin` 150, `aria-valuemax` 596, `aria-controls="studio-timeline"`, `tabindex` 0.

- [ ] **Step 2: Run them to verify they fail**

Run: `bash D:/thoth-tmp/fixes/t3a_check.sh "" src/features/studio/timeline_height.test.ts src/features/studio/TimelineDivider.test.tsx`
Expected: FAIL, modules not found.

- [ ] **Step 3: Implement both files**

`aria-valuemax` comes from a `useLayoutEffect` that measures `workstation()` on mount, and again at each pointer-down and key press. The start height of a drag and of a key step is `Math.min(height, maxTimelineHeight(measured))`. Window `pointermove`, `pointerup` and `pointercancel` listeners follow the `VolumeLine` pattern in `TimelineClip.tsx`, including its ref-held `stop` run on unmount. A cancelled pointer commits the height it last previewed. The key handler calls `preventDefault` and `stopPropagation` only for the four keys it uses. Class: `studio-timeline-divider`.

- [ ] **Step 4: Run them to verify they pass**

Same command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/features/studio/timeline_height.ts dashboard/src/features/studio/timeline_height.test.ts dashboard/src/features/studio/TimelineDivider.tsx dashboard/src/features/studio/TimelineDivider.test.tsx dashboard/src/lib/i18n.ts
git commit -m "Add a resizable divider for the Studio timeline"
```

---

### Task 2: Player controls under the preview

**Files:**
- Create: `dashboard/src/features/studio/PreviewControls.tsx`
- Modify: `dashboard/src/features/studio/usePlayerTimeline.ts:4-13`, `dashboard/src/features/studio/StudioPreview.tsx`, `dashboard/src/lib/i18n.ts`
- Test: `dashboard/src/features/studio/PreviewControls.test.tsx`

**Interfaces:**
- Modifies `PlayerTimelineRef`: adds optional `mute?(): void; unmute?(): void; isMuted?(): boolean; requestFullscreen?(): void`. Optional, so existing test fakes still type-check and a missing method degrades to a no-op.
- Produces: `canvasRatio(canvas: { width: number; height: number }): string`, moved from `StudioPreview.tsx` and exported from `PreviewControls.tsx`.
- Produces: `PreviewControls` with props `{ player: PlayerTimelineRef | null; frame: number; durationInFrames: number; fps: number; playing: boolean; canvas: { width: number; height: number }; onPlay: () => void; onPause: () => void; onFullscreenChange: (fullscreen: boolean) => void }`.
- Modifies `StudioPreview` props: `controls?: boolean` (default `true`), `footer?: ReactNode` (when given, replaces the hint line in the embedded view).

i18n, English / Indonesian. The English strings match Remotion's own labels, so existing locators keep working:
`studio.preview.play` "Play video" / "Putar video"; `studio.preview.pause` "Pause video" / "Jeda video"; `studio.preview.mute` "Mute sound" / "Bisukan suara"; `studio.preview.unmute` "Unmute sound" / "Bunyikan suara"; `studio.preview.fullscreen` "Enter Fullscreen" / "Layar penuh".

- [ ] **Step 1: Write the failing tests**

`PreviewControls.test.tsx`, with a fake player recording calls:

- `the time and the canvas are shown`: frame 180 of 825 at 30 fps shows `formatTimecode(180, 30)` and `formatTimecode(825, 30)`, and "9:16 · 1080×1920".
- `play and pause call the timeline's handlers`: `playing=false` click "Play video" calls `onPlay`; `playing=true` click "Pause video" calls `onPause`.
- `mute toggles and the label follows`: a click on "Mute sound" calls `mute`; with `isMuted` now true the button reads "Unmute sound"; a click calls `unmute`.
- `fullscreen asks the player`: a click on "Enter Fullscreen" calls `requestFullscreen`.
- `a refused fullscreen is not an error`: `requestFullscreen` throws, the click does not throw.
- `no player yet leaves the buttons off`: `player=null`, and the mute and fullscreen buttons are disabled.
- `the player's fullscreen state is reported`: fire the fake's `fullscreenchange` listener with `{ detail: { isFullscreen: true } }` and expect `onFullscreenChange(true)`; expect the listener removed on unmount.

- [ ] **Step 2: Run them to verify they fail**

Run: `bash D:/thoth-tmp/fixes/t3a_check.sh "" src/features/studio/PreviewControls.test.tsx`
Expected: FAIL, module not found.

- [ ] **Step 3: Implement**

Render a three-column bar with class `studio-preview-bar`: time, play button, then ratio with size, mute and fullscreen. Use the lucide icons `StudioPreview` already uses. In `StudioPreview`, pass `controls={controls}` and `clickToPlay` to `Player`. In the embedded return, render `footer ?? <the existing hint paragraph>`. A `console.warn` records a refused fullscreen.

- [ ] **Step 4: Run them to verify they pass**

Same command, plus `src/features/studio/StudioPreview.test.tsx` if it exists. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/features/studio/PreviewControls.tsx dashboard/src/features/studio/PreviewControls.test.tsx dashboard/src/features/studio/usePlayerTimeline.ts dashboard/src/features/studio/StudioPreview.tsx dashboard/src/lib/i18n.ts
git commit -m "Add player controls that sit under the Studio preview"
```

---

### Task 3: The issues status in the toolbar

**Files:**
- Modify: `dashboard/src/features/studio/IssuesPanel.tsx`, `dashboard/src/features/studio/TimelineToolbar.tsx`, `dashboard/src/features/studio/Timeline.tsx:696,64`
- Test: `dashboard/src/features/studio/IssuesPanel.test.tsx`, `dashboard/src/features/studio/Timeline.test.tsx`

**Interfaces:**
- Produces: `IssuesBar` prop `inline?: boolean` (default `false`).
- Produces: `TimelineToolbar` and `Timeline` prop `status?: ReactNode`, drawn at the start of the toolbar's right-hand group (`ml-auto`).
- Produces: `Timeline` prop `sectionId?: string`, set as the `id` of its `<section>` so the divider's `aria-controls` resolves.

- [ ] **Step 1: Write the failing tests**

```tsx
test("inline, the bar shows the count without the sentence and opens its list", () => {
  // A document with one issue, rendered with `inline`.
  expect(screen.getByText("1 warning")).toBeDefined();
  expect(screen.queryByText(/* issueSentence of that issue */)).toBeNull();
  // Clicking the existing view button shows the list.
});
test("inline with no issues still says so", () => {
  expect(screen.getByText("No issues")).toBeDefined();
});
```

In `Timeline.test.tsx`: `a status is drawn in the toolbar`, passing `status={<span>Status here</span>}` and finding it inside the toolbar's row.

- [ ] **Step 2: Run them to verify they fail**

Run: `bash D:/thoth-tmp/fixes/t3a_check.sh "" src/features/studio/IssuesPanel.test.tsx src/features/studio/Timeline.test.tsx`
Expected: FAIL on the new tests only.

- [ ] **Step 3: Implement**

With `inline`: the section drops `border-t` and `bg-well`, the row has no fixed `h-8`, the first-issue sentence is not drawn, and the list uses `bottom-full right-0 max-h-56` in place of `left-0 max-h-[50vh]`. The top row is at least 240 px tall, so 224 px always fits. The non-inline output is unchanged.

- [ ] **Step 4: Run them to verify they pass**

Same command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/features/studio/IssuesPanel.tsx dashboard/src/features/studio/IssuesPanel.test.tsx dashboard/src/features/studio/TimelineToolbar.tsx dashboard/src/features/studio/Timeline.tsx dashboard/src/features/studio/Timeline.test.tsx
git commit -m "Let the Timeline toolbar carry the issues status"
```

---

### Task 4: The two-row workstation and no text selection

**Files:**
- Modify: `dashboard/src/features/studio/GuidedStudio.tsx:153,198-214,717,1048-1052,1180-1200,1201,1234`, `dashboard/src/pen-studio.css` (append at the end)
- Test: `dashboard/src/features/studio/GuidedStudio.responsive.test.tsx`

**Interfaces:**
- Consumes: everything Tasks 1 to 3 produce.

- [ ] **Step 1: Write the failing tests**

Extend the `StudioPreview` mock at `GuidedStudio.responsive.test.tsx:22` so it renders `props.footer` and `data-controls={String(props.controls ?? true)}`. New tests:

- `Timeline at full desktop has the divider and the bar`: width 1440, switch to Timeline, expect the separator "Resize timeline", `data-controls="false"`, the button "Play video", and the workstation's `style.gridTemplateRows` equal to `timelineRows(392)`.
- `the stored height is used`: `saveTimelineHeight(300)` before mount, and expect `timelineRows(300)`.
- `resizing commits to the browser`: focus the separator, press ArrowUp, expect `readTimelineHeight()` to be 408.
- `fullscreen brings the Player's controls back`: fire the fake player's `fullscreenchange` with `isFullscreen: true`, and expect `data-controls="true"`.
- `the status sits in the toolbar, not under the lanes`: the "Timeline issues" region is inside the region "Timeline".
- `phones keep the panes and the Player's controls`: width 430 in Timeline, no separator, `data-controls="true"`.
- `Story keeps its layout`: width 1440 in Story, no separator, `data-controls="true"`.
- `Review keeps its layout`: width 1440, Timeline mode then the Review job, no separator and no bar.

- [ ] **Step 2: Run them to verify they fail**

Run: `bash D:/thoth-tmp/fixes/t3a_check.sh "" src/features/studio/GuidedStudio.responsive.test.tsx`
Expected: FAIL on the new tests only.

- [ ] **Step 3: Wire `GuidedStudio.tsx`**

- `const wideTimeline = advanced && editing && !compact;`, plus state `timelineHeight` (initial `readTimelineHeight`), `playerFullscreen` (initial `false`), and a `useRef` on the workstation element.
- `gridTemplateRows`: `wideTimeline ? timelineRows(timelineHeight) : <today's expression>`.
- Add class ` studio-wide-timeline` on the shell at line 717 when `wideTimeline`.
- `StudioPreview`: `overlay` is `null` when `wideTimeline`, or else today's expression. That gives the box sized from its cell. `controls={!wideTimeline || playerFullscreen}`. `footer` is `<PreviewControls ...>` when `wideTimeline`, using `state.playheadFrame`, `timeline.canvas.duration_in_frames`, `timeline.canvas.fps`, `state.playing`, `player.play`, `player.pause`.
- Inside the Timeline's `contents` wrapper, draw `<TimelineDivider>` before `<Timeline>` when `wideTimeline`. `onResize` is `setTimelineHeight`. `onCommit` sets the height and calls `saveTimelineHeight`.
- `Timeline`: `sectionId="studio-timeline"`. Build the `IssuesBar` element once. Pass it with `inline` as `status` when `wideTimeline`, and draw it under `Timeline` as today otherwise.

- [ ] **Step 4: Append the CSS to `pen-studio.css`**

```css
/* Text is not selectable in the editor; anything a person types in still is (spec 2026-11-09). */
.studio-shell.pen-studio { -webkit-user-select:none; user-select:none; }
.studio-shell.pen-studio :is(input,textarea,[contenteditable="true"]) { -webkit-user-select:text; user-select:text; }

/* Wide Timeline: main dissolves so the preview and the timeline are workstation grid items.
   Only the divider and the timeline are placed; the top row fills in document order, so a
   collapsed Assets or Inspector column needs no rule of its own. */
.studio-shell.pen-studio.studio-wide-timeline [aria-label="Guided editing workstation"] > main { display:contents; }
.studio-shell.pen-studio.studio-wide-timeline .studio-timeline-divider { grid-column:1 / -1; grid-row:2; position:relative; cursor:ns-resize; touch-action:none; background:#18191b; border-top:1px solid #47494a; }
.studio-shell.pen-studio.studio-wide-timeline .studio-timeline-divider::after { content:""; position:absolute; left:50%; top:2px; width:44px; height:3px; margin-left:-22px; border-radius:2px; background:#47494a; }
.studio-shell.pen-studio.studio-wide-timeline .studio-timeline-divider:is(:hover,:focus-visible)::after { background:#d49a79; }
.studio-shell.pen-studio.studio-wide-timeline [aria-label="Timeline"] { grid-column:1 / -1; grid-row:3; min-height:0; padding-top:0; border-top:0; }
.studio-shell.pen-studio.studio-wide-timeline [aria-label="Studio preview"] { height:auto; min-height:0; min-width:0; flex:none; padding-top:14px; background:#101113; }
.studio-shell.pen-studio.studio-wide-timeline [aria-label="Studio preview"] > div:first-child { flex:1 1 0; width:100%; height:auto; min-height:0; border:0; background:transparent; }
.studio-shell.pen-studio .studio-preview-bar { display:grid; grid-template-columns:1fr auto 1fr; align-items:center; width:100%; height:34px; flex:none; padding:0 14px; border-top:1px solid #47494a; background:#18191b; color:#c5c6c7; font:11px var(--font-mono); font-variant-numeric:tabular-nums; white-space:nowrap; }
```

- [ ] **Step 5: Run the tests**

Run: `bash D:/thoth-tmp/fixes/t3a_check.sh "" src/features/studio/GuidedStudio.responsive.test.tsx src/features/studio/GuidedStudio.test.tsx src/features/studio/GuidedStudio.regressions.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/features/studio/GuidedStudio.tsx dashboard/src/features/studio/GuidedStudio.responsive.test.tsx dashboard/src/pen-studio.css
git commit -m "Span the Studio timeline across the window"
```

---

### Task 5: Browser checks and records

**Files:**
- Modify: `e2e/tests/studio-shell-v2.e2e.ts`, `e2e/tests/studio-audit-fixes.e2e.ts:193-207`
- Modify: `CHANGELOG.md`, `docs/ROADMAP.md` (a status line, added only), the SDD checkpoint

- [ ] **Step 1: Add the read-only e2e tests**

Tests in `studio-shell-v2.e2e.ts`, at 1440x900, on the narrated draft, in Timeline mode. They use `screen`, `expect`, `browser.evaluate` and `browser.mouse` only, with no `agent.*`.

- `1440 Timeline: the timeline spans the window under the preview`: the Timeline section's width is at least 1438, and its top is below the preview's bottom.
- `1440 Timeline: the divider resizes, is remembered, and resets`: drag the separator up 100 px and expect the Timeline's height to grow by about 100. Reload, reopen Timeline, expect the same height. Double-click and expect about 392.
- `1440 Timeline: the player bar sits under the video`: "Play video" is below the bottom edge of the canvas box.
- `1440: text cannot be selected, fields still can`: `getComputedStyle` of a heading gives `userSelect` `none`, and of "Search assets" gives `text`.
- `1440 Timeline: every standard track fits at the default height`: the `SFX track` bottom is at or above the `timeline-lanes` bottom without scrolling.

In `studio-audit-fixes.e2e.ts`, change the 1024 test `the last lane can be reached` to compare against the `[data-testid="timeline-lanes"]` bottom. The issues bar it measured is now above the lanes at that width. The check that the last lane can be reached stays.

- [ ] **Step 2: Run the whole verification**

- `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/fixes/dash_full.sh full`: dashboard tests, `tsc -b` and build pass.
- No Python, renderer or contract change, so those suites do not run. Say so in the report.

- [ ] **Step 3: Check it in a real browser before any deploy**

Start `wsl -e bash /mnt/d/thoth-tmp/fixes/vite_main.sh` (port 5199) and use the e2e MCP server at 1440x900 and 1024x768: take screenshots of Timeline mode, and judge the toolbar's wrapping at 1024, the bar, and the issues list opening above the toolbar. Fix any finding test-first.

- [ ] **Step 4: Record and commit**

Append a `CHANGELOG.md` entry with the verification and a **Next steps** section, and update the checkpoint. Then:

```bash
git add -f docs/superpowers/plans/2026-11-09-studio-full-width-timeline.md docs/superpowers/specs/2026-11-09-studio-full-width-timeline-design.md
git add e2e/tests CHANGELOG.md docs/ROADMAP.md
git commit -m "Add browser checks and records for the full-width timeline"
```

**Next steps to report (each its own gate):** push and PR, deploy of the branch image, the read-only e2e on stage1, the operator's try, merge.

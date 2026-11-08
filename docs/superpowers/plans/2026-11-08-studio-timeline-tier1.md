# Studio Timeline Tier 1 (editor basics) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Studio the editing grammar of common editors: keys, right-click menus in Timeline and Story, drag to another track, click-to-seek, Ctrl+wheel zoom, readable names and a working Replace media.

**Architecture:** One shared `ContextMenu` (component plus hook) serves both modes. Edits are pure helpers in `timeline_edits.ts` that return `EditDocumentOperation[]`, committed through the existing `commit_operations` action, so one user action is one undo step. Keys live in two places: Studio-wide keys (undo, redo, the shortcut list) in a `useStudioShortcuts` hook in `GuidedStudio`, and Timeline keys in `Timeline.tsx`. Both are guarded by `isTypingTarget`. No new server operation.

**Tech Stack:** React 19 + TypeScript, Bun tests with Testing Library (`dashboard/`), lucide-react icons, tester-army/e2e (`e2e/`), pytest (one server guard test).

**Spec:** `docs/superpowers/specs/2026-11-08-studio-timeline-track-design.md` (sections 5.1 to 5.4).
**Research:** `docs/research/2026-11-08-studio-timeline-editor-research.md`.

## Global Constraints

- Every edit is a typed operation. One user action is one `commit_operations` dispatch, so it is one undo step.
- No menu entry or key starts narration, re-voice, Assist, a proposal or a render.
- Keys act only when the event target is not a typing target (`input` other than checkbox, radio, button and range; `textarea`; `select`; `[contenteditable]`).
- Locked clips and locked tracks: every edit entry and key that would change them is disabled, or does nothing.
- Every new string exists in `en` and `id` in `dashboard/src/lib/i18n.ts`. The `id` object is typed `Messages`, so a missing key fails `tsc`.
- Shortcuts (spec 5.1):
  - Delete or Backspace: delete. Shift+Delete: ripple delete. S: split.
  - Space: play or pause. Home and End: start and end.
  - Left and Right: one frame. Shift with Left or Right: one second (as the ruler does today).
  - Ctrl+wheel, Ctrl+=, Ctrl+- and Ctrl+0: zoom, with Ctrl+0 fitting the canvas.
  - Ctrl+Z: undo. Ctrl+Y or Ctrl+Shift+Z: redo.
  - Escape: close, cancel, then clear the selection. ? or Ctrl+/: the shortcut list.
- Menus are `role="menu"` with `role="menuitem"` entries; a disabled entry has `aria-disabled="true"` and its reason in `title`.
- Commits: one subject line, `git commit -m "<subject>"`, no body, no trailer (`AGENTS.md`).
- Verification per task: `bash D:/thoth-tmp/fixes/dash_test.sh <test paths>` in WSL. Before the PR: `dash_full.sh full` (all dashboard tests, `tsc -b` and build) and `make test T=tests/domain/test_timeline_operations.py`.

## Review Focus

1. **A key pressed while typing in a field.** Delete in the heading box, S in caption text, Ctrl+Z in an Inspector number field must do the field's own thing and never edit the timeline (Task 3).
2. **Ripple delete or close gap with a locked clip later on the track.** The helper returns no operations, and the entry is disabled with the reason "A later clip is locked" (Task 2).
3. **A menu opened near the bottom-right corner.** It stays inside the viewport (Task 1).
4. **Space while a button or checkbox has focus.** The control's own action runs, and playback does not also toggle (Task 3).
5. **A drag over an incompatible lane** (a video clip over Music). Nothing moves to that lane; the clip stays on its own track at the dragged frame (Task 4).

---

### Task 1: Shared context menu

**Files:**
- Create: `dashboard/src/components/ContextMenu.tsx`
- Test: `dashboard/src/components/ContextMenu.test.tsx`
- Modify: `docs/superpowers/specs/2026-11-08-studio-timeline-track-design.md`: commit the code-reading corrections already in the working tree.

**Interfaces:**
- Produces:
  ```ts
  export type MenuEntry =
    | { kind: "item"; id: string; label: string; shortcut?: string; disabled?: boolean; reason?: string; onSelect: () => void }
    | { kind: "group"; id: string; label: string; entries: MenuEntry[] }   // a labelled run of items, e.g. "Move to track"
    | { kind: "separator"; id: string };
  export function useContextMenu(): {
    /** Spread onto the element that owns the menu. */
    bind: (entries: () => MenuEntry[]) => {
      onContextMenu: (event: React.MouseEvent) => void;
      onKeyDown: (event: React.KeyboardEvent) => void;      // Shift+F10 and the ContextMenu key
      onPointerDown: (event: React.PointerEvent) => void;   // touch long press, 500 ms
      onPointerUp: () => void;
      onPointerCancel: () => void;
    };
    element: React.ReactNode;   // render once, anywhere in the owner
    close: () => void;
    open: boolean;
  };
  ```

- [ ] **Step 1: Write the failing tests** in `ContextMenu.test.tsx`. Each test renders a `Harness` with a button that spreads `bind(() => entries)` and renders `element`.
  - `right click opens a menu at the pointer`: `fireEvent.contextMenu(button, { clientX: 40, clientY: 50 })`. Expect `getByRole("menu")`, the first `menuitem` focused, and the menu's `style.left` equal to `"40px"`.
  - `Shift+F10 opens it on the focused element`: `fireEvent.keyDown(button, { key: "F10", shiftKey: true })`. Expect the menu.
  - `Escape, an outside pointer down and a chosen item close it`: one `onSelect` mock is called once after `fireEvent.click(item)`, and the menu is gone each time.
  - `arrows move between enabled items and Enter acts`: two items with a disabled one between them. ArrowDown skips the disabled one; Enter calls the second item's `onSelect`.
  - `a disabled entry shows why and does nothing`: `aria-disabled="true"`, `title` equals the reason, and a click calls nothing.
  - `a group lists its items under its label`: `getByRole("group", { name: "Move to track" })` contains two `menuitem`s.
  - `a menu near the corner stays inside the viewport`: set `window.innerWidth = 300` and `innerHeight = 200`, open at (290, 190), and stub the menu's `getBoundingClientRect` to `{ width: 160, height: 120 }`. Expect `left` ≤ 140 and `top` ≤ 80.
  - `a long touch press opens it`: `pointerDown` with `pointerType: "touch"`, advance a fake timer 500 ms, expect the menu. A `pointerUp` before 500 ms opens nothing.
- [ ] **Step 2: Run them; they fail** (module not found).
  `bash D:/thoth-tmp/fixes/dash_test.sh src/components/ContextMenu.test.tsx`
- [ ] **Step 3: Implement `useContextMenu()` and the menu element.** Render the menu in a portal to `document.body` with `position: fixed`, and clamp it with the measured size after mount (`useLayoutEffect`). Close on window `pointerdown` outside, `scroll` (capture), `resize`, Escape, and after `onSelect`. Return focus to the owner element on close. Show each shortcut right-aligned in a `<kbd>`. Use the existing tokens (`bg-raised`, `border-hairline`, `text-ink`, `text-faint`).
- [ ] **Step 4: Run the tests; they pass.**
- [ ] **Step 5: Commit**: `git add -f docs/superpowers/specs/2026-11-08-studio-timeline-track-design.md` with the component and its test, then `git commit -m "Add a shared context menu for Studio"`.

### Task 2: Edit helpers that return operations

**Files:**
- Create: `dashboard/src/features/studio/timeline_edits.ts`
- Test: `dashboard/src/features/studio/timeline_edits.test.ts`
- Test: `python/tests/domain/test_timeline_operations.py` (one test)

**Interfaces:**
- Consumes: `EditDocumentV2`, `EditDocumentOperation`, `compatibleTrackIds` from `timeline_domain.ts`.
- Produces. Every helper returns `[]` when the edit is not allowed, and `newId("op")` makes the ids:
  ```ts
  export type Refusal = "locked" | "later_locked" | "outside" | "no_gap" | "not_empty" | "edge" | "incompatible";
  export type Edit = { operations: EditDocumentOperation[]; refusal?: Refusal };
  export function deleteClip(doc: EditDocumentV2, clipId: string): Edit;
  export function rippleDelete(doc: EditDocumentV2, clipId: string): Edit;          // remove_clip, then move_clip for each later clip on the track, ascending
  export function splitAt(doc: EditDocumentV2, clipId: string, frame: number): Edit; // refusal "outside" unless from < frame < end
  export function moveToTrack(doc: EditDocumentV2, clipId: string, trackId: string): Edit; // move_clip, same from_frame, ripple false
  export function gapAt(doc: EditDocumentV2, trackId: string, frame: number): { start: number; end: number } | null; // between two clips only
  export function closeGap(doc: EditDocumentV2, trackId: string, frame: number): Edit; // moves every clip at or after gap.end left by its length
  export function moveTrack(doc: EditDocumentV2, trackId: string, direction: -1 | 1): Edit; // two reorder_track ops swapping `order` with the neighbour; refusal "edge"
  export function removeTrack(doc: EditDocumentV2, trackId: string): Edit;          // remove_empty_track; refusal "not_empty"
  export function setClipFlag(doc: EditDocumentV2, clipId: string, flag: "hidden" | "locked", value: boolean): Edit;
  ```
- [ ] **Step 1: Write the failing tests** with `timelineDocument()`. In that fixture, `clip_main` is on `track_main` at 0 for 120 frames, `clip_locked` is on `track_broll` at 150, and `clip_music` is on `track_music` at 150 for 90 frames. The tests:
  - `deleteClip(clip_main)` gives one `remove_clip`.
  - `deleteClip(clip_locked)` gives refusal `locked`.
  - `rippleDelete` on a document with three clips on `track_main` (0–60, 60–100, 130–160):
    - removing the first gives `remove_clip` and then `move_clip`s to 0 and 70, in that order;
    - when the last clip is locked, it gives refusal `later_locked`.
  - `splitAt(clip_main, 60)` gives one `split_clip` with `split_frame` 60 and two new clip ids. Frames 0 and 120 give refusal `outside`.
  - `moveToTrack(clip_main, "track_broll")` gives one `move_clip` with `target_track_id` "track_broll" and `from_frame` 0. Moving it to `track_music` gives refusal `incompatible`, because `compatibleTrackIds` excludes that track for a video clip.
  - `gapAt` and `closeGap` on the three-clip document:
    - `gapAt(track_main, 110)` is `{ start: 100, end: 130 }`;
    - `gapAt(track_main, 200)` is null, because there is no clip after it;
    - `closeGap` at 110 moves the third clip to 100.
  - `moveTrack(track_broll, -1)` gives two `reorder_track` ops with orders 0 and 1 swapped. `moveTrack(track_main, -1)` gives refusal `edge`.
  - `removeTrack(track_captions)` is refused as `locked` (the track is locked in the fixture). `removeTrack(track_main)` is refused as `not_empty`.
  - **Every helper's operations apply.** For each non-refused result, `batchDraft` from `editor_state.ts` (export it if needed) returns a document. This proves the client accepts the batch.
- [ ] **Step 2: Run them; they fail.** `bash D:/thoth-tmp/fixes/dash_test.sh src/features/studio/timeline_edits.test.ts`
- [ ] **Step 3: Implement the helpers** in `timeline_edits.ts`. `rippleDelete` and `closeGap` sort later clips by `from_frame` ascending, so each move lands in space already freed.
- [ ] **Step 4: Run them; they pass.**
- [ ] **Step 5: Add the server guard test** `test_ripple_delete_batch_applies_in_order` to `test_timeline_operations.py`. It applies `remove_clip` and then two `move_clip`s, built like the TS case, through `apply_timeline_operation` on a v2 fixture. Then it asserts `track_ranges` equals the closed-up ranges. Run `make test T=tests/domain/test_timeline_operations.py` in WSL; expect PASS (no server change).
- [ ] **Step 6: Commit**: `git commit -m "Add timeline edit helpers that return operations"`.

### Task 3: Keys (Studio-wide and Timeline)

**Files:**
- Create: `dashboard/src/features/studio/studio_keys.ts` (`isTypingTarget`, `timelineKey`, `useStudioShortcuts`)
- Test: `dashboard/src/features/studio/studio_keys.test.ts`
- Modify: `dashboard/src/features/studio/Timeline.tsx` (a window `keydown` for Timeline keys); `dashboard/src/features/studio/GuidedStudio.tsx` (calls `useStudioShortcuts`)
- Test: `dashboard/src/features/studio/Timeline.test.tsx`, `dashboard/src/features/studio/GuidedStudio.test.tsx`

**Interfaces:**
- Consumes: Task 2 helpers. The existing `undo` and `redo` in `GuidedStudio.tsx:609-610`.
- Produces:
  ```ts
  export function isTypingTarget(target: EventTarget | null): boolean;
  export type TimelineKey =
    | "delete" | "ripple_delete" | "split" | "play" | "start" | "end"
    | "frame_back" | "frame_forward" | "second_back" | "second_forward"
    | "zoom_in" | "zoom_out" | "zoom_fit" | "clear";
  export function timelineKey(event: Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "shiftKey" | "altKey">): TimelineKey | null;
  export function useStudioShortcuts(handlers: { undo: () => void; redo: () => void; shortcuts: () => void; enabled: boolean }): void;
  ```
  Timeline props gain `onShortcuts?: () => void` (used by Task 6).
- [ ] **Step 1: Write the failing tests.**
  - `studio_keys.test.ts`:
    - `isTypingTarget` is true for a text input, a textarea, a select and a `contenteditable` div; it is false for a checkbox input, a button and `null`.
    - `timelineKey` maps every key in the Global Constraints:
      - Delete and Backspace give `delete`; Shift+Delete gives `ripple_delete`; `s` and `S` without modifiers give `split`;
      - Ctrl+s gives `null`, because saving belongs to the browser;
      - Ctrl+= and Ctrl++ give `zoom_in`; Ctrl+0 gives `zoom_fit`; Escape gives `clear`.
  - `Timeline.test.tsx`, using the existing `mount`:
    - `Delete removes the selected clip`: `selectedClipId: "clip_main"`, `fireEvent.keyDown(window, { key: "Delete" })`. Expect one `commit_operations` with a `remove_clip` for `clip_main`.
    - `S splits at the playhead`: `playheadFrame: 60`. Expect `split_clip` with `split_frame` 60.
    - `keys typed in a field do nothing`: render an `<input>` beside the Timeline, focus it, and press Delete and S on it. Expect no actions.
    - `Space on a focused button does not also toggle play`: press Space on the "Zoom in" button. Expect `transport` to stay empty.
    - `Space elsewhere plays`: press Space on `document.body`. Expect `transport` to equal `["play"]`.
    - `Home and End seek`: expect `set_playhead` 0 and 299.
    - `Ctrl+0 fits the canvas`: expect a `set_zoom` whose value makes 300 frames fill the lane width that the test stubs on the scroll container (1000 px gives zoom ≈ 3.33, clamped by `clampZoom`).
    - `a locked clip ignores Delete and S`: `selectedClipId: "clip_locked"`. Expect no actions.
  - `GuidedStudio.test.tsx`: `Ctrl+Z and Ctrl+Y undo and redo outside fields`. After one edit, Ctrl+Z restores the previous draft, and Ctrl+Y re-applies it. Ctrl+Z inside the heading textbox dispatches no `undo`.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
  - **Timeline:** add a second effect with a window `keydown` that returns early when `readOnly`, when `isTypingTarget(event.target)` is true, or when `timelineKey` gives `null`.
  - **Space:** return early when the target is a `button`, an `input` or a `select`.
  - **Edit keys:** route them through the Task 2 helpers. When a helper refuses, do nothing.
  - **Zoom fit:** use the width of the lane scroll container (keep it in a ref) minus `HEADER_WIDTH`.
  - **Escape:** keep the existing drag cancel first. Otherwise, when a clip is selected, dispatch `select_clip` with `""`. Add an `""` case to the reducer, which clears both selections, if it does not accept `""` today.
  - **GuidedStudio:** call `useStudioShortcuts({ undo, redo, shortcuts: () => setShortcutsOpen(true), enabled: editing && !reviewing })`. Task 6 adds the `setShortcutsOpen` state; until then, pass a no-op.
- [ ] **Step 4: Run them; they pass.**
- [ ] **Step 5: Commit**: `git commit -m "Wire Studio and Timeline keyboard shortcuts"`.

### Task 4: Pointer: drag to a track, click to seek, Ctrl+wheel, select a track

**Files:**
- Modify: `dashboard/src/features/studio/Timeline.tsx`, `dashboard/src/features/studio/TimelineTrack.tsx`
- Test: `dashboard/src/features/studio/Timeline.test.tsx`

**Interfaces:**
- Consumes: `compatibleTrackIds` and `TRACK_CLIP_KINDS` from `timeline_domain.ts`.
- Produces: `TimelineTrack` props gain `onSeekAt(offsetPx: number)`, `onSelectTrack()` and `headerMenu` (Task 5 fills it).
- [ ] **Step 1: Write the failing tests.**
  - `a clip dragged onto another compatible lane moves there`: stub `document.elementsFromPoint` to return the B-roll lane element (`[data-track-id="track_broll"]`) and drag `clip_main` down. Expect a `commit_timeline_operation` `move_clip` with `target_track_id` "track_broll".
  - `an incompatible lane keeps the clip on its track`: the stub returns the Music lane. Expect `target_track_id` "track_main".
  - `a click on an empty part of a lane seeks`: `pointerDown` on the Music lane's well at `clientX` = left + 200, with `zoom` 4. Expect `set_playhead` 50.
  - `a click on a clip does not seek`.
  - `Ctrl+wheel zooms out and plain wheel does not`: `fireEvent.wheel(scroller, { deltaY: 240, ctrlKey: true })` gives a `set_zoom` below the current zoom; without `ctrlKey` there is none.
  - `a click on a track name selects the track`: expect `select_track` with "track_music".
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
  - **Drag:** the gesture also records `clientY`. On move, find the first `[data-track-id]` under the pointer among `document.elementsFromPoint`. Use it as `trackId` only when it is in `compatibleTrackIds(doc, clip.kind)`; otherwise keep the clip's own track.
  - **Lane click:** handle it on the lane well, only when `event.target === event.currentTarget`.
  - **Ctrl+wheel:** a native `wheel` listener with `{ passive: false }` on the scroll container. On `ctrlKey`, `preventDefault`, then zoom by ×1.25 or ÷1.25 and keep the frame under the pointer in place (adjust `scrollLeft`).
  - **Track name:** the name area becomes a button-like element with `aria-label` "Select {track} track" that calls `onSelectTrack`. The hover toggles stay as they are.
- [ ] **Step 4: Run them; they pass.**
- [ ] **Step 5: Commit**: `git commit -m "Drag clips across tracks, seek from a lane, Ctrl+wheel zoom"`.

### Task 5: Timeline right-click menus and a real Replace media

**Files:**
- Create: `dashboard/src/features/studio/ReplaceMediaDialog.tsx`; Test: `ReplaceMediaDialog.test.tsx`
- Modify: `dashboard/src/features/studio/Timeline.tsx`, `TimelineTrack.tsx`, `TimelineClip.tsx`, `GuidedStudio.tsx` (passes `assets`, `onShowInStory`), `dashboard/src/lib/i18n.ts`
- Test: `dashboard/src/features/studio/Timeline.test.tsx`

**Interfaces:**
- Consumes: `useContextMenu` and `MenuEntry` (Task 1); the Task 2 helpers; `beatOfClip(document, inventory, clipId)` from `story/story_beats.ts`.
- Produces:
  - `ReplaceMediaDialog({ clip, assets, onReplace, onClose })`, which lists the `assets` with `kind === "video"` and `validation_state === "ready"`, except the clip's own asset. `onReplace(assetId)` commits one `replace_clip_asset`.
  - Timeline props gain `assets: Record<string, EditorAsset>` and `onShowInStory?: (clipId: string) => void`.
- [ ] **Step 1: Write the failing tests.**
  - **Clip menu:** a right click on the Main video clip opens a menu with these entries, in this order: Split at playhead · Delete · Ripple delete · Replace media… · Move to track (group: B-roll) · Hide · Lock · Show in Story.
  - **Disabled entries:** with the playhead at 200 (outside the clip), "Split at playhead" is disabled with the reason "The playhead is outside this clip". On `clip_locked`, every edit entry is disabled with the reason "This clip is locked".
  - **Delete from the menu** commits `commit_operations` with `remove_clip`. **Ripple delete** commits the Task 2 batch as one action.
  - **Gap menu:** a right click on the empty well between two clips offers "Close this gap". Choosing it commits the `closeGap` batch. Off a gap the entry is disabled.
  - **Track menu:** a right click on a track name offers Select track · Move up · Move down · Hide · Mute · Lock · Remove empty track. "Move up" on the first track is disabled; "Remove empty track" on a track with clips is disabled.
  - **ReplaceMediaDialog:** it lists only ready videos. Choosing one calls `onReplace` with its id, and an empty list shows "No other ready video in this project".
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
  - **Clip menu:** `TimelineClip` spreads `bind` on its button.
  - **Gap and track menus:** `TimelineTrack` spreads it on the lane well (the gap menu) and on the name (the track menu).
  - **Entries:** `Timeline` builds them from the Task 2 helpers. A refusal maps to an i18n reason under `studio.menu.reason.<refusal>`.
  - **Committing:** every entry commits through `dispatch({ type: "commit_operations", operations })`.
  - **Show in Story** calls `onShowInStory`. `GuidedStudio` implements it as `set_editor_mode` "simple" plus `setSelectedBeat(beatOfClip(...))`. The entry is disabled when `beatOfClip` returns null.
  - **Shortcuts:** each entry shows its key from the Global Constraints.
  - **Story Inspector:** replace the placeholder Replace panel in `SceneMediaInspector.tsx` with `ReplaceMediaDialog` for the scene's video clip. Its disabled button goes away.
- [ ] **Step 4: Run them; they pass.**
- [ ] **Step 5: Commit**: `git commit -m "Add Timeline right-click menus and a working Replace media"`.

### Task 6: The shortcut list

**Files:**
- Create: `dashboard/src/features/studio/ShortcutsDialog.tsx`; Test: `ShortcutsDialog.test.tsx`
- Modify: `GuidedStudio.tsx` (adds `shortcutsOpen` state, a "Keyboard shortcuts" entry in the workspace menu, and the real handler in `useStudioShortcuts`), `i18n.ts`

**Interfaces:**
- Consumes: `useStudioShortcuts` (Task 3).
- Produces: `ShortcutsDialog({ open, onClose })`, a `<dialog>` named "Keyboard shortcuts" with one table per group (Editing, Playback, View, Studio). Every row comes from one exported `SHORTCUTS` array, which the menus (Task 5) also read for their shortcut text, so the two never drift.
- [ ] **Step 1: Failing tests.**
  - `?` on `document.body` opens the dialog, and so does Ctrl+/.
  - `?` typed in a textbox does not open it.
  - The dialog lists "Ripple delete" with "Shift+Delete".
  - Escape closes it.
- [ ] **Step 2: Run; fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run; pass.**
- [ ] **Step 5: Commit**: `git commit -m "Add the Studio keyboard shortcut list"`.

### Task 7: The look: names, time, wording, layout

**Files:**
- Modify: `TimelineTrack.tsx` (the visible name), `TimelineInspector.tsx` (time fields, the heading), `TimelineClip.tsx` (the label tooltip), `GuidedStudio.tsx` (the 1440 split and the 1024 rail), `timeline_domain.ts` (`parseTimecode`, `trackName`), `i18n.ts`
- Test: `timeline_domain.test.ts`, `TimelineInspector.test.tsx`, `GuidedStudio.responsive.test.tsx`

**Interfaces:**
- Produces:
  ```ts
  export function parseTimecode(text: string, fps: number): number | null; // "0:07.5", "7.5", "1:02" → frames; null when unreadable
  export function trackName(t: LocaleState["t"], document: EditDocumentV2, track: TimelineTrack): string; // localized kind name, " 2"/" 3" for later tracks of the same kind
  ```
  New i18n keys:
  - `studio.timeline.trackName.<kind>`:
    - `en`: Main video, B-roll, Overlay, Captions, Narration, Music, Sound effects;
    - `id`: Video utama, B-roll, Overlay, Takarir, Narasi, Musik, Efek suara.
  - `studio.timeline.startTime` and `studio.timeline.endTime`.
  - `studio.timeline.ownership*` and `studio.scene.ownership*`:
    - `en`: label "Edited by", options "Thoth", "You", "Nobody (locked)";
    - `id`: "Diedit oleh", "Thoth", "Anda", "Tidak ada (terkunci)".
- [ ] **Step 1: Failing tests.**
  - `parseTimecode("0:07.5", 30)` is 225, `parseTimecode("7.5", 30)` is 225, `parseTimecode("1:02", 30)` is 1860, and `parseTimecode("abc", 30)` is null.
  - `trackName` gives "Main video" for `track_main` in `en` and "Video utama" in `id`. A second b_roll track reads "B-roll 2".
  - **Inspector:**
    - a "Start time" textbox shows `0:00.0` for `clip_main`;
    - typing `0:01.0` and pressing Enter commits `move_clip` with `from_frame` 30;
    - the "Start frame" spinbutton still exists;
    - the track heading uses `trackName`.
  - **Responsive** (the existing harness):
    - at 1024 with nothing selected, the Timeline inspector column is the 3 rem rail; selecting a clip widens it to the Inspector width;
    - at 1440 the Timeline region's grid row is at least 55% of the workstation height.
- [ ] **Step 2: Run; fail.**
- [ ] **Step 3: Implement.**
  - **Track names:** keep every `aria-label` that uses `track.label`, so the e2e tests keep their names. Only the visible text changes.
  - **Clip labels:** the label `span` gets `title={text}`.
- [ ] **Step 4: Run; pass.**
- [ ] **Step 5: Commit**: `git commit -m "Name tracks plainly, show time in the Inspector, give the lanes room"`.

### Task 8: Story right-click menus

**Files:**
- Modify: `story/BeatInspector.tsx` (the Shown items), `story/BeatStrip.tsx` (the beats), `story/MaterialsPanel.tsx` (the materials), `GuidedStudio.tsx` (passes `onShowInTimeline`, `onPlayFrom`, `attachToOpenBeat`), `i18n.ts`
- Test: `story/BeatInspector.test.tsx`, `story/BeatStrip.test.tsx`, `story/MaterialsPanel.test.tsx`, `story/StoryMode.test.tsx`

**Interfaces:**
- Consumes: `useContextMenu` (Task 1); `swapClips`, `removeFromBeat`, `setPositionPreset`, `setEmphasis` (`story_edits.ts`); `ReplaceMediaDialog` (Task 5).
- Produces:
  - **New props:**
    - `BeatInspector`: `onShowInTimeline(clipId)` and `onPlayFrom(frame)`.
    - `BeatStrip`: `onShowInTimeline(beatId)` and `onAddFromMaterials(beatId)`.
    - `MaterialsPanel`: `openBeat`, `onAddToOpenBeat(itemId)` and `onShowUse(clipId)`.
  - **GuidedStudio implements them:**
    - `onShowInTimeline` dispatches `set_editor_mode` "advanced" plus `select_clip`. For a beat, it seeks to the beat's start instead.
    - `onPlayFrom` calls `player.seekTo(frame)` and then `player.play()`.
    - `onAddToOpenBeat` reuses the `attachMaterial` and `addMaterialToBeat` path that `BeatInspector.add` uses today. Lift it into GuidedStudio as `addMaterial(itemId, role, beat)`, and have `BeatInspector` call the same function.
- [ ] **Step 1: Failing tests.**
  - **Shown item:** a right click on the second Shown item offers Move earlier · Move later · Remove from beat · Replace media… · Position (Top, Middle, Lower third) · Emphasis (Highlight, Arrow; cards only) · Play from here · Show in Timeline.
    - "Move earlier" commits the same `swapClips` batch as the arrow button.
    - On the first item, "Move earlier" is disabled.
  - **Beat:** a right click on the Evidence beat offers Open beat · Add from materials… · Show in Timeline. "Show in Timeline" calls `onShowInTimeline("evidence")`.
  - **Material:**
    - a right click on a material offers Add to the open beat · Show where it is used · Why this material;
    - a material already shown has "Add to the open beat" disabled with the reason "Already in this beat";
    - an unused material has "Show where it is used" disabled.
  - **StoryMode:** "Show in Timeline" on a Shown item switches the editor mode to Timeline with that clip selected.
- [ ] **Step 2: Run; fail.**
- [ ] **Step 3: Implement.** Re-voice appears in no menu.
- [ ] **Step 4: Run; pass.**
- [ ] **Step 5: Commit**: `git commit -m "Add Story right-click menus"`.

### Task 9: E2E, records, and the branch gate

**Files:**
- Modify: `e2e/tests-write/studio-write.e2e.ts` (the fragile test), `e2e/tests-write/timeline-audit.e2e.ts` (new tests)
- Modify: `CHANGELOG.md`, `docs/ROADMAP.md` (track status, additions only), `.superpowers/sdd/2026-11-08-studio-timeline-track/progress.md` (new checkpoint)

- [ ] **Step 1: Fix the fragile test.** "a video longer than the canvas is cut to fit…" uploads its own 80 s fixture through the Asset library's Upload file, then adds that row by its new name. It no longer adds the newest `Upload · Video`.
- [ ] **Step 2: Add write tests** to `timeline-audit.e2e.ts`, in the existing style:
  - `right click: ripple delete pulls the next clip left`;
  - `right click: close this gap`;
  - `right click: Move to track moves the clip to B-Roll`;
  - `keyboard: ? opens the shortcut list`;
  - `story: right click on a Shown item offers Show in Timeline` (it switches mode).
- [ ] **Step 3: Full local verification.** `dash_full.sh full` (all pass, build clean), `make test`, `make lint`.
- [ ] **Step 4: Write the records.** In `CHANGELOG.md`, add an entry with **Next steps**:
  - the operator gates: a new one-day write token, push and PR, deploy of the branch image, the e2e write run, merge;
  - Tier 2 next.
  Write the same in the new checkpoint. In `docs/ROADMAP.md`, add one status line under the Studio Timeline track.
- [ ] **Step 5: Commit**: `git commit -m "Record Studio Timeline Tier 1"`.
- [ ] **Step 6: Stop at the gate.** Ask the operator for:
  - a new one-day write-scope token (`thoth-control tokens create --scope write --days 1`, stored without printing);
  - push and PR;
  - a deploy of the branch image.

  After the deploy, run the write suite at `rw1440`, expecting every test but the Fit / Crop / Position one (Tier 2) to pass. Then do the read-only look at 1440, 1024 and 430. Then merge, with its own authorization.

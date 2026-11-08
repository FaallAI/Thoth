# Studio Timeline Tier 2 (comfort) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Studio the comfort of common editors: select many clips, copy, paste and duplicate clips inside the page, paste text from the system clipboard to a place the person picks, close all gaps, edit Fit, Crop, Position and fades, find and drag assets, and J/K/L.

**Architecture:** Four new typed operations (`duplicate_clip`, `set_clip_fit`, `set_clip_crop`, `set_clip_fades`) and new fade fields on video clips land on the server first and are mirrored in `timeline_domain.ts`; the renderer honours video fades. Everything else is dashboard work on top of the Tier 1 pieces: selection grows from one id to a list in `editor_state.ts`, the pure helpers in `timeline_edits.ts` gain batch forms, and keys and menus keep calling `commit_operations`, so one user action is still one undo step.

**Tech Stack:** Python domain (pydantic, pytest), React 19 + TypeScript with Bun tests (`dashboard/`), the Remotion composition (`packages/remotion-composition/`, tested from the dashboard), tester-army/e2e (`e2e/`).

**Spec:** `docs/superpowers/specs/2026-11-08-studio-timeline-track-design.md`, section 6 (Tier 2), with sections 2 and 3 as constraints.
**Tier 1 record:** `.superpowers/sdd/2026-11-08-studio-timeline-tier1/progress.md` (rulings and the 11 deferred minors this plan picks up in Task 12).

## Global Constraints

- Every edit is a typed operation. One user action is one `commit_operations` dispatch, so it is one patch and one undo step (spec §3).
- A batch acts on the whole selection or not at all: if any clip in it is locked or the edit is refused for one clip, nothing changes and the reason is shown.
- New schema fields have defaults so stored documents and older clients still decode (`AGENTS.md`). New operations exist in `timeline_operations.py` and `timeline_domain.ts`, with tests on both sides (spec §3).
- Clips and media never go through the system clipboard. Copied clips live in the open page only. Only plain text goes through the system clipboard (operator, 2026-11-08; spec §6).
- No key or menu entry starts narration, re-voice, Assist, a proposal or a render (spec §2 anti-goals).
- Keys never act while the event target is a typing target (`isTypingTarget` in `studio_keys.ts`), nor inside `[role='dialog']` or `[role='menu']`. Ctrl+A, Ctrl+C and Ctrl+V in a field keep the browser's own behaviour.
- Text limits: a heading and a caption cue hold at most 300 characters (`ShortText`), and pasted text is plain text, trimmed.
- Every new string exists in `en` and `id` in `dashboard/src/lib/i18n.ts`.
- Commits: one subject line, `git commit -m "<subject>"`, no body, no trailer (`AGENTS.md`).
- Verification per task: `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/fixes/dash_test.sh <test paths>` for the dashboard, and `make test T=<path>` plus `make lint` in WSL for Python. Before the PR: `dash_full.sh full`, the full `make test`, and `make lint`.

## Review Focus

1. **Paste where the Main video track is already filled** (main video clips must not overlap on the server). Nothing is placed and the reason "No room on Main video at the playhead" shows (Task 7).
2. **A selection that holds one locked clip**, then Delete, ripple delete, drag or hide. Nothing changes and the reason names the lock (Task 6).
3. **A trim or a split of a clip whose fades are longer than what is left.** The fades shrink to fit and the server accepts the batch (Task 1, mirrored in Task 2).
4. **Ctrl+A, Ctrl+C or Ctrl+V while the caret is in the heading or a caption field.** The field selects, copies or pastes its own text; no clips are selected and no chooser opens (Tasks 5, 7, 8).
5. **Pasted text that is HTML, blank, or longer than 300 characters.** Only plain text is used; blank text opens nothing; text that is too long leaves every destination disabled with the reason "Longer than 300 characters" (Task 8).

---

### Task 1: Server operations and video fades

**Files:**
- Modify: `python/src/thoth_control_plane/domain/edit_document_v2.py` (video fade fields, fade validation for video and audio)
- Modify: `python/src/thoth_control_plane/domain/timeline_operations.py` (four operations, `add_text_clip.source_role` optional, fade clamping on trim and split)
- Regenerate: `python/openapi.json`, `dashboard/src/api/generated/control-plane.ts`, `renderer/src/generated/edit-document.schema.json`
- Test: `python/tests/domain/test_timeline_operations.py`, `python/tests/domain/test_edit_document_v2.py`

**Interfaces:**
- Produces (Python, mirrored in TS by the generated types):
  ```python
  class TimelineVideoClip:  # new fields
      fade_in_frames: FadeFrames = 0
      fade_out_frames: FadeFrames = 0
  class DuplicateClip(StrictModel):   # copy a clip under a new id; asset, ownership, source_role, styling kept; scene_id dropped
      kind: Literal["duplicate_clip"]; operation_id; clip_id; new_clip_id: OpaqueId
      track_id: OpaqueId; from_frame: FrameStart
  class SetClipFit(StrictModel):      # video clips
      kind: Literal["set_clip_fit"]; operation_id; clip_id; fit: FitMode
  class SetClipCrop(StrictModel):     # video clips; None restores the full frame
      kind: Literal["set_clip_crop"]; operation_id; clip_id; crop: Crop | None = None
  class SetClipFades(StrictModel):    # video and audio clips
      kind: Literal["set_clip_fades"]; operation_id; clip_id
      fade_in_frames: FadeFrames; fade_out_frames: FadeFrames
  class AddTextClip:  # changed: source_role: Literal["hook", "outro"] | None = None
  ```

- [ ] **Step 1: Write the failing tests** in `test_timeline_operations.py`:
  - `test_duplicate_clip_copies_under_a_new_id`: duplicating a video clip to frame 200 on its own track gives a second clip with the same `asset_id`, `ownership`, `source_role`, `fit`, `position` and `blur_regions`, `scene_id` None, `from_frame` 200, and the new id in the track's `clip_ids`.
  - `test_duplicate_clip_refuses_a_reused_id_a_locked_track_and_an_incompatible_track`: three `pytest.raises(ValueError)` cases.
  - `test_duplicate_onto_filled_main_video_is_refused`: the revalidated document raises "main video clips must not overlap".
  - `test_set_clip_fit_crop_and_fades`: each sets its field on a video clip; `set_clip_crop` with `crop=None` clears it; `set_clip_fit` on an audio clip raises; `set_clip_fades` works on audio and video and raises on text.
  - `test_fades_longer_than_the_clip_are_refused`: `set_clip_fades` with in + out greater than the duration raises "fades must stay inside their clip".
  - `test_trim_and_split_shrink_fades_to_fit`: a 100-frame clip with fades 40/40, trimmed to 60 frames, keeps fades whose sum is at most 60 (fade out shrinks first, then fade in). A split at frame 50 gives the left part fade out 0 and the right part fade in 0.
  - `test_add_text_clip_without_a_story_role`: `add_text_clip` without `source_role` gives a text clip whose `source_role` is None.
  - In `test_edit_document_v2.py`, `test_a_stored_video_clip_without_fades_decodes` builds a video clip dict with no fade keys and validates it with both fades 0.
- [ ] **Step 2: Run them; they fail.** `make test T=tests/domain/test_timeline_operations.py` and `T=tests/domain/test_edit_document_v2.py`.
- [ ] **Step 3: Implement.** Generalise the audio-only fade check in `EditDocumentV2` to every clip that has fades, with the message "fades must stay inside their clip". Add `_fit_fades(clip)` and call it at the end of `_trim_clip_start`, `_trim_clip_end` and `_split_clip`. Add the four handlers to `apply_timeline_operation` and the union.
- [ ] **Step 4: Run them; they pass.** Then run `make lint`.
- [ ] **Step 5: Regenerate the contract.**
  - Run `python scripts/export_openapi.py` from `python/` (WSL, `uv run --no-project`). Normalise the output to LF, because the script writes CRLF on Windows.
  - Then, in `dashboard/`, run `bunx openapi-typescript ../python/openapi.json -o src/api/generated/control-plane.ts`.
  - Then, in `renderer/`, run `bun run schema`.
  - Run `bun test src/document-schema.test.ts` in `renderer/`; it passes.
- [ ] **Step 6: Commit**: `git commit -m "Add duplicate, fit, crop and fade operations and video fades"`.

### Task 2: Mirror the operations in the dashboard

**Files:**
- Modify: `dashboard/src/features/studio/timeline_domain.ts` (the four operations; fade clamping on trim and split; `add_text_clip` without a role; new video clips carry `fade_in_frames: 0, fade_out_frames: 0`)
- Modify: every hand-built TS video clip that `tsc` now flags (test fixtures included), adding both fades as 0.
- Test: `dashboard/src/features/studio/timeline_domain.test.ts`

**Interfaces:**
- Consumes: the generated operation types from Task 1.
- Produces: `applyTimelineOperation` accepts `duplicate_clip`, `set_clip_fit`, `set_clip_crop` and `set_clip_fades`, with the same refusals as the server.

- [ ] **Step 1: Write the failing tests**, one per Python test in Task 1, with the same values and names written as sentences (`"duplicate_clip copies under a new id"`, `"trim and split shrink fades to fit"`).
- [ ] **Step 2: Run them; they fail.** `dash_test.sh src/features/studio/timeline_domain.test.ts`
- [ ] **Step 3: Implement** the cases in `applyTimelineOperation`. A duplicate takes a `structuredClone` of the clip, sets the new id, track and frame, and deletes `scene_id`.
- [ ] **Step 4: Run them, then `dash_full.sh full`** (all dashboard tests, `tsc -b` and the build); both pass.
- [ ] **Step 5: Commit**: `git commit -m "Mirror the new timeline operations in the dashboard"`.

### Task 3: The renderer plays video fades

**Files:**
- Modify: `packages/remotion-composition/src/AdvancedTimelineComposition.tsx`
- Test: `dashboard/src/features/studio/AdvancedTimelineComposition.test.tsx`

**Interfaces:**
- Consumes: `fade_in_frames` and `fade_out_frames` on video clips (Task 1).
- Produces: `fadeMultiplier(frame, clip)` takes any clip with fades. A video clip's frame has `opacity` equal to that multiplier, and its own sound is scaled by it.

- [ ] **Step 1: Write the failing tests:**
  - `a video clip fades in and out`: render a 60-frame video clip with fades 10/10 at clip frames 0, 5, 30 and 59. Its frame's opacity is 0, 0.5, 1 and about 0.1 (`toBeCloseTo`, 1 digit).
  - `a video clip without fades is fully opaque`: no `opacity` below 1.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.** Widen `fadeMultiplier` to `{ duration_in_frames; fade_in_frames?; fade_out_frames? }`. In `videoClip`, set `opacity` on the frame element and multiply the clip's volume by the same value.
- [ ] **Step 4: Run them; they pass.**
- [ ] **Step 5: Commit**: `git commit -m "Fade video clips in and out in the composition"`.

### Task 4: Inspector: Fit, Crop, Position and fades

**Files:**
- Modify: `dashboard/src/features/studio/TimelineInspector.tsx`, `dashboard/src/lib/i18n.ts`
- Modify: `e2e/tests-write/timeline-audit.e2e.ts` (the Fit test)
- Test: `dashboard/src/features/studio/TimelineInspector.test.tsx`

**Interfaces:**
- Consumes: `set_clip_fit`, `set_clip_crop`, `set_clip_position`, `set_clip_fades` (Task 1).
- Produces: Inspector controls, each committing one operation through `emit`:
  - **Fit:** a `<select>` labelled "Fit" with Cover, Contain and Fill.
  - **Crop:** four number fields in percent, labelled "Crop left", "Crop top", "Crop right" and "Crop bottom" (0–100), and a "Reset crop" button that sends `crop: null`.
  - **Position:** number fields "Position X" and "Position Y" in percent (−100 to 100), "Scale" in percent (1–400), and a "Reset position" button.
  - **Fades:** "Fade in" and "Fade out" in seconds with one decimal, on video and audio clips.

- [ ] **Step 1: Write the failing tests:**
  - `Fit is a choice that commits set_clip_fit`: choose Contain; `emit` receives `{ kind: "set_clip_fit", fit: "contain" }`.
  - `crop fields commit a crop in fractions`: type 10 in Crop left and blur. `emit` receives `crop: { left: 0.1, top: 0, width: 0.9, height: 1 }`.
  - `a crop that leaves no picture is refused in place`: left 60 and right 50 gives no emit and the message "Crop leaves no picture".
  - `position and scale commit set_clip_position`.
  - `fades commit set_clip_fades in frames`: Fade in "0.5" at 30 fps gives 15.
  - `a fade longer than the clip is refused in place`: no emit, and the message "Fades are longer than the clip".
  - `an untouched field commits nothing on blur`.
  - `a locked clip shows these values read-only`.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement** with the Tier 1 `TimeField` pattern: commit on blur or Enter, and skip when the text is unchanged. Strings go in both locales.
- [ ] **Step 4: Run them; they pass.**
- [ ] **Step 5: Update the e2e red test.** Fit is a choice, so the test expects `screen.getByRole('combobox', 'Fit')` to be enabled instead of a textbox. Record this as a ruling.
- [ ] **Step 6: Commit**: `git commit -m "Edit Fit, Crop, Position and fades in the Inspector"`.

### Task 5: Select many clips

**Files:**
- Modify: `dashboard/src/features/studio/editor_state.ts`, `Timeline.tsx`, `TimelineTrack.tsx`, `TimelineClip.tsx`, `studio_keys.ts`
- Test: `editor_state.test.ts`, `Timeline.test.tsx`, `studio_keys.test.ts`

**Interfaces:**
- Produces:
  ```ts
  // EditorState
  selectedClipIds: string[];   // every selected clip; selectedClipId stays the primary one the Inspector shows
  // EditorAction
  | { type: "select_clip"; clipId: string; add?: boolean }   // add toggles the clip in or out of the selection
  | { type: "select_clips"; clipIds: string[] }              // marquee and Ctrl+A; primary = the last id
  // TimelineKey gains "select_all" (Ctrl+A)
  ```
  The reconcile step after a save or an undo drops ids that no longer exist, as it does today for `selectedClipId`.

- [ ] **Step 1: Write the failing tests:**
  - **Reducer:**
    - `select_clip` with `add` toggles a clip in and out;
    - a plain `select_clip` replaces the selection;
    - `select_clip` with an empty id clears it;
    - `select_clips` sets the list and makes the last id primary;
    - a removed clip leaves the selection after `commit_operations`.
  - **Timeline:**
    - Shift+click and Ctrl+click add a clip;
    - a drag on empty lane space draws a marquee and selects every clip it touches on the lanes it crosses;
    - Ctrl+A selects every clip on visible, unlocked lanes;
    - Escape clears the selection;
    - every selected clip has `aria-selected="true"` and the selected style;
    - Ctrl+A with focus in a text input selects nothing (Review Focus 4).
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.** A short click on empty lane space still seeks and clears, as in Tier 1. The marquee starts only after the pointer moves more than 4 px. It is a `position: absolute` box inside the lanes' scroll box, hit-tested against each clip's frame range and lane.
- [ ] **Step 4: Run them; they pass.**
- [ ] **Step 5: Commit**: `git commit -m "Select many clips with modifier clicks, a marquee and Ctrl+A"`.

### Task 6: Edits act on the whole selection

**Files:**
- Modify: `dashboard/src/features/studio/timeline_edits.ts`, `timeline_menus.ts`, `Timeline.tsx`
- Test: `timeline_edits.test.ts`, `Timeline.test.tsx`

**Interfaces:**
- Consumes: `selectedClipIds` (Task 5).
- Produces:
  ```ts
  export function deleteClips(doc: EditDocumentV2, ids: string[]): Edit;        // refusal "locked" if any is locked
  export function rippleDeleteClips(doc: EditDocumentV2, ids: string[]): Edit;  // rippleDelete per clip, latest first, on the evolving doc; the first refusal refuses all
  export function setClipsFlag(doc: EditDocumentV2, ids: string[], flag: "hidden" | "locked", value: boolean): Edit;
  export function moveClips(doc: EditDocumentV2, ids: string[], delta: number): Edit; // same tracks; "locked", "outside" (before 0 or past the canvas)
  ```
  A drag of one clip in a selection of several moves them all by the same delta, on their own tracks. While dragging, the Timeline dispatches a new `preview_timeline_operations` action (an array). On drop it dispatches `cancel_timeline_preview` and then `commit_operations`, so history gains one step.

- [ ] **Step 1: Write the failing tests:**
  - `deleteClips` removes two clips in one batch, and refuses with `locked` when one is locked (Review Focus 2).
  - `rippleDeleteClips` on clips at 0–60 and 100–130 pulls the rest left by 90 in total. Its operations apply through `applyTimelineOperation`.
  - `moveClips` by +30 moves both clips. With a locked clip in the list, it refuses with `locked`.
  - In Timeline:
    - Delete with two selected clips commits one `commit_operations` holding two `remove_clip`, and Ctrl+Z restores both at once;
    - the clip menu on a selected clip reads "Delete 2 clips";
    - a group drag previews both clips and commits one batch on drop;
    - Escape during a group drag restores both.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.** Single-clip menu entries (Split, Replace media, Move to track) stay single, acting on the clip under the pointer. Delete, Ripple delete, Hide and Lock act on the selection when the clip under the pointer is in it.
- [ ] **Step 4: Run them; they pass.**
- [ ] **Step 5: Commit**: `git commit -m "Delete, ripple, move, hide and lock the whole selection as one edit"`.

### Task 7: Copy, paste and duplicate clips inside the page

**Files:**
- Modify: `dashboard/src/features/studio/timeline_edits.ts`, `timeline_menus.ts`, `Timeline.tsx`, `studio_keys.ts`, `dashboard/src/lib/i18n.ts`
- Test: `timeline_edits.test.ts`, `Timeline.test.tsx`

**Interfaces:**
- Consumes: `duplicate_clip` (Task 1), `selectedClipIds` (Task 5).
- Produces:
  ```ts
  export type Refusal = ... | "no_room" | "gone";
  /** duplicate_clip ops placing `ids` at `at`, each on its own track, keeping their offsets from the earliest clip. */
  export function pasteClips(doc: EditDocumentV2, ids: string[], at: number): Edit;
  /** pasteClips at the end of the selection. */
  export function duplicateClips(doc: EditDocumentV2, ids: string[]): Edit;
  // TimelineKey gains "copy" (Ctrl+C), "paste" (Ctrl+V), "duplicate" (Ctrl+D)
  ```
  The copied ids live in a `useRef<string[]>` inside `Timeline`, which is reset when the document id changes. Nothing is written to the system clipboard.
  - **`gone`:** a copied clip that was deleted before the paste refuses the paste with "A copied clip was deleted". A paste references live clips only, so the server's evidence rules hold.
  - **`no_room`:** a pasted main-video clip that overlaps another main-video clip refuses the paste.
  - **`outside`:** a paste past the canvas end refuses the paste.

- [ ] **Step 1: Write the failing tests:**
  - **`pasteClips`:**
    - two clips 30 frames apart, pasted at 200, give two `duplicate_clip` ops at 200 and 230 on their own tracks;
    - a paste at a frame where a Main video clip already sits gives `no_room` (Review Focus 1);
    - a deleted id gives `gone`;
    - a paste past the canvas end gives `outside`.
  - **`duplicateClips`:** the copy lands right after the selection's end.
  - **In Timeline:**
    - Ctrl+C then Ctrl+V pastes at the playhead as one undo step;
    - Ctrl+D duplicates;
    - the clip menu has Copy, Paste and Duplicate;
    - Ctrl+C in a text field leaves the clip clipboard empty, so a later Ctrl+V on the timeline pastes nothing (Review Focus 4).
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.** Ctrl+V on the timeline with copied clips pastes them. With none, Task 8 handles it.
- [ ] **Step 4: Run them; they pass.**
- [ ] **Step 5: Commit**: `git commit -m "Copy, paste and duplicate clips inside the open draft"`.

### Task 8: Text through the system clipboard, to a place the person picks

**Files:**
- Create: `dashboard/src/features/studio/PasteTextDialog.tsx`
- Modify: `timeline_menus.ts`, `Timeline.tsx`, `dashboard/src/lib/i18n.ts`
- Test: `PasteTextDialog.test.tsx`, `Timeline.test.tsx`

**Interfaces:**
- Consumes: `add_text_clip` with no role (Task 1), `replace_text`, `add_caption_clip`, `set_caption_cue_text`.
- Produces:
  ```ts
  export type PasteTarget = "new_text" | "replace_text" | "new_caption" | "replace_caption";
  export function PasteTextDialog(props: {
    text: string;
    targets: { target: PasteTarget; disabled?: boolean; reason?: string }[];
    onPick: (target: PasteTarget) => void;
    onClose: () => void;
  }): JSX.Element; // role="dialog", one button per target, Escape cancels
  export function pasteTextOperations(doc: EditDocumentV2, target: PasteTarget, text: string,
    at: { playheadFrame: number; selectedClipId: string }): Edit;
  ```
  - **The four targets (spec §6):**
    - `new_text` is a text clip on the first unlocked overlay track at the playhead. It runs 3 seconds, cut at the canvas end, with heading = text, body "" and style `title`.
    - `replace_text` sends `replace_text` (heading) on the selected text clip.
    - `new_caption` sends `add_caption_clip` on the first unlocked caption track for the scene under the playhead.
    - `replace_caption` sends `set_caption_cue_text` on the selected caption clip, for the cue under the playhead, or else cue 0.
  - **Disabled targets:**
    - targets that do not apply (no text clip selected, no overlay or caption track, a locked clip) are disabled with a reason;
    - text longer than 300 characters disables every target with "Longer than 300 characters".
  - **Where the text comes from:**
    - **Ctrl+V on the timeline:** a window `paste` event with no copied clips takes `clipboardData.getData("text/plain")`. That needs no permission.
    - **The menu's "Paste text…":** it reads `navigator.clipboard.readText()`. If that is refused, a notice says "Use Ctrl+V to paste text".
    - **Blank text:** text that is blank after trimming opens nothing.
  - **"Copy text"** is a clip-menu entry on text clips and caption clips. It sends the heading, or the cue under the playhead, to `navigator.clipboard.writeText`.

- [ ] **Step 1: Write the failing tests:**
  - **`pasteTextOperations`:** each target gives its operation with the given text.
  - **The dialog:**
    - it lists four buttons;
    - disabled ones carry their reasons;
    - Escape calls `onClose`;
    - nothing is placed until a pick.
  - **Timeline:**
    - a `paste` event carrying "Hello" opens the dialog, and picking "New text clip" commits one `add_text_clip` at the playhead;
    - a paste event whose target is an input opens nothing;
    - HTML-only clipboard data opens nothing;
    - blank text (only spaces) opens nothing;
    - 301 characters disable every target;
    - "Copy text" on a text clip calls `writeText` with its heading;
    - a refused `readText` shows the Ctrl+V notice.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them; they pass.**
- [ ] **Step 5: Commit**: `git commit -m "Paste text from the system clipboard to a chosen place"`.

### Task 9: Close all gaps

**Files:**
- Modify: `timeline_edits.ts`, `timeline_menus.ts`, `dashboard/src/lib/i18n.ts`
- Test: `timeline_edits.test.ts`, `Timeline.test.tsx`

**Interfaces:**
- Produces:
  ```ts
  /** Every gap between clips on one track, closed left to right on the evolving document; the first refusal refuses all. */
  export function closeAllGaps(doc: EditDocumentV2, trackId: string): Edit;
  /** Every stretch, between the first clip and the last, where no track holds a clip, closed in one batch. */
  export function closeTimelineGaps(doc: EditDocumentV2): Edit;
  ```
  "Close all gaps on this track" goes in the track menu. "Close all gaps in the timeline" goes in the gap menu, below "Close this gap". Both are disabled with the `no_gap` reason when nothing is to close.

- [ ] **Step 1: Write the failing tests:**
  - `closeAllGaps` on three main clips with two gaps leaves them touching, and the music clip moves with them.
  - `closeTimelineGaps` closes a stretch where every track is empty. It leaves a gap alone when another track has a clip there.
  - A locked clip that would move refuses with `later_locked`.
  - The batches apply.
  - The track menu entry commits one batch.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement** on top of `gapAt` and `closeGap`.
- [ ] **Step 4: Run them; they pass.**
- [ ] **Step 5: Commit**: `git commit -m "Close all gaps on a track or in the whole timeline"`.

### Task 10: Assets column: search, type filter, drag to a lane

**Files:**
- Modify: `dashboard/src/features/studio/AssetLibrary.tsx`, `Timeline.tsx`, `TimelineTrack.tsx`, `GuidedStudio.tsx`, `timeline_domain.ts`, `dashboard/src/lib/i18n.ts`
- Test: `AssetLibrary.test.tsx`, `Timeline.test.tsx`, `timeline_domain.test.ts`

**Interfaces:**
- Produces:
  ```ts
  // timeline_domain.ts: optional placement; without it, today's behaviour
  createAddClipFromAssetOperation(document, asset, playheadFrame, ids, at?: { trackId: string; frame: number })
  // Timeline prop
  onDropAsset?: (assetId: string, trackId: string, frame: number) => void;
  ```
  - **The asset list:**
    - a search box ("Search assets") matches the row label, ignoring case;
    - a type filter (All, Video, Image, Audio) is a group of toggle buttons;
    - rows are `draggable` and carry `dataTransfer` type `application/x-thoth-asset` holding the asset id.
  - **Dropping on a lane:**
    - a drop computes the frame from the pointer and the zoom;
    - an incompatible lane, or a lane with no room at that frame, places nothing and shows the existing "no room" notice;
    - a drop is one undo step.

- [ ] **Step 1: Write the failing tests:**
  - search narrows the rows;
  - the Audio filter shows audio only;
  - a row's `dragstart` sets the asset id;
  - `createAddClipFromAssetOperation` with `at` places on that track and frame, and returns undefined when there is no room;
  - in Timeline, a `drop` on the B-roll lane at 100 px calls `onDropAsset` with that track and frame;
  - a drop on the Music lane of a video asset places nothing.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.** In GuidedStudio, `onDropAsset` reuses `addAsset`'s notices.
- [ ] **Step 4: Run them; they pass.**
- [ ] **Step 5: Commit**: `git commit -m "Search, filter and drag assets onto a lane"`.

### Task 11: J, K, L

**Files:**
- Modify: `studio_keys.ts`, `Timeline.tsx`, `StudioPreview.tsx`, `GuidedStudio.tsx`, `dashboard/src/lib/i18n.ts`
- Test: `studio_keys.test.ts`, `Timeline.test.tsx`, `StudioPreview.test.tsx`

**Interfaces:**
- Produces:
  - `TimelineKey` gains `"shuttle_forward"` (L), `"shuttle_stop"` (K) and `"shuttle_back"` (J).
  - `StudioPreview` takes `playbackRate?: number`, passed to the Player.
  - GuidedStudio holds the rate:
    - **L** plays forward; each further L while playing doubles the rate, up to 4.
    - **K** pauses and resets the rate to 1.
    - **J** steps the playhead back one second per press.
  - **Ruling to record:** a browser cannot play video or audio in reverse (Remotion's Player docs: media tags cannot play at a negative rate), so J steps back instead of playing backward.
  - Shift+Left and Shift+Right (one second) already exist from Tier 1.

- [ ] **Step 1: Write the failing tests:**
  - `timelineKey` maps j, k and l;
  - L, L, L gives rates 1, 2 and 4;
  - K pauses and resets to 1;
  - J moves the playhead back by fps frames;
  - none of them act in a text field;
  - StudioPreview passes `playbackRate` to the Player.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement**, and add J, K and L to `SHORTCUTS` under playback.
- [ ] **Step 4: Run them; they pass.**
- [ ] **Step 5: Commit**: `git commit -m "Add J, K and L playback keys"`.

### Task 12: Tier 1 leftovers (the 11 deferred minors)

**Files:** the files each minor names. Tests go in the existing test file of each component.

Each minor gets a failing test first, then the fix:

1. A touch long press is cancelled when the pointer moves more than 8 px (`ContextMenu`).
2. Closing a menu focuses its owner with `{ preventScroll: true }`, outside a state updater (`ContextMenu`).
3. The BeatInspector `pickRequest` counter does not reopen the picker when the component remounts; it compares the counter against the value it saw at mount.
4. A right click inside an open material menu does not reopen it (`MaterialsPanel`). Render the menu element outside the row's `<li>`.
5. Dragging a clip over an incompatible lane shows a not-allowed state on that lane (`data-drop="refused"` and the not-allowed cursor) (spec 5.1).
6. "Move to track" stays visible: disabled with a reason when nothing fits or the clip is locked (`timeline_menus.ts`).
7. A typed time that the editor refused returns to the clip's real time (`TimelineInspector`).
8. `formatTimecode`'s doc comment sits above `formatTimecode` again (`timeline_domain.ts`; no test, a comment move).
9. A second track of one kind has a numbered accessible name, such as "Overlay 2 track" (`TimelineTrack`).
10. The shortcut list includes Backspace, Ctrl+Shift+Z, Ctrl+/, Ctrl+wheel, Shift+F10 and the Tier 2 keys (Ctrl+A, Ctrl+C, Ctrl+V, Ctrl+D, J, K, L) (`SHORTCUTS`).
11. `ReplaceMediaDialog` shows an image icon for image assets.

- [ ] **Step 1: Write the ten failing tests** (all but item 8). **Step 2:** run them; they fail. **Step 3:** fix each. **Step 4:** run them; they pass.
- [ ] **Step 5: Commit**: `git commit -m "Fix the Tier 1 review leftovers"`.

### Task 13: E2E, carried follow-ups, records and the branch gate

**Files:**
- Modify: `e2e/tests-write/timeline-audit.e2e.ts`. Add write tests:
  - Shift-select two clips and Delete;
  - copy and paste a clip;
  - Ctrl+D;
  - the paste-text chooser placing a new text clip. Use a fixed `paste` event with `DataTransfer`, never reading the real clipboard.
  - Fit set to Contain;
  - Fade in 0.5 s;
  - close all gaps on a track;
  - search the assets.
- Modify: `e2e/tests/` (read-only):
  - fix the script-panel height test;
  - fix the three tests that assumed another draft's 34.5 s total, by reading the total from the page instead of hard-coding it (carried from Tier 1).
- Modify: `CHANGELOG.md`. Add the Tier 2 entry. It also records PR #122's merge (ccddab63, 2026-11-08), which is not recorded yet.
- Modify: `docs/ROADMAP.md`, adding a status line only.
- Modify: the spec's §6, if a ruling corrected it.

- [ ] **Step 1:** Run the full checks: `dash_full.sh full`, the full `make test`, `make lint`, and `bun test` in `renderer/`. Record the counts.
- [ ] **Step 2:** Run the final whole-branch review on the most capable model (executing-plans). Fix every Critical and Important finding test-first.
- [ ] **Step 3:** Write the CHANGELOG entry, the ROADMAP line and the ledger. End with **Next steps**:
  - the operator gates, each needing its own authorization: write token, push and PR, deploy of the branch image, live write e2e, merge;
  - then Tier 3.
- [ ] **Step 4: Commit**: `git commit -m "Record Studio Timeline Tier 2"`. Stop here. Push, deploy, e2e write runs and merge each wait for the operator.

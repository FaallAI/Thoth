# Studio Timeline Tier 3a Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pro editing on the Timeline:
- two operator rulings;
- clip speed;
- slip and roll edits;
- markers on the ruler;
- menu editing on phones.

Filmstrips, waveforms and the volume line are Tier 3b, a separate plan.

**Architecture:**
- Speed, slip and markers are new typed operations and fields. They are mirrored in `timeline_operations.py` and `timeline_domain.ts`.
- New fields are stored only when used, so a rollback to Tier 2 images stays safe.
- Roll is two existing trims in one patch.
- Phones keep the view-only lanes but get the existing clip, lane and track menus by long press.

**Tech Stack:** Python 3.12 (pydantic 2.14, FastAPI), React 19 + TypeScript (Bun, happy-dom), Remotion 4.0.538 (`@remotion/media` `Video`, `remotion` `Audio`), tester-army/e2e 0.21.

**Spec:** `docs/superpowers/specs/2026-11-08-studio-timeline-track-design.md` §7, with three operator decisions from 2026-11-09:
- Phones get "menu only" editing.
- Tier 3 splits into 3a (this plan) and 3b (filmstrips, waveforms, volume line).
- The two Tier 2 open questions are settled as Tasks 1 and 2.

Branch `feat/studio-timeline-tier3a` from master `1754d852`.

## Global Constraints

- One user action is one patch: one revision and one undo step, even with several operations (spec §3).
- **New fields have defaults** so stored documents and older clients still decode (AGENTS.md).
  - Tier 2 servers forbid unknown fields, so `speed` and `markers` are stored only when used (`Field(exclude_if=…)`), like the Tier 2 video fades.
- **Every new operation is mirrored** in `python/src/thoth_control_plane/domain/timeline_operations.py` and `dashboard/src/features/studio/timeline_domain.ts`, with tests on both sides.
  - After a Python contract change, regenerate:
    - `D:/thoth-tmp/fixes/export_openapi.sh`, which writes `python/openapi.json`;
    - `bun run generate:control-plane-types` in `dashboard/`;
    - `bun run schema` in `renderer/`.
- Dashboard strings come in English and Indonesian (`lib/i18n.ts`).
- **Keyboard shortcuts** act only inside the Studio editing area, and never while focus is in an input, textarea, select or contenteditable.
- **No menu entry or shortcut spends money.** Re-voice, narration, Assist and render stay where they are.
- **Locked clips and tracks stay untouchable.** A refusal is all or nothing, with its reason in the Timeline status line.
- **Commits:** one subject line, `git commit -m "<subject>"`, no body, no trailer, no AI attribution (AGENTS.md).
- **e2e:**
  - Tests are deterministic, with `screen` locators and `expect` and no `agent.*`.
  - Write tests run only in the throwaway project with a one-day write token. Each new token needs the operator's approval.
- **Source maths.** Speed is one of the presets `0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4`.
  - All source-frame maths uses the integer percentage `pct = round(speed * 100)`.
  - Spans round up (`ceil(duration * pct / 100)`), and offsets round down (`floor(frames * pct / 100)`).
  - Python and TypeScript must give the same integers, so never use `round()` (Python rounds halves to even).

## Decisions taken in this plan (the builder's calls, §8; listed for the operator)

- **Speed keeps a clip's place and length on the timeline.** It changes how much source the clip plays.
  - Why: scenes and narration own the timing here, and a length change would ripple through both.
  - At 2× a 5 s clip plays 10 s of source. A speed whose source runs out is refused ("The source is too short for this speed"), unless the clip holds its last frame.
- **Pitch.** A faster or slower video keeps its pitch (`preservePitch`), so speech stays natural.
- **Slip is Alt+drag on a clip's body.** The picture moves with the pointer, so dragging right shows earlier source.
  - The Inspector's "Source start" field does the same by number. It is the keyboard and accessible path.
- **Roll is Alt+drag on a trim handle whose edge touches a neighbour on the same track.**
  - A roll that would cross a scene boundary is refused ("This cut is a scene boundary. Resize the scene in Story instead"), because a clip must stay inside its scene.
  - Without Alt, or without a touching neighbour, the handle trims as before.
- **Markers.** M adds a marker at the playhead.
  - A marker is a button on the ruler. Clicking it moves the playhead there.
  - Its menu offers Rename…, Move to playhead and Delete.
  - Markers are never rendered into the video.
  - When the document gets shorter, a marker past the end moves to the last frame.
- **Phones (below 1024).**
  - Tapping selects a clip. A long press opens the same clip, lane and track menus as on desktop.
  - Drag, trim, marquee, asset drops and keys stay off.
  - The Timeline pane shows the preview above the lanes.

## Review Focus

1. **A sped-up clip that is trimmed at its start or split** must keep showing the same source frames. A wrong multiplier jumps the picture. Test: Task 3.
2. **A re-voice of a sped-up or held clip** must not overrun its source. `_retime`'s remaining-source maths divides by the speed. Test: Task 3.
3. **Blur regions on a sped-up or slipped clip** stay on their source frames, so a subtitle stays covered. Test: Task 4 (`blur.ts`).
4. **A roll or slip at a limit** refuses with its reason before the save, never with a server 422. The limits are a scene boundary, the source's start or end, and a one-frame clip. Test: Task 6.
5. **A re-voice that shortens the document** keeps its markers and moves the late ones to the last frame. A marker past the canvas end would fail validation after the voices were paid for. Test: Task 7.

---

### Task 1: A duplicated clip drops its Story role (operator, 2026-11-09)

**Files:**
- Modify: `python/src/thoth_control_plane/domain/timeline_operations.py` (`_duplicate_clip`)
- Modify: `dashboard/src/features/studio/timeline_domain.ts` (`duplicate_clip` branch of `applyTimelineOperation`)
- Modify: `docs/superpowers/specs/2026-11-08-studio-timeline-track-design.md` §4 (append decisions 5–7 from this plan's Spec line)
- Test: `python/tests/domain/test_timeline_operations.py`, `dashboard/src/features/studio/timeline_domain.test.ts`

**Interfaces:** Produces nothing new. `split_clip` keeps the role on both parts: both halves are still the Hook.

- [ ] **Step 1: Write the failing tests.**
  - Python: `test_a_duplicate_drops_its_story_role`. Duplicate a video clip with `source_role="hook"`, then assert `copy.source_role is None` and `original.source_role == "hook"`.
  - TS: the same, named `"a duplicate drops its Story role"`.
- [ ] **Step 2: Run them.**
  - `make test T=python/tests/domain/test_timeline_operations.py`
  - `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/fixes/dash_test.sh src/features/studio/timeline_domain.test.ts`

  Expected: both FAIL on `"hook"`.
- [ ] **Step 3: Implement.** Set `copy.source_role = None` beside the existing `scene_id` reset, on both sides.
- [ ] **Step 4: Run both again.** Expected: PASS.
- [ ] **Step 5: Commit** "Drop the Story role from a duplicated clip".

### Task 2: Pasted text prefers a visible track, and says when it lands on a hidden one (operator, 2026-11-09)

**Files:**
- Modify: `dashboard/src/features/studio/timeline_edits.ts` (`Edit`, `pasteTextOperations`)
- Modify: `dashboard/src/features/studio/Timeline.tsx` (status line)
- Modify: `dashboard/src/lib/i18n.ts`
- Test: `timeline_edits.test.ts`, `Timeline.test.tsx`

**Interfaces:** Produces `export type Notice = "hidden_track"` and `Edit = { operations; refusal?: Refusal; notice?: Notice }`.

- [ ] **Step 1: Write the failing tests.**
  - `"pasted text goes to a visible overlay track before a hidden one"`: two unlocked overlay tracks, the first hidden. Expect the `track_id` of the second and no `notice`.
  - `"pasted text on a hidden-only overlay lands there and notices"`: expect that track and `notice === "hidden_track"`.
  - The same two tests for `new_caption`.
  - In `Timeline.test.tsx`: after a paste to a hidden-only track, the status line reads `studio.paste.hiddenTrack`.
- [ ] **Step 2: Run them.** Expected: FAIL (a hidden track is picked, and there is no notice).
- [ ] **Step 3: Implement.**
  - Pick `tracks.find(kind && !locked && !hidden) ?? tracks.find(kind && !locked)`, and set `notice` when the pick is hidden.
  - The Timeline's `commitEdit` shows the notice in the existing status line after a successful commit.
  - Strings:
    - en: "Pasted on a hidden track. Show the track to see it."
    - id: "Ditempel di track yang tersembunyi. Tampilkan track itu untuk melihatnya."
- [ ] **Step 4: Run them again.** Expected: PASS.
- [ ] **Step 5: Commit** "Paste text on a visible track first, and say when it lands on a hidden one".

### Task 3: Clip speed: model, operation and every source reader (server)

**Files:**
- Modify: `python/src/thoth_control_plane/domain/edit_document_v2.py`
- Modify: `python/src/thoth_control_plane/domain/timeline_operations.py`
- Modify: `python/src/thoth_control_plane/assembly/narration_timeline.py`
- Regenerate: `python/openapi.json`, `dashboard/src/api/generated/control-plane.ts`, `renderer/src/generated/edit-document.schema.json`
- Test:
  - `python/tests/domain/test_edit_document_v2.py`
  - `python/tests/domain/test_timeline_operations.py`
  - `python/tests/assembly/test_narration_timeline.py`

**Interfaces:**
- **Produces, in `edit_document_v2.py`:**
  - `PlaybackSpeed = Literal[0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]`.
  - `speed: PlaybackSpeed = Field(default=1.0, exclude_if=lambda speed: speed == 1.0)` on `TimelineVideoClip` and `TimelineAudioClip`.
  - `def speed_percent(clip) -> int`: 100 for clips without speed.
  - `def source_span(clip) -> int`: `ceil(duration * pct / 100)`, integer maths.
  - `def frames_left(clip, asset: AssetRef) -> int`: the timeline frames until the source ends, `floor((asset.duration_in_frames - clip.source_from_frame) * 100 / pct)`.
- **Produces, in `timeline_operations.py`:** `SetClipSpeed(kind="set_clip_speed", operation_id, clip_id, speed: PlaybackSpeed)`, added to the operation union.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_clip_at_normal_speed_stores_no_speed`: `model_dump(mode="json")` has no `speed` key.
  - `test_a_stored_clip_without_speed_decodes`.
  - `test_a_clip_at_2x_needs_twice_its_length_in_source`: a 60-frame clip at 2× on a 100-frame asset fails "clip range exceeds source asset duration". On a 120-frame asset it passes. With `hold_after_source` on video it passes on the 100-frame asset.
  - `test_set_clip_speed_sets_the_speed_and_marks_the_clip_edited`, plus refusals:
    - a locked clip;
    - an image asset ("an image has no speed");
    - a text clip.
  - `test_a_trim_start_on_a_2x_clip_moves_its_source_twice_as_far`: trim start +10 frames, then `source_from_frame` grows by 20.
  - `test_a_split_of_a_1_5x_clip_starts_the_right_part_at_the_left_span`: a 31-frame left part at 1.5× gives right `source_from_frame == floor(31*150/100) == 46`. Both parts keep the speed.
  - `test_a_retimed_2x_clip_stops_where_its_source_ends`, in `test_narration_timeline.py`: `_retime`'s source-length clamp (lines 436 and 452 today) uses `frames_left`.
- [ ] **Step 2: Run them.** `make test T=python/tests/domain` and `make test T=python/tests/assembly/test_narration_timeline.py`. Expected: FAIL (`speed` is unknown).
- [ ] **Step 3: Implement.**
  - Add the field, the helpers and `SetClipSpeed`.
  - `_validate_clip_asset` uses `source_span`.
  - `_trim_clip_start` adds `floor(delta * pct / 100)`. A negative delta uses the same floor of a negative value, and the result must stay ≥ 0, as today.
  - `_split_clip` adds `floor(left_duration * pct / 100)`.
  - `_retime` uses `frames_left`.
  - `replace_clip_asset` keeps the speed.
  - Then regenerate the three contract files.
- [ ] **Step 4: Run the tests, then the gates.** Run the Step 2 commands, then `make test` (full) and `make lint`. Expected: PASS, lint clean.
- [ ] **Step 5: Commit** "Add clip speed to the document and its source maths".

### Task 4: Clip speed in the dashboard and the renderer

**Files:**
- Modify: `dashboard/src/features/studio/timeline_domain.ts` (mirror `set_clip_speed`, `speedPercent`, `sourceSpan`, `framesLeft`, trim and split maths)
- Modify: `TimelineInspector.tsx` ("Speed" select)
- Modify: `i18n.ts`
- Check with grep and fix: every other `source_from_frame` reader that measures source length, namely `SceneAudioInspector.tsx` and `story/story_edits.ts`
- Modify: `packages/remotion-composition/src/AdvancedTimelineComposition.tsx`
- Modify: `packages/remotion-composition/src/blur.ts`
- Test:
  - `timeline_domain.test.ts`
  - `TimelineInspector.test.tsx`
  - `AdvancedTimelineComposition.test.tsx`
  - the `blur.ts` tests beside it

**Interfaces:**
- **Consumes:** the generated `PlaybackSpeed` type and the `speed` field from Task 3.
- **Produces, in `timeline_domain.ts`:**
  - `export function speedPercent(clip): number`;
  - `export function sourceSpan(clip): number`;
  - `export function framesLeft(clip, asset): number`.

  They use the same integer maths as Python.
- **Produces:** `Refusal` gains `"no_source"`.

- [ ] **Step 1: Write the failing tests.**
  - **TS mirror:** the Task 3 trim and split cases, with the same numbers.
  - **Inspector:**
    - A video clip shows a "Speed" combobox with the nine presets labelled `0.25×`…`4×`.
    - Choosing `2×` commits one `set_clip_speed`.
    - An image clip has no Speed control.
    - A speed the source cannot feed is refused in place with "The source is too short for this speed" (refusal `no_source`).
  - **Composition:**
    - A 2× video clip passes `playbackRate={2}` and `preservePitch` to `Video`.
    - A clip without speed passes neither, so its props are unchanged.
    - An audio clip passes `playbackRate`.
    - A held 2× clip holds at `framesLeft - 1`.
  - **`blur.ts`:** at timeline frame f, a 2× clip's source frame is `trim + floor(f*200/100)`.
- [ ] **Step 2: Run them.** `dash_test.sh src/features/studio` and `cd renderer && bun test`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - **Before writing code:** check `trimBefore` with `playbackRate` (trimBefore counts source frames) against the Remotion 4.0.538 docs through Context7. Record the result in the ledger.
  - **If `remotion`'s `Audio` cannot keep pitch:** record a `Ruling:` line in the ledger. Either keep the pitch shift for music, or move to `@remotion/media` `Audio`.
  - Add the strings:
    - en "Speed", "The source is too short for this speed";
    - id "Kecepatan", "Sumber terlalu pendek untuk kecepatan ini".
- [ ] **Step 4: Run them again, then the gates.** Run the Step 2 commands, then `dash_full.sh full` (tests, `tsc -b`, build). Expected: PASS, clean.
- [ ] **Step 5: Commit** "Play clips at their speed in the preview and the render, and set it in the Inspector".

### Task 5: Slip: an operation, an Inspector field and Alt+drag on a clip

**Files:**
- Modify: `timeline_operations.py` (`SlipClip`)
- Modify: `timeline_domain.ts` (mirror)
- Modify: `timeline_edits.ts`
- Modify: `TimelineClip.tsx` (`GestureMode`)
- Modify: `Timeline.tsx` (`startGesture`)
- Modify: `TimelineInspector.tsx`
- Modify: `studio_keys.ts` (shortcut list row)
- Modify: `i18n.ts`
- Regenerate the contracts
- Test: the Python and TS operation tests, `timeline_edits.test.ts`, `Timeline.test.tsx`, `TimelineInspector.test.tsx`

**Interfaces:**
- **Produces, Python and TS:** `SlipClip(kind="slip_clip", operation_id, clip_id, source_from_frame: FrameStart)`.
  - It works on an unlocked video clip with a movie asset, or an audio clip.
  - Bounds: `source_from_frame ≥ 0`, and `source_from_frame + source_span ≤ asset duration`. A video clip that holds its last frame needs only `source_from_frame < asset duration`.
- **Produces, `timeline_edits.ts`:** `export function slipClip(doc, clipId, sourceFrom): Edit`.
  - It clamps to the bounds.
  - It refuses `locked`, `still` (an image has no source time) and `no_source` (the clip is as long as its source).
- **Produces:**
  - `Refusal` gains `"still"`, and reuses `"no_source"` from Task 4;
  - `GestureMode` gains `"slip"`.

- [ ] **Step 1: Write the failing tests.**
  - **Python:** `test_slip_moves_only_the_source`. `from_frame`, `duration_in_frames`, `blur_regions` and `volume_keyframes` stay unchanged. Refusals: below 0, past the source end, an image, a locked clip.
  - **TS edits:**
    - `"slipClip clamps to the source"`;
    - `"slipClip refuses an image"`;
    - `"a clip as long as its source cannot slip"`.
  - **Timeline:**
    - Alt+pointerdown on a clip body, a move of +30 px at zoom 1, then pointerup commits one `slip_clip` with `source_from_frame = start - 30`, clamped at 0.
    - A plain drag still moves the clip.
    - The patch is previewed while dragging (`preview_timeline_operations`).
  - **Inspector:**
    - A "Source start" field in seconds commits `slip_clip`.
    - Its maximum is `(asset - span) / fps`.
    - It is absent on images and text.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `TimelineClip` passes `event.altKey` with a body press, so the gesture becomes `slip`.
  - Shift and Ctrl presses keep their Tier 2 meaning (they select and never drag).
  - Shortcut row: "Alt+drag a clip: slip its content".
  - Strings, en: "Source start", "An image has no source time", "The clip already shows its whole source".
- [ ] **Step 4: Run them again, then the gates.** Python full and lint, then `dash_full.sh full`. Expected: PASS.
- [ ] **Step 5: Commit** "Slip a clip's content by Alt+drag or by its source start".

### Task 6: Roll: Alt+drag on a cut between two touching clips

**Files:**
- Modify: `timeline_edits.ts`
- Modify: `Timeline.tsx`
- Modify: `TimelineClip.tsx`
- Modify: `studio_keys.ts`
- Modify: `i18n.ts`
- Test: `timeline_edits.test.ts`, `Timeline.test.tsx`, `python/tests/domain/test_edit_document_operations.py`

**Interfaces:**
- **Consumes:** `sourceSpan` and `framesLeft` (Task 4), and the existing `trim_clip_end` and `trim_clip_start` operations.
- **Produces:**
  - `export function rollCut(doc, leftId, rightId, frame): Edit`. It returns `[trim_clip_end(left, frame), trim_clip_start(right, frame)]` in one patch.
  - Refusals:
    - `not_touching` (the left end is not the right start, or the tracks differ);
    - `locked`;
    - `scene_cut` (both clips have scenes, and the scenes differ);
    - `edge` (either clip would drop below one frame);
    - `no_source`, in two cases:
      - the left clip's source would run out (unless it holds its last frame);
      - the right clip's `source_from_frame` would go below 0.
  - `Refusal` gains `"not_touching" | "scene_cut"`.
  - `GestureMode` gains `"roll"`.

- [ ] **Step 1: Write the failing tests.**
  - **TS edits:**
    - `"rollCut moves the cut and keeps the total"`: left ends at 60, right starts at 60, roll to 75. Expect left duration +15, and right `from_frame` 75, duration −15, `source_from_frame` +15 (1×).
    - One test per refusal above.
    - `"rollCut on 2x clips moves the right source by twice the frames"`.
  - **Python:** `test_a_roll_patch_on_main_video_validates`. Two touching Main video clips in one scene, then `apply_edit_operations` with both trims in either order. Expect no overlap error, and the same total.
  - **Timeline:**
    - Alt+pointerdown on clip A's end handle, where clip B starts at that frame, then a move of +15 px and release commits the two-trim patch as one undo step.
    - Without Alt, the same move commits a single `trim_clip_end`, as before.
    - A refused roll shows its reason in the status line and commits nothing.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - The neighbour for `trim_end` is the clip on the same track whose `from_frame` equals this clip's end. For `trim_start`, it is the clip whose end equals this clip's start.
  - Shortcut row: "Alt+drag a cut between two clips: roll it".
  - Strings, en: "These clips do not touch", "This cut is a scene boundary. Resize the scene in Story instead".
- [ ] **Step 4: Run them again, then the gates.** Expected: PASS, then `dash_full.sh full`, Python full and lint.
- [ ] **Step 5: Commit** "Roll a cut between two touching clips with Alt+drag".

### Task 7: Markers: field and operations (server)

**Files:**
- Modify: `edit_document_v2.py`
- Modify: `timeline_operations.py`
- Modify: `edit_document_operations.py` (call `fit_markers` beside `fit_fades`)
- Modify: `narration_timeline.py` (`_retime` payload)
- Regenerate the contracts
- Test: `test_edit_document_v2.py`, `test_timeline_operations.py`, `test_narration_timeline.py`

**Interfaces:**
- **Produces, the marker model:**
  - `class TimelineMarker(StrictModel)`, with fields `marker_id: OpaqueId`, `frame: FrameStart` and `label: Annotated[str, Field(max_length=60)] = ""`.
  - `EditDocumentV2.markers: Annotated[list[TimelineMarker], Field(max_length=100)] = Field(default_factory=list, exclude_if=lambda markers: not markers)`.
  - Validation: marker ids are unique, and `frame < canvas.duration_in_frames`.
- **Produces, the operations:**
  - `AddMarker(kind="add_marker", operation_id, marker_id, frame, label="")`;
  - `SetMarker(kind="set_marker", operation_id, marker_id, frame, label)`;
  - `RemoveMarker(kind="remove_marker", operation_id, marker_id)`.
  - Refusals: an id reused, an unknown marker, and a 101st marker.
- **Produces, the fitter:** `def fit_markers(document) -> None` moves every marker past the end to `duration - 1`.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_document_without_markers_stores_none`: no `markers` key in the JSON dump.
  - `test_markers_must_sit_inside_the_canvas`.
  - Add, set and remove, each with its refusals.
  - `test_an_edit_that_shortens_the_document_moves_late_markers_to_the_last_frame`.
  - `test_a_revoice_that_shortens_the_draft_keeps_its_markers_inside`, in `test_narration_timeline.py`: `_retime` clamps the payload's markers to `total - 1`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement, then regenerate the contracts.**
- [ ] **Step 4: Run them again.** Expected: PASS. Then `make test` (full) and `make lint`.
- [ ] **Step 5: Commit** "Add markers to the document".

### Task 8: Markers on the ruler

**Files:**
- Modify: `timeline_domain.ts` (mirror, `fitMarkers`)
- Modify: `timeline_edits.ts` (`addMarker`)
- Modify: `Timeline.tsx` (ruler buttons, M key, marker menu)
- Modify: `timeline_menus.ts` (`markerMenu`)
- Create: `dashboard/src/features/studio/MarkerNameDialog.tsx`
- Modify: `studio_keys.ts` (`add_marker` "M")
- Modify: `i18n.ts`
- Test:
  - `timeline_domain.test.ts`
  - `timeline_edits.test.ts`
  - `Timeline.test.tsx`
  - `MarkerNameDialog.test.tsx`
  - `studio_keys.test.ts`

**Interfaces:**
- **Consumes:** the Task 7 operations, through the generated types.
- **Produces:**
  - `export function addMarker(doc, frame): Edit`. It refuses `taken` when a marker already sits on that frame, and `too_many` at 100.
  - `Refusal` gains `"taken" | "too_many"`.
  - `markerMenu(context, marker, { onRename })`, with the entries Rename…, Move to playhead and Delete.

- [ ] **Step 1: Write the failing tests.**
  - **M key:** M at the playhead commits one `add_marker`. M inside the heading field does nothing.
  - **Ruler buttons:** the ruler shows a button named "Marker 1 at 0:02" for an unnamed marker, or "Hook beat at 0:02" when it has a label. Clicking it moves the playhead there.
  - **Marker menu:**
    - Delete commits `remove_marker`.
    - Move to playhead commits `set_marker` with the playhead frame.
    - Rename… opens "Rename marker". Save commits `set_marker` with the label, and focus returns to the marker.
  - **Shortcut list:** the list shows "M: add a marker".
  - **Mirror:** `fitMarkers` matches the Python cases.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - The dialog follows `PasteTextDialog`: `role=dialog`, a text input with `maxLength=60`, and Escape closes it.
  - Strings in en and id.
- [ ] **Step 4: Run them again, then the gates.** Expected: PASS, then `dash_full.sh full`.
- [ ] **Step 5: Commit** "Add, name, move and delete markers on the ruler".

### Task 9: Phones: the editing menus by long press, and the preview above the lanes

**Files:**
- Modify: `Timeline.tsx` (bind `clipMenu`, `laneMenu` and `nameMenu` when `readOnly`)
- Modify: `TimelineClip.tsx` (the read-only press keeps the menu handlers and still selects)
- Modify: `GuidedStudio.tsx` (on the compact Timeline pane, the preview shows above the lanes)
- Modify: `i18n.ts` (`studio.timeline.viewOnly`)
- Modify: `e2e/e2e.write.config.ts` (target `rw430`, 430×932, en-US, copied from `rw1440`)
- Test: `Timeline.test.tsx`, `TimelineClip` tests, `GuidedStudio.test.tsx`

**Interfaces:**
- **Consumes:** the Tier 1 `ContextMenu` long press (`LONG_PRESS_SLOP=8`).
- **Produces:** no new props. `readOnly` now means no direct manipulation (no drag, trim, marquee, drop or keys). It no longer means "no edits".

- [ ] **Step 1: Write the failing tests.**
  - **Long press and menus:**
    - In a read-only Timeline, a long press on a clip opens "Clip actions". Its Split, Delete and Duplicate entries commit as on desktop.
    - The lane and track menus open the same way.
    - A press that moves more than 8 px still scrolls and opens nothing.
  - **Direct manipulation stays off:** no trim handles render, and a drag commits nothing.
  - **Banner:**
    - en: "Tap a clip to select it. Press and hold for its menu. Drag and trim on a wider screen."
    - id: "Ketuk klip untuk memilihnya. Tekan lama untuk menunya. Seret dan trim di layar yang lebih lebar."
  - **Preview:** GuidedStudio at the phone viewport, in the Timeline pane, renders the preview region and the lanes together, with the preview first.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them again, then the gates.** Expected: PASS, then `dash_full.sh full`.
- [ ] **Step 5: Commit** "Open the editing menus by long press on phones, with the preview above the lanes".

### Task 10: e2e

**Files:**
- Modify: `e2e/tests-write/timeline-audit.e2e.ts`
- Create: `e2e/tests/studio-phone.e2e.ts` (read-only, `w430`)

**Interfaces:** Consumes the existing helpers (`clipOnTimeline`, `twoMainClips`, `mainLaneAt`, `startsOnMain`) and the saved-document reader those tests already use.

- [ ] **Step 1: Write the write tests.** Each reads the saved document back.
  - `speed: Speed 2x is saved`: the Inspector Speed combobox gives the saved clip `speed === 2`.
  - `slip: Source start 1 s is saved`: `source_from_frame === fps`.
  - `roll: Alt+drag the cut between two clips moves it`:
    - S splits a clip at its middle.
    - Alt+drag the cut 1 s right.
    - The left clip gets longer by fps frames, and the total stays the same.
  - `markers: M adds a marker to the ruler`: the ruler button "Marker 1" is visible, and the saved `markers.length === 1`.
  - `phone: a long press opens the clip menu, and Split is saved`, at `rw430`.

    Use e2e's long press if 0.21 has one (`npx e2e guide writing-tests`). Otherwise open the menu with `secondaryTap`, and record that as a ledger ruling.
- [ ] **Step 2: Write the read-only test.** `tests/studio-phone.e2e.ts`, at `w430`:
  - the Timeline pane shows the preview above the lanes;
  - a long press on a clip opens "Clip actions", and nothing is chosen;
  - the banner text.
- [ ] **Step 3: Run the read-only test against the current stage1.** Expected: FAIL. Stage1 runs Tier 2, so this is the red step. The write tests run at the deploy gate.
- [ ] **Step 4: Commit** "Add Tier 3a e2e tests".

### Task 11: Records and the final review

**Files:**
- Modify: `CHANGELOG.md` (a new top entry, "Studio Timeline Tier 3a")
- Modify: `docs/ROADMAP.md` (a status line; additions only)
- Modify: `.superpowers/sdd/2026-11-09-studio-timeline-tier3a/progress.md`

- [ ] **Step 1: Run the full verification.**
  - `make test`;
  - `make lint`;
  - `dash_full.sh full`;
  - `cd renderer && bun test`;
  - the read-only e2e at w1440: `studio-audit-fixes` and `studio-shell-v2`, which this tier must not change.
- [ ] **Step 2: Run the final whole-branch review** (executing-plans) with the Review Focus above. Fix Critical and Important findings test-first. Ledger the minors.
- [ ] **Step 3: Write the CHANGELOG entry.**
  - **Merge record:** PR #123 merged as `1754d852` on 2026-11-09. Stage1 runs `7b5d04f8`, the same product code.
  - **Operator rulings of 2026-11-09:**
    - the phone decision;
    - the 3a/3b split;
    - the two Tier 2 answers.
  - **What 3a adds.**
  - **The builder's decisions above.**
  - **Rollback note:** a draft that used speed or markers will not open on Tier 2 images; every other draft still does.
  - **Verification, deferred minors, and the eight Tier 2 minors still carried.**
  - **Next steps:**
    - operator gates (token, push and PR, branch deploy, write e2e, operator try, merge);
    - then Tier 3b (filmstrips, waveforms, the audio volume line).
- [ ] **Step 4: Commit** "Record Studio Timeline Tier 3a".

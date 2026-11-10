# Studio Effects Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the edit document, the composition and Studio the effects Style A and Style B need: keyframed moves, blur-fill, dim, marks, the `boxed` and `kinetic` caption styles and the `card` text style.

**Architecture:** New optional fields on the v2 document, with typed operations that the server and the Studio client apply alike. One TypeScript module in `@thoth/remotion-composition` holds the move maths for the composition and the client. Python and TypeScript run the same JSON cases, so the two implementations cannot drift. The composition draws every effect once, for the preview and the render.

**Tech Stack:** Python 3.12 with Pydantic (control plane), React 19 + TypeScript + Bun (dashboard), Remotion 4.0.538 (`packages/remotion-composition`, `renderer/`).

**Spec:** `docs/superpowers/specs/2026-11-09-studio-effects-layer-design.md`

## Global Constraints

- Every new field is optional, defaults to what renders today, and is left out of the stored JSON when unused (`Field(..., exclude_if=...)`). A clip without effects must dump exactly as before.
- Style names stay allow-listed in the composition; every coordinate and frame is bounded by the schema.
- Each Studio action is one operation or one `commit_operations` batch, so one undo step.
- Moves use timeline frames relative to the clip. Marks use source frames, as blur regions do.
- Verification is offline only. Use these commands (run from Git Bash):
  - Python: `MSYS_NO_PATHCONV=1 wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER && make test T=<path>'` and `make lint`.
  - Dashboard: `bash D:/thoth-tmp/fixes/fw_check.sh <test paths>`, and in full `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/fixes/dash_full.sh full`.
  - Composition and renderer: `cd renderer && bun test`.
- Contracts change in Task 1. Regenerate them with:
  - `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/fixes/export_openapi.sh`;
  - `cd dashboard && bun run generate:control-plane-types`;
  - `cd renderer && bun run schema`.
- Commit subjects are one line of at most 72 characters, with no body and no trailer.
- No push, deploy, golden approval or live run without the operator's separate word.
- Strings the user sees go through `t()`, with English and Indonesian entries in `dashboard/src/lib/i18n.ts`.

## Review Focus

- A trim start that passes every keyframe must keep the picture's scale and place at the new start. Pinned in Task 2.
- A clip at speed 2 must show a mark in its source-frame window, not its timeline-frame window. Pinned in Task 4.
- A mark on a cropped clip must not draw outside the visible media. Pinned in Task 4.
- A `kinetic` cue with no word timings, or with one word, must still show its text. Pinned in Task 4.
- A split exactly on a keyframe must not duplicate or lose it. Pinned in Task 2.

---

### Task 1: Document fields and contracts

**Files:**
- Modify: `python/src/thoth_control_plane/domain/edit_document_v2.py`
- Test: `python/tests/domain/test_edit_document_v2.py`
- Regenerate: `python/openapi.json`, `dashboard/src/api/generated/control-plane.ts`, and the renderer schema

**Interfaces:**
- Produces, in `edit_document_v2.py`:
  - types: `Background = Literal["none", "blur_fill"]`, `Ease = Literal["linear", "ease_out", "ease_in_out", "hold"]`, `Dim = Annotated[float, Field(ge=0.0, le=0.8)]`;
  - `class MoveKeyframe(StrictModel)` with `frame: FrameStart`, `scale: Scale = 1.0`, `x: Offset = 0.0`, `y: Offset = 0.0`, `ease: Ease = "ease_in_out"`;
  - `MoveKeyframes = Annotated[list[MoveKeyframe], Field(max_length=60)]`;
  - `class Mark(StrictModel)` with `kind: Literal["box", "arrow"]`, `x: NormalizedUnit`, `y: NormalizedUnit`, `w: NormalizedUnit = 0.0`, `h: NormalizedUnit = 0.0`, `side: Literal["top", "bottom", "left", "right"] = "top"`, `from_frame: FrameStart`, `to_frame: Frame`, `color: Literal["accent", "alert"] = "accent"`.
- On `TimelineVideoClip`:
  - `moves: MoveKeyframes`, default `[]`, left out when empty;
  - `background: Background`, default `"none"`, left out when `"none"`;
  - `dim: Dim`, default `0.0`, left out when `0.0`.
- On `Emphasis`: `marks: Annotated[list[Mark], Field(max_length=12)]`, default `[]`, left out when empty.
- `CaptionStyle` gains `"boxed"` and `"kinetic"`.

- [ ] **Step 1: Write the failing tests**

- `test_a_clip_without_effects_dumps_as_before`: a video clip built with defaults gives a `model_dump()` that has no `moves`, `background` or `dim` key, and its `emphasis` is exactly `{"highlight": False, "arrow": False}`.
- `test_effects_round_trip`: a clip with two moves, `background="blur_fill"`, `dim=0.5` and one box mark survives `model_validate(model_dump())` unchanged.
- `test_moves_must_increase_and_stay_inside_the_clip`: frames `[0, 0]` are rejected, and a frame equal to `duration_in_frames` is rejected, by the document validator with "moves must be increasing and inside the clip".
- `test_a_box_needs_a_size_and_stays_inside`: a box with `w=0`, and one with `x + w > 1`, are rejected. An arrow with `w=h=0` is accepted.
- `test_a_mark_window_must_end_after_it_starts`: `to_frame == from_frame` is rejected.
- `test_dim_is_bounded`: 0.81 is rejected.
- `test_new_caption_styles_validate`: `boxed` and `kinetic` are accepted as a caption clip's `style_slot`.

- [ ] **Step 2: Run them to verify they fail**

Run: `make test T=tests/domain/test_edit_document_v2.py`
Expected: FAIL on the new tests (unknown fields and literals).

- [ ] **Step 3: Implement the fields and validators**

The moves check sits next to the volume keyframe check in `_validate_clips`. The box and window rules live on `Mark` as a `model_validator`, worded like `ClipBlurRegion`'s.

- [ ] **Step 4: Run the tests and regenerate the contracts**

Run the test file again (Expected: PASS), then the three regeneration commands. Then `cd renderer && bun test` and the dashboard `tsc -b` inside `dash_full.sh full`. Expected: both still pass.

- [ ] **Step 5: Commit**

`git commit -m "Add moves, blur-fill, dim, marks and two caption styles"`

---

### Task 2: Move maths and the edit rules (server)

**Files:**
- Create: `python/src/thoth_control_plane/domain/clip_moves.py`
- Create: `packages/remotion-composition/src/move_cases.json`, the shared cases
- Modify: `domain/timeline_operations.py` (`_trim_clip_start`, `_split_clip`, `_replace_clip_asset`), `domain/edit_document_operations.py` (`apply_edit_operations`, `_set_scene_duration`), `assembly/narration_timeline.py` (`_retime`)
- Test: `python/tests/domain/test_clip_moves.py`, `python/tests/domain/test_timeline_operations.py`, `python/tests/assembly/test_narration_timeline.py`

**Interfaces:**
- Produces, in `clip_moves.py`:
  - `ease(kind: Ease, t: float) -> float`: `linear` is t; `ease_out` is `1-(1-t)**2`; `ease_in_out` is `2t**2` below 0.5 and `1-(-2t+2)**2/2` from 0.5; `hold` is 0;
  - `move_at(moves: list[MoveKeyframe], frame: float) -> tuple[float, float, float]`, returning (scale, x, y). Before the first keyframe it is the first one's value; after the last, the last one's. Between two keyframes it interpolates with the earlier keyframe's ease;
  - `shift_moves(moves, delta: int) -> list[MoveKeyframe]`: the clip's start moved by `delta`. Frames shift by `-delta`. Keyframes that fall below 0 are dropped, and a keyframe at 0 holds `move_at(moves, delta)`, with the ease of the segment it sat in;
  - `split_moves(moves, at: int) -> tuple[list, list]`: the left part ends with the value at `at - 1`; the right part starts at 0 with the value at `at`;
  - `stretch_moves(moves, old: int, new: int) -> list`: frames become `floor(frame * new / old)`; keep the first of any frames that collide, and clamp below `new`;
  - `fit_moves(document: EditDocumentV2) -> None`: keyframes at or past `duration_in_frames` are dropped, and one at `duration_in_frames - 1` holds the value there.
- `move_cases.json`: a list of `{ "op": "at" | "shift" | "split" | "stretch" | "fit", "moves": [...], "args": {...}, "expect": ... }`. Task 4's TypeScript tests read the same file.

- [ ] **Step 1: Write the cases and the failing tests**

`move_cases.json` holds at least:
- `at` at a keyframe, between two keyframes for each ease, and before and after;
- `shift` by +10 past every keyframe, the Review Focus case, which expects one keyframe at 0 with the old last value;
- `shift` by -5;
- `split` on a keyframe frame, the Review Focus case: one keyframe per side, no duplicate;
- `split` between keyframes;
- `stretch` 90 to 45 with colliding frames;
- `fit` with keyframes past the end.

`test_clip_moves.py` runs every case. `test_timeline_operations.py` adds:
- `test_trim_start_keeps_the_move_value`;
- `test_split_divides_the_moves`;
- `test_replace_media_drops_marks`;
- `test_trim_end_fits_the_moves`, through `apply_edit_operations`;
- `test_scene_resize_stretches_the_scene_clip_moves`.

`test_narration_timeline.py` adds `test_retime_stretches_moves`.

- [ ] **Step 2: Run them to verify they fail**

Run: `make test T=tests/domain/test_clip_moves.py`, then the two other files. Expected: FAIL (module missing, moves unchanged).

- [ ] **Step 3: Implement `clip_moves.py` and wire it in**

- `_trim_clip_start` calls `shift_moves` with the start delta.
- `_split_clip` calls `split_moves`.
- `_replace_clip_asset` sets `emphasis.marks = []`.
- `_set_scene_duration` stretches the moves of each scene's own clip from its old length to its new one.
- `_retime` stretches a video clip's moves from its old length to the new window.
- `apply_edit_operations` calls `fit_moves` right after `fit_fades`.

- [ ] **Step 4: Run them to verify they pass**

Same commands. Expected: PASS. Then `make test T=tests/domain` and `make test T=tests/assembly`. Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "Keep clip moves in place through trims, splits and retiming"`

---

### Task 3: Operations, on the server and in the Studio client

**Files:**
- Modify: `domain/timeline_operations.py`, `dashboard/src/features/studio/timeline_domain.ts`, `dashboard/src/features/studio/editor_state.ts` (scene resize), and the contracts (regenerate as in Task 1)
- Create: `packages/remotion-composition/src/moves.ts`
- Test: `python/tests/domain/test_timeline_operations.py`, `packages/remotion-composition/src/moves.test.ts`, `dashboard/src/features/studio/timeline_domain.test.ts`

**Interfaces:**
- Produces these operations, each needing an unlocked video clip:
  - `SetClipMoves(kind="set_clip_moves", operation_id, clip_id, moves: MoveKeyframes)`;
  - `SetClipBackground(kind="set_clip_background", operation_id, clip_id, background: Background)`. `blur_fill` also sets `fit="contain"`;
  - `SetClipDim(kind="set_clip_dim", operation_id, clip_id, dim: Dim)`;
  - `SetClipMarks(kind="set_clip_marks", operation_id, clip_id, marks: Annotated[list[Mark], Field(max_length=12)])`.
- `SetTextPlace.style_slot` gains `"card"`.
- `AddClipFromAsset` gains `background: Background | None = None`.
- `moves.ts` exports `ease`, `moveAt`, `shiftMoves`, `splitMoves`, `stretchMoves`, with the same rules and names as Task 2. It is re-exported from `index.ts`.
- `timeline_domain.ts`:
  - applies the four operations, and `"card"`;
  - uses `shiftMoves` and `splitMoves` in `trimClipStart` and `splitClip`;
  - clears marks in `replaceClipAsset`;
  - adds `fitMoves(document)` next to `fitFades`, and calls it where `fitFades` is called;
  - the scene resize in `editor_state.ts` stretches the scene clip's moves.

- [ ] **Step 1: Write the failing tests**

- Python: `test_set_clip_background_blur_fill_sets_contain`, `test_set_clip_moves_outside_the_clip_is_refused`, `test_effect_operations_refuse_a_locked_clip`, `test_set_text_place_card`.
- `moves.test.ts` runs every case in `move_cases.json` through `moves.ts`.
- `timeline_domain.test.ts`: the same four behaviours as the Python tests, and `trim_start keeps the move value` on the client.

- [ ] **Step 2: Run them to verify they fail**

Run: `make test T=tests/domain/test_timeline_operations.py`, `cd renderer && bun test`, and `bash D:/thoth-tmp/fixes/fw_check.sh src/features/studio/timeline_domain.test.ts`. Expected: FAIL.

- [ ] **Step 3: Implement**

Server operations follow the `SetClipMotion` pattern. Regenerate the contracts before the TypeScript work.

- [ ] **Step 4: Run them to verify they pass**

Same commands, plus `make lint` and `dash_full.sh full`. Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "Add effect operations and mirror them in the Studio client"`

---

### Task 4: Drawing the effects

**Files:**
- Create: `packages/remotion-composition/src/effects.ts`, `packages/remotion-composition/src/effects.test.ts`
- Modify: `packages/remotion-composition/src/AdvancedTimelineComposition.tsx`, `packages/remotion-composition/src/story_effects.ts`

**Interfaces:**
- `MotionState` gains `translateY` (default 0). The clip transform becomes `translate(position.x + tx, position.y + ty) scale(position.scale * s)`, and `emphasisBox` uses `translateY`.
- `effects.ts` produces:
  - `markWindowOpen(mark, clip, frame: number): boolean`, where the source frame is `clip.source_from_frame + floor(frame * speedPercent(clip) / 100)`;
  - `markBox(mark, crop, content: Box, position, motion): { left, top, width, height } | null`, which maps media fractions through the crop into the content box, and returns null when the mark lies wholly outside the crop. A box partly outside is cut at the crop edge;
  - `kineticGroups(words: CaptionWord[], max = 4): { from: number; to: number; text: string }[]`. A group ends after `max` words or after `.`, `,`, `?` or `!`. A lone last word joins the group before it.
- Drawing:
  - a clip with `moves` draws through `moveAt`; one without draws through `motionTransform`, as now;
  - `background: "blur_fill"` puts a blurred (48 px) copy of the media, at `cover` and scaled 1.1, behind the clip frame. It shares the clip's fade and has no moves;
  - `dim` is a black layer at that opacity over the clip frame, under its marks;
  - marks: a box is a 6 px outline that draws in over 8 frames; an arrow is the existing arrow shape pointing at (x, y) from `side`, popping in over 5 frames. Colours: `accent` `#ffd23f`, `alert` `#ff3b30`;
  - caption `boxed`: 30 px white text on a solid black box, with padding `6px 14px`, in the existing lower lane;
  - caption `kinetic`: 96 px, weight 800, uppercase white text with a 0 4px 12px black shadow, centred at 45% of the height, showing one `kineticGroups` group at a time. A cue without words shows its whole text;
  - text `card`: a full-frame `#ffffff` card with the heading in `#111111`, 84 px, weight 800, centred, with 80 px side padding.

- [ ] **Step 1: Write the failing tests**

In `effects.test.ts`:
- `a mark opens in its source window at speed 2`: the Review Focus case, a mark at 60 to 90 seen at clip frames 30 to 44;
- `a mark outside the crop is not drawn`, and `a mark partly outside the crop is cut at its edge`, the Review Focus case;
- `kinetic groups break at four words and at punctuation`;
- `kinetic one-word cue is one group`, the Review Focus case;
- `kinetic cue without words keeps its text`, through rendering the cue and finding its text.

Add a rendering test, in the existing style, that a clip with moves, blur-fill, dim and marks has the `clip-blur-fill`, `clip-dim` and `clip-mark` test ids.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd renderer && bun test`. Expected: FAIL.

- [ ] **Step 3: Implement**

Blur-fill for a video source must meet the render-time limit measured in Task 8. Prefer a second muted decode of the same source only if Task 8's measurement allows it.

- [ ] **Step 4: Run them to verify they pass**

Same command. Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "Draw moves, blur-fill, dim, marks and the new styles"`

---

### Task 5: Timeline Inspector controls

**Files:**
- Create: `dashboard/src/features/studio/move_presets.ts`, `dashboard/src/features/studio/move_presets.test.ts`
- Modify: `dashboard/src/features/studio/TimelineInspector.tsx`, `dashboard/src/features/studio/TimelineClip.tsx`, `dashboard/src/features/studio/CaptionTextInspector.tsx`, `dashboard/src/lib/i18n.ts`
- Test: `dashboard/src/features/studio/TimelineInspector.test.tsx`, `dashboard/src/features/studio/Timeline.test.tsx`

**Interfaces:**
- `move_presets.ts` produces `movePreset(kind: "punch_in" | "push_in" | "pan_across" | "scroll_down" | "pull_out", duration: number, fps: number, at?: number, existing?: MoveKeyframe[]): MoveKeyframe[]`. Values, with `d = duration - 1`:
  - `punch_in`: adds `{frame: max(0, at-1), scale 1, ease ease_out}` and `{frame: at + round(0.27*fps), scale 1.35, ease hold}` to `existing`, sorted, replacing any keyframe on the same frame, and clamped inside the clip;
  - `push_in`: `[{0, 1.0, linear}, {d, 1.12}]`;
  - `pan_across`: `[{0, scale 1.15, x 0.06, linear}, {d, scale 1.15, x -0.06}]`;
  - `scroll_down`: `[{0, scale 1.6, y 0.3, ease_in_out}, {d, scale 1.6, y -0.3}]`;
  - `pull_out`: `[{0, 1.2, ease_out}, {d, 1.0}]`.
- The Inspector's new section, `studio.timeline.section.effects`, for a video clip holds:
  - Background (None, Blur-fill);
  - Dim (0-80%, step 5, saved when released);
  - Moves: the five presets, where Punch in uses the playhead; a keyframe list showing time, scale % and a remove button; Clear;
  - Marks: Add box and Add arrow, which start at the middle of the picture (box x 0.35, y 0.35, w 0.3, h 0.3; arrow at 0.5, 0.5), over the clip's whole source window. Each row has percent fields, from and to times in clip time (converted to source frames), a colour, and a remove button.
- `TimelineClip` shows an icon with the accessible name "Has effects" when a clip has moves or marks.
- The caption style picker lists `boxed` and `kinetic`, and the text place picker lists `card`.

- [ ] **Step 1: Write the failing tests**

- `move_presets.test.ts`: every preset's exact keyframes at 30 fps for a 90-frame clip; punch-in merges with existing keyframes; punch-in clamps at the clip's end.
- Inspector tests:
  - `choosing Blur-fill sends set_clip_background`;
  - `releasing Dim at 40% sends set_clip_dim 0.4`;
  - `Push in sends set_clip_moves with the preset`;
  - `Punch in uses the playhead`;
  - `removing a keyframe sends the rest`;
  - `Add box sends a centred box over the clip's source window`;
  - `a mark's to time before its from time says why and sends nothing`.
- Timeline test: `a clip with moves shows Has effects`.

- [ ] **Step 2: Run them to verify they fail**

Run: `bash D:/thoth-tmp/fixes/fw_check.sh src/features/studio/move_presets.test.ts src/features/studio/TimelineInspector.test.tsx src/features/studio/Timeline.test.tsx`. Expected: FAIL.

- [ ] **Step 3: Implement**

Follow the Inspector's existing `Section` and field patterns, and the `outOfRange` messages for refused values.

- [ ] **Step 4: Run them to verify they pass**

Same command, then `dash_full.sh full`. Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "Add the Effects section to the Timeline Inspector"`

---

### Task 6: Story controls

**Files:**
- Modify: `dashboard/src/features/studio/story/BeatInspector.tsx`, `dashboard/src/lib/i18n.ts`
- Test: `dashboard/src/features/studio/story/BeatInspector.test.tsx`

**Interfaces:**
- Consumes `movePreset` (Task 5).
- For the clips the beat's motion controls act on today (its cards, or the Footage beat's photos), add:
  - Background;
  - Dim;
  - the presets `push_in`, `pan_across`, `scroll_down` and `pull_out`.

  Each sends one `commit_operations` batch, with one operation per clip.
- A line `studio.story.timelineMarks` names the beat's clips that have marks, for example "Marks set in Timeline: Post card".

- [ ] **Step 1: Write the failing tests**

- `Blur-fill applies to every card of the beat as one batch`;
- `Push in writes each card's own keyframes`, since each clip has its own length;
- `Dim applies to the Footage beat's photos`;
- `the beat names the cards with marks`.

- [ ] **Step 2: Run them to verify they fail**

Run: `bash D:/thoth-tmp/fixes/fw_check.sh src/features/studio/story/BeatInspector.test.tsx`. Expected: FAIL.

- [ ] **Step 3: Implement**

Use the existing beat-level menus in `BeatInspector`.

- [ ] **Step 4: Run them to verify they pass**

Same command. Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "Add Background, Dim and moves to Story's beat settings"`

---

### Task 7: Blur-fill in new auto-drafts

**Files:**
- Modify: `python/src/thoth_control_plane/domain/studio_layout.py`, `python/src/thoth_control_plane/infrastructure/studio_import_repository.py` (both `AddClipFromAsset` sites, lines 344 and 472)
- Test: `python/tests/application/test_workflow_studio_imports.py`

**Interfaces:**
- Produces `full_frame_fill(asset: AssetRef) -> tuple[FitMode, Background] | None` in `studio_layout.py`. It returns `("contain", "blur_fill")` when the asset has a width and height and `abs(width / height - 9 / 16) > 0.02`; otherwise it returns `None`, meaning keep what the import sets today.
- A clip added with `position is None` (full frame) uses it. Cards added with a position do not.

- [ ] **Step 1: Write the failing tests**

- `test_a_landscape_main_video_gets_blur_fill`;
- `test_a_vertical_main_video_stays_as_before`: no `background` key in the dump;
- `test_a_post_card_keeps_contain_without_background`;
- `test_a_landscape_slide_gets_blur_fill`.

- [ ] **Step 2: Run them to verify they fail**

Run: `make test T=tests/application/test_workflow_studio_imports.py`. Expected: FAIL.

- [ ] **Step 3: Implement**

Pass `fit` and `background` into `AddClipFromAsset`. The operation applies `background` to the new clip.

- [ ] **Step 4: Run them to verify they pass**

Same command, then `make test` (full) and `make lint`. Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "Put full-frame media of another shape on blur-fill"`

---

### Task 8: Release capsule and render time

**Files:**
- Create: `packages/remotion-composition/releases/effects-v1/` (`release.json`, `document.json`, `assets/` copied from `story_mode-v1`)
- Modify: `renderer/src/release-capsule.ts` (`RELEASE_IDENTITIES` and its template map gain `"effects-v1"`)
- Test: `renderer/src/release-capsule.test.ts`

**Interfaces:**
- `effects-v1/document.json` is a 120-frame v2 document using every effect:
  - a video clip with a punch-in and blur-fill;
  - an image clip with pan, dim 0.5, a box and an arrow;
  - a `kinetic` caption clip with word timings;
  - a `boxed` caption clip;
  - a `card` text clip.
- `release.json` frames: `[0, 20, 40, 60, 80, 119]`.

- [ ] **Step 1: Write the failing test**

`test("effects-v1 loads and validates its assets")`, in the style of the `story_mode-v1` case at line 589.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd renderer && bun test`. Expected: FAIL (unknown identity).

- [ ] **Step 3: Implement the capsule, then measure render time**

Render a 60 s draft twice locally with fixture media: once with blur-fill on every clip, once without. Record both times. If blur-fill costs more than 25%, change Task 4's video blur-fill to the cheaper way and measure again.

- [ ] **Step 4: Produce the candidate golden set, then stop**

Run `bun run scripts/verify-template-release.ts effects-v1` in the F1 image, the same way as the CI step in `.github/workflows/container-image.yml` (around line 527), with an artifact root outside the checkout. Do not promote the golden set, and do not add `effects-v1` to the CI loop. Approval is the operator's gate.

- [ ] **Step 5: Commit**

`git commit -m "Add the effects-v1 release capsule"`

---

### Task 9: Browser checks and records

**Files:**
- Modify: `e2e/tests/studio-shell-v2.e2e.ts`
- Create: `e2e/tests-write/effects.e2e.ts`
- Modify: `CHANGELOG.md`, `docs/ROADMAP.md` (a status line, added only), the SDD checkpoint

- [ ] **Step 1: Add the read-only check**

`1440 Timeline: a video clip shows the Effects section`: select the main video clip, and expect the Background, Dim, Moves and Marks controls.

- [ ] **Step 2: Add the write checks; do not run them**

Write these, but do not run them. They need the operator's word and a one-day write token:
- `effects: blur-fill and dim are saved`;
- `effects: Push in is saved as two keyframes`;
- `effects: Add box is saved and shows on the preview`.

- [ ] **Step 3: Run the whole verification**

Run `make test`, `make lint`, `dash_full.sh full` and `cd renderer && bun test`, then the read-only e2e against a local dev server of this branch (`vite_main.sh`, target `dev1440`). Take screenshots of a clip with each effect at 1440x900 and judge them.

- [ ] **Step 4: Record and commit**

Write a CHANGELOG entry with the measured render times and a **Next steps** section, and update the checkpoint. Then:

```bash
git add -f docs/superpowers/plans/2026-11-09-studio-effects-layer.md
git commit -m "Add browser checks and records for the effects layer"
```

**Next steps to report (each its own gate):** golden approval for `effects-v1`, push and PR, deploy, the write e2e, the operator's try, merge. After that comes the planner slice.

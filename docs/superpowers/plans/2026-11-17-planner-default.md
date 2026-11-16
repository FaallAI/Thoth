# Planner Default and Stacked Layers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every style places b-roll with the planner at its own rhythm. A planned beat owns its b-roll. Overlapping clips stack as computed layers, in Studio and in the render, with no overlap warning.

**Architecture:**
- **Python, style and planner:**
  - `CutRules.planned` defaults to on;
  - the phrase split reads the style's shot band;
  - `style_operations` drops a planned beat's import b-roll material.
- **Shared composition package:** layers are computed in `visibleLanes`, which both the Remotion composition and Studio use.
- **Studio and server review:** Studio draws one sub-row per layer, and both Studio and the server review drop `clip_overlap`.

**Tech Stack:** Python 3.12 and pytest (`make test`), React 19 + TypeScript (bun test, `tsc -b`), Remotion composition package.

**Spec:** `docs/superpowers/specs/2026-11-17-planner-default-design.md`.

## Global Constraints

- Repository text is in English. Commits follow the usual rules: one `-m`, a Conventional prefix, at most 72 characters, no attribution.
- **Shot bands:** Style B keeps 0.9-2.4 s. Style A is 1.5-4.0 s, with `planned` on, as revision 2.
- **Layers are computed, never stored.** A clip goes on the lowest layer whose last clip has ended by its start. Clips are taken by start frame, then document order.
- **Render order within a lane:** by layer, then start frame. A higher layer is drawn later, so it sits on top.
- `main_track_gap` and `clip_exceeds_canvas` stay. `clip_overlap` goes, in Studio and in the server review.
- A draft without the planner still falls back to phrase cuts, as before.

## Review Focus

1. **A lane with no overlaps** must render and draw exactly as today. Covered by: layer 0 everywhere, one sub-row, and unchanged order.
2. **Three clips where the third fits under the first.** Expected: it takes layer 0, not layer 2. Covered by a `clipLayers` test.
3. **A planned beat whose planner placed nothing.** Expected: the import material is kept, so the beat never goes blank. Covered in Task 2.
4. **A stored custom template without a `planned` field.** Expected: it is now planned. Covered in Task 1.
5. **A hidden clip** takes no layer and no row. Covered in Task 3.

---

### Task 1: Planner on by default; a rhythm per style

**Files:**
- `python/src/thoth_control_plane/domain/style_templates.py`: `CutRules.planned` defaults to `True`; Style A gets `CutRules(max_shot_seconds=4.0, min_shot_seconds=1.5, planned=True)` at revision 2.
- `python/src/thoth_control_plane/domain/planner.py`: `split_phrases(words, min_seconds=MIN_PHRASE_SECONDS, max_seconds=MAX_PHRASE_SECONDS)`.
- **Callers that pass the style's band:**
  - `assembly/narration_timeline.py` at lines 451 and 496;
  - `assembly/planner_service.py` at lines 106 and 135.
- **Tests:**
  - `python/tests/domain/test_style_templates.py` (or the existing style template test);
  - `python/tests/domain/test_planner.py`.

**Steps:**
1. Write the failing tests:
   - `test_every_built_in_style_is_planned`;
   - `test_a_stored_template_without_planned_is_planned`;
   - `test_style_a_rhythm_is_one_and_a_half_to_four_seconds`;
   - `test_phrases_follow_the_given_band`: at 1.5/4.0, a 3.5 s run of words with no punctuation is one phrase.
2. Watch them fail.
3. Implement.
4. Run `make test T='tests/domain tests/assembly'`.
5. Commit `feat(style): place every style's b-roll with the planner`.

### Task 2: A planned beat owns its b-roll

**File:** `python/src/thoth_control_plane/domain/style_apply.py`. When `assignments` holds a beat, its import material clips on the `b_roll` track are removed with `RemoveClip`: the clips of `clip_beats` for that beat, not the planner's own `PLANNER_CLIP` clips. A beat whose assignment placed no b-roll shot keeps them (Review Focus 3).

**Tests:**
- `test_a_planned_beat_leaves_no_import_material_under_its_shots`: the edoc_3ee4719b shape, a profile card spanning the evidence beat;
- `test_a_planned_beat_without_shots_keeps_its_material`.

**Steps:** write the failing tests, implement, run `make test T='tests/domain tests/assembly'`, then commit `fix(style): let a planned beat own its b-roll`.

### Task 3: Computed layers in the shared lanes, and the render follows them

**File:** `packages/remotion-composition/src/timeline.ts`.
- `clipLayers(clips: TimelineClip[]): Map<string, number>` puts each visible clip on the lowest free layer.
- `visibleLanes` lanes gain `layers: number` (at least 1) and `layerOf: Map<string, number>`.
- Their `clips` are ordered by layer, then `from_frame`.

**Tests** (in the package's test file for `timeline.ts`):
- `clipLayers stacks overlaps and reuses a freed layer`;
- `a lane without overlaps keeps one layer and its order`;
- `a hidden clip takes no layer`.

**Composition:** `AdvancedTimelineComposition` already maps `lane.clips` in order, so the new order is the draw order. Add a test that a higher-layer clip renders after the lower one.

**Steps:** write the failing tests, implement, run the package tests and `tsc`, then commit `feat(composition): stack overlapping clips as layers`.

### Task 4: Studio draws layers; the overlap warning goes

**Files:**
- `dashboard/src/features/studio/TimelineTrack.tsx`: the lane is `layers × 44` px tall.
- `dashboard/src/features/studio/TimelineClip.tsx`: a clip's `top` is `4 + (layers - 1 - layer) × 44` px, so the top layer is the highest row. It takes a new `layer` and `layers` prop.
- `dashboard/src/features/studio/timeline_domain.ts`: `timelineIssues` no longer adds `clip_overlap`.
- `python/src/thoth_control_plane/domain/studio_review.py`: no longer adds `clip_overlap`. The issue code stays in the enum so stored reviews decode.
- **Tests:**
  - `TimelineTrack.test.tsx` or `Timeline.test.tsx`: two overlapping clips sit on two rows and both can be selected;
  - `timeline_domain.test.ts`: an overlap is no issue;
  - `python/tests/domain/test_studio_review.py`: an overlap is no issue.

**Steps:**
1. Write the failing tests.
2. Implement.
3. Run `bun test`, `tsc -b`, the build, and `make test T=tests/domain`.
4. Commit `feat(studio): show stacked clips as layers without a warning`.

### After the tasks

- Run the full `make test`, `make lint` and the dashboard checks, then one fresh final review.
- Records: a CHANGELOG entry with Next steps, the checkpoint, and the brainstorm notes.
- **Gates, each needing its own authorization:**
  1. push and CI;
  2. deploy;
  3. one paid Style A narration on the Mutant draft;
  4. merge PR #133.

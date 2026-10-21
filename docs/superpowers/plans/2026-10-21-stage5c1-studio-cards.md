# Stage 5c-1: Cards, Slides and Subtitle Blur in Studio — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A draft opened from a workflow holds the profile card, up to three comment cards and every
carousel slide, laid out per the spec. Detected subtitle regions are stored on the clip, switched
off, behind one inspector action. Before any of that, the template release parity check stops
failing at random, so that it can serve as proof that blur renders.

**Architecture:**

- Pure layout lives in one Python constants module (`domain/studio_layout.py`). The projection
  emits new gate roles. `_attached` in the import repository places each role from the stored
  inventory, so a workflow import and a manual gate attach land identically.
- Blur is two additive fields on `TimelineVideoClip` plus one operation, drawn by the shared
  Remotion composition with `backdrop-filter`.
- The flaky parity frame comes from rendering video with Remotion's HTML5 `<Video>`, which is not
  frame-accurate. Task 1 proves this and switches rendering to `<OffthreadVideo>`.

**Tech Stack:** Python 3.12, FastAPI, pydantic, psycopg, Alembic (editor DB); TypeScript, React,
Remotion 4.0.523, bun; Docker smoke in WSL.

**Spec:** `docs/superpowers/specs/2026-10-21-stage5c1-studio-cards-design.md`

## Global Constraints

- **Language:** repository artifacts are in English; chat with the operator is in Indonesian.
- **Commits:** one `git commit -m "<subject>"` each, with no body, no trailer and no AI
  attribution.
- **Staging:** never stage `.superpowers/`, `graphify-out/`, `.serena/` or `design/`. Plans and
  specs go in with `git add -f docs/superpowers/...`.
- **Offline only:** no live provider request (ADR 0001). The conftest guard blocks non-loopback
  traffic.
- **Tools fail loud:** a missing tool (ffmpeg, ffprobe, rapidocr) is an explicit error, never a
  skip.
- **Cards:** only real crops, never a synthetic card.
- **Layout values, verbatim from spec section 3:**
  - reading time = `characters / 15 + 1.0` s, clamped to [2.5, 7.0];
  - the beat runs from 40 % of the main scene to its end minus 0.3 s, with 0.5 s gaps and at most
    3 cards; leftover time is spread evenly;
  - the profile card shows from 3.0 s to 6.0 s, clamped so it starts at most at the length minus
    0.5 s and lasts at least 0.5 s;
  - cards are 76 % of the canvas width, centred, with their centre at y = 0.26 × canvas height;
  - slides are 3.0 s each;
  - blur σ = max(24, 0.2 × the region's canvas height in px), and each region is widened by σ on
    every side.
- **Section 6:** imported blur is `blur_enabled = false`, and imported mute leaves the track
  unmuted.
- **One home per language:** all layout numbers live in `python/src/thoth_control_plane/domain/studio_layout.py`.
  The blur factor and floor live in `packages/remotion-composition/src/blur.ts`, because σ is
  computed where the canvas size is known. That is the single ruling against spec 3.5's "one
  module": it is one module per language.
- **Commands:**
  - Python: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-5c1 && make test T=<path relative to python/>'`
  - PostgreSQL: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-5c1 && bash scripts/dev/pytest-postgres.sh <path>'`
  - lint: `make lint`
  - dashboard and composition: `cd D:/thoth-tmp/wt-5c1/dashboard && bun test <path>`
  - renderer: `cd D:/thoth-tmp/wt-5c1/renderer && bun test <path>`
  - types: `bunx tsc --noEmit -p tsconfig.app.json`
- **Contract regeneration:** run `python/scripts/export_openapi.py` from WSL (`uv run`), then
  `bun run generate:control-plane-types` in `dashboard/`. Write `openapi.json` with LF endings.

## Review Focus

1. **A main shorter than the profile window** (the smoke's old 3 s clip, an 11 s main): the
   profile card clamps inside the scene and is never dropped, and the beat places zero cards
   rather than a card shorter than its reading time. Pinned in Task 2.
2. **The main attached by a person after the workflow import left it unresolved:** a later replay
   or manual attach of overlay items uses the current main scene length, not a stale one. Pinned
   in Task 6.
3. **A clip scaled, cropped or split in the editor after import:** the blur follows the media,
   and both halves of a split keep their regions. Pinned in Tasks 3 and 8.
4. **An asset without a width or height:** blur falls back to the clip frame instead of
   vanishing or throwing. Pinned in Task 8.
5. **Comment text with emoji or other astral characters:** characters are counted as code points,
   the same in Python as anywhere else, and the reading time stays within its clamp. Pinned in
   Task 2.

---

### Task 1: Make the template release parity deterministic

The failure (PR #37, run 39527572350): frame 90, which lies inside the `asset_video` clip (frames
60–120), differed in 33 % of its pixels from its golden on render only; the preview passed. A
re-run passed. The composition renders video through `remotion`'s `<Video>`, which is
`<Html5Video>`. Remotion's own docs say it is not frame-perfect and point to `<OffthreadVideo>`.

**Files:**
- Modify: `packages/remotion-composition/src/AdvancedTimelineComposition.tsx` (video case, around line 261)
- Test: `dashboard/src/features/studio/AdvancedTimelineComposition.test.tsx`

**Interfaces:**
- Produces: the video case renders `<OffthreadVideo>` when `useRemotionEnvironment().isRendering`
  is true, and `<Video>` (HTML5) otherwise. The props are otherwise identical: `src`, `startFrom`,
  `muted`, `style`.

- [ ] **Step 1: Reproduce.** Build the F1 image as CI does (`Dockerfile.renderer-f1`) in WSL, then
  run `bun run scripts/verify-template-release.ts vertical_text_story-v1` 10 times in it with
  `--network none` and a fresh artifact root each time, exactly as the CI step does. Record each
  run's verdict and the frames that fail into the checkpoint.
  Expected: at least one `visual_mismatch` on a frame inside 60–120. If there is none in 10 runs,
  run 20 more and record the rate. Use superpowers:diagnosing-bugs if the failures fall outside
  the video clip; the fix below then does not apply.
- [ ] **Step 2: Write the failing test** `"a render draws video with the frame-accurate tag"`.
  Mock `useRemotionEnvironment` to return `{ isRendering: true }`, render a document with one
  video clip, and assert that the rendered element is the `OffthreadVideo` stand-in. With
  `isRendering: false`, it is the HTML5 `Video`.
- [ ] **Step 3:** Run `bun test src/features/studio/AdvancedTimelineComposition.test.tsx`.
  Expected: FAIL, because `<Video>` is rendered in both cases.
- [ ] **Step 4: Implement** the switch in the video case. Import `OffthreadVideo` and
  `useRemotionEnvironment` from `remotion`.
- [ ] **Step 5:** Run the test. Expected: PASS. Run `renderer` `bun test` in full. Expected: all
  pass.
- [ ] **Step 6: Verify the fix.** Rebuild the F1 image and repeat Step 1's loop the same number of
  times.
  - Expected: every run passes.
  - If the pair or golden now fails on every run, because OffthreadVideo's decoded colours differ
    from the approved golden, stop. The goldens need re-approval, which is an operator gate.
    Record the contact sheet's path in the checkpoint and report it.
- [ ] **Step 7: Commit**

```bash
git add packages/remotion-composition/src/AdvancedTimelineComposition.tsx dashboard/src/features/studio/AdvancedTimelineComposition.test.tsx
git commit -m "fix(renderer): render video frames with OffthreadVideo"
```

---

### Task 2: Layout constants and pure placement

**Files:**
- Create: `python/src/thoth_control_plane/domain/studio_layout.py`
- Test: `python/tests/domain/test_studio_layout.py`

**Interfaces:**
- Produces:
  - constants: `READING_CPS = 15.0`, `ORIENTATION_SECONDS = 1.0`, `READING_MIN = 2.5`,
    `READING_MAX = 7.0`, `BEAT_START = 0.40`, `BEAT_TAIL = 0.3`, `CARD_GAP = 0.5`,
    `MAX_COMMENT_CARDS = 3`, `PROFILE_AT = 3.0`, `PROFILE_SECONDS = 3.0`, `CARD_WIDTH = 0.76`,
    `CARD_CENTER_Y = 0.26`, `SLIDE_SECONDS = 3.0`;
  - `reading_seconds(text: str) -> float`;
  - `profile_slot(scene_seconds: float) -> tuple[float, float]`, returning `(start, duration)`;
  - `reaction_beat(scene_seconds: float, reading: Sequence[float]) -> list[tuple[float, float] | None]`,
    one entry per card in rank order;
  - `card_position(image_width: int | None, image_height: int | None, canvas: tuple[int, int]) -> Position`,
    returning the editor's `Position` (`x`, `y`, `scale`) for a `fit = "contain"` clip whose
    image ends up `CARD_WIDTH` of the canvas wide, centred at `CARD_CENTER_Y`.

`reaction_beat` packs first, then spreads:

```python
start, end = BEAT_START * scene_seconds, scene_seconds - BEAT_TAIL
placed, cursor = [], start
for seconds in reading[:MAX_COMMENT_CARDS]:
    if cursor + seconds > end:
        break                      # never shorten, never try a later card
    placed.append(seconds)
    cursor += seconds + CARD_GAP
spare = end - start - sum(placed) - CARD_GAP * max(0, len(placed) - 1)
extra = spare / (len(placed) + 1) if placed else 0.0   # even gaps before, between, after
# slot k starts at start + extra * (k + 1) + sum(placed[:k]) + CARD_GAP * k
```

Return `None` for every card that was not placed.

- [ ] **Step 1: Write the failing tests**
  - `test_reading_time_follows_fifteen_characters_a_second`:
    - `reading_seconds("a" * 39) == pytest.approx(3.6)`;
    - 84 characters give `6.6`;
    - 155 characters give `7.0`;
    - an empty string gives `2.5`.
  - `test_reading_time_counts_code_points`: `reading_seconds("🔥" * 30) == pytest.approx(3.0)`.
  - `test_a_short_main_places_few_cards_and_never_shortens_one`:
    - `reaction_beat(11.2, [3.6, 3.6, 3.6])` has at most 2 non-`None` slots;
    - every placed duration equals its reading time;
    - every placed slot ends at or before `11.2 - 0.3`.
  - `test_a_typical_main_places_three_spread_cards`:
    - `reaction_beat(46.5, [3.6, 4.0, 6.6, 3.0])` places exactly the first three;
    - the 4th is `None`;
    - the first starts after `0.4 * 46.5`;
    - the gaps between slots are equal and at least `0.5`.
  - `test_a_card_that_does_not_fit_stops_the_beat`: in `reaction_beat(12.0, [7.0, 2.5])`, if the
    first does not fit then both are `None`.
  - `test_a_three_second_main_places_no_card`: `reaction_beat(3.0, [2.5]) == [None]`.
  - `test_profile_slot_clamps_inside_a_short_scene`:
    - `profile_slot(46.5) == (3.0, 3.0)`;
    - `profile_slot(3.0) == (2.5, 0.5)`;
    - `profile_slot(1.0) == (0.5, 0.5)`.
  - `test_card_position_is_centred_at_the_card_line`:
    - for a 768 × 198 image on (1080, 1920), the drawn width is `0.76 * 1080` within 1 px;
    - the drawn centre y is `0.26 * 1920` within 1 px;
    - with unknown size, the scale is `0.76`.
- [ ] **Step 2:** Run `make test T=tests/domain/test_studio_layout.py`. Expected: FAIL (module
  missing).
- [ ] **Step 3: Implement** the module. Remember that `position.y` is a canvas fraction
  translated before scaling, and that a `contain` image fills the canvas width when its aspect
  is wider than the canvas.
- [ ] **Step 4:** Run the test. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(studio): layout rules for cards, slides and the reaction beat"`

---

### Task 3: Blur on the editor document

**Files:**
- Modify: `python/src/thoth_control_plane/domain/edit_document_v2.py` (`TimelineVideoClip`, around line 146)
- Modify: `python/src/thoth_control_plane/domain/timeline_operations.py`: new `SetClipBlur`, added
  to the operation union and the apply dispatch
- Modify: `dashboard/src/features/studio/timeline_domain.ts` (`case "set_clip_blur"`)
- Regenerate: `python/openapi.json`, `dashboard/src/api/generated/control-plane.ts`
- Test: `python/tests/domain/test_timeline_operations.py`, `dashboard/src/features/studio/timeline_domain.test.ts`

**Interfaces:**
- Produces:
  - `ClipBlurRegion(x: Fraction, y: Fraction, w: Fraction, h: Fraction, from_frame: FrameStart | None = None, to_frame: Frame | None = None)`,
    validated so that the region stays inside [0, 1], `from_frame` and `to_frame` are both set or
    both unset, and `to_frame > from_frame`;
  - on `TimelineVideoClip`: `blur_regions: list[ClipBlurRegion]` (max 200, default `[]`) and
    `blur_enabled: bool = False`;
  - `SetClipBlur(kind="set_clip_blur", operation_id, clip_id, blur_enabled: bool)`, which only
    applies to an unlocked video clip.

- [ ] **Step 1: Write the failing tests** (Python)
  - `test_a_stored_video_clip_without_blur_still_validates`: a pre-5c-1 clip dict parses, with
    `blur_regions == []` and `blur_enabled is False`.
  - `test_set_clip_blur_switches_blur`: apply `set_clip_blur` with `True`, then `False`, and read
    the field back.
  - `test_set_clip_blur_refuses_a_text_clip`: raises `ValueError`.
  - `test_a_split_keeps_blur_regions_on_both_halves`: split a clip with one region; both halves
    keep the region unchanged, in source frames.
  - `test_a_blur_region_outside_the_frame_is_refused`: `x=0.9, w=0.2` raises.
- [ ] **Step 2: Write the failing TS tests** in `timeline_domain.test.ts`: `"set_clip_blur
  toggles blur_enabled"` and `"split keeps blur regions"`.
- [ ] **Step 3:** Run both suites. Expected: FAIL.
- [ ] **Step 4: Implement** the models and the operation, then regenerate the contract and the
  types.
- [ ] **Step 5:** Run both suites, `bunx tsc --noEmit -p tsconfig.app.json` and `make lint`.
  Expected: PASS and clean.
- [ ] **Step 6: Commit** `git commit -m "feat(editor): subtitle blur regions on video clips"`

---

### Task 4: Gate roles, item fields and the "not placed" reason

**Files:**
- Modify: `python/src/thoth_control_plane/domain/studio_imports.py`
- Create: `python/migrations/editor/0017_studio_import_decision_reason.sql` and
  `python/migrations/editor/alembic/versions/0017_studio_import_decision_reason.py`
- Modify: `python/tests/operations/test_editor_migrations.py` (the file list, around line 49)
- Modify: `python/src/thoth_control_plane/infrastructure/studio_import_repository.py`, which
  writes and reads `reason`
- Test: `python/tests/domain/test_studio_imports.py`, `python/tests/infrastructure/test_studio_import_repository.py`

**Interfaces:**
- Produces:
  - `SourceRole` gains `slide`, `profile_card` and `comment_card`;
  - `ROLE_ORDER = ("main", "main_footage", "slide", "footage", "profile_card", "comment_card", "comment")`;
  - `OVERLAY_ROLES = frozenset({"slide", "profile_card", "comment_card"})`;
  - `SourceBlurRegion(x, y, w, h: float, start: float | None, end: float | None)`, in source
    seconds;
  - `StudioSourceItem` gains `mute_audio: bool = False`,
    `blur_regions: list[SourceBlurRegion] = []` (video items only) and
    `reading_seconds: float | None = None` (`comment_card` items only);
  - `StudioImportItem` gains `mute_audio`, `blur_regions` and `reading_seconds`, all copied from
    the source item;
  - `scene_items` skips `OVERLAY_ROLES`, and `inventory` gives overlay items `scene_id = "scene_001"`;
  - `ExcludeImportItem.reason: Literal["not_placed"] | None = None`;
  - the inventory shows a stored `not_placed` decision as
    `reason = "Not placed: no room in the reaction beat"`;
  - `ImportOutcome` adds `"not_placed"`.
- Migration 0017: `ALTER TABLE studio_import_decisions ADD COLUMN reason TEXT CHECK (reason IS NULL OR reason = 'not_placed');`

- [ ] **Step 1: Write the failing tests**
  - `test_overlay_roles_take_no_scene_and_point_at_the_main_scene`: a projection with main, one
    slide, a profile card and one comment card. `scene_items` returns only main, and every
    overlay inventory item has `scene_id == "scene_001"`.
  - `test_role_order_includes_the_overlay_roles`: footage before `profile_card` is accepted, and
    `comment_card` before `footage` is refused.
  - `test_trim_and_blur_need_a_video_item`: `blur_regions` on an image item raises.
  - `test_migrations` list test: add `"0017_studio_import_decision_reason.sql"`.
  - Repository: `test_a_not_placed_exclusion_reads_back_with_its_reason` (fake cursor, matching
    the file's style). The insert passes `"not_placed"`, and the read maps it to the reason text.
- [ ] **Step 2:** Run `make test T=tests/domain/test_studio_imports.py` and the migration and
  repository tests. Expected: FAIL.
- [ ] **Step 3: Implement** the domain changes, the migration pair (copy the 0016 Alembic file's
  shape) and the repository read/write of `reason`.
- [ ] **Step 4:** Run the tests, then `bash scripts/dev/pytest-postgres.sh tests/operations/test_editor_migrations_postgres.py`.
  Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(studio): overlay roles and the not-placed decision"`

---

### Task 5: Project cards, slides, mute and blur

**Files:**
- Modify: `python/src/thoth_control_plane/assembly/studio.py`
- Test: `python/tests/assembly/test_studio_projection.py`

**Interfaces:**
- Consumes: Task 2 `reading_seconds`; Task 4 roles and fields.
- Produces:
  - `project_content_set` emits `slide` items for `main.images[1:]`;
  - one `profile_card` item titled `@<owner_handle>`;
  - `comment_card` items for comments with a card, ordered by likes descending with ties in
    Content Set order, each with its comment as `text` and `reading_seconds`;
  - `comment` text items only for comments without a card;
  - `mute_audio` and `blur_regions` on the main and footage items from their OCR;
  - `WorkflowProjection.media` keyed `slide_000`, `profile_card_000`, `comment_card_000` and so
    on.
- The constants `CARDS`, `SLIDES`, `MUTE` and `BLUR`, and their `report` calls, are deleted.
  `FIGURES` stays.

- [ ] **Step 1: Write the failing tests**
  - `test_comment_cards_follow_likes_and_carry_reading_time`: likes [5, 50, 50] give
    `comment_card` orders whose authors run 2nd, 3rd, then 1st, each with
    `reading_seconds == reading_seconds(text)`.
  - `test_a_comment_without_a_card_stays_a_text_scene`.
  - `test_profile_card_and_slides_are_projected`: an `images` main with 3 images gives 2 slide
    items and media keys `slide_000`/`slide_001`.
  - `test_subtitle_main_carries_mute_and_blur`: main OCR `subtitle` with 2 regions gives
    `mute_audio is True`, 2 `blur_regions` in seconds, and nothing in `unsupported` except
    figures.
  - Update the existing tests that asserted the 5c "unsupported" reasons.
- [ ] **Step 2:** Run `make test T=tests/assembly/test_studio_projection.py`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run it. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(studio): project cards, slides and subtitle regions"`

---

### Task 6: Place each role on attach

**Files:**
- Modify: `python/src/thoth_control_plane/infrastructure/studio_import_repository.py` (`_attached`, around line 256)
- Test: `python/tests/infrastructure/test_workflow_studio_postgres.py` and the repository unit
  test file

**Interfaces:**
- Consumes: Task 2's functions, Task 3's `ClipBlurRegion`, Task 4's item fields.
- Produces, in `_attached` by `entry.role`:
  - **`main`:** as before. For an image main, the scene is set to `SLIDE_SECONDS × (1 + slide count in the inventory)`
    via `SetSceneDuration`. A video main gets `blur_regions` converted from `entry.blur_regions`
    and `blur_enabled = False`.
  - **`footage`:** as before, plus the converted regions.
  - **`slide`:** on `track_main_video` at scene start + `(order + 1) × SLIDE_SECONDS`, for
    `SLIDE_SECONDS` frames, `fit = "contain"`.
  - **`profile_card`:** on `track_b_roll` at `profile_slot(scene seconds)`, with
    `card_position(...)` and `fit = "contain"`.
  - **`comment_card`:** run `reaction_beat(scene seconds, [reading of every comment_card entry by order])`.
    The slot is taken at `entry.order`. `None` raises
    `StudioImportDecisionRejected("no_room_in_reaction_beat")`.
  - **Any overlay role** while the inventory's `main_000` is not `attached` raises
    `StudioImportDecisionRejected("main_not_attached")`.
  - The scene length is read from the latest document at attach time, never from the inventory.
- The region conversion is a function `clip_regions(regions: list[SourceBlurRegion], fps: float, trim_frames: int) -> list[ClipBlurRegion]`
  in `studio_layout.py`:
  - seconds × fps, rounded;
  - a window ending at or before the trim is dropped;
  - a start before the trim is clamped to the trim;
  - a region without a window is kept as it is.

- [ ] **Step 1: Write the failing tests**
  - Unit, in `test_studio_layout.py`: `test_clip_regions_drop_and_clamp_at_the_trim`. At 30 fps
    with a trim of 60 frames, a window 1.0–1.5 s is dropped, 1.5–3.0 s becomes 60–90, and a
    region without a window passes through.
  - PostgreSQL, in `test_workflow_studio_postgres.py`:
    `test_cards_and_blur_land_where_the_layout_says`. Seed a Content Set with a 20 s main, a
    profile card, 4 comment cards with short text and a `subtitle` OCR main. Then assert:
    - the profile clip is on `track_b_roll` at frame 90 for 90 frames;
    - 3 comment clips sit at their `reaction_beat` frames;
    - the 4th inventory item is `excluded` with reason "Not placed: no room in the reaction beat";
    - the main clip has regions with `blur_enabled is False`;
    - `track_main_video.muted is False`.
  - PostgreSQL: `test_overlay_items_wait_for_the_main`. Make the main's media fail; the overlay
    items end `unresolved` with `main_not_attached`. Fix the media and replay the same key: all
    are placed against the now-attached main's length.
- [ ] **Step 2:** Run `make test T=tests/domain/test_studio_layout.py` and
  `bash scripts/dev/pytest-postgres.sh tests/infrastructure/test_workflow_studio_postgres.py`.
  Expected: FAIL.
- [ ] **Step 3: Implement** `clip_regions` and the role branches. Video clips are added through
  the existing `AddClipFromAsset`. Then set `fit`, `position` and the blur fields on the new clip
  in the same `apply_edit_operations` result, before validation.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(studio): place cards, slides and blur on attach"`

---

### Task 7: The workflow importer maps the new refusals

**Files:**
- Modify: `python/src/thoth_control_plane/application/workflow_studio_imports.py` (the attach loop, around line 200)
- Test: `python/tests/application/test_workflow_studio_imports.py`

**Interfaces:**
- Consumes: Task 4 `ExcludeImportItem(reason="not_placed")` and outcome `not_placed`.
- Produces:
  - a `no_room_in_reaction_beat` refusal resolves the item with
    `ExcludeImportItem(kind="exclude", reason="not_placed")` and reports outcome `not_placed`;
    the copied asset stays registered;
  - `main_not_attached` is reported `unresolved` with that reason.

- [ ] **Step 1: Write the failing tests** with the existing fakes:
  - `test_a_card_with_no_room_is_excluded_as_not_placed`: `AttachingImports` refuses with
    `no_room_in_reaction_beat`. The outcome is `not_placed`, the asset is in `MemoryAssets`, and
    the recorded decision is an exclude carrying `reason="not_placed"`.
  - `test_overlay_items_stay_unresolved_until_the_main_attaches`.
- [ ] **Step 2:** Run `make test T=tests/application/test_workflow_studio_imports.py`.
  Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run it, then the full `make test`. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(studio): exclude unplaced comment cards with a reason"`

---

### Task 8: Draw blur in the composition

**Files:**
- Create: `packages/remotion-composition/src/blur.ts`
- Modify: `packages/remotion-composition/src/AdvancedTimelineComposition.tsx` (video case)
- Test: `dashboard/src/features/studio/AdvancedTimelineComposition.test.tsx`

**Interfaces:**
- Produces:
  - `BLUR_FACTOR = 0.2` and `BLUR_FLOOR = 24`;
  - `blurBoxes(clip, asset: { width?: number | null; height?: number | null } | undefined, canvas: { width: number; height: number }): Array<{ left: number; top: number; width: number; height: number; sigma: number; from: number | null; to: number | null }>`.
    Boxes are in the clip frame's local px. `sigma` is local px:
    `max(BLUR_FLOOR / scale, BLUR_FACTOR * regionLocalHeight)`, so that on the canvas σ =
    max(24, 0.2 × the region's canvas height). Each box is widened by `sigma` on every side.
    `from` and `to` are clip-relative frames, i.e. source frame − `source_from_frame`.
  - The composition draws, inside the clip frame and only when `clip.blur_enabled` is true and
    the asset kind is `video`, one `<div data-testid="blur-region">` per box with
    `backdropFilter: blur(${sigma}px)`, wrapped in a `<Sequence>` when it has a window.

- [ ] **Step 1: Write the failing tests**
  - `"blur boxes map source fractions through fit, crop and position"`, as a pure `blurBoxes`
    test:
    - a 720 × 1280 asset, `fit = "cover"`, no crop and the region `{x: 0.1, y: 0.65, w: 0.8, h: 0.0878}`
      give a box at about 108 / 1248 / 864 / 169 px before widening;
    - σ = 34 within 1, then widened by σ.
  - `"a scaled clip keeps the canvas blur strength"`: with `position.scale = 0.5`, the local σ
    doubles relative to that region's local height rule, so the canvas σ stays at least 24.
  - `"blur falls back to the clip frame when the asset size is unknown"`.
  - `"blur off draws nothing"`.
  - `"a windowed region renders inside a Sequence offset by the trim"`.
  - `"an image clip ignores blur"`.
- [ ] **Step 2:** Run `bun test src/features/studio/AdvancedTimelineComposition.test.tsx`.
  Expected: FAIL.
- [ ] **Step 3: Implement** `blur.ts` and the drawing. Use the object-fit maths for
  `contain`/`cover` against the media element's box, which is enlarged by the crop as the
  composition already does.
- [ ] **Step 4:** Run the test, `renderer` `bun test` and `tsc`. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(composition): draw subtitle blur with backdrop-filter"`

---

### Task 9: Studio gate labels and the inspector action

**Files:**
- Modify: `dashboard/src/features/studio/StudioImportGate.tsx` (`ROLE_LABELS`, line 37; the
  reason display)
- Modify: `dashboard/src/features/studio/TimelineInspector.tsx` (video section, around line 187)
- Modify: `dashboard/src/features/workflows/OpenInStudio.tsx`, which reads outcome `not_placed`
  as done, not as a failure
- Test: `StudioImportGate.test.tsx`, `TimelineInspector.test.tsx`, `OpenInStudio.test.tsx`

**Interfaces:**
- Produces:
  - `ROLE_LABELS` adds `slide: "Slide"`, `profile_card: "Profile card"` and
    `comment_card: "Comment card"`. A slide shows as "Slide N" (order + 2), and a comment card
    as "Comment card @author" from its label.
  - The inspector, for a video clip with `blur_regions.length > 0`:
    - shows the text `Subtitles detected (N regions)`;
    - with blur off, shows a button **Blur subtitles and mute** that emits `set_clip_blur`
      (`blur_enabled: true`) and then `set_track_muted` (`muted: true`) for the clip's track;
    - with blur on, shows a button **Remove blur** that emits `set_clip_blur` (`false`) only;
    - both buttons are disabled when the clip or track is locked.

- [ ] **Step 1: Write the failing tests**
  - Gate: `"overlay items show their labels and the not-placed reason"`.
  - Inspector: `"blur subtitles and mute emits both operations in order"`,
    `"remove blur leaves the track mute alone"`, and `"no regions, no blur control"`.
  - OpenInStudio: `"a not-placed card does not count as unfinished"`. Only `unresolved` opens
    the gate.
- [ ] **Step 2:** Run the three files with `bun test`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run them, then the full `bun test`, `tsc` and `bun run build`. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(dashboard): card labels and the subtitle blur action"`

---

### Task 10: A template release that renders blur (operator gate inside)

**Files:**
- Create: `packages/remotion-composition/releases/subtitle_blur_story-v1/`, holding
  `release.json`, `document.json` and `assets/` (reuse `vertical_text_story-v1`'s
  `video.mp4` and `image.png`)
- Modify: `.github/workflows/container-image.yml` (the parity job: a second verify line), but
  only after promotion

**Interfaces:**
- Consumes: Task 1's deterministic render, Task 3's fields, Task 8's drawing.
- Produces: a 120-frame document. The video clip covers frames 0–120 with two blur regions, one
  always on and one windowed over source frames 30–90, with `blur_enabled: true`. A profile-card
  style image clip sits on `track_b_roll` at the card position. The frames are 0, 45 and 100.

- [ ] **Step 1:** Write the release files. Every asset entry carries its `sha256`.
- [ ] **Step 2: Verify the candidate** in the F1 image:
  `bun run scripts/verify-template-release.ts subtitle_blur_story-v1`, run 5 times.
  - Expected: the pair verdict is `pass` on every frame in every run, and the overall verdict is
    `golden_missing` (no golden set yet).
  - Record the contact sheet's path.
- [ ] **Step 3: Operator gate.** Report the contact sheet to the operator in Indonesian. Do not
  promote until the operator approves the golden set.
- [ ] **Step 4:** After approval, run `renderer/scripts/promote-template-release.ts` for the
  release, add the CI verify line for `subtitle_blur_story-v1`, and re-run the verify. Expected:
  `pass`.
- [ ] **Step 5: Commit** `git commit -m "test(renderer): a template release that renders subtitle blur"`

---

### Task 11: Stack smoke and records

**Files:**
- Modify: `docker/test-renderer-offline.sh` (`studio_import` driver and the clip generation in
  the verdict block)
- Modify: `CHANGELOG.md`, `docs/ROADMAP.md` (row 4 status), `docs/python-control-plane.md`
  (roles, `not_placed`, `set_clip_blur`)

**Interfaces:**
- Consumes: everything above.
- Produces: `workflow_opens_in_studio=true` now also proves the 5c-1 layout:
  - the generated clip lasts 20 s, not 3 (a 3 s main places no comment card), and the content
    set's `duration_seconds` is 20.0;
  - the content set adds a profile card PNG, two comment card PNGs (generated with ffmpeg
    `lavfi color`) and main OCR `subtitle` with one region;
  - the driver asserts:
    - 3 clips on `track_b_roll` (1 profile, 2 comments);
    - a main clip with 1 blur region and `blur_enabled` false;
    - `track_main_video.muted` false;
    - every item outcome `copied` or `reused`.

- [ ] **Step 1:** Change the driver and the generation, then run
  `bash docker/test-renderer-offline.sh` against images built from this branch, as was done for
  PR #36. Expected: `workflow_opens_in_studio=true`.
- [ ] **Step 2:** Run the full gates: `make test`, `make lint`, the PostgreSQL scripts for the
  touched files, and dashboard `bun test`, `tsc` and `build`. Expected: all green. Record the
  counts.
- [ ] **Step 3:** Write the CHANGELOG entry with Next steps (5c-2, item 6 turning on mute and
  blur, the operator's evaluation of the layout numbers), the ROADMAP row and the doc rows.
- [ ] **Step 4: Commit** `git commit -m "test(smoke): a workflow opens with cards and stored blur"`

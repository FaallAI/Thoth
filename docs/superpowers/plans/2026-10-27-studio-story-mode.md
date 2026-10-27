# Studio Story mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Studio's beat-based Story mode, with the clip fields, operations, composition, materials routes and Assist it needs. Edits must render the same in the preview and the final video.

**Architecture:**
- **Beats are computed.** They come from the draft in one pure TypeScript module and are never stored.
- **Every Story edit is a revision-bound operation.** Each operation is applied the same way by Python (`apply_edit_operations`) and TypeScript (`applyTimelineOperation`), and checked against one shared JSON case file.
- **The composition package draws the new fields** (motion, emphasis). Preview and renderer share that package.
- **Materials read the run's Content Set** through the draft's `source_workflow_id` (B9).
- **Assist calls the Prompt Lab provider inside the worker.** The provider credentials exist only in the worker, so the API runs one short Temporal workflow and waits for its result.

**Tech Stack:**
- Python: FastAPI, Pydantic v2, SQLAlchemy (sync sessions in `asyncio.to_thread`), Temporal.
- Dashboard: React 19, Tailwind v4, the custom i18n in `lib/i18n.ts`, Bun 1.4.4 tests.
- Remotion (`packages/remotion-composition`).
- Renderer (Bun).

**Spec:** `docs/superpowers/specs/2026-10-27-studio-story-mode-design.md` (approved 2026-10-27, "ya setuju"). Parent: `docs/superpowers/specs/2026-10-29-dashboard-restyle-design.md` (R6). Design: `docs/DESIGN.md` §13. Screens: `design/exports/v2/studio-story*.png`, `studio-quick-edit*-narrow.png`.

**Worktree:** `D:/thoth-tmp/wt-run-progress-p5`, branch `feat/dashboard-restyle-studio`. Ledger: `.superpowers/sdd/2026-10-27-dashboard-restyle-part-b/progress.md` in the main checkout. This plan's tasks continue that ledger as tasks S1.1 to S6.3.

## Global Constraints

**Schema:**
- Every new field is optional, and its default draws exactly what is drawn today. No database migration: documents are JSONB.
- The contract is regenerated with additions only. That covers `python/openapi.json`, `dashboard/src/api/generated/control-plane.ts` and `renderer/src/generated/edit-document.schema.json`.

**Values from the spec:**
- `StoryRole` = the import's `SourceRole` plus `hook` and `outro`.
- `motion` ∈ `none | slow_zoom | pan`, default `none`.
- `emphasis` = `{highlight: false, arrow: false}`.
- Position presets: Top, Middle and Lower third write `y` = `-0.24`, `0`, `+0.22`, keeping the clip's `x` and `scale`.
- `slow_zoom` scales 1.00 → 1.08 across the clip; `pan` translates −3 % → +3 % of the canvas width. Both are linear in the clip's own frame.
- `highlight` is a 6 px `#d49a79` outline outside the clip frame.
- `arrow` is a 120 px `#d49a79` arrow, pointing at the frame's top edge from above.
- Safe zone (TikTok, the default): top 10 %, bottom 18 %.
- Reading speed: 15 chars/s (`READING_CPS`).
- Hook: frame 0, 4 s, the run title.
- Outro: ends at the canvas end, 4 s, text "Video: @<owner> · <platform>" when the verdict names an owner; else empty.

**Anti-goals:**
- Card pixels never change. A card is never drawn for a comment without one.
- The preview never differs from the render.
- No existing draft renders differently.

**Language:**
- Every new UI string goes into the en and id catalogues of `lib/i18n.ts`.
- Repo artifacts are in English.
- Use `copper` for highlight, focus and pressed states, never `accent`.

**Process:**
- Test first. One commit per task, with a one-line subject, a single `git commit -m`, no body and no AI attribution.
- Never stage `.superpowers/`, `design/`, `graphify-out/`, `.serena/`, or `dashboard/vite.shots.config.ts`.
- Rust stays frozen; no `build_cuda.bat`.
- Offline tests only. No live provider call before the Assist gate.

**Gates (operator only):**
- push, PR, merge and deploy;
- promoting the parity golden set for the new fields;
- the live Assist check after deploy.

Renderer and Thoth deploy as one package.

**Verification per task:**

| Change | Run |
|---|---|
| Python | `wsl -e bash -lc "cd /mnt/d/thoth-tmp/wt-run-progress-p5 && make test T=<path>"`; then before the commit `make test`, `make test-postgres` and `make lint` |
| Dashboard | `bun --cwd=D:/thoth-tmp/wt-run-progress-p5/dashboard test <path>`; then `bun test` and `bun run build` in `dashboard/` |
| Renderer | `bun --cwd=D:/thoth-tmp/wt-run-progress-p5/renderer test` |

## Review Focus

1. **A clip from a draft saved before S1** (no `source_role`, `motion` or `emphasis` keys) must render and validate exactly as before. Covered by the round-trip test in S1.1 and the unchanged v1 capsule verify in S2.2.
2. **`replace_clip_asset` with a shorter video** must clamp the clip's duration so the clip never runs past the source. Every following clip must stay where it is, with no repack. Covered by the S1.1 cases `replace_video_clamps_duration` and `replace_keeps_neighbours`.
3. **Story operations on a locked clip or a locked track** must be refused, as Timeline refuses them, and the batch must leave nothing half-applied. Covered by the shared cases `position_on_locked_clip_refused` and `batch_atomic_on_refusal`.
4. **A draft whose run's Content Set is gone or unreadable** must still open Story mode. It shows its inventory without provenance, and Add from materials only offers items that already have an asset. Covered by S3.1 `test_materials_without_content_set` and S4.3 `materials panel without provenance`.
5. **Assist returning text longer than the clip allows**, or malformed JSON, must answer `assist_invalid_output` and leave the draft unchanged. Covered by S5.1 `test_assist_rejects_overlong_text` and `test_assist_rejects_malformed_output`.

---

## Phase S1: document fields and operations

### Task S1.1: Python clip fields and the five operations

**Files:**
- Modify: `python/src/thoth_control_plane/domain/edit_document_v2.py`:
  - `TimelineClipBase` (line 90);
  - `TimelineVideoClip` (line 175);
  - new `StoryRole`, `Motion`, `Emphasis`.
- Modify: `python/src/thoth_control_plane/domain/timeline_operations.py`:
  - the operation classes;
  - the `TimelineOperation` union (line ~203);
  - the `apply_timeline_operation` match (line 229);
  - `AddClipFromAsset` (line 59) and `_add_clip_from_asset` (line 447).
- Modify: `python/src/thoth_control_plane/infrastructure/editor_repository.py:374` (`_resolve_assets` also collects `ReplaceClipAsset.asset_id`).
- Modify: `python/src/thoth_control_plane/infrastructure/studio_import_repository.py`:
  - pass `source_role=entry.role` in both `AddClipFromAsset` calls (lines ~341 and ~465);
  - `_overlay` passes `fit="contain"` and `position` through the operation, replacing the post-apply mutation at lines ~483-485.
- Create: `python/tests/fixtures/story_operation_cases.json`.
- Test:
  - `python/tests/domain/test_story_operations.py` (new);
  - `python/tests/infrastructure/test_studio_import_repository*.py` (extend the existing attach test).

**Interfaces:**
- Produces (Python, `edit_document_v2.py`):
  - `StoryRole: TypeAlias = Literal[<the 11 SourceRole values>, "hook", "outro"]`, defined literally (no import from `studio_imports`, which would be circular);
  - `Motion: TypeAlias = Literal["none", "slow_zoom", "pan"]`;
  - `class Emphasis(StrictModel): highlight: bool = False; arrow: bool = False`.
- Produces (Python, clip fields):
  - `TimelineClipBase.source_role: StoryRole | None = None`;
  - `TimelineVideoClip.motion: Motion = "none"`;
  - `TimelineVideoClip.emphasis: Emphasis = Field(default_factory=Emphasis)`.
- Produces (Python, `timeline_operations.py`), every class with `kind` and `operation_id: OpaqueId`:
  - `SetClipPosition(clip_id, position: Position)`;
  - `SetClipMotion(clip_id, motion: Motion)`;
  - `SetClipEmphasis(clip_id, highlight: bool, arrow: bool)`;
  - `ReplaceClipAsset(clip_id, asset_id)`;
  - `AddTextClip(clip_id, track_id, from_frame: FrameStart, duration_in_frames: Frame, heading: ShortText, body: BodyText, style_slot: StyleSlot, source_role: Literal["hook", "outro"])`.
- Produces: `AddClipFromAsset` gains three optional fields: `fit: FitMode | None = None`, `position: Position | None = None`, `source_role: StoryRole | None = None`.
- Produces (shared case file `story_operation_cases.json`), shape `{"base": <EditDocumentV2 JSON>, "assets": {asset_id: AssetRef JSON}, "cases": [{"name", "operations": [...], "expect": {clip_id: {field: value}} | null, "refused": bool}]}`. S1.2 reads this file unchanged.

- [ ] **Step 1: Write the shared case file and the failing tests**

The base document has:
- a 1080×1920 canvas at 30 fps, 300 frames;
- scene `scene_001` (0-300);
- tracks `track_main_video`, `track_b_roll`, `track_overlay`;
- `clip_main_000` (video, on main);
- `clip_comment_card_000` (image card on b_roll, frames 60-120, `fit: contain`, `position {x: 0, y: -0.24, scale: 0.76}`);
- `clip_comment_card_001` (frames 130-190);
- `clip_locked` (a locked image clip on b_roll).

Assets:
- `asset_card_a`, `asset_card_b` (images);
- `asset_vid_long` (video, 600 frames);
- `asset_vid_short` (video, 45 frames);
- `asset_audio`.

Cases (name → expectation):

| Case | Expectation |
|---|---|
| `position_top` | `set_clip_position` y −0.24 → position equals the operation's |
| `position_on_text_refused` | refused |
| `position_on_locked_clip_refused` | refused |
| `motion_slow_zoom` | `motion` = `slow_zoom` |
| `emphasis_both` | highlight and arrow both true |
| `replace_card_keeps_layout` | asset changes; `from_frame` 60, duration 60, `fit` contain, position, motion and emphasis unchanged; `source_from_frame` 0 |
| `replace_kind_mismatch_refused` | image → `asset_audio` is refused |
| `replace_video_clamps_duration` | a 200-frame video clip on `asset_vid_long` with `source_from_frame` 90, replaced by `asset_vid_short` → duration 45, `source_from_frame` 0 |
| `replace_keeps_neighbours` | `clip_comment_card_001.from_frame` stays 130 |
| `add_hook_text` | `add_text_clip` on `track_overlay`, frames 0-120, `source_role` hook, `scene_id` null |
| `add_text_on_b_roll_refused` | refused |
| `add_text_past_canvas_refused` | from 250, length 120 → refused |
| `add_clip_with_layout` | `add_clip_from_asset` with `fit` contain, a position and `source_role` comment_card → those values stored |
| `batch_atomic_on_refusal` | `set_clip_motion` then `set_clip_position` on `clip_locked` → refused; the document is unchanged |

Python tests:
- `test_story_operation_cases` (parametrized over `cases`): apply with `apply_edit_operations(..., resolved_assets=assets)` and assert `expect` per clip, or `pytest.raises(ValueError)` when refused.
- `test_old_document_round_trips`: a v2 JSON without the new keys validates. `motion == "none"`, the emphasis is all false, `source_role is None`.
- `test_story_role_extends_source_role`: `set(get_args(StoryRole)) == set(get_args(SourceRole)) | {"hook", "outro"}`.
- Importer test: an attached `comment_card` clip has `source_role == "comment_card"`, `fit == "contain"` and the `card_position` position.

- [ ] **Step 2: Run them to see them fail**

Run: `make test T=tests/domain/test_story_operations.py`
Expected: FAIL. `StoryRole` cannot be imported, and the operations are unknown discriminator kinds.

- [ ] **Step 3: Implement the fields, operations, `_resolve_assets` and the importer change**

**Shared lock gate.** One helper, `_unlocked_video_clip(document, clip_id) -> TimelineVideoClip`, is used by the three setters. It builds on `_unlocked_clip`, and raises `ValueError` for a non-video clip.

**`replace_clip_asset`:**
- Resolve the asset as `_add_clip_from_asset` does (ready, same project).
- Require `asset.kind` to equal the kind of the clip's current asset in `asset_refs`.
- For a video asset, set `duration_in_frames = min(duration, asset.duration_in_frames)`.
- Set `source_from_frame = 0` and `ownership = "user_edited"`.
- Append the `AssetRef` when it is new.

**`add_text_clip`:**
- Require the track's kind to be `overlay`, and the clip id to be new.
- Use `ownership "user_edited"` and `scene_id None`.
- Canvas bounds come from the final `model_validate`.

- [ ] **Step 4: Run them to see them pass**

Run: `make test T=tests/domain/test_story_operations.py`, then `make test`, `make test-postgres` and `make lint`.
Expected: all pass, lint clean.

- [ ] **Step 5: Commit**

`git commit -m "Add Story clip fields and operations to the edit document"`

### Task S1.2: Contract and the TypeScript operations

**Files:**
- Regenerate:
  - `python/openapi.json` (`python/scripts/export_openapi.py`);
  - `dashboard/src/api/generated/control-plane.ts` (`bun run generate:control-plane-types`);
  - `renderer/src/generated/edit-document.schema.json` (`bun run scripts/extract-document-schema.ts` in `renderer/`).
- Modify: `dashboard/src/features/studio/timeline_domain.ts`:
  - five new `case`s in `applyTimelineOperation` (line 194);
  - `addClipFromAsset` honours `fit`, `position` and `source_role`.
- Modify: `dashboard/src/features/studio/editor_state.ts`: a new action, `{ type: "commit_operations"; operations: EditDocumentOperation[] }`.
- Test:
  - `dashboard/src/features/studio/story_operations.test.ts` (new);
  - `editor_state.test.ts`.

**Interfaces:**
- Consumes: `python/tests/fixtures/story_operation_cases.json` (S1.1), imported with `import cases from "../../../../python/tests/fixtures/story_operation_cases.json"`.
- Produces:
  - the generated types `StoryRole`, `Motion`, `Emphasis`, and the five operation shapes in the `EditDocumentOperation` union;
  - `commit_operations`, which applies the operations in order as one history entry; if any operation throws, none of them applies and the state is unchanged. It is used by S4 (add from materials, reorder), S5 (Assist apply) and S6 (Add beat).

- [ ] **Step 1: Write the failing tests**

- `story_operations.test.ts`: for each case, `applyTimelineOperation` folded over `operations` with `resolvedAssets` built from `assets` matches `expect`; refused cases throw.
- `editor_state.test.ts`: "commit_operations is one undo step". After two operations, one `undo` restores the base.
- `editor_state.test.ts`: "commit_operations is atomic". The second operation targets an unknown clip; the draft is unchanged and nothing is pending.

- [ ] **Step 2: Run them to see them fail**

Run: `bun --cwd=D:/thoth-tmp/wt-run-progress-p5/dashboard test src/features/studio/story_operations.test.ts`
Expected: FAIL (unknown operation kinds).

- [ ] **Step 3: Regenerate the contract, then add the cases and the action**

Check `git diff --stat python/openapi.json dashboard/src/api/generated renderer/src/generated`: additions only (no `-` lines other than reordered schema keys).

- [ ] **Step 4: Run them to see them pass**

Run the two test files, then `bun test`, `bun run build`, `bun --cwd=…/renderer test` (document-schema drift test) and `make test`.
Expected: all pass.

- [ ] **Step 5: Commit**

`git commit -m "Mirror the Story operations in the dashboard and regenerate the contract"`

## Phase S2: composition and parity

### Task S2.1: The composition draws motion and emphasis

**Files:**
- Modify: `packages/remotion-composition/src/AdvancedTimelineComposition.tsx`, video branch of `renderClip` (lines ~240-330).
- Create: `packages/remotion-composition/src/story_effects.ts` with the pure maths, plus `story_effects.test.ts`.
- Test: `dashboard/src/features/studio/AdvancedTimelineComposition.test.tsx` (extend).

**Interfaces:**
- Produces:
  - `motionTransform(motion: Motion, frame: number, durationInFrames: number): { scale: number; translateX: number }`, where `translateX` is a canvas-width fraction;
  - `HIGHLIGHT = { color: "#d49a79", width: 6 }`;
  - `ARROW_SIZE = 120`.

- [ ] **Step 1: Write the failing tests**

`story_effects.test.ts`:
- `none` gives `{1, 0}` at every frame.
- `slow_zoom` gives `{1, 0}` at frame 0 and `{1.08, 0}` at the last frame (`durationInFrames - 1`); half-way it is 1.04.
- `pan` gives translateX −0.03 → +0.03, and 0 at the midpoint.

Composition tests:
- A clip with `emphasis.highlight` renders an element with `data-testid="clip-highlight"` and an outline of `6px solid #d49a79`.
- `emphasis.arrow` renders `data-testid="clip-arrow"`, an SVG 120 px wide.
- A clip without the fields renders neither, and its `clip-frame` transform string equals today's exactly: `translate(0%, -24%) scale(0.76)` for the card fixture.

- [ ] **Step 2: Run them to see them fail**

Run: `bun --cwd=D:/thoth-tmp/wt-run-progress-p5/dashboard test src/features/studio/AdvancedTimelineComposition.test.tsx` and the package test.
Expected: FAIL.

- [ ] **Step 3: Implement**

**Motion.** Use `useCurrentFrame()` inside the clip's `Sequence`. It is relative to the clip, so motion runs over the clip's own duration. The motion transform is appended after the stored one: `translate(x) translate(y) scale(s) translateX(pan) scale(zoom)`. The stored placement stays the outer transform, and `none` emits no extra functions, so the string is byte-identical to today's.

**Emphasis.** Highlight and arrow are siblings drawn over the clip frame, using the same position transform, so they follow the card.

- [ ] **Step 4: Run them to see them pass**

Run: the same tests, plus `bun test`, `bun run build` and the renderer tests.
Expected: all pass.

- [ ] **Step 5: Commit**

`git commit -m "Draw clip motion and emphasis in the shared composition"`

### Task S2.2: A parity capsule for the new fields

**Files:**
- Create: `packages/remotion-composition/releases/story_mode-v1/`:
  - `document.json`, copied from `vertical_text_story-v1` plus a card clip with `motion: slow_zoom`, `emphasis {highlight: true, arrow: true}`, and a second clip with `motion: pan`;
  - `release.json` (`template_id: story_mode`, version 1, frames 0, 30, 60, 90, 119);
  - the same `assets/`.
- Modify: `renderer/src/release-capsule.ts:31-36`: add `"story_mode-v1"` to `ReleaseIdentity`, `RELEASE_IDENTITIES` and the identity map.
- Test: `renderer/src/release-capsule.test.ts`, a new case loading the `story_mode-v1` capsule.

**Interfaces:**
- Produces: the release identity `story_mode-v1`. `vertical_text_story-v1` is untouched, and its approved golden set is the proof that the defaults draw nothing new.

- [ ] **Step 1: Write the failing capsule-load test**

Run: `bun --cwd=…/renderer test src/release-capsule.test.ts`
Expected: FAIL (unknown identity).

- [ ] **Step 2: Add the capsule and the identity**

Run the test again. Expected: PASS.

- [ ] **Step 3: Capture a candidate golden run locally**

Follow the 2026-09-25 F1 Task 7 procedure in `CHANGELOG.md`:
1. Build `Dockerfile.renderer-f1` in WSL docker.
2. Run `scripts/capture-release-frames.ts story_mode-v1` inside it with `--network none`.
3. Keep the run id and its contact sheet path for the operator.

Also run `verify-template-release.ts vertical_text_story-v1` in the same image. Expected: `pass`.

If the reference image cannot be built locally, record that in the ledger and leave the capture to the operator gate.

- [ ] **Step 4: Commit**

`git commit -m "Add the story_mode parity capsule for motion and emphasis"`

Do **not** promote the golden set, and do **not** add a CI verify step for `story_mode-v1`. Both wait for the operator's golden approval. After approval: `promote-template-release.ts story_mode-v1 --run-id <run>`, then add a second verify line to the `template-release-parity` job.

## Phase S3: materials

### Task S3.1: `GET …/studio-imports/documents/{document}/materials`

**Files:**
- Modify: `python/src/thoth_control_plane/domain/studio_imports.py`: new `StudioMaterial` and `StudioMaterials` models.
- Modify: `python/src/thoth_control_plane/application/workflow_studio_imports.py`: new `materials(project_id, document_id) -> StudioMaterials`.
- Modify: `python/src/thoth_control_plane/infrastructure/studio_import_repository.py`: new `source_workflow(project_id, document_id) -> str | None`, read from `studio_import_drafts.source_workflow_id` (B9).
- Modify: `python/src/thoth_control_plane/api/routes/workflow_studio_imports.py`: the route.
- Test:
  - `python/tests/application/test_workflow_studio_imports.py`;
  - `python/tests/api/test_workflow_studio_imports.py`;
  - the Postgres repository test for `source_workflow`.

**Interfaces:**
- Produces:
  - `StudioMaterial`, made of:
    - the inventory fields: `item_id, role, label, media_kind, disposition, asset_id`;
    - the provenance fields, each `| None = None`: `platform, owner_handle, published_at, host, engagement: dict[str, int], story_score, shows_object, query, likes, author, verdict, ocr_outcome, trim_start_seconds`.
  - `StudioMaterials`: `document_id`, `provenance_available: bool`, `items: list[StudioMaterial]`, and `figures: list[{name, type, role}]` (context only, no media).
  - Client: `getStudioMaterials(projectId, documentId) => Promise<StudioMaterials>`, added to `api/control-plane.ts` in S4.3.

- [ ] **Step 1: Write the failing tests**

- `test_materials_join_provenance`: a Content Set fixture with main (verdict `replaced`, OCR `subtitle`, trim 1.5), two footage items (scores 0.8 and 0.4, query "x") and two comments (one with a card). Each inventory item carries its matching fields; `host` is the URL's host only, never the full URL.
- `test_materials_without_source_run`: a draft without `source_workflow_id` returns the inventory with `provenance_available: false`.
- `test_materials_without_content_set`: the run exists but `reports.get` returns None. Same as above, with no error.
- `test_comment_without_card_is_quote`: the comment item has `media_kind: "none"` and is never `attached`.
- `test_materials_other_project_run`: a run whose `project_id` is another project gives `provenance_available: false`.
- API test: `GET` answers 200 for a project member, 404 for another project's document, and the body has no `location` or `url` keys.

- [ ] **Step 2: Run them to see them fail**

Run: `make test T=tests/application/test_workflow_studio_imports.py`
Expected: FAIL.

- [ ] **Step 3: Implement**

**Data flow.** Inventory comes from `imports.get_inventory`. The run is `runs.get(source_workflow)` and must have the same `project_id`; ownership is not required (B9 ruling). The Content Set is read through the existing `_source(workflow_id)` loading, without the hash key.

**Join.** Join each inventory item to its Content Set entry the way `assembly/studio.py` `project_content_set` numbers items (role + order).

**Degrading.** Any `ContentSetUnavailable`, `ContentSetInvalid` or `WorkflowStudioUnavailable` while reading provenance degrades to `provenance_available: false`; it is never an error.

**Uploads.** Uploads are not part of this route. The panel reads them from the existing `listEditorAssets`.

- [ ] **Step 4: Run them to see them pass**

Run: the tests above, then `make test`, `make test-postgres` and `make lint`.
Expected: pass.

- [ ] **Step 5: Commit**

`git commit -m "Serve a draft's materials with the run's provenance"`

### Task S3.2: `POST …/materials/{item_id}/asset`

**Files:**
- Modify: `python/src/thoth_control_plane/application/workflow_studio_imports.py`: new `material_asset(project_id, document_id, item_id) -> EditorAsset`, built on `_asset_for` (line 253).
- Modify: `python/src/thoth_control_plane/api/routes/workflow_studio_imports.py`.
- Test: the same two test files.

**Interfaces:**
- Consumes: `source_workflow` (S3.1).
- Produces:
  - The route answers 200 with the editor asset (the same safe shape `listEditorAssets` returns).
  - Errors:
    - `409 {"code": "item_not_attachable"}` for a figure, a comment without a card, or an unknown item;
    - `409 content_set_unavailable` when the run's Content Set is gone;
    - `503` when media or assets are unavailable, as the existing workflow routes answer.
  - Client: `attachStudioMaterial(projectId, documentId, itemId) => Promise<EditorAsset>` (S4.3).

- [ ] **Step 1: Write the failing tests**

- `test_material_asset_copies_once`: a not-placed footage item. The first call copies, the second reuses: same `asset_id`, and `media.copy` is called once.
- `test_material_asset_reuses_comment_card`: a not-placed comment card that the import already copied → `reused`.
- `test_material_asset_not_attachable` (figure, card-less comment) → 409.
- `test_material_asset_without_run` → 409 `content_set_unavailable`.
- API: a 200 body has no storage location.

- [ ] **Step 2: Run them to see them fail.** Expected: FAIL.

- [ ] **Step 3: Implement**

`media = _source(workflow).media.get(item_id)`. If it is None, answer `item_not_attachable`. Otherwise `record, _ = await _asset_for(project_id, media)` and return the public asset. `_ItemFailed` codes map to 503.

- [ ] **Step 4: Run them to see them pass,** then `make test`, `make test-postgres` and `make lint`.

- [ ] **Step 5: Regenerate the contract** (S1.2 step 3, additions only) **and commit**

`git commit -m "Copy a run material into the editor on demand"`

## Phase S4: the Story screen

All S4 components live in `dashboard/src/features/studio/story/`. Every test renders through `src/test-render.tsx`, with at least one `{ locale: "id" }` case per component.

### Task S4.1: `story_beats.ts`

**Files:**
- Create: `dashboard/src/features/studio/story/story_beats.ts` and `story_beats.test.ts`.

**Interfaces:**
- Produces:
  - `type BeatId = "hook" | "main" | "evidence" | "reactions" | "footage" | "outro"`;
  - `type Beat = { id: BeatId; clipIds: string[]; startFrame: number; durationInFrames: number; missing: StudioImportItem[] }`;
  - `computeBeats(document: EditDocumentV2, inventory: StudioImportItem[]): Beat[]`, ordered by start;
  - `beatOfClip(document, inventory, clipId): BeatId | null`;
  - `ROLE_BEAT: Record<StoryRole, BeatId>`.

- [ ] **Step 1: Write the failing tests**

Roles:
- `main`, `main_footage`, `slide` → main;
- `post_card`, `profile_card`, `profile_page` → evidence;
- `comment_card` → reactions;
- `footage`, `creator_footage`, `creator_photo` → footage;
- `hook` → hook; `outro` → outro.

Fallbacks:
- A clip without `source_role` whose id is `clip_comment_card_001` maps through the inventory item `comment_card_001` → reactions.
- A text clip without a role inside `scene_001` takes the beat of that scene's main clip. It is never hook or outro.

Hidden clips and missing items:
- Hidden clips are excluded.
- An inventory item with `disposition: "unresolved"` whose role maps to a beat appears in that beat's `missing`.

Order and span:
- Beats are ordered by first clip start.
- A beat's start and length span its earliest start to its latest end, and overlap is allowed.
- No clips → `[]`.

- [ ] **Step 2: Run to fail; Step 3: implement; Step 4: run to pass** (`bun --cwd=… test src/features/studio/story/story_beats.test.ts`)

- [ ] **Step 5: Commit**

`git commit -m "Compute Story beats from the draft"`

### Task S4.2: Story · Timeline modes, the Story workspace, preview safe zone and beat strip

**Files:**
- Modify: `dashboard/src/features/studio/editor_state.ts:109`. The default mode becomes `"simple"` for every document. DESIGN §13.1: Story is the default for a draft from Open in Studio; Timeline is opened on demand. The stored names stay.
- Modify: `dashboard/src/features/studio/GuidedStudio.tsx`, top bar from Task 6b:
  - the mode labels become `studio.editor.story` / `studio.editor.timeline`;
  - Undo and Redo move out of the tools menu into icon buttons (`Undo2`/`Redo2`, accessible names "Undo" / "Redo");
  - "Request review" calls `selectJob("review")` and focuses the comment box;
  - a v2 document in `simple` mode renders `<StoryWorkspace>`;
  - a v1 document keeps today's scene editor (the beat UI needs v2).
- Create: `story/StoryWorkspace.tsx`, `story/StoryPreview.tsx`, `story/BeatStrip.tsx`, with tests.
- Modify: `lib/i18n.ts`, both catalogues.

**Interfaces:**
- Consumes: `computeBeats` (S4.1), `commit_operations` (S1.2).
- Produces:
  - `StoryWorkspace` props `{ state, dispatch, client, projectId, documentId, compact }`;
  - `BeatStrip` props `{ beats, selected: BeatId | null, onSelect(id), onAddBeat?, dropTarget?: BeatId | null }`.
  - Selecting a beat dispatches `set_playhead` to `beat.startFrame`, and the strip's selected tile has `aria-pressed=true`.

- [ ] **Step 1: Write the failing tests**

Modes and top bar:
- "a timeline draft opens in Story"; the mode group shows Story · Timeline (id: "Cerita" · "Timeline").
- Undo is a top-bar button.
- "Request review" switches to Review, and the comment box has focus.

Preview:
- The safe-zone toggle (`aria-pressed`) shows two overlays: top `10%` height and bottom `18%` height (asserted on the style).
- The canvas label reads `9:16 · 1080 × 1920`.

Beat strip:
- One tile per beat, each with name and length (`4.0 s`).
- Clicking a tile sets the playhead to its start and outlines it with copper.
- A tile whose beat has `missing` shows the red dot (accessible text "1 missing").
- The total length shows on the left.

Regression: existing GuidedStudio tests that assumed `advanced` by default select Timeline explicitly. List each changed test in the commit's ledger entry.

- [ ] **Step 2: Run to fail**

Run: `bun --cwd=… test src/features/studio/story src/features/studio/GuidedStudio.test.tsx`

- [ ] **Step 3: Implement.** The preview reuses the existing `StudioPreview` player; the safe zone is two absolutely placed overlays over it.

- [ ] **Step 4: Run to pass,** then `bun test` and `bun run build`.

- [ ] **Step 5: Commit**

`git commit -m "Open drafts in Story mode with the beat strip and safe zone"`

### Task S4.3: Materials panel

**Files:**
- Modify: `dashboard/src/api/control-plane.ts`: `getStudioMaterials` and `attachStudioMaterial` (S3.1 and S3.2 paths), plus fakes in the test client.
- Create: `story/MaterialsPanel.tsx` and its test.
- Modify: `lib/i18n.ts`.

**Interfaces:**
- Consumes: `StudioMaterials` (S3.1), `listEditorAssets` (uploads), `computeBeats` (used-in).
- Produces: `MaterialsPanel` props `{ materials: StudioMaterials | null, uploads: EditorAsset[], beats: Beat[], document, onDragMaterial(item) }`.
  - `materialDragType = "application/x-thoth-material"`. The drag data is the `item_id`, or `upload:<asset_id>`.

**Layout rules:**
- Groups: Main, Cards (`post_card`, `profile_card`, `profile_page`, `comment_card`), Footage, Photos (`creator_photo`), Figures, Comments (judged, the `comment` role), Uploads.
- Each group is collapsible and shows its count.
- A group shows 6 items, then "Show n more".
- Search filters by label, handle and query, case-insensitive.

**Why popover:**
- Main: verdict ("Original" / "Repost of @owner"), plus the OCR outcome and its trim.
- Footage: query, story score (as a percentage), and "Shows the object" / "Partly".
- Comment cards: likes and author.
- Posts and profiles: capture time and platform.
- Missing values are omitted.

**Chips:** "Used in <beat>" chips come from the asset ids in the beats' clips.

- [ ] **Step 1: Write the failing tests**

- Groups and counts from a fixture.
- "Show 3 more" appears after 6 footage items.
- Search "cat" keeps only matching items.
- The why popover for footage shows `Query: x`, `Story score 80%` and `Shows the object`.
- A material whose asset sits in a reactions clip shows "Used in Reactions".
- **Materials panel without provenance:** with `provenance_available: false`, items show labels only, there is no why button, and a quiet note reads "Provenance unavailable for this draft".
- Indonesian group titles.

- [ ] **Step 2: run to fail; Step 3: implement; Step 4: run to pass** (then `bun test`, `bun run build`)

- [ ] **Step 5: Commit**

`git commit -m "Add the Story materials panel with provenance"`

### Task S4.4: Beat inspector

**Files:**
- Create: `story/BeatInspector.tsx`, `story/story_edits.ts` (pure operation builders) and their tests.
- Modify: `lib/i18n.ts`.

**Interfaces:**
- Produces (`story_edits.ts`), each returning `EditDocumentOperation[]` with fresh ids from `makeOperationId()`:
  - `swapClips(document, a, b)`: two `move_clip` operations exchanging starts;
  - `removeFromBeat(clipId)`: `set_clip_hidden`;
  - `setEachCardSeconds(document, clipIds, seconds)`: `trim_clip_end` on each clip;
  - `setPositionPreset(document, clipIds, preset: "top" | "middle" | "lower")`: `set_clip_position` with y −0.24 / 0 / +0.22, keeping each clip's x and scale (missing position = `{x: 0, y: 0, scale: 1}`);
  - `setMotion(clipIds, motion)`;
  - `setEmphasis(clipIds, highlight, arrow)`;
  - `addMaterialToBeat(document, beat, asset, role)`: an `add_clip_from_asset` on `track_b_roll` after the beat's last clip end, lasting the beat's longest card length, with `fit: "contain"`, position `{x: 0, y: CARD_CENTER_Y − 0.5, scale: CARD_WIDTH}` (`0.76`, `0.26` from `studio_layout.py`) and `source_role`.
- Produces: `BeatInspector` props `{ beat, document, inventory, materials, dispatch, client, projectId, documentId }`. Every edit goes through `dispatch({type: "commit_operations", operations})`.

**Sections by beat:**
- Card beats (Evidence, Reactions): shown cards, each card's seconds, position, motion and emphasis.
- Main and Footage: their length, read-only, with the note "Follows the video · trim it in Timeline".
- Hook and Outro: the text clip's length.

- [ ] **Step 1: Write the failing tests**

`story_edits.test.ts`:
- `setPositionPreset` "lower" on a card with x 0.1 and scale 0.76 writes `{x: 0.1, y: 0.22, scale: 0.76}`.
- `swapClips` exchanges 60 ↔ 130.
- `addMaterialToBeat` places the clip at `beat.startFrame + beat.durationInFrames` with fit contain.

`BeatInspector.test.tsx`:
- The header reads "Beat 3 of 5 · 4.0 s · 2 materials".
- ↑ on the second card commits a swap.
- Remove commits `set_clip_hidden`.
- "Each card" 3 s commits `trim_clip_end` to 90 frames on each card.
- The reading check reads "Reading speed 15 chars/s · longest card needs 3.2 s" for a 48-character label.
- Lower third, Slow zoom and Highlight each commit their operation for every card.
- A Main beat shows its length read-only and hides Position, Motion and Emphasis.
- "Add from materials" lists only materials not in this beat. Picking a not-yet-attached one calls `attachStudioMaterial`, dispatches `assets_loaded` (replace false), then commits `addMaterialToBeat`.
- Indonesian section titles.

- [ ] **Step 2: run to fail; Step 3: implement; Step 4: run to pass** (then `bun test`, `bun run build`)

- [ ] **Step 5: Commit**

`git commit -m "Add the Story beat inspector"`

### Task S4.5: Drag, missing material and the conflict banner

**Files:**
- Modify: `story/BeatStrip.tsx`, `story/BeatInspector.tsx`, `story/StoryWorkspace.tsx`.
- Modify: the conflict banner in `GuidedStudio.tsx`.
- Modify: `lib/i18n.ts`.

**Interfaces:**
- Consumes: `addMaterialToBeat` (S4.4), `attachStudioMaterial`, and the existing `resolveStudioImportItem` (exclude decision).

**Behaviour:**
- **Drag.** Dropping a material on a tile adds it to that beat through `addMaterialToBeat`. While dragging over a tile, the tile has a dashed copper outline and the material shows "+ Add to <beat>".
- **Missing material.** An alert names the item and its reason through the existing `reasonText`. The fitting alternative is "Use profile card" when the profile page is missing and a profile card material exists. "Remove from beat" sends an exclude decision.
- **Conflict.** The banner text becomes "A newer revision {revision} was saved · your changes are kept on this device", with the existing two buttons.

- [ ] **Step 1: Write the failing tests**

- Firing `dragOver` then `drop` with the material type on the Reactions tile commits an `add_clip_from_asset` with `source_role` comment_card.
- The dashed outline class is present during `dragOver`.
- A missing `profile_page` with a profile card present shows "Use profile card", which adds that card to Evidence.
- "Remove from beat" calls `resolveStudioImportItem` with `decision: "exclude"`.
- On conflict, the banner shows the latest revision number, in both languages.

- [ ] **Step 2: run to fail; Step 3: implement; Step 4: run to pass** (then `bun test`, `bun run build`)

- [ ] **Step 5: Screens**

Take screens at 1440 and 1024 with the scratchpad `mock-api-studio.mjs` (extended with materials) and `shot-cdp.mjs` from `vite preview`. Save them to `D:/thoth-tmp/restyle-shots/r6/` and compare them with `design/exports/v2/studio-story*.png`. Record the differences in the ledger.

- [ ] **Step 6: Commit**

`git commit -m "Add Story drag, missing-material and conflict states"`

## Phase S5: Assist

### Task S5.1: Assist backend

**Files:**
- Modify: `python/src/thoth_control_plane/domain/prompts.py`:
  - `PromptStageId` gains `"story_assist"`;
  - `PROMPT_STARTERS["story_assist"]` gets an English starter: the person is finishing a short vertical video, rewrite the given text for the beat, keep facts, never invent names, answer JSON `{"title", "reason", "text"}`.
- Modify: `python/src/thoth_control_plane/infrastructure/prompt_provider.py`:
  - move the HTTP call in `propose` into `_chat(runtime, payload) -> str`;
  - add `complete_json(*, provider_id, model_id, system, user) -> dict[str, Any]`, which checks the model exists with the `improve` capability and `len(user) <= max_input_chars`, meters as `propose` does, and parses one JSON object.
- Create: `python/src/thoth_control_plane/activities/story_assist.py` (`StoryAssistActivity`).
- Create: `python/src/thoth_control_plane/workflows/story_assist.py` (`StoryAssistWorkflow`, one activity, 60 s timeout, no retries).
- Create: `python/src/thoth_control_plane/application/story_assist.py` (`StoryAssistService`).
- Create: `python/src/thoth_control_plane/infrastructure/story_assist_gateway.py`, which runs `execute_workflow(..., task_queue=PROMPT_PROPOSAL_TASK_QUEUE)`.
- Modify: `worker.py` (register the workflow and activity beside the prompt proposal ones) and `api/app.py` (wire the service).
- Modify: `python/src/thoth_control_plane/api/routes/edit_documents.py` (the route).
- Test: new `tests/application/test_story_assist.py`, `tests/activities/test_story_assist.py`; extend `tests/infrastructure/test_prompt_provider.py` and `tests/api/test_edit_documents*.py`.

**Interfaces:**
- Produces:
  - `POST /projects/{p}/edit-documents/{d}/assist`, body `StoryAssistRequest {base_revision: int, beat: BeatId literal, clip_ids: list[OpaqueId] (1..20)}`;
  - response `StoryAssistProposal {proposal_id: str, title: str, reason: str, operations: list[EditDocumentOperation]}`.
- Rules:
  1. Load the document at `base_revision`; a mismatch answers 409 `document_revision_conflict`.
  2. Read the project's preference for `story_assist`. With none, answer 409 `assist_not_configured`.
  3. The system prompt is the project's saved prompt for the stage when one exists, else the starter.
  4. The user message holds the beat name, the beat's text (text clip heading and body, caption cue text), the run title and the Content Set `main.description` (first 500 chars) when readable, and the rule "readable at 15 chars/s within <clip seconds> s" (one clip: the lone text clip's limit is `seconds × 15` characters).
  5. The returned `text` becomes one operation: `replace_text` (`field: "heading"`) for a text clip, or `set_caption_cue_text` for cue 0 of a caption clip.
  6. Text over the clip's `seconds × 15` limit, blank text, or non-JSON output answers 422 `assist_invalid_output`.
  7. Provider timeout, rate limit or unavailability answers 503 `assist_unavailable`.
  8. Nothing is stored.
- **Ruling: Assist never returns `add_text_clip`.** The spec lists `add_text_clip` among Assist's operations, but a proposal always targets a selected beat's existing clips. An outro without a text clip is made by Add beat (S6.1) first. Cost if wrong: one more operation kind in rule 5.

- [ ] **Step 1: Write the failing tests**

All with a fake gateway or provider:
- `test_assist_builds_replace_text`;
- `test_assist_caption_cue`;
- `test_assist_rejects_overlong_text` (a 4 s hook, 61 characters → 422);
- `test_assist_rejects_malformed_output`;
- `test_assist_not_configured`;
- `test_assist_revision_conflict`;
- `test_assist_meters_call`, with the provider `complete_json` against a `respx` mock: one usage event, with the token counts.
- `test_complete_json_requires_improve_capability`.
- `test_story_assist_stage_listed`: `/prompt-stages` includes `story_assist`.
- The Temporal worker test registers `StoryAssistWorkflow`, following the prompt proposal worker test.

- [ ] **Step 2: run to fail; Step 3: implement; Step 4: run to pass**

Run the tests above, then `make test`, `make test-postgres` and `make lint`.

- [ ] **Step 5: Regenerate the contract** (additions only) **and commit**

`git commit -m "Add Story Assist text proposals through the prompt provider"`

### Task S5.2: Assist panel

**Files:**
- Modify: `dashboard/src/api/control-plane.ts`: `requestStoryAssist(projectId, documentId, body) => Promise<StoryAssistProposal>`.
- Create: `story/AssistPanel.tsx` and its test.
- Modify: `GuidedStudio.tsx`: the Assist toggle in the top bar (purple accent, `aria-pressed`), shown in Story only.
- Modify: `StoryWorkspace.tsx` (the panel sits beside the inspector) and `lib/i18n.ts`.

**Interfaces:**
- Consumes: `commit_operations` and the selected `Beat`.

**States:**

| State | What shows |
|---|---|
| idle | "Suggest for <beat>" |
| thinking | spinner and "Thinking…" |
| proposal | title, reason, the proposed text, Apply and Dismiss |
| failed | a message per code: not configured (with a link to Presets & prompts), invalid output, unavailable |

Apply commits the proposal's operations. Dismiss forgets it. A beat change resets the panel.

- [ ] **Step 1: Write the failing tests**

- The toggle shows the panel.
- Suggest calls `requestStoryAssist` with `{base_revision, beat: "hook", clip_ids}`.
- Apply dispatches `commit_operations` with the returned operations.
- Dismiss clears the panel without dispatching.
- `assist_not_configured` shows the Presets & prompts link.
- The panel is not rendered in Timeline.
- Indonesian strings.

- [ ] **Step 2: run to fail; Step 3: implement; Step 4: run to pass** (then `bun test`, `bun run build`)

- [ ] **Step 5: Commit**

`git commit -m "Add the Story Assist panel"`

## Phase S6: Add beat and phone

### Task S6.1: Add beat (Hook, Outro)

**Files:**
- Modify: `story/story_edits.ts` (`addHook`, `addOutro`), `story/BeatStrip.tsx` (the "Add beat" menu), `lib/i18n.ts`.
- Test: `story_edits.test.ts`, `BeatStrip.test.tsx`.

**Interfaces:**
- Produces:
  - `addHook(document, title: string): EditDocumentOperation`: `add_text_clip` on `track_overlay`, from 0, `4 × fps` frames, `heading` = the title cut to 120 characters, `body` "", `style_slot "title"`, `source_role "hook"`.
  - `addOutro(document, credit: string): EditDocumentOperation`: from `canvas.duration_in_frames − 4 × fps`, `heading` = the credit, `source_role "outro"`.
  - `creditLine(owner?: string, platform?: string): string`: "Video: @owner · Platform" when the owner is known, else "".
- Consumes: the run title and owner from the B9 list fields (`source_title`, `source_owner_handle`, `source_platform`). Read them from the documents list entry the editor was opened with, or from `getStudioMaterials`' main item when absent.

- [ ] **Step 1: Write the failing tests**

- `addHook` on a 30 fps doc gives `from_frame 0` and `duration 120`.
- `addOutro` on a 300-frame canvas gives `from_frame 180`.
- `creditLine("cat", "tiktok")` = "Video: @cat · TikTok".
- The menu offers Hook only when no beat is hook, and Outro only when none is outro.
- A canvas shorter than 4 s clamps the duration to the canvas.

- [ ] **Step 2: run to fail; Step 3: implement; Step 4: run to pass** (then `bun test`, `bun run build`)

- [ ] **Step 5: Commit**

`git commit -m "Add Hook and Outro beats from the beat strip"`

### Task S6.2: Phone quick edit and the swap sheet

**Files:**
- Create: `story/QuickEdit.tsx`, `story/SwapCardSheet.tsx`, and tests.
- Modify: `StoryWorkspace.tsx` (renders `QuickEdit` when `compact`) and `lib/i18n.ts`.

**Interfaces:**
- Consumes: `replace_clip_asset` (S1), `attachStudioMaterial` and `getStudioMaterials` (S4.3), the existing caption editor component (`CaptionTextInspector`).

**Layout:**
- Header: "Quick edit · Rev n".
- The preview.
- Rows:
  - Hook text: `replace_text` on the hook clip; hidden when there is no hook.
  - Captions: the existing editor.
  - Swap comment card: opens a bottom sheet of the run's comment cards (materials with role `comment_card`), each with handle, label and likes; the one in use is marked.
- "Swap card" attaches the material when needed, then commits `replace_clip_asset` on the reactions clip being swapped.
- Closing note: "Beats and timeline editing need a larger screen".
- No beat strip, no reorder, no render start.

- [ ] **Step 1: Write the failing tests**

- At compact width, QuickEdit shows and BeatStrip does not.
- Editing the hook text commits `replace_text`.
- The sheet lists 3 cards and marks the one in use with `aria-current`.
- Swap calls `attachStudioMaterial` for a not-attached card, then commits `replace_clip_asset` with the new `asset_id`.
- A run with no comment cards hides the swap row.
- Indonesian header.

- [ ] **Step 2: run to fail; Step 3: implement; Step 4: run to pass** (then `bun test`, `bun run build`)

- [ ] **Step 5: Screens**

Take screens at 430 to `D:/thoth-tmp/restyle-shots/r6/` and compare with `studio-quick-edit*-narrow.png`.

- [ ] **Step 6: Commit**

`git commit -m "Add the phone quick edit with the comment card swap"`

### Task S6.3: Close-out

**Files:**
- Modify: `CHANGELOG.md` (one entry for Story mode S1–S6, with verification and Next steps).
- Modify: the ledger `progress.md` (tasks S1.1–S6.2 complete, rulings).
- Modify: `docs/superpowers/specs/2026-10-29-dashboard-restyle-design.md` §3 R6 (a pointer to the Story mode spec), additions only.

- [ ] **Step 1: Full verification**

Run, in order:
1. `make test`, `make test-postgres`, `make lint`;
2. `bun test` and `bun run build` in `dashboard/`;
3. the renderer tests;
4. `git diff --check caeebcf6..HEAD`.

Record the exact counts.

- [ ] **Step 2: Write the CHANGELOG and ledger entries**

Next steps:
- R7: Timeline restyle and clean-up: F3 aliases, dead `pen-studio` and `studio-prompt-*` CSS, `content_set_import.ts`, StudioPreview's "Back to Content Set", and deleting `dashboard/vite.shots.config.ts`.
- Part B release gates: push, PR, merge and deploy, each the operator's.
- Golden approval for `story_mode-v1`.
- The live Assist check after deploy.
- The follow-ups carried from Tasks 1–6b.

- [ ] **Step 3: Commit**

`git commit -m "Record Story mode in the changelog"`

Stop here. R7 starts only on the operator's word.

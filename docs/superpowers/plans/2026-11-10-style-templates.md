# Style Templates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A draft opened in Studio can take Style A or Style B with one choice. The style rebuilds
the draft's cuts and look from its materials and writes a new script in the style's voice. The
cuts can be previewed before any voice is paid for.

**Architecture:**
- A style is a stored, versioned `StyleTemplate`. Two built-in rows are seeded.
- A pure compiler turns a template plus a draft into ordinary typed edit operations. The server
  applies them as one revision, which the client undoes as one step.
- One pure cut function places shots for all three uses: the apply step (no timing), the cut
  preview (timing estimated from the script), and the narration write (real word timing).
- Each style's script prompt is a Prompt Lab stage `style_script`, with one variant per template.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, Temporal activities, SQLAlchemy with SQL-file
Alembic migrations, React 19 + TypeScript (Bun), Remotion Player.

**Spec:** `docs/superpowers/specs/2026-11-10-style-templates-design.md` (approved 2026-11-10).
Branch `feat/style-templates`, stacked on `feat/studio-effects-layer` (PR #127).

## Global Constraints

**Fields and rollback**
- Every new document or payload field is optional with a default and left out of the stored
  document when unused (`exclude_if`).
- New fields that TypeScript must see as optional use `default_factory` (openapi-typescript makes
  plain defaults required).
- The migration's rollback note says how to roll back past it.

**Editing and spending**
- The look and cuts are applied only through typed edit operations. Nothing writes a free-form
  timeline.
- Nothing pays for a voice until the operator approves a script. Tests make no paid or network
  calls: providers are stubbed.

**Logs:** `info` for a style applied, `warning` for a rule skipped, `debug` for each operation.

**Verification**
- Python: `MSYS_NO_PATHCONV=1 wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER && make test T="<path>"'`,
  then the full `make test`, `make test-postgres` (for the repository and the migration) and
  `make lint`.
- Dashboard: `bash D:/thoth-tmp/fixes/fw_check.sh <paths relative to dashboard>`, and the full run
  `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/fixes/dash_full.sh full </dev/null`.
- Contracts after any API or model change: `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/fixes/export_openapi.sh`,
  then `cd dashboard && bun run generate:control-plane-types`, then `cd renderer && bun run schema`.

**Commits:** one `git commit -m "<subject>"` per commit, at most 72 characters, no body, no
attribution. Repository text is in English.

## Review Focus

- **A beat with a locked clip.** The locked clip stays exactly as it is, and the rest of the beat
  is rebuilt around it. Pinned in Task 4.
- **A hidden clip.** Its material is not placed again: the operator hid it. Pinned in Task 4.
- **A movie shorter than the shots the rules ask for.** No shot reads past the asset's end; the
  next shot cycles to the next material. Pinned in Task 3.
- **A style applied while a narration runs or waits.** The answer is 409
  `narration_in_progress` and nothing changes. Pinned in Task 5.
- **A beat shorter than one shot.** It gets exactly one shot, never a zero-length clip. Pinned in
  Task 3.

---

### Task 1: The style template and the two built-in styles

**Files:**
- Create: `python/src/thoth_control_plane/domain/style_templates.py`
- Create: `python/src/thoth_control_plane/domain/move_presets.py` (a Python port of `dashboard/src/features/studio/move_presets.ts`)
- Create: `dashboard/src/features/studio/move_preset_cases.json` (shared cases)
- Modify: `dashboard/src/features/studio/move_presets.test.ts` (run the shared cases too)
- Test: `python/tests/domain/test_style_templates.py`, `python/tests/domain/test_move_presets.py`

**Interfaces:**
- Produces:
  - `MovePreset = Literal["none","push_in","pan_across","scroll_down","pull_out"]`;
  - `BeatLook(StrictModel)`, with:
    - `use: bool = True`;
    - `move: MovePreset = "none"`;
    - `background: Background = "none"`;
    - `dim: Dim = 0.0`;
    - `highlight: bool = False`;
    - `arrow: bool = False`;
    - `heading_place: Literal["title_top","title","title_lower","card"] | None = None`;
  - `CutRules(StrictModel)`, with:
    - `max_shot_seconds: float` (between 1.0 and 20.0);
    - `min_shot_seconds: float = 1.0`;
    - `cut_on_sentences: bool = True`;
    - `cycle_materials: bool = True`;
    - `card_between_facts: bool = False`;
  - `CaptionRules(StrictModel)`, with:
    - `style: Literal["boxed","kinetic","word_highlight"]`;
    - `words_per_caption: int` (between 1 and 8);
  - `NarrationRules(StrictModel)`, with:
    - `starter: str`;
    - `target_seconds: int | None = None`;
    - `card_lines: bool = False`;
    - `card_line_max_words: int = 6`;
    - `card_seconds: float = 2.0`;
    - `max_sfx_cues: int | None = None`;
  - `StyleTemplate(StrictModel)`, with:
    - `template_id: OpaqueId`;
    - `name: str`;
    - `revision: int`;
    - `origin: Literal["built_in"]`;
    - `beats: dict[BeatId, BeatLook]`, holding exactly the six `BEAT_ORDER` keys;
    - `cuts: CutRules`;
    - `captions: CaptionRules`;
    - `narration: NarrationRules`;
  - `BUILT_IN_STYLES: dict[str, StyleTemplate]`, keyed `"style_a"` and `"style_b"`;
  - `move_preset(kind: MovePreset, duration: int, fps: float) -> list[MoveKeyframe]`, giving the same
    keyframes as `movePreset` in TypeScript for the four playhead-free presets, and `[]` for `"none"`.

- [ ] **Step 1: Write the failing tests**
  - `test_both_built_in_styles_cover_every_beat`: `set(style.beats) == set(BEAT_ORDER)` for both
    styles.
  - `test_style_a_values`:
    - `captions.style == "boxed"`;
    - `cuts.max_shot_seconds == 5.0`;
    - `narration.card_lines is False`;
    - `beats["hook"].heading_place == "title_top"`;
    - `beats["main"].background == "blur_fill"`;
    - `beats["evidence"].highlight and beats["evidence"].arrow`;
    - `beats["footage"].background == "blur_fill"`.
  - `test_style_b_values`:
    - `captions.style == "kinetic"`;
    - `cuts.max_shot_seconds == 3.0`;
    - `cuts.card_between_facts is True`;
    - `narration.card_lines is True`;
    - `beats["main"].dim == 0.45`;
    - every beat's `move` is in `{"push_in","none"}`.
  - `test_a_template_missing_a_beat_is_refused`: `ValidationError`.
  - `test_starters_are_written`: both starters are non-empty and Indonesian. The A starter names
    Hook → Tension → Solution → Call-To-Value. The B starter asks for a metaphor in the hook that
    returns in the outro, and a reaction after each fact.
  - Shared `move_preset_cases.json`: at least 8 cases (`push_in`, `pan_across`, `scroll_down` and
    `pull_out` at 90 and at 1 frame). Both `test_move_presets.py` and `move_presets.test.ts` run
    them.
  - `test_a_one_frame_preset_is_one_keyframe`: `move_preset("push_in", 1, 30)` has length 1.
    TypeScript `movePreset` gets the same rule, fixing the deferred minor about one-frame clips.

- [ ] **Step 2: Run the tests; expect FAIL** (module not found).

- [ ] **Step 3: Implement both modules and the TypeScript one-frame rule**
  - Spec §5 fixes the values.
  - The starters are fresh Indonesian prose following the editor readings: claim, then evidence,
    then twist for A; questions and reactions, with the metaphor as bookends, for B.

- [ ] **Step 4: Run them; expect PASS.** Then run `move_presets.test.ts`.

- [ ] **Step 5: Commit:** `Add style templates with built-in Style A and Style B`.

### Task 2: Stored templates and the draft's applied style

**Files:**
- Create: `python/migrations/editor/0028_style_templates.sql` and `python/migrations/editor/alembic/versions/0028_style_templates.py` (same pattern as 0027)
- Modify: `python/src/thoth_control_plane/infrastructure/editor_models.py` (`StyleTemplateRow`)
- Create: `python/src/thoth_control_plane/infrastructure/style_template_repository.py`
- Modify: `python/src/thoth_control_plane/domain/edit_document_v2.py` (`AppliedStyle`, `EditDocumentV2.style`)
- Modify: `python/src/thoth_control_plane/domain/timeline_operations.py` (`SetDocumentStyle`)
- Modify: `dashboard/src/features/studio/timeline_domain.ts` (mirror `set_document_style`)
- Test: `python/tests/infrastructure/test_style_template_repository_postgres.py`, `python/tests/domain/test_edit_document_v2.py`, `python/tests/domain/test_timeline_operations.py`, `dashboard/src/features/studio/timeline_domain.test.ts`

**Interfaces:**
- Consumes: `StyleTemplate` and `BUILT_IN_STYLES` (Task 1).
- Produces:
  - The table `style_templates`, with:
    - `workspace_id text NULL` (NULL means built in);
    - `template_id text`;
    - `revision int`;
    - `body jsonb`;
    - primary key `(template_id, revision)`.
  - The migration seeds `style_a` and `style_b` at revision 1 from `BUILT_IN_STYLES`, serialized
    by the migration script.
  - `PostgresStyleTemplateRepository`, with:
    - `list_for(workspace_id: str) -> list[StyleTemplate]`, which returns built-ins plus that
      workspace's templates, latest revision each;
    - `get(template_id: str, workspace_id: str) -> StyleTemplate | None`.
  - `MemoryStyleTemplateRepository` with the same interface, for tests.
  - `AppliedStyle(StrictModel)`, with `template_id: OpaqueId` and `revision: int`.
  - `EditDocumentV2.style: AppliedStyle | None`, using `default_factory=lambda: None` and
    `exclude_if=None`.
  - `SetDocumentStyle`, with:
    - `kind: Literal["set_document_style"]`;
    - `operation_id`;
    - `style: AppliedStyle | None`.

- [ ] **Step 1: Write the failing tests.**
  - `test_built_ins_are_listed_for_any_workspace` (postgres).
  - `test_a_draft_without_a_style_dumps_no_style_key`.
  - `test_set_document_style_records_and_clears_it`.
  - The client mirror test: `set_document_style` sets and clears `document.style`.
- [ ] **Step 2: Run them; expect FAIL.**
- [ ] **Step 3: Implement; regenerate the contracts** (Global Constraints).
- [ ] **Step 4: Run** the domain tests, `make test-postgres` and the dashboard mirror test; expect
  PASS.
- [ ] **Step 5: Commit:** `Store style templates and record the style a draft took`.

### Task 3: The cut function

**Files:**
- Create: `python/src/thoth_control_plane/domain/style_cuts.py`
- Test: `python/tests/domain/test_style_cuts.py`

**Interfaces:**
- Consumes: `CutRules` (Task 1).
- Produces:
  - `ShotSource(frozen dataclass)`, with:
    - `asset_id: str`;
    - `kind: Literal["video","image"]`;
    - `source_from_frame: int`;
    - `source_frames: int | None` (None for an image);
    - `item_id: str | None`.
  - `Shot(frozen dataclass)`, with:
    - `from_frame: int`;
    - `duration: int`;
    - `source: ShotSource | None` (None means a card-line slot);
    - `source_from_frame: int`.
  - `plan_shots(start: int, end: int, sources: Sequence[ShotSource], rules: CutRules, fps: float, sentence_ends: Sequence[int] = (), card_slots: int = 0) -> list[Shot]`.

**The algorithm, which the tests pin:**
1. **Walking the beat.** Walk from `start` to `end`.
   - Each shot ends at the last sentence end that is at least `min_shot` and at most `max_shot`
     away.
   - If there is none, it ends at `max_shot`.
   - Without sentence ends, the beat is split into equal shots of at most `max_shot`.
2. **Short tails.** A tail shorter than `min_shot` merges into the shot before it.
3. **Cycling materials.** With `cycle_materials`, sources rotate shot by shot. A movie resumes
   where its last shot stopped. When a movie has no frames left, the next source is used. With
   no source left, the movie restarts from its own `source_from_frame`.
4. **Card slots.** With `card_between_facts` and `card_slots > 0`, a slot of the card length is
   inserted after every second shot, up to `card_slots`.

- [ ] **Step 1: Write the failing tests.**
  - `test_shots_never_exceed_max`: a beat of 330 frames at 30 fps with a 5 s maximum gives shots of
    at most 150 frames.
  - `test_cuts_snap_to_sentence_ends`: sentence ends `[100, 200]` in 0–260 with max 150 give shots
    starting at 0, 100 and 200.
  - `test_a_beat_shorter_than_one_shot_gets_one_shot`: 0–20 gives exactly one shot of 20 frames.
  - `test_a_short_tail_merges`: 0–155 with max 150 and min 30 gives one 155-frame shot.
  - `test_materials_cycle_and_a_short_movie_hands_over`: two sources, the first a 40-frame movie;
    no shot reads past frame 40 of it.
  - `test_cards_sit_between_facts`: `card_slots=2` with card 60 gives a `None` source after shot 2
    and after shot 4.
- [ ] **Step 2: Run them; expect FAIL.**
- [ ] **Step 3: Implement `plan_shots`** as described above.
- [ ] **Step 4: Run them; expect PASS.**
- [ ] **Step 5: Commit:** `Plan a beat's shots from a style's cut rules`.

### Task 4: The style compiler

**Files:**
- Create: `python/src/thoth_control_plane/domain/style_apply.py`
- Test: `python/tests/domain/test_style_apply.py` (fixtures built from the narrated draft fixtures of `test_narration_timeline.py`)

**Interfaces:**
- Consumes:
  - `plan_shots`, `ShotSource` and `Shot` (Task 3);
  - `move_preset` and `StyleTemplate` (Task 1);
  - `SetDocumentStyle` (Task 2);
  - `clip_beats` and `beat_spans` (`domain/story_beats.py`).
- Produces: `style_operations(document: EditDocumentV2, template: StyleTemplate, roles_by_item: Mapping[str, str] | None = None, sentence_ends: Mapping[BeatId, Sequence[int]] | None = None, card_lines: Mapping[BeatId, str] | None = None) -> list[EditDocumentOperation]`.

**What it does, per beat in `beat_spans`:**
1. **Sources.** The beat's picture clips are its visible video clips that are not locked, in time
   order. Their assets become `ShotSource`s.
2. **Removal.** Those clips are removed with `remove_clip`. Locked clips stay.
3. **Shots.** `plan_shots` is called over the beat's span. Each shot is added with
   `add_clip_from_asset` on the beat's own track, with:
   - the beat's `scene_id` and `source_role`;
   - `fit="contain"` and `background="blur_fill"` when the look says blur-fill and the asset is
     not 9:16 (`full_frame_fill`);
   - `set_clip_moves` from `move_preset(look.move, …)`;
   - `set_clip_dim`;
   - `set_clip_emphasis` for highlight and arrow.
4. **Card lines.** A `None` shot, or a card line at the beat start when `card_lines` is given,
   becomes `add_text_clip` with `style_slot="card"`.
5. **Heading.** The beat's heading text clip gets `set_text_place` from `heading_place`.
6. **Captions.** Every caption clip gets `set_caption_style` from the template.
7. **Style record.** The last operation is `set_document_style`.

A beat with `use=False` keeps its clips hidden (`set_clip_hidden`). The function never touches
narration, SFX, music, or clips with no beat.

- [ ] **Step 1: Write the failing tests.** For each, apply the operations with
  `apply_edit_operations`, then assert:
  - `test_style_a_rebuilds_each_beat` and `test_style_b_rebuilds_each_beat`:
    - every beat's picture shots are at most the template's maximum;
    - the moves, dim and background match the look;
    - captions are `boxed` (A) or `kinetic` (B);
    - `document.style.template_id` is set.
  - `test_a_locked_clip_stays`: a locked clip in the evidence beat is unchanged.
  - `test_a_hidden_clip_is_not_placed_again`.
  - `test_clips_outside_beats_and_narration_stay`: the narration, SFX and an uploaded clip with no
    `source_role` are byte-identical before and after.
  - `test_style_b_card_lines_become_cards`: `card_lines={"hook": "Kok bisa ya?"}` gives a text
    clip with `style_slot == "card"` at the hook's start.
  - `test_b_after_a_gives_the_same_as_b_alone`: the picture clips and their looks are equal,
    ignoring clip ids.
- [ ] **Step 2: Run them; expect FAIL.**
- [ ] **Step 3: Implement `style_operations`.** Clip ids are `style_<beat>_<n>`, made unique against
  the document.
- [ ] **Step 4: Run them and the whole domain suite; expect PASS.**
- [ ] **Step 5: Commit:** `Compile a style into a draft's edit operations`.

### Task 5: Applying a style through the API

**Files:**
- Create: `python/src/thoth_control_plane/application/styles.py` (`StyleService`)
- Create: `python/src/thoth_control_plane/api/routes/styles.py`; register it in `api/app.py`
- Modify: `python/src/thoth_control_plane/application/narrations.py` (`start(..., restart=True)` already exists; nothing else)
- Test: `python/tests/application/test_styles.py`, `python/tests/api/test_styles_routes.py`

**Interfaces:**
- Consumes:
  - `style_operations` (Task 4);
  - the repository (Task 2);
  - `EditDocumentService.apply_patch` and `NarrationService.start`.
- Produces:
  - `GET /api/v1/projects/{project_id}/styles`, which returns `list[StyleSummary]`, each with
    `template_id`, `name` and `revision`.
  - `POST /api/v1/projects/{project_id}/edit-documents/{document_id}/style`:
    - Body `ApplyStyleRequest`: `template_id` and `base_revision`.
    - Response `AppliedStyleResult`, with:
      - `document: EditDocument`;
      - `previous_revision: int`;
      - `narration: NarrationState | None`;
      - `narration_refused: str | None`, holding one of `prompt_not_configured`,
        `narration_not_available` or `narration_unavailable`.

**Rules:**
- The narration is locked: answer 409 `narration_in_progress` and change nothing.
- An unknown template gives 404.
- A stale `base_revision` gives 409 with the latest document, as the patch route does.
- Otherwise, apply the operations as **one** patch, then start a narration: `restart=True` when
  one is completed, otherwise a first one. A refusal to start is returned in `narration_refused`,
  with the look kept.
- Log `info` for a style applied.

- [ ] **Step 1: Write the failing tests**, using memory documents, a memory narration store and a
  stub gateway:
  - `test_apply_makes_one_revision_and_starts_a_narration`: the revision goes up by exactly one,
    and the gateway saw one start.
  - `test_apply_while_narration_waits_is_refused_unchanged` (Review Focus).
  - `test_apply_without_a_model_keeps_the_look_and_says_why`: `narration_refused ==
    "prompt_not_configured"`.
  - `test_unknown_template_is_404`.
  - `test_stale_base_revision_is_409`.
  - The route test checks status codes and response shapes.
- [ ] **Step 2: Run them; expect FAIL.**
- [ ] **Step 3: Implement the service and routes, then regenerate the contracts.**
- [ ] **Step 4: Run them; expect PASS.**
- [ ] **Step 5: Commit:** `Apply a style to a draft through the API`.

### Task 6: The style script stage in Prompt Lab

**Files:**
- Modify: `python/src/thoth_control_plane/domain/prompts.py`:
  - `PromptStageId` gains `"style_script"`;
  - `PromptStageDefinition` gains `variant: str | None = None`;
  - `ProjectPromptBinding` gains `variant: str = ""`.
- Create: `python/migrations/editor/0029_style_script_stage.sql` and its alembic version:
  - add `style_script` to the six stage check constraints (pattern of 0025);
  - give `project_prompt_bindings` a `variant text NOT NULL DEFAULT ''` in its primary key.
- Modify: `python/src/thoth_control_plane/infrastructure/prompt_repository.py`,
  `application/prompt_lab.py` and `api/routes/prompt_lab.py`:
  - an optional `variant` query on the bindings and resolved routes, defaulting to `""`;
  - `/prompt-stages` lists one `style_script` entry per stored template, with
    `variant=<template_id>`, label `"<name> script"` and status `draft_only`.
- Modify: `dashboard/src/features/studio/prompt_lab_state.ts` and `PromptLab.tsx` (a stage is keyed by `stage_id` plus `variant`)
- Test: `python/tests/application/test_prompt_lab.py`, `python/tests/infrastructure/` prompt repository postgres tests, `dashboard/src/features/studio/PromptLab.test.tsx`

**Interfaces:**
- Consumes: `BUILT_IN_STYLES[...].narration.starter` (Task 1), as the fallback.
- Produces: `resolve_style_prompt(prompts_port, project_id: str, template: StyleTemplate) -> str`
  in `application/prompt_lab.py`. It returns the project's binding for `("style_script",
  template_id)`, else the template's starter.

- [ ] **Step 1: Write the failing tests.**
  - `test_style_stages_are_listed_per_template`: two entries with the variants `style_a` and
    `style_b`.
  - `test_a_style_binding_is_kept_per_variant`: saving for `style_a` leaves `style_b` on its
    starter.
  - `test_existing_bindings_still_load` (postgres): a row from before the migration reads with
    `variant == ""`.
  - The UI test: choosing "Style A script" saves a binding with `variant=style_a`.
- [ ] **Step 2: Run them; expect FAIL.**
- [ ] **Step 3: Implement, write the migration, then regenerate the contracts.**
- [ ] **Step 4: Run** the tests, `make test-postgres`, and the dashboard Prompt Lab tests; expect
  PASS.
- [ ] **Step 5: Commit:** `Keep each style's script prompt in Prompt Lab`.

### Task 7: The narration writes in the style

**Files:**
- Modify: `python/src/thoth_control_plane/domain/narration.py` (`ScriptBeat.card_line: Annotated[str, Field(max_length=80)] | None = None`, left out when None)
- Modify: `python/src/thoth_control_plane/application/narration_script.py`:
  - `build_script_request(..., card_lines: bool = False)` asks for a `card_line` per beat when
    true;
  - `parse_script` reads it when present and drops one longer than `card_line_max_words`.
- Modify: `python/src/thoth_control_plane/activities/narration.py`:
  - `write_script` uses `resolve_style_prompt` when `document.style` is set;
  - `_write` passes the template to `narrate_document`.
- Modify: `python/src/thoth_control_plane/assembly/narration_timeline.py`:
  - `narrate_document(..., style: StyleTemplate | None = None)`.
  - With a style:
    - new caption clips use `style.captions.style`;
    - after the retime, the operations from `style_operations(...)` are applied, with the real
      sentence ends (from word timings: a word ending in `.`, `?` or `!`) and the script's card
      lines.
- Test: `python/tests/application/test_narration_script.py`, `python/tests/assembly/test_narration_timeline.py`, `python/tests/activities/` narration activity test with stubbed provider

**Interfaces:**
- Consumes: `style_operations` (Task 4), `resolve_style_prompt` (Task 6).
- Produces: `sentence_ends(words: Sequence[WordTiming], start: int, fps: float) -> list[int]` in
  `assembly/narration_timeline.py`.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_style_b_script_asks_for_card_lines`: the request text contains the card-line
    instruction only when `card_lines=True`.
  - `test_an_old_script_without_card_lines_still_parses`.
  - `test_a_too_long_card_line_is_dropped`.
  - `test_a_styled_narration_cuts_on_real_sentence_ends`: two sentences in a beat give a shot
    boundary at the second sentence's first frame.
  - `test_a_styled_narration_uses_the_style_caption`: new captions are `kinetic` for B.
  - `test_write_script_uses_the_style_prompt`: the stub provider receives the style starter's
    text.
  - `test_the_style_overrides_target_length_and_sfx`: a template's `target_seconds` and
    `max_sfx_cues`, when set, replace the preset's in the request. When unset, the preset's
    values stand.
- [ ] **Step 2: Run them; expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** them, then the full `make test`; expect PASS.
- [ ] **Step 5: Commit:** `Write the narration, captions and cuts in the draft's style`.

### Task 8: The cut preview before any voice

**Files:**
- Create: `python/src/thoth_control_plane/assembly/style_preview.py`
- Modify: `python/src/thoth_control_plane/api/routes/narrations.py` (a new GET route)
- Test: `python/tests/assembly/test_style_preview.py`, `python/tests/api/` narration route test

**Interfaces:**
- Consumes: `style_operations` (Task 4), `NarrationScript`, and `NarrationPreset.words_per_second`.
- Produces:
  - `estimated_words(script: NarrationScript, preset: NarrationPreset) -> dict[BeatId, list[WordTiming]]`.
    Each word lasts `1 / words_per_second`, and a beat opens with `lead_in_seconds`.
  - `preview_document(document, template, script, preset, roles_by_item) -> EditDocumentV2`. It
    retimes the beats to the estimated lengths, then applies the style's cuts with the estimated
    sentence ends and the card lines. It adds no voice clips and is never saved.
  - `GET /api/v1/projects/{project_id}/narrations/{document_id}/preview`:
    - returns the preview document while the script is `awaiting_approval` and the draft has a
      style;
    - answers 409 `no_script` otherwise.

- [ ] **Step 1: Write the failing tests.**
  - `test_estimated_words_follow_the_preset_rate`: 9 words at 3 words per second last 3 s plus the
    lead-in.
  - `test_the_preview_is_cut_like_the_style`: no picture shot exceeds the maximum, and the shot
    boundaries sit on the estimated sentence ends.
  - `test_the_preview_is_not_saved`: the document store revision is unchanged.
  - The route answers 409 when no script waits.
- [ ] **Step 2: Run them; expect FAIL.**
- [ ] **Step 3: Implement, then regenerate the contracts.**
- [ ] **Step 4: Run them; expect PASS.**
- [ ] **Step 5: Commit:** `Preview a style's cuts from the script's estimated timing`.

### Task 9: The Style control in Studio

**Files:**
- Create: `dashboard/src/features/studio/StyleControl.tsx` and `StyleControl.test.tsx`
- Modify:
  - `dashboard/src/api/control-plane.ts`: `listStyles` and `applyStyle`;
  - `dashboard/src/features/studio/editor_state.ts`: a new action `style_applied`;
  - `dashboard/src/features/studio/GuidedStudio.tsx`: place the control in the Studio header,
    beside the mode switch;
  - the Script mode approval screen: when the draft has a style, play the preview document from
    Task 8 in its Player;
  - `dashboard/src/lib/i18n.ts`: English and Indonesian copy.
- Test: `StyleControl.test.tsx`, `editor_state.test.ts`, and the approval screen's test

**Interfaces:**
- Consumes: the two routes from Task 5, the preview route from Task 8, and `restoreEditDocument`
  (existing).
- Produces:
  - The action `style_applied`. Its fields are `document` and `previousRevision`. It adopts the
    document like `save_succeeded` and pushes `previousRevision` onto `savedUndo`, so one Undo
    restores the draft from before the style.

**Copy (English, then Indonesian):**
- Control label: "Style" / "Gaya". Its values are "None", "Style A" and "Style B".
- Confirmation title: "Apply Style A?" / "Terapkan Style A?".
- Confirmation body:
  - "This rebuilds the draft's cuts and look and replaces every edit you made by hand." /
    "Ini menyusun ulang potongan dan tampilan draft dan mengganti semua editan tangan Anda."
  - "A new script is written for your approval. The voice is made only after you approve it, with
    its cost shown first." / "Naskah baru ditulis untuk Anda setujui. Suara baru dibuat setelah
    Anda menyetujuinya, dengan biayanya ditampilkan lebih dulu."
- Buttons: "Apply style" / "Terapkan gaya", and "Cancel" / "Batal".
- When the narration cannot start: "The style is applied. The narration cannot start: {reason}." /
  "Gaya sudah diterapkan. Narasi belum bisa dimulai: {reason}."

- [ ] **Step 1: Write the failing tests.**
  - `the control lists the styles and shows the current one`.
  - `choosing a style asks first and Cancel sends nothing`.
  - `Apply sends applyStyle with the base revision and adopts the result`.
  - `one Undo after a style restores the previous revision`: `restoreEditDocument` is called with
    `previousRevision`.
  - `a narration refusal is shown in words`.
  - `the approval screen plays the cut preview for a styled draft`.
  - `the control is disabled while a narration runs`.
- [ ] **Step 2: Run them; expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the files, then `dash_full.sh full`; expect PASS. `tsc` and the build must be
  clean.
- [ ] **Step 5: Commit:** `Add the Style control and the cut preview to Studio`.

### Task 10: Browser checks and records

**Files:**
- Modify: `e2e/tests/studio-shell-v2.e2e.ts`
- Create: `e2e/tests-write/styles.e2e.ts`
- Modify: `CHANGELOG.md`, `docs/ROADMAP.md` (a status line, added only), the SDD checkpoint

- [ ] **Step 1: Add the read-only check** `1440: the Style control asks before applying`. Open the
  control, choose Style A, expect the confirmation copy, press Cancel, and expect the revision
  unchanged.
- [ ] **Step 2: Add the write checks, but do not run them.** They need the operator's word.
  - `styles: Style A rebuilds a draft and one Undo restores it`. The throwaway project has no
    script model, so `narration_refused` is expected and nothing is spent.
  - `styles: Style B gives kinetic captions and card clips`.
- [ ] **Step 3: Run the whole verification** (Global Constraints). Then run the read-only e2e against
  `vite_main.sh` at `dev1440`, and judge screenshots of the confirmation and of a styled draft at
  1440x900.
- [ ] **Step 4: Record and commit.** Write the CHANGELOG entry with a **Next steps** section, and
  update the ROADMAP's Style template track step 1 status line. Then
  `git add -f docs/superpowers/plans/2026-11-10-style-templates.md` and
  `git commit -m "Add browser checks and records for style templates"`.

**Next steps to report (each its own gate):** push and PR, deploy, the write e2e, the operator's
try with one real narrated draft (a paid voice only on their approval of a script), and merge.
After that come the style editor, then Style B's material flow, then the planner.

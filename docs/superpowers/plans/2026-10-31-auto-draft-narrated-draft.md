# Auto-draft Narrated Draft Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `produce_video` draft in Studio gains, on "Create narration", a script the operator approves (with a TTS estimate), then an ElevenLabs voice, word-highlight captions, ducking and SFX, and renders as a narrated video.

**Architecture:** A per-draft `NarrationWorkflow` (Temporal) runs transcribe → script → wait for approval → voice → write draft. Its state lives in a `narrations` row the API reads; approval is a workflow update. The draft change is one pure function (`narrate_document`) that retimes beats to their voice and adds narration, caption, ducking and SFX clips, saved as a new revision. Studio adds the button, Script mode and the preset form; the composition adds a word-highlight caption style and volume keyframes.

**Tech Stack:** Python 3.12, FastAPI, Temporal, pydantic, SQLAlchemy + Alembic (editor DB), faster-whisper, ElevenLabs adapter (`voice/`), React 19 + TypeScript + Bun, Remotion.

**Spec:** `docs/superpowers/specs/2026-10-31-auto-draft-narrated-draft-design.md`

## Global Constraints

- Every new document field is optional with a default that renders exactly what renders today; existing documents, revisions and renders are unchanged.
- No TTS call before the operator approves the script; a rejected or cancelled narration spends no TTS.
- Narration starts only from "Create narration"; never on import.
- Defaults: language `id`; target 45 s at 3 words per second; voice ElevenLabs `plgKUYgnlZ1DCNh54DwJ`, model `eleven_multilingual_v2`; duck 0.12, leak 0.45, lead-in 1.6 s; at most 3 SFX cues.
- The script uses only facts from the Content Set, the attribution verdict and the transcript; never a new name, number or quote.
- The ElevenLabs key lives only in the worker's provider file; never in a log, event, report, document or response.
- Metering per workspace: transcription seconds, LLM tokens, TTS characters (`metering.record_call(..., characters=n)`).
- Workspace isolation as every editor route: a narration is reachable only through its project.
- Ducking and captions render in the composition; no ffmpeg pre-mix.
- Repo rules: English artifacts, one-line commit subjects with no body or trailer; Python checks `make test T=...`, `make lint`; dashboard `bun --cwd=dashboard test`, `tsc -b`, build.

## Review Focus

1. A draft the operator edited after import (cards removed, beats reordered, an added Hook) — narration must follow the draft's current beats, not the import's.
2. A beat with no material left (empty after edits) or a beat the script leaves empty — no zero-length clip, no validation error; the beat keeps its length or is skipped.
3. A main video shorter than its retimed beat — the video clip is capped at its source length and the document still validates.
4. Approve or reject sent twice, or after cancel, or for an old workflow — idempotent, never a second voice spend.
5. The provider returns a script naming an unknown beat or SFX, too long for the target, or invented text the facts don't support — refused as `invalid_provider_output`, the narration fails cleanly and "Create narration" is offered again.

Each line has a test in the task named below (Task 4: 1-3; Task 8: 4; Task 6: 5).

---

### Task 1: Narration domain models and the estimate

**Files:**
- Create: `python/src/thoth_control_plane/domain/narration.py`
- Test: `python/tests/domain/test_narration.py`

**Interfaces:**
- Produces:
  - `NarrationPreset(StrictModel)`: `language: str = "id"`, `target_seconds: int = 45` (10..180), `words_per_second: float = 3.0`, `voice_provider: Literal["elevenlabs"] = "elevenlabs"`, `voice_id: str = "plgKUYgnlZ1DCNh54DwJ"`, `voice_model: str = "eleven_multilingual_v2"`, `duck_volume: float = 0.12`, `leak_volume: float = 0.45`, `lead_in_seconds: float = 1.6`, `max_sfx_cues: int = 3` (0..10).
  - `BeatId = Literal["hook", "main", "evidence", "reactions", "footage", "outro"]`, `BEAT_ORDER: tuple[BeatId, ...]`.
  - `ScriptBeat(beat: BeatId, text: str)`; `SfxCue(sfx_id: str, beat: BeatId, moment: str, word_index: int | None = None)`; `NarrationScript(beats: list[ScriptBeat], sfx_cues: list[SfxCue])` (beats unique and in `BEAT_ORDER`, at most `max_sfx_cues` checked by the writer, not here).
  - `TranscriptWord(text: str, start_seconds: float, end_seconds: float)`.
  - `NarrationStatus = Literal["transcribing", "scripting", "awaiting_approval", "voicing", "writing", "completed", "failed", "cancelled"]`.
  - `VoiceEstimate(characters: int, provider: str, voice_id: str, usd: float | None)`.
  - `SfxEntry(sfx_id: str, file_name: str, location: str, checksum: str, duration_seconds: float, labels: dict[str, object])` — `labels` holds the catalog row (category, intensity, beats, moments, description).
  - `NarrationState(document_id, status, script: NarrationScript | None, estimate: VoiceEstimate | None, stale_beats: list[BeatId], failure_code: str | None, workflow_id: str)`.
  - `estimate_voice(script: NarrationScript, preset: NarrationPreset, prices: Mapping[tuple[str, str, str], float]) -> VoiceEstimate` — characters = sum of beat text lengths; price key `("provider_call", "elevenlabs", "character")`, falling back to `("provider_call", "*", "character")` as `metering.estimate` does; `None` when unpriced.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_preset_defaults_are_the_rust_values() -> None:
    preset = NarrationPreset()
    assert (preset.target_seconds, preset.words_per_second) == (45, 3.0)
    assert (preset.voice_id, preset.voice_model) == ("plgKUYgnlZ1DCNh54DwJ", "eleven_multilingual_v2")
    assert (preset.duck_volume, preset.leak_volume, preset.lead_in_seconds) == (0.12, 0.45, 1.6)
    assert preset.max_sfx_cues == 3

def test_a_script_refuses_a_repeated_or_unordered_beat() -> None: ...  # ValidationError

def test_the_estimate_counts_characters_and_prices_them_when_a_price_exists() -> None:
    script = NarrationScript(beats=[ScriptBeat(beat="hook", text="abcd"), ScriptBeat(beat="main", text="ef")], sfx_cues=[])
    assert estimate_voice(script, NarrationPreset(), {}).usd is None
    priced = estimate_voice(script, NarrationPreset(), {("provider_call", "elevenlabs", "character"): 0.0003})
    assert (priced.characters, priced.usd) == (6, pytest.approx(0.0018))
```

- [ ] **Step 2:** `make test T=tests/domain/test_narration.py` — Expected: FAIL (module missing).
- [ ] **Step 3:** Implement the models and `estimate_voice` in `domain/narration.py`.
- [ ] **Step 4:** Same command — Expected: PASS.
- [ ] **Step 5:** `git commit -m "Add the narration domain models and voice estimate"`

### Task 2: Story beats in Python, shared with the dashboard

The dashboard computes beats from `source_role` (`dashboard/src/features/studio/story/story_beats.ts`, `ROLE_BEAT`); the narration needs the same answer server side.

**Files:**
- Create: `python/src/thoth_control_plane/domain/story_beats.py`
- Create: `dashboard/src/features/studio/story_beat_cases.json` (inside the web build context, like `story_operation_cases.json`)
- Test: `python/tests/domain/test_story_beats.py`, `dashboard/src/features/studio/story/story_beats.test.ts` (add a case-file test)

**Interfaces:**
- Produces: `ROLE_BEAT: dict[str, BeatId]` (the TS map verbatim); `beat_scenes(document: EditDocumentV2) -> dict[BeatId, list[str]]` — scene IDs per beat in canvas order, a scene's beat being the beat of its first clip with a role (Hook/Outro only from `source_role`), a scene with no role joining no beat.

- [ ] **Step 1:** Write the case file (at least: imported draft, an added Hook, a scene with no role, a reordered Evidence scene) and both tests reading it; the TS test asserts `computeBeats` scene grouping equals each case's `expected`, the Python test asserts `beat_scenes` equals it.
- [ ] **Step 2:** `make test T=tests/domain/test_story_beats.py` — Expected: FAIL (module missing); `bun --cwd=dashboard test story_beats` — Expected: PASS for existing tests, FAIL for the new case test only if TS disagrees (fix the case, not the TS).
- [ ] **Step 3:** Implement `story_beats.py`.
- [ ] **Step 4:** Both commands — Expected: PASS.
- [ ] **Step 5:** `git commit -m "Compute Story beats in Python from a case file shared with Studio"`

### Task 3: Document fields for word captions and ducking

**Files:**
- Modify: `python/src/thoth_control_plane/domain/edit_document_v2.py`
- Test: `python/tests/domain/test_edit_document_v2.py`

**Interfaces:**
- Produces:
  - `CaptionWord(from_frame: FrameStart, duration_in_frames: Frame, text: ShortText)`, relative to its cue; `CaptionCue.words: list[CaptionWord] = []` (max 40), each word inside its cue.
  - `CaptionStyle` gains `"word_highlight"`.
  - `VolumeKeyframe(frame: FrameStart, volume: Volume)`, relative to the clip; `volume_keyframes: list[VolumeKeyframe] = []` (max 500) on `TimelineVideoClip` and `TimelineAudioClip`; frames strictly increasing and inside the clip.

- [ ] **Step 1:** Tests: a v2 document from the existing fixtures validates unchanged and round-trips byte-identical JSON (`model_dump_json(exclude_defaults=False)` equal before/after); a word outside its cue, keyframes out of order or past the clip each raise `ValueError` with "caption words must stay inside their cue" / "volume keyframes must be increasing and inside the clip".
- [ ] **Step 2:** `make test T=tests/domain/test_edit_document_v2.py` — Expected: FAIL.
- [ ] **Step 3:** Add the fields and validators.
- [ ] **Step 4:** Same — Expected: PASS. Then regenerate the contract (`python/scripts/export_openapi.py` under the `scripts/dev/pytest-wsl.sh` dependency set, then `bun --cwd=dashboard run generate:control-plane-types`) and run `bun --cwd=dashboard x tsc -b` — Expected: clean.
- [ ] **Step 5:** `git commit -m "Add caption words and volume keyframes to the v2 document"`

### Task 4: `narrate_document`, the pure draft change

**Files:**
- Create: `python/src/thoth_control_plane/assembly/narration_timeline.py`
- Test: `python/tests/assembly/test_narration_timeline.py`

**Interfaces:**
- Consumes: Task 1 models, Task 2 `beat_scenes`, Task 3 fields.
- Produces:
  - `VoicedBeat(beat: BeatId, asset: AssetRef, duration_seconds: float, words: list[WordTiming])` (`WordTiming` from `voice/ports.py`).
  - `PlacedSfx(cue: SfxCue, asset: AssetRef, duration_seconds: float)`.
  - `narrate_document(document: EditDocumentV2, voiced: list[VoicedBeat], sfx: list[PlacedSfx], preset: NarrationPreset) -> EditDocumentV2` with `revision` unchanged (the store assigns the next one).

Rules (each a test):
1. Beats with a voice get a new length: `voice + lead_in` for the first voiced beat, `voice` for the rest, in frames at `canvas.fps`, rounded up. Beats without a voice keep their length. Scenes in a beat share its new length in proportion to their old lengths; every clip in a scene keeps its relative start and scales with the scene. `canvas.duration_in_frames` becomes the sum.
2. A video clip is capped at its asset's remaining frames (`asset.duration_in_frames - source_from_frame`); an image or card fills its scaled length.
3. One `narration` track (reuse the draft's, else add one) with one audio clip per voiced beat, starting at the beat's start (+ lead-in for the first), `source_role` = the beat's first role.
4. One `caption` clip per voiced beat with style `word_highlight`: cues are pages of at most 4 words or 1.2 s, each cue's `words` timed from the voice. Existing caption clips with style `source` are kept.
5. Every `main_video` clip and every non-narration audio clip under narration gets `volume_keyframes`: full until the narration starts, `duck_volume` while a word sounds, `leak_volume` in gaps longer than 0.3 s, back to full after the last word; frames relative to each clip.
6. SFX: one `sfx`-track audio clip per placed cue at the cue's word (`word_index`) or the beat start, never past the canvas.
7. Blur: video clips with imported subtitle `blur_regions` get `blur_enabled = True` in voiced beats (spec 5c-1: blur waits for narration).
8. The result validates as `EditDocumentV2`; calling it twice with the same input gives the same document (no new IDs from randomness: IDs derive from the beat, e.g. `clip_narration_main`).

- [ ] **Step 1:** Write tests for rules 1-8 and Review Focus 1-3 (an edited draft with an added Hook and a removed card; an empty beat; a main video shorter than its retimed beat), using the Story fixtures in `python/tests/fixtures` and fake `AssetRef`s.
- [ ] **Step 2:** `make test T=tests/assembly/test_narration_timeline.py` — Expected: FAIL.
- [ ] **Step 3:** Implement. Also `revoice_beat(document, voiced: VoicedBeat, preset) -> EditDocumentV2`: the same rules applied to one beat (its narration clip, captions, the ducking around it, and the beats after it shifted).
- [ ] **Step 4:** Same — Expected: PASS.
- [ ] **Step 5:** `git commit -m "Retime a draft to its narration and add voice, captions, ducking and SFX"`

### Task 5: Storage — migration 0027 and the narration store

**Files:**
- Create: `python/migrations/editor/0027_narration.sql`, `python/migrations/editor/alembic/versions/0027_narration.py` (same shape as 0025)
- Modify: `python/src/thoth_control_plane/infrastructure/editor_models.py`
- Create: `python/src/thoth_control_plane/infrastructure/narration_store.py`
- Test: `python/tests/infrastructure/test_narration_store.py` (Postgres-marked, run by `make test-postgres`)

**Interfaces:**
- SQL: the six prompt-stage CHECKs gain `'narration_script'`; tables:
  - `narrations(document_id PK, project_id, workflow_id, status, script JSONB NULL, estimate JSONB NULL, transcript JSONB NULL, stale_beats JSONB NOT NULL DEFAULT '[]', failure_code NULL, preset JSONB NOT NULL, updated_at)`;
  - `narration_presets(project_id PK, preset JSONB, revision INT)`;
  - `sfx_library(sfx_id PK, file_name, location, checksum, duration_seconds, labels JSONB, created_at)`.
- Produces `NarrationStore` (SQLAlchemy ORM, like the other editor repositories): `start(project_id, document_id, workflow_id, preset) -> NarrationState` (refuses `NarrationInProgress` unless the row is `completed|failed|cancelled`), `get(project_id, document_id) -> NarrationState | None`, `set_status(document_id, status, **fields)`, `set_script(document_id, script, estimate)`, `mark_stale(document_id, beat)`, `clear_stale(document_id, beat)`, `get_preset(project_id) -> NarrationPreset` (defaults when none), `save_preset(project_id, preset, base_revision)`, `list_sfx() -> list[SfxEntry]`, `upsert_sfx(entry)`.

- [ ] **Step 1:** Tests: start twice refuses; a project's narration is invisible to another project's `get`; preset defaults then save with revision conflict; `upsert_sfx` idempotent by checksum.
- [ ] **Step 2:** `make test-postgres` — Expected: FAIL.
- [ ] **Step 3:** Migration, models, store.
- [ ] **Step 4:** `make test-postgres` — Expected: PASS; `make test T=tests/deployment` — Expected: PASS (migration chain head 0027).
- [ ] **Step 5:** `git commit -m "Store narrations, narration presets and the SFX library (migration 0027)"`

### Task 6: The `narration_script` Prompt Lab stage and the script writer

**Files:**
- Modify: `python/src/thoth_control_plane/domain/prompts.py` (stage + starter)
- Create: `python/src/thoth_control_plane/application/narration_script.py`
- Test: `python/tests/application/test_narration_script.py`

**Interfaces:**
- `PromptStageId` gains `"narration_script"`; `PROMPT_STAGES` gains it (label "Narration script"); its starter (`id-ID`): Hook → Tension → Solution → Call-To-Value across the beats present, about `target_seconds × words_per_second` words, only facts given, figures by name.
- `ANSWER_CONTRACT` (always appended): `{"beats": [{"beat": ..., "text": ...}], "sfx_cues": [{"sfx_id": ..., "beat": ..., "moment": ..., "word_index": ...}]}`.
- Produces: `build_script_request(*, beats: list[BeatId], facts: ScriptFacts, transcript: list[TranscriptWord], preset: NarrationPreset, sfx: list[SfxEntry]) -> tuple[str, str]` (system, user) and `parse_script(answer: object, *, beats, preset, sfx_ids: set[str]) -> NarrationScript` raising `ScriptInvalid` when a beat is unknown or missing from `beats`, a cue names an unknown SFX or beat, there are more than `max_sfx_cues` cues, or the word count exceeds 1.25 × the target.
- `ScriptFacts(title, description, owner_handle, platform, verdict, figures: list[str], comments: list[str])`, built from the run's Content Set and attribution report (the materials endpoint's join, `application/studio_imports` materials).

- [ ] **Step 1:** Tests for each `ScriptInvalid` case (Review Focus 5) and that the user prompt carries the facts, the transcript text and the SFX labels, and no URL.
- [ ] **Step 2:** `make test T=tests/application/test_narration_script.py` — Expected: FAIL.
- [ ] **Step 3:** Implement; prompt resolution reuses Story Assist's `_system` pattern (saved prompt, else starter, contract always).
- [ ] **Step 4:** Same — Expected: PASS; `make test T=tests/domain/test_prompts.py` — Expected: PASS.
- [ ] **Step 5:** `git commit -m "Add the narration_script prompt stage and its script writer"`

### Task 7: Narration activities

**Files:**
- Modify: `python/src/thoth_control_plane/attribution/adapters/speech.py` (word timestamps, whole length)
- Create: `python/src/thoth_control_plane/activities/narration.py`
- Test: `python/tests/activities/test_narration.py`

**Interfaces:**
- `LocalSpeech.transcribe_words(video: Path) -> list[TranscriptWord]` (`word_timestamps=True`, VAD on, the same process pool and model as attribution).
- `NarrationActivities` with `@activity.defn` methods, each taking `NarrationStepInput(project_id, document_id)` and returning a small result; each meters under `metering.project_scope(project_id)`:
  - `narration_transcribe` → stores the transcript (records `("transcription", "faster_whisper", seconds, "second")`); a draft with no main video stores an empty transcript.
  - `narration_write_script` (prompt queue; credentials there) → `NarrationScript` + estimate stored, status `awaiting_approval`; `ScriptInvalid` → status `failed`, code `invalid_provider_output`.
  - `narration_voice` → one `build_voice(settings, "elevenlabs").synthesize(...)` per beat; each audio registered through `EditorAssetUploadService.upload(project_id, media_type, chunks)`; `metering.record_call("elevenlabs", characters=len(text))`; returns `list[VoicedBeatRef]` (beat, asset_id, duration, words); `narration_write_draft` turns each into Task 4's `VoicedBeat` with the asset's `AssetRef`. `VoiceNotConfigured` → `failed`, `voice_not_configured`.
  - `narration_write_draft` → loads the latest revision, copies each cued SFX into the project (Task 10's `ensure_project_sfx`), runs `narrate_document`, saves revision n+1 through `EditDocumentService.write_derived_revision(project_id, document_id, base_revision, document)` (new: inserts via the repository with the revision check), status `completed`.
  - `narration_revoice(beat)` → voice for one beat + `revoice_beat` + save; clears the beat's stale flag.
- [ ] **Step 1:** Tests with fakes (speech, provider, voice, upload service, store): metering lines recorded; no voice call happens in transcribe or script; a missing key fails with `voice_not_configured` and leaves the draft unchanged; the key never appears in a failure or log (capture logs, assert the fake key string absent).
- [ ] **Step 2:** `make test T=tests/activities/test_narration.py` — Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Same — Expected: PASS.
- [ ] **Step 5:** `git commit -m "Add the narration activities: transcribe, script, voice, write"`

### Task 8: `NarrationWorkflow`, re-voice, and the worker

**Files:**
- Create: `python/src/thoth_control_plane/workflows/narration.py`
- Modify: `python/src/thoth_control_plane/worker.py`
- Test: `python/tests/workflows/test_narration_workflow.py` (Temporal test environment, as the existing workflow tests)

**Interfaces:**
- `NarrationWorkflow.run(NarrationWorkflowInput(project_id, document_id))`, id `narration/{document_id}/{n}`: transcribe → script → wait → voice → write. Update `decide(NarrationDecision(decision: Literal["approve","reject"], note: str | None))` accepted only while `awaiting_approval`; a reject re-runs the script step with the note appended to the user prompt. Cancel at any point sets `cancelled`, spends nothing further.
- `NarrationRevoiceWorkflow.run(NarrationRevoiceInput(project_id, document_id, beat))`, id `narration-revoice/{document_id}/{beat}/{n}`.
- Worker: both workflows and the transcribe/voice/write activities on `TASK_QUEUE`; `narration_write_script` on `PROMPT_PROPOSAL_TASK_QUEUE`.
- [ ] **Step 1:** Tests: the happy path ends `completed` with one voice call per beat; reject then approve makes two script calls and one voice pass; approve twice or after cancel is rejected by the update validator and makes no second voice pass (Review Focus 4); a voice failure retries per the activity policy and ends `failed` without touching the draft.
- [ ] **Step 2:** `make test T=tests/workflows/test_narration_workflow.py` — Expected: FAIL.
- [ ] **Step 3:** Implement and register. Update `tests/test_worker.py`'s queue/workflow expectations.
- [ ] **Step 4:** Same plus `make test T=tests/test_worker.py` — Expected: PASS.
- [ ] **Step 5:** `git commit -m "Run narration as its own workflow with a script approval gate"`

### Task 9: Narration API and the editing lock

**Files:**
- Create: `python/src/thoth_control_plane/api/routes/narrations.py`, `python/src/thoth_control_plane/application/narrations.py`, `python/src/thoth_control_plane/infrastructure/narration_gateway.py`
- Modify: `python/src/thoth_control_plane/api/routes/edit_documents.py` (lock), app wiring
- Test: `python/tests/api/test_narrations.py`

**Interfaces (all under `/api/v1/projects/{project_id}/edit-documents/{document_id}`, owner/admin/editor as the edit routes):**
- `POST /narration` → 202 `NarrationState`; 409 `narration_in_progress`; 409 `narration_not_available` when the draft has no run (`source_workflow_id` empty); 503 `voice_not_configured` / `prompt_not_configured` (checked before start, so nothing is spent).
- `GET /narration` → `NarrationState` or 404.
- `POST /narration/decision` `{decision, note}` → 202; 409 when not awaiting approval.
- `PUT /narration/beats/{beat}` `{text}` → only when `completed`; updates the script beat and marks it stale.
- `POST /narration/beats/{beat}/revoice` → 202; 409 unless the beat is stale.
- `GET /api/v1/projects/{project_id}/narration-preset`, `PUT` with `base_revision`.
- `GET /api/v1/sfx` → the library (id, file name, duration, labels).
- `PATCH /edit-documents/{d}` answers 409 `narration_in_progress` while the narration is `transcribing|scripting|awaiting_approval|voicing|writing`.
- [ ] **Step 1:** Tests: each status code above; another project's document is 404; the estimate appears in `GET` while awaiting approval; the lock refuses a patch and lifts at `completed`.
- [ ] **Step 2:** `make test T=tests/api/test_narrations.py` — Expected: FAIL.
- [ ] **Step 3:** Implement; regenerate `python/openapi.json` and the dashboard types.
- [ ] **Step 4:** Same plus `make test T=tests/api` — Expected: PASS; `bun --cwd=dashboard x tsc -b` clean.
- [ ] **Step 5:** `git commit -m "Expose narration, its decision, re-voice and the preset over the API"`

### Task 10: The SFX library in MinIO

**Files:**
- Create: `python/src/thoth_control_plane/application/sfx_library.py`
- Modify: `python/src/thoth_control_plane/cli.py` (`thoth-control sfx seed`)
- Test: `python/tests/application/test_sfx_library.py`

**Interfaces:**
- `seed_sfx(store: NarrationStore, media: MediaStore, catalog: Path, directory: Path) -> SeedReport(added, unchanged)` — every `assets/sfx` file in `assets/asset_catalog.json` goes to `sfx/{checksum}{suffix}` with its catalog labels; idempotent by checksum.
- `ensure_project_sfx(project_id, sfx_id) -> AssetRef` — the project's editor asset for one library SFX, copied on first use and reused by checksum after (the importer's reuse-by-checksum).
- The image gains `assets/sfx` and `assets/asset_catalog.json` at `/opt/thoth/assets` (Dockerfile `COPY`; `.dockerignore` keeps `assets` excluded except these).
- [ ] **Step 1:** Tests: seeding twice reports `added=21` then `unchanged=21` on the real catalog; `ensure_project_sfx` copies once per project and is invisible to another project.
- [ ] **Step 2:** `make test T=tests/application/test_sfx_library.py` — Expected: FAIL.
- [ ] **Step 3:** Implement; update `tests/deployment/test_container_contract.py` for the new `COPY`.
- [ ] **Step 4:** Same plus `make test T=tests/deployment` — Expected: PASS.
- [ ] **Step 5:** `git commit -m "Seed the SFX library into object storage"`

### Task 11: Composition — word highlight and volume keyframes

**Files:**
- Modify: `packages/remotion-composition/src/AdvancedTimelineComposition.tsx`, its types
- Create: `packages/remotion-composition/releases/narration-v1/` (candidate only)
- Test: `packages/remotion-composition/src/*.test.ts(x)`, `renderer/src/template-release.test.ts`

**Interfaces:**
- `CAPTION_STYLES.word_highlight`: the cue's words in one line, the word under the current frame drawn in the highlight colour (`#d49a79`, as Story emphasis), the others white; a cue with no `words` draws its `text` as `caption_default` does.
- `volumeAt(frame, keyframes, fallback)`: linear between keyframes, the first value before the first, the last after; `Video` gets `volume={(f) => muted ? 0 : volumeAt(f, clip.volume_keyframes, 1)}` only when keyframes exist (no prop otherwise, so existing renders stay byte-identical); `Audio` multiplies its fade by `volumeAt(f, keyframes, clip.volume)` when keyframes exist.
- [ ] **Step 1:** Tests: both existing parity capsules still verify `pass`; `volumeAt` interpolation cases; a `word_highlight` cue highlights the word whose window holds the frame.
- [ ] **Step 2:** `bun --cwd=packages/remotion-composition test` — Expected: FAIL for the new tests.
- [ ] **Step 3:** Implement. Draw the `narration-v1` candidate (a document with narration, word cues, keyframes and an SFX) the way `story_mode-v1` was drawn, and stop: its golden set is an **operator gate**.
- [ ] **Step 4:** Same plus `bun --cwd=renderer test` — Expected: PASS.
- [ ] **Step 5:** `git commit -m "Draw word-highlight captions and keyframed volume in the composition"`

### Task 12: Studio — Create narration, Script mode, preset, SFX

**Files:**
- Create: `dashboard/src/features/studio/script/ScriptMode.tsx`, `NarrationButton.tsx`, `NarrationPresetForm.tsx`, their tests
- Modify: `GuidedStudio.tsx` (mode switch Story · Script · Timeline; lock), `PresetsPage.tsx` (preset form), `AssetLibrary.tsx` (Sound effects section), the API client, `dashboard/src/lib/locale` en + id strings

**Behaviour:**
- **Create narration** in the top bar on a draft with a source run and no running narration; disabled with the API's reason (`voice_not_configured`, `prompt_not_configured`).
- While running, the draft is read-only with the §13.3 steps (Transcribe · Write script · Awaiting approval · Voice beat n of m · Write draft); the GET is polled every 3 s until it settles.
- **Script mode, awaiting approval:** beats as read-only paragraphs beside the 9:16 preview, the SFX cues per beat, the estimate (characters, provider, voice, price or "Unpriced"), Approve, Reject with an optional note.
- **Script mode, completed:** editable paragraphs; a changed beat shows "Voice out of date" and Re-voice; the header counts stale beats.
- **Presets & prompts:** the narration preset form (Task 1 fields) with revision-conflict handling; the `narration_script` stage appears in Prompt Lab by itself (registered stage).
- **Asset library:** a Sound effects section listing the library with labels; "Add" copies it into the draft's project.
- [ ] **Step 1:** Tests: button states; the lock shows steps and blocks edits; approve/reject call the decision route once; a stale beat shows Re-voice; the preset form saves with `base_revision`; both locales have every new key.
- [ ] **Step 2:** `bun --cwd=dashboard test` — Expected: FAIL for the new tests.
- [ ] **Step 3:** Implement following `docs/DESIGN.md` §13.1 and §13.3 tokens and components.
- [ ] **Step 4:** `bun --cwd=dashboard test`, `bun --cwd=dashboard x tsc -b`, `bun --cwd=dashboard run build` — Expected: PASS, clean, built.
- [ ] **Step 5:** `git commit -m "Add Create narration, Script mode and the narration preset to Studio"`

### Task 13: Records and deploy notes

**Files:**
- Modify: `docs/python-control-plane.md` (Narration section), `docs/operations/stage1-local-docker.md` (provider file gains `THOTH_ELEVENLABS_API_KEY`; run `thoth-control sfx seed` once after the deploy), `docs/ROADMAP.md` (item 6 status, additions only), `CHANGELOG.md`, the SDD checkpoint
- [ ] **Step 1:** Write the entries; CHANGELOG ends with **Next steps**: operator gates (approve `narration-v1` golden; push/PR; merge; deploy with migration 0027; move the ElevenLabs key into the provider file; run `sfx seed`; a live narrated run as the acceptance).
- [ ] **Step 2:** `make test`, `make lint`, dashboard test/tsc/build — Expected: all green.
- [ ] **Step 3:** `git commit -m "Record the narrated-draft milestone"`

# Stressed Narration Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Eleven v4 (`eleven_v4`) with style-calibrated inline audio tags the default stressed narration delivery for every style while keeping captions, b-roll planner phrases, SFX indices, cut previews, and Studio approval clean.

**Architecture:** Inline `[tag]` audio directions live in `ScriptBeat.text` (single source of truth). Style templates carry per-style `DeliveryRules` (`stability`, allowed tags, per-beat cap, guidance). Downstream text validators, cut previews, and ElevenLabs' `words_from_alignment` strip `[...]` tags so `VoiceRef.words` stays 100% spoken words; non-`eleven_v4*` models strip tags before synthesis and keep `speed`. Editor migration `0036` upgrades existing default `eleven_multilingual_v2` project presets to `eleven_v4` while leaving historical `narrations.preset` snapshots untouched.

**Tech Stack:** Python 3.12 (Pydantic v2, httpx, Alembic/PostgreSQL, pytest, Ruff), React 19 + TypeScript (Bun test, `tsc -b`, Vite), OpenAPI codegen.

**Spec:** `docs/superpowers/specs/2026-11-24-stressed-narration-delivery-design.md`

## Global Constraints

- Every new Pydantic field (`VoiceRequest.stability`, `NarrationRules.delivery`) must have a default so stored data and older clients still decode.
- `supports_audio_tags(model_id)` is scoped to `model_id.startswith("eleven_v4")` only (not `eleven_v3`, which lacks `previous_request_ids` request stitching).
- Never send `voice_settings.speed` when `supports_audio_tags(model_id)` is `True`; send `language_code` and optional `stability` only.
- On non-`eleven_v4*` models, omit delivery tag prompting in script generation, count tag-stripped characters in `estimate_voice`, and strip tags in the adapter before calling ElevenLabs.
- Existing historical `narrations.preset` snapshots are untouched by migration `0036`; only `narration_presets` rows matching `eleven_multilingual_v2` migrate to `eleven_v4`.
- All repository artifacts (code, comments, tests, commit messages, docs) in English; Conventional Commits single-line subjects (`<= 72` chars, no body/trailer/Co-Authored-By).
- Never print secrets (`.env*`, API keys, tokens). Run Python tests and lint from WSL (`make test`, `make test-postgres`, `make lint`).

## Review Focus

1. **Multi-word and adjacent tags in character alignment:** `[clears throat]` (contains a space) or `[curious]Halo` (no space after `]`) must be stripped cleanly in `words_from_alignment` without splitting/leaking tokens or corrupting spoken-word start/end timestamps (pinned in Task 2).
2. **Leading audio tag before a capitalized word in `unsupported_tokens`:** `"[curious] Mutant nggak suka"` must keep `sentence_start=True` for `"Mutant"` so sentence-initial words after a tag are not falsely flagged as mid-sentence unsupported tokens (pinned in Task 4).
3. **Tag-only beat or empty text after v2 tag stripping:** A beat whose text is only `"[curious] [excited]"` must be dropped by `parse_script`, and if manually saved via Studio and voiced on `eleven_multilingual_v2`, `ElevenLabsVoice.synthesize` must raise `VoiceRejected("empty_text_after_tag_strip")` instead of sending empty text to ElevenLabs (pinned in Tasks 2 & 4).
4. **Unclosed bracket in manually edited beat:** A user typo like `"[curious Mutant nggak suka"` must not swallow the rest of the sentence in `words_from_alignment` or `strip_audio_tags` (pinned in Tasks 1 & 2).
5. **Pre-approval cut preview leaking tags:** `assembly/style_preview.py`'s `estimated_words` must strip `[...]` tags before splitting so preview captions and beat durations match spoken words only (pinned in Task 4).

---

### Task 1: Shared audio-tag utilities and `VoiceRequest.stability`

**Files:**
- Create: `python/src/thoth_control_plane/voice/audio_tags.py`
- Modify: `python/src/thoth_control_plane/voice/ports.py:12-26`
- Test: `python/tests/voice/test_audio_tags.py`

**Interfaces:**
- Consumes: none.
- Produces:
  - `AUDIO_TAG_RE: re.Pattern[str]` matching `r"\[[A-Za-z][A-Za-z ]{0,39}\]"`
  - `supports_audio_tags(model_id: str | None) -> bool` (`True` iff `bool(model_id) and model_id.startswith("eleven_v4")`)
  - `strip_audio_tags(text: str) -> str`
  - `sanitize_script_tags(text: str, allowed: frozenset[str], *, max_tags: int | None = None) -> str`
  - `VoiceRequest.stability: Annotated[float, Field(ge=0.0, le=1.0)] | None = None`

- [ ] **Step 1: Write the failing unit tests**

Create `python/tests/voice/test_audio_tags.py` asserting:
- `test_supports_audio_tags_matches_only_eleven_v4_family`: `True` for `"eleven_v4"`, `"eleven_v4_turbo"`; `False` for `"eleven_multilingual_v2"`, `"eleven_v3"`, `""`, `None`.
- `test_strip_audio_tags_removes_single_multiword_and_adjacent_tags`:
  - `strip_audio_tags("[curious] Halo, [amused] dunia!") == "Halo, dunia!"`
  - `strip_audio_tags("[clears throat] Mulai sekarang.") == "Mulai sekarang."`
  - `strip_audio_tags("[curious]Halo [sighs]") == "Halo"`
  - `strip_audio_tags("suka, [amused] tapi") == "suka, tapi"`
  - `strip_audio_tags("Tahun [2026] tetap ada.") == "Tahun [2026] tetap ada."` (non-letter bracket preserved by `strip_audio_tags`)
  - `strip_audio_tags("[curious tanpa tutup") == "[curious tanpa tutup"` (unclosed bracket preserved)
- `test_sanitize_script_tags_keeps_allowed_normalizes_and_caps`:
  - `sanitize_script_tags("[CURIOUS] Halo [tertawa] [amused] dunia [excited]!", frozenset({"curious", "amused", "excited"}), max_tags=2) == "[curious] Halo [amused] dunia!"`
  - `sanitize_script_tags("[curious] Halo [jeda 2 detik] dunia.", frozenset({"curious"})) == "[curious] Halo dunia."`
  - `sanitize_script_tags("[curious] Halo.", frozenset()) == "Halo."`
- `test_voice_request_stability_defaults_none_and_bounds`:
  - `VoiceRequest(text="Halo", voice_id="v").stability is None`
  - `VoiceRequest(text="Halo", voice_id="v", stability=0.45).stability == 0.45`
  - `VoiceRequest(text="Halo", voice_id="v", stability=1.5)` raises `ValidationError`.

- [ ] **Step 2: Run tests to verify failure**

Run (from WSL): `make test T=tests/voice/test_audio_tags.py`
Expected: FAIL (`ModuleNotFoundError: No module named 'thoth_control_plane.voice.audio_tags'`).

- [ ] **Step 3: Implement `audio_tags.py` and `VoiceRequest.stability`**

- Create `python/src/thoth_control_plane/voice/audio_tags.py` with `AUDIO_TAG_RE`, `supports_audio_tags`, `strip_audio_tags`, and `sanitize_script_tags`.
  - Keep whitespace cleanup clean so removing a tag between a word and punctuation (`"dunia [excited]!"` -> `"dunia!"`) does not leave a stray space before `[.,!?;:]`, while removing an adjacent tag (`"[curious]Halo"` -> `"Halo"` or `"suka, [amused] tapi"` -> `"suka, tapi"`) preserves normal word spacing.
  - `sanitize_script_tags` scans all `r"\[([^\[\]]+)\]"` matches: normalizes inner text with `" ".join(inner.lower().split())`, keeps `[normalized]` if in `allowed` and kept count `< max_tags` (when `max_tags is not None`), else removes the span; then normalizes whitespace/punctuation spacing.
- Add `stability: Annotated[float, Field(ge=0.0, le=1.0)] | None = None` to `VoiceRequest` in `python/src/thoth_control_plane/voice/ports.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test T=tests/voice/test_audio_tags.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/voice/audio_tags.py python/src/thoth_control_plane/voice/ports.py python/tests/voice/test_audio_tags.py
git commit -m "feat(voice): add audio tag helpers and VoiceRequest stability"
```

---

### Task 2: ElevenLabs v4 adapter and tag-free alignment

**Files:**
- Modify: `python/src/thoth_control_plane/voice/adapters/elevenlabs.py:21-114`
- Modify: `python/tests/voice/test_elevenlabs.py`
- Modify: `python/tests/test_metering_seams.py:70-80`

**Interfaces:**
- Consumes: `supports_audio_tags`, `strip_audio_tags`, `AUDIO_TAG_RE` from `thoth_control_plane.voice.audio_tags`; `VoiceRequest.stability` from `thoth_control_plane.voice.ports`.
- Produces:
  - `DEFAULT_MODEL = "eleven_v4"` in `thoth_control_plane.voice.adapters.elevenlabs`
  - `words_from_alignment(alignment: dict[str, Any]) -> list[WordTiming]` (guaranteed tag-free)
  - `ElevenLabsVoice.synthesize(request: VoiceRequest) -> SynthesizedVoice` (v4 sends `language_code` + optional `stability`, omits `speed`, preserves tags in `text`, strips tags in `previous_text`/`next_text`; non-v4 strips tags in `text`/`previous_text`/`next_text`, sends `speed` + optional `stability`, raises `VoiceRejected("empty_text_after_tag_strip")` if stripped `text` is empty).

- [ ] **Step 1: Write the failing adapter and alignment tests**

In `python/tests/voice/test_elevenlabs.py`:
- Update `test_synthesize_posts_with_timestamps_and_decodes_audio` to verify the new default `eleven_v4` request:
  - `seen["body"]["model_id"] == "eleven_v4"`
  - `seen["body"]["language_code"] == "id"`
  - `"voice_settings" not in seen["body"]` when `stability is None` (no `speed` sent!)
- Update `test_request_ids_stitch_and_the_billed_cost_comes_from_the_header` assertion from `"elevenlabs/eleven_multilingual_v2"` to `"elevenlabs/eleven_v4"`.
- Update `python/tests/test_metering_seams.py` lines 74–75 from `"elevenlabs/eleven_multilingual_v2"` to `"elevenlabs/eleven_v4"`.
- Add new tests in `python/tests/voice/test_elevenlabs.py`:
  - `test_v4_sends_stability_keeps_tags_and_strips_neighbor_tags`: `VoiceRequest(text="[curious] Halo!", voice_id="v", model="eleven_v4", stability=0.45, previous_text="[amused] Awal.", next_text="[excited] Akhir.")` sends `text="[curious] Halo!"`, `language_code="id"`, `voice_settings={"stability": 0.45}` (no `speed`), `previous_text="Awal."`, `next_text="Akhir."`.
  - `test_v2_strips_tags_and_sends_speed`: `VoiceRequest(text="[curious] Halo, [amused] dunia!", voice_id="v", model="eleven_multilingual_v2", speed=1.1, stability=0.35, previous_text="[excited] Awal.")` sends `text="Halo, dunia!"`, `previous_text="Awal."`, `voice_settings={"speed": 1.1, "stability": 0.35}`, and `"language_code" not in body`.
  - `test_v2_rejects_text_empty_after_stripping_tags`: `VoiceRequest(text="[curious] [excited]", voice_id="v", model="eleven_multilingual_v2")` raises `VoiceRejected("empty_text_after_tag_strip")` without calling HTTP.
  - `test_alignment_strips_audio_tags_including_multiword_adjacent_trailing_and_preserves_unclosed`:
    - `"[curious] Halo, [clears throat] [amused]dunia! [sighs]"` -> `[("Halo,", ...), ("dunia!", ...)]` with exact character timestamps preserved;
    - `"[curious tanpa tutup"` -> `[("[curious", ...), ("tanpa", ...), ("tutup", ...)]` (unclosed bracket does not swallow text);
    - spike-shaped alignment with `[curious]`, `[amused]`, `[excited]` interspersed in `"Kelihatannya sih Mutant nggak suka, tapi ternyata ada maunya!"` yields exact clean spoken words with zero bracket tokens.

- [ ] **Step 2: Run tests to verify failure**

Run: `make test T="tests/voice/test_elevenlabs.py tests/test_metering_seams.py"`
Expected: FAIL.

- [ ] **Step 3: Implement changes in `elevenlabs.py`**

- Change `DEFAULT_MODEL = "eleven_v4"`.
- Update `words_from_alignment(alignment)`: walk index `i` over `characters`/`starts`/`ends`. When `characters[i] == "["`, scan ahead for the first `"]"` before any `"["`; if found and `"".join(characters[i : close + 1])` matches `AUDIO_TAG_RE.fullmatch(...)`, flush any in-progress word and jump `i = close + 1`. Otherwise process `characters[i]` as today.
- Update `ElevenLabsVoice.synthesize(request)`:
  - `model_id = request.model or DEFAULT_MODEL`
  - `tag_capable = supports_audio_tags(model_id)`
  - If `tag_capable`:
    - `body: dict[str, Any] = {"text": request.text, "model_id": model_id, "language_code": request.language}`
    - If `request.stability is not None`: `body["voice_settings"] = {"stability": request.stability}`
  - Else:
    - `text = strip_audio_tags(request.text)`
    - If not `text`: `raise VoiceRejected("empty_text_after_tag_strip")`
    - `settings: dict[str, Any] = {"speed": request.speed}`
    - If `request.stability is not None`: `settings["stability"] = request.stability`
    - `body = {"text": text, "model_id": model_id, "voice_settings": settings}`
  - For `previous_text` / `next_text`: strip tags via `strip_audio_tags(...)` and include only if non-empty.

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test T="tests/voice/test_elevenlabs.py tests/test_metering_seams.py"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/voice/adapters/elevenlabs.py python/tests/voice/test_elevenlabs.py python/tests/test_metering_seams.py
git commit -m "feat(voice): default ElevenLabs adapter to eleven_v4 and strip tags from alignment"
```

---

### Task 3: Per-style delivery profiles and `NarrationPreset` default

**Files:**
- Modify: `python/src/thoth_control_plane/domain/style_templates.py:61-159`
- Modify: `python/src/thoth_control_plane/domain/narration.py:40-54,130-149`
- Modify: `python/tests/domain/test_style_templates.py`
- Modify: `python/tests/domain/test_narration.py`

**Interfaces:**
- Consumes: `supports_audio_tags`, `strip_audio_tags` from `thoth_control_plane.voice.audio_tags`.
- Produces:
  - `DeliveryRules(StrictModel)` in `thoth_control_plane.domain.style_templates` with fields `stability: float`, `tags: tuple[str, ...]`, `max_tags_per_beat: int`, `guide: str`
  - `DEFAULT_DELIVERY: DeliveryRules` in `thoth_control_plane.domain.style_templates`
  - `NarrationRules.delivery: DeliveryRules = Field(default_factory=lambda: DEFAULT_DELIVERY)`
  - `NarrationPreset.voice_model` default `"eleven_v4"`
  - `estimate_voice(script, preset, prices)` counting `len(beat.text)` on `eleven_v4*` and `len(strip_audio_tags(beat.text))` on non-tag models.

- [ ] **Step 1: Write the failing domain tests**

- In `python/tests/domain/test_style_templates.py`:
  - `test_built_in_styles_define_distinct_delivery_profiles`:
    - `style_a.narration.delivery.stability == 0.45`, `max_tags_per_beat == 3`, `tags == ("curious", "amused", "excited", "surprised", "emphatically", "whispers")`
    - `style_b.narration.delivery.stability == 0.50`, `max_tags_per_beat == 2`, `tags == ("seriously", "intrigued", "emphatically", "thoughtful")`
    - `"amused" not in style_b.narration.delivery.tags`
  - `test_narration_rules_decodes_without_delivery_field`: `NarrationRules(starter="x").delivery == DEFAULT_DELIVERY`.
- In `python/tests/domain/test_narration.py`:
  - Update existing default assertions (lines 23, 60) from `"eleven_multilingual_v2"` to `"eleven_v4"`.
  - Add `test_estimate_voice_counts_tags_on_v4_and_strips_on_v2`:
    - script beat `"[curious] Halo dunia!"` (21 chars raw, 11 chars stripped):
    - with `NarrationPreset(voice_model="eleven_v4")` -> `estimate.characters == 21`;
    - with `NarrationPreset(voice_model="eleven_multilingual_v2")` -> `estimate.characters == 11`.

- [ ] **Step 2: Run tests to verify failure**

Run: `make test T="tests/domain/test_style_templates.py tests/domain/test_narration.py"`
Expected: FAIL.

- [ ] **Step 3: Implement `DeliveryRules`, built-in profiles, and `NarrationPreset` default**

- In `python/src/thoth_control_plane/domain/style_templates.py`:
  - Define `DeliveryRules(StrictModel)` and `DEFAULT_DELIVERY` matching spec §5.2 verbatim (`stability=0.48`, `tags=("curious", "emphatically", "intrigued", "seriously")`, `max_tags_per_beat=3`).
  - Add `delivery: DeliveryRules = Field(default_factory=lambda: DEFAULT_DELIVERY)` to `NarrationRules`.
  - Configure `style_a` (`stability=0.45`, 6 tags, `max_tags_per_beat=3`, Style A guide) and `style_b` (`stability=0.50`, 4 tags, `max_tags_per_beat=2`, Style B guide). Keep `_STARTER_A`, `_STARTER_B`, and `revision` values unchanged.
- In `python/src/thoth_control_plane/domain/narration.py`:
  - Change `NarrationPreset.voice_model` default to `"eleven_v4"`.
  - Update `estimate_voice` to sum `len(beat.text)` if `supports_audio_tags(preset.voice_model)` else `len(strip_audio_tags(beat.text))`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test T="tests/domain/test_style_templates.py tests/domain/test_narration.py"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/domain/style_templates.py python/src/thoth_control_plane/domain/narration.py python/tests/domain/test_style_templates.py python/tests/domain/test_narration.py
git commit -m "feat(narration): add style delivery profiles and default preset to eleven_v4"
```

---

### Task 4: Script contract, validation, cut preview, and narration activities

**Files:**
- Modify: `python/src/thoth_control_plane/application/narration_script.py:111-322`
- Modify: `python/src/thoth_control_plane/assembly/style_preview.py:23-36`
- Modify: `python/src/thoth_control_plane/activities/narration.py:240-398,516-544`
- Modify: `python/tests/application/test_narration_script.py`
- Modify: `python/tests/assembly/test_style_preview.py`
- Modify: `python/tests/activities/test_narration_activities.py`

**Interfaces:**
- Consumes: `DeliveryRules`, `DEFAULT_DELIVERY` from `thoth_control_plane.domain.style_templates`; `supports_audio_tags`, `strip_audio_tags`, `sanitize_script_tags` from `thoth_control_plane.voice.audio_tags`; `VoiceRequest.stability` from `thoth_control_plane.voice.ports`.
- Produces:
  - `build_script_request(..., delivery: DeliveryRules | None = None) -> tuple[str, str]`
  - `parse_script(..., allowed_tags: frozenset[str] | None = None, max_tags_per_beat: int | None = None) -> NarrationScript`
  - `unsupported_tokens(script, facts, transcript)` ignoring audio tags and preserving `sentence_start`
  - `estimated_words(script, preset)` in `assembly/style_preview.py` producing tag-free `WordTiming`
  - `NarrationActivities.write_script`, `voice`, `revoice` wiring `delivery` and `stability` from draft style (defaulting to `DEFAULT_DELIVERY`).

- [ ] **Step 1: Write the failing tests**

- In `python/tests/application/test_narration_script.py`:
  - `test_build_script_request_includes_delivery_rules_for_v4_and_omits_for_v2`:
    - On `NarrationPreset(voice_model="eleven_v4")` with Style A delivery, `system` contains `[curious]`, `[amused]`, `max_tags_per_beat`, Style A guide, and spoken-words-only `word_index` rule;
    - With `delivery=None` on `eleven_v4`, uses `DEFAULT_DELIVERY` tags;
    - On `NarrationPreset(voice_model="eleven_multilingual_v2")`, `system` omits `[curious]` / delivery tag rules.
  - `test_parse_script_sanitizes_tags_caps_per_beat_drops_tag_only_beat_and_strips_headline_card`:
    - Disallowed Indonesian tag `[tertawa]` is removed;
    - Tags beyond `max_tags_per_beat=2` are dropped (first 2 kept);
    - A beat containing only `"[curious] [excited]"` is dropped (and raises `ScriptInvalid` if all beats are tag-only);
    - `[curious]` in `headline` or `card_line` is stripped;
    - On `NarrationPreset(voice_model="eleven_multilingual_v2")`, all tags are stripped;
    - Length check (`LENGTH_SLACK`) counts spoken words only (tags do not push a valid beat over the limit).
  - `test_unsupported_tokens_ignores_tags_and_preserves_sentence_start`:
    - `"[curious] Mutant nggak suka. [amused] Tiba-tiba Densu datang."` where facts contain `Densu` but not `Mutant` or `Tiba-tiba`: neither `curious`, `amused`, `Mutant`, nor `Tiba-tiba` is flagged (both `Mutant` and `Tiba-tiba` start sentences right after tags!), while a mid-sentence unknown capitalized name `"Budi"` IS still flagged.
- In `python/tests/assembly/test_style_preview.py`:
  - `test_estimated_words_strips_audio_tags`: `"[curious] Kelihatannya sih [amused] Mutant suka."` yields 4 spoken `WordTiming` items (`Kelihatannya`, `sih`, `Mutant`, `suka.` — no `[curious]` or `[amused]`) with duration based on 4 words.
- In `python/tests/activities/test_narration_activities.py`:
  - `test_write_script_passes_style_delivery_and_counts_spoken_words_for_min_length`: verifies Style A prompt receives Style A tags, Style B receives Style B tags without `[amused]`, and tags do not inflate the `MIN_LENGTH_SHARE` word count.
  - `test_voice_and_revoice_pass_style_stability`: Style A draft passes `stability=0.45` in `VoiceRequest` during both `voice()` and `revoice()`; Style B passes `0.50`; unstyled passes `0.48`.

- [ ] **Step 2: Run tests to verify failure**

Run: `make test T="tests/application/test_narration_script.py tests/assembly/test_style_preview.py tests/activities/test_narration_activities.py"`
Expected: FAIL.

- [ ] **Step 3: Implement script, preview, and activity changes**

- In `python/src/thoth_control_plane/application/narration_script.py`:
  - Add helper `_delivery_rules(delivery: DeliveryRules) -> str` formatting allowed tags (`[tag1], [tag2], ...`), `max_tags_per_beat`, `delivery.guide`, no invented/Indonesian tags, no tags in `headline`/`card_line`, and `sfx_cues.word_index` counting spoken words only.
  - Update `build_script_request`: accept `delivery: DeliveryRules | None = None`; when `supports_audio_tags(preset.voice_model)`, append `_delivery_rules(delivery or DEFAULT_DELIVERY)` into `system`.
  - Update `parse_script`: accept `allowed_tags: frozenset[str] | None = None` and `max_tags_per_beat: int | None = None`; compute effective `allowed = (allowed_tags if allowed_tags is not None else frozenset(DEFAULT_DELIVERY.tags))` when `supports_audio_tags(preset.voice_model)` else `frozenset()`; sanitize beat `text` via `sanitize_script_tags`, drop beats whose `strip_audio_tags(text)` is empty, strip tags in `_headline` and `_card_line`, count words via `strip_audio_tags(beat.text).split()`.
  - Update `_missing(text, words, numbers)` to run on `strip_audio_tags(text)`.
- In `python/src/thoth_control_plane/assembly/style_preview.py`:
  - Update `estimated_words` to split `strip_audio_tags(beat.text).split()`.
- In `python/src/thoth_control_plane/activities/narration.py`:
  - Add small helper `_delivery_for(style: StyleTemplate | None) -> DeliveryRules` returning `style.narration.delivery if style is not None else DEFAULT_DELIVERY`.
  - In `write_script`: pass `delivery` to `build_script_request`, pass `allowed_tags=frozenset(delivery.tags)` and `max_tags_per_beat=delivery.max_tags_per_beat` to `parse_script`, and count spoken words via `strip_audio_tags(beat.text).split()` for `MIN_LENGTH_SHARE` and `longer`.
  - In `voice` and `revoice`: resolve `style` via `await ports.documents.get_latest(step.project_id, step.document_id)` (catching `Exception` with debug log -> `None` so stubs without `documents` degrade cleanly to `DEFAULT_DELIVERY`), pass `stability=_delivery_for(style).stability` to `_voice_beats` -> `VoiceRequest(..., stability=stability)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test T="tests/application/test_narration_script.py tests/assembly/test_style_preview.py tests/activities/test_narration_activities.py"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/application/narration_script.py python/src/thoth_control_plane/assembly/style_preview.py python/src/thoth_control_plane/activities/narration.py python/tests/application/test_narration_script.py python/tests/assembly/test_style_preview.py python/tests/activities/test_narration_activities.py
git commit -m "feat(narration): wire style delivery rules into scripts, preview, and voicing"
```

---

### Task 5: Editor migration `0036` (`narration_presets` default upgrade)

**Files:**
- Create: `python/migrations/editor/0036_stressed_voice_model.sql`
- Create: `python/migrations/editor/alembic/versions/0036_stressed_voice_model.py`
- Modify: `python/tests/operations/test_editor_migrations.py:32-70`
- Modify: `python/tests/operations/test_editor_migrations_postgres.py:41-97` (plus new test at end)

**Interfaces:**
- Consumes: existing migration `0035_footage_relation` (`down_revision = "0035"`).
- Produces: linear Alembic head `0036` updating `narration_presets` rows with `preset->>'voice_model' = 'eleven_multilingual_v2'` to `'eleven_v4'` and incrementing `revision = revision + 1`, leaving custom `voice_model` values and `narrations.preset` untouched.

- [ ] **Step 1: Write the failing migration tests**

- In `python/tests/operations/test_editor_migrations.py`: append `"0036_stressed_voice_model.sql"` to `MIGRATION_FILES` assertion.
- In `python/tests/operations/test_editor_migrations_postgres.py`:
  - Update `test_fresh_database_applies_every_revision_and_a_rerun_applies_none`: `== 36`.
  - Update `test_database_migrated_before_alembic_is_adopted_and_only_the_rest_applied`: `== 30` (`36 minus the 6 applied by hand`).
  - Add `test_migration_0036_upgrades_default_v2_presets_only`:
    - Apply migrations through `0035` (or stamp & run `0036` SQL / upgrade from `0035` to `head`):
    - Insert two `narration_presets` rows: project A with `voice_model = "eleven_multilingual_v2"`, `revision = 13`; project B with `voice_model = "custom_model"`, `revision = 2`; plus one `narrations` row with `preset.voice_model = "eleven_multilingual_v2"`.
    - Run `apply_editor_migrations(DATABASE_URL, MIGRATIONS)`:
      - project A is now `voice_model == "eleven_v4"`, `revision == 14`, all other preset fields intact;
      - project B stays `voice_model == "custom_model"`, `revision == 2`;
      - `narrations.preset->>'voice_model'` stays `"eleven_multilingual_v2"`.
    - Re-running `apply_editor_migrations` applies `0` revisions and leaves `revision == 14`.

- [ ] **Step 2: Run tests to verify failure**

Run: `make test T=tests/operations/test_editor_migrations.py`
Expected: FAIL.

- [ ] **Step 3: Create migration `0036`**

- Create `python/migrations/editor/0036_stressed_voice_model.sql`:
  ```sql
  -- Stressed narration delivery (2026-11-24): switch projects still on the old default
  -- eleven_multilingual_v2 to eleven_v4. Historical narrations.preset snapshots stay untouched.
  -- Rollback before 0036: UPDATE narration_presets SET preset = jsonb_set(preset, '{voice_model}',
  -- '"eleven_multilingual_v2"'::jsonb) WHERE preset->>'voice_model' = 'eleven_v4'; because older
  -- images send voice_settings.speed, which eleven_v4 rejects.
  UPDATE narration_presets
  SET preset = jsonb_set(preset, '{voice_model}', '"eleven_v4"'::jsonb),
      revision = revision + 1,
      updated_at = CURRENT_TIMESTAMP
  WHERE preset->>'voice_model' = 'eleven_multilingual_v2';
  ```
- Create `python/migrations/editor/alembic/versions/0036_stressed_voice_model.py` (`revision = "0036"`, `down_revision = "0035"`, calling `execute_sql_file(__file__)`).

- [ ] **Step 4: Run offline and Postgres migration tests**

Run:
- `make test T=tests/operations/test_editor_migrations.py`
- `make test-postgres`
Expected: PASS (0 skips in Postgres suite).

- [ ] **Step 5: Commit**

```bash
git add python/migrations/editor/0036_stressed_voice_model.sql python/migrations/editor/alembic/versions/0036_stressed_voice_model.py python/tests/operations/test_editor_migrations.py python/tests/operations/test_editor_migrations_postgres.py
git commit -m "feat(db): migrate default narration presets from v2 to eleven_v4"
```

---

### Task 6: Studio approval tag rendering, OpenAPI/types sync, and full verification

**Files:**
- Modify: `dashboard/src/features/studio/script/ScriptPanel.tsx:33-56`
- Modify: `dashboard/src/features/studio/script/ScriptPanel.test.tsx`
- Modify: `python/openapi.json` (regenerated)
- Modify: `dashboard/src/api/generated/control-plane.ts` (regenerated)
- Modify: `CHANGELOG.md`
- Modify: `.superpowers/sdd/2026-11-12-footage-library/progress.md`

**Interfaces:**
- Consumes: `NarrationPreset` OpenAPI schema (`@default eleven_v4`) and inline `[tag]` format (`\[[A-Za-z][A-Za-z ]{0,39}\]`).
- Produces: subtle muted `[tag]` rendering in `ScriptPanel.tsx`'s `Marked` approval component (never underlined as unsupported), editable raw text preserved in completed-state beat textareas, synchronized `openapi.json` and `control-plane.ts`.

- [ ] **Step 1: Write the failing dashboard test**

In `dashboard/src/features/studio/script/ScriptPanel.test.tsx`:
- Add `test("audio tags render subtly in approval without unsupported underlines and stay editable when completed")`:
  - With beat text `"[curious] Kata Andi, [clears throat] ikan diambil."` and `unsupported: { main: ["Andi"] }`:
  - In `awaiting_approval`: `[curious]` and `[clears throat]` render inside elements marked `data-audio-tag="true"` (subtle muted monospace styling) and are NOT inside `<mark title="Not found in the evidence">`, while `Andi` IS still underlined as unsupported;
  - In `completed`: the beat `<textarea>` value contains the exact raw `"[curious] Kata Andi, [clears throat] ikan diambil."` so the operator can edit tags inline before re-voicing.

- [ ] **Step 2: Run dashboard test to verify failure**

Run: `bun --cwd=dashboard test src/features/studio/script/ScriptPanel.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Update `ScriptPanel.tsx` and regenerate OpenAPI + TypeScript types**

- In `dashboard/src/features/studio/script/ScriptPanel.tsx`, update `Marked` to split first on `/(\[[A-Za-z][A-Za-z ]{0,39}\])/g`: render matched `[...]` audio tags as `<span data-audio-tag="true" className="mx-0.5 rounded bg-surface px-1 py-0.5 font-mono text-[11px] text-muted-ink">{segment}</span>`, and pass non-tag segments through the existing whitespace + unsupported-word `<mark>` logic.
- Regenerate OpenAPI and dashboard types:
  - From WSL: `python/scripts/export_openapi.py` (via the repo's uv/python environment used by `make test`) to update `python/openapi.json`;
  - Run `bun --cwd=dashboard run generate:control-plane-types` to update `dashboard/src/api/generated/control-plane.ts`.
  - Verify `git diff dashboard/src/api/generated/control-plane.ts` shows `@default eleven_v4`.

- [ ] **Step 4: Run full verification suite**

Run every required verification command (from WSL):
- `make lint` (check exit code 0)
- `make test` (full Python suite)
- `make test-postgres` (full Postgres suite)
- `make dashboard-test`
- `make dashboard-build` (includes `tsc -b` and Vite build)
- `graphify update .` (per `.agents/rules/graphify.md`, never commit `graphify-out/`)

Expected: ALL green, zero failures, zero lint warnings.

- [ ] **Step 5: Commit implementation, update `CHANGELOG.md` and SDD checkpoint**

```bash
git add dashboard/src/features/studio/script/ScriptPanel.tsx dashboard/src/features/studio/script/ScriptPanel.test.tsx python/openapi.json dashboard/src/api/generated/control-plane.ts
git commit -m "feat(dashboard): style audio tags in script approval and sync openapi"
```

Then append the completed-work record (with exact test counts, migration 0036 rollback note, and **Next steps** gates: push/PR + CI, branch deploy to stage1 with migration 0036, paid live Style A & Style B narration check with cost shown first, merge) to `CHANGELOG.md` and `.superpowers/sdd/2026-11-12-footage-library/progress.md`, and commit `CHANGELOG.md`:

```bash
git add CHANGELOG.md
git commit -m "docs: record stressed narration delivery implementation"
```

**Hard stop:** Do NOT push, open a PR, deploy to stage1, or make any paid ElevenLabs/LLM call without explicit operator authorization for each gate.

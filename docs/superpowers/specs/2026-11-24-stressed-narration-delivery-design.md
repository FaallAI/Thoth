# Stressed narration delivery with Eleven v4

Date: 2026-11-24. Status: approved by operator ("ya lanjut", 2026-11-24). Roadmap: Reference-faithful editing track, stage 4 (`docs/ROADMAP.md`). Brainstorm record: items 93–99 of `.superpowers/sdd/2026-11-12-footage-library/brainstorm-notes.md`.

## 1. Intent and why

Human narrators in our reference videos emphasize the words that carry the story, while our current TTS narrations sound flat and stress sentence endings instead.

Measured read-only (`D:/thoth-tmp/footage-spike/stress_timing.py`, 11 reference breakdowns vs 13 of our narrations / 47 voices / 1,363 words; stressed = word held >= 1.6× the speaker's median seconds-per-letter):
- **Style A human references (5 Shorts):** stretch 36.7% of contrast/interjection words (*tapi, wah, eh, ternyata*), 27% of names, and 27% of numbers, but only 7% of phrase ends (stdev 0.90).
- **Style B human references (6 WinNews):** steadier news tone (stdev 0.48) with lighter stress on numbers (16.7%), names, and phrase ends (22.9%), and only 7.1% on contrast words.
- **Our current voices (`eleven_multilingual_v2`, sending only `speed=1.0`):** stretch 49.7% of phrase ends and 14.4% of names, but only 5.7% of contrast words and 0% of numbers.

A paid listening spike (`D:/thoth-tmp/footage-spike/stress_sample.py`, 401 input chars across 3 versions on `edoc_afd07b23`'s `main` beat using voice `plgKUYgnlZ1DCNh54DwJ`) settled both the quality choice and the API unknowns:
- **Operator verdict:** Eleven v4 (`eleven_v4`) with inline audio tags sounded noticeably more human and expressive than tuned `eleven_multilingual_v2` ("lebih enak versi 4").
- **Settled API fact:** `eleven_v4` interprets bracketed audio tags (`[curious]`, `[amused]`, `[excited]`) without speaking them aloud, **and includes those tags as timestamped tokens in both `alignment` and `normalized_alignment`**.

The operator ruled that **every style gets stressed delivery as the default**, not an opt-in toggle.

## 2. Goals, non-goals, and anti-goals

### Goals
- Make `eleven_v4` with style-appropriate inline audio tags the default narration delivery for **every style** (Style A, Style B, and unstyled drafts), including projects with custom Prompt Lab prompts.
- Match delivery intensity to each style's character (expressive commentary for Style A; calm, authoritative emphasis for Style B; moderate default when unstyled).
- Keep captions, b-roll planner phrase boundaries, SFX `word_index` placement, word-length checks, and `unsupported_tokens` completely free of `[...]` audio tags.
- Allow the operator to see, edit, add, or remove inline `[...]` tags directly when editing a beat for re-voice in Studio.
- Migrate existing saved project presets that still hold the old default `eleven_multilingual_v2` to `eleven_v4` so existing projects receive the improvement automatically.

### Non-goals
- Highlighting or animating stressed words differently in rendered captions (parked as optional future polish).
- Adding a new UI widget or separate tag editor in Studio (plain inline text editing in the existing beat textarea is sufficient).
- Supporting audio tags on non-ElevenLabs providers (`openai_compatible` ignores them or strips them if ever wired to narration).
- Changing loudness normalization (`-14 LUFS`, 3 s padding fix) or the voice ID (`plgKUYgnlZ1DCNh54DwJ`).

### Anti-goals
- An audio tag (`[curious]`, `[excited]`, etc.) appearing in rendered subtitles, planner phrase text, or Studio's unsupported-token warnings.
- An older model (`eleven_multilingual_v2`) speaking a tag word aloud if a project explicitly switches back to v2.
- Sending `speed` in `voice_settings` to `eleven_v4` / `eleven_v3` (unsupported by ElevenLabs v3/v4 APIs).
- Hallucinated Indonesian or non-tag brackets from the LLM (e.g., `[tertawa]`, `[musik]`, `[nama]`) reaching ElevenLabs.
- Re-voicing a beat losing its style's delivery `stability`.

## 3. Approaches considered

### Approach A — Inline audio tags in `beat.text` *(chosen by the operator)*
The script model writes ElevenLabs audio tags directly inside `ScriptBeat.text` (e.g., `[curious] Kelihatannya sih Mutant nggak suka, [amused] tapi ternyata ada maunya!`). Downstream layers strip `[...]` wherever spoken words are counted, validated, timed, or displayed as captions.
- **Pros:** Single source of truth. Editing a beat in Studio for re-voice naturally preserves or edits tags in place without drift. No new fields on `ScriptBeat`, no extra LLM call on re-voice, minimal UI changes.
- **Trade-off:** Tags appear inline in the Studio Script panel (mitigated by subtle badge/muted styling in the read-only approval view).

### Approach B — Separate plain `text` and `spoken_text` (or tag offsets)
Keep `ScriptBeat.text` completely plain and store tagged text or `{word_index, tag}` in a second field.
- **Pros:** Studio script text stays 100% bracket-free.
- **Trade-off:** Any manual beat edit in Studio immediately makes `spoken_text` or tag indices stale, either dropping stress on re-voice, requiring an extra LLM pass per re-voice, or needing a bespoke Studio tag editor. Adds schema, OpenAPI, and UI complexity with higher drift risk.

**Decision:** Operator chose **Approach A** ("gunakan pendekatan A", item 98).

## 4. Constraints

- **Schema backward compatibility:** Every new field on Pydantic domain models (`VoiceRequest`, `NarrationRules`, etc.) must have a default so stored drafts, presets, and older clients continue decoding cleanly.
- **ElevenLabs v4 API contract (verified via Context7 & live spike):**
  - Endpoint remains `POST /v1/text-to-speech/{voice_id}/with-timestamps?output_format=mp3_44100_128`.
  - `eleven_v4` (and `eleven_v4_turbo`) supports Indonesian (`language_code: "id"`), `previous_request_ids` (up to 3), `previous_text` / `next_text`, and `voice_settings.stability` (float `0.0..1.0`).
  - `eleven_v4` does **not** support `voice_settings.speed`.
  - `character-cost` header scales with total input length including tags, so `estimate_voice()` counts `len(beat.text)` when on `eleven_v4*`, and `len(strip_audio_tags(beat.text))` when on a non-tag model.
- **Graceful degradation:** If a project explicitly configures `eleven_multilingual_v2` (or another non-`eleven_v4*` model), script generation omits audio-tag instructions and the adapter strips any `[...]` tags before sending to ElevenLabs so nothing is spoken literally.
- **Database rollback:** Editor migration `0036` updates stored `narration_presets` rows (leaving historical `narrations.preset` snapshots untouched so older v2 drafts stay acoustically consistent on single-beat re-voice). Because images older than this release send `voice_settings: {"speed": 1.0}` to whatever `voice_model` is stored, rolling back to pre-0036 images requires reverting `narration_presets.preset->>'voice_model'` back to `"eleven_multilingual_v2"` (documented in the migration header).

## 5. Design

### 5.1 Shared audio-tag utilities

Add a small, pure module (e.g., `python/src/thoth_control_plane/voice/audio_tags.py`, or inside `voice/ports.py` — left to the builder) used across script validation, activities, and the ElevenLabs adapter:

- **Tag pattern:** A bracketed audio tag is `[...]` containing 1 to 40 ASCII letters and spaces (`r"\[[A-Za-z][A-Za-z ]{0,39}\]"`). This covers both single-word (`[curious]`, `[excited]`) and multi-word (`[clears throat]`) ElevenLabs tags without accidentally eating numeric citations or arbitrary prose.
- `strip_audio_tags(text: str) -> str`: removes all bracketed audio tags (and any stray `[...]` blocks during sanitization when requested) and normalizes surrounding whitespace (`" ".join(...split())`), keeping punctuation attached to the preceding word cleanly (e.g., `"suka, [amused] tapi"` → `"suka, tapi"`).
- `sanitize_script_tags(text: str, allowed: frozenset[str]) -> str`: used on LLM-generated script output in `parse_script`. For every bracketed span `\[([^\[\]]+)\]`:
  - normalize inner text with `" ".join(inner.lower().split())`;
  - keep `[normalized]` if `normalized in allowed`;
  - otherwise remove the entire bracketed span and collapse extra whitespace.
  This guarantees the LLM can never smuggle Indonesian tags (`[tertawa]`), stage notes (`[jeda 2 detik]`), or unapproved noisy tags (like `[laughs]` in Style B) into a generated script.
- Manual edits via Studio (`edit_beat`) do **not** restrict tags to the style allowlist, so the operator can experiment with any valid ElevenLabs English tag in Studio; only `strip_audio_tags` runs if the project switches to a non-tag model.

### 5.2 Per-style delivery profiles (`domain/style_templates.py`)

Add `DeliveryRules(StrictModel)` and attach it to `NarrationRules` with a sensible default:

```python
class DeliveryRules(StrictModel):
    stability: Annotated[float, Field(ge=0.0, le=1.0)] = 0.48
    tags: tuple[str, ...] = ("curious", "emphatically", "intrigued", "seriously")
    max_tags_per_beat: Annotated[int, Field(ge=1, le=6)] = 3
    guide: Annotated[str, Field(min_length=1, max_length=600)] = (
        "Use tags sparingly before contrast words, key names, numbers, or surprising turns."
    )
```

Built-in style profiles (grounded in item 94's reference measurements):
- **Style A (`style_a`, story explainer / commentary):**
  - `stability = 0.45`
  - `tags = ("curious", "amused", "excited", "surprised", "emphatically", "whispers")`
  - `max_tags_per_beat = 3`
  - `guide`: Expressive conversational commentary. Place tags before contrast/interjection words (*tapi, ternyata, malah, wah, eh*), key names, numbers, or plot twists; an ellipsis (`...`) may precede a surprising reveal.
- **Style B (`style_b`, kinetic-text news):**
  - `stability = 0.50`
  - `tags = ("seriously", "intrigued", "emphatically", "thoughtful")`
  - `max_tags_per_beat = 2`
  - `guide`: Calm, firm news delivery with light stress on numbers, dates, key names, and punchlines. Never use laughing, whispering, or overly dramatic reactions.
- **Unstyled default (`DEFAULT_DELIVERY`):**
  - `DeliveryRules()` (`stability = 0.48`, tags `curious`, `emphatically`, `intrigued`, `seriously`, `max_tags_per_beat = 3`).

`_STARTER_A` and `_STARTER_B` remain unchanged so existing Prompt Lab bindings and `style.revision` stay unaffected. Because `build_script_request()` appends the delivery contract to the system prompt (alongside `SOURCE_RULES` and `ANSWER_CONTRACT`), **every** style and **every** custom Prompt Lab prompt gets stressed delivery automatically.

### 5.3 Script generation, validation, and cut preview (`application/narration_script.py`, `assembly/style_preview.py`, `activities/narration.py`)

1. **`build_script_request(..., delivery: DeliveryRules | None = None)`:**
   - When `supports_audio_tags(preset.voice_model)` is `True` *(our call: gate script tag prompting on model capability so projects that explicitly switch back to v2 do not receive dead tags)*:
     - resolves `delivery` (defaulting to `DEFAULT_DELIVERY` when `None`);
     - appends a concise `DELIVERY_RULES` block to `system` specifying:
       - allowed tags formatted as `[tag1]`, `[tag2]`, ...;
       - at most `delivery.max_tags_per_beat` tags per beat, placed immediately before the clause/word to emphasize;
       - the style's `delivery.guide`;
       - never invent bracketed tags outside the allowed list, never write Indonesian tags, and never put tags inside `headline` or `card_line`;
       - for `sfx_cues`, `word_index` counts **spoken words only** (ignoring `[...]` tags).
   - When `supports_audio_tags(preset.voice_model)` is `False`, omits `DELIVERY_RULES` so v2 scripts remain plain prose.
2. **`parse_script(..., allowed_tags: frozenset[str] | None = None, max_tags_per_beat: int | None = None)`:**
   - When `supports_audio_tags(preset.voice_model)` is `True`: uses `allowed_tags` (defaulting to `frozenset(DEFAULT_DELIVERY.tags)`) and `max_tags_per_beat` (defaulting to `DEFAULT_DELIVERY.max_tags_per_beat`) to run `sanitize_script_tags(text, allowed_tags, max_tags=...)` on each beat's `text`.
   - When `supports_audio_tags(preset.voice_model)` is `False`: strips all bracketed tags (`allowed_tags=frozenset()`).
   - Always strips any bracketed tags that might leak into `headline` or `card_line`.
   - Drops beats whose `strip_audio_tags(text)` is empty (a beat containing only tags produces no speech).
   - Counts words for `LENGTH_SLACK` using `len(strip_audio_tags(beat.text).split())`.
3. **`estimate_voice` (`domain/narration.py`):**
   - Counts `len(beat.text)` when `supports_audio_tags(preset.voice_model)` is `True`, and `len(strip_audio_tags(beat.text))` when `False`, so the Studio approval estimate matches what ElevenLabs actually receives.
4. **`unsupported_tokens` / `_missing`:**
   - Runs on `strip_audio_tags(text)` so tags never trigger false unsupported-token warnings or reset `sentence_start` erroneously.
5. **Pre-approval cut preview (`assembly/style_preview.py`):**
   - `estimated_words()` splits `strip_audio_tags(beat.text).split()` instead of `beat.text.split()`, so `[...]` tags never leak into pre-approval cut-preview captions or inflate estimated beat durations.
6. **Short-script retry in `activities/narration.py` (`write_script`):**
   - Counts words using `len(strip_audio_tags(beat.text).split())` for both `MIN_LENGTH_SHARE` and comparing `script` vs `short`.

### 5.4 Voice port and ElevenLabs adapter (`voice/ports.py` & `voice/adapters/elevenlabs.py`)

1. **`VoiceRequest` (`voice/ports.py`):**
   - Add `stability: Annotated[float, Field(ge=0.0, le=1.0)] | None = None`.
   - Keep `speed: Annotated[float, Field(ge=0.7, le=1.5)] = 1.0` for backward compatibility with v2 models and CLI callers.
2. **Model detection (`supports_audio_tags`):**
   - `DEFAULT_MODEL = "eleven_v4"`.
   - `supports_audio_tags(model_id: str) -> bool`: returns `True` when `model_id` starts with `"eleven_v4"` (covering `eleven_v4` and `eleven_v4_turbo`) *(our call: narrow to `eleven_v4*` rather than `eleven_v3*`, because `eleven_v3` does not support `previous_request_ids` request stitching and was not selected; narrowing prevents mid-narration 4xx failures on beat 2+)*.
3. **Request payload in `ElevenLabsVoice.synthesize`:**
   - `model_id = request.model or DEFAULT_MODEL`.
   - If `supports_audio_tags(model_id)` is `True`:
     - `body["text"] = request.text` (keeps inline `[...]` tags);
     - `body["language_code"] = request.language`;
     - `voice_settings`: include `"stability": request.stability` when `request.stability is not None`; **do not send `speed`** (unsupported by v4). Omit `voice_settings` altogether if empty so ElevenLabs defaults apply cleanly.
     - `previous_text` / `next_text`: pass `strip_audio_tags(...)` (when non-empty) so neighboring mood tags don't bleed into the current beat's delivery while prose context and `previous_request_ids` still stitch smoothly.
   - If `supports_audio_tags(model_id)` is `False` (e.g., `eleven_multilingual_v2`):
     - `body["text"] = strip_audio_tags(request.text)` (if stripping empties the text, raise `VoiceRejected("empty_text_after_tag_strip")`);
     - `body["voice_settings"] = {"speed": request.speed}` (plus `"stability": request.stability` if set);
     - `previous_text` / `next_text`: pass `strip_audio_tags(...)` when non-empty.
4. **Tag stripping in `words_from_alignment(alignment)`:**
   - Walk the parallel `characters`, `character_start_times_seconds`, `character_end_times_seconds` arrays.
   - Whenever `[` is encountered and a matching `]` exists ahead before the next `[` (and the inner span matches the audio-tag shape `[A-Za-z][A-Za-z ]{0,39}`), skip all characters from `[` through `]` inclusive, treating the skipped span as a word boundary (flushing any word currently in progress).
   - This handles:
     - standard space-separated tags (`[curious] Halo` → `Halo`);
     - multi-word tags (`[clears throat] Halo` → `Halo`);
     - adjacent tags without spaces (`[curious]Halo` → `Halo`);
     - trailing tags (`Halo [sighs]` → `Halo`);
     - unclosed `[` (degrades gracefully as ordinary characters rather than dropping the rest of the sentence).
   - Because `VoiceRef.words` comes solely from `words_from_alignment`, **captions, b-roll planner phrases, and SFX `word_index` all remain 100% tag-free automatically**.
   - **Duration:** Keep `probe_duration(audio)` as fallback, or when `words` is non-empty keep `max(words[-1].end_seconds, ...)` — wait: if a beat ends with a silent tail or trailing tag, `probe_duration(audio)` vs `words[-1].end_seconds` behaves identically to today because tags sit before clauses and trailing tags are stripped; no change needed to `duration = words[-1].end_seconds if words else probe_duration(audio)`.

### 5.5 Activities wiring (`activities/narration.py`)

- In `write_script`: resolve `delivery = style.narration.delivery if style is not None else DEFAULT_DELIVERY`, pass `delivery` to `build_script_request(...)`, and pass `allowed_tags=frozenset(delivery.tags)` and `max_tags_per_beat=delivery.max_tags_per_beat` to `parse_script(...)`.
- In `voice` and `revoice`: load the latest document to read `style = _style_of(document)` and compute `stability = (style.narration.delivery if style is not None else DEFAULT_DELIVERY).stability`, passing `stability` into `_voice_beats(...)` → `VoiceRequest(..., stability=stability)`.
  - If loading the document fails unexpectedly in a unit test stub that doesn't mock `documents` on `voice`/`revoice`, fall back gracefully to `DEFAULT_DELIVERY.stability` (log debug, never crash).

### 5.6 Preset default and migration `0036`

- `NarrationPreset.voice_model` (`domain/narration.py`) default changes from `"eleven_multilingual_v2"` to `"eleven_v4"`.
- New editor migration `0036_stressed_voice_model`:
  - `python/migrations/editor/0036_stressed_voice_model.sql`:
    ```sql
    -- Stressed narration delivery (2026-11-24): switch projects still on the old default
    -- eleven_multilingual_v2 to eleven_v4. Rollback before 0036: set voice_model back to
    -- 'eleven_multilingual_v2' because older images send voice_settings.speed, which v4 rejects.
    UPDATE narration_presets
    SET preset = jsonb_set(preset, '{voice_model}', '"eleven_v4"'::jsonb)
    WHERE preset->>'voice_model' = 'eleven_multilingual_v2';
    ```
  - Matching Alembic wrapper `python/migrations/editor/alembic/versions/0036_stressed_voice_model.py` (`revision = "0036"`, `down_revision = "0035"`).
- **Existing drafts (`narrations.preset`) stay untouched *(our call)*:** Historical completed drafts keep their frozen `eleven_multilingual_v2` snapshot so re-voicing a single beat on an older draft does not mix an `eleven_v4` voice with surrounding v2 beats. Starting a new narration or clicking **Restart narration** snapshots the migrated `narration_presets` (`eleven_v4`) for all beats consistently.
- Projects that already chose a custom `voice_model` are untouched. Users can still edit `voice_model` anytime in Studio's `NarrationPresetForm`.

### 5.7 Studio UI and OpenAPI (`dashboard/`)

- **`ScriptPanel.tsx` (`Marked` component, read-only approval view):**
  - Split text recognizing `[tag]` tokens (matching `/(\[[A-Za-z][A-Za-z ]{0,39}\])/g`) alongside whitespace/unsupported highlighting.
  - Render each `[tag]` in a subtle muted monospace span (`font-mono text-[11px] text-muted-ink`) so the script reads smoothly while showing where emphasis lands, and never underline a tag as unsupported.
- **Completed-state beat textarea:** unchanged — displays raw `beat.text` so the operator can edit, add, or remove `[tag]` inline before clicking Save & Re-voice.
- **OpenAPI & generated TypeScript types:** regenerate `python/openapi.json` and `dashboard/src/api/generated/control-plane.ts` so `NarrationPreset.voice_model` reflects `@default eleven_v4`.

## 6. Degrades without failing

- **Project uses `eleven_multilingual_v2` (or another non-`eleven_v4*` model):** script generation omits delivery tags, `estimate_voice` counts tag-stripped characters, and the adapter strips any `[...]` tags before synthesis while sending `speed` + `stability`, so delivery never reads tags aloud.
- **LLM returns no tags or invalid/Indonesian tags:** unknown tags are stripped cleanly; the narration still synthesizes on `eleven_v4` with the style's `stability` (never fails script parsing just because tags are absent or malformed).
- **Stored old scripts without tags:** synthesize cleanly on `eleven_v4` with `stability` and `language_code`.
- **Unclosed bracket in manually edited beat:** `words_from_alignment` treats it as normal text rather than dropping words.

## 7. Verification and evaluation

### Offline (automated, test-first)
- **Audio-tag helpers:** single-word tags, multi-word tags (`[clears throat]`), adjacent tags (`[curious]Halo`), unknown/Indonesian tag stripping (`[tertawa]` dropped), `max_tags_per_beat` capping, punctuation spacing preserved.
- **ElevenLabs adapter:**
  - `eleven_v4` sends `language_code`, sends `stability`, omits `speed`, keeps tags in `text`, strips tags in `previous_text`/`next_text`;
  - `eleven_multilingual_v2` strips tags from `text`/`previous_text`/`next_text`, sends `speed`;
  - `words_from_alignment` strips single-word, multi-word, adjacent, and trailing `[...]` tags while preserving exact start/end timestamps of every spoken word; unclosed `[` does not swallow trailing text;
  - real alignment payload recorded from the spike (`v3_eleven_v4_tags`) parses to the exact 19 clean spoken words with zero tags.
- **Script generation, validation, and cut preview:**
  - `build_script_request` includes style-specific delivery rules and allowed tags for Style A, Style B, and unstyled drafts on `eleven_v4`, omits delivery tag instructions when on `eleven_multilingual_v2`, and includes the spoken-only `word_index` instruction;
  - `parse_script` sanitizes disallowed tags, caps per-beat tag count, counts spoken words only for `LENGTH_SLACK`, drops tag-only beats, and strips tags from `headline`/`card_line`;
  - `estimate_voice` counts full `beat.text` on `eleven_v4` and tag-stripped text on `eleven_multilingual_v2`;
  - `unsupported_tokens` ignores `[...]` tags and preserves `sentence_start` across leading tags (`"[curious] Mutant..."` treats `Mutant` as sentence start, not mid-sentence unsupported);
  - `style_preview.estimated_words` strips `[...]` tags so cut-preview captions and durations stay clean.
- **Activities:** `write_script`, `voice`, and `revoice` pass style-specific delivery rules and `stability`; `MIN_LENGTH_SHARE` counts spoken words only.
- **Migration `0036` (Postgres test):** upgrades `eleven_multilingual_v2` rows to `eleven_v4`, leaves custom model rows untouched, idempotent.
- **Dashboard:** `ScriptPanel.test.tsx` verifies `[curious]` renders with subtle tag styling in approval view without unsupported underlining, and stays editable in the completed textarea; `bun test`, `tsc -b`, and build pass.
- **Full suite:** `make test`, `make test-postgres`, `make lint`.

### Live (operator gate, after push + CI + branch deploy to stage1)
- Run one paid narration on stage1 (cost shown first, operator approval required) — ideally checking both a Style A draft and a Style B draft — to verify:
  1. natural stressed delivery in Studio preview;
  2. zero `[...]` tags in captions, b-roll cuts, or SFX timing;
  3. editing a beat's tag and re-voicing applies cleanly.

## 8. Left to the builder

- Exact placement of `audio_tags.py` (standalone module under `voice/` vs helper inside `voice/ports.py`) as long as there are no circular imports between `domain/`, `application/`, and `voice/`.
- Exact Tailwind classes for the subtle `[tag]` span in `ScriptPanel.tsx` matching existing design tokens (`text-muted-ink`, `bg-surface` / `bg-well`).
- Whether `0036_stressed_voice_model.sql` increments `narration_presets.revision` or leaves `revision` unchanged (incrementing `revision = revision + 1` is safe and prevents a stale browser tab from silently overwriting `eleven_v4` back to `eleven_multilingual_v2` on save — recommended).

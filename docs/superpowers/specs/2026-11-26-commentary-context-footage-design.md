# Commentary Context Footage & Mid-Story B-Roll Cutaways

**Date:** 2026-11-26
**Status:** Approved (operator, 2026-11-26)
**Track:** Footage Library & Planner follow-up (after PR #133 & PR #135)
**Brainstorm log:** `.superpowers/sdd/2026-11-12-footage-library/brainstorm-notes.md` (items 106–107)

---

## 1. Problem & Live Evidence

Live inspection of narrated draft `edoc_7ec87b54ccfc4305ba1121582551028b` (workflow `wf_18344b47ad6dce56d715ff1a`) exposed why context-enriching footage fails on commentary / talking-head posts:

- **Main video:** Ernest Prakasa (`@ernestprakasa`, 102 s Instagram monologue) responding to Kemenbud's Irini Dewi Wanti about artists using the FFI 2026 Piala Citra stage for political criticism, and explicitly citing *"Bahwa Fadlizon menyangkal perkosaan masal di 98 itu fakta"* (`S8–S9`, 19.9–25.9 s).
- **Operator feedback:** Stressed narration delivery (`eleven_v4`) and overall editing rhythm are good, but footage only appeared at the tail (`footage` beat) instead of enriching the story mid-narration — e.g., showing a brief visual cut of the FFI 2026 3-finger protest or Fadli Zon when Ernest mentions them (referencing `@pikiranrakyat/video/7710524300305894674` and `@podmuses/video/7710288912601632052`).
- **Four stacked blockers verified in `wf_18344b47`:**
  1. **English `event` + missing years killed 100% of Indonesian event clips at `story` gate:** `CARD_PROMPT` wrote `event` in English (`"...Ministry of Culture... FFI 2026..."`). `event_terms()` kept only capitalized words (`>= 4` chars) and uppercase acronyms (`>= 3` chars), dropping digits (`2026`), leaving only `{"ministry", "culture", "ffi"}`. Because `context_reason()` requires `names_subject` (`"ernest"`) OR `>= 2` event terms, no Indonesian caption could ever match 2 terms. **8+ spot-on FFI 2026 / Fadli Zon / Kemenbud clips were already returned by search** (`@tribunkaltimofficial`, `@MediaCakra`, `@tribunnews`, `@suaradotcom`, `@besokajanonton`, `@whatpop.id`, `@nusantarapost.news`, `@jandahebrink`, `@amiawardsofficial`) and all were rejected `story`.
  2. **Discussed figures & external sub-events omitted from Context Card:** `CARD_PROMPT` puts `people[0]` = on-camera speaker (`Ernest Prakasa`) and restricts `related` queries to naming `people[0]`, omitting **Fadli Zon** and specific sub-events (FFI 2026 3-finger protest, Fadli Zon 1998 denial) from `people` and searches.
  3. **Commentator face check, `MAX_DISCUSSES = 1`, and `_sections()` block external event clips:** Even after fixing `story`, `footage/service.py` enforces ArcFace matching against `people[0]` (Ernest) and caps non-subject clips at `MAX_DISCUSSES = 1` (requiring the caption to name Ernest). On a commentary video, clips of the discussed event (FFI stage, Fadli Zon, Irini Dewi Wanti) will never contain Ernest's face. Likewise, `_sections()` requires long YouTube captions to name `people[0]`.
  4. **Planner locks talking-head soundbites to `main`, lacks footage topic metadata, and Rule 12 blocks external figures:** `planner_service.py:_merged()` unconditionally discards `answer.base` whenever `phrase.soundbite` is `True` (locking 7/9 `main` phrases to Ernest's face; total 22/22 phrases used `main`, 0x footage). `SOURCES:` passes only `from <handle>` and `said` (blank for short TikToks) — never the clip's caption or vision description. In addition, `_on_screen()` only matches `MAIN`'s face groups, so every external footage shot is tagged `"other people"`, which Rule 12 currently bars for any named person.

---

## 2. Scope, Goals & Non-Goals

**Approved direction (operator, 2026-11-26):** Package 1 (context-aware retrieval & gating) + Package 2 (context-aware mid-story visual B-roll cutaways, Option A: muted visual B-roll under narration/main voice).

**Goals:**
1. Preserve 100% of existing strict behavior for **`incident`** videos (e.g., Mutant at USS: ArcFace subject-face check, `MAX_DISCUSSES = 1`, `related` naming `people[0]`, replay fixtures).
2. Accurately classify **`commentary`** main videos (person talking to camera reacting to or explaining external events/figures), search for the discussed events and figures in Indonesian, and admit clean external event footage without requiring the commentator's face.
3. Carry each footage clip's topic summary (`caption` and vision `description`, falling back to `query` when absent) from `content-set.json` provenance into `StudioMaterial` and the planner's `SOURCES:` prompt.
4. Allow the planner to place muted visual B-roll cutaways (`layer="broll"`) during talking-head `main` soundbites when a footage clip directly illustrates a discussed event or external public figure, falling back safely to the `main` soundbite / running cursor if the footage shot is unavailable or too short.
5. Keep backward compatibility for all stored `footage_runs.context`, `content-set.json`, `DraftPlan`, and `EditDocumentV2` rows with zero database migrations and zero Remotion composition / golden changes.

**Non-Goals:**
- **No external clip audio / L-cut playback** (Option B declined by operator). Sounding `b_roll` clips that overlap a visible `main_video` clip are muted via `volume_keyframes=[VolumeKeyframe(frame=0, volume=0.0)]`, while standalone `footage`-beat b-roll keeps its existing ducking behavior.
- **No changes to narration script generation** (`application/narration_script.py`). Raw TikTok captions are noisy and must not be injected as spoken script facts; the main transcript and `footage_talk` remain the script's factual sources.
- **No changes to `MAX_FOOTAGE` (8), `MAX_OLD` (2), `MAX_TRANSCRIPT` (1500), or the `commentary` vision rejection** (slideshows, news anchors, and reaction heads remain rejected; real event/stage/press-conference footage passes).

---

## 3. Package 1: Context Card & Commentary Footage Gating

### 3.1 `ContextCard.main_kind` (`python/src/thoth_control_plane/footage/context.py`)

Add one defaulted field to `ContextCard`:

```python
main_kind: Literal["incident", "commentary"] = "incident"
```

Add a `mode="before"` validator on `main_kind`:
- Strip and lowercase strings; return `"commentary"` iff the value is `"commentary"`, otherwise `"incident"`.
- Older stored cards without `main_kind` and unexpected LLM values safely decode as `"incident"`.

### 3.2 `CARD_PROMPT` and `REFINE_PROMPT` (`footage/context.py`)

Update `CARD_PROMPT`:
- Add `"main_kind": "incident" | "commentary"` to the required JSON object:
  - `"incident"`: the main video shows an event, interaction, or person doing something in person.
  - `"commentary"`: the main video is a person talking to camera (monologue, reaction, opinion, explainer) about an external event, controversy, or other public figures.
- Require **`"event"` and `"place"` in the language of the post** (Indonesian for Indonesian posts), capitalizing real proper names of events, awards, institutions, and keeping years as Indonesian viewers call them (e.g., `"Polemik kritik panggung Piala Citra FFI 2026 soal pernyataan Fadli Zon dan Kemenbud"` rather than English `"Ministry of Culture"`).
- Keep `people[0]` as the person on camera (`"people[0]"`, `"only in comments"`, `"without titles"`, and `"spoken"` contract wording preserved).
- For **`"commentary"`** posts:
  - `people[1:]` must include key external public figures named in the post or transcript (e.g., both `Irini Dewi Wanti` and `Fadli Zon`), not only the account being replied to.
  - `queries` (up to `INCIDENT_QUERIES = 2`) and `related` (up to `MAX_RELATED = 6`) search the **specific external events, moments, gestures, and statements discussed** as Indonesian viewers search them — without forcing `people[0]`'s name into every query (e.g., `"FFI 2026 3 jari"`, `"kritik panggung Piala Citra FFI 2026"`, `"Fadli Zon menyangkal 1998"`, `"tanggapan Kemenbud FFI 2026"`).
  - For `related[].event`, describe the **visible scene** (e.g., `"Sineas berpidato dan mengacungkan tiga jari di panggung FFI 2026"`, `"Fadli Zon berbicara di wawancara atau konferensi pers"`) rather than an invisible abstract claim, so the vision gate checks frames realistically.
- For **`"incident"`** posts: `related` keeps the existing rule (other events naming `people[0]`).

Update `REFINE_PROMPT`:
- Keep `"event"` and `"place"` in the language of the post and preserve `"main_kind"`.
- Because round 2 only sees search titles (not the main video/caption/transcript), `footage/service.py:_rounds()` **always preserves `card.main_kind`** (`refined = refined.model_copy(update={"main_kind": card.main_kind})`), preventing an omitted or drifted `main_kind` from silently resetting a `"commentary"` run back to `"incident"`.

### 3.3 `event_terms()` & `context_reason()` (`footage/context.py`)

1. **Year tokens & Indonesian generic terms:**
   - Add `_YEAR = re.compile(r"^(?:19|20)\d{2}$")`.
   - Extract helper `_terms(text: str) -> set[str]`:
     - Keeps tokens matching:
       - uppercase acronym of length `>= MIN_NAME` (e.g., `FFI`, `USS`), OR
       - capitalized word of length `>= MIN_TERM` (e.g., `Piala`, `Citra`, `Kemenbud`, `Festival`, `Film`), OR
       - 4-digit year matching `_YEAR` (e.g., `1998`, `2026`).
     - Subtracts `GENERIC_TERMS` and checks `term in content_words(term)`.
   - Expand `GENERIC_TERMS` with common Indonesian sentence-opening/generic nouns that should not count as distinctive event identifiers on their own:
     `{"tanggapan", "respons", "kritik", "soal", "tentang", "terkait", "berita", "kasus", "momen", "aksi", "polemik", "pernyataan", "panggung", "tahun", "hari", "orang", "warga", "publik", "pemerintah", "sosial"}`.
   - `event_terms(card)` returns `sorted(_terms(f"{card.event} {card.place}"))`.
   - **Year + `place` collision guard:** When checking a `>= 2` term match on `card.event + card.place` (in `context_reason` and `same_event`), require **at least 1 matched non-year term from `card.event`** (unless `>= 2` non-year terms matched overall). That way `"FFI 2026"` (`ffi` from `card.event` + `2026`) passes, `"Urban Sneaker Society"` passes, and an unrelated `"Konser Jakarta 2026"` matching only `place="Jakarta"` + `"2026"` is rejected.

2. **`context_reason(text: str, card: ContextCard)`:**
   - **`card.main_kind == "incident"` (default):** 100% unchanged in behavior (`names_subject(said, card)` OR `>= 2` non-person terms from `event_terms(card)` with the year+place guard).
   - **`card.main_kind == "commentary"`:** Passes if ANY of the following hold:
     1. `names_subject(said, card)` (names `people[0]`);
     2. Matches `>= 2` non-person terms from `event_terms(card)` (with the year+place guard) **OR** matches `>= 2` non-person terms from any **single** `related.event` (`_terms(r.event) - named`, requiring `>= 1` non-year term, evaluated per related event so unrelated words from different events cannot combine);
     3. `names_discussed_with_context(said, card)` is `True`:
        - `said` mentions at least one discussed person in `card.people[1:]` (via `mentions`), **AND**
        - `said` matches at least **1** distinctive context word (whole-word `_says`) from:
          - non-person `event_terms(card)`,
          - non-person `_terms(r.event)` and `_terms(r.query)` across `card.related`,
          - non-person `_terms(q)` across `card.queries`, or
          - `card.spoken`.
        - Including `_terms(r.query)` / `_terms(q)` keeps `related[].event` purely visual for the vision judge while allowing years/acronyms in queries (such as `"1998"` in `"Fadli Zon menyangkal 1998"`) to confirm relevance.
   - **Precision check:**
     - *"Fadli Zon bantah pemerkosaan massal Mei 1998"* → names `Fadli Zon` (`people[1:]`) + `"1998"` (from `r.query` / `spoken`) → **passes**.
     - *"Fadli Zon kunjungi museum batik di Solo"* → names `Fadli Zon` + 0 context words → **rejected (`story`)**.
     - *"Sineas acungkan 3 jari di panggung FFI 2026"* → matches `ffi` (non-year from `card.event`) + `2026` → **passes**.
     - *"Menang Piala Citra! Produser Film Para Perasuk Kritik Fadli Zon Soal Pemerkosaan Mei 1998"* → matches `piala` + `citra` (and `fadli zon` + `1998`) → **passes**.
     - *"Konser musik di Jakarta 2026"* (against `event="Polemik FFI 2026", place="Jakarta"`) → matches only `place` + year, 0 non-year terms from `card.event` → **rejected (`story`)**.

### 3.4 Time Window, Face Check, `MAX_DISCUSSES`, and Long-Video Sections (`footage/service.py`)

1. **Time window (`_off_story`):**
   - `names_subject(said, card)` → `PERSON_WINDOW` (730 days, unchanged).
   - If `card.main_kind == "commentary"` and `names_discussed_with_context(said, card)` → also `PERSON_WINDOW` (730 days, still bounded by `MAX_OLD = 2` clips older than 30 days) so historical clips of a discussed figure's prior statement (e.g., Fadli Zon's 1998 denial) are admitted instead of dropped by the 30-day event window.
   - Pure event-term matches without any named person → keep `WINDOW_BEFORE` (30 days).

2. **Commentator face check (`_needs_subject_face(candidate, state)`):**
   - Add pure helper method `_needs_subject_face(candidate: CandidateView, state: _Build) -> bool`:
     - `False` when `state.subject is None` or `candidate.source == "carousel"`.
     - `True` when `state.card is None` or `state.card.main_kind != "commentary"` (incident runs 100% unchanged).
     - On `card.main_kind == "commentary"`: normalize `q = norm(candidate.query)`. Returns `True` **only** if `q` is *solely* targeting `people[0]` — i.e., `names_subject(q, card)` AND `q` does not mention any `card.people[1:]` (via `mentions`) AND `q` contains no non-person event term from `card` / `card.related` (checked with whole-word `_says(q, term)`, never substring matching). Note: `source="creator"` (`query="creator:@ernestprakasa"`) satisfies this and keeps checking Ernest's face, which is intentional.
     - For all external-event and discussed-figure candidates (e.g., `"FFI 2026 3 jari"`, `"Fadli Zon menyangkal 1998"`, `"Irini Dewi Wanti Ernest Prakasa"`), `_needs_subject_face` returns `False`:
       - ArcFace commentator-face check is skipped (`shown = True`).
       - The clip does **not** consume `MAX_DISCUSSES = 1`.
       - It still passes through every quality gate: OCR (`subtitle`/`overlay`), Vision (`commentary`, `shows_object`, `same_event`), dHash duplicate, ORB copy check, and `MAX_OLD = 2`.
   - In `_from_library()` (`service.py:1691`): skip `self._shows_subject(path, state)` when `card.main_kind == "commentary"` (library reuse still requires `clip.relation == "related"` and `same_event(card, clip.event, clip.names)`).

3. **Long-video sections (`_sections`, `service.py:870-875`):**
   - On `card.main_kind == "incident"`: unchanged (`subject = subject_names(card)`, `others = card_names - subject`).
   - On `card.main_kind == "commentary"`: pass `subject = []`, `others = card_names(card)`, and include non-person terms from `card.related` (`_terms(r.event) | _terms(r.query)`) in `words` so long YouTube videos of the FFI 2026 ceremony or Fadli Zon press conferences can be cut at the exact moments they discuss the event/figures (still requiring `MIN_SCORE = 4` and `MIN_WORDS = 2` distinct words in `pick_discussions`).

4. **Vision `person` flag (`footage/context.py:290`):**
   - Already sets `person = _person(card, query) is not None`. Because `Fadli Zon` and `Irini Dewi Wanti` are now in `card.people`, queries naming them automatically receive `person=True` (`_PERSON_KIND`), which treats press conferences and interviews they give as `footage` while still rejecting news anchors, slideshows, and reaction videos as `commentary`.

---

## 4. Package 2: Context-Aware Mid-Story B-Roll Cutaways

### 4.1 Carry Footage Topic Metadata to the Planner

1. **`python/src/thoth_control_plane/assembly/studio.py` (`_footage`):**
   - Add two optional keys to `why` (computed on the fly from `content-set.json`, which already stores `Footage.caption` and `Footage.description` — so existing runs gain topic metadata immediately without re-importing):
     - `"caption": " ".join(clip.caption.split())[:300] or None`
     - `"description": " ".join(clip.description.split())[:300] or None`
2. **`python/src/thoth_control_plane/domain/studio_imports.py` (`StudioMaterial`):**
   - Add two optional defaulted fields (no breaking change to existing records or `comment_NNN` quotes):
     - `caption: str | None = None`
     - `description: str | None = None`
   - Regenerate API schema & TypeScript types using the repo's scripts:
     - `python/scripts/export_openapi.py` → `python/openapi.json`
     - `bun --cwd=dashboard run generate:control-plane-types` → `dashboard/src/api/generated/control-plane.ts`
3. **`python/src/thoth_control_plane/assembly/planner_service.py` (`_candidates`):**
   - Collect per-footage context from `materials.items` (indexed by `asset_id`), normalizing whitespace with `" ".join(text.split())`:
     - Prefer `caption` (truncated to 160 chars) and `description` (truncated to 140 chars).
     - Fall back to `query` when both `caption` and `description` are empty.
   - Append the summary to each footage line in `SOURCES:`:
     ```text
     - F1: footage video, from @tribunkaltimofficial — topic: Menang Piala Citra! Produser Film Para Perasuk Kritik Fadli Zon Soal Pemerkosaan Mei 1998; shows: A filmmaker speaking on stage at an award ceremony
     ```

### 4.2 Allow Visual B-Roll Cutaways During Soundbites

1. **`python/src/thoth_control_plane/assembly/adapters/planner_model.py` (`SYSTEM_PROMPT`):**
   - Keep Rule 1 (*Soundbite first*) so soundbites are never replaced by post cards or wrong `main` shots.
   - **Tighten Rule 12** so `"other people"` (emitted by `_on_screen()`, which only knows `MAIN`'s face groups) does not block external public figures:
     > 12. A phrase that names a person listed in "WHO IS ON SCREEN IN EACH SHOT" takes shots where that person is on screen, when there are any. A shot listed only with "other people" is never the picture for a person who IS listed in "WHO IS ON SCREEN IN EACH SHOT" (it may still show an external person named in `SOURCES`).
   - **Add Rule 13 (Context cutaway over talking head):**
     > 13. Context cutaway over a talking head. When the main video is mostly one person talking to camera and a phrase names or describes a specific external event, stage moment, protest, or another public figure that a footage source (`F1`, `F2`, ...) clearly shows (check its topic/shows line in `SOURCES` and its contact sheet), pick that footage shot as `base` for that phrase (1–2 phrases) instead of staying on the talking head — even if the main speaker says those words (this is the one exception to rule 1) and even if "WHO IS ON SCREEN IN EACH SHOT" tags that footage shot as "other people". Only cut to footage that directly matches the phrase; return to `MAIN` for the speaker's own opinion, reaction, or summary.

2. **`python/src/thoth_control_plane/assembly/planner_service.py` (`_merged`):**
   - Pass `footage_ids: AbstractSet[str]` (`{s.shot_id for s in shots if s.source == "footage"}`) into `_merged(phrase, answer, footage_ids)`:
     ```python
     def _merged(
         phrase: PlanPhrase,
         answer: PhraseAnswer | None,
         footage_ids: AbstractSet[str] = frozenset(),
     ) -> PlanPhrase:
         """A soundbite keeps its main base unless the model chose a footage cutaway; the
         soundbite's main shots remain as fallback if the cutaway shot is too short or used."""
         if answer is None:
             return phrase
         if phrase.soundbite:
             cutaway = [shot for shot in answer.base if shot in footage_ids]
             if cutaway:
                 return phrase.model_copy(
                     update={
                         "base": [*cutaway, *phrase.base],
                         "overlay": answer.overlay,
                         "soundbite": False,
                         "why": answer.why,
                     }
                 )
             return phrase.model_copy(update={"overlay": answer.overlay, "why": answer.why})
         return phrase.model_copy(
             update={"base": answer.base, "overlay": answer.overlay, "why": answer.why}
         )
     ```
   - **Behavior with `domain/planner_assign.py:pick_bases()`:**
     - `soundbite=False` ensures `pick_bases()` enforces `MIN_SHARE_OF_WINDOW` (a footage cutaway must last at least half the phrase window, capped by `cap_seconds` if set) and never forces a tiny sliver onto a phrase.
     - `*phrase.base` stays appended as fallback: if every cutaway shot is already used or too short, `pick_bases()` tries the `main` soundbite shots (subject to `MIN_SHARE_OF_WINDOW`) and otherwise falls back cleanly to the running `main` cursor.
     - If the model picks `main` shots, `none`, or fails/times out (`PlannerUnavailable`), `phrase.soundbite` keeps its deterministic `phrase.base` 100% unchanged.
     - `domain/planner_assign.py` requires **zero** changes (`test_planner_assign.py` invariants stay untouched).

### 4.3 Mute Sounding B-Roll Cutaways Over Running `main` Audio (`assembly/narration_timeline.py`)

Per operator decision (Option A: visual B-roll muted over narration/main voice):
- `TimelineVideoClip` carries audio level through `volume_keyframes` (it has no `volume` field, and `volume_keyframes=[]` plays at full 1.0 volume in Remotion `AdvancedTimelineComposition.tsx`). A single keyframe `[VolumeKeyframe(frame=0, volume=0.0)]` mutes a sounding `TimelineVideoClip` across its entire duration with zero schema, renderer, or golden changes.
- Extract one shared helper `_apply_video_audio(document, assets, curve)` called in **both** pass 1 (lines 328–335, covering re-voice early return and non-styled drafts) and pass 2 (lines 445–457, **before** returning when `curve` is empty):
  - Identify visible `b_roll` tracks (`{t.track_id for t in document.tracks if t.kind == "b_roll"}`) and visible `main_video` clip intervals (`[(c.from_frame, c.end_frame) for c in document.clips if isinstance(c, TimelineVideoClip) and c.track_id in main_tracks and not c.hidden]`).
  - For each clip in `document.clips`:
    - If not `_sounding(clip, assets)` (e.g., still cards `kind="image"` on `b_roll`, audio clips, text clips): leave unchanged (`volume_keyframes` stays `[]`).
    - Else if `clip.track_id in b_roll_tracks` and `[clip.from_frame, clip.end_frame)` overlaps any visible `main_video` interval (`clip.from_frame < m_end and m_start < clip.end_frame`): set `volume_keyframes=[VolumeKeyframe(frame=0, volume=0.0)]`.
    - Else if `curve`: set `volume_keyframes=_clip_keyframes(curve, clip)` (standalone `footage`-beat b-roll clips and `main_video` clips keep their exact existing ducking curve).
- Preserves `test_footage_on_the_b_roll_ducks_under_its_voice` (still card keeps `[]`, standalone `footage` clip keeps `duck_volume`) and `test_narrating_a_narrated_draft_again_changes_nothing` (idempotency across re-voice).

---

## 5. Verification Plan (Offline, Test-First)

1. **Replay & unit tests (`python/tests/footage/test_context.py`, `test_service.py`, `test_replay.py`):**
   - **Incident regression:** all existing Mutant replay & context tests pass unchanged (`main_kind="incident"` default).
   - **Ernest / FFI 2026 commentary fixture:** add a commentary card + the real candidate captions from `wf_18344b47` (FFI 2026 Piala Citra, Fadli Zon 1998, Irini Dewi Wanti, Kemenbud, plus off-topic Fadli Zon / `"Konser Jakarta 2026"` noise):
     - Confirm all relevant FFI 2026 / Fadli Zon / Kemenbud clips pass `context_reason()`.
     - Confirm unrelated Fadli Zon clip (*"Fadli Zon kunjungi museum batik di Solo"*) and `place` + year noise (*"Konser Jakarta 2026"*) are rejected `story`.
     - Confirm archival Fadli Zon 1998 clip (> 30 days, < 2 years) passes `_off_story` on commentary card, while pure event clip > 30 days still fails.
     - Confirm `_rounds()` preserves `card.main_kind == "commentary"` even when the round-2 model omits `"main_kind"`.
     - Confirm `FootageBuilder` on a commentary card with `face_check=True` (Ernest's face) admits multiple FFI / Fadli Zon clips without Ernest's face (`relation="related"`, NOT rejected `subject_absent`, NOT capped at `MAX_DISCUSSES = 1`), while still checking Ernest's face on an Ernest-only query (using whole-word matching) and still rejecting `subject_absent` on an `incident` card.
     - Confirm `_sections()` cuts long YouTube videos on a commentary card even when captions never say `people[0]`.
2. **Material provenance, planner & timeline tests (`python/tests/assembly/test_studio_projection.py`, `python/tests/application/test_workflow_studio_imports.py`, `python/tests/assembly/test_planner_service.py`, `python/tests/assembly/test_narration_timeline.py`):**
   - `project_content_set` / `StudioMaterial` preserves `caption` and `description` and decodes legacy provenance without them (and leaves `comment_NNN` quotes untouched).
   - `planner_service` includes `topic:` / `shows:` (whitespace-normalized, with `query` fallback) in `SOURCES:`.
   - `_merged` accepts a footage cutaway chosen by the model on a soundbite phrase (appending main soundbite fallback and clearing `soundbite`), while keeping `phrase.base` when the model picks `main` or `none`.
   - `narration_timeline` sets `volume_keyframes=[VolumeKeyframe(frame=0, volume=0.0)]` on sounding `b_roll` clips overlapping visible `main_video` (in both pass 1 and pass 2, including empty `curve` and re-voice idempotency), while leaving still cards `[]` and standalone `footage`-beat `b_roll` clips ducked.
3. **Full verification before any push:**
   - `make lint` and `make test` (full Python suite, WSL).
   - `python/scripts/export_openapi.py` + `bun --cwd=dashboard run generate:control-plane-types`.
   - `make dashboard-test` and `make dashboard-build` (`tsc -b` + build).
   - No live/paid calls during offline implementation; live verification on stage1 happens only after operator approves push & deploy.

---

## 6. Files Touched

- `python/src/thoth_control_plane/footage/context.py`
- `python/src/thoth_control_plane/footage/service.py`
- `python/src/thoth_control_plane/assembly/studio.py`
- `python/src/thoth_control_plane/domain/studio_imports.py`
- `python/src/thoth_control_plane/assembly/planner_service.py`
- `python/src/thoth_control_plane/assembly/adapters/planner_model.py`
- `python/src/thoth_control_plane/assembly/narration_timeline.py`
- `python/openapi.json` & `dashboard/src/api/generated/control-plane.ts`
- Unit/replay tests under `python/tests/footage/`, `python/tests/assembly/`, and `python/tests/application/`

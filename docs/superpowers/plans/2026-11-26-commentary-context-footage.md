# Commentary Context Footage & Mid-Story B-Roll Cutaways — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` (or `superpowers:subagent-driven-development`), `ponytail` (`full` intensity), `karpathy-guidelines`, and `tdd` (test-first) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable commentary/talking-head posts (like Ernest Prakasa discussing FFI 2026 / Fadli Zon / Kemenbud) to search and admit clean external event footage in Indonesian without requiring the commentator's face, feed each footage clip's topic summary to the planner, and place muted visual B-roll cutaways over talking-head `main` soundbites when a clip directly illustrates a discussed event or external public figure.

**Approved Spec:** `docs/superpowers/specs/2026-11-26-commentary-context-footage-design.md` (approved by operator 2026-11-26; brainstorm log items 106–108).

**Architecture:** Pure domain/context rules live in `footage/context.py`, orchestration/gates in `footage/service.py`, provenance carry-through in `assembly/studio.py` + `domain/studio_imports.py`, planner prompting/merging in `assembly/planner_service.py` + `assembly/adapters/planner_model.py`, and audio overlap muting in `assembly/narration_timeline.py`. Zero database migrations, zero `EditDocumentV2` schema changes, zero Remotion composition changes, and zero regressions on `main_kind="incident"` runs (Mutant replay fixtures).

**Branching:** Cut a new branch `feat/commentary-context-footage` from `master` (`065d7b1e`, or latest `origin/master` if `build/python-deps` has merged by execution time). **Never commit this work onto `build/python-deps` or `build/js-deps`.** If the main working tree is on `build/python-deps` with unmerged work, verify git status first and either switch to a clean branch from `master` or use a dedicated worktree off `master`.

**Tech Stack:** Python 3.12+ control plane (`uv`, `pytest`, `ruff` via WSL `make test T=<path>`, `make lint`), OpenAPI export (`python/scripts/export_openapi.py`), TypeScript dashboard types (`bun --cwd=dashboard run generate:control-plane-types`, `make dashboard-test`, `make dashboard-build`).

---

## Task 1: Commentary Context Card & Indonesian Event Matching (`footage/context.py`)

**Files:**
- Modify: `python/src/thoth_control_plane/footage/context.py`
- Test: `python/tests/footage/test_context.py`
- Test: `python/tests/footage/test_replay.py`

- [ ] **Step 1: Write failing tests in `python/tests/footage/test_context.py` and `python/tests/footage/test_replay.py`**

Add unit tests in `test_context.py` covering:
1. `ContextCard.main_kind` defaults to `"incident"`, normalizes `" Commentary "` → `"commentary"`, and coerces unknown/None values (`None`, `"unknown"`, `123`) to `"incident"`.
2. `CARD_PROMPT` requires `"main_kind"`, Indonesian `"event"`/`"place"`, discussed external figures in `people[1:]`, and visible scene descriptions in `related[].event`, while preserving existing prompt assertions (`"spoken"`, `"people[0]"`, `"only in comments"`, `"without titles"`). `REFINE_PROMPT` preserves `"main_kind"` and post-language `"event"`.
3. `event_terms()` extracts 4-digit years (`1998`, `2026`) alongside proper nouns (`>= 4`) and uppercase acronyms (`>= 3`), and filters Indonesian generic openers (`tanggapan`, `respons`, `kritik`, `soal`, `tentang`, `terkait`, `berita`, `kasus`, `momen`, `aksi`, `polemik`, `pernyataan`, `panggung`, `tahun`, `hari`, `orang`, `warga`, `publik`, `pemerintah`, `sosial`).
4. Year + `place` collision guard: a card with `event="Polemik FFI 2026"`, `place="Jakarta"` rejects `"Konser musik di Jakarta 2026"` (`"story"`) in both `context_reason` and `same_event`, while `"Sineas acungkan 3 jari di panggung FFI 2026"` passes (`None`).
5. Commentary card `context_reason()` + `names_discussed_with_context()` using the real Ernest / FFI 2026 scenario:
   - `main_kind="commentary"`, `people=[Ernest Prakasa, Irini Dewi Wanti, Fadli Zon]`, `event="Polemik kritik panggung Piala Citra FFI 2026 soal pernyataan Fadli Zon dan Kemenbud"`, `place="Indonesia"`, `related=[{"event": "Sineas berpidato dan mengacungkan tiga jari di panggung FFI 2026", "query": "FFI 2026 3 jari"}, {"event": "Fadli Zon berbicara di konferensi pers", "query": "Fadli Zon menyangkal 1998"}]`, `spoken=["piala", "citra", "pemerkosaan", "tragedi"]`.
   - Passes:
     - `"Menang Piala Citra! Produser Film Para Perasuk Kritik Fadli Zon Soal Pemerkosaan Mei 1998"`
     - `"Sentilan Keras Siera Tamihardja untuk Fadli Zon di Panggung FFI 2026 Soal Tragedi 1998"`
     - `"Respons Fadli Zon seusai Dikritik Terang-terangan di Panggung FFI 2026 soal Pemerkosaan Massal"`
     - `"Sejumlah Sineas Gunakan Panggung FFI 2026 untuk Suarakan Protes, Ini Tanggapan Kemenbud"`
     - `"Fadli Zon bantah pemerkosaan massal Mei 1998"` (matches `Fadli Zon` + `"1998"` from `r.query` even though `r.event` is purely visual!)
     - `"Sineas acungkan 3 jari di panggung FFI 2026"` (`ffi` + `2026`)
     - `"Irini Dewi Wanti tanggapi kritik panggung FFI 2026"`
   - Rejects (`"story"`):
     - `"Fadli Zon kunjungi museum batik di Solo"` (discussed person with 0 context words)
     - `"Berita terbaru panggung musik tahun ini"` (generic Indonesian words only)
     - `"Tanggapan kasus viral hari ini"` (generic Indonesian words only)
6. Incident card (`main_kind="incident"`) remains strictly unchanged: naming `people[1]` (`Denny Sumargo`) + a spoken word still returns `"story"` unless `people[0]` or `>= 2` event terms match.

Add a replay test in `test_replay.py` asserting all 8 real `wf_18344b47` FFI 2026 / Fadli Zon / Kemenbud captions pass on the commentary card while unrelated Fadli Zon / generic captions fail.

- [ ] **Step 2: Run targeted tests to verify they fail**

Run from WSL:
```bash
make test T="tests/footage/test_context.py tests/footage/test_replay.py"
```
Expected: new tests FAIL; existing tests pass.

- [ ] **Step 3: Implement changes in `python/src/thoth_control_plane/footage/context.py`**

Implement per Spec §3.1–3.3:
- Add `main_kind: Literal["incident", "commentary"] = "incident"` with `mode="before"` validator normalizing `"commentary"` (case-insensitive, stripped) and defaulting anything else to `"incident"`.
- Update `CARD_PROMPT` and `REFINE_PROMPT` per Spec §3.2 (preserving existing contract phrases).
- Add `_YEAR = re.compile(r"^(?:19|20)\d{2}$")` and expand `GENERIC_TERMS` with Indonesian generic fillers.
- Extract pure helper `_terms(text: str) -> set[str]` matching uppercase acronyms (`>= MIN_NAME`), capitalized words (`>= MIN_TERM`), or `_YEAR`, subtracting `GENERIC_TERMS` and checking `term in content_words(term)`.
- Update `event_terms(card)` to return `sorted(_terms(f"{card.event} {card.place}"))`.
- Add pure helper `_event_match(matched: set[str], event_only: set[str]) -> bool` implementing the year + `place` collision guard: `len(matched) >= 2` AND (`len({t for t in matched if not _YEAR.fullmatch(t)}) >= 2` OR `bool({t for t in matched if not _YEAR.fullmatch(t)} & event_only)`). Use it in both `context_reason()` and `same_event()`.
- Add pure helper `discussed_names(card: ContextCard) -> list[str]` (names/aliases of `card.people[1:]`) and `commentary_context_terms(card: ContextCard) -> set[str]` (non-person terms from `event_terms(card)`, every `r.event` and `r.query` in `card.related`, every `q` in `card.queries`, plus `card.spoken`).
- Add pure helper `names_discussed_with_context(said: str, card: ContextCard) -> bool` returning `True` iff `card.main_kind == "commentary"`, `any(mentions(said, name) for name in discussed_names(card))`, and `any(_says(said, term) for term in commentary_context_terms(card))`.
- Update `context_reason(text: str, card: ContextCard)`:
  - Always pass if `names_subject(said, card)`.
  - Pass if `_event_match(matched_main, event_only)` where `matched_main = {t for t in event_terms(card) if t not in named and _says(said, t)}`.
  - When `card.main_kind == "commentary"`:
    - Pass if any single `r` in `card.related` has `matched_rel = {t for t in _terms(r.event) - named if _says(said, t)}` with `len(matched_rel) >= 2` and `any(not _YEAR.fullmatch(t) for t in matched_rel)`.
    - Pass if `names_discussed_with_context(said, card)`.
  - Otherwise return `"story"`.

- [ ] **Step 4: Run tests and lint**

```bash
make test T="tests/footage/test_context.py tests/footage/test_replay.py"
make lint
```
Expected: all tests PASS, ruff check & format exit 0.

- [ ] **Step 5: Commit Task 1**

```bash
git add python/src/thoth_control_plane/footage/context.py python/tests/footage/test_context.py python/tests/footage/test_replay.py
git commit -m "feat(footage): add commentary context card and indonesian event matching"
```

---

## Task 2: Commentary Window, Face Check, Round-2 Preservation, and Long-Video Sections (`footage/service.py`)

**Files:**
- Modify: `python/src/thoth_control_plane/footage/service.py`
- Test: `python/tests/footage/test_service.py`

- [ ] **Step 1: Write failing tests in `python/tests/footage/test_service.py`**

Add tests covering Spec §3.2 (round 2) and §3.4:
1. **`_off_story` time window on commentary card:**
   - Candidate naming `Fadli Zon` + `"1998"` published 120 days before main (> 30 d, < 730 d) passes `_off_story` on `main_kind="commentary"`.
   - Candidate matching only event terms (`"FFI 2026"`) published 120 days before main still fails `_off_story` (30-day window).
   - Same archival Fadli Zon candidate fails `_off_story` on `main_kind="incident"`.
2. **`_rounds()` preserves `card.main_kind`:**
   - When round-1 card has `main_kind="commentary"` and the round-2 card model returns a card omitting `"main_kind"` (which validates as `"incident"`), stored context and `state.card.main_kind` remain `"commentary"`.
3. **Commentator face check exemption & `MAX_DISCUSSES`:**
   - Build a `FootageBuilder` run with `main_kind="commentary"`, `face_check=True`, `subject=<ernest_template>`, and a fake face reader returning non-matching faces on external clips.
   - Verify 2+ external clips (queries `"FFI 2026 3 jari"`, `"Fadli Zon menyangkal 1998"`, `"Irini Dewi Wanti Ernest Prakasa"`) are **admitted with `relation="related"`** (neither rejected `subject_absent` nor capped at `MAX_DISCUSSES = 1`).
   - Verify a commentator-only query (`"Ernest Prakasa standup"`, naming `people[0]` with no discussed person and no whole-word event term) STILL runs the face check and rejects `subject_absent` when Ernest's face is absent (and verify substring safety: a query like `"Ernest khusus"` does NOT falsely treat `"uss"` as an event term).
   - Verify an identical run with `main_kind="incident"` STILL enforces ArcFace and caps non-subject clips at `MAX_DISCUSSES = 1`.
4. **`_from_library()` on commentary card:**
   - Reused `relation="related"` library clip matching `same_event` is admitted on a `main_kind="commentary"` run even when `state.subject` is set and `_shows_subject` returns `False`.
5. **`_sections()` on commentary card:**
   - Long YouTube video (> `MAX_SECONDS`) whose captions discuss `"Fadli Zon"`, `"piala"`, `"citra"`, `"1998"` without ever saying `"Ernest"` produces sections on `main_kind="commentary"`, whereas `main_kind="incident"` produces 0 sections without `people[0]`.

- [ ] **Step 2: Run targeted tests to verify they fail**

```bash
make test T="tests/footage/test_service.py"
```

- [ ] **Step 3: Implement changes in `python/src/thoth_control_plane/footage/service.py`**

Implement per Spec §3.2 & §3.4:
- Import `discussed_names`, `names_discussed_with_context`, `_says` (or public `mentions_term` / `commentary_event_terms` helper from `footage/context.py` so `service.py` imports no private `_` symbols!). Prefer exporting clean public helpers from `footage/context.py` (e.g., `discussed_names`, `names_discussed_with_context`, `has_event_term(text, card)`).
- In `_off_story()`:
  - If `names_subject(said, card)` OR (`card.main_kind == "commentary"` and `names_discussed_with_context(said, card)`): check `in_window(..., before=PERSON_WINDOW)`.
  - Otherwise keep `in_window(...)` (30 days) and `context_reason(text, card) is not None`.
- In `_rounds()`:
  - Immediately after receiving `refined`, preserve `main_kind`: `refined = refined.model_copy(update={"main_kind": card.main_kind})`.
- Add `_needs_subject_face(candidate: CandidateView, state: _Build) -> bool`:
  - Return `False` if `state.subject is None` or `candidate.source == "carousel"`.
  - Return `True` if `state.card is None` or `state.card.main_kind != "commentary"`.
  - On `commentary`: normalize `q = norm(candidate.query)`. Return `True` iff `names_subject(q, state.card)` and not `any(mentions(q, name) for name in discussed_names(state.card))` and not `has_event_term(q, state.card)` (using whole-word `_says`).
- In `_check()` (line 1297): guard the face check with `if self._needs_subject_face(candidate, state):`.
- In `_from_library()` (line 1691): skip `_shows_subject` when `card.main_kind == "commentary"`.
- In `_sections()` (lines 870–875): when `card.main_kind == "commentary"`, pass `subject = []`, `others = card_names(card)`, and include non-person `related` event/query terms in `words`.

- [ ] **Step 4: Run tests and lint**

```bash
make test T="tests/footage/"
make lint
```

- [ ] **Step 5: Commit Task 2**

```bash
git add python/src/thoth_control_plane/footage/context.py python/src/thoth_control_plane/footage/service.py python/tests/footage/test_service.py
git commit -m "feat(footage): admit external event clips on commentary videos"
```

---

## Task 3: Footage `caption` & `description` on `StudioMaterial` + OpenAPI/TS Sync

**Files:**
- Modify: `python/src/thoth_control_plane/assembly/studio.py`
- Modify: `python/src/thoth_control_plane/domain/studio_imports.py`
- Regenerate: `python/openapi.json`
- Regenerate: `dashboard/src/api/generated/control-plane.ts`
- Test: `python/tests/assembly/test_studio_projection.py`
- Test: `python/tests/application/test_workflow_studio_imports.py`

- [ ] **Step 1: Write failing tests in `test_studio_projection.py` and `test_workflow_studio_imports.py`**

1. In `test_studio_projection.py`: verify `project_content_set` writes whitespace-normalized `"caption"` (<= 300 chars) and `"description"` (<= 300 chars) into `provenance["footage_000"]` (and `None` when empty).
2. In `test_workflow_studio_imports.py`: verify `materials()` hydrates `caption` and `description` onto `StudioMaterial`, decodes legacy provenance dicts without them (`caption is None and description is None`), and leaves `comment_NNN` quotes unaffected.

- [ ] **Step 2: Run targeted tests to verify they fail**

```bash
make test T="tests/assembly/test_studio_projection.py tests/application/test_workflow_studio_imports.py"
```

- [ ] **Step 3: Implement changes in `assembly/studio.py` and `domain/studio_imports.py`**

1. In `assembly/studio.py:_footage`, add to `why`:
   - `"caption": " ".join(clip.caption.split())[:300] or None`,
   - `"description": " ".join(clip.description.split())[:300] or None`,
2. In `domain/studio_imports.py:StudioMaterial`, add:
   - `caption: str | None = None`
   - `description: str | None = None`

- [ ] **Step 4: Regenerate OpenAPI & Dashboard TypeScript types**

Run OpenAPI export (WSL, using the same uv environment as `scripts/dev/pytest-wsl.sh` or `cd python && uv run python scripts/export_openapi.py` — check `scripts/dev/pytest-wsl.sh` for the exact uv invocation on WSL), then:
```bash
bun --cwd=dashboard run generate:control-plane-types
```
Verify `git diff python/openapi.json dashboard/src/api/generated/control-plane.ts` shows ONLY the new optional `caption` and `description` fields on `StudioMaterial`.

- [ ] **Step 5: Run tests, lint, and dashboard checks**

```bash
make test T="tests/assembly/test_studio_projection.py tests/application/test_workflow_studio_imports.py"
make lint
make dashboard-test
make dashboard-build
```

- [ ] **Step 6: Commit Task 3**

```bash
git add python/src/thoth_control_plane/assembly/studio.py python/src/thoth_control_plane/domain/studio_imports.py python/openapi.json dashboard/src/api/generated/control-plane.ts python/tests/assembly/test_studio_projection.py python/tests/application/test_workflow_studio_imports.py
git commit -m "feat(studio): expose footage caption and description on materials"
```

---

## Task 4: Planner Topic Context & Mid-Story Cutaways (`planner_service.py`, `planner_model.py`)

**Files:**
- Modify: `python/src/thoth_control_plane/assembly/planner_service.py`
- Modify: `python/src/thoth_control_plane/assembly/adapters/planner_model.py`
- Test: `python/tests/assembly/test_planner_service.py`

- [ ] **Step 1: Write failing tests in `python/tests/assembly/test_planner_service.py`**

Add tests covering Spec §4.1–4.2:
1. `SOURCES:` line for a footage source includes whitespace-normalized `topic: <caption>` (<= 160 chars) and `shows: <description>` (<= 140 chars), and falls back to `topic: <query>` when both `caption` and `description` are empty.
2. When a phrase matches a deterministic `main` soundbite (`phrase.soundbite=True`, `phrase.base=["S2"]`):
   - If the model picks a footage cutaway (`answer.base=["S40"]`, where `S40` has `source="footage"`), the merged phrase has `base=["S40", "S2"]`, `soundbite=False`, preserving `overlay` and `why`.
   - If the model picks only `main` shots (`answer.base=["S5"]`) or `none` (`answer.base=[]`), the merged phrase keeps `base=["S2"]`, `soundbite=True`, while still applying `overlay` and `why`.
   - If the model is unavailable (`PlannerUnavailable`), the soundbite phrase still keeps `base=["S2"]`, `soundbite=True`.
3. `SYSTEM_PROMPT` includes Rule 13 (context cutaway over talking head) and Rule 12's clarified `"other people"` wording so external figures in `SOURCES` are not blocked.

- [ ] **Step 2: Run targeted tests to verify they fail**

```bash
make test T="tests/assembly/test_planner_service.py"
```

- [ ] **Step 3: Implement changes in `assembly/planner_service.py` and `assembly/adapters/planner_model.py`**

1. In `assembly/planner_service.py:_candidates`:
   - Build a per-`asset_id` context map from `materials.items` (`role == "footage"`): normalize whitespace with `" ".join(text.split())`, take `caption[:160]` / `description[:140]`, fall back to `query[:160]` when both are blank.
   - Format the `SOURCES:` footage line as:
     `- {label}: footage video` + (`, from {handle}` if handle) + (` — {context}` if context), where `{context}` joins `topic: ...` and `shows: ...` with `; `.
2. In `assembly/planner_service.py`:
   - Pass `footage_ids = {s.shot_id for s in shots if s.source == "footage"}` into `_merged(p, by_id.get(p.phrase_id), footage_ids)`.
   - Update `_merged(phrase: PlanPhrase, answer: PhraseAnswer | None, footage_ids: AbstractSet[str] = frozenset()) -> PlanPhrase` per Spec §4.2 (using `from collections.abc import Set as AbstractSet`).
3. In `assembly/adapters/planner_model.py:SYSTEM_PROMPT`:
   - Tighten Rule 12 and append Rule 13 per Spec §4.2.

- [ ] **Step 4: Run tests and lint**

```bash
make test T="tests/assembly/test_planner_service.py tests/domain/test_planner.py tests/domain/test_planner_assign.py"
make lint
```

- [ ] **Step 5: Commit Task 4**

```bash
git add python/src/thoth_control_plane/assembly/planner_service.py python/src/thoth_control_plane/assembly/adapters/planner_model.py python/tests/assembly/test_planner_service.py
git commit -m "feat(planner): allow context b-roll cutaways over talking-head soundbites"
```

---

## Task 5: Mute Sounding `b_roll` Cutaways Over Running `main_video` (`assembly/narration_timeline.py`)

**Files:**
- Modify: `python/src/thoth_control_plane/assembly/narration_timeline.py`
- Test: `python/tests/assembly/test_narration_timeline.py`

- [ ] **Step 1: Write failing tests in `python/tests/assembly/test_narration_timeline.py`**

Add tests covering Spec §4.3:
1. A sounding planned `b_roll` footage clip placed over a visible `main_video` clip (e.g., during the `main` beat via a `DraftPlan`) receives `volume_keyframes == [VolumeKeyframe(frame=0, volume=0.0)]`.
2. A still image card (`kind="image"`) on `b_roll` overlapping `main_video` still has `volume_keyframes == []`.
3. A standalone `footage`-beat `b_roll` video clip (no overlapping visible `main_video` clip) still receives `PRESET.duck_volume` keyframes.
4. Re-narrating a draft with an overlapping sounding `b_roll` clip (both unchanged voices hitting the early return AND empty `curve` / re-voice of another beat) keeps `[VolumeKeyframe(frame=0, volume=0.0)]` and stays idempotent (`narrate_document(once, ...) == once`).

- [ ] **Step 2: Run targeted tests to verify they fail**

```bash
make test T="tests/assembly/test_narration_timeline.py"
```

- [ ] **Step 3: Implement shared `_apply_video_audio` helper in `assembly/narration_timeline.py`**

Implement per Spec §4.3:
- Extract `_apply_video_audio(document: EditDocumentV2, assets: Mapping[str, AssetRef], curve: list[tuple[int, float]]) -> EditDocumentV2`:
  - `main_tracks = {t.track_id for t in document.tracks if t.kind == "main_video"}`
  - `b_roll_tracks = {t.track_id for t in document.tracks if t.kind == "b_roll"}`
  - `main_ranges = [(c.from_frame, c.end_frame) for c in document.clips if isinstance(c, TimelineVideoClip) and c.track_id in main_tracks and not c.hidden]`
  - For each clip:
    - If not `_sounding(clip, assets)`: unchanged.
    - Else if `clip.track_id in b_roll_tracks` and `any(clip.from_frame < end and start < clip.end_frame for start, end in main_ranges)`: set `volume_keyframes=[VolumeKeyframe(frame=0, volume=0.0)]`.
    - Else if `curve`: set `volume_keyframes=_clip_keyframes(curve, clip)`.
    - Else: unchanged.
- Call `_apply_video_audio` in BOTH pass 1 (lines 328–335, before re-voice early return) and pass 2 (lines 445–457, **before** returning even if `curve` is empty).

- [ ] **Step 4: Run tests and lint**

```bash
make test T="tests/assembly/test_narration_timeline.py tests/domain/test_style_apply.py"
make lint
```

- [ ] **Step 5: Commit Task 5**

```bash
git add python/src/thoth_control_plane/assembly/narration_timeline.py python/tests/assembly/test_narration_timeline.py
git commit -m "fix(narration): mute sounding b-roll cutaways over main video"
```

---

## Task 6: Full Verification, Graphify Update, Checkpoint & Changelog

**Files:**
- Track spec & plan (force-add since `docs/superpowers/` is gitignored):
  - `docs/superpowers/specs/2026-11-26-commentary-context-footage-design.md`
  - `docs/superpowers/plans/2026-11-26-commentary-context-footage.md`
- Update: `CHANGELOG.md`
- Update: `.superpowers/sdd/2026-11-12-footage-library/progress.md` (untracked/gitignored checkpoint; do not commit)

- [ ] **Step 1: Run full verification suite (zero partial passes)**

```bash
make lint
make test
make dashboard-test
make dashboard-build
```
Check every exit code explicitly; fix any failure test-first before proceeding.

- [ ] **Step 2: Refresh local code index**

Run `graphify update .` (never stage `graphify-out/`, `.codegraph/`, or `.superpowers/`).

- [ ] **Step 3: Record completion in `CHANGELOG.md` and `.superpowers/sdd/2026-11-12-footage-library/progress.md`**

Include verification evidence, commit list, and a **Next steps** section listing:
- Push `feat/commentary-context-footage` & open PR (pending operator authorization);
- Wait for CI green & deploy branch CI image to stage1 (pending operator authorization);
- Live test on a commentary post (e.g., Ernest / FFI 2026) and verify footage admission + mid-story cutaways (paid call, pending operator authorization);
- Merge PR after operator acceptance.

- [ ] **Step 4: Commit docs & spec/plan**

```bash
git add -f docs/superpowers/specs/2026-11-26-commentary-context-footage-design.md docs/superpowers/plans/2026-11-26-commentary-context-footage.md
git add CHANGELOG.md
git commit -m "docs: record commentary context footage and b-roll cutaways"
```

- [ ] **Step 5: Hard stop & report back for review**

Do NOT push, open a PR, merge, deploy, or run live/paid API calls.

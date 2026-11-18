# Footage Revision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix footage found in the first live look, and let the narration and the planner use what
footage videos say. The fixes:
- the subject is always on the context card;
- podcast moments are picked where the incident is discussed;
- only one copy of a recording is kept, the original or the cleanest copy.

**Architecture:**
- **Card.** The card gains `spoken` words and a subject-first rule.
- **Moments.** A density picker in `footage/moments.py` returns discussions with their caption
  lines (`said`).
- **`said` storage and flow.** It is stored on candidates and library rows (editor migration 0034),
  carried by the Content Set's `Footage`, and exposed through Studio materials. The narration
  script request and the planner sources read it from there.
- **Copy check.** A two-stage check reuses the attribution `OrbMatcher`: a cheap trigger, then a
  time-alignment matrix.

**Tech Stack:** Python 3.12, pydantic, SQLAlchemy and Alembic over SQL files, OpenCV (already
installed), and pytest run through WSL `make`.

**Spec:** `docs/superpowers/specs/2026-11-15-footage-library-design.md`. Section 9 is approved
("ya sesuai", 2026-11-16), and 9.9 amends 9.4. The brainstorm record is items 59-64 in
`.superpowers/sdd/2026-11-12-footage-library/brainstorm-notes.md`.

## Global Constraints

**Card and moments:**
- Card `spoken`: up to 12 single lowercase Indonesian words, default `[]`.
- Discussion window 60 s, past the 30 s intro. Scoring: 2 per line naming the subject, 1 per line
  naming another card person, and 1 per distinct spoken or event word. A window qualifies with a
  score of at least 4 and at least 2 distinct words. Up to 3 windows, non-overlapping.
- `said` is at most 1,500 characters per discussion. Its lines are in source-video seconds,
  stored as TranscriptSegment dumps (`text`, `start_seconds`, `end_seconds`).
- The section stays 8 s from the moment minus 1 s (`section()`, unchanged).

**Copy check:**
- Use `OrbMatcher` (3000 features) on 480 px frames.
- Stage 1 compares the candidate's 3 vision-time frames against the main (1 frame per 2 s) and
  against each admitted clip. A best match of 25 or more inliers triggers stage 2.
- Stage 2 is a 1 fps matrix. A copy needs all three: at least 3 frames with best inliers of 25 or
  more; at least 60% of those on one offset within 1 s; and a median peak ratio (best / row
  median) of at least 3.
- Sections of the same source URL (the part before `#t=`) are never compared.
- Choosing among copies: an original (`source` in `creator`, `trace`, or an own account of the
  card) wins. Otherwise the lower OCR text-box area share over the 3 vision frames wins. A tie goes
  to the earlier `published_at`, with a missing date last.
- The loser is rejected `duplicate`, and its library row is dropped only if this run created it.
- No new reject reason and no CHECK change. Migration 0033 stays as shipped. A new 0034 adds
  `said JSONB NOT NULL DEFAULT '[]'` to `footage_candidates` and `footage_library`.

**Narration and planner:**
- The narration script sees footage speech under "What people say in other videos
  (auto-captions, may be misheard):". Each item is a line "- from <label>: <text>", labelled by
  `credit_label(platform, owner_handle)`.
- `SOURCE_RULES` gains the attribution sentence. Footage talk counts as evidence.
- The planner sources header becomes "WHAT EACH VIDEO SAYS DURING EACH SHOT:". `soundbite()` stays
  main-only.

**Rules that apply to every task:**
- Every new field has a default.
- No new paid call.
- With `matcher` None, the copy check is skipped and today's checks still run.
- Commits: one `git commit -m "<prefix>: <lowercase imperative>"`, at most 72 characters, no body,
  no trailer. Run `make lint` before every commit.
- Tests: `make test T=<path>` from WSL, and `make test-postgres` for `*_postgres.py`.

## Review Focus

1. **A card with no people** (`people=[]`): the picker runs on words alone and nothing crashes.
   Pinned in Task 2.
2. **Two copies checked at the same time:** exactly one stays admitted. A lock covers the decision
   and admit. Pinned in Task 5.
3. **A photo main, or a main video whose frames fail:** the main comparison is skipped and the
   other checks still run. Pinned in Task 5.
4. **A library clip from an earlier run losing to a cleaner copy:** that run's library row is
   kept. Only a row this run created is dropped. Pinned in Tasks 3 and 5.
5. **Stored `said` that is not a list** (old or odd JSON): it decodes to `[]` everywhere. Pinned
   in Tasks 3 and 6.

---

### Task 1: Context card — subject first, spoken words

**Files:**
- Modify: `python/src/thoth_control_plane/footage/context.py`
- Test: `python/tests/footage/test_context.py`

**Interfaces:**
- Produces: `ContextCard.spoken: list[str]` and `subject_names(card: ContextCard) -> list[str]`.
  The latter returns the normalised name and aliases of `people[0]`, at least 3 characters,
  longest first, and `[]` with no people.

- [ ] **Step 1: Write the failing tests**

```python
def test_spoken_words_are_single_lowercase_words() -> None:
    card = ContextCard.model_validate(
        {"spoken": ["Pedang", "marah", None, {"x": 1}, "dua kata", "marah", *[f"w{i}" for i in range(20)]]}
    )
    assert card.spoken[:2] == ["pedang", "marah"]
    assert "dua kata" not in card.spoken and len(card.spoken) == 12

def test_an_old_card_decodes_without_spoken() -> None:
    assert ContextCard.model_validate({"event": "x"}).spoken == []

def test_subject_names_are_the_first_persons() -> None:
    card = ContextCard.model_validate(
        {"people": [{"name": "Mutant", "aliases": ["Saiful", "Ipul"]}, {"name": "Denny Sumargo"}]}
    )
    assert subject_names(card) == ["mutant", "saiful", "ipul"]  # longest first, stable
    assert subject_names(ContextCard()) == []

def test_the_prompts_ask_for_the_subject_first_and_spoken_words() -> None:
    assert '"spoken"' in CARD_PROMPT and "people[0]" in CARD_PROMPT
    assert "only in comments" in CARD_PROMPT
    assert "people[0]" in REFINE_PROMPT
```

- [ ] **Step 2: Run them; expect FAIL** (`spoken`/`subject_names` missing).
  Run: `make test T=tests/footage/test_context.py`

- [ ] **Step 3: Implement.**
  - `spoken`: a `field_validator(mode="before")` that reuses `_texts`, then lowercases and strips
    each word, keeps only words without whitespace, dedupes in order, and caps the list at 12.
  - `subject_names`: `sorted(dict.fromkeys(_names(card.people[0])), key=len, reverse=True)` when
    there are people.
  - `CARD_PROMPT`: add `"spoken": [str]` to the JSON shape. Add the rules from spec 9.2:
    - people[0] is the person the post shows doing the thing, even if only a nickname or a
      description is known;
    - a person named only in comments is not one of the people, unless the comments say that
      person is in the video;
    - spoken is up to 12 single lowercase Indonesian words that people would say aloud when
      discussing the event.
  - `REFINE_PROMPT`: add "keep people[0] first and add the real names the titles use for people[0]".

- [ ] **Step 4: Run; expect PASS.** Then run the whole `tests/footage/test_context.py` and
  `test_context_model.py`.

- [ ] **Step 5: Commit** — `feat(footage): put the subject first and add spoken words to the card`

### Task 2: Discussions by density

**Files:**
- Modify: `python/src/thoth_control_plane/footage/moments.py`
- Test: `python/tests/footage/test_moments.py` (the two `pick_moments` tests are replaced; the
  ruling is spec 9.3 "replaces the scoring in 4.4")

**Interfaces:**
- Produces:
  - `Discussion` (frozen dataclass), with `moment: float` and
    `said: list[dict[str, float | str]]` (TranscriptSegment dumps);
  - `pick_discussions(lines: Sequence[CaptionLine], subject: Sequence[str], others:
    Sequence[str], words: Sequence[str], limit: int = MAX_MOMENTS) -> list[Discussion]`, in time
    order.
  - `pick_moments` is removed.
- Constants: `WINDOW_SECONDS = 60.0`, `MIN_SCORE = 4`, `MIN_WORDS = 2`, `SAID_CHARS = 1500`.

- [ ] **Step 1: Write the failing tests** (fixture `podcast_captions.json3`, 0-600 s)

```python
SUBJECT = ["mutan", "saiful"]
OTHERS = ["denny sumargo", "densu", "aldi taher"]
WORDS = ["pedang", "marah", "kursi", "diundang", "ngamuk", "uss"]

def test_the_incident_discussion_is_found() -> None:
    found = pick_discussions(parse_json3(CAPTIONS), SUBJECT, OTHERS, WORDS)
    assert any(240 <= d.moment <= 300 for d in found)  # mutan + pedang + USS, 4:05-5:00
    assert all(d.moment >= 30 for d in found)
    assert all(b.moment - a.moment >= 60 for a, b in pairwise(found))

def test_a_bare_name_mention_is_no_discussion() -> None:
    found = pick_discussions(parse_json3(CAPTIONS), SUBJECT, OTHERS, WORDS)
    assert not any(560 <= d.moment <= 600 for d in found)  # "Aldi Taher" only

def test_names_without_words_give_nothing() -> None:
    assert pick_discussions(parse_json3(CAPTIONS), SUBJECT, OTHERS, []) == []

def test_words_alone_work_without_people() -> None:  # Review Focus 1
    assert isinstance(pick_discussions(parse_json3(CAPTIONS), [], [], WORDS), list)

def test_said_holds_the_window_lines() -> None:
    d = next(d for d in pick_discussions(parse_json3(CAPTIONS), SUBJECT, OTHERS, WORDS)
             if 240 <= d.moment <= 300)
    text = " ".join(str(line["text"]) for line in d.said)
    assert "pedang" in text.lower() and len(text) <= 1500
    assert all(float(line["end_seconds"]) >= float(line["start_seconds"]) for line in d.said)
```

- [ ] **Step 2: Run; expect FAIL** (`pick_discussions` missing).
  Run: `make test T=tests/footage/test_moments.py`

- [ ] **Step 3: Implement `pick_discussions`.**
  - **Windows:** each window starts at a line past `INTRO_SECONDS` and holds the lines whose
    start is in `[start, start + 60)`. Matching uses `norm()` and the existing `_says`.
  - **Window score:** 2 per line naming a subject, plus 1 per line naming another person, plus 1
    per distinct word said in the window. Keep the window when the score is at least 4 and at
    least 2 distinct words are said.
  - **Choosing windows:** best score first, the earlier window on a tie. A window is skipped when
    it overlaps a kept one, which keeps kept windows at least 60 s apart.
  - **Moment:** the start of the window's best line, scored 2 per subject, 1 per other person and
    1 per word on that line. The earliest wins a tie.
  - **said:** the window's lines. Each line's `end_seconds` is the next line's start, and the last
    line gets `start + 3`. Stop adding lines before the joined text passes 1,500 characters.

- [ ] **Step 4: Run; expect PASS** (including `test_a_section_is_eight_seconds_from_a_second_before`).

- [ ] **Step 5: Commit** — `feat(footage): pick podcast moments by discussion density`

### Task 3: Storage — `said` and dropping a library row

**Files:**
- Create: `python/migrations/editor/0034_footage_said.sql`,
  `python/migrations/editor/alembic/versions/0034_footage_said.py` (copy of 0033's shim, revision
  "0034", down "0033")
- Modify: `python/src/thoth_control_plane/infrastructure/footage_models.py`,
  `infrastructure/footage_store.py`, `footage/models.py`, `footage/ports.py`
- Test: `python/tests/footage/test_store_postgres.py`,
  `python/tests/operations/test_editor_migrations_postgres.py`

**Interfaces:**
- Produces:
  - `NewCandidate.said`, `CandidateView.said` (last field, default empty) and `LibraryClip.said`,
    each `list[dict[str, Any]]` with default `[]`;
  - `FootageStore.drop_library(workspace_id: str, workflow_id: str, url: str) -> None`, which
    deletes only rows with that url whose `first_workflow_id == workflow_id`. It is added to the
    port Protocol.

- [ ] **Step 1: Write the failing tests**
  - `test_said_round_trips_on_a_candidate`: `add_candidates` with
    `said=[{"text": "pedang", "start_seconds": 1.0, "end_seconds": 2.0}]`, then
    `candidates()[0].said` equals it.
  - `test_said_round_trips_on_a_library_clip`: via `add_library` then `library(...)`.
  - `test_odd_stored_said_reads_as_empty`: write `{"x": 1}` into the column with raw SQL; the
    view's `said == []` (Review Focus 5).
  - `test_drop_library_keeps_an_earlier_runs_row` (Review Focus 4): a row first written by
    `wf_a` survives `drop_library(ws, "wf_b", url)`, and a row first written by `wf_b` is gone.
  - In the migration tests, the counts become 34, 28 and 21. The "before" copy also unlinks both
    0034 files.

- [ ] **Step 2: Run; expect FAIL.** Run: `make test-postgres`

- [ ] **Step 3: Implement.**
  - The SQL: `ALTER TABLE footage_candidates ADD COLUMN said JSONB NOT NULL DEFAULT '[]'::jsonb;`
    plus the same for `footage_library`.
  - ORM: `said: Mapped[list[Any]] = mapped_column(JSON, default=list)` on both rows.
  - `_view` and `_library_clip`: `said = value if isinstance(value, list) else []`.
  - `add_candidates`, `add_library` and the library merge write `said`. The earlier copy wins on a
    merge, as today.

- [ ] **Step 4: Run; expect PASS.** Also run `make test T=tests/footage` (the fakes in
  `test_service.py` gain `drop_library`).

- [ ] **Step 5: Commit** — `feat(footage): store what a footage section says`

### Task 4: Sections use discussions and keep `said`

**Files:**
- Modify: `python/src/thoth_control_plane/footage/service.py` (`_sections`, `_from_library`,
  `_remember`)
- Test: `python/tests/footage/test_service.py`

**Interfaces:**
- Consumes:
  - Task 1: `subject_names` and `ContextCard.spoken`;
  - Task 2: `pick_discussions` and `Discussion`;
  - Task 3: the `said` fields.
- `_sections` calls `pick_discussions(lines, subject_names(card), [n for n in card_names(card) if
  n not in subject], [*card.spoken, *event_terms(card)])`. Each section's `NewCandidate` carries
  `said=discussion.said`.

- [ ] **Step 1: Write the failing tests** (existing fakes `Captions`, `Cards`, `_run_a`)
  - `test_a_section_keeps_what_is_said_around_it`: a card with `spoken=["pedang", "uss"]` and
    `people[0]` named "Mutant" with alias "mutan". The section candidate's `said` text contains
    "pedang".
  - `test_a_long_video_naming_only_a_person_gives_no_section`: captions naming the card's second
    person, with no spoken words. The video is rejected `duration`, and there are no section rows.
  - `test_a_library_clip_brings_its_said`: a `LibraryClip` with `said` is reused, and the
    candidate row has that `said`. `_remember` writes the admitted candidate's `said` to the
    library.
  - Existing section tests whose cards have no `spoken` get `spoken` words in their fixture card.
    That is a ruling (spec 9.3), not a weakened assertion.

- [ ] **Step 2: Run; expect FAIL.** Run: `make test T=tests/footage/test_service.py`

- [ ] **Step 3: Implement as the Interfaces block says.**

- [ ] **Step 4: Run; expect PASS.** Then run the replay test `tests/footage/test_replay.py`.

- [ ] **Step 5: Commit** — `feat(footage): cut sections where the incident is discussed`

### Task 5: One copy of a recording

**Files:**
- Modify: `python/src/thoth_control_plane/attribution/adapters/visual.py` (add `matrix`)
- Create: `python/src/thoth_control_plane/footage/recording.py`
- Modify: `footage/service.py` (`FootagePorts.matcher`, `_Build`, `_check`, `_verify_admitted`),
  `footage/ports.py`, `activities/footage.py` (wire `matcher=OrbMatcher(step=1)`)
- Test: `python/tests/footage/test_recording.py`, `python/tests/footage/test_service.py`

**Interfaces:**
- `OrbMatcher.matrix(a: list[Any], b: list[Any]) -> list[list[int]]`: inliers for every pair,
  rows of `a`, run in a thread.
- In `footage/recording.py`:
  - `MIN_INLIERS = 25`, `MIN_FRAMES = 3`, `ALIGNED_SHARE = 0.6`, `OFFSET_SLACK = 1`,
    `MIN_PEAK = 3.0`, `RECORDING_WIDTH = 480`;
  - `triggered(best: Sequence[int]) -> bool`;
  - `is_copy(matrix: Sequence[Sequence[int]]) -> bool`;
  - `text_share(frames: Sequence[Sequence[TextBox]]) -> float`: the mean over frames of the summed
    box area, `(bottom-top)*(right-left)`, capped at 1;
  - `CopyFacts` (frozen dataclass), with `url`, `original: bool`, `share: float` and
    `published_at: str | None`;
  - `keep_first(a: CopyFacts, b: CopyFacts) -> bool`.
- `FootagePorts.matcher: Any | None = None`.

- [ ] **Step 1: Write the failing unit tests** (`test_recording.py`)

```python
def test_a_copy_lines_up_in_time() -> None:
    m = [[40 if j == i + 2 else 3 for j in range(20)] for i in range(18)]
    assert is_copy(m)

def test_the_same_set_at_another_moment_is_no_copy() -> None:  # spike: 9/9 matched, 1.2x peak
    m = [[30 + (i * j) % 7 for j in range(9)] for i in range(9)]
    assert not is_copy(m)

def test_too_few_matched_frames_is_no_copy() -> None:
    assert not is_copy([[40, 0], [0, 0], [0, 0]])

def test_an_original_beats_a_cleaner_copy() -> None:
    assert keep_first(CopyFacts("a", True, 0.3, None), CopyFacts("b", False, 0.0, "2026-11-01"))

def test_the_cleaner_copy_wins_then_the_earlier() -> None:
    assert not keep_first(CopyFacts("a", False, 0.2, None), CopyFacts("b", False, 0.05, None))
    assert keep_first(CopyFacts("a", False, 0.1, "2026-11-01"), CopyFacts("b", False, 0.1, "2026-11-02"))
    assert not keep_first(CopyFacts("a", False, 0.1, None), CopyFacts("b", False, 0.1, "2026-11-02"))

def test_text_share_sums_boxes() -> None:
    box = TextBox(text="JawaPos", top=0.0, bottom=0.1, left=0.0, right=0.5)
    assert text_share([[box], []]) == pytest.approx(0.025)

def test_orb_finds_a_cropped_overlaid_copy() -> None:
    # A seeded random texture as a JPEG; the copy is cropped 10%, resized and has a filled text
    # band; a second seed is unrelated. Real OrbMatcher.prepare + matrix.
    assert max(max(row) for row in copy_matrix) >= 25
    assert max(max(row) for row in unrelated_matrix) < 25
```

- [ ] **Step 2: Run; expect FAIL.** Run: `make test T=tests/footage/test_recording.py`

- [ ] **Step 3: Implement `recording.py` and `OrbMatcher.matrix`.**
  - `is_copy`: take the rows whose max is 25 or more; there must be at least 3. Their offsets
    (argmax − row index) must share a mode with at least 60% within ±1. The median of `max / max(1,
    median(row))` must be at least 3.
  - `keep_first`: compare by the tuple `(not original, share, published_at or "9999")`. Ties keep
    `a`.

- [ ] **Step 4: Run; expect PASS.**

- [ ] **Step 5: Write the failing service tests.** The fake matcher's `prepare` returns the frames'
  jpeg bytes. `matrix` returns 40 on the diagonal when both clips' frame bytes start with the same
  recording tag, and 0 otherwise. The fake text reader returns boxes by tag.
  - `test_a_cleaner_copy_replaces_an_admitted_one`: copy A (`share` 0.2) is admitted first and
    copy B (0.05) is checked next. Then A is `rejected/duplicate` and B is admitted.
  - `test_the_loser_s_library_row_from_this_run_is_dropped`: the store fake records
    `drop_library(ws, wf, A.url)`.
  - `test_an_original_stays_over_a_cleaner_repost`.
  - `test_sections_of_one_video_are_not_compared`: two `#t=` sections of one URL with the same tag
    are both admitted.
  - `test_two_copies_checked_together_leave_one` (Review Focus 2): both are checked through
    `_together`, and exactly one is admitted.
  - `test_a_copy_of_the_main_is_rejected_duplicate`.
  - `test_a_photo_main_skips_the_main_comparison` (Review Focus 3): no error, and the clip is
    admitted.
  - `test_no_matcher_no_copy_check`: `matcher=None`, and both copies are admitted.

- [ ] **Step 6: Run; expect FAIL.**

- [ ] **Step 7: Implement in `service.py`.**
  - **State:** `_Build` gains `copy_lock: asyncio.Lock`, `main_recording: list[Any] | None`
    (prepared lazily once, from the main video at 1 frame per 2 s and 480 px, `[]` when there is no
    main video or its frames fail), and `recordings: dict[str, _Recording]`. A `_Recording` holds
    the url, source url, features at 1 fps, trigger features from 3 frames, `CopyFacts` and the
    hashes.
  - **Where the check goes:** in `_check`, after the dHash step and before `admit`, run the copy
    step under `copy_lock` through `admit`.
  - **Copy of the main:** if stage 1 against the main triggers and the 1 fps `is_copy` holds,
    reject `duplicate`.
  - **Other clips:** for each recording from another source url where stage 1 triggers and
    `is_copy` holds, compute `share` lazily with `self._ports.text.read` on the 3 vision frames.
    - If the existing clip is kept, reject the candidate `duplicate`.
    - Otherwise reject the existing clip `duplicate` through `store.reject`, call
      `drop_library(state.workspace, workflow, url)` when there is a workspace, remove it from
      `recordings` and from the admitted hashes, and continue.
  - **Original:** `candidate.source in ("creator", "trace")` or `is_own_account(owner_handle,
    card)`.
  - **On a retry:** `_verify_admitted` rebuilds `recordings` from the admitted files.

- [ ] **Step 8: Run; expect PASS.** Then run `make test T=tests/footage`.

- [ ] **Step 9: Commit** (two commits):
  - `feat(footage): recognise copies of one recording by time alignment`
  - `feat(footage): keep the original or the cleanest copy of a recording`

### Task 6: `said` into the Content Set and Studio materials

**Files:**
- Modify: `python/src/thoth_control_plane/assembly/models.py` (`Footage.said`),
  `assembly/service.py` (`_footage_item`), `assembly/studio.py` (`_footage` `why`),
  `domain/studio_imports.py` (`StudioMaterial.said`, `StudioMaterial.clip_start`)
- Test: `python/tests/assembly/test_service.py`,
  `python/tests/assembly/test_studio_projection.py`, and the materials test that builds
  `StudioMaterial` from provenance (`tests/application/test_workflow_studio_imports*.py`)

**Interfaces:**
- `Footage.said: list[TranscriptSegment] = []`. Invalid entries are dropped, not failed.
- `why["said"]` holds TranscriptSegment dumps, and `why["clip_start"]` holds `clip.clip_start`.
- `StudioMaterial.said: list[TranscriptSegment] = []` and `StudioMaterial.clip_start: float |
  None = None`.

- [ ] **Step 1: Write the failing tests:**
  - an admitted view with `said` becomes `Footage.said`;
  - a view whose `said` holds a bad entry keeps the good ones;
  - the projection's footage `why` holds `said` and `clip_start`;
  - `materials()` returns `said` and `clip_start` for a footage item;
  - a main item still has `said == []`.

- [ ] **Step 2: Run; expect FAIL.** Run:
  `make test T="tests/assembly/test_service.py tests/assembly/test_studio_projection.py"`

- [ ] **Step 3: Implement as the Interfaces block says.**

- [ ] **Step 4: Run; expect PASS.**

- [ ] **Step 5: Commit** — `feat(assembly): carry footage speech into the draft materials`

### Task 7: Narration uses footage talk

**Files:**
- Modify: `python/src/thoth_control_plane/application/narration_script.py`
- Test: `python/tests/application/test_narration_script.py`

**Interfaces:**
- `FootageTalk(StrictModel)`, with `label: str` and `text: str`.
- `ScriptFacts.footage_talk: list[FootageTalk] = []`.
- `facts_from_materials` fills `footage_talk` from items with role `footage` or `creator_footage`
  and a non-empty `said`. The label is `credit_label(item.platform, item.owner_handle)` or
  `item.label`. The text is the joined `said` text, cleaned to 1,500 characters.

- [ ] **Step 1: Write the failing tests:**
  - `test_footage_talk_is_sent_with_its_source`: the user message holds "What people say in other
    videos (auto-captions, may be misheard):" and "- from YouTube/CURHAT BANG: … pedang …".
  - `test_the_system_prompt_says_to_attribute_footage_talk`: `SOURCE_RULES` names other videos and
    who said it.
  - `test_footage_talk_counts_as_evidence`: a script word found only in footage talk is not in
    `unsupported_tokens`.
  - `test_materials_without_said_give_no_footage_talk`.

- [ ] **Step 2: Run; expect FAIL.** Run: `make test T=tests/application/test_narration_script.py`

- [ ] **Step 3: Implement.**
  - The block goes after the transcript line.
  - The `SOURCE_RULES` sentence: "What people say in other videos is what they said there (a
    podcast, an interview): say who said it and where, never present it as said in the main video
    or as fact."
  - `_evidence` adds the `footage_talk` texts.

- [ ] **Step 4: Run; expect PASS.** Then run `tests/activities/test_narration_activities.py`.

- [ ] **Step 5: Commit** — `feat(narration): draw on what footage videos say`

### Task 8: The planner places footage talk

**Files:**
- Modify: `python/src/thoth_control_plane/assembly/planner_service.py`,
  `assembly/adapters/planner_model.py` (`SYSTEM_PROMPT`)
- Test: `python/tests/assembly/test_planner_service.py`, `python/tests/assembly/test_planner_model.py`

**Interfaces:**
- Footage shots get `said=shot_speech(material.said, clip_start + start, clip_start + end)`.
  `material` is the footage item for that asset, and `clip_start` defaults to 0.
- The sources header is "WHAT EACH VIDEO SAYS DURING EACH SHOT:".

- [ ] **Step 1: Write the failing tests:**
  - A footage shot whose source span covers a `said` line gets that text, and a shot outside it
    gets `""`.
  - The sources list holds the new header.
  - `soundbite()` still looks only at main shots (existing test unchanged).
  - `SYSTEM_PROMPT` holds both new rules: retelling footage speech takes that video's shots, and a
    same-scene clip from another angle only for phrases about that moment.

- [ ] **Step 2: Run; expect FAIL.**
  Run: `make test T="tests/assembly/test_planner_service.py tests/assembly/test_planner_model.py"`

- [ ] **Step 3: Implement.** Add rules 10 and 11, and change rule 1's block name to the new
  header's main-video lines.

- [ ] **Step 4: Run; expect PASS.**

- [ ] **Step 5: Commit** — `feat(planner): place footage speech on its video's shots`

### Task 9: Verify and record

- [ ] `make test`, `make lint` and `make test-postgres`, all green; read the output tails.
- [ ] Update the checkpoint `.superpowers/sdd/2026-11-12-footage-library/progress.md`.
- [ ] Append a `CHANGELOG.md` entry "2026-11-16 - Footage revision after the first live look"
  with the spike evidence (items 62 and 64), the rulings, and Next steps:
  - push and deploy the branch image;
  - one live footage run on the Mutant post;
  - one paid narration write, with its cost shown first;
  - the merge of PR #133.
- [ ] Commit — `docs: record the footage revision`
- [ ] Final whole-branch review (executing-plans), fixes RED→GREEN, and the report with Next steps.

# Footage Related Events Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Footage favours the card's people in *other* related events. A run may keep at most one clean original of the main's own incident, and it holds up to 8 clips.

**Architecture:**
- **Card:** gains `related` events and their queries. The refine round always runs once.
- **Text gate:** a name matches in its hashtag form and with the "nya" suffix. A clip that names a person gets a 2-year window.
- **Vision call:** the same single call also answers `same_event` against the main's scene.
- **Relation:** stored on candidates and library rows (`related` / `same_event` / `unknown`). The admit step caps `same_event` at one clean original.
- **Downloads:** media failures log their cause.

**Tech Stack:** Python 3.12, pydantic, SQLAlchemy and Alembic over editor SQL migrations, pytest (`make test` in WSL), ruff (`make lint`).

**Spec:** `docs/superpowers/specs/2026-11-15-footage-library-design.md`, section 10 (approved 2026-11-16, "ya sesuai"). The brainstorm record is `.superpowers/sdd/2026-11-12-footage-library/brainstorm-notes.md`, items 66-70.

## Global Constraints

- Repository text is English. Commits use one `git commit -m` with a Conventional Commits prefix and a subject of at most 72 characters, with no body and no AI attribution.
- New schema and payload fields get a default. Stored rows and older images must still decode.
- **Graceful degradation:**
  - with no card (the object path), `relation` stays `unknown`, and there is neither a same-event check nor a cap;
  - with no copy-check ports, a clip's text share counts as 0.
- `MAX_FOOTAGE = 8`. `PER_QUERY = 2` and the `SECTIONS` queue are unchanged.
- At most 1 `same_event` clip per run. It must be an original (`source` in `ORIGINAL_SOURCES`, or an own account) whose text share is at most `CLEAN_SHARE = 0.15`. Any other same-event clip is rejected with the new reason `same_event`.
- A person-naming candidate may be published up to `PERSON_WINDOW = timedelta(days=730)` before the main post. One matched only by event words keeps `WINDOW_BEFORE` (30 days).
- At most 2 incident queries (`INCIDENT_QUERIES = 2`) and at most 6 related queries (`MAX_RELATED = 6`) per card.
- No new paid call. `same_event` rides on the existing vision call, and the refine round is the existing card call.
- Always check `make lint`'s exit code explicitly. Use `make test T=<path>` while iterating, and the full `make test` at the end.

## Review Focus

1. **A same-event clip with no card** (the object path). Expected: no `same_event` question asked, `relation` stays `unknown`, and nothing is capped. Covered in Task 3: `test_no_card_asks_no_scene`.
2. **A second clean original of the incident arrives after the first.** The 9.4 order (`keep_first`) decides. The loser is rejected `same_event`, and the quota count drops. Covered in Task 4: `test_a_cleaner_same_event_original_takes_the_slot`.
3. **A library row stored before 0035** (`relation = 'unknown'`). Expected: not reused. Covered in Task 5: `test_library_reuses_only_related_clips`.
4. **A person's name inside a longer word that is not the "nya" form.** For example "Mutant" inside "mutantsquad" must not match, while "mutannya" must match "mutan". Covered in Task 2: `test_names_match_hashtag_and_nya_forms_only`.
5. **A refined card whose model call fails.** Expected: the run goes on with round one's card, and it is marked refined so the round is not retried. Covered in Task 1: `test_refine_runs_even_when_round_one_filled_the_quota`, together with the existing failure test.

---

### Task 1: Card with related events; refine always runs

**Files:**
- Modify: `python/src/thoth_control_plane/footage/context.py` (CARD_PROMPT, REFINE_PROMPT, `ContextCard`, `context_objects`)
- Modify: `python/src/thoth_control_plane/footage/service.py` (`_start_context`, `_rounds`, constants)
- Test: `python/tests/footage/test_context.py`, `python/tests/footage/test_service.py`
- Fixture: `python/tests/fixtures/footage/context/mutant_card.json` gains `related`.

**Interfaces:**
- Produces:
  - `class RelatedEvent(StrictModel)` with `event: str = ""` and `query: str = ""`, using lenient config like `CardPerson`;
  - `ContextCard.related: list[RelatedEvent]`, with a default of `[]`, entries without a query dropped, and at most `MAX_RELATED = 6`;
  - `context_objects(card, queries, related=())` and `card_objects(card) -> list[FootageObject]`. `card_objects` returns `card.queries[:INCIDENT_QUERIES]` through `context_objects`, followed by one object per related event (see Step 3).

- [ ] **Step 1: Write the failing tests**

```python
# test_context.py
def test_the_card_reads_related_events() -> None:
    card = ContextCard.model_validate({"people": [{"name": "Mutant"}], "related": [
        {"event": "Mutant at a medical check-up on Sekolah Normal", "query": "Mutant Sekolah Normal"},
        {"event": "no query"}, "junk"]})
    assert [r.query for r in card.related] == ["Mutant Sekolah Normal"]

def test_card_objects_take_two_incident_queries_and_the_related_ones() -> None:
    card = _mutant(queries=["a USS", "b USS", "c USS"], related=[
        {"event": "Saiful's clarification with Gofar Hilman", "query": "Saiful klarifikasi Gofar"}])
    objects = card_objects(card)
    assert [o.query for o in objects] == ["a USS", "b USS", "Saiful klarifikasi Gofar"]
    assert objects[-1].visual == "Saiful's clarification with Gofar Hilman"

def test_a_person_query_visual_no_longer_names_the_incident() -> None:
    (obj,) = context_objects(_mutant(), ["Mutant bawa pedang"])
    assert obj.visual == "Mutant in person" and obj.person
```

```python
# test_service.py
async def test_refine_runs_even_when_round_one_filled_the_quota(store, tmp_path) -> None:
    # 8 passing hits in round one; the refine model is still asked once.
    cards = Cards(_card(), refined=_card())
    await _builder(store, search=Search(_hits(*[_video(n, caption=SHOWN) for n in range(8)],
                   query="Mutant USS Denny Sumargo")), card=cards, context_enabled=True
                   ).build(_inputs(tmp_path))
    assert len(cards.calls) == 2
```

`_mutant(**overrides)` is a small local helper in `test_context.py` that builds a card with `people[0]` named "Mutant". Add it if no equivalent exists.

- [ ] **Step 2: Run them, and watch them fail**

Run: `make test T=tests/footage/test_context.py` and `make test T=tests/footage/test_service.py::test_refine_runs_even_when_round_one_filled_the_quota`
Expected: FAIL. `related` and `card_objects` are unknown, the visual still contains ", at ...", and the card is called once.

- [ ] **Step 3: Implement**

- **`context_objects`:**
  - a person query's visual becomes `f"{person name} in person"`;
  - a non-person query keeps `card.event or DEFAULT_VISUAL`;
  - a related event becomes `FootageObject(query=r.query[:100], visual=r.event or DEFAULT_VISUAL, person=<the query names a card person>)`.
- **`card_objects`** is used by `_start_context` in place of `card.queries[:FIRST_QUERIES]`. `FIRST_QUERIES` is removed.
- **`_rounds`:** drop the `passing >= MAX_FOOTAGE` condition. Keep the `stored.get(REFINED)` and `card is None` guards. The refined card's new objects are the fresh queries plus the fresh related queries (by `norm`), still limited to `REFINE_QUERIES` each.
- **CARD_PROMPT**, copy decided here:
  - the JSON shape gains `"related": [{"event": str, "query": str}]`;
  - the first sentence becomes "...write a context card used to find footage of this story's people and context on YouTube, TikTok and X";
  - the rules add: "aliases include real names, other spellings, and the hashtag form of each name (no spaces, lowercase)";
  - queries: "queries: at most 2 short searches about this incident";
  - related: "related: up to 6 OTHER events these people are known for or that followed (their shows, a clarification, an apology, a reply, a meeting), each with one short search as Indonesian viewers would type it; never this incident itself".
- **REFINE_PROMPT** adds: "you may add related events the titles show (same shape as the card's related)".

- [ ] **Step 4: Run, and watch them pass**

Run: `make test T=tests/footage`
Expected: PASS. Fix any existing test whose visual assertion pinned ", at <event>", but only where the spec changes it (spec 10.5).

- [ ] **Step 5: Commit**

`git commit -m "feat(footage): add related events to the card and always refine"`

---

### Task 2: Name forms and the person window

**Files:**
- Modify: `python/src/thoth_control_plane/footage/context.py` (`_says` users, `context_reason`, `in_window`, a new `names_person`)
- Modify: `python/src/thoth_control_plane/footage/service.py` (`_off_story`)
- Test: `python/tests/footage/test_context.py`

**Interfaces:**
- Produces:
  - `mentions(text: str, name: str) -> bool`, where `text` and `name` are already `norm`-ed. It is true when the text says `name`, or `name` without spaces, or `name + "nya"` (also without spaces), each as whole words;
  - `names_person(text: str, card: ContextCard) -> bool`;
  - `in_window(published_at, main_published, now, before: timedelta = WINDOW_BEFORE)`;
  - `PERSON_WINDOW = timedelta(days=730)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_names_match_hashtag_and_nya_forms_only() -> None:
    assert mentions(norm("#sekolahnormal #mutan #tretanmuslim"), "tretan muslim")
    assert mentions(norm("Klarifikasi Muslim soal mutannya Saiful"), "mutan")
    assert not mentions(norm("#mutantsquad"), "mutant")

def test_a_person_clip_may_be_two_years_old() -> None:
    card = _mutant(aliases=["Saiful"])
    now = datetime(2026, 11, 16, tzinfo=UTC)
    old = "2024-12-11T08:24:00Z"
    assert names_person(norm("Mutant diajarin acting Jefri nichol"), card)
    assert in_window(old, "2026-11-08T00:00:00Z", now, before=PERSON_WINDOW)
    assert not in_window(old, "2026-11-08T00:00:00Z", now)
```

```python
# test_service.py: the gate end to end
async def test_older_person_clips_pass_the_story_gate(store, tmp_path) -> None:
    old = _video(1, caption="Mutant diajarin acting Jefri nichol")
    old = old.model_copy(update={"published_at": "2024-12-11T08:24:00Z"})
    unnamed = _video(2, caption="Urban Sneaker Society USS 2024 recap").model_copy(
        update={"published_at": "2024-12-11T08:24:00Z"})
    await _builder(store, search=Search(_hits(old, unnamed, query="Mutant USS Denny Sumargo")),
                   card=Cards(_card()), context_enabled=True).build(_inputs(tmp_path))
    rows = {c.url: c for c in store.candidates("wf_a")}
    assert rows[str(old.canonical_url)].reason != "story"
    assert rows[str(unnamed.canonical_url)].reason == "story"
```

Adjust `published_at` to the field `DiscoveredVideo` actually has, and the fixture's main date if needed.

- [ ] **Step 2: Run, and watch them fail.** `make test T=tests/footage/test_context.py`. Expected: FAIL, because the names are unknown and the window has no `before` parameter.

- [ ] **Step 3: Implement**
  - `context_reason` and `names_person` use `mentions` over `card_names(card)`.
  - `_off_story(text, published_at, main, card)` becomes:
    - named → `not in_window(..., before=PERSON_WINDOW)`;
    - otherwise → `not in_window(...)` or fewer than 2 event terms.

- [ ] **Step 4: Run, and watch them pass.** Run `make test T=tests/footage`.

- [ ] **Step 5: Commit.** `git commit -m "feat(footage): match name forms and keep older person clips"`

---

### Task 3: The vision call answers `same_event`; sections may talk

**Files:**
- Modify: `python/src/thoth_control_plane/footage/adapters/vision.py`
- Modify: `python/src/thoth_control_plane/footage/service.py` (`_check` vision step, `_sections` visual)
- Test: `python/tests/footage/test_vision_adapter.py` (or wherever `FootageAnswer` is tested; `grep -rl FOOTAGE_PROMPT tests`), and `python/tests/footage/test_service.py`

**Interfaces:**
- Produces:
  - `FootageAnswer.same_event: Literal["yes", "no"] = "no"`;
  - `AgnoFootageJudge.judge(frames, visual, *, person=False, scene: str | None = None)`. When `scene` is set, the prompt adds `'same_event: do the frames show this same scene: "{scene}"? Answer yes or no. '`, so the questions become four;
  - `relation_of(answer: FootageAnswer, asked: bool) -> Literal["related", "same_event", "unknown"]`, a module function in `service.py`. With `asked` false it returns `unknown`;
  - the scene passed is `" ".join(f"{card.event}, at {card.place}".split())[:300]`, and only when `state.card is not None`.
- The test `Judge` fake gains `scene: str | None = None` and records it. It answers `same_event` from a `scenes: dict[str, str]` keyed by the candidate's visual, defaulting to `"no"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_scene_question_is_asked_only_with_a_scene() -> None:
    assert "same_event" not in FOOTAGE_PROMPT
    # judge(...) with scene: the prompt sent to _run contains the scene text and "same_event"

async def test_no_card_asks_no_scene(store, tmp_path) -> None:  # Review Focus 1
    judge = Judge()
    await _builder(store, search=Search(_hits(_video(1))), judge=judge).build(_inputs(tmp_path))
    assert judge.scenes_seen == [None]
    assert store.admitted("wf_a")[0].relation == "unknown"

async def test_a_section_talking_is_kept(store, tmp_path) -> None:
    judge = Judge(default=FootageAnswer(kind="commentary", shows_object="yes"))
    await _builder(store, search=_yt("Mutant USS Denny Sumargo", _podcast()), judge=judge,
                   downloader=WindowDownloader(), card=Cards(_card()),
                   captions_text=Captions(CAPTIONS), context_enabled=True).build(_inputs(tmp_path))
    sections = [c for c in store.candidates("wf_a") if c.source == "section"]
    assert sections and all(c.reason != "commentary" for c in sections)
    assert all(c.visual.endswith(" in person") for c in sections)
```

`relation` on `CandidateView` arrives in Task 5. Until then, assert `relation` through `AdmittedClip`, or move the `relation` assertion into Task 5's tests and record that as a ruling.

- [ ] **Step 2: Run, and watch them fail.**
- [ ] **Step 3: Implement.**
  - `_check` passes `scene` and computes `relation = relation_of(answer, scene is not None)`. The commentary reject is skipped for `candidate.source == "section"`.
  - In `_sections`, rows get `visual=f"{people[0] name} in person"` and `person=True`. They are judged with `PERSON_PROMPT` (`person` is passed from `quota_key`/candidate source in `_check_all`: `c.query in people or c.source == "section"`).
- [ ] **Step 4: Run, and watch them pass.** Run `make test T=tests/footage`.
- [ ] **Step 5: Commit.** `git commit -m "feat(footage): ask the vision call whether a clip is the main's scene"`

---

### Task 4: One clean same-event clip; eight in total

**Files:**
- Modify: `python/src/thoth_control_plane/footage/models.py` (`RejectReason` + `"same_event"`)
- Modify: `python/src/thoth_control_plane/footage/service.py` (`MAX_FOOTAGE = 8`, `CLEAN_SHARE = 0.15`, `_Build.same_event: _Recording | str | None`, the admit step, `_displace(..., reason)`)
- Test: `python/tests/footage/test_service.py`

**Interfaces:**
- Consumes: `relation_of` from Task 3; `CopyFacts`, `keep_first` and `ORIGINAL_SOURCES` (from 9.4).
- Produces:
  - `clean_original(facts: CopyFacts) -> bool` in `footage/recording.py`, meaning `facts.original and facts.share <= CLEAN_SHARE`;
  - `_displace(workflow, other, admitted_hashes, state, reason: RejectReason = "duplicate")`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_only_one_clean_original_of_the_incident_is_kept(store, tmp_path) -> None:
    # creator original (clean) + two search recaps, all judged same_event
    ...
    reasons = Counter(c.reason for c in store.candidates("wf_a") if c.status == "rejected")
    assert reasons["same_event"] == 2
    kept = [c for c in store.admitted("wf_a") if c.relation == "same_event"]
    assert [c.source for c in kept] == ["creator"]

async def test_a_same_event_repost_is_rejected_even_when_the_slot_is_free(store, tmp_path) -> None:
    # one search recap judged same_event, no original: rejected same_event, nothing kept
    ...

async def test_a_cleaner_same_event_original_takes_the_slot(store, tmp_path) -> None:  # RF 2
    # two originals, the second with a lower text share: the first is rejected same_event,
    # the total admitted stays consistent (quota counter drained like `displaced`)
    ...

async def test_quota_two_per_query_eight_in_total(store, tmp_path) -> None:
    # the old six-in-total test, now with 5 queries x 3 videos: admitted == 8
    ...
```

Rename `test_quota_two_per_query_six_in_total` to the eight version. Spec 10.6 changes the value; this is not a weakening.

- [ ] **Step 2: Run, and watch them fail.**
- [ ] **Step 3: Implement**
  - Inside `copy_lock`, after `_losers` and before the admit:
    - **For `relation == "same_event"`:**
      - facts = `evidence.facts`, or `CopyFacts(url, original, 0.0, published_at)` when there is no evidence;
      - if not `clean_original(facts)`, reject `same_event`;
      - if the slot is held by a kept clip that `keep_first(held.facts, facts)` keeps, reject `same_event`;
      - otherwise, after the admit lands, displace the holder with reason `same_event` and take the slot.
    - **For `related` or `unknown`:** nothing changes.
  - The displaced query drains through `state.displaced`, as in 9.4.
- [ ] **Step 4: Run, and watch them pass.** Run `make test T=tests/footage`.
- [ ] **Step 5: Commit.** `git commit -m "feat(footage): keep one clean same-event clip in eight"`

---

### Task 5: Store the relation; reuse only related library clips

**Files:**
- Create: `python/migrations/editor/0035_footage_relation.sql` and `python/migrations/editor/alembic/versions/0035_footage_relation.py` (revision "0035", down "0034"), modelled on 0034.
- Modify:
  - `python/src/thoth_control_plane/footage/models.py` (`AdmittedClip.relation`, `CandidateView.relation`, `LibraryClip.relation`, each `str = "unknown"`);
  - `python/src/thoth_control_plane/infrastructure/footage_models.py`;
  - `python/src/thoth_control_plane/infrastructure/footage_store.py` (admit, candidates, add_library, library).
- Modify: `python/src/thoth_control_plane/footage/service.py`:
  - `AdmittedClip(relation=...)`;
  - `_remember` writes `relation`;
  - `_from_library` keeps only `clip.relation == "related"`.
- Test:
  - `python/tests/footage/test_store_postgres.py`;
  - `python/tests/footage/test_service.py`;
  - `python/tests/operations/test_editor_migrations_postgres.py` (counts move from 34 to 35, and the "before" state also unlinks 0035);
  - `python/tests/operations/test_editor_migrations.py` (0035 in the file list).

**SQL** (copy fixed here):

```sql
-- Footage related events (2026-11-16, spec 10.3/10.7): how a kept clip relates to the main's
-- incident, and the reason a second same-event clip is rejected. Rollback: images before 0035
-- never read the column nor write the reason; both may stay.
ALTER TABLE footage_candidates ADD COLUMN relation TEXT NOT NULL DEFAULT 'unknown'
    CHECK (relation IN ('related', 'same_event', 'unknown'));
ALTER TABLE footage_library ADD COLUMN relation TEXT NOT NULL DEFAULT 'unknown'
    CHECK (relation IN ('related', 'same_event', 'unknown'));
ALTER TABLE footage_candidates
    DROP CONSTRAINT footage_candidates_reason_check,
    ADD CONSTRAINT footage_candidates_reason_check CHECK (reason IN (
        'main', 'aggregator', 'spam', 'reaction_text', 'duration', 'story', 'subtitle',
        'commentary', 'object_absent', 'duplicate', 'media_failed', 'vision_unavailable', 'repost',
        'same_event'
    ));
```

- [ ] **Step 1: Write the failing tests**
  - `test_relation_round_trips_on_candidates_and_library`: postgres. Admit with `relation="related"` and read it back. An old row reads `unknown`.
  - `test_library_reuses_only_related_clips`: three library rows, `related`, `same_event` and `unknown`. Only the related one is admitted with source `library`. This is Review Focus 3.
  - The migration count tests are moved to 35.
- [ ] **Step 2: Run, and watch them fail.** Run `make test T=tests/footage` and `make test-postgres`.
- [ ] **Step 3: Implement**, as listed under Files.
- [ ] **Step 4: Run, and watch them pass.** Run `make test T=tests/footage`, `make test T=tests/operations` and `make test-postgres`.
- [ ] **Step 5: Commit.** Two commits: `feat(footage): store how a clip relates to the incident` and `test: list editor migration 0035`, if the file-list test is separate.

---

### Task 6: Media failures say why

**Files:**
- Modify: `python/src/thoth_control_plane/footage/service.py` (the `ClipError`, `FrameError`/`DurationError` and `MEDIA_FAILURES` rejects; `_Build.media_causes: Counter[str]`; the "footage finished" log)
- Test: `python/tests/footage/test_service.py`

- [ ] **Step 1: Write the failing test**

```python
async def test_a_media_failure_logs_its_cause(store, tmp_path, caplog) -> None:
    downloader = Downloader(fail={str(_video(1).canonical_url): ClipError("TimeoutError")})
    with caplog.at_level("WARNING"):
        await _builder(store, search=Search(_hits(_video(1))), downloader=downloader
                       ).build(_inputs(tmp_path))
    assert "footage media failed cause=ClipError(TimeoutError)" in caplog.text
    assert "tiktok.com" not in caplog.text.split("cause=")[1]
    assert "media_causes={'ClipError(TimeoutError)': 1}" in caplog.text
```

Adapt this to the existing `Downloader` fake's failure hook.

- [ ] **Step 2: Run, and watch it fail.**
- [ ] **Step 3: Implement.** There is one `logger.warning("footage media failed cause=%s", cause)` per reject, where `cause` is `f"{type(error).__name__}({error})"` for `ClipError`, the error code for a `MEDIA_FAILURES` code, and the class name otherwise. The causes are counted in `state.media_causes`, and the finished line appends `media_causes=%s`.
- [ ] **Step 4: Run, and watch it pass. Then run the full verification:** `make test`, `make test-postgres` and `make lint` (`echo lint=$?`).
- [ ] **Step 5: Commit.** `git commit -m "feat(footage): log why a clip's media failed"`

---

### After the tasks

- A final whole-branch review by a fresh reviewer (executing-plans). Critical and Important findings are fixed test-first, and minors are deferred.
- **Records:**
  - a CHANGELOG entry "2026-11-16 - Footage related events", with Next steps;
  - the checkpoint;
  - brainstorm notes.
- **Gates**, each needing its own authorization:
  1. push and CI;
  2. deploy (migration 0035);
  3. a new Mutant run judged by the operator;
  4. one paid narration;
  5. merge PR #133.

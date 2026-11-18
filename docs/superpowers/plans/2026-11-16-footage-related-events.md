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

---

## Amendments for spec 10.12 (the subject by text and by face)

Spec 10.12 amends Tasks 2-5 and adds Tasks 7-10. Where this section differs from the tasks above, it wins. Order: Tasks 1, 2 (amended), 3 (amended), 4, 5 (amended), 6, 7, 8, 9, 10.

### Global Constraints, added

- **The text gate** (revisions 1 and 5):
  - a candidate that names the subject (`people[0]`: its name, aliases, hashtag form or "nya" form) may be up to 730 days older than the main post;
  - one that matches only by event words keeps 30 days;
  - one that names only other card people is rejected `story`;
  - at most `MAX_OLD = 2` admitted clips per run are older than 30 days. Further ones are rejected `too_old`.
- **The vision prompt carries no person's name.** `same_event` is judged against one frame of the main, sent as the first image.
- **Face models:**
  - **YuNet** `face_detection_yunet_2023mar.onnx`, from `https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx`, sha256 `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`;
  - **ArcFace r50**, from Hugging Face `immich-app/buffalo_l` at revision `381829d83a41c0d0e03d0c5b9a4f6ddcaf5d6855`, file `recognition/model.onnx`, sha256 `4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43`;
  - both are baked into `/opt/thoth/models/faces/{yunet,arcface}.onnx`. A missing file raises; it is never skipped.
- **Face numbers:**

  | Constant | Value |
  |---|---|
  | `FACE_FPS` | 1.0 |
  | `MIN_FACE` | 40 px |
  | `DETECT_SCORE` | 0.8 |
  | `GROUP_LINK` | 0.25 (average linkage) |
  | `MIN_SECONDS` | 3 |
  | `CLEAR_RATIO` | 1.5 |
  | `MAX_CHOICES` | 4 |
  | `TEMPLATE_SIZE` | 16 (members evenly spaced by time) |
  | `TOP_K` | 5 |
  | `MATCH` | 0.42 |
  | `MATCH_SECONDS` | 2 |
  | `MAX_DISCUSSES` | 1 |

  - **Embedding:** YuNet-aligned 112 px crop, `blobFromImage(crop, 1/127.5, (112,112), (127.5,)*3, swapRB=True)`, L2-normalised.
- **Relations:** `related`, `same_event`, `discusses` and `unknown`. New reject reasons: `same_event`, `subject_absent` and `too_old`.
- **The subject template crosses activities inside the workflow,** with no new table:
  - members are float16, base64-encoded;
  - face crops are 96 px JPEG, base64-encoded.

### Review Focus, added

6. **No main faces at all** (a screen recording). Expected:
   - no stop, and the face check is off;
   - every clip keeps its 10.3 relation, and `discusses` is never set.

   Covered in Task 9: `test_no_main_faces_turn_the_face_check_off`.
7. **The operator answers "none of these".** Expected: footage runs with the face check off, and the workflow does not fail. Covered in Task 8: `test_rejecting_every_face_runs_footage_without_the_check`.
8. **A cancel during the subject stop.** Expected: the run is cancelled, and footage never starts. Covered in Task 8: `test_cancel_while_choosing_the_subject`.
9. **A same-event clip without the subject's face.** Expected: rejected `subject_absent`, and it does not take the `discusses` slot. Covered in Task 9: `test_a_same_event_clip_needs_the_subject`.
10. **A workflow history from before the subject stage** (replay). Expected: no `find_subject` activity, and footage runs as before. Covered in Task 8 by `workflow.patched(SUBJECT_PATCH)` and the replay test pattern the module already uses.

### Task 2, amended

- **Produces in addition:**
  - `subject_names(card) -> list[str]`: `people[0]`'s name plus its aliases, `norm`-ed;
  - `names_subject(text, card) -> bool`;
  - `names_person` stays and is used only to tell "names another person" apart.
- **`_off_story`:**
  - names the subject → `not in_window(..., before=PERSON_WINDOW)`;
  - names only another person → off story;
  - otherwise → the 30-day window and the event-term rule, as before.
- **Tests in addition:**
  - `test_a_clip_naming_only_another_person_is_off_story`: a "Denny Sumargo podcast" caption with no subject name → `story`;
  - in `test_older_person_clips_pass_the_story_gate`, the old clip names "Mutant", the subject.
- **Long-video sections:** `_sections` keeps only caption moments whose text `names_subject`. Test: `test_sections_are_cut_only_where_the_subject_is_named`, a podcast caption track with one cue naming "Saiful" and a denser one naming nobody. Only the named moment is cut.

### Task 3, amended

- `AgnoFootageJudge.judge(frames, visual, *, person=False, reference: Frame | None = None)` replaces the `scene` parameter.
  - When `reference` is set, it is sent as the first image, and the prompt adds: `'same_event: the first image is from another video; do the other frames show that same scene and moment? Answer yes or no. '`.
- **The prompts drop names:**
  - **`PERSON_PROMPT`'s kind rule** reads "the video showing a real person themself speaking or acting on camera (at an event, a press conference, a visit, or an interview they give) is footage; a news anchor, a slideshow, still photos, or a reaction is commentary";
  - **`shows_object` for a person query** asks `"is a real person on screen (not a photo, a graphic, or a slideshow)?"`.
- **Visuals:**
  - a person query's `visual` is `"a person on camera"`;
  - a related event's `visual` is its event text with the card names removed (`strip_names(text, card)`, which replaces each card name and alias with "a person");
  - a section's `visual` is `"a person on camera"`.
- **The reference frame** is the main's middle frame at `VISION_WIDTH`, read once per run into `_Build.reference`. With no card, it is `None`, so no same-event question is asked.
- **Tests:** `test_the_scene_question_is_asked_only_with_a_reference` and `test_no_names_reach_the_vision_prompt`. The second builds a Mutant run and asserts that no card name or alias appears in any recorded `visual`.

### Task 4, amended

- **`too_old`:**
  - checked inside `copy_lock`, before the admit;
  - when the candidate's `published_at` is more than 30 days before the main's and `state.old >= MAX_OLD`, it is rejected `too_old`;
  - `state.old` counts admitted old clips, and a displaced old clip lowers it.
- **Test:** `test_at_most_two_old_clips`, with 3 old subject-named clips: 2 admitted and 1 `too_old`.

### Task 5, amended

- **The relation CHECK lists:** `('related', 'same_event', 'discusses', 'unknown')`.
- **The reason CHECK adds:** `'same_event'`, `'subject_absent'` and `'too_old'`.
- **The comment line** names spec 10.12 too.

### Task 7: Face models and the face reader

**Files:**
- Modify: `docker/fetch_speech_models.py`:
  - a `FACES` pin dict;
  - `fetch_faces(out)`, wired into the existing CLI the way the diarization models are.
- Modify: `Dockerfile`, adding `test -r /opt/thoth/models/faces/yunet.onnx && test -r /opt/thoth/models/faces/arcface.onnx` beside the diarization checks.
- Modify: `python/src/thoth_control_plane/config.py`, adding `THOTH_FACE_MODELS_DIR: Path = Path("/opt/thoth/models/faces")`.
- Create: `python/src/thoth_control_plane/footage/faces.py`, the pure rules over embeddings with no cv2 and no onnx.
- Create: `python/src/thoth_control_plane/footage/adapters/faces.py`, the reader.
- Test:
  - `python/tests/footage/test_faces.py` for the pure rules;
  - `python/tests/footage/test_face_reader.py` for the models, skipped when the model files are absent.

**Interfaces:**
- Produces, in `footage/faces.py`:
  - `@dataclass(frozen=True) class Face: second: int; embedding: np.ndarray; crop: bytes`;
  - `@dataclass(frozen=True) class FaceGroup: members: list[Face]; seconds: int`;
  - `group_faces(faces: Sequence[Face]) -> list[FaceGroup]`: average linkage at `GROUP_LINK`; only groups with at least `MIN_SECONDS` distinct seconds; ordered by seconds, descending;
  - `clear_subject(groups) -> FaceGroup | None`: the first group when it alone counts, or when its seconds are at least `CLEAR_RATIO` times the second group's; otherwise `None`;
  - `template(group) -> np.ndarray`: up to `TEMPLATE_SIZE` member embeddings, evenly spaced by second;
  - `shows_subject(template, faces) -> bool`: true when faces in at least `MATCH_SECONDS` distinct seconds have a mean of their `TOP_K` best similarities of at least `MATCH`;
  - `encode_template(array) -> str` and `decode_template(text) -> np.ndarray` (float16, base64).
- Produces, in `adapters/faces.py`:
  - `class FaceReader` with `__init__(models_dir: Path)`, which loads both models and raises `FileNotFoundError` when either is missing;
  - `faces(path: Path, start: float = 0.0, duration: float | None = None) -> list[Face]`, which reads at `FACE_FPS` with cv2, detects, aligns with `FaceRecognizerSF.alignCrop`, and embeds with onnxruntime. Since cv2 needs a recognizer instance only to align, it is created with an empty model path, if OpenCV allows it. Otherwise the alignment uses `cv2.estimateAffinePartial2D` to the ArcFace five-point template.
  - Callers run it through `asyncio.to_thread`. The builder measures the event-loop lag on a 60 s main; see memory "native GIL holders need a process". If the lag exceeds 1 s, it moves to a process pool and records the ruling.

**Steps:**
1. Write the failing tests:
   - `test_group_faces_ranks_by_screen_time`;
   - `test_clear_subject_needs_one_and_a_half_times_the_next` (Mutant numbers: 54 vs 31 → clear; 30 vs 25 → `None`; one group → clear; none → `None`);
   - `test_shows_subject_needs_two_seconds_at_0_42`;
   - `test_template_round_trips_through_text`.

   Use synthetic unit vectors.
2. Run them, and watch them fail.
3. Implement.
4. Run them, and watch them pass. Then run the reader test in WSL with `THOTH_FACE_MODELS_DIR=/mnt/d/thoth-tmp/face-spike/models`, after copying `arcface_r50.onnx` to `arcface.onnx` there. It asserts at least one face on a 3-frame fixture cut from the spike's `pos_akting.mp4`; commit that fixture only if it is under 300 KB, and otherwise skip it with a reason.
5. Commit: `feat(footage): read and group faces with ArcFace`.

### Task 8: The subject stage in the workflow

**Files:**
- Modify: `python/src/thoth_control_plane/activities/footage.py`:
  - `find_subject(FootageActivityInput) -> SubjectResult`;
  - `FootageActivityInput.subject: str | None = None` (an encoded template);
  - `FootageActivityInput.face_check: bool = False`.
- Modify: `python/src/thoth_control_plane/worker.py`, to register the activity.
- Modify: `python/src/thoth_control_plane/domain/models.py`:
  - `ApprovalChoice(StrictModel)`: `choice_id`, `image` (a data URI, at most 40 000 chars) and `seconds: int`;
  - `ApprovalRequest.choices: list[ApprovalChoice] = []`;
  - `ApprovalDecision.choice: str | None = None`.
- Modify: `python/src/thoth_control_plane/application/ports.py`, adding `ApprovalSubmission.choice: str | None = None`.
- Modify: `python/src/thoth_control_plane/infrastructure/temporal_gateway.py`, to pass `choice` into the signal.
- Modify: `python/src/thoth_control_plane/workflows/source_investigation.py`:
  - `SUBJECT_PATCH = "footage-subject"`;
  - `_footage()` first runs `find_subject`;
  - when the result is doubtful, it stops on `ApprovalRequest(kind="choose_subject", prompt="Who is this story about?", allowed_decisions=["approve","reject"], choices=...)`;
  - `record_approval` accepts `choice` only when it names one of the choices.
- Regenerate: `python/openapi.json` and the dashboard's generated types, with the repo's existing commands.
- Test:
  - `python/tests/activities/test_footage_activity.py` (or the existing footage activity test);
  - `python/tests/workflows/test_source_investigation*.py`;
  - `python/tests/api` for the submission.

**Interfaces:**
- `SubjectResult(StrictModel)`:
  - `status: Literal["clear", "doubtful", "none"]`;
  - `subject: str | None`, the encoded template when clear;
  - `choices: list[SubjectChoice]`, where each `SubjectChoice` holds `choice_id`, `image`, `seconds` and `template`; present when doubtful, at most `MAX_CHOICES`.
- **The workflow:**
  - **clear:** `build_footage(subject=..., face_check=True)`;
  - **none:** `face_check=False`;
  - **doubtful:** stop. An approve with a choice gives that choice's template and `face_check=True`; a reject gives `face_check=False`. Either way, the stop's status is restored to `RUNNING` afterwards, and the stage plan is unchanged.
- **The `find_subject` activity:**
  - reads the main video the way `build_footage` does;
  - runs `FaceReader.faces`, `group_faces` and `clear_subject`.
- **A `find_subject` failure** after its retries fails the footage stage the same way a `build_footage` failure does.

**Steps:**
1. Write the failing tests:
   - `test_a_clear_subject_runs_footage_with_the_check`;
   - `test_a_doubtful_subject_waits_for_a_choice` (signal with `choice="g1"` → `build_footage` gets g1's template);
   - `test_rejecting_every_face_runs_footage_without_the_check` (Review Focus 7);
   - `test_cancel_while_choosing_the_subject` (Review Focus 8);
   - `test_a_choice_outside_the_offered_faces_is_ignored`;
   - an API test: `choice` passes through `POST .../approval`.

   Use the existing workflow test harness and stub activities.
2. Run them, and watch them fail.
3. Implement.
4. Run them, and watch them pass, with `make test T=tests/workflows`, `T=tests/activities` and `T=tests/api`.
5. Commit: `feat(workflow): stop for the story's subject when the face is unclear`.

### Task 9: The face check in footage screening

**Files:**
- Modify: `python/src/thoth_control_plane/footage/service.py`:
  - `FootageInputs.subject` / `face_check`;
  - `_Build.subject: np.ndarray | None` and `_Build.discusses: int`;
  - the face step in `_check` after OCR and before vision;
  - `relation` per spec 10.12.
- Modify: `python/src/thoth_control_plane/footage/ports.py`, adding `faces: FaceReader | None = None` to the ports.
- Modify: the activity wiring, to build `FaceReader(settings.THOTH_FACE_MODELS_DIR)` when `face_check` is true.
- Test: `python/tests/footage/test_service.py`, with a `Faces` fake that returns fixed `Face` lists per URL.

**Rules in `_check`:**
- With the face check on:
  - `on = shows_subject(state.subject, await asyncio.to_thread(faces.faces, path, ...))`.
- After vision:
  - vision `same_event` and `on` → `same_event` (then the Task 4 rule);
  - vision `same_event` and not `on` → reject `subject_absent`;
  - `on` → `related`;
  - not `on`, the text names the subject, and `state.discusses < MAX_DISCUSSES` → `discusses`, and `state.discusses += 1` after the admit lands;
  - otherwise → reject `subject_absent`.
- A clip with no faces at all and the slot taken is `subject_absent` too.
- To save the paid call, the face step runs before vision. Vision still runs for a face-less clip that may take the `discusses` slot.
- With the face check off: Task 3's relations, unchanged.

**Steps:**
1. Write the failing tests:
   - `test_a_clip_without_the_subject_is_rejected_subject_absent`;
   - `test_one_clip_may_discuss_the_subject_without_showing_them`;
   - `test_a_same_event_clip_needs_the_subject` (Review Focus 9);
   - `test_no_main_faces_turn_the_face_check_off` (Review Focus 6);
   - `test_a_clip_without_the_subject_spends_no_vision_call` (the judge is not called when the slot is taken).
2. Run them, and watch them fail.
3. Implement.
4. Run them, and watch them pass, with `make test T=tests/footage`.
5. Commit: `feat(footage): keep only clips that show the story's subject`.

### Task 10: The dashboard asks who the story is about

**Files:**
- Modify: `dashboard/src/features/workflows/RunDetailPage.tsx`. When `summary.approval.kind === "choose_subject"`, it shows the choice images as buttons, each with its screen time. A click approves with that `choice`, and a "None of these" button rejects.
- Modify: the client's `approveWorkflow` payload type (generated), and `dashboard/src/lib/i18n.ts` (EN + ID):
  - `approval.subjectTitle`: "Who is this story about?" / "Siapa tokoh cerita ini?";
  - `approval.subjectNone`: "None of these" / "Bukan salah satunya";
  - `approval.subjectSeconds`: "{n} s on screen" / "{n} detik di layar".
- Test: `RunDetailPage.test.tsx`. It renders the 2 choices, a click sends `{approval_id, decision: "approve", choice: "g1"}`, and "None of these" sends `reject`.

**Steps:** write the failing test, watch it fail, implement, then run `bun --cwd=dashboard test`, `tsc -b` and the build until they pass. Commit: `feat(dashboard): choose the story's subject when the face is unclear`.

### After the tasks, amended

- **Gates:**
  - deploy needs migration 0035 and a new worker image carrying about 167 MB of face models;
  - the live Mutant run is expected to go without a stop.
- **The final review** covers Tasks 1-10.

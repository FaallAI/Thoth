# Planner Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Style B drafts are cut on narration phrase starts. Each phrase shows a picture chosen for what it says: a main-video soundbite, else the vision model's pick, else the main video. A card can sit on top as an overlay. The camera is still, and every footage shot carries a credit.

**Architecture:** The pure domain code splits phrases, matches soundbites, and assigns shots and cards per phrase without repeats. The I/O lives in `assembly/`: ffmpeg shot detection, contact sheets, one OpenRouter call per draft, and a `Planner` service that builds and stores a `DraftPlan`. `narrate_document` turns the plan into per-beat assignments, and `style_operations` places them as ordinary edit operations in place of `plan_shots`' cursor picks. Every planner failure degrades to the phrase-start rhythm.

**Tech Stack:** Python 3.12, Pydantic, SQLAlchemy + Alembic (editor DB), httpx, Pillow (already in the `acquisition` extra the worker installs), ffmpeg/ffprobe, Temporal activities, pytest.

**Spec:** `docs/superpowers/specs/2026-11-13-planner-stage-1-design.md`. Read it first; section numbers below refer to it.

## Global Constraints

- **Repository language and commits:**
  - repository text is English;
  - each commit is one `git commit -m "<prefix>: <lowercase imperative>"` with a subject of at most 72 characters, no body and no trailer;
  - prefixes are `feat:`, `fix:`, `test:`, `refactor:` or `docs:`.
- **Tests:**
  - run from WSL with `make test T=<path>` while iterating;
  - before reporting, run the full `make test` and `make lint`;
  - a missing ffmpeg is an error, never a skip (operator, 2026-10-11).
- **Schema:** every new schema or payload field has a default, so stored rows and older documents still decode.
- **Degrade, never fail:**
  - the narration never fails because of the planner (spec goal 8);
  - degradation logs `warning`, progress logs `info`, detail logs `debug`.
- **Phrases (spec 5.1):** 0.9 s minimum, about 2.4 s maximum; cut at punctuation.
- **Shots (spec 5.2):**
  - scene detection with `select='gt(scene,0.3)'`;
  - merge shots under 0.8 s; split shots over 4.0 s into pieces of about 3.0 s;
  - the keyframe is the middle frame.
- **Speech per shot (spec 4):** a transcript sentence belongs to a shot only when it covers at least `min(1.0, 0.5 × shot length)` seconds of it.
- **Soundbite (spec 5.3):** fires when the best main shot shares at least 50% of the phrase's content words; the phrase needs at least 2 content words.
- **Contact sheets (spec 5.4):** 3×3 tiles of 384 px with a yellow shot label; one source per sheet; cards stacked 900 px wide.
- **Model call (spec 5.4):**
  - `temperature 0`, `response_format json_object`, `reasoning {"effort": "low"}`, `provider {"data_collection": "deny"}`, `usage {"include": true}`, `max_tokens 12000`;
  - a `finish_reason` other than `stop` is a failure.
- **Settings:** `THOTH_PLANNER_MODEL="qwen/qwen3.7-flash"`, `THOTH_PLANNER_FALLBACK_MODEL="google/gemini-3.1-flash-lite"`, `THOTH_PLANNER_ENABLED=True`.
- **Positioned card:** overlay cards use the import's card placement, `Position(x=0.0, y=-0.24, scale=0.76)` with `fit="contain"`.
- **Planner deadline:** the planner gets at most 180 s inside `narration_write_draft`, whose timeout is 5 min; on timeout it degrades.
- **Never print secrets:** the OpenRouter key is never logged.

## Review Focus

1. **A draft with no footage and no cards** (main video only): planning must still work. Soundbites jump-cut the main video, and every other phrase plays the main video on. No b-roll and no credits appear. *Test in Task 7.*
2. **A re-voice of one beat whose words are unchanged but whose timing changed** must make no model call and keep the picks. *Test in Task 8.*
3. **A model answer naming unknown ids, more than 3 base shots, or 2 overlays** must be clamped, not trusted. *Test in Task 4.*
4. **A locked card or a locked credit** in a planned beat must not move and must not be removed. *Test in Task 7.*
5. **A footage shot shorter than its phrase window** holds its last frame and never runs past its source. *Test in Task 6.*

---

## File map

| File | Responsibility |
|---|---|
| `python/src/thoth_control_plane/domain/planner.py` (create) | Plan models; phrase split; plan reuse; speech per shot; soundbite match. Pure. |
| `python/src/thoth_control_plane/domain/planner_assign.py` (create) | Picks per phrase (no repeats, fallback) and frame-level beat assignments. Pure. |
| `python/src/thoth_control_plane/assembly/planner_shots.py` (create) | ffmpeg shot detection, keyframes, contact sheets, card sheet. |
| `python/src/thoth_control_plane/assembly/adapters/planner_model.py` (create) | Prompt v3, the OpenRouter call, retries, fallback model, answer clamping, metering. |
| `python/src/thoth_control_plane/assembly/planner_service.py` (create) | `Planner`: candidates, shot cache, soundbite, model call, store, degrade. |
| `python/migrations/editor/0032_planner.sql` + `alembic/versions/0032_planner.py` (create) | `narrations.plan JSONB`; table `planner_shots`. |
| `infrastructure/editor_models.py`, `infrastructure/narration_store.py` (modify) | Plan column, shot-cache row, store methods. |
| `domain/style_templates.py`, `domain/style_apply.py` (modify) | Style B rev 2; planned beats placed from assignments. |
| `assembly/narration_timeline.py`, `activities/narration.py`, `config.py` (modify) | Plumb the plan; ports; settings. |
| `python/tests/fixtures/planner/` (create) | Trial data: 4 held-out drafts, v3 answers, blind picks. |

---

### Task 1: Plan models, phrase split and plan reuse

**Files:**
- Create: `python/src/thoth_control_plane/domain/planner.py`
- Test: `python/tests/domain/test_planner.py`

**Interfaces:**
- Produces (all `StrictModel` from `domain/models.py`, every field defaulted except ids):
  - `PlanShot(shot_id: str, asset_id: str, source: Literal["main", "footage"], start_seconds: float, end_seconds: float, said: str = "", handle: str | None = None)`
  - `PlanCard(card_id: str, asset_id: str, item_id: str, kind: Literal["post_card", "comment_card"])`
  - `PlanPhrase(phrase_id: str, first_word: int, last_word: int, text: str, base: list[str] = [], overlay: str | None = None, soundbite: bool = False, why: str = "")`
  - `BeatPlan(beat: BeatId, words_key: str, phrases: list[PlanPhrase] = [])`
  - `DraftPlan(version: int = 1, model: str | None = None, shots: list[PlanShot] = [], cards: list[PlanCard] = [], beats: list[BeatPlan] = [])`
  - `split_phrases(words: Sequence[WordTiming]) -> list[tuple[int, int]]`: inclusive word-index ranges.
  - `words_key(words: Sequence[WordTiming]) -> str`: sha256 hex of the word texts joined by `"\n"`. Timing is ignored.
  - `reuse_picks(stored: BeatPlan, ranges: Sequence[tuple[int, int]], words: Sequence[WordTiming]) -> list[PlanPhrase]`: each new range takes the base, overlay and soundbite of the stored phrase covering most of its words.
  - `MIN_PHRASE_SECONDS = 0.9`, `MAX_PHRASE_SECONDS = 2.4`.

- [ ] **Step 1: Write the failing tests**

```python
def w(text, start, end): return WordTiming(text=text, start_seconds=start, end_seconds=end)

def test_split_cuts_at_punctuation_once_long_enough():
    words = [w("Rocky", 0.0, 0.4), w("Gerung", 0.4, 0.9), w("kena", 0.9, 1.1), w("semprot!", 1.1, 1.6),
             w("Ada", 1.7, 1.9), w("yang", 1.9, 2.1), w("teriak", 2.1, 2.6), w("tobat,", 2.6, 3.0)]
    assert split_phrases(words) == [(0, 3), (4, 7)]

def test_split_caps_a_phrase_near_2_4_seconds():
    words = [w(f"kata{i}", i * 0.5, i * 0.5 + 0.45) for i in range(10)]
    ranges = split_phrases(words)
    assert all(words[b].end_seconds - words[a].start_seconds <= 2.4 + 0.5 for a, b in ranges)
    assert len(ranges) >= 2

def test_split_folds_a_short_tail_into_the_phrase_before():
    words = [w("Bung", 0.0, 0.5), w("Rocky", 0.5, 1.0), w("Gerung", 1.0, 1.6), w("nih.", 1.6, 1.9)]
    assert split_phrases(words) == [(0, 3)]

def test_words_key_ignores_timing():
    assert words_key([w("a", 0, 1), w("b", 1, 2)]) == words_key([w("a", 0, 2), w("b", 2, 3)])

def test_reuse_maps_picks_by_word_overlap():
    stored = BeatPlan(beat="main", words_key="k", phrases=[
        PlanPhrase(phrase_id="P1", first_word=0, last_word=3, text="", base=["S4"]),
        PlanPhrase(phrase_id="P2", first_word=4, last_word=7, text="", overlay="C2")])
    words = [w(str(i), i, i + 1) for i in range(8)]
    out = reuse_picks(stored, [(0, 2), (3, 7)], words)
    assert [p.base for p in out] == [["S4"], []] and [p.overlay for p in out] == [None, "C2"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `make test T=tests/domain/test_planner.py`
Expected: FAIL with `ImportError` (module `domain.planner` missing).

- [ ] **Step 3: Implement the models, `split_phrases`, `words_key` and `reuse_picks` in `domain/planner.py`**

`split_phrases` follows the trial's `phrases_for`:
- a word ending in `[,.?!;:]` closes the phrase once the phrase spans at least 0.9 s;
- a phrase also closes when adding the next word would exceed 2.4 s, the phrase already spans 0.9 s, and the next word does not itself end in punctuation;
- the last word closes the final phrase;
- a final phrase shorter than 0.9 s folds into the one before it.

- [ ] **Step 4: Run the tests to see them pass**

Run: `make test T=tests/domain/test_planner.py`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/domain/planner.py python/tests/domain/test_planner.py
git commit -m "feat: split narration into phrases and reuse stored picks"
```

### Task 2: Speech per shot, soundbite matching, and the trial fixtures

**Files:**
- Modify: `python/src/thoth_control_plane/domain/planner.py`
- Create: `python/tests/fixtures/planner/README.md`, `python/tests/fixtures/planner/<doc8>.json` (4 files), `python/scripts/export_planner_fixtures.py`
- Test: `python/tests/domain/test_planner.py`

**Interfaces:**
- Consumes: `PlanShot` (Task 1).
- Produces:
  - `shot_speech(transcript: Sequence[TranscriptSegment], start: float, end: float) -> str`;
  - `soundbite(text: str, main_shots: Sequence[PlanShot]) -> list[str]`: shot ids in time order, empty when it does not fire;
  - `STOP_WORDS: frozenset[str]`, exactly: `yang dan di ke dari ini itu ada aja juga dia nya sih nih kan lagi ya pun saat jadi untuk dengan atau sebagai dalam`.
- **Fixture file shape** (one per held-out draft: `641b43a8`, `b410cf36`, `194f5305`, `3a20bf9f`):
  - `{"shots": [{shot, source, start, end, said, asset_id}], "phrases": [{id, beat, text, start, end}], "answer_v3": {"P1": {"base": [...], "overlay": [...]}}, "blind": {"P1": {"own": [...], "model_ok": bool, "v2_pick": "S3" | null}}}`;
  - `said` is recomputed with the fixed rule. No thumbnails, no URLs, no secrets.

- [ ] **Step 1: Write `scripts/export_planner_fixtures.py` and run it once**

The script takes three arguments: the trial folder (`D:/thoth-tmp/planner-trial`), the scratchpad `trial-data.js` path, and an output directory. It reads:
- `trial/<doc>/trial.json`;
- `results/qwen__qwen3.7-flash__v3a.json`;
- `results/qwen__qwen3.7-flash__v2pre.json` (for `v2_pick`);
- `judgments-r3/judgments/*_r3.json`.

It writes the four fixture files. The README names the source (the operator's blind round 3, 2026-11-13) and the fixtures' limits (one story family). Commit the fixtures; the script stays as the record of how they were made.

- [ ] **Step 2: Write the failing tests**

```python
SEGS = [TranscriptSegment(text="A", start_seconds=0.9, end_seconds=20.4),
        TranscriptSegment(text="B", start_seconds=20.4, end_seconds=32.1)]

def test_a_sliver_at_a_cut_is_not_the_shots_speech():
    assert shot_speech(SEGS, 17.9, 20.9) == "A"
    assert shot_speech(SEGS, 20.9, 23.9) == "B"
    assert shot_speech(SEGS, 19.0, 22.0) == "A B"

def test_soundbite_needs_two_content_words_and_half_overlap():
    shots = [PlanShot(shot_id="S25", asset_id="m", source="main", start_seconds=0, end_seconds=1, said="Penjilat nasional."),
             PlanShot(shot_id="S3", asset_id="m", source="main", start_seconds=1, end_seconds=2, said="Tobat, TG!")]
    assert soundbite("penjilat nasional.", shots) == ["S25"]
    assert soundbite("nah.", shots) == []

def test_soundbite_hits_the_operators_blind_pick_on_the_fixtures():
    fired, hit = fixture_soundbite_score()  # helper in the test module, reads tests/fixtures/planner/*.json
    assert fired >= 12 and hit >= 12
```

- [ ] **Step 3: Run them to see them fail**

Run: `make test T=tests/domain/test_planner.py`
Expected: FAIL with `ImportError: cannot import name 'shot_speech'`.

- [ ] **Step 4: Implement `shot_speech` and `soundbite`**

- `shot_speech` joins, in order, the texts of the segments that overlap `[start, end)` by at least `min(1.0, 0.5 * (end - start))`.
- `soundbite` uses words from `re.findall(r"[a-z0-9]+", text.lower())`, dropping `STOP_WORDS` and single letters. The score is shared words over the phrase's word count. It returns every shot with the best score when that score is at least 0.5 and the phrase has at least 2 words.

- [ ] **Step 5: Run the tests to see them pass**

Run: `make test T=tests/domain/test_planner.py`
Expected: PASS (8 tests).

- [ ] **Step 6: Commit**

```bash
git add python/src/thoth_control_plane/domain/planner.py python/tests/domain/test_planner.py python/tests/fixtures/planner python/scripts/export_planner_fixtures.py
git commit -m "feat: match soundbites to main-video shots by their speech"
```

### Task 3: Source shots and contact sheets

**Files:**
- Create: `python/src/thoth_control_plane/assembly/planner_shots.py`
- Test: `python/tests/assembly/test_planner_shots.py`

**Interfaces:**
- Produces:
  - `async def detect_shots(video: Path, ffmpeg: str, ffprobe: str) -> list[tuple[float, float]]`: seconds, merged and split per the Global Constraints;
  - `async def keyframes(video: Path, spans: Sequence[tuple[float, float]], ffmpeg: str, directory: Path) -> list[Path]`: one JPEG per span at its middle, scaled to fit 384×384;
  - `@dataclass(frozen=True) class Sheet(source: str, shot_ids: list[str], jpeg: bytes)`;
  - `contact_sheets(source: str, tiles: Sequence[tuple[str, Path]]) -> list[Sheet]`: 9 tiles per sheet;
  - `card_sheet(cards: Sequence[tuple[str, Path]]) -> bytes | None`: None when there are no cards;
  - constants `SCENE_THRESHOLD = 0.3`, `MIN_SHOT = 0.8`, `MAX_SHOT = 4.0`, `SPLIT_TO = 3.0`, `TILE = 384`, `GRID = 3`.
- Runs ffmpeg through `asyncio.create_subprocess_exec`. Merge and split follow the trial's `shots_for`. Sheet drawing follows the trial's `sheet` and `card_sheet`; the label font is DejaVuSans-Bold when present, else Pillow's default.

- [ ] **Step 1: Write the failing tests**

```python
async def test_detect_shots_finds_the_cuts_of_a_three_scene_clip(tmp_path):
    clip = make_three_scene_clip(tmp_path)  # ffmpeg lavfi: 2 s red, 2 s blue, 6 s green
    spans = await detect_shots(clip, _require(FFMPEG), _require(FFPROBE))
    assert len(spans) == 4  # 2 s, 2 s, then the 6 s scene split into two 3 s pieces
    assert spans[0][0] == 0.0 and abs(spans[-1][1] - 10.0) < 0.2

def test_a_contact_sheet_holds_nine_tiles(tmp_path):
    tiles = [(f"S{i}", solid_jpeg(tmp_path, i)) for i in range(1, 12)]
    sheets = contact_sheets("MAIN", tiles)
    assert [s.shot_ids[:1] for s in sheets] == [["S1"], ["S10"]]
    assert Image.open(io.BytesIO(sheets[0].jpeg)).size == (1152, 1152)

def test_no_cards_no_card_sheet():
    assert card_sheet([]) is None
```

- [ ] **Step 2: Run them to see them fail**

Run: `make test T=tests/assembly/test_planner_shots.py`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `planner_shots.py`**

- [ ] **Step 4: Run the tests to see them pass**

Run: `make test T=tests/assembly/test_planner_shots.py`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/assembly/planner_shots.py python/tests/assembly/test_planner_shots.py
git commit -m "feat: detect source shots and draw planner contact sheets"
```

### Task 4: The planner model call

**Files:**
- Create: `python/src/thoth_control_plane/assembly/adapters/planner_model.py`
- Test: `python/tests/assembly/test_planner_model.py`

**Interfaces:**
- Consumes: `Sheet` (Task 3); `PlanShot`, `PlanCard` (Task 1).
- Produces:
  - `@dataclass(frozen=True) class PhraseAsk(phrase_id: str, beat: str, text: str)`;
  - `@dataclass(frozen=True) class PhraseAnswer(phrase_id: str, base: list[str], overlay: str | None, why: str)`;
  - `class PlannerUnavailable(Exception)`;
  - `class PlannerModel(api_key: str, model: str, fallback: str | None, *, client: httpx.AsyncClient | None = None, sleep=asyncio.sleep)` with `async def ask(self, sources: str, sheets: Sequence[Sheet], cards: bytes | None, script: str, phrases: Sequence[PhraseAsk], shot_ids: set[str], card_ids: set[str]) -> list[PhraseAnswer]`; `.model_used: str | None` is set after a success;
  - `SYSTEM_PROMPT`: copy `SYSTEM_V3` verbatim from `D:/thoth-tmp/planner-trial/call.py`.
- **Message order** follows the trial's `build()`:
  1. the sources text, with each main shot's speech;
  2. per sheet, a text label then the image as a `data:image/jpeg;base64` URL;
  3. the card sheet;
  4. "FULL NARRATION" and "PHRASES TO MATCH".
- **Retries:** up to 3 attempts per model on HTTP 429, 502, 503 or `httpx.TransportError`, sleeping 5 s then 15 s. Then the fallback model, also up to 3 attempts. Then `PlannerUnavailable`.
- **Failures:** any other non-200, a `finish_reason` other than `stop`, or a body that is not JSON. A failure on the main model moves to the fallback.
- **Clamping:** unknown ids are dropped, `base` is cut to 3, `overlay` to the first card id, and `fit: "none"` clears both. Phrases the model left out are absent from the result.
- **Metering:** `metering.record_call(model, tokens_in=usage.prompt_tokens, tokens_out=usage.completion_tokens)` after each 200 answer.

- [ ] **Step 1: Write the failing tests** (httpx `MockTransport`, `sleep` replaced by a no-op)

```python
async def test_body_carries_the_trial_settings_and_the_images(): ...
    # assert body["temperature"] == 0 and body["reasoning"] == {"effort": "low"}
    # assert body["provider"] == {"data_collection": "deny"} and body["max_tokens"] == 12000
    # assert body["response_format"] == {"type": "json_object"}
    # assert sum(part["type"] == "image_url" for part in body["messages"][1]["content"]) == len(sheets) + 1

async def test_a_429_is_retried_then_answered(): ...          # 429, 429, 200 -> answers; 3 requests
async def test_truncation_moves_to_the_fallback_model(): ...  # finish_reason "length" -> next request model == fallback
async def test_both_models_failing_raises_planner_unavailable(): ...

async def test_answers_are_clamped():
    # model returns base ["S1","S99","S2","S3","S4"], overlay ["C9","C1"] for P1 and fit "none" for P2
    assert answers == [PhraseAnswer("P1", ["S1", "S2", "S3"], "C1", "..."), PhraseAnswer("P2", [], None, "...")]
```

- [ ] **Step 2: Run them to see them fail**

Run: `make test T=tests/assembly/test_planner_model.py`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `planner_model.py` with raw `httpx`**

Ruling: raw httpx, not Agno like `attribution/adapters/vision.py`. Agno hides `finish_reason`, `reasoning` and `provider`, which the trial showed are required.

- [ ] **Step 4: Run the tests to see them pass**

Run: `make test T=tests/assembly/test_planner_model.py`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/assembly/adapters/planner_model.py python/tests/assembly/test_planner_model.py
git commit -m "feat: ask the planner model for base shots and card overlays"
```

### Task 5: Plan storage and the shot cache

**Files:**
- Create: `python/migrations/editor/0032_planner.sql`, `python/migrations/editor/alembic/versions/0032_planner.py`
- Modify: `python/src/thoth_control_plane/infrastructure/editor_models.py`, `python/src/thoth_control_plane/infrastructure/narration_store.py`
- Test: `python/tests/infrastructure/test_narration_store_postgres.py`

**Interfaces:**
- Produces on `NarrationStore`:
  - `async def get_plan(document_id: str) -> DraftPlan | None`;
  - `async def set_plan(document_id: str, plan: DraftPlan) -> None`;
  - `async def get_shots(checksum: str) -> list[tuple[float, float]] | None`;
  - `async def put_shots(checksum: str, spans: list[tuple[float, float]]) -> None`. On a conflict, put keeps the first row.
- **SQL**, following 0030's style with a rollback note:

  ```sql
  ALTER TABLE narrations ADD COLUMN plan JSONB;
  CREATE TABLE planner_shots (
      checksum TEXT PRIMARY KEY,
      shots JSONB NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
  );
  ```

  The Alembic file is `revision = "0032"`, `down_revision = "0031"`, `execute_sql_file(__file__)`.
- ORM: `NarrationRow.plan: Mapped[Any | None]` (JSONB, nullable) and `PlannerShotsRow`.

- [ ] **Step 1: Write the failing Postgres tests**

```python
async def test_plan_round_trips(store, narration_row):
    plan = DraftPlan(model="m", beats=[BeatPlan(beat="main", words_key="k")])
    await store.set_plan(DOC, plan)
    assert await store.get_plan(DOC) == plan

async def test_shot_cache_keeps_the_first_write(store):
    await store.put_shots("sha256:x", [(0.0, 1.5)])
    await store.put_shots("sha256:x", [(0.0, 9.0)])
    assert await store.get_shots("sha256:x") == [(0.0, 1.5)]
    assert await store.get_shots("sha256:missing") is None
```

- [ ] **Step 2: Run them to see them fail**

Run: `make test T=tests/infrastructure/test_narration_store_postgres.py`
Expected: FAIL with `AttributeError: 'NarrationStore' object has no attribute 'set_plan'`.

- [ ] **Step 3: Write the migration, ORM rows and store methods**

- [ ] **Step 4: Run the tests to see them pass, plus the migration tests**

Run: `make test T=tests/infrastructure/test_narration_store_postgres.py` and `make test T=tests/operations`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/migrations/editor python/src/thoth_control_plane/infrastructure python/tests/infrastructure/test_narration_store_postgres.py
git commit -m "feat: store a draft's plan and cache source shots by checksum"
```

### Task 6: The assigner

**Files:**
- Create: `python/src/thoth_control_plane/domain/planner_assign.py`
- Test: `python/tests/domain/test_planner_assign.py`

**Interfaces:**
- Consumes: `PlanPhrase`, `PlanShot`, `PlanCard`, `DraftPlan` (Task 1).
- Produces:
  - `pick_bases(phrases: Sequence[PlanPhrase], shots: Mapping[str, PlanShot], windows_seconds: Sequence[float], used: set[str]) -> list[str | None]`. This is spec 5.5 steps 1 and 4:
    - for each phrase, a soundbite phrase's (`soundbite=True`) first unused base shot whatever its length, else the first unused base shot whose length is at least half its window;
    - `None` means the main-video fallback;
    - chosen ids are added to `used`, so the caller shares one `used` set across the whole draft (spec 5.7, no repeats).
  - `@dataclass(frozen=True) class PlannedShot(from_frame: int, duration: int, asset_id: str, source_from_frame: int, layer: Literal["main", "broll"], hold: bool, credit: str | None)`
  - `@dataclass(frozen=True) class PlannedCard(from_frame: int, duration: int, asset_id: str, item_id: str, full: bool)`
  - `@dataclass(frozen=True) class BeatAssignment(beat: BeatId, shots: list[PlannedShot], cards: list[PlannedCard], phrase_starts: list[int])`
  - `assign_beat(beat: BeatId, phrases: Sequence[PlanPhrase], windows: Sequence[tuple[int, int]], plan: DraftPlan, fps: float, main_asset: str | None, main_from_frame: int, background: bool, used: set[str], source_frames: Mapping[str, int]) -> BeatAssignment`
- **`assign_beat` rules** (spec 5.5 and 5.7):
  - **Base on the main video** → a `main` layer shot from that shot's start.
  - **Footage base** → a `broll` shot carrying the source's handle as `credit`. On a `background` beat, the main video also continues on the `main` layer underneath.
  - **`None`** → the main video continues on the `main` layer (`main_from_frame` advances with the frames played). On the footage beat, with no main video under it, the phrase window is left to the rhythm-only shots.
  - **Short shot:** a shot shorter than its window holds (`hold=True`) and never reads past `source_frames`.
  - **Overlay card** → `PlannedCard(full=False)` over the phrase window. A card with no base → `PlannedCard(full=True)`, and no b-roll shot.

- [ ] **Step 1: Write the failing tests**

```python
def test_no_shot_repeats_across_the_draft():
    used: set[str] = set()
    first = pick_bases([ph(base=["S1"])], SHOTS, [1.5], used)
    second = pick_bases([ph(base=["S1", "S2"])], SHOTS, [1.5], used)
    assert first == ["S1"] and second == ["S2"]

def test_a_soundbite_is_taken_even_when_shorter_than_half_its_window():
    # a soundbite phrase's base holds the soundbite shots (Task 8 sets base and soundbite=True)
    assert pick_bases([ph(base=["S8"], soundbite=True)], SHOTS, [9.0], set()) == ["S8"]

def test_nothing_fits_falls_back_to_the_main_video():
    a = assign_beat("main", [ph()], [(0, 45)], PLAN, 30.0, "main_asset", 300, True, set(), SRC)
    assert [(s.layer, s.asset_id, s.source_from_frame) for s in a.shots] == [("main", "main_asset", 300)]

def test_footage_base_rides_over_the_running_main_video_with_a_credit():
    a = assign_beat("main", [ph(base=["S40"])], [(0, 45)], PLAN, 30.0, "main_asset", 300, True, set(), SRC)
    assert {s.layer for s in a.shots} == {"main", "broll"}
    assert next(s for s in a.shots if s.layer == "broll").credit == "@kompascomreport"

def test_a_short_footage_shot_holds_inside_its_source():   # Review Focus 5
    a = assign_beat("main", [ph(base=["S41"])], [(0, 90)], PLAN, 30.0, "main_asset", 0, True, set(), {"f2": 20})
    shot = next(s for s in a.shots if s.layer == "broll")
    assert shot.hold and shot.source_from_frame < 20

def test_card_with_no_base_fills_the_screen():
    a = assign_beat("reactions", [ph(overlay="C2")], [(0, 45)], PLAN, 30.0, "main_asset", 0, True, set(), SRC)
    assert [c.full for c in a.cards] == [True]

def test_the_trial_answers_keep_the_blind_first_shot_score():
    # tests/fixtures/planner: pick_bases over answer_v3 + soundbite, scored against "own" (blind picks only),
    # first pick only, main-video fallback where own has no shot counted fine (spec 6, the middle counting)
    assert fixture_blind_first_shot_score() >= 0.60
```

- [ ] **Step 2: Run them to see them fail**

Run: `make test T=tests/domain/test_planner_assign.py`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `planner_assign.py`**

- [ ] **Step 4: Run the tests to see them pass**

Run: `make test T=tests/domain/test_planner_assign.py`
Expected: PASS (7 tests). The fixture score prints in the test's assertion message.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/domain/planner_assign.py python/tests/domain/test_planner_assign.py
git commit -m "feat: assign each phrase a base shot, card and credit"
```

### Task 7: Style B revision 2 and planned beats in `style_operations`

**Files:**
- Modify: `python/src/thoth_control_plane/domain/style_templates.py`, `python/src/thoth_control_plane/domain/style_apply.py`
- Test: `python/tests/domain/test_style_templates.py`, `python/tests/domain/test_style_apply.py`

**Interfaces:**
- Consumes: `BeatAssignment`, `PlannedShot`, `PlannedCard` (Task 6).
- Produces:
  - `CutRules.planned: bool = False`;
  - Style B becomes `revision=2`, with `BeatLook(move="none", dim=0.45)` on every beat and `CutRules(max_shot_seconds=2.4, min_shot_seconds=0.9, card_between_facts=True, planned=True)`;
  - `style_operations(..., assignments: Mapping[BeatId, BeatAssignment] | None = None)`.
- **For a beat with an assignment:**
  - its unlocked full-frame pictures are removed, as today;
  - each `PlannedShot` becomes an `AddClipFromAsset`: the `main` layer on the beat's main-video track, the `broll` layer on the first `b_roll` track;
  - each carries the beat's look, with `hold_after_source` when `hold`;
  - a `credit` adds an `AddTextClip(style_slot="credit", heading=credit, body="")` over the same frames, with an id from `new_clip_id("credit")`, i.e. `clip_style_credit_<n>`.
- **Cards:**
  - each `PlannedCard` is an `AddClipFromAsset` on the `b_roll` track with `fit="contain"`;
  - `position=Position(x=0.0, y=-0.24, scale=0.76)` unless `full`;
  - an unlocked positioned card clip of the same asset in the beat is removed first (it moves); a locked one stays.
- **Credits removed in a planned beat:** unlocked text clips whose `source_role` is `footage`, whose heading starts with `@` and whose body is empty (the import's credits), and earlier `clip_style_credit_*` clips. Locked ones stay.
- **Card lines (`planned=True`)** never take a slot:
  - spoken → at `card_at`, as today;
  - otherwise at `phrase_starts[2]`, or the last phrase start when there are fewer, for `card_seconds`.
- **A planned style with no assignment for a beat** cuts it with `plan_shots`, using `phrase_starts` passed in place of sentence ends (rhythm-only, goal 8).

- [ ] **Step 1: Write the failing tests**

```python
def test_style_b_is_still_and_planned():
    b = BUILT_IN_STYLES["style_b"]
    assert b.revision == 2 and b.cuts.planned and {look.move for look in b.beats.values()} == {"none"}

def test_planned_beat_places_shots_cards_and_credits(): ...
    # document with a main video, one footage source and a comment card; assignment with one broll shot
    # (credit "@kompascomreport") and one overlay card -> one AddClipFromAsset on b_roll, one credit text
    # clip "clip_style_credit_1" spanning the shot, the card moved to the phrase window with the import position

def test_import_credits_are_replaced_but_locked_ones_stay(): ...       # Review Focus 4
def test_a_locked_card_does_not_move(): ...                            # Review Focus 4
def test_card_line_sits_over_the_third_phrase_and_pushes_nothing(): ...
def test_main_only_draft_has_no_broll_and_no_credits(): ...           # Review Focus 1
```

- [ ] **Step 2: Run them to see them fail**

Run: `make test T=tests/domain/test_style_apply.py` and `make test T=tests/domain/test_style_templates.py`
Expected: FAIL (revision 1; unexpected keyword `assignments`).

- [ ] **Step 3: Implement the template change and the planned-beat branch in `style_operations`**

Keep the existing per-track loop for beats without an assignment. Existing Style B expectations in other tests that assert `push_in` or revision 1 are updated to revision 2, and each update is named in the commit's task ledger line.

- [ ] **Step 4: Run the style tests and the narration timeline tests**

Run: `make test T=tests/domain` and `make test T=tests/assembly/test_narration_timeline.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/domain/style_templates.py python/src/thoth_control_plane/domain/style_apply.py python/tests/domain
git commit -m "feat: place planned shots, cards and credits in style b beats"
```

### Task 8: The planner service, narration plumbing and settings

**Files:**
- Create: `python/src/thoth_control_plane/assembly/planner_service.py`
- Modify: `python/src/thoth_control_plane/assembly/narration_timeline.py`, `python/src/thoth_control_plane/activities/narration.py`, `python/src/thoth_control_plane/config.py`
- Test: `python/tests/assembly/test_planner_service.py`, `python/tests/activities/test_narration_activities.py`, `python/tests/assembly/test_narration_timeline.py`, `python/tests/test_config.py`

**Interfaces:**
- Consumes: Tasks 1-7.
- **Produces `class Planner`** (in `planner_service.py`):
  - built from `store` (Task 5 methods, plus `get_transcript`), `fetch_asset: Callable[[str, str, Path], Awaitable[tuple[Path, str] | None]]` (project, asset → local file and checksum), `model: PlannerModel | None`, `ffmpeg: str`, `ffprobe: str`;
  - `async def plan(self, project_id: str, document_id: str, document: EditDocumentV2, materials: StudioMaterials, voices: Sequence[VoicedBeat]) -> DraftPlan | None`.
- **What `plan` does:**
  1. **Stored picks:** a stored beat plan with the same `words_key` takes `reuse_picks`, and that beat makes no call.
  2. **Candidates:** the timeline's video assets, plus the Materials items with role `footage`, `post_card` or `comment_card` that have an `asset_id`. The handle is `owner_handle`.
  3. **Shots:** from the cache by checksum, else `detect_shots` then `put_shots`. `said` comes from `shot_speech` over `get_transcript`.
  4. **Soundbites** are set first.
  5. **One `model.ask`** covers only the beats that need it. With no model, or on `PlannerUnavailable`, those phrases keep their soundbite or nothing.
  6. **`set_plan`**, then return the plan.
  7. **Any other exception** logs a warning and returns `None`.
- `narrate_document(..., plan: DraftPlan | None = None)`:
  - when `style.cuts.planned`, it computes each voiced beat's phrase windows in frames from `split_phrases` and `starts`;
  - it runs `pick_bases` and `assign_beat` with one shared `used` set, and passes `assignments` and phrase starts to `style_operations`;
  - with no plan, it still passes phrase starts (rhythm-only).
- `NarrationPorts.planner: Any | None = None`. `_write` calls `await asyncio.wait_for(ports.planner.plan(...), PLANNER_DEADLINE_SECONDS)` with `PLANNER_DEADLINE_SECONDS = 180`, only when `style is not None and style.cuts.planned`. A timeout logs a warning and continues with `plan=None`.
- `build_narration_activities` wires the `Planner`:
  - `PlannerModel(settings.openrouter_api_key(), settings.THOTH_PLANNER_MODEL, settings.THOTH_PLANNER_FALLBACK_MODEL)` when a key exists and `THOTH_PLANNER_ENABLED`, else `model=None`;
  - `fetch_asset` is built like `main_video` from `assets.get_ready_record` and `media.fetch`, returning the record's checksum.
- `config.py` gains `THOTH_PLANNER_MODEL`, `THOTH_PLANNER_FALLBACK_MODEL` and `THOTH_PLANNER_ENABLED`, with the Global Constraints defaults.

- [ ] **Step 1: Write the failing tests**

```python
async def test_unchanged_words_reuse_the_plan_without_a_call(): ...   # Review Focus 2: same words, new timing -> model.ask not called
async def test_model_unavailable_keeps_soundbites(): ...              # PlannerUnavailable -> soundbite phrases keep base, others empty
async def test_shots_come_from_the_cache_by_checksum(): ...           # cached checksum -> detect_shots not called
async def test_the_post_card_from_materials_is_a_candidate(): ...

def test_planned_style_cuts_on_phrase_starts_without_a_plan(): ...   # narrate_document(style_b, plan=None): cuts == phrase starts
def test_write_draft_survives_a_planner_timeout(): ...                # fake planner sleeps past a patched deadline -> draft written
def test_planner_settings_default(): ...                              # the three defaults
```

- [ ] **Step 2: Run them to see them fail**

Run: `make test T=tests/assembly/test_planner_service.py` (and the three other test files)
Expected: FAIL with `ImportError` / an unexpected keyword `plan`.

- [ ] **Step 3: Implement `planner_service.py`, the `narrate_document` plumbing, the port, the wiring and the settings**

- [ ] **Step 4: Run them to see them pass**

Run: `make test T=tests/assembly` and `make test T=tests/activities/test_narration_activities.py` and `make test T=tests/test_config.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane python/tests
git commit -m "feat: plan style b narrations per phrase in the draft write"
```

### Task 9: Full verification and records

**Files:**
- Modify: `CHANGELOG.md`, `BLUEPRINT.md` (subsystem status only), `.superpowers/sdd/2026-11-12-footage-library/progress.md`

- [ ] **Step 1: Run the full suite and lint**

Run: `make test` then `make lint`
Expected: both green. Name every failure that is not this branch's, with its output.

- [ ] **Step 2: Record**

Write a CHANGELOG entry for the stage: what was built, the test evidence, the trial's 50-77% range with the 60-66% fixture guard, and the cost per draft. End it with a **Next steps** section:
- the operator's review;
- the push, deploy and merge gates;
- the live paid check on a new story, judged blind;
- the target agreed from that check;
- carried forward: the "Tobat, TG!" typo, the footage library and stressed narration.

Write the same next steps into `progress.md`.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md BLUEPRINT.md
git commit -m "docs: record planner stage 1"
```

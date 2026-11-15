# Footage Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The run's footage stage finds footage of the same story from a context card of the main
post. It searches with people and aliases in two rounds, takes moments from long videos by their
captions, prefers originals over reposts, and keeps every clip in a per-workspace library for
later runs.

**Architecture:** New pure modules under `footage/`:
- `context.py`: the card, its queries, the window and the context gate;
- `moments.py`: caption moments;
- `reposts.py`: credits and own accounts.

There are three new adapters: the card model, the caption fetcher and the library media copy. The
existing `FootageBuilder._build` gains a context path in front of today's object path. The context
path produces the same `FootageObject` rows and candidates, so `_check_all`, OCR, vision, the
dhash duplicate check, publish and the import are reused unchanged. Editor migration 0033 adds
`footage_runs.context` and the `footage_library` table.

**Tech Stack:** Python 3.12, pydantic, SQLAlchemy and Alembic (SQL-file migrations), httpx to
OpenRouter, yt-dlp, pytest.

**Spec:** `docs/superpowers/specs/2026-11-15-footage-library-design.md` (approved 2026-11-15).
The brainstorm record is `.superpowers/sdd/2026-11-12-footage-library/brainstorm-notes.md`, items
46-55.

## Global Constraints

- **Feature flag:** `THOTH_FOOTAGE_CONTEXT_ENABLED: bool = True`. With it off, or with no card
  answer, today's object path runs unchanged.
- **Card model:** `THOTH_FOOTAGE_CARD_MODEL: str = "google/gemini-3.1-flash-lite"`. On failure the
  existing `THOTH_FOOTAGE_QUERY_MODEL` is tried once. A model failure never fails the run.
- **Limits:**
  - card queries: round 1 takes the first 4, round 2 at most 3 new ones;
  - round 2 sees the top 15 round-1 titles;
  - window: from 30 days before the main post's publish time to the run start;
  - long videos: at most 3 per run, at most 3 moments each, at least 60 s apart, none in the
    first 30 s;
  - a section starts at the line minus 1 s and lasts 8 s;
  - `MAX_FOOTAGE = 6` is unchanged.
- **Credit:** "YouTube/<handle without @>" for YouTube, "@<handle>" for TikTok, X and Instagram.
- **Reject reason:** a new `"repost"` in `RejectReason`. Every other reason is unchanged.
- **New fields have defaults:**
  - the migration adds a nullable column and a new table;
  - the card's JSON decodes with every field optional.
- **Logs:** `info` for progress, `warning` for degradation (card failed, captions missing), and
  never a URL with a secret.
- **Repo rules:**
  - English in code and docs;
  - one-line commit subjects with a Conventional Commits prefix and no trailers;
  - `make test` and `make lint` from WSL.

## Review Focus

1. **Short or common aliases** ("TG", "RG", "Sandy") must not admit unrelated posts. An alias
   counts only if it has at least 3 characters and matches whole words. The test is in Task 2.
2. **A candidate with no `published_at`** stays in, and is not dropped by the window. The test is
   in Task 2.
3. **A long video with captions but no line naming a card person** is rejected `duration`, and
   nothing is downloaded. The test is in Task 3.
4. **The library never crosses workspaces.** A lookup with another workspace's names returns
   nothing. The test is in Task 5.
5. **A traced "original" that is the main post itself** is rejected `main`, not admitted. The test
   is in Task 7.

---

### Task 1: The context card and its model adapter

**Files:**
- Create: `python/src/thoth_control_plane/footage/context.py`
- Create: `python/src/thoth_control_plane/footage/adapters/context_model.py`
- Modify: `python/src/thoth_control_plane/config.py` (add the two settings above, next to
  `THOTH_FOOTAGE_QUERY_MODEL`)
- Test: `python/tests/footage/test_context.py`, `python/tests/footage/test_context_model.py`
- Fixtures: `python/tests/fixtures/footage/context/` holds the spike's 4 card answers as JSON,
  copied from `D:/thoth-tmp/footage-spike/spike.out`:
  - `mutant_card.json`;
  - `rocky_card.json`;
  - `persib_card.json`;
  - `erio_card.json`.

**Interfaces:**
- Produces:
  - `class CardPerson(StrictModel)`: `name: str = ""`, `aliases: list[str] = []`, `role: str = ""`,
    `accounts: list[str] = []`;
  - `class ContextCard(StrictModel)`: `people: list[CardPerson] = []`, `event: str = ""`,
    `place: str = ""`, `when: str = ""`, `meme_or_joke: str = ""`, `queries: list[str] = []`,
    `notes: str = ""`.

    Null becomes empty, and a non-list becomes empty, as in `FootageQueryAnswer`'s validators.
    Extra keys such as `"model"` are ignored (`model_config extra="ignore"`).
  - `CARD_PROMPT: str`: the spike prompt in `D:/thoth-tmp/footage-spike/spike.py`, word for word,
    plus one rule: "queries are in the language of the post".
  - `REFINE_PROMPT: str` for round 2. It gets the card and the top 15 titles and channels, and
    returns the same JSON with new aliases or corrections plus up to 3 new `queries`.
  - `card_material(main: SourceReport, figures: Sequence[dict], transcript: str) -> str`: JSON of
    caption, owner, `published_at`, figures, the top 25 comments by likes, and the transcript
    (first 1500 characters).
  - `class CardModel(Protocol)`:
    `async def card(self, system: str, material: str) -> ContextCard | None`.
- **Adapter:** `OpenRouterCardModel(api_key: str, models: Sequence[str])`. It posts to
  `/chat/completions` with `response_format={"type": "json_object"}`, `max_tokens=1500` and
  `timeout=60`.
  - It parses the text between the first `{` and the last `}`, and tries the next model on any
    failure, including empty `content`. If every model fails it returns `None`.
  - It records cost through `metering.record_model_run`, or the planner's raw-httpx metering
    helper (`assembly/adapters/planner_model.py`), whichever that file uses.

- [ ] **Step 1: Write the failing tests.**
  - `test_the_spike_cards_decode`: each fixture decodes. `mutant_card.json` gives people names
    `["Mutant", "Denny Sumargo"]`, and `"Densu"` is in the second person's aliases.
  - `test_nulls_and_junk_become_empty`: `ContextCard.model_validate({"people": None, "queries":
    "x", "event": None})` gives an empty card.
  - `test_card_material_takes_the_top_comments_by_likes`: with 30 comments, the material holds 25,
    and the most-liked is first.
  - In `test_context_model.py`, with `respx`:
    - `test_an_empty_answer_falls_to_the_next_model`: the first model's `content` is `None`, the
      second returns `mutant_card.json`, and the result has 2 people;
    - `test_every_model_failing_gives_none`.
- [ ] **Step 2: Run them and see them fail.**
  `make test T=tests/footage/test_context.py` and `T=tests/footage/test_context_model.py`.
  Expected: ImportError.
- [ ] **Step 3: Implement `context.py` (types, prompts, `card_material`), the adapter, and the two
  settings.**
- [ ] **Step 4: Run them again.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(footage): add the context card and its model"`

### Task 2: Context queries, the date window and the context gate

**Files:**
- Modify: `python/src/thoth_control_plane/footage/context.py`
- Test: `python/tests/footage/test_context.py`
- Fixture: `python/tests/fixtures/footage/context/mutant_candidates.json`. It is exported
  read-only from stage1:

  ```sql
  select url, platform, owner_handle, caption, source_duration
  from footage_candidates
  where workflow_id = 'wf_4c7961fc1cbafda54186bcbd';
  ```

  That is 70 rows. Commit them as JSON.

**Interfaces:**
- Consumes: `ContextCard` (Task 1), and `norm` from `footage/gates.py`.
- Produces:
  - `card_names(card: ContextCard) -> list[str]`: every person name and alias, normalised by
    `norm`, with "?" stripped, at least 3 characters, deduplicated, longest first.
  - `event_terms(card: ContextCard) -> list[str]`: the event's and place's content words, using
    `domain/planner.content_words`.
  - `context_objects(card: ContextCard, queries: Sequence[str]) -> list[FootageObject]`: one per
    query, with `query[:100]`. The `visual` is "<first card person> in person, at <event>"
    (`person=True`) when a person is named in the query, else `card.event[:300]` or
    `DEFAULT_VISUAL`. `_storable` is applied by the caller as today.
  - `in_window(published_at: str | None, main_published: str | None, now: datetime) -> bool`:
    true when the time is unknown, or when it falls from 30 days before `main_published` to `now`.
  - `context_reason(text: str, card: ContextCard) -> Literal["story"] | None`: None when `norm(text)`
    contains a card name as whole words, or two `event_terms`; else `"story"`.

- [ ] **Step 1: Write the failing tests.**
  - `test_short_and_marked_aliases_are_dropped`: a card with the aliases "TG", "Rocky?" and
    "Bung Rocky" gives names `["bung rocky", "rocky"]` with no `"tg"`.
  - `test_a_name_matches_whole_words_only`: with the name `"sandy"`, `"sandyakala"` gives
    `"story"` and `"sandy walsh cetak gol"` gives `None`.
  - `test_the_mutant_candidates_pass_on_the_card`: with `mutant_card.json` round-1-refined to
    include the alias `"Saiful"` (add it in the test), these pass:
    - "SAIFUL BUKAN MUTAN ❗️❗️❗️❗️ #curhatbangdennysumargo…";
    - "Momen Saeful temui Denny Sumargo di acara Urban Sneaker Society…";
    - "Detik-detik Pria Mengamuk di Depan Denny Sumargo hingga Tendang Kursi…".

    Every caption from the query `"sneakers"` gives `"story"`.
  - `test_an_unknown_time_stays_in_the_window`: `in_window(None, "2026-11-10T11:16:32Z", now)` is
    True. `"2026-10-01T00:00:00Z"` is False, and `"2026-11-12T00:00:00Z"` is True with `now` =
    2026-11-14.
  - `test_context_objects_mark_person_queries`: from `mutant_card.json`, "Mutant USS Denny Sumargo"
    gives `person=True` and a visual starting "Mutant in person"; "Pria bawa pedang Urban Sneaker
    Society" gives `person=False`.
- [ ] **Step 2: Run them.** Expected: FAIL (names undefined).
- [ ] **Step 3: Implement the five functions.**
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(footage): match candidates against the context card"`

### Task 3: Caption moments in long videos

**Files:**
- Create: `python/src/thoth_control_plane/footage/moments.py`
- Create: `python/src/thoth_control_plane/footage/adapters/captions.py`
- Modify: `python/src/thoth_control_plane/acquisition/youtube_service.py`. `YtDlpClient.__init__`
  gains a keyword `options: dict[str, Any] | None = None`, merged after `YTDLP_OPTIONS` on every
  call.
- Modify: `python/src/thoth_control_plane/footage/adapters/search.py`. The footage YouTube search
  builds `YouTubeSearchDiscovery(client=YtDlpClient(options={"extractor_args": {"youtube":
  {"lang": ["id"]}}}))`.
- Test: `python/tests/footage/test_moments.py`, plus one test in the existing YouTube client
  tests.
- Fixture: `python/tests/fixtures/footage/context/podcast_captions.json3`, the first 300 caption
  events of `Sy_S4TgvKbY`, fetched once in the worker the way the spike did. Commit it.

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class CaptionLine: start: float; text: str`;
  - `parse_json3(data: bytes) -> list[CaptionLine]`: events with text, `tStartMs/1000`, segments
    joined and stripped;
  - `pick_moments(lines: Sequence[CaptionLine], names: Sequence[str], terms: Sequence[str],
    limit: int = 3) -> list[float]`.

    A line scores 2 per name and 1 per term it contains as whole words, after `norm`. Only lines
    with a name count. Scores are compared highest first, earlier first on ties. Lines before 30 s
    are skipped, kept moments are at least 60 s apart, and the result is sorted ascending.
  - `section(moment: float) -> tuple[float, float]`: `(max(0, moment - 1), max(0, moment - 1) + 8)`;
  - `class CaptionPort(Protocol)`: `async def captions(self, url: str, language: str) -> bytes | None`;
  - adapter `YtDlpCaptionFetcher(client: YtDlpClient)`.

    It reads `automatic_captions[language]` (then `subtitles[language]`) for the json3 entry from
    an `extract(url, comments=False)` info dict, and fetches it with httpx (timeout 20). It returns
    `None` on any failure and logs a warning.

- [ ] **Step 1: Write the failing tests.**
  - `test_the_podcast_captions_parse`: the fixture gives more than 250 lines; the first line's
    `start` is less than 1.
  - `test_moments_need_a_name_and_skip_the_intro`: names `["mutan", "denny sumargo"]` and terms
    `["podcast"]` on the fixture give at most 3 moments, all at 30 s or later, pairwise at least
    60 s apart, the first within ±5 s of 165.4 (02:45.4 "Mutan Tretan.").
  - `test_no_name_no_moment`: names `["rocky gerung"]` on the fixture give `[]`.
  - `test_a_section_is_eight_seconds_from_a_second_before`: `section(165.4) == (164.4, 172.4)` and
    `section(0.5) == (0, 8)`.
  - YouTube client: `test_client_options_reach_every_call`. A fake factory records the options;
    `YtDlpClient(factory, options={"extractor_args": {"youtube": {"lang": ["id"]}}})` passes them
    on `extract`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement `moments.py`, the adapter, the client option and the search wiring.**
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(footage): find moments in long videos by captions"`

### Task 4: Credits, own accounts and the credit label

**Files:**
- Create: `python/src/thoth_control_plane/footage/reposts.py`
- Modify: `python/src/thoth_control_plane/footage/models.py` (add `"repost"` to `RejectReason`)
- Modify: `python/src/thoth_control_plane/assembly/planner_service.py:222`. The handles map becomes
  `credit_label(i.platform, i.owner_handle)`.
- Test: `python/tests/footage/test_reposts.py`, and one test in
  `python/tests/assembly/test_planner_service.py`

**Interfaces:**
- Consumes: `attribution/credit.py` (`text_handles`, `text_rule_credit`, `normalize`), and
  `ContextCard` and `card_names`.
- Produces:
  - `credited_account(text: str) -> str | None`.

    It returns the first handle from `text_rule_credit`, then `text_handles`. Failing those, it
    returns the name after "sumber:", "source:", "via" or "youtube/", up to the end of the line or
    a "|", normalised; else None.
  - `is_own_account(owner_handle: str, card: ContextCard) -> bool`.

    It is true when `normalize(owner_handle)` equals a normalised entry of any person's `accounts`,
    or contains a card name with spaces removed and length 6 or more ("curhatbang" for "CURHAT
    BANG" accounts; "dennysumargo").
  - `credit_label(platform: str | None, handle: str | None) -> str | None`.

    It returns "YouTube/<handle without @>" for "youtube", "@<handle without @>" otherwise, and
    None for no handle.

- [ ] **Step 1: Write the failing tests.**
  - `test_credits_are_read_from_common_forms`:
    - "Sumber: YouTube Curhat Bang | Tribun" gives `"youtube curhat bang"`;
    - "cr: @curhatbang" gives `"curhatbang"`;
    - "Detik-detik Pria Mengamuk di Depan Denny Sumargo" gives `None`.
  - `test_own_accounts_come_from_the_card`: a card whose Denny Sumargo person has
    `accounts=["@curhatbang"]` makes `is_own_account("curhatbang", card)` True and
    `is_own_account("tribunnewsbogor", card)` False.
  - `test_credit_labels`: `("youtube", "@curhatbang")` gives "YouTube/curhatbang", `("tiktok",
    "jnrksn")` gives "@jnrksn", and `(None, None)` gives None.
  - Planner service: `test_a_youtube_footage_item_is_credited_with_its_platform`. A materials
    footage item with platform "youtube" and owner "@curhatbang" gives the planned shot the credit
    "YouTube/curhatbang". Build it from the existing planner-service fixtures in that test file.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them, plus `make test T=tests/assembly`.** Expected: PASS. Existing credit
  assertions on TikTok handles still pass.
- [ ] **Step 5: Commit.** `git commit -m "feat(footage): read reposts' credits and label credits by platform"`

### Task 5: Migration 0033 and the library store

**Files:**
- Create: `python/migrations/editor/0033_footage_library.sql`
- Create: `python/migrations/editor/alembic/versions/0033_footage_library.py`, a copy of 0032's
  shape with `revision = "0033"` and `down_revision = "0032"`.
- Modify: `python/src/thoth_control_plane/infrastructure/footage_models.py` (`FootageRunRow.context`,
  `FootageLibraryRow`)
- Modify: `python/src/thoth_control_plane/infrastructure/footage_store.py`
- Modify: `python/src/thoth_control_plane/footage/models.py` (`RunView.context`, `LibraryClip`)
- Modify: `python/src/thoth_control_plane/footage/ports.py` (`FootageState` gains the methods below)
- Test: `python/tests/footage/test_store.py`. The Postgres variant goes wherever the existing
  footage store Postgres tests live.

**Interfaces:**
- **SQL:**
  - `alter table footage_runs add column context jsonb null;`
  - `create table footage_library` with these columns:
    - `id text primary key`;
    - `workspace_id text not null references workspaces(workspace_id)`;
    - `url text not null`;
    - `platform text not null`;
    - `owner_handle text not null default ''`;
    - `published_at text null`;
    - `section_start double precision not null default 0`;
    - `section_end double precision null`;
    - `media_location text not null`;
    - `media_checksum text not null`;
    - `hashes jsonb not null default '[]'`;
    - `names jsonb not null default '[]'`;
    - `event text not null default ''`;
    - `first_workflow_id text not null`;
    - `created_at timestamptz not null default now()`.

    Add `unique (workspace_id, url, section_start)` and an index on `(workspace_id)`.
- **`@dataclass(frozen=True) class LibraryClip`:** `url`, `platform`, `owner_handle`, `published_at`,
  `section_start`, `section_end`, `media_location`, `media_checksum`, `hashes: list[int]`,
  `names: list[str]`, `event: str`.
- **`FootageStore` methods:**
  - `set_context(workflow_id: str, context: dict | None) -> None`;
  - `RunView.context: dict | None = None`;
  - `workspace_of(workflow_id: str) -> str | None`, through `workflow_runs.project_id` and then
    `projects.workspace_id`;
  - `add_library(workspace_id: str, workflow_id: str, clip: LibraryClip) -> None`.

    It first checks the workspace's rows: when a row's hashes match by `is_duplicate`, the clip is
    merged into that row. The row is replaced only if the new clip's `published_at` is earlier.
    Otherwise the clip is inserted. A unique-key conflict is a no-op.
  - `library(workspace_id: str, names: Sequence[str], since: datetime, until: datetime) ->
    list[LibraryClip]`.

    It returns rows whose `names` share at least one name and whose `published_at` is in
    `[since, until]` or null, newest first, at most 12.

- [ ] **Step 1: Write the failing tests** (SQLite, as `test_store.py` does now).
  - `test_context_round_trips`.
  - `test_a_library_clip_is_found_by_a_shared_name`.
  - `test_another_workspace_sees_nothing`: the same names under "ws2" give `[]`.
  - `test_a_copy_merges_into_the_earlier_original`: the same hashes with a later date keep the
    earlier row's url, and with an earlier date replace it; the count stays 1.
  - `test_the_run_finds_its_workspace`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement the SQL, the ORM rows, the store methods and the view fields.**
- [ ] **Step 4: Run `make test T=tests/footage/test_store.py`, and the Postgres variant with
  `make test-postgres`.** Expected: PASS. The migration applies on a fresh database after 0032.
- [ ] **Step 5: Commit.** `git commit -m "feat(footage): add the footage library table and store"`

### Task 6: The context path in the builder: card, two rounds, gate and order

**Files:**
- Modify: `python/src/thoth_control_plane/footage/service.py` (`FootagePorts`, `FootageInputs`,
  `FootageBuilder.__init__`, `_build`, a new `_context` method, `_gate`, `_story`)
- Test: `python/tests/footage/test_service.py` (fake ports already exist there; add fake
  `CardModel` and `CaptionPort`)

**Interfaces:**
- Consumes: Tasks 1, 2, 4 and 5.
- Produces:
  - `FootagePorts` gains `card: CardModel | None = None`, `captions_text: CaptionPort | None =
    None` and `library_media: Callable[[str, Path], Awaitable[None]] | None = None`.
  - `FootageInputs` gains `figures: list[dict] = []` and `transcript: str = ""`.
  - `FootageBuilder.__init__` gains `context_enabled: bool = False`.
- **The path:** with `context_enabled` and `ports.card`, on a new run, `_build` calls
  `_context(main, inputs) -> tuple[ContextCard, list[FootageObject]] | None`:
  1. **The card:** `card_material` goes to `ports.card.card(CARD_PROMPT, …)`. The card is stored
     with `set_context` and the run started with `context_objects(card, card.queries[:4])`.
  2. **Round 1:** search with those objects. Candidates outside `in_window`, or failing
     `context_reason` on caption plus owner handle, are rejected `story`. A candidate that passes
     gets `story_score` 1.0 if `is_own_account`, else 0.5, so `_check_all`'s queue order puts own
     accounts first.
  3. **Round 2:** it runs only when fewer than `MAX_FOOTAGE` round-1 candidates pass. The top 15
     round-1 captions and handles go to `REFINE_PROMPT`; the updated card is stored; the up to 3
     new queries become objects appended to `run.objects`, and are searched and gated the same
     way.
  4. **Fallback:** if the card is None, the old path runs (`_objects`, then `_story`) exactly as
     today, and a warning is logged.
- `_story` is skipped on the context path. The cosine score is still computed and stored for
  comparison (`self._store.score`), without rejecting.
- On the context path, `_creator` decides each listed post with `in_window` and `context_reason`
  instead of `verdict(scores…)` and `closest` (spec 4.3.6). A passing post gets `story_score` 1.0.
- A retry reuses `run.context`, and the card model is not called again.

- [ ] **Step 1: Write the failing tests.**
  - `test_the_context_path_searches_people_queries`: the fake card is `mutant_card.json`; the
    searched queries are exactly the card's first 4.
  - `test_sneakers_are_rejected_and_saiful_passes`: the fake search returns two TikTok videos, one
    "SAIFUL BUKAN MUTAN #curhatbangdennysumargo" and one "Sneakers hitam putih". The refined card
    adds Saiful. The first stays pending and the second is rejected `story`.
  - `test_round_two_adds_queries_from_titles`: the round-1 hits pass fewer than 6; the fake refine
    returns `queries=["saiful denny sumargo"]`, which is searched, and `run.objects` gains it.
  - `test_own_account_candidates_are_screened_first`: two passing candidates, one from
    "curhatbang". The first `_check` call is for the curhatbang URL.
  - `test_no_card_falls_back_to_object_queries`: the fake card returns None; the old
    `ports.queries.read` is called and today's objects are searched.
  - `test_a_retry_reuses_the_stored_card`: a second build on the same workflow calls the card
    model 0 more times.
  - `test_context_disabled_runs_today`: `context_enabled=False` never calls `ports.card`.
  - `test_creator_posts_pass_the_context_gate`: a fake creator listing with "Urban Sneaker Society
    #densu #Dennysumargo" and "Kuta beach sunset today". The first stays pending and the second is
    rejected `story`.
- [ ] **Step 2: Run `make test T=tests/footage/test_service.py`.** Expected: the new tests FAIL and
  the old ones pass.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the footage tests again.** Expected: all PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(footage): search footage from the context card in two rounds"`

### Task 7: Long-video sections and repost tracing in the builder

**Files:**
- Modify: `python/src/thoth_control_plane/footage/service.py` (`_gate`, `_check`, a new
  `_sections` and a new `_trace`)
- Modify: `python/src/thoth_control_plane/footage/gates.py` (`text_gate` gains `long_ok: bool =
  False`: with it, the 900 s cap is skipped and the caller decides)
- Test: `python/tests/footage/test_service.py`, `python/tests/footage/test_gates.py`

**Interfaces:**
- Consumes: Task 3 (`CaptionPort`, `parse_json3`, `pick_moments`, `section`), Task 4
  (`credited_account`), and Task 5.
- **Sections:** on the context path, a YouTube candidate over `MAX_SECONDS` that passes the context
  gate is handled by `_sections`:
  1. `ports.captions_text.captions(url, "id")`, then `pick_moments(…, card_names(card),
     event_terms(card))`;
  2. each moment adds a `NewCandidate` with `url=f"{url}#t={start:.1f}"`, the same owner and query,
     `source="section"` and `source_duration=8.0`;
  3. the parent is rejected `duration`.

  No captions or no moment means the parent is rejected `duration` and nothing is added. At most 3
  long videos are handled per run, by passing order.
- **`_check` for a section:** a URL with `#t=` downloads `url` without the fragment, with the window
  `section(t)`, and `clip_start = t`.
- **`_trace`:** a passing candidate whose caption gives `credited_account(...)` not equal to its
  own owner is a repost.
  1. `ports.creator.listing_of(platform, credited, CREATOR_LISTING)` is fetched once per credited
     account per run.
  2. Its videos go through `text_gate` (the main gate included), `in_window` and `context_reason`.
     The passing ones are added with `source="trace"`, `story_score=1.0`, and the repost is
     rejected `"repost"`.
  3. With no listing or nothing passing, the repost stays pending and is checked like any
     candidate, so OCR still rejects burned-in text.
- **Duplicates:** a picture match against an admitted clip stays `duplicate`.
  > Ruling: the spec's 4.5.4 asks for `repost` there. The existing reason has the same effect, and
  > relabelling it would need the original's owner in `_check`.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_long_video_becomes_sections_at_its_moments`: a fake search returns a 3219 s YouTube
    video titled "MASTER SAIFUL MENGAMUK⁉️ JANGAN PANGGIL AKU MUTANT‼️". The fake captions return
    the podcast fixture. Its section candidates have `#t=` fragments; the first lies within ±5 s
    of 164.4; the parent is rejected `duration`.
  - `test_a_long_video_without_a_named_line_downloads_nothing`: the captions fixture with the card
    names `["rocky gerung"]` gives no section, the parent `duration`, and the fake downloader is
    never called.
  - `test_a_section_downloads_its_window`: the fake downloader receives the fragment-free URL and
    the window `(164.4, 172.4)`; the admitted clip has `clip_start == 164.4`.
  - `test_a_credited_repost_is_replaced_by_its_original`:
    - the candidate "Master Saiful Ngamuk… | Sumber: YouTube curhatbang" comes from
      "tribunbanten";
    - the fake listing for "curhatbang" returns the podcast;
    - the podcast is added with `source="trace"`, and the repost is rejected `repost`.
  - `test_a_traced_original_that_is_the_main_post_is_rejected_main`: the fake listing returns the
    main post's URL, which is rejected `main`, and the repost stays pending.
  - `test_long_ok_skips_the_duration_cap` in `test_gates.py`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `make test T=tests/footage`.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(footage): cut long videos at caption moments and trace reposts"`

### Task 8: Library read and write in the builder

**Files:**
- Modify: `python/src/thoth_control_plane/footage/service.py` (`_context` looks up the library;
  `_check` writes on admit)
- Test: `python/tests/footage/test_service.py`

**Interfaces:**
- Consumes: Task 5's store methods, and `ports.library_media` (fetch a stored location into a
  local path).
- **Read:** after the card, when `workspace_of(workflow)` is known,
  `library(workspace, card_names(card), since, until)` with the Task 2 window.
  1. Each clip, up to `MAX_FOOTAGE`, is added as a `NewCandidate` (`source="library"`, its own
     url with the section fragment when `section_start > 0`).
  2. It is then admitted directly. `library_media(clip.media_location, root / new_location)`
     copies the file, and an `AdmittedClip` is built with the stored hashes. Library clips are
     never searched again and never vision-checked again.
  3. A copy failure rejects that candidate `media_failed` and the run goes on.
- **Write:** every admit on the context path calls `add_library(workspace, workflow,
  LibraryClip(…, names=card_names(card), event=card.event))`. A store failure there logs a warning
  and never fails the admit.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_second_run_on_the_story_reuses_the_library`: run A admits a clip; run B (same
    workspace, a card with an overlapping name) admits it from the library. The fake downloader is
    not called for it in run B, and the fake search is still called for the remaining quota.
  - `test_a_library_copy_failure_is_one_reject`: `library_media` raises; that candidate is
    `media_failed` and the run status is decided by the rest.
  - `test_an_admit_writes_the_library_with_the_card_names`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `make test T=tests/footage`.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(footage): reuse and grow the footage library across runs"`

### Task 9: Production wiring, the offline replay, and the records

**Files:**
- Modify: `python/src/thoth_control_plane/activities/footage.py`
  - `build_production_footage` adds `card=OpenRouterCardModel(key, [settings.THOTH_FOOTAGE_CARD_MODEL,
    settings.THOTH_FOOTAGE_QUERY_MODEL])`, `captions_text=YtDlpCaptionFetcher(YtDlpClient())` and
    `library_media`, a wrapper over the activity's `MediaStore.fetch`, run in a thread;
  - `context_enabled=settings.THOTH_FOOTAGE_CONTEXT_ENABLED`;
  - `_run` passes `figures` and `transcript` into `FootageInputs`, when the run already has them
    at this stage. Otherwise they are empty: check the workflow order in `workflows/` and
    ledger a ruling.
- Modify: `.env.example` or the settings docs, wherever `THOTH_FOOTAGE_QUERY_MODEL` is documented.
- Modify: `CHANGELOG.md` (a new entry with a **Next steps** section),
  `.superpowers/sdd/2026-11-12-footage-library/progress.md`, and `docs/ROADMAP.md` (step 3
  status; additions only).
- Test: `python/tests/footage/test_replay.py`, and the existing activity wiring test, if any.

- [ ] **Step 1: Write the failing tests.**
  - `test_the_mutant_run_replays_under_the_context_gate`: using `mutant_candidates.json` and
    `mutant_card.json` plus the alias "Saiful", `context_reason` passes at least the 3 captions
    named in Task 2, and none of the 21 rows whose query was "sneakers" or "pedang excalibur…".
  - `test_production_wiring_builds_the_context_ports`: `build_production_footage` with a settings
    stub has `ports.card` and `ports.captions_text` set and `context_enabled` True.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement the wiring and the records.**
- [ ] **Step 4: Run the full gate: `make test`, `make lint`.** Expected: all pass. Record the counts
  in CHANGELOG.
- [ ] **Step 5: Commit.** `git commit -m "feat(footage): wire the context path into the run"`, then
  `git commit -m "docs: record the footage library build"`.

**Out of this plan (each its own gate, with the operator's yes):**
- push and CI;
- the deploy to stage1 from the branch image, which applies migration 0033;
- one live run on the Mutant post, judged blind by the operator;
- merge.

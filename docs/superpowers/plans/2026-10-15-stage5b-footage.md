# Stage 5b Footage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add up to six gated, checked, windowed b-roll clips from TikTok, YouTube, and X (or the
main's own Instagram carousel) to the Content Set, with every decision stored in PostgreSQL so a
retry resumes.

**Architecture:** A new `footage/` package (domain logic behind ports, adapters at the edge) runs
as its own `build_footage` activity and `footage` stage between attribution and assembly. State
lives in three new tables in the control-plane database (SQLAlchemy ORM, editor migration 0010);
clips are files under `reports/<workflow_id>/footage/`. Assembly reads the admitted clips into
`ContentSet.footage`.

**Tech Stack:** Python 3.12, Temporal, SQLAlchemy 2 + Alembic, Pydantic 2, Agno over OpenRouter,
Scrapling (browser XHR capture), yt-dlp, ffmpeg/ffprobe, RapidOCR, OpenCV, onnxruntime +
tokenizers (already installed), pytest.

**Spec:** `docs/superpowers/specs/2026-10-14-stage5b-footage-design.md` (with its 2026-10-14
amendment). Research: `docs/research/2026-10-14-stage5b-footage-research.md` (sections 9 and 10).

## Global Constraints

- At most 6 footage items per Content Set and 2 per query; the search stops when 6 are admitted.
- At most 4 objects (queries); no person query.
- Search platforms: `tiktok`, `youtube`, `x`; carousel footage is `instagram`.
- Up to 8 results per platform per query; YouTube details the 5 most viewed.
- Text gates in order: main, aggregator, spam, reaction text, duration (3 s to 900 s when known),
  story (`THOTH_FOOTAGE_STORY_MIN`, default 0.33). An empty caption fails the story gate.
- Window: whole clip when its duration is 30 s or less; else 20 s starting at 10% of the clip
  (at least 3 s, at most `duration - 20`); unknown duration: 0 to 30 s.
- Frame checks: 5a OCR (`subtitle` rejected), one vision call on 3 frames (`commentary` and
  `shows_object = no` rejected), dHash duplicate (Hamming at most 10 on at least half the frames).
- At most 3 candidates checked at once, 90 s each; the stage stops at 720 s with what it admitted.
- Activity: `start_to_close` 20 minutes, heartbeat 2 minutes, 3 attempts; a footage failure never
  fails the workflow.
- Downloads go direct, never through an account proxy. X search leases the X account.
- Never stored or logged: CDN URLs, cookies, proxies, prompts, raw model output, captions in logs.
- A missing required tool or model is an explicit error, never a skip (tests included).
- No new Python dependency; no new compose service.
- Repo artifacts in English. Commits: one `git commit -m "<subject>"`, at most 72 characters, no
  body, no trailer, no AI attribution. Never stage `graphify-out/`, `.superpowers/`,
  `.understand-anything/`, `.env.stage1.local*`, `dashboard/dist/`, or `design/`; files under
  `docs/superpowers/` need `git add -f`.
- CRLF files (`Dockerfile`, `.github/workflows/*.yml`, `CHANGELOG.md`, `docs/**`) are edited at
  the byte level so their line endings stay CRLF.
- Tests run from `python/`: `uv run pytest <path> -q` (the conftest guard blocks non-loopback
  network; never add a live test).

## Review Focus

1. **A retry after a crash mid-check** — a candidate left `pending` with a half-written window
   file must be redone cleanly, never admitted twice, and its `.part` must not linger
   (Task 8, `test_a_retry_redoes_pending_and_keeps_admitted`).
2. **The same URL from two platforms or two queries** — it must become one candidate, not two
   rows or a unique-constraint crash (Task 8, `test_one_url_found_twice_is_one_candidate`).
3. **A query the LLM returns with characters `KeywordDiscovery` refuses** — that query is skipped,
   the others still search (Task 8, `test_an_invalid_query_is_skipped`).
4. **A main without a video (images or a card)** — the duplicate check runs without main hashes
   instead of failing (Task 8, `test_a_main_without_video_still_gets_footage`).
5. **An X search that simply finds nothing** — the X account must stay healthy: `blocked`
   cools an account down for 15 min, then 1 h, 6 h, 24 h, for every X job. Only a refusal (HTTP
   400 or above, or a GraphQL error body) reports `blocked`; an empty timeline or no captured
   response reports no outcome (Task 6, `test_only_a_refusal_cools_the_x_account_down`).

---

## File structure

Create:

| Path (under `python/`) | Responsibility |
|---|---|
| `src/thoth_control_plane/footage/__init__.py` | package marker |
| `src/thoth_control_plane/footage/models.py` | footage domain types, store views, reason enums |
| `src/thoth_control_plane/footage/gates.py` | text gates ported from Scout |
| `src/thoth_control_plane/footage/queries.py` | query prompt and normalization |
| `src/thoth_control_plane/footage/frames.py` | window choice, vision sample times, dHash |
| `src/thoth_control_plane/footage/ports.py` | protocols the builder needs |
| `src/thoth_control_plane/footage/service.py` | `FootageBuilder` |
| `src/thoth_control_plane/footage/adapters/__init__.py` | package marker |
| `src/thoth_control_plane/footage/adapters/queries.py` | `AgnoQueryModel` |
| `src/thoth_control_plane/footage/adapters/embedder.py` | `OnnxEmbedder` |
| `src/thoth_control_plane/footage/adapters/youtube.py` | `YouTubeSearchDiscovery` |
| `src/thoth_control_plane/footage/adapters/x_search.py` | `XSearchDiscovery`, `parse_search` |
| `src/thoth_control_plane/footage/adapters/search.py` | `PlatformSearch` and its factories |
| `src/thoth_control_plane/footage/adapters/vision.py` | `AgnoFootageJudge` |
| `src/thoth_control_plane/footage/adapters/downloader.py` | `YtDlpClipDownloader` |
| `src/thoth_control_plane/infrastructure/footage_models.py` | ORM rows |
| `src/thoth_control_plane/infrastructure/footage_store.py` | `FootageStore` |
| `src/thoth_control_plane/activities/footage.py` | `build_footage` activity |
| `migrations/editor/0010_footage.sql` | tables |
| `migrations/editor/alembic/versions/0010_footage.py` | Alembic revision |
| `tests/footage/__init__.py` and the test files named in each task | tests |

Modify: `assembly/models.py`, `assembly/service.py`, `assembly/figures.py`,
`activities/content_assembly.py`, `attribution/adapters/discovery.py`, `config.py`,
`domain/models.py`, `workflows/source_investigation.py`, `infrastructure/temporal_gateway.py`,
`worker.py`, `docker/fetch_speech_models.py`, `.github/workflows/container-image.yml`,
`tests/deployment/test_container_contract.py`, `tests/operations/test_editor_migrations.py`,
`CHANGELOG.md`, `docs/python-scout-migration-roadmap.md`.

---

### Task 1: Content Set footage contract

**Files:**
- Modify: `python/src/thoth_control_plane/assembly/models.py`
- Test: `python/tests/assembly/test_models.py`

**Interfaces:**
- Produces: `assembly.models.Footage`, `assembly.models.FootageStatus`
  (`Literal["ok", "none", "disabled", "unavailable"]`), `MAX_FOOTAGE = 6`,
  `ContentSet.footage: list[Footage]`, `ContentSet.footage_status: FootageStatus = "disabled"`.

- [ ] **Step 1: Write the failing tests** (append to `tests/assembly/test_models.py`; reuse the
  file's existing helpers for a valid `ContentSet`; if it has none, build one inline as below)

```python
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from thoth_control_plane.assembly.models import ContentSet, Footage, MainOcr

CLEAN_OCR = {
    "analyzed_at": datetime(2026, 10, 15, tzinfo=UTC),
    "requested_frames": 12,
    "valid_frames": 12,
    "outcome": "clean",
    "trim_start": 0.0,
    "mute_audio": False,
}


def _footage(**changes: object) -> dict[str, object]:
    item: dict[str, object] = {
        "source": "search",
        "url": "https://www.tiktok.com/@kreator/video/7400000000000000001",
        "platform": "tiktok",
        "owner_handle": "kreator",
        "query": "banjir jakarta",
        "visual": "a flooded street with cars half under water",
        "caption": "banjir lagi",
        "description": "Cars drive through a flooded street.",
        "video": {
            "location": "reports/wf_a/footage/abc.mp4",
            "media_type": "video/mp4",
            "checksum": "sha256:" + "a" * 64,
            "bytes": 2048,
            "duration_seconds": 20.0,
        },
        "clip_start": 3.0,
        "ocr": CLEAN_OCR,
        "story_score": 0.61,
        "shows_object": "yes",
    }
    item.update(changes)
    return item


def _set(**changes: object) -> dict[str, object]:
    document: dict[str, object] = {
        "workflow_id": "wf_a",
        "attribution_verdict": "none",
        "main": {
            "source": "input",
            "url": "https://www.instagram.com/p/ABC123/",
            "platform": "instagram",
            "owner_handle": "akun",
            "kind": "card",
            "card": {
                "location": "reports/wf_a/cards/post.png",
                "media_type": "image/png",
                "checksum": "sha256:" + "b" * 64,
                "bytes": 2048,
            },
        },
        "figures_status": "none",
    }
    document.update(changes)
    return document


def test_a_content_set_without_footage_says_disabled() -> None:
    content_set = ContentSet.model_validate(_set())
    assert content_set.footage == []
    assert content_set.footage_status == "disabled"


def test_footage_status_ok_exactly_when_footage_is_present() -> None:
    ContentSet.model_validate(_set(footage=[_footage()], footage_status="ok"))
    with pytest.raises(ValidationError):
        ContentSet.model_validate(_set(footage=[_footage()], footage_status="none"))
    with pytest.raises(ValidationError):
        ContentSet.model_validate(_set(footage=[], footage_status="ok"))


def test_footage_urls_are_unique_and_never_the_main() -> None:
    with pytest.raises(ValidationError):
        ContentSet.model_validate(_set(footage=[_footage(), _footage()], footage_status="ok"))
    with pytest.raises(ValidationError):
        ContentSet.model_validate(
            _set(footage=[_footage(url="https://www.instagram.com/p/ABC123/")], footage_status="ok")
        )


def test_subtitled_footage_is_refused() -> None:
    subtitled = {
        **CLEAN_OCR,
        "outcome": "subtitle",
        "mute_audio": True,
        "subtitle_blur": [{"x": 0.1, "y": 0.8, "w": 0.8, "h": 0.1}],
    }
    with pytest.raises(ValidationError):
        Footage.model_validate(_footage(ocr=subtitled))


def test_footage_holds_at_most_six_items() -> None:
    items = [
        _footage(url=f"https://www.tiktok.com/@kreator/video/740000000000000000{n}")
        for n in range(7)
    ]
    with pytest.raises(ValidationError):
        ContentSet.model_validate(_set(footage=items, footage_status="ok"))
    assert MainOcr.model_validate(CLEAN_OCR).outcome == "clean"
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd python && uv run pytest tests/assembly/test_models.py -q -k "footage or disabled or subtitled"`
Expected: FAIL — `ImportError: cannot import name 'Footage'`.

- [ ] **Step 3: Implement** in `assembly/models.py`

Add after `MAX_FIGURES = 5`:

```python
MAX_FOOTAGE = 6
FootageStatus = Literal["ok", "none", "disabled", "unavailable"]
```

Add before `class ContentSet`:

```python
class Footage(StrictModel):
    """One b-roll clip (spec 2026-10-14, section 6): a window file and its checks."""

    source: Literal["search", "carousel"]
    url: HttpUrl
    platform: Literal["tiktok", "youtube", "x", "instagram"]
    owner_handle: TikTokHandle
    published_at: PublishedAt | None = None
    engagement: dict[str, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    query: Annotated[str, Field(min_length=1, max_length=100)]
    visual: Annotated[str, Field(max_length=300)] = ""
    caption: Annotated[str, Field(max_length=2_000)] = ""
    description: Annotated[str, Field(max_length=300)] = ""
    video: MediaRef
    clip_start: Seconds = 0.0
    ocr: MainOcr
    story_score: Fraction
    shows_object: Literal["yes", "partly"]

    @model_validator(mode="after")
    def renderable(self) -> Footage:
        if self.video.media_type != "video/mp4":
            raise ValueError("footage must be video/mp4")
        if self.ocr.outcome == "subtitle":
            raise ValueError("the renderer refuses subtitle-classified footage")
        return self
```

In `class ContentSet`, replace

```python
    # Always empty in 5a; 5b defines footage items.
    footage: tuple[()] = ()
```

with

```python
    footage: list[Footage] = Field(default_factory=list, max_length=MAX_FOOTAGE)
    footage_status: FootageStatus = "disabled"
```

and extend its validator (rename it `consistent`, keep the figures rule):

```python
    @model_validator(mode="after")
    def consistent(self) -> ContentSet:
        if (self.figures_status == "ok") != bool(self.figures):
            raise ValueError("figures_status is ok exactly when figures are present")
        if (self.footage_status == "ok") != bool(self.footage):
            raise ValueError("footage_status is ok exactly when footage is present")
        urls = [str(item.url) for item in self.footage]
        if len(set(urls)) != len(urls) or str(self.main.url) in urls:
            raise ValueError("footage URLs are unique and never the main's")
        return self
```

- [ ] **Step 4: Run the assembly tests**

Run: `cd python && uv run pytest tests/assembly -q`
Expected: PASS (5a tests still build a `ContentSet` without footage: `disabled` is the default).

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/assembly/models.py python/tests/assembly/test_models.py
git commit -m "feat(assembly): footage items in the Content Set"
```

---

### Task 2: Footage persistence (migration 0010, ORM, store)

**Files:**
- Create: `python/migrations/editor/0010_footage.sql`
- Create: `python/migrations/editor/alembic/versions/0010_footage.py`
- Create: `python/src/thoth_control_plane/footage/__init__.py`
- Create: `python/src/thoth_control_plane/footage/models.py`
- Create: `python/src/thoth_control_plane/infrastructure/footage_models.py`
- Create: `python/src/thoth_control_plane/infrastructure/footage_store.py`
- Modify: `python/tests/operations/test_editor_migrations.py` (the `MIGRATION_FILES` list)
- Test: `python/tests/footage/__init__.py`, `python/tests/footage/test_store.py`

**Interfaces:**
- Produces (in `footage/models.py`): `FootagePlatform`, `CandidatePlatform`, `RejectReason`,
  `REJECT_REASONS`, `FootageObject`, `NewCandidate`, `CandidateView`, `RunView`, `AdmittedClip`,
  `FootageResult`.
- Produces (in `infrastructure/footage_store.py`): `FootageStore` with
  `connect(database_url) -> FootageStore`, `cached_search(platform, query) -> list[DiscoveredVideo] | None`,
  `save_search(platform, query, videos) -> None`, `run(workflow_id) -> RunView | None`,
  `start_run(workflow_id, objects) -> RunView`, `finish_run(workflow_id, footage_status) -> None`,
  `candidates(workflow_id) -> list[CandidateView]`, `add_candidates(workflow_id, items) -> None`,
  `score(workflow_id, url, story_score) -> None`,
  `reject(workflow_id, url, reason, *, story_score=None, kind=None, shows_object=None, description=None) -> None`,
  `admit(workflow_id, url, clip) -> None`, `reopen(workflow_id, url) -> None`,
  `admitted(workflow_id) -> list[CandidateView]`. All synchronous; callers use `asyncio.to_thread`.
- Ruling carried from the spec: URLs repeated within a run are skipped before they are stored, so
  the reason `seen` is not used; columns `source_duration` (from search) and `clip_duration` (the
  window) replace the spec's single `duration_seconds`.

- [ ] **Step 1: Write the migration files**

`python/migrations/editor/0010_footage.sql`:

```sql
-- Stage 5b footage (spec 2026-10-14): a 24-hour search cache, one run per workflow, and one
-- row per candidate with its decision. Media stay files; rows hold locations and checksums.

CREATE TABLE footage_searches (
    id UUID PRIMARY KEY,
    platform TEXT NOT NULL CHECK (platform IN ('tiktok', 'youtube', 'x')),
    query TEXT NOT NULL CHECK (char_length(query) BETWEEN 1 AND 200),
    results JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    UNIQUE (platform, query)
);
CREATE INDEX footage_searches_expires_at ON footage_searches (expires_at);

CREATE TABLE footage_runs (
    workflow_id TEXT PRIMARY KEY CHECK (char_length(workflow_id) BETWEEN 1 AND 128),
    status TEXT NOT NULL CHECK (status IN ('running', 'done')),
    footage_status TEXT CHECK (footage_status IN ('ok', 'none', 'disabled', 'unavailable')),
    objects JSONB NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ
);

CREATE TABLE footage_candidates (
    id UUID PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES footage_runs (workflow_id) ON DELETE CASCADE,
    url TEXT NOT NULL CHECK (char_length(url) BETWEEN 1 AND 2048),
    platform TEXT NOT NULL CHECK (platform IN ('tiktok', 'youtube', 'x', 'instagram')),
    source TEXT NOT NULL CHECK (source IN ('search', 'carousel')),
    query TEXT NOT NULL,
    visual TEXT NOT NULL,
    owner_handle TEXT NOT NULL,
    caption TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    engagement JSONB NOT NULL,
    source_duration DOUBLE PRECISION,
    status TEXT NOT NULL CHECK (status IN ('pending', 'admitted', 'rejected')),
    reason TEXT CHECK (reason IN (
        'main', 'aggregator', 'spam', 'reaction_text', 'duration', 'story', 'subtitle',
        'commentary', 'object_absent', 'duplicate', 'media_failed', 'vision_unavailable'
    )),
    story_score DOUBLE PRECISION,
    kind TEXT CHECK (kind IN ('footage', 'commentary')),
    shows_object TEXT CHECK (shows_object IN ('yes', 'partly', 'no')),
    description TEXT,
    media_location TEXT,
    media_checksum TEXT,
    media_bytes BIGINT,
    clip_duration DOUBLE PRECISION,
    clip_start DOUBLE PRECISION,
    ocr JSONB,
    position INTEGER,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE (workflow_id, url),
    CHECK ((status = 'rejected') = (reason IS NOT NULL)),
    CHECK (status <> 'admitted' OR (media_location IS NOT NULL AND position IS NOT NULL))
);
```

`python/migrations/editor/alembic/versions/0010_footage.py`:

```python
"""Apply the shipped 0010_footage.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    execute_sql_file(__file__)
```

In `tests/operations/test_editor_migrations.py`, append `"0010_footage.sql",` to the
`MIGRATION_FILES` list in `test_editor_migrations_stay_explicit_forward_only_sql_files`.

- [ ] **Step 2: Write `footage/models.py`**

```python
"""Footage domain types (spec 2026-10-14): objects, candidates, decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, get_args

from pydantic import Field

from thoth_control_plane.domain.models import StrictModel

FootagePlatform = Literal["tiktok", "youtube", "x"]
CandidatePlatform = Literal["tiktok", "youtube", "x", "instagram"]
FootageStatus = Literal["ok", "none", "disabled", "unavailable"]
RejectReason = Literal[
    "main",
    "aggregator",
    "spam",
    "reaction_text",
    "duration",
    "story",
    "subtitle",
    "commentary",
    "object_absent",
    "duplicate",
    "media_failed",
    "vision_unavailable",
]
REJECT_REASONS: frozenset[str] = frozenset(get_args(RejectReason))


class FootageObject(StrictModel):
    """One search: the Indonesian query and the English look vision checks against."""

    query: Annotated[str, Field(min_length=1, max_length=100)]
    visual: Annotated[str, Field(min_length=1, max_length=300)]


@dataclass(frozen=True)
class NewCandidate:
    url: str
    platform: str
    source: str
    query: str
    visual: str
    owner_handle: str
    caption: str = ""
    published_at: str | None = None
    engagement: dict[str, int] = field(default_factory=dict)
    source_duration: float | None = None
    status: str = "pending"
    reason: str | None = None


@dataclass(frozen=True)
class CandidateView:
    url: str
    platform: str
    source: str
    query: str
    visual: str
    owner_handle: str
    caption: str
    published_at: str | None
    engagement: dict[str, int]
    source_duration: float | None
    status: str
    reason: str | None
    story_score: float | None
    kind: str | None
    shows_object: str | None
    description: str | None
    media_location: str | None
    media_checksum: str | None
    media_bytes: int | None
    clip_duration: float | None
    clip_start: float | None
    ocr: dict[str, Any] | None
    position: int | None


@dataclass(frozen=True)
class RunView:
    workflow_id: str
    status: str
    footage_status: str | None
    objects: list[FootageObject]


@dataclass(frozen=True)
class AdmittedClip:
    kind: str
    shows_object: str
    description: str
    media_location: str
    media_checksum: str
    media_bytes: int
    clip_duration: float
    clip_start: float
    ocr: dict[str, Any]
    position: int


@dataclass(frozen=True)
class FootageResult:
    status: FootageStatus
    admitted: int = 0
    rejected: dict[str, int] = field(default_factory=dict)
```

`footage/__init__.py`: `"""Stage 5b footage: b-roll search, gates, and clip checks."""`

- [ ] **Step 3: Write the failing store test** `tests/footage/test_store.py`
  (`tests/footage/__init__.py` is empty)

```python
"""The footage store on in-memory SQLite (the source-account store's test pattern)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.footage.models import AdmittedClip, FootageObject, NewCandidate
from thoth_control_plane.infrastructure.footage_store import FootageStore
from thoth_control_plane.infrastructure.source_account_models import Base

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
OBJECTS = [FootageObject(query="banjir jakarta", visual="a flooded street")]


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(clock: Clock) -> FootageStore:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return FootageStore(engine, clock=clock)


def _video(n: int = 1) -> DiscoveredVideo:
    return DiscoveredVideo(
        post_id=f"740000000000000000{n}",
        owner_handle="kreator",
        canonical_url=f"https://www.tiktok.com/@kreator/video/740000000000000000{n}",
        caption="banjir lagi di jakarta",
        duration_seconds=42.0,
        engagement={"like": 10},
    )


def _candidate(url: str = "https://x.com/a/status/1", **changes: object) -> NewCandidate:
    values: dict[str, object] = {
        "url": url,
        "platform": "x",
        "source": "search",
        "query": "banjir jakarta",
        "visual": "a flooded street",
        "owner_handle": "a",
        "caption": "banjir",
    }
    values.update(changes)
    return NewCandidate(**values)  # type: ignore[arg-type]


def _clip(position: int) -> AdmittedClip:
    return AdmittedClip(
        kind="footage",
        shows_object="yes",
        description="A flooded street.",
        media_location="reports/wf_a/footage/abc.mp4",
        media_checksum="sha256:" + "a" * 64,
        media_bytes=2048,
        clip_duration=20.0,
        clip_start=4.2,
        ocr={"outcome": "clean"},
        position=position,
    )


def test_a_search_is_cached_for_a_day_and_pruned_after(store: FootageStore, clock: Clock) -> None:
    store.save_search("tiktok", "  Banjir   Jakarta ", [_video()])
    cached = store.cached_search("tiktok", "banjir jakarta")
    assert cached is not None and cached[0].post_id == "7400000000000000001"
    assert store.cached_search("youtube", "banjir jakarta") is None

    clock.now = NOW + timedelta(hours=25)
    assert store.cached_search("tiktok", "banjir jakarta") is None
    store.save_search("tiktok", "other", [])  # a write prunes expired rows
    clock.now = NOW
    assert store.cached_search("tiktok", "banjir jakarta") is None


def test_saving_a_search_again_replaces_it(store: FootageStore) -> None:
    store.save_search("tiktok", "banjir jakarta", [_video(1)])
    store.save_search("tiktok", "banjir jakarta", [_video(2)])
    cached = store.cached_search("tiktok", "banjir jakarta")
    assert [video.post_id for video in cached or []] == ["7400000000000000002"]


def test_a_run_starts_once_and_keeps_its_objects(store: FootageStore) -> None:
    first = store.start_run("wf_a", OBJECTS)
    again = store.start_run("wf_a", [])
    assert first.objects == OBJECTS and again.objects == OBJECTS
    store.finish_run("wf_a", "ok")
    run = store.run("wf_a")
    assert run is not None and run.status == "done" and run.footage_status == "ok"
    assert store.run("wf_b") is None


def test_candidates_are_unique_per_workflow_and_url(store: FootageStore) -> None:
    store.start_run("wf_a", OBJECTS)
    store.add_candidates("wf_a", [_candidate(), _candidate()])
    store.add_candidates("wf_a", [_candidate()])
    assert len(store.candidates("wf_a")) == 1


def test_decisions_and_admission_order(store: FootageStore) -> None:
    store.start_run("wf_a", OBJECTS)
    store.add_candidates(
        "wf_a",
        [
            _candidate("https://x.com/a/status/1"),
            _candidate("https://x.com/a/status/2"),
            _candidate("https://x.com/a/status/3", status="rejected", reason="spam"),
        ],
    )
    store.score("wf_a", "https://x.com/a/status/1", 0.7)
    store.reject("wf_a", "https://x.com/a/status/2", "commentary", kind="commentary")
    store.admit("wf_a", "https://x.com/a/status/1", _clip(0))

    by_url = {c.url: c for c in store.candidates("wf_a")}
    assert by_url["https://x.com/a/status/2"].reason == "commentary"
    assert by_url["https://x.com/a/status/3"].reason == "spam"
    admitted = store.admitted("wf_a")
    assert [c.url for c in admitted] == ["https://x.com/a/status/1"]
    assert admitted[0].story_score == 0.7 and admitted[0].clip_start == 4.2


def test_reopen_returns_an_admitted_candidate_to_pending(store: FootageStore) -> None:
    store.start_run("wf_a", OBJECTS)
    store.add_candidates("wf_a", [_candidate()])
    store.admit("wf_a", "https://x.com/a/status/1", _clip(0))
    store.reopen("wf_a", "https://x.com/a/status/1")
    (candidate,) = store.candidates("wf_a")
    assert candidate.status == "pending" and candidate.media_location is None
    assert store.admitted("wf_a") == []


def test_an_unknown_reason_is_refused(store: FootageStore) -> None:
    store.start_run("wf_a", OBJECTS)
    store.add_candidates("wf_a", [_candidate()])
    with pytest.raises(ValueError):
        store.reject("wf_a", "https://x.com/a/status/1", "seen")


def test_a_candidate_needs_its_run(store: FootageStore) -> None:
    with pytest.raises((IntegrityError, ValueError)):
        store.add_candidates("wf_missing", [_candidate()])
```

- [ ] **Step 4: Run it to see it fail**

Run: `cd python && uv run pytest tests/footage/test_store.py -q`
Expected: FAIL — `ModuleNotFoundError: thoth_control_plane.infrastructure.footage_store`.

- [ ] **Step 5: Write `infrastructure/footage_models.py`**

```python
"""SQLAlchemy ORM mapping of the footage tables (editor migration 0010)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from thoth_control_plane.infrastructure.source_account_models import Base, UtcDateTime


class FootageSearchRow(Base):
    __tablename__ = "footage_searches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    platform: Mapped[str] = mapped_column(String)
    query: Mapped[str] = mapped_column(String)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(UtcDateTime)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)


class FootageRunRow(Base):
    __tablename__ = "footage_runs"

    workflow_id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String)
    footage_status: Mapped[str | None] = mapped_column(String, nullable=True)
    objects: Mapped[list[dict[str, str]]] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class FootageCandidateRow(Base):
    __tablename__ = "footage_candidates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[str] = mapped_column(
        String, ForeignKey("footage_runs.workflow_id", ondelete="CASCADE")
    )
    url: Mapped[str] = mapped_column(String)
    platform: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    query: Mapped[str] = mapped_column(String)
    visual: Mapped[str] = mapped_column(String)
    owner_handle: Mapped[str] = mapped_column(String)
    caption: Mapped[str] = mapped_column(String, default="")
    published_at: Mapped[str | None] = mapped_column(String, nullable=True)
    engagement: Mapped[dict[str, int]] = mapped_column(JSON)
    source_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    story_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    kind: Mapped[str | None] = mapped_column(String, nullable=True)
    shows_object: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    media_location: Mapped[str | None] = mapped_column(String, nullable=True)
    media_checksum: Mapped[str | None] = mapped_column(String, nullable=True)
    media_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    clip_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    clip_start: Mapped[float | None] = mapped_column(Float, nullable=True)
    ocr: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)
```

The unique constraints live in the migration; the store never relies on the database to dedupe
(it checks first), so SQLite tests need no constraint declarations.

- [ ] **Step 6: Write `infrastructure/footage_store.py`**

```python
"""Footage state per workflow and a 24-hour search cache (editor migration 0010).

Synchronous like the source-account store; callers wrap calls in `asyncio.to_thread`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.footage.models import (
    REJECT_REASONS,
    AdmittedClip,
    CandidateView,
    FootageObject,
    NewCandidate,
    RunView,
)
from thoth_control_plane.infrastructure.footage_models import (
    FootageCandidateRow,
    FootageRunRow,
    FootageSearchRow,
)

SEARCH_KEPT = timedelta(hours=24)


def normalize_query(query: str) -> str:
    return " ".join(query.lower().split())


def _view(row: FootageCandidateRow) -> CandidateView:
    return CandidateView(
        url=row.url,
        platform=row.platform,
        source=row.source,
        query=row.query,
        visual=row.visual,
        owner_handle=row.owner_handle,
        caption=row.caption,
        published_at=row.published_at,
        engagement=dict(row.engagement or {}),
        source_duration=row.source_duration,
        status=row.status,
        reason=row.reason,
        story_score=row.story_score,
        kind=row.kind,
        shows_object=row.shows_object,
        description=row.description,
        media_location=row.media_location,
        media_checksum=row.media_checksum,
        media_bytes=row.media_bytes,
        clip_duration=row.clip_duration,
        clip_start=row.clip_start,
        ocr=row.ocr,
        position=row.position,
    )


def _run_view(row: FootageRunRow) -> RunView:
    return RunView(
        workflow_id=row.workflow_id,
        status=row.status,
        footage_status=row.footage_status,
        objects=[FootageObject.model_validate(item) for item in row.objects],
    )


class FootageStore:
    def __init__(
        self, engine: Engine, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        self._clock = clock

    @classmethod
    def connect(cls, database_url: str) -> FootageStore:
        url = make_url(database_url).set(drivername="postgresql+psycopg")
        return cls(create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2))

    # Search cache

    def cached_search(self, platform: str, query: str) -> list[DiscoveredVideo] | None:
        with self._sessions() as session:
            row = session.scalar(
                select(FootageSearchRow).where(
                    FootageSearchRow.platform == platform,
                    FootageSearchRow.query == normalize_query(query),
                    FootageSearchRow.expires_at > self._clock(),
                )
            )
            if row is None:
                return None
            return [DiscoveredVideo.model_validate(item) for item in row.results]

    def save_search(self, platform: str, query: str, videos: Sequence[DiscoveredVideo]) -> None:
        now = self._clock()
        key = normalize_query(query)
        with self._sessions.begin() as session:
            session.execute(delete(FootageSearchRow).where(FootageSearchRow.expires_at <= now))
            session.execute(
                delete(FootageSearchRow).where(
                    FootageSearchRow.platform == platform, FootageSearchRow.query == key
                )
            )
            session.add(
                FootageSearchRow(
                    platform=platform,
                    query=key,
                    results=[video.model_dump(mode="json") for video in videos],
                    fetched_at=now,
                    expires_at=now + SEARCH_KEPT,
                )
            )

    # Runs

    def run(self, workflow_id: str) -> RunView | None:
        with self._sessions() as session:
            row = session.get(FootageRunRow, workflow_id)
            return None if row is None else _run_view(row)

    def start_run(self, workflow_id: str, objects: Sequence[FootageObject]) -> RunView:
        with self._sessions.begin() as session:
            row = session.get(FootageRunRow, workflow_id)
            if row is None:
                row = FootageRunRow(
                    workflow_id=workflow_id,
                    status="running",
                    objects=[item.model_dump() for item in objects],
                    started_at=self._clock(),
                )
                session.add(row)
            return _run_view(row)

    def finish_run(self, workflow_id: str, footage_status: str) -> None:
        with self._sessions.begin() as session:
            row = session.get(FootageRunRow, workflow_id)
            if row is None:
                raise ValueError("no footage run for this workflow")
            row.status = "done"
            row.footage_status = footage_status
            row.finished_at = self._clock()

    # Candidates

    def candidates(self, workflow_id: str) -> list[CandidateView]:
        with self._sessions() as session:
            rows = session.scalars(
                select(FootageCandidateRow)
                .where(FootageCandidateRow.workflow_id == workflow_id)
                .order_by(FootageCandidateRow.created_at, FootageCandidateRow.url)
            )
            return [_view(row) for row in rows]

    def add_candidates(self, workflow_id: str, items: Sequence[NewCandidate]) -> None:
        now = self._clock()
        with self._sessions.begin() as session:
            if session.get(FootageRunRow, workflow_id) is None:
                raise ValueError("no footage run for this workflow")
            known = set(
                session.scalars(
                    select(FootageCandidateRow.url).where(
                        FootageCandidateRow.workflow_id == workflow_id
                    )
                )
            )
            for item in items:
                if item.url in known:
                    continue
                if item.reason is not None and item.reason not in REJECT_REASONS:
                    raise ValueError(f"unknown footage reason {item.reason}")
                known.add(item.url)
                session.add(
                    FootageCandidateRow(
                        workflow_id=workflow_id,
                        url=item.url,
                        platform=item.platform,
                        source=item.source,
                        query=item.query,
                        visual=item.visual,
                        owner_handle=item.owner_handle,
                        caption=item.caption,
                        published_at=item.published_at,
                        engagement=dict(item.engagement),
                        source_duration=item.source_duration,
                        status=item.status,
                        reason=item.reason,
                        created_at=now,
                        updated_at=now,
                    )
                )

    def score(self, workflow_id: str, url: str, story_score: float) -> None:
        with self._sessions.begin() as session:
            row = self._row(session, workflow_id, url)
            row.story_score = story_score
            row.updated_at = self._clock()

    def reject(
        self,
        workflow_id: str,
        url: str,
        reason: str,
        *,
        story_score: float | None = None,
        kind: str | None = None,
        shows_object: str | None = None,
        description: str | None = None,
    ) -> None:
        if reason not in REJECT_REASONS:
            raise ValueError(f"unknown footage reason {reason}")
        with self._sessions.begin() as session:
            row = self._row(session, workflow_id, url)
            row.status = "rejected"
            row.reason = reason
            if story_score is not None:
                row.story_score = story_score
            row.kind = kind
            row.shows_object = shows_object
            row.description = description
            row.updated_at = self._clock()

    def admit(self, workflow_id: str, url: str, clip: AdmittedClip) -> None:
        with self._sessions.begin() as session:
            row = self._row(session, workflow_id, url)
            row.status = "admitted"
            row.reason = None
            row.kind = clip.kind
            row.shows_object = clip.shows_object
            row.description = clip.description
            row.media_location = clip.media_location
            row.media_checksum = clip.media_checksum
            row.media_bytes = clip.media_bytes
            row.clip_duration = clip.clip_duration
            row.clip_start = clip.clip_start
            row.ocr = clip.ocr
            row.position = clip.position
            row.updated_at = self._clock()

    def reopen(self, workflow_id: str, url: str) -> None:
        with self._sessions.begin() as session:
            row = self._row(session, workflow_id, url)
            row.status = "pending"
            row.reason = None
            row.media_location = row.media_checksum = None
            row.media_bytes = None
            row.clip_duration = row.clip_start = None
            row.ocr = None
            row.position = None
            row.updated_at = self._clock()

    def admitted(self, workflow_id: str) -> list[CandidateView]:
        with self._sessions() as session:
            rows = session.scalars(
                select(FootageCandidateRow)
                .where(
                    FootageCandidateRow.workflow_id == workflow_id,
                    FootageCandidateRow.status == "admitted",
                )
                .order_by(FootageCandidateRow.position)
            )
            return [_view(row) for row in rows]

    @staticmethod
    def _row(session: Session, workflow_id: str, url: str) -> FootageCandidateRow:
        row = session.scalar(
            select(FootageCandidateRow).where(
                FootageCandidateRow.workflow_id == workflow_id, FootageCandidateRow.url == url
            )
        )
        if row is None:
            raise ValueError("no such footage candidate")
        return row
```

- [ ] **Step 7: Run the tests**

Run: `cd python && uv run pytest tests/footage/test_store.py tests/operations/test_editor_migrations.py -q`
Expected: PASS. (`test_a_candidate_needs_its_run` passes through the store's own `ValueError`.)

- [ ] **Step 8: Prove the migration on a disposable Postgres**

The 2026-10-14 CI failure came from the migration chain on a fresh database, so run the real
chain once:

```bash
wsl -e bash -lc 'docker run -d --rm --name thoth-pg-0010 -e POSTGRES_PASSWORD=t -p 55432:5432 postgres:16.4-bookworm && sleep 6'
cd python && THOTH_EDITOR_DATABASE_URL=postgresql://postgres:t@127.0.0.1:55432/postgres uv run thoth-control editor migrate
cd python && THOTH_EDITOR_DATABASE_URL=postgresql://postgres:t@127.0.0.1:55432/postgres uv run thoth-control editor migrate
wsl -e docker stop thoth-pg-0010
```

Expected: the first `migrate` prints `10`, the second prints `0`. (If the API key setting is
required by `Settings`, prefix `THOTH_CONTROL_PLANE_API_KEY=local`.)

- [ ] **Step 9: Commit**

```bash
git add python/migrations/editor/0010_footage.sql python/migrations/editor/alembic/versions/0010_footage.py python/src/thoth_control_plane/footage python/src/thoth_control_plane/infrastructure/footage_models.py python/src/thoth_control_plane/infrastructure/footage_store.py python/tests/footage python/tests/operations/test_editor_migrations.py
git commit -m "feat(footage): footage tables and store"
```

---

### Task 3: Text gates ported from Scout

**Files:**
- Create: `python/src/thoth_control_plane/footage/gates.py`
- Test: `python/tests/footage/test_gates.py`

**Interfaces:**
- Consumes: `DiscoveredVideo` (acquisition), `RejectReason` (Task 2).
- Produces: `norm(text) -> str`, `video_id(url) -> str`, `compose_query(obj, subject) -> str`,
  `looks_spam(text) -> bool`, `looks_reaction(text) -> bool`, `MainIdentity` (frozen dataclass:
  `urls: frozenset[str]`, `video_id: str`, `caption: str`) with
  `MainIdentity.of(url, other_urls, text) -> MainIdentity`, `same_as_main(main, url, caption) -> bool`,
  `text_gate(url, video, main, aggregators) -> RejectReason | None`, `MIN_SECONDS = 3.0`,
  `MAX_SECONDS = 900.0`.

- [ ] **Step 1: Write the failing tests**

```python
"""Scout's footage text gates (scout/pipeline/build_footage.ts, footage_queries.ts), ported."""

from __future__ import annotations

import re
from pathlib import Path

from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.footage.gates import (
    REACTION_RE,
    SPAM_DOMAINS,
    MainIdentity,
    compose_query,
    looks_reaction,
    looks_spam,
    norm,
    same_as_main,
    text_gate,
    video_id,
)

REPO = Path(__file__).resolve().parents[3]
SCOUT = (REPO / "scout" / "pipeline" / "build_footage.ts").read_text(encoding="utf-8")


def _scout_regex(name: str) -> str:
    match = re.search(rf"const {name} =\s*/(.+?)/i;", SCOUT, re.S)
    assert match, f"{name} not found in build_footage.ts"
    return match.group(1)


def test_the_reaction_regex_is_scouts_verbatim() -> None:
    assert REACTION_RE.pattern == _scout_regex("REACTION_RE")


def test_the_spam_domains_are_scouts_verbatim() -> None:
    match = re.search(r"\|\| /(vidku.+?)/i\.test\(t\)", SCOUT)
    assert match and SPAM_DOMAINS.pattern == match.group(1)


def test_reaction_and_spam() -> None:
    assert looks_reaction("REACTION video banjir")
    assert looks_reaction("nonton bareng final")
    assert not looks_reaction("nonton banjir")  # bare "nonton" over-filters (Scout)
    assert looks_spam("https://vidku.fun/x lagi viral")
    assert looks_spam("Yang lagi viral di mobil vidku.fun #Gempa")
    assert not looks_spam("banjir di kemang pagi ini")


def test_video_ids_like_scout() -> None:
    assert video_id("https://www.tiktok.com/@a/video/7400000000000000001") == "7400000000000000001"
    assert video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert video_id("https://www.instagram.com/reel/ABC123/") == "ABC123"
    assert video_id("https://x.com/a/status/1") == ""


def test_norm_and_compose_query() -> None:
    assert norm("  Banjir!! di  JAKARTA… ") == "banjir di jakarta"
    assert compose_query("chip ai", "nvidia") == "chip ai nvidia"
    assert compose_query("data center nvidia", "nvidia") == "data center nvidia"
    assert compose_query("longsor", "") == "longsor"


def test_same_as_main_by_id_or_caption() -> None:
    main = MainIdentity.of(
        "https://www.tiktok.com/@a/video/7400000000000000001",
        [],
        "Banjir besar melanda Kemang pagi ini, warga mengungsi ke masjid terdekat",
    )
    assert same_as_main(main, "https://www.tiktok.com/@b/video/7400000000000000001", "")
    assert same_as_main(main, "https://x.com/b/status/9", "banjir besar melanda kemang pagi ini")
    assert not same_as_main(main, "https://x.com/b/status/9", "banjir")  # 20 chars or fewer
    assert not same_as_main(main, "https://x.com/b/status/9", "kebakaran pasar senen tadi malam")


def _video(caption: str, duration: float | None = 40.0, owner: str = "kreator") -> DiscoveredVideo:
    return DiscoveredVideo(
        post_id="7400000000000000009",
        owner_handle=owner,
        canonical_url=f"https://www.tiktok.com/@{owner}/video/7400000000000000009",
        caption=caption,
        duration_seconds=duration,
    )


def test_text_gate_order() -> None:
    main = MainIdentity.of("https://www.instagram.com/p/MAIN1/", [], "banjir kemang")
    url = "https://www.tiktok.com/@kreator/video/7400000000000000009"
    gate = lambda video: text_gate(url, video, main, frozenset({"kurator"}))  # noqa: E731
    assert gate(_video("banjir kemang hari ini", owner="Kurator")) == "aggregator"
    assert gate(_video("https://bit.ly/x banjir")) == "spam"
    assert gate(_video("reaction banjir kemang")) == "reaction_text"
    assert gate(_video("banjir kemang", duration=2.0)) == "duration"
    assert gate(_video("banjir kemang", duration=901.0)) == "duration"
    assert gate(_video("banjir kemang", duration=None)) is None
    assert gate(_video("air naik di jalan")) is None
    assert text_gate("https://www.instagram.com/p/MAIN1/", _video("x"), main, frozenset()) == "main"
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd python && uv run pytest tests/footage/test_gates.py -q`
Expected: FAIL — `ModuleNotFoundError: thoth_control_plane.footage.gates`.

- [ ] **Step 3: Implement `footage/gates.py`**

```python
"""Footage text gates, ported from Scout's build_footage.ts and footage_queries.ts.

None of them touches media. The regexes are Scout's verbatim (tests read Scout's source).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.footage.models import RejectReason

# Reaction/repost content = someone reacting to other footage, not b-roll (Scout).
REACTION_RE = re.compile(
    r"\b(reaction|reaksi|bereaksi|ngereact|nge-?react|react(?:ing|s|ed)?|reupload|nonton bareng)\b",
    re.IGNORECASE,
)
SPAM_LEAD = re.compile(r"^https?:\/\/")
SPAM_DOMAINS = re.compile(r"vidku\.|t\.me\/|bit\.ly|tinyurl|cutt\.ly|\.fun\b|\.xyz\b", re.IGNORECASE)
VIDEO_IDS = (
    re.compile(r"/video/(\d{6,})"),
    re.compile(r"[?&]v=([\w-]{6,})"),
    re.compile(r"youtu\.be/([\w-]+)"),
    re.compile(r"/(?:reel|reels|p|tv)/([\w-]+)"),
)
NON_WORD = re.compile(r"[^a-z0-9 ]+")
MIN_SECONDS = 3.0
MAX_SECONDS = 900.0


def norm(text: str) -> str:
    return " ".join(NON_WORD.sub(" ", (text or "").lower()).split())


def video_id(url: str) -> str:
    for pattern in VIDEO_IDS:
        match = pattern.search(url or "")
        if match:
            return match.group(1)
    return ""


def compose_query(obj: str, subject: str) -> str:
    """Scout's composeQuery: append the subject unless the object already names it."""
    if not subject:
        return obj
    lowered = (obj or "").lower()
    if any(len(token) >= 3 and token in lowered for token in subject.lower().split()):
        return obj
    return f"{obj} {subject}"


def looks_spam(text: str) -> bool:
    lowered = (text or "").lower().strip()
    return bool(SPAM_LEAD.search(lowered) or SPAM_DOMAINS.search(lowered))


def looks_reaction(text: str) -> bool:
    return bool(REACTION_RE.search(text or ""))


@dataclass(frozen=True)
class MainIdentity:
    urls: frozenset[str]
    video_id: str
    caption: str

    @classmethod
    def of(cls, url: str, other_urls: Iterable[str], text: str) -> MainIdentity:
        # Scout: mainCap = norm(`${title} ${description}`), title being the first 120 characters.
        return cls(
            urls=frozenset([url, *other_urls]),
            video_id=video_id(url),
            caption=norm(f"{text[:120]} {text}"),
        )


def same_as_main(main: MainIdentity, url: str, caption: str) -> bool:
    if url in main.urls:
        return True
    candidate = video_id(url)
    if candidate and main.video_id and candidate == main.video_id:
        return True
    text = norm(caption)
    return bool(
        text
        and len(text) > 20
        and main.caption
        and (text in main.caption or main.caption[:80] in text)
    )


def text_gate(
    url: str, video: DiscoveredVideo, main: MainIdentity, aggregators: frozenset[str]
) -> RejectReason | None:
    """Spec F5 steps 1 and 3-6 in order; the story gate runs apart (it needs embeddings)."""
    if same_as_main(main, url, video.caption):
        return "main"
    if video.owner_handle.lower() in aggregators:
        return "aggregator"
    if looks_spam(video.caption):
        return "spam"
    if looks_reaction(video.caption):
        return "reaction_text"
    duration = video.duration_seconds
    if duration is not None and not MIN_SECONDS <= duration <= MAX_SECONDS:
        return "duration"
    return None
```

Note `load_curated` (attribution) returns normalized lowercase handles; `text_gate` lowercases the
owner to match.

- [ ] **Step 4: Run the tests**

Run: `cd python && uv run pytest tests/footage/test_gates.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/footage/gates.py python/tests/footage/test_gates.py
git commit -m "feat(footage): text gates ported from Scout"
```

---

### Task 4: Local embedding model and embedder

**Files:**
- Modify: `docker/fetch_speech_models.py` (CRLF? check with `file`; keep its line endings)
- Modify: `.github/workflows/container-image.yml` (CRLF)
- Modify: `python/tests/deployment/test_container_contract.py`
- Modify: `python/src/thoth_control_plane/config.py`
- Create: `python/src/thoth_control_plane/footage/adapters/__init__.py`
- Create: `python/src/thoth_control_plane/footage/adapters/embedder.py`
- Test: `python/tests/footage/test_embedder.py`

**Interfaces:**
- Produces: `footage.adapters.embedder.EMBEDDING_FILES = ("model.onnx", "tokenizer.json")`,
  `OnnxEmbedder(directory: Path)` with `async embed(texts: Sequence[str]) -> list[list[float]]`
  (unit-length vectors), `cosine(a, b) -> float`.
- Produces: settings `THOTH_EMBEDDING_MODEL_DIR: Path = Path("/opt/thoth/models/embedding")`.
- Test env: `THOTH_TEST_EMBEDDING_MODEL_DIR` (CI: `${{ runner.temp }}/models/embedding`).

- [ ] **Step 1: Write the failing tests** `tests/footage/test_embedder.py`

```python
"""The local multilingual embedder on the real model; a missing model fails the test."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from thoth_control_plane.attribution.adapters.frames import ToolMissing
from thoth_control_plane.footage.adapters.embedder import OnnxEmbedder, cosine


def _required(variable: str) -> Path:
    # Operator, 2026-10-11/13: a missing tool or model fails the test, never a skip.
    value = os.environ.get(variable)
    if not value or not Path(value).is_dir():
        pytest.fail(f"{variable} must point to the fetched embedding model (plan Task 4)")
    return Path(value)


async def test_a_paraphrase_scores_above_an_unrelated_text() -> None:
    embedder = OnnxEmbedder(_required("THOTH_TEST_EMBEDDING_MODEL_DIR"))
    story, paraphrase, unrelated = await embedder.embed(
        [
            "banjir besar melanda jakarta, mobil terendam di jalan",
            "jalanan jakarta tergenang air setelah hujan deras",
            "resep nasi goreng kampung yang enak dan murah",
        ]
    )
    assert abs(cosine(story, story) - 1.0) < 1e-4
    assert cosine(story, paraphrase) > cosine(story, unrelated) + 0.1


async def test_a_missing_model_is_an_explicit_error(tmp_path: Path) -> None:
    with pytest.raises(ToolMissing, match="embedding_model_missing"):
        await OnnxEmbedder(tmp_path).embed(["x"])
```

- [ ] **Step 2: Extend the model fetch script** — add to `docker/fetch_speech_models.py`, after
  `DIARIZATION`:

```python
# Stage 5b story gate (spec 2026-10-14, amendment 2): the official ONNX export, quantized.
EMBEDDING = {
    "repo": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "revision": "e8f8c211226b894fcb81acc59f3b34ba3efd5f42",
    "files": {
        "model.onnx": (
            "onnx/model_quint8_avx2.onnx",
            "98a01d88b7de996cdea58c32ca71208c09968d143798814b2ea09d3439dc334f",
        ),
        "tokenizer.json": (
            "tokenizer.json",
            "2c3387be76557bd40970cec13153b3bbf80407865484b209e655e5e4729076b8",
        ),
    },
}
```

and after `fetch_diarization`:

```python
def fetch_embedding(out: Path) -> None:
    from huggingface_hub import hf_hub_download

    target = out / "embedding"
    target.mkdir(parents=True, exist_ok=True)
    for name, (remote, digest) in EMBEDDING["files"].items():
        with tempfile.TemporaryDirectory() as scratch:
            path = hf_hub_download(
                EMBEDDING["repo"], remote, revision=EMBEDDING["revision"], local_dir=scratch
            )
            shutil.copyfile(path, target / name)
        verify(target / name, digest)
```

and call it last in `__main__`: `fetch_embedding(arguments.out)`. Update the module docstring's
first line to "Fetch the pinned models: whisper, the two diarization ONNX files, and the footage
embedding model." (Keep the file name; the Dockerfile and CI already call it in the heavy layer.)

- [ ] **Step 3: Fetch the model locally and run the test to see it fail on the import**

```bash
cd python && uv run python ../docker/fetch_speech_models.py --whisper tiny --out /mnt/d/thoth-tmp/models
cd python && THOTH_TEST_EMBEDDING_MODEL_DIR=/mnt/d/thoth-tmp/models/embedding uv run pytest tests/footage/test_embedder.py -q
```

Expected: the fetch ends without "checksum mismatch"; the test FAILS with
`ModuleNotFoundError: thoth_control_plane.footage.adapters`.

- [ ] **Step 4: Implement `footage/adapters/embedder.py`** (`footage/adapters/__init__.py` is a
  one-line docstring)

```python
"""Sentence embeddings on the local ONNX model: mean pooling over the attention mask, as the
model's `1_Pooling/config.json` says, then unit length. No network at run time."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from thoth_control_plane.attribution.adapters.frames import ToolMissing
from thoth_control_plane.attribution.adapters.speech import missing

EMBEDDING_FILES = ("model.onnx", "tokenizer.json")
MAX_TOKENS = 128


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Vectors from `OnnxEmbedder` are unit length, so the dot product is the cosine."""
    return float(sum(x * y for x, y in zip(a, b, strict=True)))


class OnnxEmbedder:
    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._session: Any = None
        self._tokenizer: Any = None

    def _load(self) -> None:
        if missing(self._dir, EMBEDDING_FILES):
            raise ToolMissing("embedding_model_missing")
        if self._session is None:
            import onnxruntime
            from tokenizers import Tokenizer

            tokenizer = Tokenizer.from_file(str(self._dir / "tokenizer.json"))
            tokenizer.enable_truncation(MAX_TOKENS)
            tokenizer.enable_padding()
            self._tokenizer = tokenizer
            self._session = onnxruntime.InferenceSession(
                str(self._dir / "model.onnx"), providers=["CPUExecutionProvider"]
            )

    def embed_sync(self, texts: Sequence[str]) -> list[list[float]]:
        import numpy as np

        self._load()
        encodings = self._tokenizer.encode_batch([text or " " for text in texts])
        ids = np.array([e.ids for e in encodings], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": mask}
        names = {item.name for item in self._session.get_inputs()}
        if "token_type_ids" in names:
            feeds["token_type_ids"] = np.zeros_like(ids)
        hidden = self._session.run(None, feeds)[0]
        weights = mask[..., None].astype(hidden.dtype)
        pooled = (hidden * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        vectors = pooled / np.clip(norms, 1e-12, None)
        return [[float(x) for x in row] for row in vectors]

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self.embed_sync, texts)
```

- [ ] **Step 5: Add the setting** in `config.py`, next to `THOTH_DIARIZATION_MODEL_DIR`:

```python
    THOTH_EMBEDDING_MODEL_DIR: Path = Path("/opt/thoth/models/embedding")
```

- [ ] **Step 6: CI env and its contract test**

In `.github/workflows/container-image.yml` (byte-level, CRLF), in the "Run Python non-live
tests" step's `env:`, add after the diarization line:

```yaml
          THOTH_TEST_EMBEDDING_MODEL_DIR: ${{ runner.temp }}/models/embedding
```

In `tests/deployment/test_container_contract.py`,
`test_container_workflow_pins_gates_tags_platform_and_digest_summary`, insert the same line into
the asserted block after the diarization line:

```python
        "          THOTH_TEST_DIARIZATION_MODEL_DIR: ${{ runner.temp }}/models/diarization\n"
        "          THOTH_TEST_EMBEDDING_MODEL_DIR: ${{ runner.temp }}/models/embedding\n"
```

Check `.github/workflows/yt-dlp-update.yml` for the same "Run Python non-live tests" env block
(it fetches the models too, line 93); add the same env line there if it runs the suite.

Append to the contract tests:

```python
def test_the_embedding_model_is_pinned_and_fetched_with_the_speech_models() -> None:
    script = _repo_text("docker/fetch_speech_models.py")
    assert "paraphrase-multilingual-MiniLM-L12-v2" in script
    assert "e8f8c211226b894fcb81acc59f3b34ba3efd5f42" in script
    assert "fetch_embedding(arguments.out)" in script
    dockerfile = _repo_text("Dockerfile")
    assert dockerfile.index("fetch_speech_models.py \\") < dockerfile.index(
        "COPY --chown=thoth:thoth python/src/"
    )
```

- [ ] **Step 7: Run the tests**

Run: `cd python && THOTH_TEST_EMBEDDING_MODEL_DIR=/mnt/d/thoth-tmp/models/embedding uv run pytest tests/footage/test_embedder.py tests/deployment/test_container_contract.py -q`
Expected: PASS. If `cosine(story, paraphrase) > cosine(story, unrelated) + 0.1` fails, print the
three scores and record them in the ledger before changing the margin.

- [ ] **Step 8: Commit**

```bash
git add docker/fetch_speech_models.py .github/workflows/container-image.yml python/tests/deployment/test_container_contract.py python/src/thoth_control_plane/config.py python/src/thoth_control_plane/footage/adapters python/tests/footage/test_embedder.py
git commit -m "feat(footage): local multilingual embedder, pinned model"
```

(If `yt-dlp-update.yml` changed, add it too.)

---

### Task 5: Query extraction

**Files:**
- Create: `python/src/thoth_control_plane/footage/queries.py`
- Create: `python/src/thoth_control_plane/footage/adapters/queries.py`
- Modify: `python/src/thoth_control_plane/config.py`
- Test: `python/tests/footage/test_queries.py`

**Interfaces:**
- Consumes: `compose_query` (Task 3), `FootageObject` (Task 2).
- Produces: `MAX_OBJECTS = 4`, `ObjectItem`, `FootageQueryAnswer` (pydantic), `query_prompt(description, headline, comments) -> str | None`,
  `footage_objects(answer) -> list[FootageObject]`, `top_comments(texts_with_likes) -> str`,
  `AgnoQueryModel(api_key, model)` with `async read(prompt) -> FootageQueryAnswer | None`.
- Produces: setting `THOTH_FOOTAGE_QUERY_MODEL: str = "deepseek/deepseek-v4-flash-0731"`.

- [ ] **Step 1: Write the failing tests**

```python
"""Footage queries: Scout's footage_objects prompt plus an English visual per object."""

from __future__ import annotations

from thoth_control_plane.footage.queries import (
    FootageQueryAnswer,
    footage_objects,
    query_prompt,
    top_comments,
)


def test_no_text_means_no_prompt() -> None:
    assert query_prompt("", "  ", "") is None


def test_the_prompt_carries_the_texts_bounded() -> None:
    prompt = query_prompt("d" * 900, "HEADLINE", "c" * 900)
    assert prompt is not None
    assert "d" * 700 in prompt and "d" * 701 not in prompt
    assert "HEADLINE" in prompt
    assert "c" * 600 in prompt and "c" * 601 not in prompt
    assert '"visual"' in prompt


def test_objects_are_cleaned_composed_and_capped() -> None:
    answer = FootageQueryAnswer.model_validate(
        {
            "subjects": ["Nvidia", "jensen"],
            "objects": [
                {"name": "Chip AI", "visual": "a close-up of a computer chip"},
                {"name": "chip ai", "visual": "duplicate"},
                {"name": "data center nvidia", "visual": "rows of server racks"},
                {"name": "", "visual": "empty name"},
                {"name": "x" * 41, "visual": "too long"},
                {"name": "kartu grafis", "visual": " "},
                {"name": "gpu", "visual": "a graphics card"},
                {"name": "laptop", "visual": "a gaming laptop"},
                {"name": "pabrik", "visual": "a factory floor"},
            ],
        }
    )
    objects = footage_objects(answer)
    assert [o.query for o in objects] == [
        "chip ai nvidia",
        "data center nvidia",
        "gpu nvidia",
        "laptop nvidia",
    ]
    assert objects[0].visual == "a close-up of a computer chip"


def test_objects_without_a_subject_stay_bare() -> None:
    answer = FootageQueryAnswer.model_validate(
        {"subjects": [], "objects": [{"name": "longsor", "visual": "a landslide"}]}
    )
    assert [o.query for o in footage_objects(answer)] == ["longsor"]


def test_null_fields_do_not_lose_the_answer() -> None:
    answer = FootageQueryAnswer.model_validate(
        {"subjects": None, "objects": [{"name": "banjir", "visual": None}, None]}
    )
    assert footage_objects(answer) == []


def test_top_comments_by_likes() -> None:
    joined = top_comments([("pertama", 1), ("teratas", 50), ("", 99), ("kedua", 10)])
    assert joined == "teratas • kedua • pertama"
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd python && uv run pytest tests/footage/test_queries.py -q`
Expected: FAIL — `ModuleNotFoundError: thoth_control_plane.footage.queries`.

- [ ] **Step 3: Implement `footage/queries.py`**

```python
"""Footage queries: a port of Scout's footage_objects prompt (rules unchanged, in English),
with one change: each object carries an English visual description for the vision check."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, Field, field_validator

from thoth_control_plane.footage.gates import compose_query
from thoth_control_plane.footage.models import FootageObject

MAX_OBJECTS = 4
MAX_NAME = 40
PROMPT = """From the post text below, extract entities for FOOTAGE (b-roll) search queries:
clips that could be SHOWN in a video. Split them into SUBJECTS (anchors) and OBJECTS (concrete
things).

RULES:
1. SUBJECTS = the core anchor entities of the topic: a brand, organization, title, place, or
   event (for example "nvidia", "cerita lila", "gempa filipina", "mindanao"). 1-3 only, the most
   central first.
2. OBJECTS = concrete THINGS, PRODUCTS, PLACES, or ACTIVITIES shown or implied (for example
   "chip ai", "data center", "kartu grafis", "longsor", "bioskop"). Do NOT attach the subject;
   keep them GENERIC, the subject is joined automatically when searching. Distinctive names
   ("mvp pictures", "m block space") may stay as they are. EXPAND generic brands: "ojol" to
   gojek, grab; "e-commerce" to shopee, tokopedia; "mobil sport" to porsche, ferrari. 2-4
   objects, the most visual first, short (1-4 words), lowercase, in the post's language, no
   duplicates.
3. For each object, "visual": one English sentence describing what it looks like on screen
   (for example "a green-jacketed motorbike taxi driver on a city street").
4. AVOID abstract things (payments, prices, policies, numbers) and the uploading or curating
   account.

TEXT:
[DESCRIPTION/CAPTION]: {description}
[HEADLINE/HOOK]: {headline}
[AUDIENCE COMMENTS]: {comments}

Answer in JSON: {{"subjects": [""], "objects": [{{"name": "", "visual": ""}}]}}"""


class ObjectItem(BaseModel):
    name: str = ""
    visual: str = ""

    @field_validator("name", "visual", mode="before")
    @classmethod
    def _null_is_empty(cls, value: object) -> object:
        return "" if value is None else value


class FootageQueryAnswer(BaseModel):
    subjects: list[str] = Field(default_factory=list)
    objects: list[ObjectItem | None] = Field(default_factory=list)

    @field_validator("subjects", "objects", mode="before")
    @classmethod
    def _null_is_empty_list(cls, value: object) -> object:
        return [] if value is None else value

    @field_validator("subjects", mode="before")
    @classmethod
    def _strings(cls, value: object) -> object:
        return [str(item) for item in value if item is not None] if isinstance(value, list) else value


def query_prompt(description: str, headline: str, comments: str) -> str | None:
    description, headline, comments = description.strip(), headline.strip(), comments.strip()
    if not (description or headline or comments):
        return None
    return PROMPT.format(
        description=description[:700] or "(empty)",
        headline=headline[:300] or "(empty)",
        comments=comments[:600] or "(empty)",
    )


def _clean(text: str) -> str:
    return " ".join(text.lower().split())


def footage_objects(answer: FootageQueryAnswer) -> list[FootageObject]:
    """Scout's clean(): lowercase, trim, at most 40 characters, no duplicates; then compose."""
    subjects = [s for s in (_clean(item) for item in answer.subjects) if s and len(s) <= MAX_NAME]
    subject = subjects[0] if subjects else ""
    seen: set[str] = set()
    objects: list[FootageObject] = []
    for item in answer.objects:
        if item is None:
            continue
        name, visual = _clean(item.name), " ".join(item.visual.split())
        if not name or len(name) > MAX_NAME or name in seen or not visual:
            continue
        seen.add(name)
        objects.append(
            FootageObject(query=compose_query(name, subject)[:100], visual=visual[:300])
        )
        if len(objects) == MAX_OBJECTS:
            break
    return objects


def top_comments(comments: Iterable[tuple[str, int]], limit: int = 12) -> str:
    """Scout's topComments: by likes, non-empty, joined with a bullet, at most 600 characters."""
    ranked = sorted(comments, key=lambda item: -item[1])
    texts = [text.strip() for text, _ in ranked if text.strip()][:limit]
    return " • ".join(texts)[:600]
```

- [ ] **Step 4: Implement `footage/adapters/queries.py`** (mirrors `assembly/adapters/figures.py`)

```python
"""Footage queries through Agno over OpenRouter's OpenAI-compatible endpoint."""

from __future__ import annotations

import logging

from thoth_control_plane.footage.queries import FootageQueryAnswer

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
TIMEOUT_SECONDS = 60.0


class AgnoQueryModel:
    def __init__(self, api_key: str, model: str, *, base_url: str = OPENROUTER_BASE_URL) -> None:
        self._key = api_key
        self._model = model
        self._base_url = base_url

    async def read(self, prompt: str) -> FootageQueryAnswer | None:
        from agno.agent import Agent
        from agno.models.openai.like import OpenAILike

        agent = Agent(
            model=OpenAILike(
                id=self._model,
                api_key=self._key,
                base_url=self._base_url,
                timeout=TIMEOUT_SECONDS,
                max_retries=1,
                temperature=0.0,
            ),
            output_schema=FootageQueryAnswer,
            use_json_mode=True,
            telemetry=False,
        )
        try:
            run = await agent.arun(input=prompt)
        except Exception:
            logger.warning("footage queries unavailable")
            return None
        return run.content if isinstance(run.content, FootageQueryAnswer) else None
```

Add to `config.py` next to `THOTH_FIGURES_MODEL`:

```python
    THOTH_FOOTAGE_QUERY_MODEL: str = "deepseek/deepseek-v4-flash-0731"
```

- [ ] **Step 5: Run the tests**

Run: `cd python && uv run pytest tests/footage/test_queries.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add python/src/thoth_control_plane/footage/queries.py python/src/thoth_control_plane/footage/adapters/queries.py python/src/thoth_control_plane/config.py python/tests/footage/test_queries.py
git commit -m "feat(footage): query extraction with visual descriptions"
```

---

### Task 6: Keyword search (TikTok, YouTube, X)

**Files:**
- Modify: `python/src/thoth_control_plane/attribution/adapters/discovery.py`
- Create: `python/src/thoth_control_plane/footage/adapters/youtube.py`
- Create: `python/src/thoth_control_plane/footage/adapters/x_search.py`
- Create: `python/src/thoth_control_plane/footage/adapters/search.py`
- Test: `python/tests/footage/test_search.py`

**Interfaces:**
- Produces: `ProfileDiscoverer.list(platform, request, *, require_account=False) -> list[DiscoveredVideo]`
  (the access-mode logic, now shared; `discover(platform, handle)` delegates to it).
- Produces: `YouTubeSearchDiscovery(client)` and `XSearchDiscovery(session_factory)`, each with
  `async discover(request: KeywordDiscovery) -> DiscoveryResult`; `parse_search(roots, limit) -> DiscoveryResult`.
- Produces: `PlatformSearch(discoverer)` with
  `async search(platform, query, limit) -> list[DiscoveredVideo]`; `build_platform_search(leases) -> PlatformSearch`;
  `SEARCH_FACTORIES`; `REQUIRES_ACCOUNT = frozenset({"x"})`.
- Evidence for X: research section 10 (the page renders in the browser; the page's own
  `SearchTimeline` response carries GraphQL tweets; fields listed there).

- [ ] **Step 1: Write the failing tests** `tests/footage/test_search.py`

```python
"""Keyword search for footage: YouTube via yt-dlp, X via the captured SearchTimeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.acquisition.models import (
    DiscoveredVideo,
    DiscoveryDrops,
    DiscoveryReason,
    DiscoveryResult,
    KeywordDiscovery,
)
from thoth_control_plane.attribution.adapters.discovery import DiscoveryBlocked, ProfileDiscoverer
from thoth_control_plane.footage.adapters.search import PlatformSearch
from thoth_control_plane.footage.adapters.x_search import XSearchDiscovery, parse_search
from thoth_control_plane.footage.adapters.youtube import YouTubeSearchDiscovery


def _tweet(rest_id: str, *, video: bool = True, retweet: bool = False) -> dict[str, Any]:
    media = [
        {
            "type": "video",
            "video_info": {"duration_millis": 42_000, "aspect_ratio": [9, 16], "variants": []},
        }
    ]
    legacy: dict[str, Any] = {
        "full_text": f"banjir di kemang {rest_id} https://t.co/abc",
        "created_at": "Wed Oct 14 10:00:00 +0000 2026",
        "favorite_count": 12,
        "reply_count": 3,
        "retweet_count": 4,
        "lang": "in",
    }
    if video:
        legacy["extended_entities"] = {"media": media}
    if retweet:
        legacy["retweeted_status_result"] = {"result": {"__typename": "Tweet"}}
    return {
        "__typename": "Tweet",
        "rest_id": rest_id,
        "core": {"user_results": {"result": {"core": {"screen_name": "warga_kemang"}}}},
        "legacy": legacy,
        "views": {"count": "1500"},
    }


def _timeline(*tweets: dict[str, Any]) -> dict[str, Any]:
    entries = [
        {"content": {"itemContent": {"tweet_results": {"result": tweet}}}} for tweet in tweets
    ]
    return {
        "data": {
            "search_by_raw_query": {
                "search_timeline": {
                    "timeline": {"instructions": [{"type": "TimelineAddEntries", "entries": entries}]}
                }
            }
        }
    }


def test_parse_search_keeps_video_tweets_in_order() -> None:
    result = parse_search(
        [_timeline(_tweet("1001"), _tweet("1002", video=False), _tweet("1003", retweet=True), _tweet("1004"))],
        limit=8,
    )
    assert [v.post_id for v in result.videos] == ["1001", "1004"]
    first = result.videos[0]
    assert str(first.canonical_url) == "https://x.com/warga_kemang/status/1001"
    assert first.caption == "banjir di kemang 1001"
    assert first.duration_seconds == 42.0
    assert first.published_at == "2026-10-14T10:00:00Z"
    assert first.engagement == {"like": 12, "comment": 3, "share": 4, "play": 1500}
    assert result.drops == DiscoveryDrops(photo_posts=1, invalid=1)


def test_an_empty_timeline_is_an_answer_not_a_failure() -> None:
    result = parse_search([_timeline()], limit=8)
    assert result.videos == [] and result.reason is None and result.exhausted


class _Entry:
    def __init__(self, body: dict[str, Any], status: int = 200) -> None:
        self.status = status
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


class _Response:
    def __init__(self, captured: list[Any]) -> None:
        self.captured_xhr = captured
        self.status = 200


class _Session:
    def __init__(self, captured: list[Any], seen: list[str]) -> None:
        self._captured = captured
        self._seen = seen

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def fetch(self, url: str, **kwargs: object) -> _Response:
        self._seen.append(url)
        return _Response(self._captured)


async def test_x_search_reads_the_captured_timeline() -> None:
    seen: list[str] = []
    patterns: list[str] = []

    def factory(**kwargs: Any) -> _Session:
        patterns.append(kwargs["capture_xhr"])
        return _Session([_Entry(_timeline(_tweet("1001")))], seen)

    result = await XSearchDiscovery(factory).discover(KeywordDiscovery(query="banjir kemang", limit=8))
    assert [v.post_id for v in result.videos] == ["1001"]
    assert seen == ["https://x.com/search?q=banjir%20kemang&f=video&src=typed_query"]
    assert patterns == [r"/SearchTimeline"]


async def test_x_search_without_a_captured_response_is_no_data() -> None:
    result = await XSearchDiscovery(lambda **kwargs: _Session([], [])).discover(
        KeywordDiscovery(query="banjir", limit=8)
    )
    assert result.videos == [] and result.reason is DiscoveryReason.NO_DATA


@pytest.mark.parametrize(
    "entry", [_Entry({}, status=429), _Entry({"errors": [{"code": 88, "message": "Rate limit"}]})]
)
async def test_x_refusing_the_search_is_blocked(entry: _Entry) -> None:
    result = await XSearchDiscovery(lambda **kwargs: _Session([entry], [])).discover(
        KeywordDiscovery(query="banjir", limit=8)
    )
    assert result.videos == [] and result.reason is DiscoveryReason.BLOCKED


async def test_an_empty_captured_timeline_is_an_empty_answer() -> None:
    result = await XSearchDiscovery(lambda **kwargs: _Session([_Entry(_timeline())], [])).discover(
        KeywordDiscovery(query="topik sepi", limit=8)
    )
    assert result.videos == [] and result.reason is None


class _YtClient:
    def __init__(self) -> None:
        self.extracted: list[str] = []

    async def listing(self, url: str, limit: int) -> dict[str, Any]:
        assert url == "ytsearch8:banjir kemang" and limit == 8
        return {
            "entries": [
                {"id": f"vid{n:08d}", "view_count": n * 100} for n in range(1, 9)
            ]
        }

    async def extract(self, url: str, *, comments: bool) -> dict[str, Any]:
        self.extracted.append(url)
        return {"id": url[-11:], "title": "banjir kemang", "duration": 50, "channel": "c",
                "uploader_id": "@kanal", "channel_id": "UC123", "view_count": 5, "like_count": 1}


async def test_youtube_search_details_the_five_most_viewed() -> None:
    client = _YtClient()

    async def no_sleep(seconds: float) -> None:
        return None

    result = await YouTubeSearchDiscovery(client, sleep=no_sleep).discover(  # type: ignore[arg-type]
        KeywordDiscovery(query="banjir kemang", limit=8)
    )
    assert len(client.extracted) == 5
    assert client.extracted[0].endswith("vid00000008")
    assert result.kind == "keyword"


class _Leases:
    def __init__(self, mode: str) -> None:
        self._mode = mode
        self.leased: list[str] = []

    async def mode(self, platform: str) -> str:
        return self._mode

    async def lease(self, platform: str) -> None:
        self.leased.append(platform)
        return None

    async def release(self, lease: object, outcome: object) -> None:
        return None


class _Lease:
    account_id = "account-1"
    access = None
    leased_until = None


class _RecordingLeases(_Leases):
    def __init__(self) -> None:
        super().__init__("anonymous")
        self.outcomes: list[object] = []

    async def lease(self, platform: str) -> _Lease:  # type: ignore[override]
        self.leased.append(platform)
        return _Lease()

    async def release(self, lease: object, outcome: object) -> None:
        self.outcomes.append(outcome)


@pytest.mark.parametrize(
    ("reason", "outcome"),
    [(None, None), (DiscoveryReason.NO_DATA, None), (DiscoveryReason.BLOCKED, "blocked")],
)
async def test_only_a_refusal_cools_the_x_account_down(
    reason: DiscoveryReason | None, outcome: str | None
) -> None:
    class Discovery:
        async def discover(self, request: KeywordDiscovery) -> DiscoveryResult:
            return DiscoveryResult(
                kind="keyword", videos=[], pages=1, exhausted=True, drops=DiscoveryDrops(),
                reason=reason,
            )

    leases = _RecordingLeases()
    search = PlatformSearch(
        ProfileDiscoverer({"x": lambda access, scratch: Discovery()}, leases=leases)  # type: ignore[arg-type]
    )
    if reason is DiscoveryReason.BLOCKED:
        with pytest.raises(DiscoveryBlocked):
            await search.search("x", "banjir", 8)
    else:
        assert await search.search("x", "banjir", 8) == []
    assert leases.leased == ["x"] and leases.outcomes == [outcome]


async def test_x_search_always_asks_for_an_account() -> None:
    calls: list[object] = []

    class Discovery:
        async def discover(self, request: KeywordDiscovery) -> DiscoveryResult:
            calls.append(request)
            return DiscoveryResult(kind="keyword", videos=[], pages=1, exhausted=True, drops=DiscoveryDrops())

    leases = _Leases("anonymous")
    search = PlatformSearch(
        ProfileDiscoverer({"x": lambda access, scratch: Discovery()}, leases=leases)  # type: ignore[arg-type]
    )
    assert await search.search("x", "banjir", 8) == []
    assert leases.leased == ["x"]  # even with the platform's mode set to anonymous
    assert isinstance(calls[0], KeywordDiscovery)


def test_youtube_discovery_module_still_imports(tmp_path: Path) -> None:
    assert DiscoveredVideo  # the shared model the adapters return
    with pytest.raises(ValueError):
        KeywordDiscovery(query="\x00", limit=8)
```

Check `_YtClient.extract`'s returned dict against what `youtube_discovery._video` /
`adapters.youtube.parse_info` require (read `parse_info` before running); add the fields
`parse_info` needs so the five detailed entries validate, and assert
`len(result.videos) == 5` once they do.

- [ ] **Step 2: Run them to see them fail**

Run: `cd python && uv run pytest tests/footage/test_search.py -q`
Expected: FAIL — `ModuleNotFoundError: thoth_control_plane.footage.adapters.search`.

- [ ] **Step 3: Share the access-mode logic** in `attribution/adapters/discovery.py`

Replace `ProfileDiscoverer.discover` and `_run` with:

```python
    async def discover(self, platform: Platform, handle: str) -> list[DiscoveredVideo]:
        return await self.list(platform, ProfileDiscovery(handle=handle, limit=PROFILE_LIMIT))

    async def list(
        self,
        platform: str,
        request: ProfileDiscovery | KeywordDiscovery,
        *,
        require_account: bool = False,
    ) -> list[DiscoveredVideo]:
        """One listing under the platform's access mode; `require_account` acts as `always`.

        Footage search on X needs a signed-in page (research 2026-10-14, section 10).
        """
        mode: Mode = await self._leases.mode(platform) if self._leases else "anonymous"
        if require_account and self._leases is not None:
            mode = "always"
        anonymous: DiscoveryResult | None = None
        if mode != "always":
            anonymous = await self._run(platform, request, None)
            thin = 0 < len(anonymous.videos) < THIN_LISTING
            blocked = not anonymous.videos and anonymous.reason in RETRY_REASONS
            if mode == "anonymous" or not (thin or blocked):
                return _videos(anonymous)
        assert self._leases is not None  # a leasing mode implies a lease source
        lease = await self._leases.lease(platform)  # type: ignore[arg-type]
        if lease is None:
            logger.info("no source account for discovery platform=%s mode=%s", platform, mode)
            if anonymous is not None and anonymous.videos:
                return _videos(anonymous)
            if mode == "always":
                return _videos(await self._run(platform, request, None))
            raise DiscoveryBlocked(f"{platform} discovery blocked and no source account to lease")
        outcome: Outcome | None = None
        try:
            result = await self._run(platform, request, lease.access)
            if result.videos:
                outcome = "success"
            elif result.reason in CHALLENGE_REASONS:
                outcome = "challenge"
            elif result.reason in RETRY_REASONS:
                outcome = "blocked"
        except ToolMissing:
            raise
        except Exception:
            if anonymous is None or not anonymous.videos:
                raise
            logger.warning("signed-in discovery failed; keeping the anonymous listing")
            return _videos(anonymous)
        finally:
            await self._leases.release(lease, outcome)
        logger.info("discovery used a source account platform=%s outcome=%s", platform, outcome)
        if anonymous is not None and len(anonymous.videos) > len(result.videos):
            return _videos(anonymous)
        return _videos(result)

    async def _run(
        self,
        platform: str,
        request: ProfileDiscovery | KeywordDiscovery,
        access: SessionAccess | None,
    ) -> DiscoveryResult:
        # A private directory for yt-dlp's cookie file, removed with everything in it.
        with tempfile.TemporaryDirectory(prefix="thoth-discovery-") as scratch:
            discovery = self._factories[platform](access, Path(scratch))
            return await discovery.discover(request)
```

The outcome rule is exactly today's: videos report `success`; a captcha or challenge reports
`challenge`; a block reports `blocked`; anything else (an empty listing, `NO_DATA`, a timeout)
reports no outcome, so the account's health is untouched. An empty search is an answer, not a
refusal (ruling P3). Import `KeywordDiscovery` from `acquisition.models`.

Run: `cd python && uv run pytest tests/attribution -q` — Expected: PASS (behavior unchanged for
profiles).

- [ ] **Step 4: Implement `footage/adapters/youtube.py`**

```python
"""YouTube keyword search for footage: yt-dlp's `ytsearch`, flat, then a detail extract of the
five most viewed results (likes, upload time, duration). Never raises."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from thoth_control_plane.acquisition.adapters.youtube import channel_candidates, video_url
from thoth_control_plane.acquisition.discovery import _empty
from thoth_control_plane.acquisition.models import (
    DiscoveredVideo,
    DiscoveryDrops,
    DiscoveryReason,
    DiscoveryResult,
    KeywordDiscovery,
)
from thoth_control_plane.acquisition.youtube_discovery import (
    DETAIL_SPACING_SECONDS,
    _reason,
    _video,
)
from thoth_control_plane.acquisition.youtube_service import YtDlpClient, YtDlpError

SEARCH_RESULTS = 8
DETAILS = 5


class YouTubeSearchDiscovery:
    def __init__(
        self,
        client: YtDlpClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client or YtDlpClient()
        self._sleep = sleep

    async def discover(self, request: KeywordDiscovery) -> DiscoveryResult:
        try:
            listing = await self._client.listing(
                f"ytsearch{SEARCH_RESULTS}:{request.query}", SEARCH_RESULTS
            )
        except YtDlpError as error:
            return _empty("keyword", _reason(error))
        candidates = channel_candidates([listing], DETAILS)
        if not candidates:
            return _empty("keyword", DiscoveryReason.NO_DATA)
        videos: list[DiscoveredVideo] = []
        invalid = 0
        stopped: DiscoveryReason | None = None
        for index, video_id in enumerate(candidates):
            if index:
                await self._sleep(DETAIL_SPACING_SECONDS)
            try:
                info = await self._client.extract(video_url(video_id), comments=False)
            except YtDlpError as error:
                stopped = _reason(error)
                break
            video = _video(info, video_id)
            if video is None:
                invalid += 1
                continue
            videos.append(video)
        return DiscoveryResult(
            kind="keyword",
            videos=videos[: request.limit],
            pages=1,
            exhausted=False,
            drops=DiscoveryDrops(invalid=invalid),
            reason=stopped,
        )
```

- [ ] **Step 5: Implement `footage/adapters/x_search.py`**

```python
"""X keyword search for footage: a signed-in browser opens the search page and the page's own
`SearchTimeline` response is captured (verified live 2026-10-15, research section 10). Only
video tweets of their own author are kept; retweets are dropped. Never raises."""

from __future__ import annotations

import html
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any
from urllib.parse import quote

from thoth_control_plane.acquisition.adapters.x import (
    CANONICAL_BASE,
    _get,
    display_text,
    page_tweets,
    post_url,
)
from thoth_control_plane.acquisition.browser import (
    _decrement_active_sessions,
    _default_session_factory,
    _increment_active_sessions,
    _is_timeout,
)
from thoth_control_plane.acquisition.discovery import MAX_CAPTION, _empty
from thoth_control_plane.acquisition.models import (
    DiscoveredVideo,
    DiscoveryDrops,
    DiscoveryReason,
    DiscoveryResult,
    KeywordDiscovery,
)
from thoth_control_plane.acquisition.normalize import numeric_id, published_at_from_epoch

XHR_PATTERN = r"/SearchTimeline"
VIDEO_TYPES = frozenset({"video", "animated_gif"})
CREATED_AT = "%a %b %d %H:%M:%S %z %Y"
FETCH_TIMEOUT_MS = 60_000


def _count(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _video_media(tweet: dict[str, Any]) -> dict[str, Any] | None:
    media = _get(tweet, "legacy", "extended_entities", "media")
    for item in media if isinstance(media, list) else []:
        if isinstance(item, dict) and item.get("type") in VIDEO_TYPES:
            return item
    return None


def _published(tweet: dict[str, Any]) -> str | None:
    value = _get(tweet, "legacy", "created_at")
    if not isinstance(value, str):
        return None
    try:
        return published_at_from_epoch(int(datetime.strptime(value, CREATED_AT).timestamp()))
    except ValueError:
        return None


def _video(tweet: dict[str, Any], owner: str, media: dict[str, Any]) -> DiscoveredVideo | None:
    rest_id = numeric_id(tweet.get("rest_id"))
    text = _get(tweet, "note_tweet", "note_tweet_results", "result", "text")
    if not isinstance(text, str):
        text = _get(tweet, "legacy", "full_text")
    millis = _count(_get(media, "video_info", "duration_millis"))
    engagement = {
        key: count
        for key, count in (
            ("like", _count(_get(tweet, "legacy", "favorite_count"))),
            ("comment", _count(_get(tweet, "legacy", "reply_count"))),
            ("share", _count(_get(tweet, "legacy", "retweet_count"))),
            ("play", _count(_get(tweet, "views", "count"))),
        )
        if count is not None
    }
    if rest_id is None:
        return None
    try:
        return DiscoveredVideo(
            post_id=rest_id,
            owner_handle=owner,
            canonical_url=post_url(owner, rest_id),
            caption=display_text(html.unescape(text))[:MAX_CAPTION] if isinstance(text, str) else "",
            published_at=_published(tweet),
            duration_seconds=millis / 1000 if millis is not None else None,
            engagement=engagement,
        )
    except ValueError:
        return None


def parse_search(roots: Iterable[object], limit: int) -> DiscoveryResult:
    """X's answer to one search. Zero tweets is a valid empty answer, never a failure: an empty
    search must not cool the account down (ruling P3)."""
    tweets = page_tweets(roots)
    videos: list[DiscoveredVideo] = []
    photo_posts = invalid = 0
    for tweet in tweets:
        owner = _get(tweet, "core", "user_results", "result", "core", "screen_name")
        if not isinstance(owner, str) or isinstance(
            _get(tweet, "legacy", "retweeted_status_result"), dict
        ):
            invalid += 1
            continue
        media = _video_media(tweet)
        if media is None:
            photo_posts += 1
            continue
        video = _video(tweet, owner, media)
        if video is None:
            invalid += 1
            continue
        videos.append(video)
    return DiscoveryResult(
        kind="keyword",
        videos=videos[:limit],
        pages=1,
        exhausted=not tweets,
        drops=DiscoveryDrops(photo_posts=photo_posts, invalid=invalid),
    )


class XSearchDiscovery:
    def __init__(self, session_factory: Callable[..., Any] = _default_session_factory) -> None:
        self._session_factory = session_factory

    async def discover(self, request: KeywordDiscovery) -> DiscoveryResult:
        url = f"{CANONICAL_BASE}/search?q={quote(request.query, safe='')}&f=video&src=typed_query"
        try:
            session = self._session_factory(headless=True, max_pages=1, capture_xhr=XHR_PATTERN)
            active = await session.__aenter__()
        except Exception:
            return _empty("keyword", DiscoveryReason.BROWSER_UNAVAILABLE)
        _increment_active_sessions()
        try:
            response = await active.fetch(url, network_idle=True, timeout=FETCH_TIMEOUT_MS)
        except Exception as error:
            reason = DiscoveryReason.TIMEOUT if _is_timeout(error) else DiscoveryReason.BLOCKED
            return _empty("keyword", reason)
        finally:
            try:
                await session.__aexit__(None, None, None)
            except Exception:
                pass
            finally:
                _decrement_active_sessions()
        captured = getattr(response, "captured_xhr", None) or []
        if not captured:
            # No SearchTimeline at all (a slow load, a changed page, a logged-out session):
            # unknown, so the account's health is left alone.
            return _empty("keyword", DiscoveryReason.NO_DATA)
        roots: list[object] = []
        refused = False
        for entry in captured:
            status = getattr(entry, "status", None)
            if not isinstance(status, int) or status >= 400:
                refused = True
                continue
            try:
                body = entry.json()
            except Exception:
                continue
            if isinstance(body, dict) and body.get("errors") and not body.get("data"):
                refused = True  # GraphQL refusals (a rate limit) arrive with HTTP 200
                continue
            roots.append(body)
        if not roots:
            # X answered and refused: a block, which cools the account down.
            return _empty(
                "keyword", DiscoveryReason.BLOCKED if refused else DiscoveryReason.NO_DATA
            )
        return parse_search(roots, request.limit)
```

Confirm `CANONICAL_BASE` in `acquisition/adapters/x.py` is `https://x.com` (the test expects
`https://x.com/search?...`); if it differs, build the URL from `https://x.com` literally.
Confirm `page_tweets` walks plain dicts (it does for the profile page's decoded values) and
returns the timeline's `Tweet` nodes; if it needs other roots, pass `[body]` per response.

- [ ] **Step 6: Implement `footage/adapters/search.py`**

```python
"""Footage search per platform, under each platform's access mode (spec 2026-10-14, F4)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.models import DiscoveredVideo, KeywordDiscovery
from thoth_control_plane.attribution.adapters.discovery import (
    AccountLeases,
    DiscoveryFactory,
    ProfileDiscoverer,
    _tiktok,
)

REQUIRES_ACCOUNT = frozenset({"x"})


def _youtube(access: SessionAccess | None, scratch: Path) -> Any:
    from thoth_control_plane.acquisition.registry import _yt_dlp_factory
    from thoth_control_plane.acquisition.youtube_service import YtDlpClient
    from thoth_control_plane.footage.adapters.youtube import YouTubeSearchDiscovery

    factory = _yt_dlp_factory(access, scratch)
    return YouTubeSearchDiscovery(YtDlpClient(factory, signed_in=access is not None))


def _x(access: SessionAccess | None, scratch: Path) -> Any:
    from thoth_control_plane.acquisition.registry import _browser_factory
    from thoth_control_plane.footage.adapters.x_search import XSearchDiscovery

    return XSearchDiscovery(_browser_factory(access))


SEARCH_FACTORIES: Mapping[str, DiscoveryFactory] = {
    "tiktok": _tiktok,
    "youtube": _youtube,
    "x": _x,
}


class PlatformSearch:
    def __init__(self, discoverer: ProfileDiscoverer) -> None:
        self._discoverer = discoverer

    async def search(self, platform: str, query: str, limit: int) -> list[DiscoveredVideo]:
        """Raises `ValueError` for a query KeywordDiscovery refuses, `DiscoveryBlocked` when the
        platform blocked and no account could help."""
        request = KeywordDiscovery(query=query, limit=limit)
        return await self._discoverer.list(
            platform, request, require_account=platform in REQUIRES_ACCOUNT
        )


def build_platform_search(leases: AccountLeases | None) -> PlatformSearch:
    return PlatformSearch(ProfileDiscoverer(SEARCH_FACTORIES, leases=leases))
```

- [ ] **Step 7: Run the tests**

Run: `cd python && uv run pytest tests/footage/test_search.py tests/attribution -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add python/src/thoth_control_plane/attribution/adapters/discovery.py python/src/thoth_control_plane/footage/adapters/youtube.py python/src/thoth_control_plane/footage/adapters/x_search.py python/src/thoth_control_plane/footage/adapters/search.py python/tests/footage/test_search.py
git commit -m "feat(footage): keyword search on TikTok, YouTube, and X"
```

---

### Task 7: Clip checks (window, frames, vision, download)

**Files:**
- Create: `python/src/thoth_control_plane/footage/frames.py`
- Create: `python/src/thoth_control_plane/footage/adapters/vision.py`
- Create: `python/src/thoth_control_plane/footage/adapters/downloader.py`
- Test: `python/tests/footage/test_frames.py`, `python/tests/footage/test_clip_adapters.py`

**Interfaces:**
- Produces (`footage/frames.py`): `clip_window(duration) -> tuple[float, float] | None`,
  `vision_seconds(trim_start, duration) -> list[float]`, `dhash(jpeg) -> int`,
  `is_duplicate(hashes, others, distance=10) -> bool`.
- Produces (`footage/adapters/vision.py`): `FootageAnswer` (pydantic: `kind`, `shows_object`,
  `description`), `AgnoFootageJudge(api_key, model)` with
  `async judge(frames, visual) -> FootageAnswer` (raises `AttributionError("vision_unavailable")`).
- Produces (`footage/adapters/downloader.py`): `ClipError`,
  `YtDlpClipDownloader(ffmpeg)` with `async download(url, window, target) -> Path`.

- [ ] **Step 1: Write the failing tests** `tests/footage/test_frames.py`

```python
from __future__ import annotations

import cv2
import numpy as np

from thoth_control_plane.footage.frames import clip_window, dhash, is_duplicate, vision_seconds


def test_clip_window() -> None:
    assert clip_window(30.0) is None
    assert clip_window(12.5) is None
    assert clip_window(None) == (0.0, 30.0)
    assert clip_window(40.0) == (4.0, 24.0)  # 10% of 40, window of 20
    assert clip_window(31.0) == (3.1, 23.1)
    assert clip_window(600.0) == (60.0, 80.0)
    assert clip_window(35.0) == (3.5, 23.5)


def test_vision_seconds_spread_after_the_trim() -> None:
    assert vision_seconds(0.0, 20.0) == [4.0, 10.0, 16.0]
    assert vision_seconds(5.0, 15.0) == [7.0, 10.0, 13.0]


def _jpeg(seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    image = rng.integers(0, 255, (90, 160, 3), dtype=np.uint8)
    ok, data = cv2.imencode(".jpg", image)
    assert ok
    return data.tobytes()


def test_dhash_matches_itself_and_not_noise() -> None:
    a, b = dhash(_jpeg(1)), dhash(_jpeg(2))
    assert dhash(_jpeg(1)) == a
    assert is_duplicate([a, a, a], [[a]])
    assert not is_duplicate([a, a, a], [[b]])
    assert not is_duplicate([], [[a]])
    assert not is_duplicate([a], [])
```

`tests/footage/test_clip_adapters.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.attribution.ports import AttributionError, Frame
from thoth_control_plane.footage.adapters import downloader as downloader_module
from thoth_control_plane.footage.adapters.downloader import ClipError, YtDlpClipDownloader
from thoth_control_plane.footage.adapters.vision import FOOTAGE_PROMPT, AgnoFootageJudge, FootageAnswer


def test_the_prompt_names_the_visual_and_the_stage4_classes() -> None:
    assert "{visual}" in FOOTAGE_PROMPT
    assert "commentary" in FOOTAGE_PROMPT and "reaction" in FOOTAGE_PROMPT


async def test_the_judge_asks_with_the_visual(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_run(self: Any, schema: Any, prompt: str, frames: Any) -> FootageAnswer:
        seen.update(schema=schema, prompt=prompt, frames=len(frames))
        return FootageAnswer(kind="footage", shows_object="yes", description="A flooded street.")

    monkeypatch.setattr(AgnoFootageJudge, "_run", fake_run)
    frames = [Frame(second=float(n), jpeg=b"x") for n in range(5)]
    answer = await AgnoFootageJudge("k", "m").judge(frames, "a flooded street")
    assert answer.kind == "footage"
    assert seen["schema"] is FootageAnswer and seen["frames"] == 3
    assert "a flooded street" in seen["prompt"]


async def test_a_failed_download_is_a_clip_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, options: dict[str, Any]) -> None:
        raise RuntimeError("network")

    monkeypatch.setattr(downloader_module, "_run_yt_dlp", boom)
    with pytest.raises(ClipError):
        await YtDlpClipDownloader("ffmpeg").download(
            "https://www.tiktok.com/@a/video/7400000000000000001", (4.0, 24.0), tmp_path / "c.mp4"
        )
    assert list(tmp_path.iterdir()) == []


async def test_a_window_reaches_yt_dlp_and_the_file_lands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake(url: str, options: dict[str, Any]) -> None:
        seen.update(options)
        Path(options["outtmpl"].replace("%(ext)s", "mp4")).write_bytes(b"\x00" * 64)

    monkeypatch.setattr(downloader_module, "_run_yt_dlp", fake)
    target = tmp_path / "c.mp4"
    assert await YtDlpClipDownloader("ffmpeg").download("https://youtu.be/x", (4.0, 24.0), target) == target
    assert target.read_bytes() == b"\x00" * 64
    assert seen["force_keyframes_at_cuts"] is True and "download_ranges" in seen
    assert not any(p.name.endswith(".part") for p in tmp_path.iterdir())

    seen.clear()
    await YtDlpClipDownloader("ffmpeg").download("https://youtu.be/y", None, tmp_path / "d.mp4")
    assert "download_ranges" not in seen


def test_attribution_error_is_the_judge_failure() -> None:
    assert AttributionError("vision_unavailable").code == "vision_unavailable"
```

(Check `AttributionError` exposes `.code`; if it stores the code differently, assert on
`str(error)` instead.)

- [ ] **Step 2: Run them to see them fail**

Run: `cd python && uv run pytest tests/footage/test_frames.py tests/footage/test_clip_adapters.py -q`
Expected: FAIL — modules missing.

- [ ] **Step 3: Implement `footage/frames.py`**

```python
"""Pure helpers for the clip checks: the download window, vision sample times, and dHash."""

from __future__ import annotations

from collections.abc import Sequence

WINDOW_SECONDS = 20.0
WHOLE_UP_TO = 30.0
UNKNOWN_WINDOW = (0.0, 30.0)
LEAD_SHARE = 0.1
MIN_LEAD = 3.0
VISION_SHARES = (0.2, 0.5, 0.8)
HASH_SIZE = 8
DUPLICATE_DISTANCE = 10


def clip_window(duration: float | None) -> tuple[float, float] | None:
    """The span to download, or None for the whole clip (spec amendment 1)."""
    if duration is None:
        return UNKNOWN_WINDOW
    if duration <= WHOLE_UP_TO:
        return None
    start = min(max(MIN_LEAD, LEAD_SHARE * duration), duration - WINDOW_SECONDS)
    start = round(start, 3)
    return start, round(start + WINDOW_SECONDS, 3)


def vision_seconds(trim_start: float, duration: float) -> list[float]:
    span = max(duration - trim_start, 0.0)
    return [round(trim_start + span * share, 3) for share in VISION_SHARES]


def dhash(jpeg: bytes) -> int:
    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError("not an image")
    small = cv2.resize(image, (HASH_SIZE + 1, HASH_SIZE), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def is_duplicate(
    hashes: Sequence[int], others: Sequence[Sequence[int]], distance: int = DUPLICATE_DISTANCE
) -> bool:
    """Duplicate when at least half the frames sit within `distance` bits of a frame of one
    other clip (the main or an admitted clip)."""
    if not hashes:
        return False
    for other in others:
        close = sum(1 for h in hashes if any((h ^ o).bit_count() <= distance for o in other))
        if close * 2 >= len(hashes) and other:
            return True
    return False
```

- [ ] **Step 4: Implement `footage/adapters/vision.py`**

```python
"""The footage frame check: one structured vision call through Stage 4's reader."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from thoth_control_plane.attribution.adapters.vision import MAX_FRAMES, AgnoVisionReader
from thoth_control_plane.attribution.ports import Frame

FOOTAGE_PROMPT = (
    "These are frames of a short video. Answer three things. kind: is it raw footage of an "
    "event, place, or thing, or commentary (a person talking to the camera about it, a news "
    "anchor, a slideshow, or a reaction)? shows_object: do the frames show this: \"{visual}\"? "
    "Answer yes, partly, or no. description: one sentence on what the video shows. Answer in "
    "JSON."
)


class FootageAnswer(BaseModel):
    kind: Literal["footage", "commentary"] = Field(
        description="footage: raw footage; commentary: talking head, anchor, slideshow, reaction"
    )
    shows_object: Literal["yes", "partly", "no"]
    description: str = ""

    @field_validator("description", mode="before")
    @classmethod
    def _bounded(cls, value: object) -> object:
        return ("" if value is None else str(value)).strip()[:300]


class AgnoFootageJudge(AgnoVisionReader):
    async def judge(self, frames: Sequence[Frame], visual: str) -> FootageAnswer:
        """Raises `AttributionError("vision_unavailable")` on a provider error or a bad answer."""
        prompt = FOOTAGE_PROMPT.format(visual=" ".join(visual.split())[:300])
        return await self._run(FootageAnswer, prompt, frames[:MAX_FRAMES])
```

- [ ] **Step 5: Implement `footage/adapters/downloader.py`**

```python
"""Download a footage clip, or only its window, with yt-dlp; directly, never through an
account proxy (spec 2026-10-14, decision 7). The file lands through `.part` and `os.replace`."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

FORMAT = "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/b[ext=mp4]/b"
TIMEOUT_SECONDS = 75.0


class ClipError(Exception):
    """The clip could not be downloaded: a media failure of this candidate only."""


def _run_yt_dlp(url: str, options: dict[str, Any]) -> None:
    from yt_dlp import YoutubeDL

    with YoutubeDL(options) as ydl:
        ydl.download([url])


class YtDlpClipDownloader:
    def __init__(self, ffmpeg: str, timeout: float = TIMEOUT_SECONDS) -> None:
        self._ffmpeg = shutil.which(ffmpeg) or ffmpeg
        self._timeout = timeout

    async def download(self, url: str, window: tuple[float, float] | None, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="thoth-footage-", dir=target.parent) as scratch:
            options: dict[str, Any] = {
                "format": FORMAT,
                "merge_output_format": "mp4",
                "outtmpl": str(Path(scratch) / "clip.%(ext)s"),
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "socket_timeout": 20,
                "ffmpeg_location": self._ffmpeg,
            }
            if window is not None:
                from yt_dlp.utils import download_range_func

                options["download_ranges"] = download_range_func(None, [window])
                options["force_keyframes_at_cuts"] = True
            try:
                # ponytail: a timed-out download finishes in its thread; the scratch directory
                # is removed with it. Bounded by socket_timeout and the window's size.
                await asyncio.wait_for(
                    asyncio.to_thread(_run_yt_dlp, url, options), self._timeout
                )
            except Exception as error:
                raise ClipError(type(error).__name__) from None
            produced = sorted(Path(scratch).glob("clip.*"))
            if not produced or produced[0].stat().st_size == 0:
                raise ClipError("no file")
            part = target.with_name(target.name + ".part")
            shutil.move(produced[0], part)
            os.replace(part, target)
        return target
```

In the test, `download_range_func` must exist in the installed yt-dlp
(`yt_dlp.utils.download_range_func`; it does in 2026.8.19). The test only checks that the key is
present.

- [ ] **Step 6: Run the tests**

Run: `cd python && uv run pytest tests/footage/test_frames.py tests/footage/test_clip_adapters.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add python/src/thoth_control_plane/footage/frames.py python/src/thoth_control_plane/footage/adapters/vision.py python/src/thoth_control_plane/footage/adapters/downloader.py python/tests/footage/test_frames.py python/tests/footage/test_clip_adapters.py
git commit -m "feat(footage): clip window, vision judge, dHash, downloader"
```

---

### Task 8: FootageBuilder

**Files:**
- Create: `python/src/thoth_control_plane/footage/ports.py`
- Create: `python/src/thoth_control_plane/footage/service.py`
- Test: `python/tests/footage/test_service.py`

**Interfaces:**
- Consumes: everything from Tasks 2–7; `analyze_main_ocr` (5a); `AssemblyError`;
  `FrameSampler`, `DurationProbe`, `TextReader`, `RegionTracker`, `CaptionJudge` (assembly ports);
  `SourceReport`, `SourceAttribution`.
- Produces: `FootagePorts` (dataclass), `FootageInputs` (dataclass: `workflow_id`, `report`,
  `attribution`, `original`, `artifact_root`), `FootageBuilder(ports, *, aggregators, story_min, max_frames, clock=..., deadline_seconds=720.0, per_candidate_seconds=90.0, concurrency=3)`
  with `async build(inputs) -> FootageResult`; `select_batch(queues, admitted, total, size, per_query=PER_QUERY) -> list[CandidateView]`;
  `MAX_FOOTAGE = 6`, `PER_QUERY = 2`, `RESULTS_PER_QUERY = 8`, `SEARCH_PLATFORMS = ("tiktok", "youtube", "x")`.

- [ ] **Step 1: Write `footage/ports.py`**

```python
"""What the footage builder needs from the outside world; adapters implement it."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.attribution.ports import Frame
from thoth_control_plane.footage.adapters.vision import FootageAnswer
from thoth_control_plane.footage.models import (
    AdmittedClip,
    CandidateView,
    FootageObject,
    NewCandidate,
    RunView,
)
from thoth_control_plane.footage.queries import FootageQueryAnswer


class QueryModel(Protocol):
    async def read(self, prompt: str) -> FootageQueryAnswer | None: ...


class SearchPort(Protocol):
    async def search(self, platform: str, query: str, limit: int) -> list[DiscoveredVideo]: ...


class Embedder(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class ClipDownloader(Protocol):
    async def download(
        self, url: str, window: tuple[float, float] | None, target: Path
    ) -> Path: ...


class FootageJudge(Protocol):
    async def judge(self, frames: Sequence[Frame], visual: str) -> FootageAnswer: ...


class FootageState(Protocol):
    """`FootageStore`'s methods; synchronous, called through `asyncio.to_thread`."""

    def cached_search(self, platform: str, query: str) -> list[DiscoveredVideo] | None: ...
    def save_search(self, platform: str, query: str, videos: Sequence[DiscoveredVideo]) -> None: ...
    def run(self, workflow_id: str) -> RunView | None: ...
    def start_run(self, workflow_id: str, objects: Sequence[FootageObject]) -> RunView: ...
    def finish_run(self, workflow_id: str, footage_status: str) -> None: ...
    def candidates(self, workflow_id: str) -> list[CandidateView]: ...
    def add_candidates(self, workflow_id: str, items: Sequence[NewCandidate]) -> None: ...
    def score(self, workflow_id: str, url: str, story_score: float) -> None: ...
    def reject(self, workflow_id: str, url: str, reason: str, **fields: object) -> None: ...
    def admit(self, workflow_id: str, url: str, clip: AdmittedClip) -> None: ...
    def reopen(self, workflow_id: str, url: str) -> None: ...
    def admitted(self, workflow_id: str) -> list[CandidateView]: ...
```

- [ ] **Step 2: Write the failing tests** `tests/footage/test_service.py`

Use the real `FootageStore` on SQLite (Task 2 fixture pattern) and fakes for every other port.
The fakes record calls so the tests can assert that nothing expensive ran.

```python
"""FootageBuilder: order, quota, rejections, resume (spec 2026-10-14, F1-F9 and section 8)."""

from __future__ import annotations

from collections.abc import Sequence
import copy
import json
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from tests.assembly.support import FIXTURE
from tests.assembly.support import report as support_report
from thoth_control_plane.acquisition.models import DiscoveredVideo, SourceReport
from thoth_control_plane.assembly.ports import AssemblyError
from thoth_control_plane.attribution.ports import AttributionError, Frame
from thoth_control_plane.footage.adapters.downloader import ClipError
from thoth_control_plane.footage.adapters.vision import FootageAnswer
from thoth_control_plane.footage.queries import FootageQueryAnswer
from thoth_control_plane.footage.service import (
    FootageBuilder,
    FootageInputs,
    FootagePorts,
    select_batch,
)
from thoth_control_plane.infrastructure.footage_store import FootageStore
from thoth_control_plane.infrastructure.source_account_models import Base

NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)


def _report(*, slides: int = 0) -> SourceReport:
    """A TikTok main without media, or an Instagram carousel main with `slides` videos."""
    if not slides:
        return support_report(
            url="https://www.tiktok.com/@akun/video/7499999999999999999",
            owner="akun",
            text="Banjir besar di Kemang pagi ini",
            media="none",
        )
    data = copy.deepcopy(FIXTURE)
    data["workflow_id"] = "wf_a"
    data["source"] = {"platform": "instagram", "canonical_url": "https://www.instagram.com/p/MAIN1/"}
    data["post"].update(owner_handle="akun", text="Banjir besar di Kemang pagi ini")
    video = data["media"][0]
    data["media"] = [
        video | {"media_id": f"media_{n}", "index": n, "location": f"reports/wf_a/media/slide-{n}.mp4"}
        for n in range(1, slides + 1)
    ]
    data["comments"] = []
    return SourceReport.model_validate_json(json.dumps(data))
```

```python
def _video(n: int, caption: str = "air naik di jalan kemang", duration: float = 20.0, owner: str = "kreator") -> DiscoveredVideo:
    return DiscoveredVideo(
        post_id=f"74000000000000000{n:02d}",
        owner_handle=owner,
        canonical_url=f"https://www.tiktok.com/@{owner}/video/74000000000000000{n:02d}",
        caption=caption,
        duration_seconds=duration,
    )


class Queries:
    def __init__(self, answer: FootageQueryAnswer | None) -> None:
        self.answer = answer
        self.calls = 0

    async def read(self, prompt: str) -> FootageQueryAnswer | None:
        self.calls += 1
        return self.answer


TWO_OBJECTS = FootageQueryAnswer.model_validate(
    {
        "subjects": ["kemang"],
        "objects": [
            {"name": "banjir", "visual": "a flooded street"},
            {"name": "mobil terendam", "visual": "cars under water"},
        ],
    }
)


class Search:
    def __init__(self, results: dict[tuple[str, str], list[DiscoveredVideo]] | None = None, fail: set[str] | None = None) -> None:
        self.results = results or {}
        self.fail = fail or set()
        self.calls: list[tuple[str, str]] = []

    async def search(self, platform: str, query: str, limit: int) -> list[DiscoveredVideo]:
        self.calls.append((platform, query))
        if platform in self.fail:
            raise RuntimeError("blocked")
        if "\x00" in query:
            raise ValueError("bad query")
        return self.results.get((platform, query), [])


class Embedder:
    """Scores by keyword: a caption with 'kemang' is on the story, else off."""

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[1.0, 0.0] if "kemang" in text.lower() else [0.0, 1.0] for text in texts]


class Downloader:
    def __init__(self, fail: set[str] | None = None) -> None:
        self.fail = fail or set()
        self.calls: list[tuple[str, Any]] = []

    async def download(self, url: str, window: Any, target: Path) -> Path:
        self.calls.append((url, window))
        if url in self.fail:
            raise ClipError("network")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(url.encode() * 50)
        return target


class Frames:
    async def frame_at(self, video: Path, second: float, *, width: int) -> Frame:
        return Frame(second=second, jpeg=_jpeg_for(video))


def _jpeg_for(video: Path) -> bytes:
    import cv2
    import numpy as np

    seed = zlib.crc32(video.read_bytes()) if video.exists() else 0
    image = np.random.default_rng(seed).integers(0, 255, (90, 160, 3), dtype=np.uint8)
    return cv2.imencode(".jpg", image)[1].tobytes()


class Probe:
    async def duration(self, video: Path) -> float:
        return 20.0


class Text:
    def __init__(self, subtitled: set[str] | None = None) -> None:
        self.subtitled = subtitled or set()

    async def read(self, frame: Frame) -> list[Any]:
        return []


class Judge:
    def __init__(self, answers: dict[str, FootageAnswer | Exception] | None = None) -> None:
        self.answers = answers or {}
        self.calls: list[str] = []

    async def judge(self, frames: Sequence[Frame], visual: str) -> FootageAnswer:
        key = visual
        self.calls.append(key)
        answer = self.answers.get(key, FootageAnswer(kind="footage", shows_object="yes", description="A flooded street."))
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def store() -> FootageStore:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return FootageStore(engine, clock=lambda: NOW)


def _builder(store: FootageStore, **ports: Any) -> FootageBuilder:
    values: dict[str, Any] = {
        "queries": Queries(TWO_OBJECTS),
        "search": Search(),
        "embedder": Embedder(),
        "downloader": Downloader(),
        "frames": Frames(),
        "probe": Probe(),
        "text": Text(),
        "judge": Judge(),
        "store": store,
    }
    values.update(ports)
    return FootageBuilder(FootagePorts(**values), aggregators=frozenset({"kurator"}), story_min=0.33, max_frames=4, clock=lambda: NOW)


def _inputs(tmp_path: Path, report: SourceReport | None = None) -> FootageInputs:
    return FootageInputs(workflow_id="wf_a", report=report or _report(), attribution=None, original=None, artifact_root=tmp_path)


def _hits(*videos: DiscoveredVideo, query: str = "banjir kemang") -> dict[tuple[str, str], list[DiscoveredVideo]]:
    return {("tiktok", query): list(videos)}
```

The `Text` fake returns no OCR boxes, so `analyze_main_ocr` yields `clean`. A subtitle verdict
is exercised through `monkeypatch` on `thoth_control_plane.footage.service.analyze_main_ocr` in
`test_a_subtitled_clip_is_rejected_and_deleted`.

Tests (each `async def`, `asyncio_mode = auto`):

```python
def test_select_batch_rounds_across_queries_and_respects_the_caps() -> None:
    from collections import Counter

    from thoth_control_plane.footage.models import CandidateView

    def view(url: str, query: str) -> CandidateView:
        return CandidateView(url=url, platform="tiktok", source="search", query=query, visual="v",
            owner_handle="o", caption="", published_at=None, engagement={}, source_duration=None,
            status="pending", reason=None, story_score=0.5, kind=None, shows_object=None,
            description=None, media_location=None, media_checksum=None, media_bytes=None,
            clip_duration=None, clip_start=None, ocr=None, position=None)

    queues = {"a": [view("a1", "a"), view("a2", "a"), view("a3", "a")], "b": [view("b1", "b")]}
    batch = select_batch(queues, Counter({"a": 1}), total=1, size=3)
    assert [c.url for c in batch] == ["a1", "b1"]  # a holds one admitted: one more slot only
    assert [c.url for c in queues["a"]] == ["a2", "a3"]
    assert select_batch({"a": [view("x", "a")]}, Counter(), total=6, size=3) == []


async def test_text_gates_and_story_gate_touch_no_media(store: FootageStore, tmp_path: Path) -> None:
    downloader, judge = Downloader(), Judge()
    search = Search(_hits(
        _video(1, caption="reaction banjir kemang"),
        _video(2, caption="https://bit.ly/x kemang"),
        _video(3, caption="resep nasi goreng"),
        _video(4, owner="kurator", caption="banjir kemang"),
        _video(5, caption="banjir kemang", duration=2.0),
    ))
    result = await _builder(store, search=search, downloader=downloader, judge=judge).build(_inputs(tmp_path))
    assert result.status == "none"
    assert result.rejected == {"reaction_text": 1, "spam": 1, "story": 1, "aggregator": 1, "duration": 1}
    assert downloader.calls == [] and judge.calls == []


async def test_quota_two_per_query_six_in_total(store: FootageStore, tmp_path: Path) -> None:
    answer = FootageQueryAnswer.model_validate({"subjects": ["kemang"], "objects": [
        {"name": f"objek{n}", "visual": f"visual {n}"} for n in range(4)]})
    results = {("tiktok", f"objek{n} kemang"): [_video(n * 10 + k) for k in range(3)] for n in range(4)}
    downloader = Downloader()
    result = await _builder(store, queries=Queries(answer), search=Search(results), downloader=downloader).build(_inputs(tmp_path))
    assert result.status == "ok" and result.admitted == 6
    admitted = store.admitted("wf_a")
    per_query: dict[str, int] = {}
    for c in admitted:
        per_query[c.query] = per_query.get(c.query, 0) + 1
    assert max(per_query.values()) <= 2
    assert [c.position for c in admitted] == list(range(6))
    assert len(downloader.calls) == 6  # stopped once six were admitted


async def test_commentary_absent_object_and_vision_failure_are_rejected(store: FootageStore, tmp_path: Path) -> None:
    answer = FootageQueryAnswer.model_validate({"subjects": ["kemang"], "objects": [
        {"name": "a", "visual": "talking"}, {"name": "b", "visual": "absent"}, {"name": "c", "visual": "broken"}]})
    results = {("tiktok", "a kemang"): [_video(1)], ("tiktok", "b kemang"): [_video(2)], ("tiktok", "c kemang"): [_video(3)]}
    judge = Judge({
        "talking": FootageAnswer(kind="commentary", shows_object="yes", description="A man talks."),
        "absent": FootageAnswer(kind="footage", shows_object="no", description="A cat."),
        "broken": AttributionError("vision_unavailable"),
    })
    result = await _builder(store, queries=Queries(answer), search=Search(results), judge=judge).build(_inputs(tmp_path))
    assert result.status == "none"
    assert result.rejected == {"commentary": 1, "object_absent": 1, "vision_unavailable": 1}
    assert list((tmp_path / "reports" / "wf_a" / "footage").glob("*.mp4")) == []  # rejected windows deleted


async def test_a_failed_download_is_media_failed(store: FootageStore, tmp_path: Path) -> None:
    video = _video(1)
    result = await _builder(store, search=Search(_hits(video)), downloader=Downloader({str(video.canonical_url)})).build(_inputs(tmp_path))
    assert result.rejected == {"media_failed": 1}


async def test_a_subtitled_clip_is_rejected_and_deleted(store: FootageStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from thoth_control_plane.footage import service

    async def subtitled(*args: Any, **kwargs: Any) -> Any:
        from thoth_control_plane.assembly.models import MainOcr
        return MainOcr(analyzed_at=NOW, requested_frames=4, valid_frames=4, outcome="subtitle",
            trim_start=0.0, mute_audio=True, subtitle_blur=[{"x": 0.1, "y": 0.8, "w": 0.8, "h": 0.1}])

    monkeypatch.setattr(service, "analyze_main_ocr", subtitled)
    judge = Judge()
    result = await _builder(store, search=Search(_hits(_video(1))), judge=judge).build(_inputs(tmp_path))
    assert result.rejected == {"subtitle": 1} and judge.calls == []


async def test_incomplete_ocr_is_media_failed_but_a_missing_tool_raises(store: FootageStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from thoth_control_plane.footage import service

    async def incomplete(*args: Any, **kwargs: Any) -> Any:
        raise AssemblyError("incomplete_frame_coverage")

    monkeypatch.setattr(service, "analyze_main_ocr", incomplete)
    result = await _builder(store, search=Search(_hits(_video(1)))).build(_inputs(tmp_path))
    assert result.rejected == {"media_failed": 1}

    async def no_ffmpeg(*args: Any, **kwargs: Any) -> Any:
        raise AssemblyError("ffmpeg_missing")

    monkeypatch.setattr(service, "analyze_main_ocr", no_ffmpeg)
    with pytest.raises(AssemblyError, match="ffmpeg_missing"):
        await _builder(store, search=Search(_hits(_video(2)))).build(
            FootageInputs(workflow_id="wf_b", report=_report(), attribution=None, original=None, artifact_root=tmp_path)
        )


async def test_a_duplicate_of_an_admitted_clip_is_rejected(store: FootageStore, tmp_path: Path) -> None:
    # Two different URLs whose downloaded bytes (and so frames) are identical.
    class Same(Downloader):
        async def download(self, url: str, window: Any, target: Path) -> Path:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"same" * 50)
            return target

    result = await _builder(store, search=Search(_hits(_video(1), _video(2))), downloader=Same()).build(_inputs(tmp_path))
    assert result.admitted == 1 and result.rejected == {"duplicate": 1}


async def test_all_platforms_failing_is_unavailable(store: FootageStore, tmp_path: Path) -> None:
    result = await _builder(store, search=Search(fail={"tiktok", "youtube", "x"})).build(_inputs(tmp_path))
    assert result.status == "unavailable"


async def test_one_platform_failing_leaves_the_others(store: FootageStore, tmp_path: Path) -> None:
    result = await _builder(store, search=Search(_hits(_video(1)), fail={"x"})).build(_inputs(tmp_path))
    assert result.status == "ok"


async def test_no_query_answer_twice_is_unavailable(store: FootageStore, tmp_path: Path) -> None:
    queries = Queries(None)
    result = await _builder(store, queries=queries).build(_inputs(tmp_path))
    assert result.status == "unavailable" and queries.calls == 2


async def test_an_invalid_query_is_skipped(store: FootageStore, tmp_path: Path) -> None:
    answer = FootageQueryAnswer.model_validate({"subjects": [], "objects": [
        {"name": "bad\x00query", "visual": "x"}, {"name": "banjir kemang", "visual": "a flooded street"}]})
    result = await _builder(store, queries=Queries(answer), search=Search(_hits(_video(1)))).build(_inputs(tmp_path))
    assert result.status == "ok"


async def test_one_url_found_twice_is_one_candidate(store: FootageStore, tmp_path: Path) -> None:
    video = _video(1)
    results = {("tiktok", "banjir kemang"): [video], ("youtube", "banjir kemang"): [video],
               ("tiktok", "mobil terendam kemang"): [video]}
    await _builder(store, search=Search(results)).build(_inputs(tmp_path))
    assert len(store.candidates("wf_a")) == 1


async def test_a_retry_redoes_pending_and_keeps_admitted(store: FootageStore, tmp_path: Path) -> None:
    search = Search(_hits(_video(1), _video(2)))
    queries = Queries(TWO_OBJECTS)
    await _builder(store, search=search, queries=queries).build(_inputs(tmp_path))
    first = store.admitted("wf_a")

    # Simulate a crash: the run is not done, one admitted file vanished, a .part lingers.
    from thoth_control_plane.infrastructure.footage_models import FootageRunRow
    with store._sessions.begin() as session:  # noqa: SLF001 — test-only rewind
        session.get(FootageRunRow, "wf_a").status = "running"
    (tmp_path / first[0].media_location).unlink()
    stale = tmp_path / "reports" / "wf_a" / "footage" / "stale.mp4.part"
    stale.write_bytes(b"x")

    search.calls.clear()
    judge = Judge()
    result = await _builder(store, search=search, queries=queries, judge=judge).build(_inputs(tmp_path))
    assert queries.calls == 1  # the objects were reused
    assert search.calls == []  # the cache answered
    assert result.status == "ok"
    assert len(judge.calls) == 1  # only the reopened candidate was checked again
    assert not stale.exists()


async def test_a_done_run_is_not_redone(store: FootageStore, tmp_path: Path) -> None:
    queries = Queries(TWO_OBJECTS)
    await _builder(store, search=Search(_hits(_video(1))), queries=queries).build(_inputs(tmp_path))
    again = await _builder(store, queries=queries).build(_inputs(tmp_path))
    assert again.status == "ok" and queries.calls == 1


async def test_a_main_without_video_still_gets_footage(store: FootageStore, tmp_path: Path) -> None:
    report = _report()
    assert not [m for m in report.media if m.kind == "video"]
    result = await _builder(store, search=Search(_hits(_video(1)))).build(_inputs(tmp_path, report))
    assert result.status == "ok"


async def test_a_carousel_main_uses_its_own_video_slides(store: FootageStore, tmp_path: Path) -> None:
    for index in (1, 2, 3, 4):
        location = tmp_path / f"reports/wf_a/media/slide-{index}.mp4"
        location.parent.mkdir(parents=True, exist_ok=True)
        location.write_bytes(bytes([index]) * 20_000)
    search, downloader = Search(), Downloader()
    result = await _builder(store, search=search, downloader=downloader).build(
        _inputs(tmp_path, _report(slides=4))
    )
    # Three slides after the main, all from one "query": the per-query cap of two does not apply.
    assert result.admitted == 3 and search.calls == [] and downloader.calls == []
    admitted = store.admitted("wf_a")
    assert {c.source for c in admitted} == {"carousel"}
    assert all(c.url.startswith("https://www.instagram.com/p/MAIN1/#slide") for c in admitted)
    assert all(c.story_score == 1.0 for c in admitted)
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd python && uv run pytest tests/footage/test_service.py -q`
Expected: FAIL — `ModuleNotFoundError: thoth_control_plane.footage.service`.

- [ ] **Step 4: Implement `footage/service.py`**

```python
"""Footage for one workflow: queries, search, gates, clip checks, quota (spec 2026-10-14).

Cheap before expensive: text gates and the story gate touch no media; a candidate that passes
them is downloaded as a short window, then checked by OCR, vision, and a duplicate hash. Every
decision is stored as it is made, so a retry resumes instead of starting over.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from thoth_control_plane.acquisition.models import DiscoveredVideo, SourceReport
from thoth_control_plane.assembly.ocr import analyze_main_ocr
from thoth_control_plane.assembly.ports import (
    AssemblyError,
    CaptionJudge,
    DurationProbe,
    FrameSampler,
    RegionTracker,
    TextReader,
)
from thoth_control_plane.attribution.adapters.frames import DurationError, FrameError, ToolMissing
from thoth_control_plane.attribution.models import SourceAttribution
from thoth_control_plane.attribution.ports import AttributionError
from thoth_control_plane.footage.adapters.embedder import cosine
from thoth_control_plane.footage.frames import clip_window, dhash, is_duplicate, vision_seconds
from thoth_control_plane.footage.gates import MainIdentity, text_gate
from thoth_control_plane.footage.models import (
    AdmittedClip,
    CandidateView,
    FootageObject,
    FootageResult,
    FootageStatus,
    NewCandidate,
)
from thoth_control_plane.footage.ports import (
    ClipDownloader,
    Embedder,
    FootageJudge,
    FootageState,
    QueryModel,
    SearchPort,
)
from thoth_control_plane.footage.queries import footage_objects, query_prompt, top_comments

logger = logging.getLogger(__name__)

MAX_FOOTAGE = 6
PER_QUERY = 2
RESULTS_PER_QUERY = 8
SEARCH_PLATFORMS = ("tiktok", "youtube", "x")
CAROUSEL = "carousel"
VISION_WIDTH = 360
MEDIA_FAILURES = frozenset(
    {"incomplete_frame_coverage", "duration_probe_failed", "main_media_missing"}
)
HEADLINE_PREFIX = "headline: "
DEFAULT_VISUAL = "the scene the post is about"


@dataclass(frozen=True)
class FootagePorts:
    queries: QueryModel
    search: SearchPort
    embedder: Embedder
    downloader: ClipDownloader
    frames: FrameSampler
    probe: DurationProbe
    text: TextReader
    judge: FootageJudge
    store: FootageState
    tracker: RegionTracker | None = None
    captions: CaptionJudge | None = None


@dataclass(frozen=True)
class FootageInputs:
    workflow_id: str
    report: SourceReport
    attribution: SourceAttribution | None
    original: SourceReport | None
    artifact_root: Path


def _main(inputs: FootageInputs) -> SourceReport:
    """The main assembly uses (5a A2): the original when attribution replaced the post."""
    verdict = inputs.attribution.verdict if inputs.attribution is not None else "none"
    if verdict == "replaced" and inputs.original is not None:
        return inputs.original
    return inputs.report


def _headline(attribution: SourceAttribution | None) -> str:
    for item in attribution.evidence if attribution is not None else []:
        if item.kind == "cover_vision" and item.detail.startswith(HEADLINE_PREFIX):
            return item.detail[len(HEADLINE_PREFIX) :]
    return ""


def _carousel(main: SourceReport) -> dict[str, PurePosixPath]:
    """Spec F2: an Instagram /p/ post with at least two videos; the first video is the main."""
    url = str(main.source.canonical_url)
    videos = [media for media in main.media if media.kind == "video"]
    if main.source.platform != "instagram" or "/p/" not in url or len(videos) < 2:
        return {}
    return {
        f"{url}#slide{media.index}": media.location for media in videos[1 : MAX_FOOTAGE + 1]
    }


def select_batch(
    queues: dict[str, list[CandidateView]],
    admitted: Counter[str],
    total: int,
    size: int,
    per_query: int = PER_QUERY,
) -> list[CandidateView]:
    """Take up to `size` candidates in rounds across queries, within the per-query and total caps."""
    batch: list[CandidateView] = []
    taken: Counter[str] = Counter()
    progress = True
    while progress and len(batch) < size and total + len(batch) < MAX_FOOTAGE:
        progress = False
        for query, queue in queues.items():
            if len(batch) >= size or total + len(batch) >= MAX_FOOTAGE:
                break
            if queue and admitted[query] + taken[query] < per_query:
                batch.append(queue.pop(0))
                taken[query] += 1
                progress = True
    return batch


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return "sha256:" + hashlib.file_digest(handle, "sha256").hexdigest()


class FootageBuilder:
    def __init__(
        self,
        ports: FootagePorts,
        *,
        aggregators: frozenset[str],
        story_min: float,
        max_frames: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        deadline_seconds: float = 720.0,
        per_candidate_seconds: float = 90.0,
        concurrency: int = 3,
    ) -> None:
        self._ports = ports
        self._store = ports.store
        self._aggregators = aggregators
        self._story_min = story_min
        self._max_frames = max_frames
        self._clock = clock
        self._deadline = deadline_seconds
        self._per_candidate = per_candidate_seconds
        self._concurrency = concurrency
        self._position = 0

    async def build(self, inputs: FootageInputs) -> FootageResult:
        started = time.monotonic()
        workflow = inputs.workflow_id
        main = _main(inputs)
        run = await asyncio.to_thread(self._store.run, workflow)
        if run is not None and run.status == "done":
            return await self._result(workflow, run.footage_status or "unavailable")
        self._clean_parts(inputs.artifact_root, workflow)

        slides = _carousel(main)
        if slides:
            await asyncio.to_thread(self._store.start_run, workflow, [])
            await asyncio.to_thread(
                self._store.add_candidates,
                workflow,
                [
                    NewCandidate(
                        url=url,
                        platform="instagram",
                        source="carousel",
                        query=CAROUSEL,
                        visual="",
                        owner_handle=main.post.owner_handle,
                        caption=main.post.text[:2000],
                    )
                    for url in slides
                ],
            )
            return await self._check_all(inputs, main, started, [CAROUSEL], slides)

        if run is None:
            found = await self._objects(main, inputs.attribution)
            if found is None:
                await asyncio.to_thread(self._store.start_run, workflow, [])
                await asyncio.to_thread(self._store.finish_run, workflow, "unavailable")
                return FootageResult(status="unavailable")
            run = await asyncio.to_thread(self._store.start_run, workflow, found)
        objects = run.objects
        if not objects:
            await asyncio.to_thread(self._store.finish_run, workflow, "none")
            return FootageResult(status="none")

        hits, failed = await self._search(objects)
        if failed:
            await asyncio.to_thread(self._store.finish_run, workflow, "unavailable")
            return await self._result(workflow, "unavailable")
        identity = MainIdentity.of(
            str(main.source.canonical_url),
            [str(inputs.report.source.canonical_url)],
            main.post.text,
        )
        await self._gate(workflow, identity, objects, hits)
        await self._story(workflow, main)
        return await self._check_all(inputs, main, started, [obj.query for obj in objects], {})

    async def _objects(
        self, main: SourceReport, attribution: SourceAttribution | None
    ) -> list[FootageObject] | None:
        comments = top_comments((comment.text, comment.likes) for comment in main.comments)
        prompt = query_prompt(main.post.text, _headline(attribution), comments)
        if prompt is None:
            return []
        for _ in range(2):  # spec F3: one retry
            answer = await self._ports.queries.read(prompt)
            if answer is not None:
                return footage_objects(answer)
        return None

    async def _search(
        self, objects: Sequence[FootageObject]
    ) -> tuple[dict[str, list[tuple[str, DiscoveredVideo]]], bool]:
        async def platform(name: str) -> dict[str, list[DiscoveredVideo]] | None:
            found: dict[str, list[DiscoveredVideo]] = {}
            for obj in objects:
                cached = await asyncio.to_thread(self._store.cached_search, name, obj.query)
                if cached is None:
                    try:
                        cached = await self._ports.search.search(
                            name, obj.query, RESULTS_PER_QUERY
                        )
                    except ToolMissing:
                        raise
                    except ValueError:  # a query KeywordDiscovery refuses
                        logger.warning("footage query refused platform=%s", name)
                        continue
                    except Exception:
                        logger.warning("footage search failed platform=%s", name)
                        return None
                    await asyncio.to_thread(self._store.save_search, name, obj.query, cached)
                found[obj.query] = list(cached)
            return found

        results = await asyncio.gather(*(platform(name) for name in SEARCH_PLATFORMS))
        merged: dict[str, list[tuple[str, DiscoveredVideo]]] = {obj.query: [] for obj in objects}
        for name, result in zip(SEARCH_PLATFORMS, results, strict=True):
            for query, videos in (result or {}).items():
                merged[query].extend((name, video) for video in videos)
        logger.info(
            "footage search done platforms_failed=%d hits=%d",
            sum(1 for result in results if result is None),
            sum(len(items) for items in merged.values()),
        )
        return merged, all(result is None for result in results)

    async def _gate(
        self,
        workflow: str,
        identity: MainIdentity,
        objects: Sequence[FootageObject],
        hits: dict[str, list[tuple[str, DiscoveredVideo]]],
    ) -> None:
        known = {c.url for c in await asyncio.to_thread(self._store.candidates, workflow)}
        new: list[NewCandidate] = []
        for obj in objects:
            for platform, video in hits.get(obj.query, []):
                url = str(video.canonical_url)
                if url in known:  # the same post from another platform or query
                    continue
                known.add(url)
                reason = text_gate(url, video, identity, self._aggregators)
                new.append(
                    NewCandidate(
                        url=url,
                        platform=platform,
                        source="search",
                        query=obj.query,
                        visual=obj.visual,
                        owner_handle=video.owner_handle,
                        caption=video.caption[:2000],
                        published_at=video.published_at,
                        engagement=dict(video.engagement),
                        source_duration=video.duration_seconds,
                        status="rejected" if reason else "pending",
                        reason=reason,
                    )
                )
        await asyncio.to_thread(self._store.add_candidates, workflow, new)

    async def _story(self, workflow: str, main: SourceReport) -> None:
        candidates = await asyncio.to_thread(self._store.candidates, workflow)
        unscored = [c for c in candidates if c.status == "pending" and c.story_score is None]
        if not unscored:
            return
        text = main.post.text
        story = f"{text[:120]}. {text}".strip()
        vectors = await self._ports.embedder.embed([story, *(c.caption for c in unscored)])
        for candidate, vector in zip(unscored, vectors[1:], strict=True):
            score = 0.0
            if candidate.caption.strip():
                score = max(0.0, min(1.0, cosine(vectors[0], vector)))
            if score < self._story_min:
                await asyncio.to_thread(
                    self._store.reject, workflow, candidate.url, "story", story_score=score
                )
            else:
                await asyncio.to_thread(self._store.score, workflow, candidate.url, score)

    async def _check_all(
        self,
        inputs: FootageInputs,
        main: SourceReport,
        started: float,
        queries: list[str],
        carousel: dict[str, PurePosixPath],
    ) -> FootageResult:
        workflow, root = inputs.workflow_id, inputs.artifact_root
        admitted_hashes = await self._verify_admitted(workflow, root)
        main_hashes = await self._main_hashes(main, root)
        candidates = await asyncio.to_thread(self._store.candidates, workflow)
        pending = [c for c in candidates if c.status == "pending"]
        admitted = Counter(c.query for c in candidates if c.status == "admitted")
        positions = [c.position for c in candidates if c.position is not None]
        self._position = max(positions, default=-1) + 1
        queues = {
            query: sorted(
                (c for c in pending if c.query == query), key=lambda c: -(c.story_score or 0.0)
            )
            for query in queries
        }
        per_query = MAX_FOOTAGE if carousel else PER_QUERY
        total = sum(admitted.values())
        while total < MAX_FOOTAGE and time.monotonic() - started < self._deadline:
            batch = select_batch(queues, admitted, total, self._concurrency, per_query)
            if not batch:
                break
            outcomes = await asyncio.gather(
                *(
                    self._timed(workflow, root, c, carousel.get(c.url), main_hashes, admitted_hashes)
                    for c in batch
                )
            )
            for candidate, ok in zip(batch, outcomes, strict=True):
                if ok:
                    admitted[candidate.query] += 1
                    total += 1
        status: FootageStatus = "ok" if total else "none"
        await asyncio.to_thread(self._store.finish_run, workflow, status)
        return await self._result(workflow, status)

    async def _timed(
        self,
        workflow: str,
        root: Path,
        candidate: CandidateView,
        existing: PurePosixPath | None,
        main_hashes: list[int],
        admitted_hashes: list[list[int]],
    ) -> bool:
        owned = existing is None
        name = hashlib.sha256(candidate.url.encode()).hexdigest()[:20] + ".mp4"
        location = existing or PurePosixPath("reports") / workflow / "footage" / name
        try:
            return await asyncio.wait_for(
                self._check(
                    workflow, root, candidate, location, owned, main_hashes, admitted_hashes
                ),
                self._per_candidate,
            )
        except TimeoutError:
            return await self._reject(workflow, root, candidate, location, owned, "media_failed")

    async def _check(
        self,
        workflow: str,
        root: Path,
        candidate: CandidateView,
        location: PurePosixPath,
        owned: bool,
        main_hashes: list[int],
        admitted_hashes: list[list[int]],
    ) -> bool:
        path = root / location
        window = clip_window(candidate.source_duration) if owned else None
        if owned:
            try:
                await self._ports.downloader.download(candidate.url, window, path)
            except ToolMissing:
                raise
            except Exception:
                return await self._reject(workflow, root, candidate, location, owned, "media_failed")
        try:
            ocr = await analyze_main_ocr(
                path,
                None,
                frames=self._ports.frames,
                probe=self._ports.probe,
                text=self._ports.text,
                max_frames=self._max_frames,
                now=self._clock(),
                trim_allowed=True,
                tracker=self._ports.tracker,
                judge=self._ports.captions,
            )
            if ocr.outcome == "subtitle":
                return await self._reject(workflow, root, candidate, location, owned, "subtitle")
            duration = await self._ports.probe.duration(path)
            frames = [
                await self._ports.frames.frame_at(path, second, width=VISION_WIDTH)
                for second in vision_seconds(ocr.trim_start, duration)
            ]
        except AssemblyError as error:
            if error.code in MEDIA_FAILURES:
                return await self._reject(workflow, root, candidate, location, owned, "media_failed")
            raise  # a missing tool is an explicit error
        except (FrameError, DurationError):
            return await self._reject(workflow, root, candidate, location, owned, "media_failed")
        try:
            answer = await self._ports.judge.judge(frames, candidate.visual or DEFAULT_VISUAL)
        except AttributionError:
            return await self._reject(
                workflow, root, candidate, location, owned, "vision_unavailable"
            )
        seen = {
            "kind": answer.kind,
            "shows_object": answer.shows_object,
            "description": answer.description,
        }
        if answer.kind == "commentary":
            return await self._reject(
                workflow, root, candidate, location, owned, "commentary", **seen
            )
        if answer.shows_object == "no":
            return await self._reject(
                workflow, root, candidate, location, owned, "object_absent", **seen
            )
        hashes = [dhash(frame.jpeg) for frame in frames]
        if is_duplicate(hashes, [main_hashes, *admitted_hashes]):
            return await self._reject(workflow, root, candidate, location, owned, "duplicate", **seen)
        admitted_hashes.append(hashes)
        position, self._position = self._position, self._position + 1
        clip = AdmittedClip(
            kind=answer.kind,
            shows_object=answer.shows_object,
            description=answer.description,
            media_location=location.as_posix(),
            media_checksum=_sha256(path),
            media_bytes=path.stat().st_size,
            clip_duration=duration,
            clip_start=window[0] if window else 0.0,
            ocr=ocr.model_dump(mode="json"),
            position=position,
        )
        await asyncio.to_thread(self._store.admit, workflow, candidate.url, clip)
        if candidate.source == "carousel":
            await asyncio.to_thread(self._store.score, workflow, candidate.url, 1.0)
        return True

    async def _reject(
        self,
        workflow: str,
        root: Path,
        candidate: CandidateView,
        location: PurePosixPath,
        owned: bool,
        reason: str,
        **seen: str,
    ) -> bool:
        if owned:  # a carousel slide is the acquisition's file, never deleted here
            (root / location).unlink(missing_ok=True)
        await asyncio.to_thread(self._store.reject, workflow, candidate.url, reason, **seen)
        return False

    async def _verify_admitted(self, workflow: str, root: Path) -> list[list[int]]:
        hashes: list[list[int]] = []
        for candidate in await asyncio.to_thread(self._store.admitted, workflow):
            path = root / (candidate.media_location or "")
            if not path.is_file() or _sha256(path) != candidate.media_checksum:
                await asyncio.to_thread(self._store.reopen, workflow, candidate.url)
                continue
            hashes.append(await self._hashes(path, candidate.clip_duration or 0.0))
        return hashes

    async def _main_hashes(self, main: SourceReport, root: Path) -> list[int]:
        videos = [media for media in main.media if media.kind == "video"]
        if not videos:
            return []
        path = root / videos[0].location
        if not path.is_file():
            return []
        try:
            duration = videos[0].duration_seconds or await self._ports.probe.duration(path)
        except DurationError:
            return []
        return await self._hashes(path, duration)

    async def _hashes(self, path: Path, duration: float) -> list[int]:
        try:
            frames = [
                await self._ports.frames.frame_at(path, second, width=VISION_WIDTH)
                for second in vision_seconds(0.0, duration)
            ]
        except FrameError:
            return []
        return [dhash(frame.jpeg) for frame in frames]

    async def _result(self, workflow: str, status: str) -> FootageResult:
        candidates = await asyncio.to_thread(self._store.candidates, workflow)
        reasons = Counter(c.reason for c in candidates if c.reason)
        admitted = sum(1 for c in candidates if c.status == "admitted")
        logger.info(
            "footage finished status=%s admitted=%d rejected=%s", status, admitted, dict(reasons)
        )
        return FootageResult(status=status, admitted=admitted, rejected=dict(reasons))  # type: ignore[arg-type]

    @staticmethod
    def _clean_parts(root: Path, workflow: str) -> None:
        for part in (root / "reports" / workflow / "footage").glob("*.part"):
            part.unlink(missing_ok=True)
```

Notes for the implementer:
- The fakes' `Text.read` returns `[]`; `analyze_main_ocr` then returns `clean`. Its frame
  sampler (`Frames.frame_at`) must accept the `width` keyword (it does).
- `FootageState.reject` is called with keyword fields; `FootageStore.reject` accepts them.
- Run `uv run ruff format` on the new files before committing.
- If `test_a_retry_redoes_pending_and_keeps_admitted` shows two vision calls, the `.part`
  cleanup or `_verify_admitted` is not running before the check loop; fix the order, not the test.

- [ ] **Step 5: Run the tests**

Run: `cd python && uv run pytest tests/footage -q`
Expected: PASS (the embedder test needs `THOTH_TEST_EMBEDDING_MODEL_DIR`, as in Task 4).

- [ ] **Step 6: Commit**

```bash
git add python/src/thoth_control_plane/footage/ports.py python/src/thoth_control_plane/footage/service.py python/tests/footage/test_service.py
git commit -m "feat(footage): footage builder with quota and resume"
```

---

### Task 9: Activity, workflow stage, worker, gateway

**Files:**
- Create: `python/src/thoth_control_plane/activities/footage.py`
- Modify: `python/src/thoth_control_plane/config.py`
- Modify: `python/src/thoth_control_plane/domain/models.py`
- Modify: `python/src/thoth_control_plane/workflows/source_investigation.py`
- Modify: `python/src/thoth_control_plane/infrastructure/temporal_gateway.py`
- Modify: `python/src/thoth_control_plane/worker.py`
- Test: `python/tests/activities/test_footage.py`, `python/tests/workflows/test_source_investigation.py`,
  `python/tests/test_worker.py`

**Interfaces:**
- Consumes: `FootageBuilder`, `FootageInputs`, `FootagePorts` (Task 8); adapters (Tasks 4–7);
  `FootageStore` (Task 2); `_attribution`, `_original`, `_heartbeat`, `REPORT_FILE` from
  `activities/content_assembly.py`; `_account_store`, `_account_profiles` from
  `activities/source_investigation.py`; `StoreLeases`, `load_curated`.
- Produces: `FootageActivityInput(workflow_id, attribution, original_report)`,
  `FootageActivityResult(footage_status, footage_count, events)`, activity name `build_footage`,
  `build_footage_activity(settings, *, builder=None)`, `build_production_footage(settings) -> FootageBuilder`;
  settings `THOTH_FOOTAGE_ENABLED: bool = False`, `THOTH_FOOTAGE_STORY_MIN: float = 0.33`;
  `SourceInvestigationWorkflowInput.build_footage: bool = False`; payload keys
  `footage_count`, `footage_status`.

- [ ] **Step 1: Settings and domain** — in `config.py` next to `THOTH_CONTENT_ASSEMBLY_ENABLED`:

```python
    THOTH_FOOTAGE_ENABLED: bool = False
    THOTH_FOOTAGE_STORY_MIN: Annotated[float, Field(ge=0.0, le=1.0)] = 0.33
```

(Import `Annotated`/`Field` if `config.py` does not already.) In `domain/models.py`, add
`"footage_count", "footage_status"` to `SOURCE_EVENT_PAYLOAD_KEYS`, and to
`SourceInvestigationWorkflowInput`:

```python
    # Absent from histories started before Stage 5b, so those replay without the new stage.
    build_footage: bool = False
```

- [ ] **Step 2: Write the failing activity test** `tests/activities/test_footage.py`

```python
from __future__ import annotations

from pathlib import Path

from tests.assembly.support import report as support_report
from thoth_control_plane.activities.footage import (
    FootageActivityInput,
    build_footage_activity,
)
from thoth_control_plane.config import Settings
from thoth_control_plane.footage.models import FootageResult


class Builder:
    def __init__(self) -> None:
        self.inputs: list[object] = []

    async def build(self, inputs: object) -> FootageResult:
        self.inputs.append(inputs)
        return FootageResult(status="ok", admitted=2, rejected={"story": 3})


def _settings(tmp_path: Path, **changes: object) -> Settings:
    return Settings(THOTH_CONTROL_PLANE_API_KEY="k", THOTH_CONTROL_PLANE_ARTIFACT_ROOT=tmp_path, **changes)  # type: ignore[arg-type]


async def test_disabled_footage_reports_disabled(tmp_path: Path) -> None:
    activity = build_footage_activity(_settings(tmp_path))
    result = await activity(FootageActivityInput(workflow_id="wf_a"))
    assert result.footage_status == "disabled" and result.footage_count == 0


async def test_a_missing_report_is_unavailable(tmp_path: Path) -> None:
    builder = Builder()
    activity = build_footage_activity(_settings(tmp_path), builder=builder)  # type: ignore[arg-type]
    result = await activity(FootageActivityInput(workflow_id="wf_a"))
    assert result.footage_status == "unavailable" and builder.inputs == []


async def test_the_builder_runs_on_the_stage3_report(tmp_path: Path) -> None:
    report = support_report(workflow_id="wf_a")
    folder = tmp_path / "reports" / "wf_a"
    folder.mkdir(parents=True)
    (folder / "source-report.json").write_text(report.model_dump_json(), encoding="utf-8")
    builder = Builder()
    activity = build_footage_activity(_settings(tmp_path), builder=builder)  # type: ignore[arg-type]
    result = await activity(FootageActivityInput(workflow_id="wf_a"))
    assert result.footage_status == "ok" and result.footage_count == 2
    assert result.events[-1].payload["stage"] == "footage"
    assert result.events[-1].payload["footage_count"] == 2
```

- [ ] **Step 3: Run it to see it fail**

Run: `cd python && uv run pytest tests/activities/test_footage.py -q`
Expected: FAIL — `ModuleNotFoundError: thoth_control_plane.activities.footage`.

- [ ] **Step 4: Implement `activities/footage.py`**

```python
"""The `build_footage` activity: footage for one workflow from its persisted reports.

It reads `reports/<workflow_id>/source-report.json`, the attribution and the original's report
the workflow passes, and runs the footage builder; state lives in PostgreSQL, clips under
`reports/<workflow_id>/footage/`. Only IDs, a status, counts, and elapsed milliseconds reach
Temporal history.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Protocol

from pydantic import Field
from temporalio import activity

from thoth_control_plane.acquisition.models import SourceReport
from thoth_control_plane.activities.content_assembly import (
    REPORT_FILE,
    _attribution,
    _heartbeat,
    _original,
)
from thoth_control_plane.config import Settings
from thoth_control_plane.domain.models import OpaqueId, SourceProgressEvent, StrictModel
from thoth_control_plane.footage.models import FootageResult
from thoth_control_plane.footage.service import FootageBuilder, FootageInputs


class FootageActivityInput(StrictModel):
    workflow_id: OpaqueId
    attribution: str | None = None
    original_report: str | None = None


class FootageActivityResult(StrictModel):
    footage_status: Literal["ok", "none", "disabled", "unavailable"]
    footage_count: Annotated[int, Field(ge=0, le=6)] = 0
    events: list[SourceProgressEvent] = Field(default_factory=list)


class Builder(Protocol):
    async def build(self, inputs: FootageInputs) -> FootageResult: ...


def _done(status: str, count: int, started: float) -> FootageActivityResult:
    return FootageActivityResult(
        footage_status=status,  # type: ignore[arg-type]
        footage_count=count,
        events=[
            SourceProgressEvent(
                kind="stage.completed",
                payload={
                    "stage": "footage",
                    "status": "succeeded",
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                    "footage_status": status,
                    "footage_count": count,
                },
            )
        ],
    )


async def _run(
    input_: FootageActivityInput, artifact_root: Path, builder: Builder | None
) -> FootageActivityResult:
    started = time.monotonic()
    if builder is None:
        return _done("disabled", 0, started)
    folder = PurePosixPath("reports") / input_.workflow_id
    try:
        report = SourceReport.model_validate_json((artifact_root / folder / REPORT_FILE).read_bytes())
    except (OSError, ValueError):
        return _done("unavailable", 0, started)
    heartbeat = asyncio.create_task(_heartbeat())
    try:
        result = await builder.build(
            FootageInputs(
                workflow_id=input_.workflow_id,
                report=report,
                attribution=_attribution(artifact_root, input_.attribution),
                original=_original(artifact_root, input_.original_report),
                artifact_root=artifact_root,
            )
        )
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
    return _done(result.status, result.admitted, started)


def build_production_footage(settings: Settings) -> FootageBuilder:
    from thoth_control_plane.activities.source_investigation import (
        _account_profiles,
        _account_store,
    )
    from thoth_control_plane.assembly.adapters.captions import AgnoCaptionJudge
    from thoth_control_plane.assembly.adapters.region import FfmpegRegionTracker
    from thoth_control_plane.attribution.adapters.discovery import StoreLeases
    from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource, FfprobeDuration
    from thoth_control_plane.attribution.adapters.ocr import RapidOcrReader
    from thoth_control_plane.attribution.candidates import load_curated
    from thoth_control_plane.footage.adapters.downloader import YtDlpClipDownloader
    from thoth_control_plane.footage.adapters.embedder import OnnxEmbedder
    from thoth_control_plane.footage.adapters.queries import AgnoQueryModel
    from thoth_control_plane.footage.adapters.search import build_platform_search
    from thoth_control_plane.footage.adapters.vision import AgnoFootageJudge
    from thoth_control_plane.footage.service import FootagePorts
    from thoth_control_plane.infrastructure.footage_store import FootageStore

    key = settings.openrouter_api_key
    database = settings.THOTH_EDITOR_DATABASE_URL
    if key is None or database is None:
        raise RuntimeError("footage needs the OpenRouter key and the editor database")
    accounts = _account_store(settings)
    leases = StoreLeases(accounts, _account_profiles(settings)) if accounts is not None else None
    return FootageBuilder(
        FootagePorts(
            queries=AgnoQueryModel(key, settings.THOTH_FOOTAGE_QUERY_MODEL),
            search=build_platform_search(leases),
            embedder=OnnxEmbedder(settings.THOTH_EMBEDDING_MODEL_DIR),
            downloader=YtDlpClipDownloader(settings.THOTH_FFMPEG),
            frames=FfmpegFrameSource(settings.THOTH_FFMPEG),
            probe=FfprobeDuration(settings.THOTH_FFPROBE),
            text=RapidOcrReader(angle=False),
            judge=AgnoFootageJudge(key, settings.THOTH_SOURCE_VISION_MODEL),
            store=FootageStore.connect(database.get_secret_value()),
            tracker=FfmpegRegionTracker(settings.THOTH_FFMPEG),
            captions=AgnoCaptionJudge(key, settings.THOTH_SOURCE_VISION_MODEL),
        ),
        aggregators=load_curated(),
        story_min=settings.THOTH_FOOTAGE_STORY_MIN,
        max_frames=settings.THOTH_SUBTITLE_OCR_MAX_FRAMES,
    )


@activity.defn(name="build_footage")
async def build_footage(input_: FootageActivityInput) -> FootageActivityResult:
    """Activity-name reference for workflow definitions and direct local use."""
    configured = build_footage_activity(Settings())  # type: ignore[call-arg]
    return await configured(input_)


def build_footage_activity(
    settings: Settings, *, builder: Builder | None = None
) -> Callable[[FootageActivityInput], Awaitable[FootageActivityResult]]:
    artifact_root = settings.THOTH_CONTROL_PLANE_ARTIFACT_ROOT.resolve()
    selected = builder or (
        build_production_footage(settings) if settings.THOTH_FOOTAGE_ENABLED else None
    )

    @activity.defn(name="build_footage")
    async def configured_footage_activity(input_: FootageActivityInput) -> FootageActivityResult:
        return await _run(input_, artifact_root, selected)

    return configured_footage_activity
```

Run: `cd python && uv run pytest tests/activities/test_footage.py -q` — Expected: PASS.

- [ ] **Step 5: Write the failing workflow tests** — append to
  `tests/workflows/test_source_investigation.py` (import `FootageActivityInput`,
  `FootageActivityResult` from `thoth_control_plane.activities.footage`):

```python
FOOTAGE_INPUTS: list[FootageActivityInput] = []
ORDER: list[str] = []


@activity.defn(name="build_footage")
async def fake_footage(input_: FootageActivityInput) -> FootageActivityResult:
    FOOTAGE_INPUTS.append(input_)
    ORDER.append("footage")
    return FootageActivityResult(footage_status="ok", footage_count=2)


@activity.defn(name="build_footage")
async def crashing_footage(input_: FootageActivityInput) -> FootageActivityResult:
    raise RuntimeError("footage detail must not enter history")


@activity.defn(name="assemble_content")
async def ordered_assemble(input_: ContentAssemblyActivityInput) -> ContentAssemblyActivityResult:
    ORDER.append("assembly")
    return await fake_assemble(input_)


def _with_footage(enabled: bool = True) -> SourceInvestigationWorkflowInput:
    return _assembled().model_copy(update={"build_footage": enabled})


@pytest.mark.asyncio
async def test_footage_runs_after_attribution_and_before_assembly(workflow_env: WorkflowEnvironment) -> None:
    FOOTAGE_INPUTS.clear()
    ORDER.clear()
    async with Worker(
        workflow_env.client, task_queue="test", workflows=[SourceInvestigationWorkflow],
        activities=[fake_inspect, fake_attribute, fake_footage, ordered_assemble],
    ):
        result = await workflow_env.client.execute_workflow(
            SourceInvestigationWorkflow.run, args=[_with_footage()], id="wf_test_footage", task_queue="test",
        )
    assert result.status == "succeeded"
    assert ORDER == ["footage", "assembly"]
    assert FOOTAGE_INPUTS[-1].attribution == "reports/wf_test_footage/source-attribution.json"


@pytest.mark.asyncio
async def test_a_crashing_footage_stage_never_fails_the_workflow(workflow_env: WorkflowEnvironment) -> None:
    async with Worker(
        workflow_env.client, task_queue="test", workflows=[SourceInvestigationWorkflow],
        activities=[fake_inspect, fake_attribute, crashing_footage, fake_assemble],
    ):
        result = await workflow_env.client.execute_workflow(
            SourceInvestigationWorkflow.run, args=[_with_footage()], id="wf_test_footage_crash", task_queue="test",
        )
    assert result.status == "succeeded"
    assert [a.kind for a in result.artifacts][-1] == "content_set"


@pytest.mark.asyncio
async def test_footage_off_runs_no_footage_activity(workflow_env: WorkflowEnvironment) -> None:
    FOOTAGE_INPUTS.clear()
    async with Worker(
        workflow_env.client, task_queue="test", workflows=[SourceInvestigationWorkflow],
        activities=[fake_inspect, fake_attribute, fake_footage, fake_assemble],
    ):
        await workflow_env.client.execute_workflow(
            SourceInvestigationWorkflow.run, args=[_with_footage(False)], id="wf_test_footage_off", task_queue="test",
        )
    assert FOOTAGE_INPUTS == []
```

The crash test retries three times; if the test environment's time-skipping makes it slow, give
the footage activity a `RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=1))`.
Also add a gateway test next to `test_the_gateway_requests_assembly_when_enabled`, copying it and
asserting `build_footage=True` reaches the workflow input when the gateway is built with
`build_footage=True`.

Run: `cd python && uv run pytest tests/workflows/test_source_investigation.py -q -k footage`
Expected: FAIL (`build_footage` field unused; no footage stage).

- [ ] **Step 6: Implement the stage** in `workflows/source_investigation.py`

Import (inside `imports_passed_through`):

```python
    from thoth_control_plane.activities.footage import FootageActivityInput, build_footage
```

In `run`, directly before `if input_.assemble_content:`:

```python
                if input_.assemble_content and input_.build_footage:
                    await self._footage()
                    if self._cancel_requested:
                        self._transition(WorkflowStatus.CANCELLED)
                        self._record_event(EventKind.WORKFLOW_CANCELLED)
                        return self._summary()
```

Add the method next to `_assemble`:

```python
    async def _footage(self) -> None:
        """Footage is optional (spec 2026-10-14): a failure never fails the workflow."""
        self._record_event(EventKind.STAGE_STARTED, stage=StageProgress(name="footage", progress=0.0))
        task = asyncio.create_task(
            workflow.execute_activity(
                build_footage,
                FootageActivityInput(
                    workflow_id=self._workflow_id,
                    attribution=self._attribution_location,
                    original_report=self._original_report,
                ),
                start_to_close_timeout=timedelta(minutes=20),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        )
        await workflow.wait_condition(lambda: self._cancel_requested or task.done())
        if self._cancel_requested and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, ActivityError):
                await task
            return
        try:
            result = await task
        except ActivityError:
            result = None
        if result is not None:
            self._source_events.extend(result.events)
            self._event_sequence += len(result.events)
        self._updated_at = workflow.now()
        self._record_event(EventKind.STAGE_COMPLETED, stage=StageProgress(name="footage", progress=1.0))
```

In `infrastructure/temporal_gateway.py`: add `build_footage: bool = False` to `__init__` (store
as `self._build_footage`), pass `build_footage=settings.THOTH_FOOTAGE_ENABLED` in `connect`, and
`build_footage=self._build_footage` into `SourceInvestigationWorkflowInput` in `start`.

- [ ] **Step 7: Worker registration and start checks** in `worker.py`

Register the activity in `build_source_investigation_worker` after the assembly one:

```python
            build_footage_activity(settings),
```

(import `build_footage_activity` from `thoth_control_plane.activities.footage`). At the end of
`check_media_tools`:

```python
    if settings.THOTH_FOOTAGE_ENABLED:
        from thoth_control_plane.footage.adapters.embedder import EMBEDDING_FILES

        if settings.openrouter_api_key is None:
            raise SettingsValidationError("openrouter_key_missing")
        if settings.THOTH_EDITOR_DATABASE_URL is None:
            raise SettingsValidationError("footage_database_missing")
        _require_media(settings)
        if missing(settings.THOTH_EMBEDDING_MODEL_DIR, EMBEDDING_FILES):
            raise SettingsValidationError("embedding_model_missing")
```

Tests in `tests/test_worker.py`:

```python
def _footage_settings(tmp_path: Path, **overrides: Any) -> Settings:
    embedding = tmp_path / "embedding"
    embedding.mkdir(exist_ok=True)
    for name in ("model.onnx", "tokenizer.json"):
        (embedding / name).write_bytes(b"x")
    values: dict[str, Any] = {
        "THOTH_CONTROL_PLANE_API_KEY": "test-only",
        "THOTH_SOURCE_ATTRIBUTION_ENABLED": False,
        "THOTH_FOOTAGE_ENABLED": True,
        "THOTH_OPENROUTER_API_KEY": "synthetic-key",
        "THOTH_EDITOR_DATABASE_URL": "postgresql://u:p@127.0.0.1:5432/db",
        "THOTH_EMBEDDING_MODEL_DIR": embedding,
    }
    return Settings(**{**values, **overrides})


def test_footage_starts_with_every_tool_present(tmp_path: Path) -> None:
    worker.check_media_tools(_footage_settings(tmp_path))


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"THOTH_OPENROUTER_API_KEY": None}, "openrouter_key_missing"),
        ({"THOTH_EDITOR_DATABASE_URL": None}, "footage_database_missing"),
        ({"THOTH_FFMPEG": "/nonexistent/ffmpeg"}, "ffmpeg_missing"),
        ({"THOTH_EMBEDDING_MODEL_DIR": Path("/nonexistent")}, "embedding_model_missing"),
    ],
)
def test_footage_refuses_to_start_without_a_tool(tmp_path: Path, change: dict[str, Any], code: str) -> None:
    from thoth_control_plane.config import SettingsValidationError

    with pytest.raises(SettingsValidationError, match=code):
        worker.check_media_tools(_footage_settings(tmp_path, **change))
```

If `SettingsValidationError`'s accepted codes are an enum or set, add `footage_database_missing`
and `embedding_model_missing` there.

- [ ] **Step 8: Run the tests**

Run: `cd python && uv run pytest tests/activities/test_footage.py tests/workflows/test_source_investigation.py tests/test_worker.py tests/infrastructure -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add python/src/thoth_control_plane/activities/footage.py python/src/thoth_control_plane/config.py python/src/thoth_control_plane/domain/models.py python/src/thoth_control_plane/workflows/source_investigation.py python/src/thoth_control_plane/infrastructure/temporal_gateway.py python/src/thoth_control_plane/worker.py python/tests/activities/test_footage.py python/tests/workflows/test_source_investigation.py python/tests/test_worker.py
git commit -m "feat(footage): footage stage before assembly"
```

---

### Task 10: Assembly reads footage; figures read footage descriptions

**Files:**
- Modify: `python/src/thoth_control_plane/assembly/service.py`
- Modify: `python/src/thoth_control_plane/assembly/figures.py`
- Modify: `python/src/thoth_control_plane/activities/content_assembly.py`
- Test: `python/tests/assembly/test_service.py`, `python/tests/assembly/test_figures.py`

**Interfaces:**
- Consumes: `FootageStore.run`, `FootageStore.admitted` (Task 2), `Footage` (Task 1).
- Produces: `AssemblyPorts.footage: FootageReader | None` (protocol with `run(workflow_id)` and
  `admitted(workflow_id)`), `figure_prompt(title, description, headline, footage=())`.

- [ ] **Step 1: Write the failing tests**

In `tests/assembly/test_figures.py`:

```python
def test_footage_descriptions_reach_the_figures_prompt() -> None:
    prompt = figure_prompt("Judul", "desc", "", ["Jensen Huang on stage.", "A server room."])
    assert prompt is not None
    assert "Jensen Huang on stage." in prompt and "A server room." in prompt
    assert "(empty)" in (figure_prompt("Judul", "desc", "") or "")
```

In `tests/assembly/test_service.py` (reuse its existing ports/fakes; add a fake reader):

```python
class FootageReader:
    def __init__(self, run: object, admitted: list[object]) -> None:
        self._run = run
        self._admitted = admitted

    def run(self, workflow_id: str) -> object:
        return self._run

    def admitted(self, workflow_id: str) -> list[object]:
        return self._admitted
```

Tests:
- ports without a footage reader → `footage_status == "disabled"`, `footage == []`;
- a reader whose `run` is `None` → `"unavailable"`;
- a reader whose run is `RunView(workflow_id="wf", status="done", footage_status="ok", objects=[])`
  with one admitted `CandidateView` (fields as in Task 2's `_clip`, `source="search"`,
  `platform="tiktok"`, a TikTok URL, `ocr` a full clean `MainOcr` dump) → one `Footage` with the
  admitted values, `footage_status == "ok"`;
- the same with `ocr` that does not validate (e.g. `{}`) → that item dropped and
  `footage_status == "none"` (a broken row never breaks the Content Set);
- a run that is `running` (not done) → `"unavailable"`.

Run: `cd python && uv run pytest tests/assembly/test_service.py tests/assembly/test_figures.py -q`
Expected: FAIL.

- [ ] **Step 2: Implement**

`assembly/figures.py`: add a `[FOOTAGE]` line to `PROMPT` after `[HEADLINE]`:

```
[FOOTAGE]: {footage}
```

and change the function:

```python
def figure_prompt(
    title: str, description: str, headline: str, footage: Sequence[str] = ()
) -> str | None:
    title, description, headline = title.strip(), description.strip(), headline.strip()
    if not (title or description or headline):
        return None
    shown = " ".join(item.strip() for item in footage if item.strip())
    return PROMPT.format(
        title=title[:200] or "(empty)",
        description=description[:600] or "(empty)",
        headline=headline[:200] or "(empty)",
        footage=shown[:600] or "(empty)",
    )
```

(`from collections.abc import Sequence`.) Update the existing figure test that checks the prompt
if it compares the whole text.

`assembly/service.py`:

```python
class FootageReader(Protocol):
    def run(self, workflow_id: str) -> Any: ...
    def admitted(self, workflow_id: str) -> list[Any]: ...
```

Add `footage: FootageReader | None = None` to `AssemblyPorts`. Add:

```python
def _footage_item(view: Any) -> Footage | None:
    try:
        return Footage(
            source=view.source,
            url=view.url,
            platform=view.platform,
            owner_handle=view.owner_handle,
            published_at=view.published_at,
            engagement=view.engagement,
            query=view.query,
            visual=view.visual,
            caption=view.caption[:2000],
            description=(view.description or "")[:300],
            video=MediaRef(
                location=view.media_location,
                media_type="video/mp4",
                checksum=view.media_checksum,
                bytes=view.media_bytes,
                duration_seconds=view.clip_duration,
            ),
            clip_start=view.clip_start or 0.0,
            ocr=MainOcr.model_validate(view.ocr or {}),
            story_score=min(1.0, max(0.0, view.story_score or 0.0)),
            shows_object=view.shows_object,
        )
    except (ValidationError, TypeError, ValueError):
        logger.warning("a stored footage clip failed validation; it is left out")
        return None
```

and a method on `ContentAssembler`:

```python
    async def _footage(self, workflow_id: str) -> tuple[list[Footage], FootageStatus]:
        reader = self._ports.footage
        if reader is None:
            return [], "disabled"
        try:
            run = await asyncio.to_thread(reader.run, workflow_id)
            views = await asyncio.to_thread(reader.admitted, workflow_id) if run else []
        except Exception:
            logger.warning("footage state unavailable; the content set continues without it")
            return [], "unavailable"
        if run is None or run.status != "done":
            return [], "unavailable"
        items = [item for item in (_footage_item(view) for view in views) if item is not None]
        if run.footage_status == "ok":
            return items, "ok" if items else "none"
        return [], run.footage_status or "unavailable"
```

In `build`, read footage before starting the figures task and pass its descriptions:

```python
        footage, footage_status = await self._footage(inputs.workflow_id)
        figures_task = asyncio.create_task(
            self._figures(
                fields["title"], fields["description"], _headline(inputs.attribution),
                [item.description for item in footage],
            )
        )
```

`_figures` gains the `footage: Sequence[str]` parameter and passes it to `figure_prompt`. Pass
`footage=footage, footage_status=footage_status` to `ContentSet(...)`. Import `Footage`,
`FootageStatus` from `assembly.models`; `Protocol`, `Sequence` as needed.

In `activities/content_assembly.py`, `build_production_assembler`, add to `AssemblyPorts(...)`:

```python
            footage=FootageStore.connect(settings.THOTH_EDITOR_DATABASE_URL.get_secret_value())
            if settings.THOTH_FOOTAGE_ENABLED and settings.THOTH_EDITOR_DATABASE_URL is not None
            else None,
```

(`from thoth_control_plane.infrastructure.footage_store import FootageStore` inside the
function.) Add `"footage_count"` to the assembly `stage.completed` payload:
`"footage_count": len(content_set.footage)`.

- [ ] **Step 3: Run the tests**

Run: `cd python && uv run pytest tests/assembly tests/activities -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add python/src/thoth_control_plane/assembly/service.py python/src/thoth_control_plane/assembly/figures.py python/src/thoth_control_plane/activities/content_assembly.py python/tests/assembly/test_service.py python/tests/assembly/test_figures.py
git commit -m "feat(assembly): Content Set footage from the footage stage"
```

---

### Task 11: Full verification and records

**Files:**
- Modify: `CHANGELOG.md` (CRLF), `docs/python-scout-migration-roadmap.md` (CRLF)
- Modify (gitignored): `.superpowers/sdd/2026-10-15-stage5b-footage/progress.md`

- [ ] **Step 1: Full suites**

```bash
cd python && THOTH_TEST_WHISPER_MODEL_DIR=/mnt/d/thoth-tmp/models/whisper-tiny THOTH_TEST_DIARIZATION_MODEL_DIR=/mnt/d/thoth-tmp/models/diarization THOTH_TEST_EMBEDDING_MODEL_DIR=/mnt/d/thoth-tmp/models/embedding uv run pytest -m "not live" -q
uv run --project python ruff check python/src python/tests
uv run --project python ruff format --check python/src python/tests
```

Expected: all pass; record the counts.

- [ ] **Step 2: Local image build proves the model layer**

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER && docker build -t thoth:5b-local . 2>&1 | tail -5'
wsl -e bash -lc 'docker run --rm --entrypoint sh thoth:5b-local -c "ls -la /opt/thoth/models/embedding"'
```

Expected: the build passes (the fetch script verifies both SHA-256s); the directory lists
`model.onnx` (~118 MB) and `tokenizer.json`.

- [ ] **Step 3: Records** — append a CHANGELOG entry "2026-10-15 - Stage 5b: footage" (byte-level
  CRLF, newest first) with: what was built, the spec amendment, the X probe evidence (research
  section 10), suite counts, rulings, and **Next steps**:
  - next: the calibration capture (operator gate: about five stories the operator picks; live
    searches and vision calls), then 5c (post cards, carousel photos, creator-profile footage);
  - operator gates: push, merge, CI, image pin, deploy, and turning `THOTH_FOOTAGE_ENABLED` on;
  - follow-ups: the JSON reports to PostgreSQL; the dashboard and Studio reading the new
    artifact; dossier-driven queries after Stage 6.

  Add a "Stage 5b status (2026-10-15)" paragraph to `docs/python-scout-migration-roadmap.md`
  pointing to the CHANGELOG. Update the ledger.

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md docs/python-scout-migration-roadmap.md
git commit -m "docs(changelog): Stage 5b footage"
```

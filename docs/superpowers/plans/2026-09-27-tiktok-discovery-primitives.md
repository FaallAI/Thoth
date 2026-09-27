# TikTok Discovery Primitives Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Stage 2 items 5-7: offline-tested profile, keyword, and trending TikTok discovery
primitives, plus engagement and publication-time normalization on the single-post path.

**Architecture:** A pure normalizer (`acquisition/normalize.py`) is shared by the headless
single-post path, the TikWM adapter, and discovery. Discovery (`acquisition/discovery.py`) opens
the ordinary TikTok page in one stealthy headless Scrapling session, scrolls it, and parses the
list responses the page itself makes. It never builds or signs an API request. A pure parser is
the offline test seam, and a fake session drives the scroll logic deterministically. Golden
fixtures come from one read-only anonymous capture, sanitized by a new operator tool.

**Tech Stack:** Python 3.12, Pydantic v2 strict models, Scrapling `AsyncStealthySession`
(Patchright), pytest with `asyncio_mode=auto`, ruff.

**Spec:** `docs/superpowers/specs/2026-09-27-tiktok-discovery-primitives-design.md`

## Global Constraints

- Every new contract extends `StrictModel` and reuses `TikTokNumericId` and `TikTokHandle`.
- Captchas are avoided, never solved or blocked. Never open `/search/video`. No captcha host in
  `blocked_domains`, no solver, no retry that re-triggers the challenge.
- No paid scraping service, no proxy, no logged-in source.
- No production caller, Temporal activity, or API route. Orchestration is Stage 8.
- Every test is offline. The conftest network guard is never weakened.
- Handles, queries, captions, URLs, and ids are never logged.
- The repository is public:
  - never commit raw captures, real ids, handles, captions, hashtags, or PNGs;
  - never print the discovery target handle or query.
- Raw captures stay under `D:/thoth-tmp/bu/out/`. All temp files go on `D:/thoth-tmp`.
- The only live run is the read-only fixture capture in Task 7. It needs the operator's
  fixture-capture authorization for this execution; stop and ask if it is absent. Never record
  that authorization in a repository document.
- No Rust changes, so `build_cuda.bat` is not required.
- Line endings:
  - Python source, tests, and fixtures are LF.
  - `CHANGELOG.md`, `docs/python-scout-migration-roadmap.md`, and the program `progress.md` are
    CRLF and are edited only through Python binary scripts.
- Tooling:
  - Windows `python` is Anaconda 3.10, and `python3` does not exist.
  - Tests run in WSL through `pt.sh`, invoked from Git Bash with `MSYS_NO_PATHCONV=1`.
  - The Bash tool mangles `\`+newline and heredoc backslashes. Create scripts with the Write
    tool.
- Commits:
  - exactly one `git commit -m "<subject>"` per commit;
  - subject at most 72 characters, no body;
  - no `Co-Authored-By` or any AI attribution.
- Work happens on branch `feat/tiktok-discovery-primitives`. Nothing is pushed.

**Test command** (from the repository root, in Git Bash):

```bash
MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh <paths relative to python/> 2>&1 | tail -5
```

**Ruff command** (do not pipe it through `tail`, or the exit code is lost):

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff format src tests && ~/.local/bin/uvx ruff check src tests' > D:/thoth-tmp/ruff.txt 2>&1; echo RC=$?
```

Expected: `RC=0`. On a non-zero code, read `D:/thoth-tmp/ruff.txt`, fix, and re-run.

## Review Focus

1. **String `createTime` in the rehydration script.** The single-post embedded data carries
   `createTime` as a decimal string, not a number. `published_at` must still be filled. Pinned in
   Task 3 by a test that uses `"1709287200"`.
2. **A scroll that loads nothing.** Discovery must stop after two idle scrolls, not spin to
   `MAX_SCROLLS`. Pinned in Task 5 (idle test: exactly 2 scrolls).
3. **An exception inside `page_action` or a failed in-page `body()` read.** It must never escape
   or discard what Scrapling already captured. Pinned in Task 5 (wheel error and body error
   tests).
4. **Counter and hashtag values TikTok mis-shapes.** Examples: a 20-digit or Arabic-Indic digit
   stat string, an empty hashtag, a 101-character hashtag. The bad value is skipped and the video
   is kept. Pinned in Task 2 (counts) and Task 4 (hashtags).
5. **A keyword with whitespace, control characters, or URL metacharacters.** Blank and
   control-character queries are rejected, `"  cats  "` is stripped, and `&`, `/`, and emoji are
   percent-encoded into the search URL. Pinned in Task 1 (validation) and Task 5 (page URL).

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `python/src/thoth_control_plane/acquisition/models.py` | Modify | Discovery contracts |
| `python/src/thoth_control_plane/acquisition/normalize.py` | Create | Pure engagement and epoch normalization |
| `python/src/thoth_control_plane/acquisition/browser.py` | Modify | Fill `published_at` and `engagement` from the item struct |
| `python/src/thoth_control_plane/acquisition/adapters/tikwm.py` | Modify | Fill them from TikWM data |
| `python/src/thoth_control_plane/acquisition/service.py` | Modify | `_merge_post` per-field merge |
| `python/src/thoth_control_plane/acquisition/discovery.py` | Create | Parser, scroll logic, `ScraplingDiscoveryBrowser` |
| `python/src/thoth_control_plane/operations/tiktok_discovery_fixture.py` | Create | Capture sanitizer with replay and leak checks |
| `python/tests/acquisition/test_models.py` | Modify | Contract tests |
| `python/tests/acquisition/test_normalize.py` | Create | Normalizer tests |
| `python/tests/acquisition/test_browser.py` | Modify | Snapshot normalization tests |
| `python/tests/acquisition/test_service.py` | Modify | TikWM and merge tests |
| `python/tests/acquisition/test_discovery.py` | Create | Parser and browser tests |
| `python/tests/operations/test_tiktok_discovery_fixture.py` | Create | Sanitizer and golden tests |
| `python/tests/fixtures/tiktok/discovery/{profile,search,explore}.json` | Create | Sanitized golden pages |
| `CHANGELOG.md`, `docs/python-scout-migration-roadmap.md` | Modify | Record the sub-stage |

Throwaway files, never committed: `D:/thoth-tmp/bu/extract_targets.py`, `capture_discovery.py`,
`capture_discovery.sh`, `sanitize_discovery.sh`, `edit_roadmap_discovery.py`,
`edit_changelog_discovery.py`, and `D:/thoth-tmp/bu/out/discovery_targets.json`.

## Rulings recorded while planning

Each ruling narrows or fills the spec and is carried by the task that owns it.

1. **Per-kind capture pattern.** `capture_xhr` uses one pattern per kind (`XHR_PATTERNS`), a
   stricter subset of the spec's single regex. Each session then holds only its own kind's
   bodies.
2. **Fetch errors.** A fetch exception whose type name contains `timeout` maps to `timeout`.
   Every other fetch exception maps to `browser_unavailable`, the spec's nearest reason for a
   browser that did not deliver.
3. **String epochs.** `published_at_from_epoch` also accepts an ASCII decimal string, because the
   single-post rehydration script carries `createTime` as a string.
4. **Count size cap.** Decimal count strings are capped at 19 digits. A longer string is skipped,
   never truncated.
5. **Long hashtags.** A hashtag longer than 100 characters is dropped from the list; the video is
   kept. The spec only says "non-empty strings", and the model caps each at 100.
6. **Failed in-page reads.** A failed in-page `response.body()` read counts as an empty body. That
   stops scrolling early. The authoritative parse from `captured_xhr` is unaffected.
7. **Checks live in the tool.** The leak check and the replay check live inside the fixture
   tool, not in a throwaway script. A leak or a replay mismatch refuses to write.
8. **Golden test location.** Golden tests live in `tests/operations`, next to the tool that
   produces the fixtures.
9. **Unparseable fixture pages.** A fixture page is a JSON object, or `null` for a page that was
   not a JSON object (it replays as an empty body).
10. **Warm-up fetch.** The keyword warm-up fetch passes no `page_setup` or `page_action`, and its
    response is discarded.
11. **Kind type.** `DiscoveryKind` is a `Literal`, as in the spec, not an enum.
12. **Capture targets.** The capture targets are the public official handle and generic keyword
    used by the operator-authorized feasibility probe (`D:/thoth-tmp/bu/disc9.py`). They are
    copied without being printed.

---

### Task 1: Discovery contracts

**Files:**
- Modify: `python/src/thoth_control_plane/acquisition/models.py` (docstring line 1, imports lines
  3-11, append at the end of the file)
- Test: `python/tests/acquisition/test_models.py`

**Interfaces:**
- Consumes: `TikTokNumericId`, `TikTokHandle`, `StrictModel` (existing).
- Produces, all in `thoth_control_plane.acquisition.models`:
  - `EngagementKey = Literal["play", "like", "comment", "share", "collect"]`;
  - `DiscoveryKind = Literal["profile", "keyword", "trending"]`;
  - `DiscoveryReason` (StrEnum: `CAPTCHA`, `BLOCKED`, `NO_DATA`, `TIMEOUT`,
    `BROWSER_UNAVAILABLE`);
  - `ProfileDiscovery(handle, limit=30)`, `KeywordDiscovery(query, limit=30)`,
    `TrendingDiscovery(limit=30)`;
  - `DiscoveryRequest`, the discriminated union of the three request models;
  - `DiscoveredVideo(post_id, owner_handle, canonical_url, caption="", published_at=None,
    duration_seconds=None, engagement={}, hashtags=[])`;
  - `DiscoveryDrops(ads=0, photo_posts=0, invalid=0)`;
  - `DiscoveryResult(kind, videos, pages, exhausted, drops, reason=None)`.

- [ ] **Step 0: Create the branch**

```bash
git checkout master && git checkout -b feat/tiktok-discovery-primitives
```

Expected: `Switched to a new branch 'feat/tiktok-discovery-primitives'`.

- [ ] **Step 1: Write the failing tests**

In `python/tests/acquisition/test_models.py`:
- change `from pydantic import SecretStr, ValidationError` to
  `from pydantic import SecretStr, TypeAdapter, ValidationError`;
- add `DiscoveredVideo`, `DiscoveryDrops`, `DiscoveryReason`, `DiscoveryRequest`,
  `DiscoveryResult`, `KeywordDiscovery`, `ProfileDiscovery`, and `TrendingDiscovery` to the
  existing `from thoth_control_plane.acquisition.models import (...)` block, keeping it sorted.

Then append:

```python
DISCOVERY_REQUEST = TypeAdapter(DiscoveryRequest)
VIDEO_URL = "https://www.tiktok.com/@creator/video/1000000001"


def test_discovery_request_is_discriminated_by_kind() -> None:
    profile = DISCOVERY_REQUEST.validate_python({"kind": "profile", "handle": "creator"})
    keyword = DISCOVERY_REQUEST.validate_python({"kind": "keyword", "query": "  cats  "})
    trending = DISCOVERY_REQUEST.validate_python({"kind": "trending", "limit": 5})

    assert isinstance(profile, ProfileDiscovery) and profile.limit == 30
    assert isinstance(keyword, KeywordDiscovery) and keyword.query == "cats"
    assert isinstance(trending, TrendingDiscovery) and trending.limit == 5
    with pytest.raises(ValidationError):
        DISCOVERY_REQUEST.validate_python({"kind": "hashtag"})


@pytest.mark.parametrize("query", ["", "   ", "cats\ndogs", "tab\there", "x" * 101])
def test_keyword_query_rejects_blank_control_and_oversized_text(query: str) -> None:
    with pytest.raises(ValidationError):
        KeywordDiscovery(query=query)


def test_keyword_query_keeps_punctuation_and_emoji() -> None:
    query = "anak & kucing/2 \U0001f63a"
    assert KeywordDiscovery(query=query).query == query


@pytest.mark.parametrize("limit", [0, 101])
def test_discovery_limit_is_bounded(limit: int) -> None:
    with pytest.raises(ValidationError):
        TrendingDiscovery(limit=limit)


@pytest.mark.parametrize("handle", ["", "bad handle", "a/b", "x" * 65])
def test_profile_discovery_rejects_invalid_handles(handle: str) -> None:
    with pytest.raises(ValidationError):
        ProfileDiscovery(handle=handle)


def test_discovered_video_rejects_unknown_engagement_keys() -> None:
    with pytest.raises(ValidationError):
        DiscoveredVideo(
            post_id="1000000001",
            owner_handle="creator",
            canonical_url=VIDEO_URL,
            engagement={"views": 1},
        )


@pytest.mark.parametrize("hashtag", ["", "x" * 101])
def test_discovered_video_rejects_empty_or_oversized_hashtags(hashtag: str) -> None:
    with pytest.raises(ValidationError):
        DiscoveredVideo(
            post_id="1000000001",
            owner_handle="creator",
            canonical_url=VIDEO_URL,
            hashtags=[hashtag],
        )


def test_partial_discovery_result_round_trips_through_json() -> None:
    video = DiscoveredVideo(
        post_id="1000000001",
        owner_handle="creator",
        canonical_url=VIDEO_URL,
        published_at="2024-03-01T10:00:00Z",
        duration_seconds=15.0,
        engagement={"play": 1, "like": 2},
        hashtags=["cats"],
    )
    result = DiscoveryResult(
        kind="keyword",
        videos=[video],
        pages=1,
        exhausted=False,
        drops=DiscoveryDrops(ads=1),
        reason=DiscoveryReason.CAPTCHA,
    )

    dumped = result.model_dump_json()

    assert json.loads(dumped)["reason"] == "captcha"
    assert DiscoveryResult.model_validate_json(dumped) == result
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_models.py 2>&1 | tail -5`
Expected: collection error, `ImportError: cannot import name 'DiscoveredVideo'`.

- [ ] **Step 3: Implement the contracts**

In `models.py`, replace line 1 with:

```python
"""Strict, serializable contracts for TikTok acquisition: single-post and discovery."""
```

Add `import unicodedata` after `from __future__ import annotations`, so the stdlib imports read:

```python
from __future__ import annotations

import unicodedata
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal
```

Append at the end of the file:

```python
EngagementKey = Literal["play", "like", "comment", "share", "collect"]
DiscoveryKind = Literal["profile", "keyword", "trending"]
DiscoveryLimit = Annotated[int, Field(ge=1, le=100)]


def _search_query(value: str) -> str:
    value = value.strip()
    if not value or any(unicodedata.category(char) == "Cc" for char in value):
        raise ValueError("search query must be non-blank text without control characters")
    return value


SearchQuery = Annotated[str, Field(min_length=1, max_length=100), AfterValidator(_search_query)]


class DiscoveryReason(StrEnum):
    CAPTCHA = "captcha"  # empty/non-JSON API body or captcha container rendered
    BLOCKED = "blocked"  # API JSON with a non-zero status code
    NO_DATA = "no_data"  # no matching API response was captured
    TIMEOUT = "timeout"  # navigation or the scroll deadline expired
    BROWSER_UNAVAILABLE = "browser_unavailable"  # the Scrapling stack could not start


class ProfileDiscovery(StrictModel):
    kind: Literal["profile"] = "profile"
    handle: TikTokHandle
    limit: DiscoveryLimit = 30


class KeywordDiscovery(StrictModel):
    kind: Literal["keyword"] = "keyword"
    query: SearchQuery
    limit: DiscoveryLimit = 30


class TrendingDiscovery(StrictModel):
    kind: Literal["trending"] = "trending"
    limit: DiscoveryLimit = 30


DiscoveryRequest = Annotated[
    ProfileDiscovery | KeywordDiscovery | TrendingDiscovery, Field(discriminator="kind")
]


class DiscoveredVideo(StrictModel):
    post_id: TikTokNumericId
    owner_handle: TikTokHandle
    canonical_url: HttpUrl  # rebuilt from handle and id, never taken from TikTok
    caption: Annotated[str, Field(max_length=10_000)] = ""
    published_at: str | None = None  # ISO 8601 UTC, "YYYY-MM-DDTHH:MM:SSZ"
    duration_seconds: Annotated[float, Field(ge=0)] | None = None
    engagement: dict[EngagementKey, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    hashtags: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list
    )


class DiscoveryDrops(StrictModel):
    ads: int = 0
    photo_posts: int = 0
    invalid: int = 0  # missing/invalid id or handle, or a failed model validation


class DiscoveryResult(StrictModel):
    """A result with `reason` set and non-empty `videos` is a valid partial result."""

    kind: DiscoveryKind
    videos: list[DiscoveredVideo]  # deduplicated by post_id, first seen wins, at most limit
    pages: Annotated[int, Field(ge=0)]
    exhausted: bool  # the last captured page reported no more results
    drops: DiscoveryDrops
    reason: DiscoveryReason | None = None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_models.py 2>&1 | tail -5`
Expected: all passed, 0 failed.

- [ ] **Step 5: Run ruff**

Run the ruff command from Global Constraints. Expected: `RC=0`.

- [ ] **Step 6: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/models.py python/tests/acquisition/test_models.py
git commit -m "feat: add tiktok discovery contracts"
```

---

### Task 2: Engagement and publication-time normalizer

**Files:**
- Create: `python/src/thoth_control_plane/acquisition/normalize.py`
- Test: `python/tests/acquisition/test_normalize.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces, in `thoth_control_plane.acquisition.normalize`:
  - `normalize_engagement(stats: object, stats_v2: object) -> dict[str, int]`, with keys drawn
    from `play`, `like`, `comment`, `share`, and `collect`;
  - `published_at_from_epoch(value: object) -> str | None`, returning `YYYY-MM-DDTHH:MM:SSZ`.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/acquisition/test_normalize.py`:

```python
import pytest

from thoth_control_plane.acquisition.normalize import (
    normalize_engagement,
    published_at_from_epoch,
)

STATS = {"playCount": 10, "diggCount": 5, "commentCount": 2, "shareCount": 1, "collectCount": 3}


def test_stats_v2_wins_per_key_and_stats_fills_the_rest() -> None:
    stats_v2 = {"playCount": "12345678901234567", "diggCount": "-1"}

    assert normalize_engagement(STATS, stats_v2) == {
        "play": 12345678901234567,
        "like": 5,
        "comment": 2,
        "share": 1,
        "collect": 3,
    }


def test_tikwm_snake_case_counters_are_recognized() -> None:
    data = {
        "play_count": 7,
        "digg_count": 6,
        "comment_count": 5,
        "share_count": 4,
        "collect_count": 3,
    }

    assert normalize_engagement(data, None) == {
        "play": 7,
        "like": 6,
        "comment": 5,
        "share": 4,
        "collect": 3,
    }


@pytest.mark.parametrize(
    "value",
    [True, False, -1, 1.5, "-3", "1e3", " 12", "\u0661\u0662", "9" * 20, "", None, [1], {"n": 1}],
)
def test_invalid_counts_are_skipped_never_guessed(value: object) -> None:
    assert normalize_engagement({"playCount": value}, {"playCount": value}) == {}


@pytest.mark.parametrize("stats", [None, [], "10", 5])
def test_non_mapping_stats_yield_nothing(stats: object) -> None:
    assert normalize_engagement(stats, stats) == {}


@pytest.mark.parametrize("value", [1709287200, "1709287200"])
def test_epoch_seconds_become_iso_utc(value: object) -> None:
    assert published_at_from_epoch(value) == "2024-03-01T10:00:00Z"


@pytest.mark.parametrize(
    "value", [0, -5, True, 1709287200.5, "2024-03-01", "", None, 10**20, "9" * 30, 10**400]
)
def test_invalid_epochs_are_none(value: object) -> None:
    assert published_at_from_epoch(value) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_normalize.py 2>&1 | tail -5`
Expected: collection error, `ModuleNotFoundError: No module named 'thoth_control_plane.acquisition.normalize'`.

- [ ] **Step 3: Implement the normalizer**

Create `python/src/thoth_control_plane/acquisition/normalize.py`:

```python
"""Pure engagement and publication-time normalization shared by TikTok adapters.

A value that is not what it claims to be is skipped, never guessed. A count must be a
non-negative integer or an ASCII decimal string of one. A publication time must be a positive
integer epoch in seconds, or an ASCII decimal string of one.
"""

from __future__ import annotations

from datetime import UTC, datetime

# Engagement key -> accepted source names: camelCase from TikTok's web API, snake_case from TikWM.
ENGAGEMENT_KEYS: dict[str, tuple[str, ...]] = {
    "play": ("playCount", "play_count"),
    "like": ("diggCount", "digg_count"),
    "comment": ("commentCount", "comment_count"),
    "share": ("shareCount", "share_count"),
    "collect": ("collectCount", "collect_count"),
}
MAX_COUNT_DIGITS = 19


def _decimal(value: str) -> int | None:
    if value.isascii() and value.isdecimal() and len(value) <= MAX_COUNT_DIGITS:
        return int(value)
    return None


def _count(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str):
        return _decimal(value)
    return None


def _pick(source: object, names: tuple[str, ...]) -> int | None:
    if not isinstance(source, dict):
        return None
    for name in names:
        count = _count(source.get(name))
        if count is not None:
            return count
    return None


def normalize_engagement(stats: object, stats_v2: object) -> dict[str, int]:
    """Map TikTok counters to engagement keys, preferring the precise `statsV2` per key."""
    engagement: dict[str, int] = {}
    for key, names in ENGAGEMENT_KEYS.items():
        count = _pick(stats_v2, names)
        if count is None:
            count = _pick(stats, names)
        if count is not None:
            engagement[key] = count
    return engagement


def published_at_from_epoch(value: object) -> str | None:
    """Return a positive epoch-seconds value as `YYYY-MM-DDTHH:MM:SSZ`, else `None`."""
    if isinstance(value, str):
        value = _decimal(value)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_normalize.py 2>&1 | tail -5`
Expected: all passed, 0 failed.

- [ ] **Step 5: Run ruff**

Run the ruff command from Global Constraints. Expected: `RC=0`.

- [ ] **Step 6: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/normalize.py python/tests/acquisition/test_normalize.py
git commit -m "feat: add engagement and publication-time normalizer"
```

---

### Task 3: Fill single-post engagement and publication time (item 7)

**Files:**
- Modify: `python/src/thoth_control_plane/acquisition/browser.py`
  - imports: after the `acquisition.models` import block, around line 185;
  - `extract_browser_snapshot`: docstring around line 393, body lines 400-428.
- Modify: `python/src/thoth_control_plane/acquisition/adapters/tikwm.py`
  - imports;
  - `parse_tikwm_payload`: the `TikTokPost(...)` call around line 112.
- Modify: `python/src/thoth_control_plane/acquisition/service.py` (`_merge_post`, lines 94-115)
- Test: `python/tests/acquisition/test_browser.py`, `python/tests/acquisition/test_service.py`,
  `python/tests/acquisition/test_models.py`

**Interfaces:**
- Consumes: `normalize_engagement` and `published_at_from_epoch` from Task 2.
- Produces: `TikTokPost.published_at` and `TikTokPost.engagement` filled on the headless,
  TikWM, and merged paths. No signature changes.

- [ ] **Step 1: Write the failing tests**

Append to `python/tests/acquisition/test_browser.py`:

```python
def _embedded(item: dict) -> dict:
    return {"__DEFAULT_SCOPE__": {"webapp.video-detail": {"itemInfo": {"itemStruct": item}}}}


def test_item_struct_fills_publication_time_and_engagement() -> None:
    # The rehydration script carries createTime as a decimal string.
    item = {
        **_item_struct(),
        "createTime": "1709287200",
        "stats": {"playCount": 5, "diggCount": 2},
        "statsV2": {"playCount": "7"},
    }
    snapshot = extract_browser_snapshot(
        final_url=POST_URL,
        og_title=None,
        author=None,
        video_sources=[],
        captured_xhr=[],
        embedded_data=_embedded(item),
    )

    post = snapshot.post_candidates[0]
    assert post.published_at == "2024-03-01T10:00:00Z"
    assert post.engagement == {"play": 7, "like": 2}


def test_item_struct_without_counters_leaves_them_empty() -> None:
    snapshot = extract_browser_snapshot(
        final_url=POST_URL,
        og_title=None,
        author=None,
        video_sources=[],
        captured_xhr=[],
        embedded_data=_embedded(_item_struct()),
    )

    post = snapshot.post_candidates[0]
    assert post.published_at is None
    assert post.engagement == {}
```

In `python/tests/acquisition/test_service.py`, change
`from thoth_control_plane.acquisition.service import TikTokAcquisitionService` to
`from thoth_control_plane.acquisition.service import TikTokAcquisitionService, _merge_post`.
Then append:

```python
def test_parse_tikwm_payload_fills_publication_time_and_engagement() -> None:
    payload = _valid_tikwm_payload(
        create_time=1709287200,
        play_count=9,
        digg_count=8,
        comment_count=7,
        share_count=6,
        collect_count=5,
    )

    post = parse_tikwm_payload(payload).post

    assert post.published_at == "2024-03-01T10:00:00Z"
    assert post.engagement == {"play": 9, "like": 8, "comment": 7, "share": 6, "collect": 5}


def test_parse_tikwm_payload_without_counters_leaves_them_empty() -> None:
    post = parse_tikwm_payload(_valid_tikwm_payload()).post

    assert post.published_at is None
    assert post.engagement == {}


def test_parse_tikwm_payload_skips_malformed_counters_without_failing() -> None:
    payload = _valid_tikwm_payload(create_time="soon", play_count=-1, digg_count=4)

    post = parse_tikwm_payload(payload).post

    assert post.published_at is None
    assert post.engagement == {"like": 4}


def _post(published_at: str | None = None, engagement: dict[str, int] | None = None) -> TikTokPost:
    return TikTokPost(
        post_id="1234567890",
        owner_handle="creator",
        published_at=published_at,
        engagement=engagement or {},
    )


HEADLESS_TIME = "2024-03-01T10:00:00Z"
PROVIDER_TIME = "2024-02-01T00:00:00Z"


@pytest.mark.parametrize(
    ("headless", "provider", "published_at", "engagement"),
    [
        (_post(HEADLESS_TIME, {"play": 7}), _post(PROVIDER_TIME, {"like": 3}), HEADLESS_TIME, {"play": 7}),
        (_post(), _post(PROVIDER_TIME, {"like": 3}), PROVIDER_TIME, {"like": 3}),
        (_post(HEADLESS_TIME), _post(PROVIDER_TIME, {"like": 3}), HEADLESS_TIME, {"like": 3}),
        (None, _post(PROVIDER_TIME, {"like": 3}), PROVIDER_TIME, {"like": 3}),
        (_post(HEADLESS_TIME, {"play": 7}), None, HEADLESS_TIME, {"play": 7}),
        (_post(), _post(), None, {}),
    ],
)
def test_merge_post_fills_each_field_from_headless_first(
    headless: TikTokPost | None,
    provider: TikTokPost | None,
    published_at: str | None,
    engagement: dict[str, int],
) -> None:
    post = _merge_post(None, headless, provider)

    assert post.published_at == published_at
    assert post.engagement == engagement
```

Append to `python/tests/acquisition/test_models.py`:

```python
@pytest.mark.parametrize("schema_version", [1, 2])
def test_reports_carry_publication_time_and_engagement(schema_version: int) -> None:
    payload = _fixture_report().model_dump(mode="json")
    payload["schema_version"] = schema_version
    payload["post"].update(published_at="2024-03-01T10:00:00Z", engagement={"play": 7, "like": 2})

    report = TikTokSourceReport.model_validate_json(json.dumps(payload))

    assert report.post.published_at == "2024-03-01T10:00:00Z"
    assert report.post.engagement == {"play": 7, "like": 2}
```

- [ ] **Step 2: Run the tests to verify the new behavior fails**

Run: `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_browser.py tests/acquisition/test_service.py tests/acquisition/test_models.py 2>&1 | tail -8`

Expected failures:
- `test_item_struct_fills_publication_time_and_engagement`;
- `test_parse_tikwm_payload_fills_publication_time_and_engagement`;
- `test_parse_tikwm_payload_skips_malformed_counters_without_failing`, because engagement is `{}`;
- the `_merge_post` cases that expect a non-empty value.

Expected passes, because these tests pin behavior that already holds:
- the two "leaves them empty" tests;
- the `(_post(), _post(), None, {})` merge case;
- both `test_reports_carry_publication_time_and_engagement` cases.

- [ ] **Step 3: Implement**

In `browser.py`, add after the `from thoth_control_plane.acquisition.models import (...)` block:

```python
from thoth_control_plane.acquisition.normalize import normalize_engagement, published_at_from_epoch
```

In the `extract_browser_snapshot` docstring, replace:

```python
    candidate is accepted. Raw XHR bodies are inspected only long enough to
    pull out `id`/`desc`/`author.uniqueId`; nothing raw is retained.
```

with:

```python
    candidate is accepted. Raw XHR bodies are inspected only long enough to
    pull out `id`/`desc`/`author.uniqueId`, `createTime`, and the `stats`/`statsV2`
    counters; nothing raw is retained.
```

Replace the item-struct block:

```python
    item_struct = _item_struct(captured_xhr, embedded_data, identity.post_id)
    caption = ""
    xhr_unique_id: str | None = None
    if item_struct is not None:
        xhr_desc = item_struct.get("desc")
```

with:

```python
    item_struct = _item_struct(captured_xhr, embedded_data, identity.post_id)
    caption = ""
    published_at: str | None = None
    engagement: dict[str, int] = {}
    xhr_unique_id: str | None = None
    if item_struct is not None:
        published_at = published_at_from_epoch(item_struct.get("createTime"))
        engagement = normalize_engagement(item_struct.get("stats"), item_struct.get("statsV2"))
        xhr_desc = item_struct.get("desc")
```

Replace the post candidate:

```python
            TikTokPost(
                post_id=identity.post_id,
                owner_handle=identity.owner_handle,
                caption=caption[:10_000],
            )
```

with:

```python
            TikTokPost(
                post_id=identity.post_id,
                owner_handle=identity.owner_handle,
                caption=caption[:10_000],
                published_at=published_at,
                engagement=engagement,
            )
```

In `adapters/tikwm.py`, add after the existing `thoth_control_plane` imports:

```python
from thoth_control_plane.acquisition.normalize import normalize_engagement, published_at_from_epoch
```

Replace:

```python
            post=TikTokPost(post_id=str(post_id), owner_handle=unique_id, caption=caption[:10_000]),
```

with:

```python
            post=TikTokPost(
                post_id=str(post_id),
                owner_handle=unique_id,
                caption=caption[:10_000],
                # TikWM field names are an assumption (spec 4.4); absent fields stay empty.
                published_at=published_at_from_epoch(data.get("create_time")),
                engagement=normalize_engagement(data, None),
            ),
```

In `service.py`, replace the whole `_merge_post` function with:

```python
def _merge_post(
    identity: TikTokPostIdentity | None,
    headless_post: TikTokPost | None,
    provider_post: TikTokPost | None,
) -> TikTokPost:
    """Prefer a valid headless caption over a provider caption, while
    canonical URL identity (if derivable) wins all post-id/handle conflicts.
    `published_at` and `engagement` merge per field, headless first.
    """
    caption = ""
    if headless_post is not None and headless_post.caption:
        caption = headless_post.caption
    elif provider_post is not None:
        caption = provider_post.caption

    published_at: str | None = None
    engagement: dict[str, int] = {}
    for post in (headless_post, provider_post):
        if post is not None:
            published_at = published_at or post.published_at
            engagement = engagement or post.engagement

    identity_source = identity or headless_post or provider_post
    if identity_source is None:
        raise AssertionError("post identity must be derivable from at least one source")
    return TikTokPost(
        post_id=identity_source.post_id,
        owner_handle=identity_source.owner_handle,
        caption=caption,
        published_at=published_at,
        engagement=engagement,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition 2>&1 | tail -5`
Expected: all passed, 0 failed.

- [ ] **Step 5: Run ruff**

Run the ruff command from Global Constraints. Expected: `RC=0`. `ruff format` may re-wrap the
long parametrize rows in `test_service.py`; that is fine.

- [ ] **Step 6: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/browser.py python/src/thoth_control_plane/acquisition/adapters/tikwm.py python/src/thoth_control_plane/acquisition/service.py python/tests/acquisition/test_browser.py python/tests/acquisition/test_service.py python/tests/acquisition/test_models.py
git commit -m "feat: fill single-post engagement and publication time"
```

---

### Task 4: Discovery page parser

**Files:**
- Create: `python/src/thoth_control_plane/acquisition/discovery.py`
- Test: `python/tests/acquisition/test_discovery.py`

**Interfaces:**
- Consumes:
  - Task 1: `DiscoveredVideo`, `DiscoveryDrops`, `DiscoveryKind`, `DiscoveryReason`;
  - Task 2: `normalize_engagement`, `published_at_from_epoch`.
- Produces, in `thoth_control_plane.acquisition.discovery`:
  - `DiscoveryPage`, a frozen dataclass with `videos: list[DiscoveredVideo]`,
    `has_more: bool`, `drops: DiscoveryDrops`, and `reason: DiscoveryReason | None = None`;
  - `parse_discovery_page(kind: DiscoveryKind, body: bytes) -> DiscoveryPage`;
  - the constants `MAX_CAPTION = 10_000` and `MAX_HASHTAG = 100`.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/acquisition/test_discovery.py`:

```python
import json

import pytest

from thoth_control_plane.acquisition.discovery import parse_discovery_page
from thoth_control_plane.acquisition.models import DiscoveryDrops, DiscoveryReason


def _item(post_id: object = "1000000001", handle: str = "creator", **extra: object) -> dict:
    item = {
        "id": post_id,
        "desc": "a caption #cats",
        "createTime": 1709287200,
        "author": {"uniqueId": handle, "secUid": "MS4wLjABAAAA", "verified": False},
        "stats": {
            "playCount": 10,
            "diggCount": 5,
            "commentCount": 2,
            "shareCount": 1,
            "collectCount": 3,
        },
        "video": {"duration": 15},
        "challenges": [{"title": "cats"}],
    }
    item.update(extra)
    return item


def _list_body(items: list, has_more: object = True) -> bytes:
    return json.dumps({"statusCode": 0, "itemList": items, "hasMore": has_more}).encode()


def _search_body(entries: list, has_more: object = 1) -> bytes:
    return json.dumps({"status_code": 0, "data": entries, "has_more": has_more}).encode()


@pytest.mark.parametrize("kind", ["profile", "trending"])
def test_list_pages_reduce_to_validated_videos(kind: str) -> None:
    page = parse_discovery_page(kind, _list_body([_item()]))

    assert page.reason is None
    assert page.has_more is True
    assert page.drops == DiscoveryDrops()
    [video] = page.videos
    assert video.post_id == "1000000001"
    assert video.owner_handle == "creator"
    assert str(video.canonical_url) == "https://www.tiktok.com/@creator/video/1000000001"
    assert video.caption == "a caption #cats"
    assert video.published_at == "2024-03-01T10:00:00Z"
    assert video.duration_seconds == 15.0
    assert video.engagement == {"play": 10, "like": 5, "comment": 2, "share": 1, "collect": 3}
    assert video.hashtags == ["cats"]


def test_search_pages_keep_only_video_entries() -> None:
    body = _search_body(
        [
            {"type": 1, "item": _item("1000000001"), "common": {}},
            {"type": 4, "user_list": [{"uniqueId": "someone"}]},
            {"type": 1, "item": _item("1000000002"), "common": {}},
        ]
    )

    page = parse_discovery_page("keyword", body)

    assert [video.post_id for video in page.videos] == ["1000000001", "1000000002"]
    assert page.drops == DiscoveryDrops()
    assert page.has_more is True


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, True), (1, True), (False, False), (0, False), (None, False), ("true", False)],
)
def test_has_more_is_true_only_for_true_or_one(value: object, expected: bool) -> None:
    assert parse_discovery_page("profile", _list_body([_item()], has_more=value)).has_more is expected


def test_ads_photo_posts_and_invalid_items_are_dropped_and_counted() -> None:
    items = [
        _item("1000000001"),
        _item("1000000002", isAd=True),
        _item("1000000003", imagePost={"images": []}),
        _item(1000000004),
        _item("12"),
        _item("1000000006", author={}),
        "junk",
    ]

    page = parse_discovery_page("profile", _list_body(items))

    assert [video.post_id for video in page.videos] == ["1000000001"]
    assert page.drops == DiscoveryDrops(ads=1, photo_posts=1, invalid=4)


def test_an_ad_that_is_also_a_photo_post_counts_as_an_ad() -> None:
    page = parse_discovery_page("profile", _list_body([_item(isAd=True, imagePost={})]))

    assert page.drops == DiscoveryDrops(ads=1)


@pytest.mark.parametrize("body", [b"", b"<html></html>", b"[]", b"\xff\xfe"])
def test_empty_or_non_object_bodies_are_captcha(body: bytes) -> None:
    page = parse_discovery_page("keyword", body)

    assert page.reason is DiscoveryReason.CAPTCHA
    assert page.videos == []
    assert page.has_more is False


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("profile", {"statusCode": 10201, "itemList": [_item()], "hasMore": True}),
        ("keyword", {"status_code": 5, "data": [], "has_more": 1}),
    ],
)
def test_non_zero_status_is_blocked(kind: str, payload: dict) -> None:
    page = parse_discovery_page(kind, json.dumps(payload).encode())

    assert page.reason is DiscoveryReason.BLOCKED
    assert page.videos == []


def test_canonical_url_is_rebuilt_never_taken_from_tiktok() -> None:
    item = _item(shareUrl="https://evil.example/@creator/video/1000000001")

    [video] = parse_discovery_page("profile", _list_body([item])).videos

    assert str(video.canonical_url) == "https://www.tiktok.com/@creator/video/1000000001"


def test_caption_is_truncated_and_a_non_string_desc_is_empty() -> None:
    items = [_item("1000000001", desc="x" * 10_050), _item("1000000002", desc=None)]

    long_caption, no_caption = parse_discovery_page("profile", _list_body(items)).videos

    assert len(long_caption.caption) == 10_000
    assert no_caption.caption == ""


@pytest.mark.parametrize("duration", [True, -1, float("nan"), float("inf"), "15"])
def test_invalid_duration_is_none_and_the_video_is_kept(duration: object) -> None:
    [video] = parse_discovery_page(
        "profile", _list_body([_item(video={"duration": duration})])
    ).videos

    assert video.duration_seconds is None


def test_bad_hashtags_are_dropped_and_the_video_is_kept() -> None:
    challenges = [{"title": ""}, {"title": "x" * 101}, {"title": 5}, "junk", {"title": "ok"}]

    [video] = parse_discovery_page("profile", _list_body([_item(challenges=challenges)])).videos

    assert video.hashtags == ["ok"]


def test_missing_stats_yield_empty_engagement() -> None:
    item = _item()
    del item["stats"]

    [video] = parse_discovery_page("trending", _list_body([item])).videos

    assert video.engagement == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_discovery.py 2>&1 | tail -5`
Expected: collection error, `ModuleNotFoundError: No module named 'thoth_control_plane.acquisition.discovery'`.

- [ ] **Step 3: Implement the parser**

Create `python/src/thoth_control_plane/acquisition/discovery.py`:

```python
"""Headless TikTok discovery: profile, keyword, and trending video lists.

TikTok signs its list APIs inside the page, so this module never builds an API request. It
opens the ordinary page in a stealthy headless session, scrolls it, and reads the list
responses the page itself makes. A captcha is avoided, never solved or blocked: when TikTok
refuses, the result is returned partial with a typed reason.

This is the sole boundary where raw list payloads are inspected. Only validated
`DiscoveredVideo` records and drop counts cross back out; nothing raw is retained or logged.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from thoth_control_plane.acquisition.models import (
    DiscoveredVideo,
    DiscoveryDrops,
    DiscoveryKind,
    DiscoveryReason,
)
from thoth_control_plane.acquisition.normalize import normalize_engagement, published_at_from_epoch

MAX_CAPTION = 10_000
MAX_HASHTAG = 100


@dataclass(frozen=True, slots=True)
class DiscoveryPage:
    """One parsed list response; internal, not a contract."""

    videos: list[DiscoveredVideo]
    has_more: bool
    drops: DiscoveryDrops
    reason: DiscoveryReason | None = None


def parse_discovery_page(kind: DiscoveryKind, body: bytes) -> DiscoveryPage:
    """Reduce one raw list response body to validated videos and drop counts.

    A body that is not a JSON object is what TikTok serves a refused request, so it maps to
    `captcha`. A non-zero status code maps to `blocked`.
    """
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        payload = None
    if not isinstance(payload, dict):
        return DiscoveryPage([], False, DiscoveryDrops(), DiscoveryReason.CAPTCHA)
    status = payload.get("statusCode", payload.get("status_code"))
    if status not in (None, 0):
        return DiscoveryPage([], False, DiscoveryDrops(), DiscoveryReason.BLOCKED)

    videos: list[DiscoveredVideo] = []
    ads = photo_posts = invalid = 0
    for item in _items(kind, payload):
        if not isinstance(item, dict):
            invalid += 1
        elif item.get("isAd") is True:
            ads += 1
        elif item.get("imagePost") is not None:
            photo_posts += 1
        elif (video := _video(item)) is not None:
            videos.append(video)
        else:
            invalid += 1
    has_more = payload.get("hasMore", payload.get("has_more")) in (True, 1)
    drops = DiscoveryDrops(ads=ads, photo_posts=photo_posts, invalid=invalid)
    return DiscoveryPage(videos, has_more, drops)


def _items(kind: DiscoveryKind, payload: dict[str, Any]) -> list[Any]:
    if kind == "keyword":
        data = payload.get("data")
        if not isinstance(data, list):
            return []
        # Search mixes users and other cards into `data`; only type 1 entries are videos.
        return [e.get("item") for e in data if isinstance(e, dict) and e.get("type") == 1]
    items = payload.get("itemList")
    return items if isinstance(items, list) else []


def _video(item: dict[str, Any]) -> DiscoveredVideo | None:
    post_id = item.get("id")
    author = item.get("author")
    handle = author.get("uniqueId") if isinstance(author, dict) else None
    if not isinstance(post_id, str) or not isinstance(handle, str):
        return None
    desc = item.get("desc")
    video = item.get("video")
    try:
        return DiscoveredVideo(
            post_id=post_id,
            owner_handle=handle,
            canonical_url=f"https://www.tiktok.com/@{handle}/video/{post_id}",
            caption=desc[:MAX_CAPTION] if isinstance(desc, str) else "",
            published_at=published_at_from_epoch(item.get("createTime")),
            duration_seconds=_duration(video.get("duration") if isinstance(video, dict) else None),
            engagement=normalize_engagement(item.get("stats"), item.get("statsV2")),
            hashtags=_hashtags(item.get("challenges")),
        )
    except ValidationError:
        return None


def _duration(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        seconds = float(value)
    except OverflowError:
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _hashtags(challenges: object) -> list[str]:
    if not isinstance(challenges, list):
        return []
    titles = (challenge.get("title") for challenge in challenges if isinstance(challenge, dict))
    return [title for title in titles if isinstance(title, str) and 1 <= len(title) <= MAX_HASHTAG]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_discovery.py 2>&1 | tail -5`
Expected: all passed, 0 failed.

- [ ] **Step 5: Run ruff**

Run the ruff command from Global Constraints. Expected: `RC=0`.

- [ ] **Step 6: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/discovery.py python/tests/acquisition/test_discovery.py
git commit -m "feat: parse tiktok discovery list pages"
```

---

### Task 5: Headless discovery browser

**Files:**
- Modify: `python/src/thoth_control_plane/acquisition/discovery.py` (replace the import block,
  add constants, append the scroll and browser code)
- Test: `python/tests/acquisition/test_discovery.py` (replace the import block, append)

**Interfaces:**
- Consumes:
  - Task 4: `parse_discovery_page`, `DiscoveryPage`;
  - Task 1: `DiscoveryRequest`, `DiscoveryResult`, `KeywordDiscovery`, `ProfileDiscovery`;
  - from `browser.py`: `FETCH_TIMEOUT_MS`, `FETCH_WAIT_MS`, `_default_session_factory`,
    `_increment_active_sessions`, `_decrement_active_sessions`.
- Produces, in `thoth_control_plane.acquisition.discovery`:
  - `class ScraplingDiscoveryBrowser(session_factory=_default_session_factory)`, with
    `async discover(request: DiscoveryRequest) -> DiscoveryResult`;
  - `_assemble(kind, limit, bodies: list[bytes], *, captcha: bool, timed_out: bool) ->
    DiscoveryResult`, which Task 7's golden tests reuse;
  - the constants `XHR_PATTERNS`, `EXPLORE_URL`, `CAPTCHA_SELECTOR`, `MAX_SCROLLS`,
    `SCROLL_DEADLINE_S`, and the others below.

- [ ] **Step 1: Write the failing tests**

In `python/tests/acquisition/test_discovery.py`, replace the import block with:

```python
import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from thoth_control_plane.acquisition import discovery as discovery_module
from thoth_control_plane.acquisition.browser import (
    FETCH_TIMEOUT_MS,
    FETCH_WAIT_MS,
    active_scrapling_session_count,
)
from thoth_control_plane.acquisition.discovery import (
    CAPTCHA_SELECTOR,
    EXPLORE_URL,
    XHR_PATTERNS,
    ScraplingDiscoveryBrowser,
    _assemble,
    parse_discovery_page,
)
from thoth_control_plane.acquisition.models import (
    DiscoveryDrops,
    DiscoveryReason,
    KeywordDiscovery,
    ProfileDiscovery,
    TrendingDiscovery,
)
```

Append:

```python
API_URLS = {
    "profile": "https://www.tiktok.com/api/post/item_list/?aid=1988&count=16",
    "keyword": "https://www.tiktok.com/api/search/general/full/?aid=1988",
    "trending": "https://www.tiktok.com/api/explore/item_list/?aid=1988",
}
WARM_UP_ID = "1999999999"


def _body_for(kind: str, ids: list[str], has_more: bool = True) -> bytes:
    items = [_item(post_id) for post_id in ids]
    if kind == "keyword":
        return _search_body([{"type": 1, "item": item} for item in items], int(has_more))
    return _list_body(items, has_more)


def _pages(kind: str, count: int, per_page: int = 3, last_has_more: bool = True) -> list[bytes]:
    bodies = []
    for page in range(count):
        ids = [str(1_000_000_000 + page * per_page + index) for index in range(per_page)]
        bodies.append(_body_for(kind, ids, last_has_more or page < count - 1))
    return bodies


class FakeNetworkResponse:
    def __init__(self, url: str, body: bytes, fail: bool = False) -> None:
        self.url = url
        self._body = body
        self._fail = fail

    async def body(self) -> bytes:
        if self._fail:
            raise RuntimeError("Target closed")
        return self._body


class FakePage:
    """Emits one list response on load and one per scroll, like TikTok's infinite list."""

    def __init__(self, api_url: str, bodies: list[bytes], **flags: object) -> None:
        self.api_url = api_url
        self.pending = list(bodies)
        self.emitted: list[bytes] = []
        self.captcha = flags.get("captcha", False)
        self.body_error = flags.get("body_error", False)
        self.wheel_error = flags.get("wheel_error")
        self.scrolls = 0
        self.handlers: list = []
        self.mouse = SimpleNamespace(wheel=self._wheel)

    def on(self, event: str, handler) -> None:
        assert event == "response"
        self.handlers.append(handler)

    def emit(self) -> None:
        if not self.pending:
            return
        body = self.pending.pop(0)
        self.emitted.append(body)
        for handler in self.handlers:
            # An unrelated response must be ignored by the pattern filter.
            handler(FakeNetworkResponse("https://www.tiktok.com/api/user/detail/", b"{}"))
            handler(FakeNetworkResponse(self.api_url, body, fail=bool(self.body_error)))

    async def _wheel(self, delta_x: int, delta_y: int) -> None:
        if self.wheel_error is not None:
            raise self.wheel_error
        self.scrolls += 1
        self.emit()

    async def wait_for_timeout(self, timeout: int) -> None:
        return None

    async def query_selector(self, selector: str) -> object | None:
        assert selector == CAPTCHA_SELECTOR
        return object() if self.captcha else None


class FakeSession:
    def __init__(self, kind: str, bodies: list[bytes], **flags: object) -> None:
        self.page = FakePage(API_URLS[kind], bodies, **flags)
        self.css_captcha = flags.get("css_captcha", False)
        self.fetch_error = flags.get("fetch_error")
        self.enter_error = flags.get("enter_error")
        self.factory_kwargs: dict = {}
        self.fetched: list[str] = []
        self.fetch_kwargs: list[dict] = []
        self.exited = False

    async def __aenter__(self) -> "FakeSession":
        if self.enter_error is not None:
            raise self.enter_error
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.exited = True

    async def fetch(self, url: str, **kwargs: object) -> SimpleNamespace:
        self.fetched.append(url)
        self.fetch_kwargs.append(kwargs)
        if self.fetch_error is not None:
            raise self.fetch_error
        if "page_action" not in kwargs:
            warm_up = SimpleNamespace(url=API_URLS["keyword"], body=_body_for("keyword", [WARM_UP_ID]))
            return SimpleNamespace(captured_xhr=[warm_up], css=lambda selector: [])
        await kwargs["page_setup"](self.page)
        self.page.emit()
        await kwargs["page_action"](self.page)
        captured = [SimpleNamespace(url=self.page.api_url, body=body) for body in self.page.emitted]
        rendered = ["captcha"] if self.css_captcha else []
        return SimpleNamespace(captured_xhr=captured, css=lambda selector: rendered)


def _browser(session: FakeSession) -> ScraplingDiscoveryBrowser:
    def factory(**kwargs: object) -> FakeSession:
        session.factory_kwargs = kwargs
        return session

    return ScraplingDiscoveryBrowser(session_factory=factory)


@pytest.mark.parametrize(
    ("request_model", "url"),
    [
        (ProfileDiscovery(handle="creator"), "https://www.tiktok.com/@creator"),
        (
            KeywordDiscovery(query="anak & kucing/2"),
            "https://www.tiktok.com/search?q=anak%20%26%20kucing%2F2",
        ),
        (TrendingDiscovery(), "https://www.tiktok.com/explore"),
    ],
)
async def test_each_kind_opens_its_ordinary_page(request_model, url: str) -> None:
    session = FakeSession(request_model.kind, _pages(request_model.kind, 1, last_has_more=False))

    await _browser(session).discover(request_model)

    assert session.fetched[-1] == url


async def test_keyword_warms_up_on_explore_and_discards_that_visit() -> None:
    session = FakeSession("keyword", _pages("keyword", 1, last_has_more=False))

    result = await _browser(session).discover(KeywordDiscovery(query="cats"))

    assert session.fetched == [EXPLORE_URL, "https://www.tiktok.com/search?q=cats"]
    assert "page_action" not in session.fetch_kwargs[0]
    assert "page_setup" not in session.fetch_kwargs[0]
    assert WARM_UP_ID not in {video.post_id for video in result.videos}
    assert len(result.videos) == 3


@pytest.mark.parametrize("request_model", [ProfileDiscovery(handle="creator"), TrendingDiscovery()])
async def test_profile_and_trending_need_no_warm_up(request_model) -> None:
    session = FakeSession(request_model.kind, _pages(request_model.kind, 1, last_has_more=False))

    await _browser(session).discover(request_model)

    assert len(session.fetched) == 1


async def test_session_and_fetch_options_capture_only_the_list_api() -> None:
    session = FakeSession("profile", _pages("profile", 1, last_has_more=False))

    await _browser(session).discover(ProfileDiscovery(handle="creator"))

    assert session.factory_kwargs == {
        "headless": True,
        "max_pages": 1,
        "capture_xhr": XHR_PATTERNS["profile"],
    }
    options = {key: session.fetch_kwargs[0][key] for key in ("timeout", "network_idle", "disable_resources", "google_search", "wait")}
    assert options == {
        "timeout": FETCH_TIMEOUT_MS,
        "network_idle": True,
        "disable_resources": False,
        "google_search": False,
        "wait": FETCH_WAIT_MS,
    }
    assert session.exited is True
    assert active_scrapling_session_count() == 0


async def test_stops_scrolling_once_the_limit_is_reached() -> None:
    session = FakeSession("profile", _pages("profile", 5))

    result = await _browser(session).discover(ProfileDiscovery(handle="creator", limit=5))

    assert session.page.scrolls == 1
    assert result.pages == 2
    assert len(result.videos) == 5
    assert result.reason is None
    assert result.exhausted is False


async def test_stops_when_a_page_reports_no_more_results() -> None:
    session = FakeSession("trending", _pages("trending", 2, last_has_more=False))

    result = await _browser(session).discover(TrendingDiscovery(limit=100))

    assert session.page.scrolls == 1
    assert result.pages == 2
    assert len(result.videos) == 6
    assert result.exhausted is True
    assert result.reason is None


async def test_stops_after_two_scrolls_that_load_nothing() -> None:
    session = FakeSession("profile", _pages("profile", 1))

    result = await _browser(session).discover(ProfileDiscovery(handle="creator", limit=100))

    assert session.page.scrolls == 2
    assert result.pages == 1
    assert result.exhausted is False
    assert result.reason is None


async def test_stops_at_max_scrolls() -> None:
    session = FakeSession("profile", _pages("profile", 20))

    result = await _browser(session).discover(ProfileDiscovery(handle="creator", limit=100))

    assert session.page.scrolls == discovery_module.MAX_SCROLLS == 10
    assert result.pages == 11
    assert len(result.videos) == 33


async def test_captcha_container_stops_with_a_partial_result() -> None:
    session = FakeSession("profile", _pages("profile", 3), captcha=True)

    result = await _browser(session).discover(ProfileDiscovery(handle="creator"))

    assert session.page.scrolls == 0
    assert result.reason is DiscoveryReason.CAPTCHA
    assert result.pages == 1
    assert len(result.videos) == 3


async def test_captcha_rendered_in_the_final_page_is_reported() -> None:
    session = FakeSession("profile", _pages("profile", 1, last_has_more=False), css_captcha=True)

    result = await _browser(session).discover(ProfileDiscovery(handle="creator"))

    assert result.reason is DiscoveryReason.CAPTCHA
    assert len(result.videos) == 3


async def test_scroll_deadline_is_a_timeout_with_a_partial_result(monkeypatch) -> None:
    monkeypatch.setattr(discovery_module, "SCROLL_DEADLINE_S", 0.0)
    session = FakeSession("profile", _pages("profile", 3))

    result = await _browser(session).discover(ProfileDiscovery(handle="creator"))

    assert session.page.scrolls == 0
    assert result.reason is DiscoveryReason.TIMEOUT
    assert len(result.videos) == 3


async def test_an_empty_first_body_is_captcha_with_no_pages() -> None:
    session = FakeSession("keyword", [b"", *_pages("keyword", 2)])

    result = await _browser(session).discover(KeywordDiscovery(query="cats"))

    assert session.page.scrolls == 0
    assert result.reason is DiscoveryReason.CAPTCHA
    assert result.pages == 0
    assert result.videos == []


async def test_a_blocked_page_keeps_earlier_videos() -> None:
    blocked = json.dumps({"statusCode": 10201}).encode()
    session = FakeSession("profile", [*_pages("profile", 1), blocked])

    result = await _browser(session).discover(ProfileDiscovery(handle="creator"))

    assert session.page.scrolls == 1
    assert result.reason is DiscoveryReason.BLOCKED
    assert result.pages == 1
    assert len(result.videos) == 3


def test_assembly_ignores_pages_after_the_first_reason() -> None:
    blocked = json.dumps({"statusCode": 10201}).encode()
    first = _body_for("profile", ["1000000001"])
    later = _body_for("profile", ["1000000002"], has_more=False)

    result = _assemble("profile", 100, [first, blocked, later], captcha=False, timed_out=False)

    assert [video.post_id for video in result.videos] == ["1000000001"]
    assert result.pages == 1
    assert result.reason is DiscoveryReason.BLOCKED
    assert result.exhausted is False


def test_assembly_deduplicates_first_seen_sums_drops_and_truncates() -> None:
    first = _list_body(
        [_item("1000000001", desc="first"), _item("1000000002"), _item("1000000009", isAd=True)]
    )
    second = _list_body(
        [_item("1000000001", desc="second"), _item("1000000003"), _item("1000000008", isAd=True)],
        has_more=False,
    )

    result = _assemble("profile", 2, [first, second], captcha=False, timed_out=False)

    assert [video.post_id for video in result.videos] == ["1000000001", "1000000002"]
    assert result.videos[0].caption == "first"
    assert result.drops == DiscoveryDrops(ads=2)
    assert result.pages == 2
    assert result.exhausted is True


async def test_no_captured_response_is_no_data() -> None:
    session = FakeSession("trending", [])

    result = await _browser(session).discover(TrendingDiscovery())

    assert result.reason is DiscoveryReason.NO_DATA
    assert result.pages == 0


async def test_a_factory_failure_is_browser_unavailable() -> None:
    def broken_factory(**kwargs: object) -> None:
        raise ImportError("scrapling is not installed")

    result = await ScraplingDiscoveryBrowser(session_factory=broken_factory).discover(TrendingDiscovery())

    assert result.reason is DiscoveryReason.BROWSER_UNAVAILABLE
    assert result.videos == []
    assert active_scrapling_session_count() == 0


async def test_a_browser_start_failure_is_browser_unavailable() -> None:
    session = FakeSession("trending", [], enter_error=RuntimeError("no browser binary"))

    result = await _browser(session).discover(TrendingDiscovery())

    assert result.reason is DiscoveryReason.BROWSER_UNAVAILABLE
    assert active_scrapling_session_count() == 0


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (TimeoutError("navigation"), DiscoveryReason.TIMEOUT),
        (RuntimeError("page crashed"), DiscoveryReason.BROWSER_UNAVAILABLE),
    ],
)
async def test_fetch_errors_are_classified_and_close_the_session(error, reason) -> None:
    session = FakeSession("profile", _pages("profile", 1), fetch_error=error)

    result = await _browser(session).discover(ProfileDiscovery(handle="creator"))

    assert result.reason is reason
    assert result.videos == []
    assert session.exited is True
    assert active_scrapling_session_count() == 0


async def test_cancellation_propagates_and_still_closes_the_session() -> None:
    session = FakeSession("profile", _pages("profile", 1), fetch_error=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await _browser(session).discover(ProfileDiscovery(handle="creator"))

    assert session.exited is True
    assert active_scrapling_session_count() == 0


async def test_a_failing_scroll_keeps_what_was_captured() -> None:
    session = FakeSession("profile", _pages("profile", 3), wheel_error=RuntimeError("detached"))

    result = await _browser(session).discover(ProfileDiscovery(handle="creator"))

    assert result.pages == 1
    assert len(result.videos) == 3
    assert result.reason is None


async def test_a_failed_in_page_body_read_stops_scrolling_but_keeps_the_capture() -> None:
    session = FakeSession("profile", _pages("profile", 3), body_error=True)

    result = await _browser(session).discover(ProfileDiscovery(handle="creator"))

    assert session.page.scrolls == 0
    assert result.pages == 1
    assert len(result.videos) == 3
    assert result.reason is None


async def test_logs_carry_counts_but_never_targets_or_content(caplog) -> None:
    session = FakeSession("keyword", _pages("keyword", 1), captcha=True)
    caplog.set_level(logging.INFO, logger=discovery_module.__name__)

    await _browser(session).discover(KeywordDiscovery(query="secretquery"))

    records = [record for record in caplog.records if record.name == discovery_module.__name__]
    assert [record.levelname for record in records] == ["INFO", "WARNING"]
    text = " ".join(record.getMessage() for record in records)
    for secret in ("secretquery", "creator", "a caption", "1000000000", WARM_UP_ID, "tiktok.com"):
        assert secret not in text


def test_importing_discovery_module_does_not_import_scrapling_or_patchright() -> None:
    probe = (
        "import sys;"
        "import thoth_control_plane.acquisition.discovery;"
        "assert 'scrapling' not in sys.modules;"
        "assert 'patchright' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_discovery.py 2>&1 | tail -5`
Expected: collection error, `ImportError: cannot import name 'CAPTCHA_SELECTOR'`.

- [ ] **Step 3: Implement the browser**

In `discovery.py`, replace the import block (from `from __future__ import annotations` through
the `normalize` import) with:

```python
from __future__ import annotations

import contextlib
import json
import logging
import math
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from pydantic import ValidationError

from thoth_control_plane.acquisition.browser import (
    FETCH_TIMEOUT_MS,
    FETCH_WAIT_MS,
    _decrement_active_sessions,
    _default_session_factory,
    _increment_active_sessions,
)
from thoth_control_plane.acquisition.models import (
    DiscoveredVideo,
    DiscoveryDrops,
    DiscoveryKind,
    DiscoveryReason,
    DiscoveryRequest,
    DiscoveryResult,
    KeywordDiscovery,
    ProfileDiscovery,
)
from thoth_control_plane.acquisition.normalize import normalize_engagement, published_at_from_epoch

logger = logging.getLogger(__name__)

# One pattern per kind, so a session holds only its own list responses.
XHR_PATTERNS: dict[str, str] = {
    "profile": r"/api/post/item_list/",
    "keyword": r"/api/search/general/full/",
    "trending": r"/api/explore/item_list/",
}
EXPLORE_URL = "https://www.tiktok.com/explore"
CAPTCHA_SELECTOR = '[id*="captcha"], .captcha-verify-container'
```

Keep `MAX_CAPTION` and `MAX_HASHTAG`, and add directly below them:

```python
MAX_SCROLLS = 10
SCROLL_PX = 5_000
SCROLL_WAIT_MS = 3_000
POLL_MS = 250
IDLE_SCROLLS = 2
SCROLL_DEADLINE_S = 60.0
_FETCH_OPTIONS: dict[str, Any] = {
    "timeout": FETCH_TIMEOUT_MS,
    "network_idle": True,
    "disable_resources": False,
    "google_search": False,
    "wait": FETCH_WAIT_MS,
}
```

Append at the end of the file:

```python
@dataclass
class _Scroll:
    """Live tally of the list responses the page makes while it is scrolled.

    It only decides when to stop scrolling. The result is built afterwards from Scrapling's
    own capture, so a failed read here never loses a page.
    """

    kind: DiscoveryKind
    limit: int
    responses: list[Any] = field(default_factory=list)
    parsed: int = 0
    seen: set[str] = field(default_factory=set)
    done: bool = False
    captcha: bool = False
    timed_out: bool = False

    def on_response(self, response: Any) -> None:
        if re.search(XHR_PATTERNS[self.kind], response.url):
            self.responses.append(response)

    async def attach(self, page: Any) -> None:
        page.on("response", self.on_response)

    async def absorb(self) -> None:
        while self.parsed < len(self.responses):
            response = self.responses[self.parsed]
            self.parsed += 1
            try:
                body = await response.body()
            except Exception:
                body = b""
            page = parse_discovery_page(self.kind, body)
            self.seen.update(video.post_id for video in page.videos)
            if page.reason is not None or not page.has_more:
                self.done = True


def _scroll_action(scroll: _Scroll) -> Callable[[Any], Awaitable[None]]:
    async def action(page: Any) -> None:
        # A failed scroll must never discard the pages Scrapling already captured.
        with contextlib.suppress(Exception):
            await _paginate(page, scroll)

    return action


async def _paginate(page: Any, scroll: _Scroll) -> None:
    deadline = time.monotonic() + SCROLL_DEADLINE_S
    idle = 0
    for _ in range(MAX_SCROLLS):
        await scroll.absorb()
        if scroll.done or len(scroll.seen) >= scroll.limit:
            return
        if await page.query_selector(CAPTCHA_SELECTOR) is not None:
            scroll.captcha = True
            return
        if time.monotonic() >= deadline:
            scroll.timed_out = True
            return
        before = len(scroll.responses)
        await page.mouse.wheel(0, SCROLL_PX)
        if await _wait_for_new(page, scroll, before):
            idle = 0
        else:
            idle += 1
            if idle >= IDLE_SCROLLS:
                return


async def _wait_for_new(page: Any, scroll: _Scroll, before: int) -> bool:
    for _ in range(SCROLL_WAIT_MS // POLL_MS):
        if len(scroll.responses) > before:
            return True
        await page.wait_for_timeout(POLL_MS)
    return len(scroll.responses) > before


def _assemble(
    kind: DiscoveryKind,
    limit: int,
    bodies: list[bytes],
    *,
    captcha: bool,
    timed_out: bool,
) -> DiscoveryResult:
    """Parse captured pages in order; the first page reason stops assembly."""
    videos: dict[str, DiscoveredVideo] = {}
    pages = ads = photo_posts = invalid = 0
    exhausted = False
    reason: DiscoveryReason | None = None
    for body in bodies:
        page = parse_discovery_page(kind, body)
        if page.reason is not None:
            reason = page.reason
            exhausted = False
            break
        pages += 1
        ads += page.drops.ads
        photo_posts += page.drops.photo_posts
        invalid += page.drops.invalid
        for video in page.videos:
            videos.setdefault(video.post_id, video)
        exhausted = not page.has_more
    if reason is None:
        if captcha:
            reason = DiscoveryReason.CAPTCHA
        elif not bodies:
            reason = DiscoveryReason.NO_DATA
        elif timed_out:
            reason = DiscoveryReason.TIMEOUT
    return DiscoveryResult(
        kind=kind,
        videos=list(videos.values())[:limit],
        pages=pages,
        exhausted=exhausted,
        drops=DiscoveryDrops(ads=ads, photo_posts=photo_posts, invalid=invalid),
        reason=reason,
    )


def _empty(kind: DiscoveryKind, reason: DiscoveryReason) -> DiscoveryResult:
    return DiscoveryResult(
        kind=kind, videos=[], pages=0, exhausted=False, drops=DiscoveryDrops(), reason=reason
    )


def _body(entry: Any) -> bytes:
    body = getattr(entry, "body", None)
    return body if isinstance(body, bytes) else b""


def _captcha_rendered(response: Any) -> bool:
    try:
        return bool(response.css(CAPTCHA_SELECTOR))
    except Exception:
        return False


def _page_url(request: DiscoveryRequest) -> str:
    if isinstance(request, ProfileDiscovery):
        return f"https://www.tiktok.com/@{request.handle}"
    if isinstance(request, KeywordDiscovery):
        # Never `/search/video`: that route is refused with a captcha.
        return f"https://www.tiktok.com/search?q={quote(request.query, safe='')}"
    return EXPLORE_URL


class ScraplingDiscoveryBrowser:
    """Discovers TikTok videos by scrolling the ordinary page in a stealthy headless session."""

    def __init__(self, session_factory: Callable[..., Any] = _default_session_factory) -> None:
        self._session_factory = session_factory

    async def discover(self, request: DiscoveryRequest) -> DiscoveryResult:
        result = await self._collect(request)
        reason = result.reason.value if result.reason is not None else "none"
        logger.info(
            "tiktok discovery finished kind=%s pages=%d videos=%d ads=%d photo_posts=%d "
            "invalid=%d reason=%s",
            result.kind,
            result.pages,
            len(result.videos),
            result.drops.ads,
            result.drops.photo_posts,
            result.drops.invalid,
            reason,
        )
        if result.reason in (DiscoveryReason.CAPTCHA, DiscoveryReason.BLOCKED):
            logger.warning("tiktok discovery stopped early kind=%s reason=%s", result.kind, reason)
        return result

    async def _collect(self, request: DiscoveryRequest) -> DiscoveryResult:
        kind = request.kind
        try:
            session = self._session_factory(
                headless=True, max_pages=1, capture_xhr=XHR_PATTERNS[kind]
            )
            active = await session.__aenter__()
        except Exception:
            return _empty(kind, DiscoveryReason.BROWSER_UNAVAILABLE)

        _increment_active_sessions()
        scroll = _Scroll(kind=kind, limit=request.limit)
        try:
            if isinstance(request, KeywordDiscovery):
                # Search answers only a session warmed on /explore; that visit is discarded.
                await active.fetch(EXPLORE_URL, **_FETCH_OPTIONS)
            response = await active.fetch(
                _page_url(request),
                page_setup=scroll.attach,
                page_action=_scroll_action(scroll),
                **_FETCH_OPTIONS,
            )
        except Exception as error:
            if "timeout" in type(error).__name__.lower():
                return _empty(kind, DiscoveryReason.TIMEOUT)
            return _empty(kind, DiscoveryReason.BROWSER_UNAVAILABLE)
        finally:
            try:
                with contextlib.suppress(Exception):
                    await session.__aexit__(None, None, None)
            finally:
                _decrement_active_sessions()

        bodies = [_body(entry) for entry in getattr(response, "captured_xhr", None) or []]
        return _assemble(
            kind,
            request.limit,
            bodies,
            captcha=scroll.captcha or _captcha_rendered(response),
            timed_out=scroll.timed_out,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition 2>&1 | tail -5`
Expected: all passed, 0 failed.

- [ ] **Step 5: Run ruff**

Run the ruff command from Global Constraints. Expected: `RC=0`. If ruff reports a
private-import rule on the `browser.py` helpers, stop and ledger a ruling. Do not duplicate the
session counter.

- [ ] **Step 6: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/discovery.py python/tests/acquisition/test_discovery.py
git commit -m "feat: add headless tiktok discovery browser"
```

---

### Task 6: Discovery fixture sanitizer

**Files:**
- Create: `python/src/thoth_control_plane/operations/tiktok_discovery_fixture.py`
- Test: `python/tests/operations/test_tiktok_discovery_fixture.py`

**Interfaces:**
- Consumes:
  - Task 4: `parse_discovery_page`;
  - from `operations/tiktok_comment_fixture.py`: `_Pseudonyms` and `ID_BASE`, where
    `.comment_id(v)` gives a 19-digit id, `.handle(v)` gives `user_NNN`, and `.text(v)` gives
    same-length text.
- Produces, in `thoth_control_plane.operations.tiktok_discovery_fixture`:
  - `sanitize_capture(raw: dict) -> dict`, where `raw` is `{"kind", "pages": [str, ...]}` and
    the result is `{"kind", "pages": [dict | None, ...], "expected": [dict, ...]}`;
  - `replay_page(kind, body: bytes) -> dict`, the non-secret projection of one parsed page;
  - `fixture_page_bytes(page: dict | None) -> bytes`;
  - `leak_report(raw: dict, text: str) -> tuple[int, int]`, returning `(checked, leaks)`;
  - `main(argv) -> int`, which prints `checked=N leaks=M` and writes only on zero leaks.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/operations/test_tiktok_discovery_fixture.py`:

```python
"""Golden TikTok discovery captures: sanitizer, leak check, and parser replay."""

import json

from thoth_control_plane.operations import tiktok_discovery_fixture as fixture_module
from thoth_control_plane.operations.tiktok_comment_fixture import ID_BASE
from thoth_control_plane.operations.tiktok_discovery_fixture import (
    MAX_FIXTURE_PAGES,
    main,
    sanitize_capture,
)

RAW_ITEM = {
    "id": "7412345678901234567",
    "desc": "Secret caption #kitten",
    "createTime": 1709287200,
    "author": {
        "uniqueId": "real.creator",
        "secUid": "MS4wLjABAAAAsecret",
        "nickname": "Real Creator",
        "avatarThumb": "https://p16.example/avatar.jpg",
    },
    "stats": {
        "playCount": 10,
        "diggCount": 5,
        "commentCount": 2,
        "shareCount": 1,
        "collectCount": 3,
        "whateverCount": 9,
    },
    "statsV2": {"playCount": "10", "diggCount": "5"},
    "video": {"duration": 15, "playAddr": "https://v16.example/p.mp4"},
    "challenges": [{"title": "kitten", "id": "123", "coverLarger": "https://p16.example/k.jpg"}],
    "music": {"title": "a song"},
}
PAGE = {"statusCode": 0, "hasMore": True, "itemList": [RAW_ITEM], "cursor": "1709287200000"}


def _raw(kind: str, pages: list) -> dict:
    return {"kind": kind, "pages": [page if isinstance(page, str) else json.dumps(page) for page in pages]}


def test_items_keep_only_parser_keys_with_pseudonymized_values() -> None:
    [page] = sanitize_capture(_raw("profile", [PAGE]))["pages"]

    assert set(page) == {"statusCode", "hasMore", "itemList"}
    [item] = page["itemList"]
    assert item == {
        "id": str(ID_BASE),
        "desc": item["desc"],
        "createTime": 1709287200,
        "stats": {
            "playCount": 10,
            "diggCount": 5,
            "commentCount": 2,
            "shareCount": 1,
            "collectCount": 3,
        },
        "statsV2": {"playCount": "10", "diggCount": "5"},
        "video": {"duration": 15},
        "author": {"uniqueId": "user_001"},
        "challenges": [{"title": item["challenges"][0]["title"]}],
    }
    assert len(item["desc"]) == len(RAW_ITEM["desc"]) and item["desc"] != RAW_ITEM["desc"]
    assert len(item["challenges"][0]["title"]) == 6
    assert item["challenges"][0]["title"] != "kitten"


def test_search_entries_are_reduced_to_type_and_item() -> None:
    page = {
        "status_code": 0,
        "has_more": 1,
        "data": [
            {"type": 1, "item": RAW_ITEM, "common": {"doc_id_str": "x"}},
            {"type": 4, "user_list": [{"uniqueId": "real.creator"}]},
        ],
    }

    [sanitized] = sanitize_capture(_raw("keyword", [page]))["pages"]

    assert set(sanitized) == {"status_code", "has_more", "data"}
    assert [entry["type"] for entry in sanitized["data"]] == [1, 4]
    assert set(sanitized["data"][0]) == {"type", "item"}
    assert sanitized["data"][1] == {"type": 4}


def test_expected_records_the_capture_replay() -> None:
    items = [
        RAW_ITEM,
        {**RAW_ITEM, "id": "7412345678901234568", "isAd": True},
        {**RAW_ITEM, "id": "7412345678901234569", "imagePost": {"images": [{"url": "https://x"}]}},
        {**RAW_ITEM, "id": 7412345678901234570},
    ]
    page = {"statusCode": 0, "hasMore": False, "itemList": items}

    fixture = sanitize_capture(_raw("profile", [page]))

    [expected] = fixture["expected"]
    assert expected["drops"] == {"ads": 1, "photo_posts": 1, "invalid": 1}
    assert expected["has_more"] is False
    assert expected["reason"] is None
    assert expected["videos"] == [
        {
            "published_at": "2024-03-01T10:00:00Z",
            "duration_seconds": 15.0,
            "engagement": {"play": 10, "like": 5, "comment": 2, "share": 1, "collect": 3},
            "caption_length": 22,
            "hashtags": 1,
        }
    ]
    assert fixture["pages"][0]["itemList"][1]["isAd"] is True
    assert fixture["pages"][0]["itemList"][2]["imagePost"] == {}


def test_a_non_json_page_becomes_null_and_replays_as_captcha() -> None:
    fixture = sanitize_capture(_raw("keyword", ["<html>verify</html>"]))

    assert fixture["pages"] == [None]
    assert fixture["expected"][0]["reason"] == "captcha"


def test_only_the_first_pages_are_kept() -> None:
    fixture = sanitize_capture(_raw("profile", [PAGE, PAGE, PAGE]))

    assert len(fixture["pages"]) == len(fixture["expected"]) == MAX_FIXTURE_PAGES == 2


def test_main_writes_a_leak_free_lf_fixture(tmp_path, capsys) -> None:
    source = tmp_path / "raw.json"
    target = tmp_path / "fixture.json"
    source.write_text(json.dumps(_raw("profile", [PAGE])), encoding="utf-8")

    assert main([str(source), str(target)]) == 0

    assert capsys.readouterr().out == "checked=6 leaks=0\n"
    data = target.read_bytes()
    assert b"\r\n" not in data
    for secret in (b"real.creator", b"Secret caption", b"7412345678901234567", b"http"):
        assert secret not in data


def test_main_refuses_to_write_when_an_original_survives(tmp_path, capsys, monkeypatch) -> None:
    def passthrough(raw: dict) -> dict:
        return {"kind": raw["kind"], "pages": [json.loads(page) for page in raw["pages"]]}

    monkeypatch.setattr(fixture_module, "sanitize_capture", passthrough)
    source = tmp_path / "raw.json"
    target = tmp_path / "fixture.json"
    source.write_text(json.dumps(_raw("profile", [PAGE])), encoding="utf-8")

    assert main([str(source), str(target)]) == 1

    assert not target.exists()
    assert "leaks=0" not in capsys.readouterr().out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/operations/test_tiktok_discovery_fixture.py 2>&1 | tail -5`
Expected: collection error, `ModuleNotFoundError: No module named 'thoth_control_plane.operations.tiktok_discovery_fixture'`.

- [ ] **Step 3: Implement the sanitizer**

Create `python/src/thoth_control_plane/operations/tiktok_discovery_fixture.py`:

```python
"""Sanitize a one-time live TikTok discovery capture into a public golden fixture.

The repository is public. A fixture keeps at most two list pages and only the keys the
discovery parser reads. Ids, handles, captions, and hashtags become stable pseudonyms of the
same shape; every URL and every other key is dropped. Engagement counters and `createTime` are
kept: they are public aggregate values the normalizer is tested against. The tool replays the
parser over both forms and refuses to write if they differ or if any original value survives.

Usage: python -m thoth_control_plane.operations.tiktok_discovery_fixture RAW.json FIXTURE.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.discovery import parse_discovery_page
from thoth_control_plane.operations.tiktok_comment_fixture import _Pseudonyms

MAX_FIXTURE_PAGES = 2
ENVELOPE_KEYS = ("statusCode", "status_code", "hasMore", "has_more")
STAT_KEYS = ("playCount", "diggCount", "commentCount", "shareCount", "collectCount")
MIN_SECRET_LENGTH = 4


def _stats(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {key: value[key] for key in STAT_KEYS if key in value}


def _create_time(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, int) or (isinstance(value, str) and value.isdecimal())


def _item(names: _Pseudonyms, item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    kept: dict[str, Any] = {}
    if isinstance(item.get("id"), str):
        kept["id"] = names.comment_id(item["id"])
    if isinstance(item.get("desc"), str):
        kept["desc"] = names.text(item["desc"])
    if _create_time(item.get("createTime")):
        kept["createTime"] = item["createTime"]
    for key in ("stats", "statsV2"):
        stats = _stats(item.get(key))
        if stats is not None:
            kept[key] = stats
    video = item.get("video")
    if isinstance(video, dict) and "duration" in video:
        kept["video"] = {"duration": video["duration"]}
    author = item.get("author")
    if isinstance(author, dict) and isinstance(author.get("uniqueId"), str):
        kept["author"] = {"uniqueId": names.handle(author["uniqueId"])}
    challenges = item.get("challenges")
    if isinstance(challenges, list):
        kept["challenges"] = [
            {"title": names.text(challenge["title"])}
            for challenge in challenges
            if isinstance(challenge, dict) and isinstance(challenge.get("title"), str)
        ]
    if item.get("imagePost") is not None:
        kept["imagePost"] = {}
    if isinstance(item.get("isAd"), bool):
        kept["isAd"] = item["isAd"]
    return kept


def _entry(names: _Pseudonyms, entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    if entry.get("type") == 1:
        return {"type": 1, "item": _item(names, entry.get("item"))}
    entry_type = entry.get("type")
    return {"type": entry_type if isinstance(entry_type, int) else None}


def _payload(text: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(text)
    except (ValueError, RecursionError):
        return None
    return payload if isinstance(payload, dict) else None


def _page(names: _Pseudonyms, kind: str, text: str) -> dict[str, Any] | None:
    payload = _payload(text)
    if payload is None:
        return None
    page = {key: payload[key] for key in ENVELOPE_KEYS if key in payload}
    if kind == "keyword":
        data = payload.get("data")
        if isinstance(data, list):
            page["data"] = [_entry(names, entry) for entry in data]
    else:
        items = payload.get("itemList")
        if isinstance(items, list):
            page["itemList"] = [_item(names, item) for item in items]
    return page


def fixture_page_bytes(page: dict[str, Any] | None) -> bytes:
    """A fixture page as the raw body the parser reads; `null` replays as an empty body."""
    return b"" if page is None else json.dumps(page, ensure_ascii=False).encode("utf-8")


def replay_page(kind: str, body: bytes) -> dict[str, Any]:
    """The parser's view of one page, projected onto values that are never secret."""
    page = parse_discovery_page(kind, body)
    return {
        "has_more": page.has_more,
        "reason": page.reason.value if page.reason is not None else None,
        "drops": page.drops.model_dump(),
        "videos": [
            {
                "published_at": video.published_at,
                "duration_seconds": video.duration_seconds,
                "engagement": dict(video.engagement),
                "caption_length": len(video.caption),
                "hashtags": len(video.hashtags),
            }
            for video in page.videos
        ],
    }


def sanitize_capture(raw: dict[str, Any]) -> dict[str, Any]:
    kind = raw["kind"]
    if kind not in ("profile", "keyword", "trending"):
        raise ValueError("unknown discovery kind")
    names = _Pseudonyms()
    texts = raw["pages"][:MAX_FIXTURE_PAGES]
    pages = [_page(names, kind, text) for text in texts]
    expected = [replay_page(kind, text.encode("utf-8")) for text in texts]
    if [replay_page(kind, fixture_page_bytes(page)) for page in pages] != expected:
        raise ValueError("sanitized pages do not replay like the capture")
    return {"kind": kind, "pages": pages, "expected": expected}


def _raw_items(kind: str, payload: dict[str, Any]) -> list[Any]:
    if kind == "keyword":
        data = payload.get("data")
        return [e.get("item") for e in data if isinstance(e, dict)] if isinstance(data, list) else []
    items = payload.get("itemList")
    return items if isinstance(items, list) else []


def _originals(raw: dict[str, Any]) -> set[str]:
    """Every original id, handle, caption, and hashtag long enough to identify a source."""
    secrets: set[str] = set()
    for text in raw["pages"]:
        payload = _payload(text)
        for item in _raw_items(raw["kind"], payload) if payload is not None else []:
            if not isinstance(item, dict):
                continue
            author = item.get("author") if isinstance(item.get("author"), dict) else {}
            challenges = item.get("challenges") if isinstance(item.get("challenges"), list) else []
            values = [
                item.get("id"),
                item.get("desc"),
                author.get("uniqueId"),
                author.get("secUid"),
                author.get("nickname"),
                *(c.get("title") for c in challenges if isinstance(c, dict)),
            ]
            secrets.update(
                value.strip()
                for value in values
                if isinstance(value, str)
                and len(value.strip()) >= MIN_SECRET_LENGTH
                and any(char.isalnum() for char in value)
            )
    return secrets


def leak_report(raw: dict[str, Any], text: str) -> tuple[int, int]:
    """Count originals that survive into `text`, raw or JSON-escaped, plus any URL."""
    secrets = _originals(raw)
    leaks = sum(
        secret in text or json.dumps(secret, ensure_ascii=False)[1:-1] in text
        for secret in secrets
    )
    return len(secrets), leaks + ("http" in text)


def main(argv: list[str] | None = None) -> int:
    source, target = argv if argv is not None else sys.argv[1:]
    raw = json.loads(Path(source).read_text(encoding="utf-8"))
    text = json.dumps(sanitize_capture(raw), ensure_ascii=False, indent=2) + "\n"
    checked, leaks = leak_report(raw, text)
    print(f"checked={checked} leaks={leaks}")
    if leaks:
        return 1
    Path(target).write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/operations/test_tiktok_discovery_fixture.py tests/operations/test_tiktok_comment_fixture.py 2>&1 | tail -5`
Expected: all passed, 0 failed.

- [ ] **Step 5: Run ruff**

Run the ruff command from Global Constraints. Expected: `RC=0`.

- [ ] **Step 6: Commit**

```bash
git add python/src/thoth_control_plane/operations/tiktok_discovery_fixture.py python/tests/operations/test_tiktok_discovery_fixture.py
git commit -m "feat: add tiktok discovery fixture sanitizer"
```

---

### Task 7: Live capture and sanitized golden fixtures

**Operator gate.** This is the only live network run in the plan: read-only and anonymous, one
run per kind. It requires the operator's fixture-capture authorization for this execution. If
that authorization is not in the conversation, stop and ask before Step 3. Never write the
authorization into a repository document.

**Files:**
- Create: `python/tests/fixtures/tiktok/discovery/profile.json`, `search.json`, `explore.json`
- Modify: `python/tests/operations/test_tiktok_discovery_fixture.py` (append golden tests)
- Throwaway, never committed: `D:/thoth-tmp/bu/extract_targets.py`, `capture_discovery.py`,
  `capture_discovery.sh`, `sanitize_discovery.sh`, and
  `D:/thoth-tmp/bu/out/discovery_targets.json`

**Interfaces:**
- Consumes:
  - Task 5: `ScraplingDiscoveryBrowser`, `_assemble` (wrapped to record bodies);
  - Task 6: `main`, `replay_page`, `fixture_page_bytes`;
  - Task 4: `parse_discovery_page`.
- Produces: three committed golden fixtures of two pages each.

- [ ] **Step 1: Copy the capture targets without printing them**

Create `D:/thoth-tmp/bu/extract_targets.py` with the Write tool:

```python
# Throwaway: copy the probe's public discovery targets without printing them.
import json
import pathlib
import re
from urllib.parse import unquote_plus

source = pathlib.Path("D:/thoth-tmp/bu/disc9.py").read_text(encoding="utf-8")
handle = re.search(r"tiktok\.com/@([A-Za-z0-9._-]+)", source).group(1)
query = unquote_plus(re.search(r"search\?q=([^\"'&\s]+)", source).group(1))
target = pathlib.Path("D:/thoth-tmp/bu/out/discovery_targets.json")
target.write_text(json.dumps({"handle": handle, "query": query}), encoding="utf-8")
print("targets written")
```

Run: `python D:/thoth-tmp/bu/extract_targets.py`
Expected: `targets written`. Never print or `cat` the file.

- [ ] **Step 2: Write the capture scripts**

Create `D:/thoth-tmp/bu/capture_discovery.py` with the Write tool:

```python
# Throwaway: one read-only anonymous discovery run per kind. Prints counts only.
import asyncio
import json
import sys

sys.path.insert(0, "/src")

from thoth_control_plane.acquisition import discovery as dm  # noqa: E402
from thoth_control_plane.acquisition.models import (  # noqa: E402
    KeywordDiscovery,
    ProfileDiscovery,
    TrendingDiscovery,
)

with open("/out/discovery_targets.json", encoding="utf-8") as handle_file:
    targets = json.load(handle_file)
captured = {}
original_assemble = dm._assemble


def recording_assemble(kind, limit, bodies, **flags):
    captured[kind] = [body.decode("utf-8", "replace") for body in bodies]
    return original_assemble(kind, limit, bodies, **flags)


dm._assemble = recording_assemble
REQUESTS = {
    "profile": ProfileDiscovery(handle=targets["handle"], limit=40),
    "keyword": KeywordDiscovery(query=targets["query"], limit=30),
    "trending": TrendingDiscovery(limit=20),
}


async def main():
    for kind in sys.argv[1:] or list(REQUESTS):
        result = await dm.ScraplingDiscoveryBrowser().discover(REQUESTS[kind])
        pages = captured.get(kind, [])
        with open(f"/out/discovery-{kind}.json", "w", encoding="utf-8") as out:
            json.dump({"kind": kind, "pages": pages}, out, ensure_ascii=False)
        drops = result.drops
        reason = result.reason.value if result.reason is not None else None
        print(
            f"kind={kind} pages={result.pages} captured={len(pages)} videos={len(result.videos)}"
            f" exhausted={result.exhausted} ads={drops.ads} photo_posts={drops.photo_posts}"
            f" invalid={drops.invalid} reason={reason}"
        )


asyncio.run(main())
```

Create `D:/thoth-tmp/bu/capture_discovery.sh` with the Write tool (LF):

```bash
#!/usr/bin/env bash
set -uo pipefail
cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER
IMAGE=$(grep -E '^THOTH_IMAGE=' .env.stage1.local | cut -d= -f2- | tr -d '\r')
mkdir -p /mnt/d/thoth-tmp/bu/out
docker run --rm -i -v /mnt/d/thoth-tmp/bu/out:/out -v "$PWD/python/src":/src:ro --entrypoint /opt/thoth/python/.venv/bin/python "$IMAGE" - "$@" < /mnt/d/thoth-tmp/bu/capture_discovery.py 2>&1 | grep -E "^kind=|Traceback|^[A-Za-z]+Error"
```

- [ ] **Step 3: Run the live capture**

Run: `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/bu/capture_discovery.sh`

Expected: three lines, each `kind=<kind> pages=N captured=N ... reason=None`, with `pages >= 2`
and `videos > 0`, and no `Traceback`.
- A kind with `captured=0`, a first-page `captcha`/`blocked`, or a traceback may be re-run once,
  alone: `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/bu/capture_discovery.sh <kind>`.
- If it fails again, stop and report the count line to the operator. Do not change targets and
  do not retry further.
- If search captures only one page, ledger a ruling. That kind's fixture then holds one page, and
  its golden page-count assertion becomes `1`.
- A later-page `captcha` with `pages >= 2` is acceptable: the fixture keeps the first two pages.

- [ ] **Step 4: Sanitize into fixtures**

Create `D:/thoth-tmp/bu/sanitize_discovery.sh` with the Write tool (LF). It uses the same
dependency set as `pt.sh`, because importing the package pulls in the domain modules:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python
mkdir -p tests/fixtures/tiktok/discovery
for pair in profile:profile keyword:search trending:explore; do
  kind=${pair%%:*}
  name=${pair##*:}
  printf '%s ' "$name"
  PYTHONPATH=$PWD/src ~/.local/bin/uv run --no-project --python 3.12 --with pytest --with pydantic --with typer --with httpx --with pytest-asyncio --with temporalio --with pydantic-settings --with fastapi --with 'psycopg[binary]' --with sqlalchemy --with alembic --with boto3 --with python-multipart --with pyjwt --with respx --with agno --with pillow --with pyyaml -- python -m thoth_control_plane.operations.tiktok_discovery_fixture "/mnt/d/thoth-tmp/bu/out/discovery-$kind.json" "tests/fixtures/tiktok/discovery/$name.json"
done
```

Run: `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/bu/sanitize_discovery.sh`
Expected: three lines, `profile checked=N leaks=0`, `search checked=N leaks=0`, and
`explore checked=N leaks=0`, each with `N > 0`.
- A `leaks=` value other than 0 exits non-zero and writes nothing for that kind. Stop and report
  the count to the operator.
- A `ValueError` (replay mismatch) means the sanitizer changed what the parser sees. Fix the
  sanitizer with a failing unit test first (Task 6 style), then re-run.

Record the `checked`/`leaks` counts in the SDD ledger. Then check the fixtures' line endings:
`file python/tests/fixtures/tiktok/discovery/*.json`. Expected: no `CRLF`.

- [ ] **Step 5: Write the golden tests**

Append to `python/tests/operations/test_tiktok_discovery_fixture.py`, and add the imports this
block needs to the top of the file: `import re`, `from pathlib import Path`, `import pytest`,
`from thoth_control_plane.acquisition.discovery import _assemble, parse_discovery_page`, and
`fixture_page_bytes` and `replay_page` from the fixture module.

```python
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "tiktok" / "discovery"
GOLDEN = {"profile": "profile.json", "keyword": "search.json", "trending": "explore.json"}
GOLDEN_PAGES = {"profile": 2, "keyword": 2, "trending": 2}
ISO_UTC = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
PSEUDONYMOUS_URL = re.compile(r"https://www\.tiktok\.com/@user_[0-9]{3}/video/7[0-9]{18}")
ENGAGEMENT_KEYS = {"play", "like", "comment", "share", "collect"}


def _golden(kind: str) -> dict:
    return json.loads((FIXTURES / GOLDEN[kind]).read_text(encoding="utf-8"))


@pytest.mark.parametrize("kind", list(GOLDEN))
def test_golden_pages_replay_exactly(kind: str) -> None:
    fixture = _golden(kind)

    assert fixture["kind"] == kind
    assert len(fixture["pages"]) == GOLDEN_PAGES[kind]
    replayed = [replay_page(kind, fixture_page_bytes(page)) for page in fixture["pages"]]
    assert replayed == fixture["expected"]


@pytest.mark.parametrize("kind", list(GOLDEN))
def test_golden_pages_yield_normalized_pseudonymous_videos(kind: str) -> None:
    fixture = _golden(kind)

    videos = [
        video
        for page in fixture["pages"]
        for video in parse_discovery_page(kind, fixture_page_bytes(page)).videos
    ]

    assert videos
    for video in videos:
        assert PSEUDONYMOUS_URL.fullmatch(str(video.canonical_url))
        assert set(video.engagement) <= ENGAGEMENT_KEYS
        assert video.published_at is None or ISO_UTC.fullmatch(video.published_at)
    assert any(len(video.engagement) == 5 and video.published_at for video in videos)


@pytest.mark.parametrize("kind", list(GOLDEN))
def test_golden_pages_assemble_without_a_reason(kind: str) -> None:
    fixture = _golden(kind)
    bodies = [fixture_page_bytes(page) for page in fixture["pages"]]

    result = _assemble(kind, 100, bodies, captcha=False, timed_out=False)

    assert result.pages == GOLDEN_PAGES[kind]
    assert result.reason is None
```

- [ ] **Step 6: Run the golden tests**

Run: `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/operations/test_tiktok_discovery_fixture.py 2>&1 | tail -5`
Expected: all passed, 0 failed.

Then prove the replay test can fail. Copy `profile.json` aside, change one `playCount` in it with
the Edit tool, re-run the file, and expect `test_golden_pages_replay_exactly[profile]` to fail.
Restore the file from the copy and re-run. Expected: all passed. Check that
`git diff --stat python/tests/fixtures` still shows only new files.

- [ ] **Step 7: Run ruff**

Run the ruff command from Global Constraints. Expected: `RC=0`.

- [ ] **Step 8: Commit**

```bash
git add python/tests/fixtures/tiktok/discovery/profile.json python/tests/fixtures/tiktok/discovery/search.json python/tests/fixtures/tiktok/discovery/explore.json python/tests/operations/test_tiktok_discovery_fixture.py
git commit -m "test: add sanitized tiktok discovery golden fixtures"
```

Expected: `git status --short` shows nothing under `D:/thoth-tmp` (outside the repository) and
no raw capture staged.

---

### Task 8: Documentation, full verification, and checkpoint

**Files:**
- Modify: `docs/python-scout-migration-roadmap.md` (CRLF)
- Modify: `CHANGELOG.md` (CRLF), with a new entry above the newest `## ` entry
- Modify (gitignored): `.superpowers/sdd/2026-09-23-python-scout-migration-program/progress.md`
  (CRLF)

**Interfaces:**
- Consumes: evidence from Tasks 1-7: commit hashes, test counts, capture counts, leak counts.
- Produces: the documentation record. No code.

- [ ] **Step 1: Run the full verification**

Run: `MSYS_NO_PATHCONV=1 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh 2>&1 | tail -6`
Expected: all passed except the known pre-existing failure
`test_route_modules_do_not_depend_on_a_process_runner`. Any other failure blocks this task.

Run the ruff command from Global Constraints. Expected: `RC=0`.

Run: `git diff --stat master...HEAD -- '*.rs'`
Expected: empty. No Rust changed, so `build_cuda.bat` is not required by spec section 6.

- [ ] **Step 2: Update the roadmap**

Create `D:/thoth-tmp/bu/edit_roadmap_discovery.py` with the Write tool:

```python
import pathlib

p = pathlib.Path("C:/Users/mfr/Documents/MyTools/CLIPPER/docs/python-scout-migration-roadmap.md")
data = p.read_bytes()
stage3 = b"\r\n\r\n## Stage 3: Port the Remaining Platform Adapters"
status = """

Status (2026-09-27): items 1-7 are implemented. Items 1-4 run on the single-post acquisition
path. Items 5-7 are delivered as offline-tested acquisition primitives with no production
caller; discovery orchestration is Stage 8. Closing Stage 2 is the operator's decision.""".replace(
    "\n", "\r\n"
).encode("utf-8")
old_next = (
    b"Stage 1 is closed. Write the Stage 2 design specification and implementation plan\r\n"
    b'("Complete the TikTok Vertical Slice" above) under the direct-migration strategy of'
)
new_next = (
    b"Stage 2 items 1-7 are implemented (see the status note under Stage 2). The operator\r\n"
    b"decides whether Stage 2 closes; the next stage then proceeds under the direct-migration\r\n"
    b"strategy of"
)
assert data.count(stage3) == 1 and data.count(old_next) == 1 and b"\r\n" in data
data = data.replace(stage3, status + stage3, 1).replace(old_next, new_next, 1)
p.write_bytes(data)
print("ok")
```

Run: `python D:/thoth-tmp/bu/edit_roadmap_discovery.py && git diff --stat docs/python-scout-migration-roadmap.md`
Expected: `ok`, then one file changed. `file docs/python-scout-migration-roadmap.md` still
reports CRLF.

- [ ] **Step 3: Add the CHANGELOG entry**

Create `D:/thoth-tmp/bu/edit_changelog_discovery.py` with the Write tool. Fill every `<...>` from
evidence already produced in this run:
- commit hashes come from `git log --oneline master..HEAD`;
- page and video counts come from the Task 7 Step 3 lines;
- test counts come from the Step 1 summary.

```python
import pathlib

p = pathlib.Path("C:/Users/mfr/Documents/MyTools/CLIPPER/CHANGELOG.md")
data = p.read_bytes()
anchor = b"## 2026-09-27 - Stage 2: TikTok comments and real card artifacts (report v2)"
assert data.count(anchor) == 1 and b"\r\n" in data
entry = """## 2026-09-27 - Stage 2: TikTok discovery primitives and engagement normalization

- Spec `docs/superpowers/specs/2026-09-27-tiktok-discovery-primitives-design.md`, plan
  `docs/superpowers/plans/2026-09-27-tiktok-discovery-primitives.md`.
- `<t1>`: discovery contracts: profile, keyword, and trending requests, `DiscoveredVideo`, and a
  `DiscoveryResult` with a typed reason (`captcha`, `blocked`, `no_data`, `timeout`,
  `browser_unavailable`).
- `<t2>`: `acquisition/normalize.py` maps `stats`/`statsV2` and TikWM counters to
  play/like/comment/share/collect, and epoch seconds to ISO 8601 UTC. Malformed values are
  skipped, never guessed.
- `<t3>`: the single-post path fills `TikTokPost.published_at` and `engagement` from the headless
  item and from TikWM. `_merge_post` merges them per field, headless first. No schema change.
- `<t4>`, `<t5>`: `acquisition/discovery.py` scrolls the ordinary profile, search, or explore
  page in one stealthy headless session and parses the list responses the page itself makes. It
  never builds or signs a request. Captchas are avoided, never solved or blocked: a refusal
  returns a partial result with a typed reason.
- `<t6>`, `<t7>`: a sanitizer with built-in replay and leak checks, and golden fixtures from one
  read-only anonymous capture: profile <pp> pages / <pv> videos, search <sp> / <sv>, explore
  <ep> / <ev>. Leak check 0 leaks. Raw captures stay outside the repository.
- No production caller: discovery orchestration is Stage 8.
- Verification:
  - WSL, Python 3.12: <passed> passed, <skipped> skipped, and 1 failed. The failure is the
    pre-existing `test_route_modules_do_not_depend_on_a_process_runner`.
  - ruff check and ruff format are clean.
  - No Rust changed, so no `build_cuda.bat` run was needed.
- Not pushed.

""".replace("\n", "\r\n").encode("utf-8")
p.write_bytes(data.replace(anchor, entry + anchor, 1))
print("ok")
```

Run: `python D:/thoth-tmp/bu/edit_changelog_discovery.py && git diff --stat CHANGELOG.md`
Expected: `ok`, then one file changed.

Then run: `grep -nE '<(t[0-9]|pp|pv|sp|sv|ep|ev|passed|skipped)>' CHANGELOG.md`
Expected: no output, because every placeholder was filled.

- [ ] **Step 4: Commit the docs**

```bash
git add docs/python-scout-migration-roadmap.md CHANGELOG.md
git commit -m "docs: record tiktok discovery primitives"
```

- [ ] **Step 5: Update the program checkpoint and the graph**

Append a `## 2026-09-27 - Stage 2 discovery primitives implemented` section to
`.superpowers/sdd/2026-09-23-python-scout-migration-program/progress.md`. Use a Python binary CRLF
append in the same pattern as Step 3, and never stage the file. The section lists:
- the commits;
- the verification numbers;
- the capture counts and the leak-check counts;
- every `Ruling:` line from this plan's ledger;
- the next operator gates:
  - pushing the branch;
  - the Stage 2 closure decision;
  - the deferred minors (sticker-only filter, 10 vs 12 card cap).

Run: `graphify update .`

Expected: `git status --short` shows a clean tree, because the checkpoint and `graphify-out/` are
gitignored.

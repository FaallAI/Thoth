# Stage 3b: Instagram Acquisition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port Instagram single-post acquisition (post, media, post card, first-page comments
with real per-comment cards, profile card) and anonymous profile discovery onto the Stage 3a
Python platform kernel, following the Threads pattern.

**Architecture:** A pure adapter (`acquisition/adapters/instagram.py`) owns URL identity and
parsing of the anonymous page JSON. A service (`acquisition/instagram_service.py`) owns the
Scrapling request fetcher, one lazily opened headless session for share resolution and card
crops, and `InstagramAcquirer`. A request-only discovery module reads the 12-post profile grid.
Operator-run capture and fixture tools produce sanitized golden fixtures that decide the
content and share-resolution methods offline.

**Tech Stack:** Python 3.12, Pydantic v2, Scrapling (lazily imported; never in tests),
pytest through WSL `pt.sh`, ruff (line length 100).

**Spec:** `docs/superpowers/specs/2026-09-28-stage3b-instagram-design.md`

## Global Constraints

- Branch `feat/stage3b-instagram` from `master`. The branch is not deployable between Task 1
  (routing flips Instagram to `python`) and Task 4 (registry branch); do not push before Task 8.
- X and YouTube stay `legacy`. Facebook and Reddit stay `unsupported`. TikTok and Threads
  behavior is unchanged.
- No new failure codes; `RETRYABLE_FAILURES` and `LEGACY_FALLBACK_ELIGIBLE_CODES` unchanged.
- No live test in the suite. Never change the conftest `_offline_unless_live` guard.
- A card is never synthetic. Card failures never fail acquisition and never enter
  `outcome.attempts`.
- Logs never carry a URL, raw handle, or caption/comment text.
- Task 7 is a HARD STOP: the live capture needs operator authorization at capture time.
- Raw captures, URL files, and PNGs live only under `D:/thoth-tmp/bu/instagram/`; never
  commit, print, or describe them beyond counts, keys, and enums. Mask any URL in shell output
  with `sed -E 's#https?://[^ ]+#<url>#g'`.
- Tests: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh <paths relative to python/> -q`.
- Ruff: `wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff check . && ~/.local/bin/uvx ruff format --check .'`.
- Commits: exactly one `git commit -m "<subject>"`, at most 72 characters, no body, no
  trailer, no AI attribution. `docs/superpowers/` needs `git add -f`.
- Never stage `graphify-out/`, `build_log.txt`, `.superpowers`, `.understand-anything`,
  `.env.stage1.local.bak-*`, or the untracked `design/` files.
- Plans and specs are LF. `CHANGELOG.md`, `docs/python-scout-migration-roadmap.md`, and the
  checkpoint `progress.md` are CRLF: edit them only with the binary Python script in Task 8.
- No Rust changes; `build_cuda.bat` is not required.

## Review Focus

1. A share link whose request lands on the login wall (`/accounts/login/?next=...`) must fail
   as retryable `request_blocked`, not `invalid_source_url` — Task 4
   `test_share_link_landing_on_the_login_wall_is_request_blocked`.
2. The same comment `pk` twice on one page must yield one comment (first wins) and one drop —
   Task 2 `test_duplicate_comment_pk_keeps_the_first`.
3. A post whose `user.username` is missing or outside the handle pattern must be
   `request_incomplete`, never a crash or a report crediting a bogus owner — Task 2
   `test_missing_or_invalid_owner_is_no_parse`, Task 4 `test_missing_owner_is_request_incomplete`.
4. Discovery for `NASA` must find the page user `nasa` (Instagram handles are
   case-insensitive) and credit `nasa` — Task 5 `test_handle_match_is_case_insensitive`.
5. A carousel item without any https URL is skipped with the remaining order kept, and the
   `/<user>/reel/<code>/` URL form is accepted — Task 2 `test_carousel_skips_urlless_items_in_order`
   and the URL parametrization. Also `/share/p/<t>/` is never a post URL — Task 2.

## File Structure

| File | Responsibility |
|---|---|
| `python/src/thoth_control_plane/acquisition/platforms.py` | add the `instagram` host row |
| `python/src/thoth_control_plane/acquisition/models.py` | `ReportSource.platform` gains `"instagram"` |
| `python/src/thoth_control_plane/acquisition/adapters/threads.py` | refactors (a) `_match_safe_path` platform/error, (b) `_widest` |
| `python/src/thoth_control_plane/acquisition/adapters/instagram.py` | new: URL identity and pure parsing |
| `python/src/thoth_control_plane/acquisition/threads_service.py` | refactors (c) `_await_post_url(path)`, (d) module-level `materialize_media` |
| `python/src/thoth_control_plane/acquisition/instagram_service.py` | new: fetcher, headless browser, cards, acquirer |
| `python/src/thoth_control_plane/acquisition/instagram_discovery.py` | new: profile discovery |
| `python/src/thoth_control_plane/acquisition/registry.py` | `instagram` branch |
| `python/src/thoth_control_plane/operations/instagram_capture.py` | new: operator-run capture |
| `python/src/thoth_control_plane/operations/instagram_fixture.py` | new: sanitizer, leak check, method decision |
| `python/tests/fixtures/instagram/*.json` | golden fixtures (Task 7) |

---

### Task 1: Route Instagram to Python

**Files:**
- Modify: `python/src/thoth_control_plane/acquisition/platforms.py:12-15`
- Modify: `python/src/thoth_control_plane/acquisition/models.py:209`
- Test: `python/tests/acquisition/test_platforms.py`, `python/tests/acquisition/test_registry.py`,
  `python/tests/acquisition/test_models.py`, `python/tests/activities/test_source_investigation.py`,
  `python/tests/workflows/test_source_investigation.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `PYTHON_PLATFORM_HOSTS["instagram"] == frozenset({"instagram.com"})`;
  `platform_of(<instagram url>) == "instagram"`; `ReportSource(platform="instagram", ...)` is valid.

- [ ] **Step 1: Create the branch**

```bash
git checkout master && git checkout -b feat/stage3b-instagram
```

- [ ] **Step 2: Write the failing tests**

In `tests/acquisition/test_platforms.py`, change the parametrize row
`("https://www.instagram.com/p/abc/", "legacy"),` to `"python"` and add after the Threads rows:

```python
        ("https://www.instagram.com/p/abc/", "python"),
        ("https://instagram.com/reel/abc/", "python"),
        ("https://m.instagram.com/p/abc/", "python"),
        ("https://WWW.Instagram.COM./p/abc/", "python"),
        ("https://instagr.am/p/abc/", "legacy"),
```

(the first row replaces the old `legacy` row; do not keep both). In
`test_platform_of_names_python_platforms_only`, replace
`assert platform_of("https://www.instagram.com/p/abc/") is None` with:

```python
    assert platform_of("https://www.instagram.com/p/abc/") == "instagram"
    assert platform_of("https://x.com/a/status/1") is None
```

In `tests/acquisition/test_registry.py`, change the `LookupError` URL
`"https://www.instagram.com/p/abc/"` to `"https://x.com/a/status/1"`.

In `tests/activities/test_source_investigation.py` (`test_unknown_platform_never_enters_the_runner`),
change `"https://www.instagram.com/p/abc/"` to `"https://x.com/a/status/1"`.

In `tests/workflows/test_source_investigation.py` (`test_activity_mode_routing` parametrize),
replace the two tuples that start with `"https://www.instagram.com/p/abc/"` by:

```python
        (
            "https://x.com/a/status/1",
            "python_tiktok_with_legacy_fallback",
            counted_python_success,
            "succeeded",
            None,
            0,
            1,
        ),
        (
            "https://x.com/a/status/1",
            "python",
            counted_python_success,
            "failed",
            "unsupported_platform",
            0,
            0,
        ),
        (
            "https://www.instagram.com/p/code_001/",
            "python_tiktok_with_legacy_fallback",
            counted_python_success,
            "succeeded",
            None,
            1,
            0,
        ),
        (
            "https://www.instagram.com/p/code_001/",
            "python_tiktok_with_legacy_fallback",
            request_blocked_python_failure,
            "succeeded",
            None,
            1,
            1,
        ),
        (
            "https://www.instagram.com/p/code_001/",
            "python",
            counted_python_success,
            "succeeded",
            None,
            1,
            0,
        ),
```

In `tests/acquisition/test_models.py`, add next to the other `_v3` tests:

```python
def test_v3_report_accepts_an_instagram_source() -> None:
    report = _v3(
        source={"platform": "instagram", "canonical_url": "https://www.instagram.com/p/code_001/"}
    )
    assert report.source.platform == "instagram"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_platforms.py tests/acquisition/test_models.py tests/workflows/test_source_investigation.py -q`
Expected: FAIL — the Instagram rows report `legacy`, `platform_of` returns `None`, and the
model rejects `platform="instagram"`.

- [ ] **Step 4: Implement**

`platforms.py`:

```python
PYTHON_PLATFORM_HOSTS: dict[str, frozenset[str]] = {
    "tiktok": frozenset({"tiktok.com", "vm.tiktok.com", "vt.tiktok.com"}),
    "threads": frozenset({"threads.net", "threads.com"}),
    "instagram": frozenset({"instagram.com"}),
}
```

`models.py:209`:

```python
    platform: Literal["tiktok", "threads", "instagram"]
```

- [ ] **Step 5: Confirm no other Instagram-as-legacy assumption remains**

Run: `rg -n -i "instagram" python/src python/tests --glob '!**/fixtures/**'`
Expected: hits only in the files edited above (and legacy Scout wiring that routes by mode,
which stays unchanged). Any other test using Instagram as the "legacy" example moves to
`https://x.com/a/status/1` the same way.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition tests/activities/test_source_investigation.py tests/workflows/test_source_investigation.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/platforms.py python/src/thoth_control_plane/acquisition/models.py python/tests/acquisition/test_platforms.py python/tests/acquisition/test_registry.py python/tests/acquisition/test_models.py python/tests/activities/test_source_investigation.py python/tests/workflows/test_source_investigation.py
git commit -m "feat(acquisition): route instagram urls to the python kernel"
```

---

### Task 2: Instagram adapter (URL identity and parsing)

**Files:**
- Modify: `python/src/thoth_control_plane/acquisition/adapters/threads.py:55-74,133-143`
- Create: `python/src/thoth_control_plane/acquisition/adapters/instagram.py`
- Test: `python/tests/acquisition/test_instagram_adapter.py`

**Interfaces:**
- Consumes: `PYTHON_PLATFORM_HOSTS["instagram"]` (Task 1).
- Produces:
  - `threads._match_safe_path(url, pattern, platform="threads", error=ThreadsUrlError) -> re.Match[str]`
  - `threads._widest(candidates: object) -> str | None`
  - `instagram.CANONICAL_BASE = "https://www.instagram.com"`, `CODE`, `HANDLE`, `POST_PATH`, `SHARE_PATH`
  - `InstagramUrlError(ValueError)`
  - `InstagramPostIdentity(canonical_url: HttpUrl, post_id: str)`
  - `InstagramParse(post: SourcePost, media: list[ResolvedMedia], comments: list[ReportComment], dropped_comments: int = 0)`
  - `canonicalize_instagram_post_url(url: str) -> InstagramPostIdentity`
  - `canonical_instagram_share_url(url: str) -> str`
  - `find_instagram_media(roots: Iterable[object], code: str) -> tuple[dict[str, Any], dict[str, Any] | None] | None`
  - `login_required(roots: Iterable[object]) -> bool`
  - `engagement_of(node: dict[str, Any]) -> dict[str, int]`
  - `parse_post(roots: Iterable[object], identity: InstagramPostIdentity) -> InstagramParse | None`

- [ ] **Step 1: Write the failing tests**

Create `python/tests/acquisition/test_instagram_adapter.py`:

```python
"""Instagram URL identity and pure parsing of anonymous page JSON."""

from __future__ import annotations

from typing import Any

import pytest

from thoth_control_plane.acquisition.adapters.instagram import (
    InstagramUrlError,
    canonical_instagram_share_url,
    canonicalize_instagram_post_url,
    login_required,
    parse_post,
)

CANONICAL = "https://www.instagram.com/p/code_001/"
IDENTITY = canonicalize_instagram_post_url(CANONICAL)


def _post(**extra: Any) -> dict[str, Any]:
    return {
        "code": "code_001",
        "pk": "3000000000000000001",
        "user": {"username": "user_001"},
        "caption": {"text": "hello world"},
        "taken_at": 1_700_000_000,
        "like_count": 1_200,
        "comment_count": 34,
        "media_type": 1,
        "image_versions2": {
            "candidates": [
                {"url": "https://img.example.test/small.jpg", "width": 320, "height": 320},
                {"url": "https://img.example.test/big.jpg", "width": 1080, "height": 1080},
            ]
        },
        **extra,
    }


def _raw_comment(n: int, **extra: Any) -> dict[str, Any]:
    return {
        "pk": str(18_000_000_000_000_000 + n),
        "text": f"comment {n}",
        "comment_like_count": n,
        "user": {"username": f"fan_{n:03d}"},
        **extra,
    }


def _connection(*nodes: object) -> dict[str, Any]:
    return {"edges": [{"node": node} for node in nodes]}


def _doc(post: dict[str, Any], connection: dict[str, Any] | None = None) -> dict[str, Any]:
    media: dict[str, Any] = {"if_not_gated_logged_out": post}
    if connection is not None:
        media["comments_connection"] = connection
    return {"require": [{"data": {"xig_polaris_media": media}}]}


def _urls(parsed) -> list[str]:
    return [item.ephemeral_url.get_secret_value() for item in parsed.media]


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/p/code_001/",
        "https://instagram.com/reel/code_001",
        "https://m.instagram.com/reels/code_001/?igsh=abc",
        "https://www.instagram.com/tv/code_001/#frag",
        "https://www.instagram.com/user_001/reel/code_001/",
        "https://www.instagram.com/user_001/p/code_001",
        "https://WWW.Instagram.COM./p/code_001/",
    ],
)
def test_post_url_shapes_canonicalize(url: str) -> None:
    identity = canonicalize_instagram_post_url(url)
    assert str(identity.canonical_url) == CANONICAL
    assert identity.post_id == "code_001"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/user_001/",
        "https://instagr.am/p/code_001/",
        "http://www.instagram.com/p/code_001/",
        "https://www.instagram.com/p/bad*code/",
        "https://www.instagram.com:8443/p/code_001/",
        "https://user@www.instagram.com/p/code_001/",
        "https://notinstagram.com/p/code_001/",
        "https://www.instagram.com/stories/user_001/1234567/",
        "https://www.instagram.com/share/p/tok_001/",
        "https://www.instagram.com/share/tok_001/",
        "https://[::1",
    ],
)
def test_non_post_urls_are_rejected(url: str) -> None:
    with pytest.raises(InstagramUrlError):
        canonicalize_instagram_post_url(url)


@pytest.mark.parametrize(
    ("url", "share"),
    [
        ("https://www.instagram.com/share/tok_001/", "https://www.instagram.com/share/tok_001/"),
        (
            "https://www.instagram.com/share/reel/tok_001?igsh=x",
            "https://www.instagram.com/share/reel/tok_001/",
        ),
        ("https://instagram.com/share/p/tok_001/", "https://www.instagram.com/share/p/tok_001/"),
    ],
)
def test_share_url_shapes_canonicalize(url: str, share: str) -> None:
    assert canonical_instagram_share_url(url) == share


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/share/x/tok_001/",
        "https://www.instagram.com/p/code_001/",
        "http://www.instagram.com/share/tok_001/",
    ],
)
def test_non_share_urls_are_rejected(url: str) -> None:
    with pytest.raises(InstagramUrlError):
        canonical_instagram_share_url(url)


def test_image_post_parses_fields_and_the_widest_candidate() -> None:
    parsed = parse_post([_doc(_post())], IDENTITY)
    assert parsed is not None
    assert parsed.post.post_id == "code_001"
    assert parsed.post.owner_handle == "user_001"
    assert parsed.post.text == "hello world"
    assert parsed.post.published_at == "2023-11-14T22:13:20Z"
    assert parsed.post.engagement == {"like": 1_200, "comment": 34}
    assert [item.kind for item in parsed.media] == ["image"]
    assert _urls(parsed) == ["https://img.example.test/big.jpg"]
    assert parsed.comments == []


def test_video_post_takes_the_widest_video_version() -> None:
    versions = [
        {"url": "https://video.example.test/low.mp4", "width": 480, "height": 854},
        {"url": "https://video.example.test/high.mp4", "width": 720, "height": 1280},
    ]
    parsed = parse_post([_doc(_post(media_type=2, video_versions=versions))], IDENTITY)
    assert parsed is not None
    assert [item.kind for item in parsed.media] == ["video"]
    assert _urls(parsed) == ["https://video.example.test/high.mp4"]


def test_carousel_skips_urlless_items_in_order() -> None:
    carousel = [
        {"image_versions2": {"candidates": [{"url": "https://img.example.test/a.jpg"}]}},
        {"image_versions2": {"candidates": [{"url": "http://img.example.test/insecure.jpg"}]}},
        {"video_versions": [{"url": "https://video.example.test/b.mp4"}]},
        "not a dict",
        {"image_versions2": {"candidates": [{"url": "https://img.example.test/c.jpg"}]}},
    ]
    parsed = parse_post([_doc(_post(media_type=8, carousel_media=carousel))], IDENTITY)
    assert parsed is not None
    assert [item.kind for item in parsed.media] == ["image", "video", "image"]
    assert _urls(parsed) == [
        "https://img.example.test/a.jpg",
        "https://video.example.test/b.mp4",
        "https://img.example.test/c.jpg",
    ]


def test_carousel_is_capped_at_twenty() -> None:
    carousel = [
        {"image_versions2": {"candidates": [{"url": f"https://img.example.test/{n}.jpg"}]}}
        for n in range(25)
    ]
    parsed = parse_post([_doc(_post(carousel_media=carousel))], IDENTITY)
    assert parsed is not None
    assert len(parsed.media) == 20


def test_disabled_counts_give_empty_engagement() -> None:
    parsed = parse_post([_doc(_post(like_and_view_counts_disabled=True))], IDENTITY)
    assert parsed is not None
    assert parsed.post.engagement == {}


def test_null_caption_is_empty_text() -> None:
    parsed = parse_post([_doc(_post(caption=None))], IDENTITY)
    assert parsed is not None
    assert parsed.post.text == ""


def test_comments_parse_in_order_and_cap_at_fifty() -> None:
    comments = [_raw_comment(n) for n in range(1, 56)]
    parsed = parse_post([_doc(_post(), _connection(*comments))], IDENTITY)
    assert parsed is not None
    assert len(parsed.comments) == 50
    first = parsed.comments[0]
    assert (first.comment_id, first.author, first.text, first.likes, first.card) == (
        "18000000000000001",
        "fan_001",
        "comment 1",
        1,
        None,
    )
    assert parsed.dropped_comments == 0


def test_duplicate_comment_pk_keeps_the_first() -> None:
    connection = _connection(_raw_comment(1), _raw_comment(1, text="later copy"))
    parsed = parse_post([_doc(_post(), connection)], IDENTITY)
    assert parsed is not None
    assert [c.text for c in parsed.comments] == ["comment 1"]
    assert parsed.dropped_comments == 1


def test_invalid_comments_are_dropped_and_counted() -> None:
    connection = _connection(
        _raw_comment(1, pk="not-numeric"),
        _raw_comment(2, text="   "),
        _raw_comment(3, text="x" * 2_001),
        _raw_comment(4, user={"username": "bad name"}),
        _raw_comment(5, user=None),
        "not a dict",
        _raw_comment(6),
    )
    parsed = parse_post([_doc(_post(), connection)], IDENTITY)
    assert parsed is not None
    assert [c.author for c in parsed.comments] == ["fan_006"]
    assert parsed.dropped_comments == 6


def test_a_connection_outside_the_post_holder_is_used() -> None:
    loose = {"xig_polaris_media": {"comments_connection": _connection(_raw_comment(1))}}
    parsed = parse_post([_doc(_post()), loose], IDENTITY)
    assert parsed is not None
    assert [c.author for c in parsed.comments] == ["fan_001"]


@pytest.mark.parametrize("user", [{}, {"username": None}, {"username": "bad name"}])
def test_missing_or_invalid_owner_is_no_parse(user: dict[str, Any]) -> None:
    assert parse_post([_doc(_post(user=user))], IDENTITY) is None


def test_other_post_code_is_no_parse() -> None:
    assert parse_post([_doc(_post(code="other_01"))], IDENTITY) is None


def test_login_required_reads_root_documents_only() -> None:
    assert login_required([{"message": "x", "require_login": True, "status": "fail"}])
    assert not login_required([_doc(_post())])
    assert not login_required([{"data": {"require_login": True}}])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_instagram_adapter.py -q`
Expected: FAIL — `ModuleNotFoundError: ... adapters.instagram`.

- [ ] **Step 3: Refactor the Threads helpers**

In `adapters/threads.py`, replace `_match_safe_path` with:

```python
def _match_safe_path(
    url: str,
    pattern: re.Pattern[str],
    platform: str = "threads",
    error: type[ValueError] = ThreadsUrlError,
) -> re.Match[str]:
    """Match `pattern` against the path of a safe https URL on `platform`'s hosts, or raise."""
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        # The bare ValueError embeds the raw offending substring; never chain it.
        raise error("invalid_source_url") from None
    match = pattern.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or bare_host(host) not in PYTHON_PLATFORM_HOSTS[platform]
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or match is None
    ):
        raise error("invalid_source_url")
    return match
```

and replace `_largest_image_url` with:

```python
def _widest(candidates: object) -> str | None:
    """The https URL of the largest-area candidate; the first one wins a tie."""
    best: tuple[int, str] | None = None
    for candidate in candidates if isinstance(candidates, list) else []:
        if not isinstance(candidate, dict) or (url := _https(candidate.get("url"))) is None:
            continue
        area = (_count(candidate.get("width")) or 0) * (_count(candidate.get("height")) or 0)
        if best is None or area > best[0]:
            best = (area, url)
    return best[1] if best else None


def _largest_image_url(item: dict[str, Any]) -> str | None:
    container = item.get("image_versions2")
    return _widest(container.get("candidates") if isinstance(container, dict) else None)
```

- [ ] **Step 4: Write the adapter**

Create `python/src/thoth_control_plane/acquisition/adapters/instagram.py`:

```python
"""SSRF-safe Instagram URL identity and pure parsing of anonymous Instagram page JSON.

An anonymous post page embeds `application/json` scripts; the post is the
`xig_polaris_media.if_not_gated_logged_out` node whose `code` matches, and the first
comment page is its `comments_connection`. Nothing here performs I/O.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from pydantic import HttpUrl

from thoth_control_plane.acquisition.adapters.threads import (
    _largest_image_url,
    _match_safe_path,
    _walk,
    _widest,
)
from thoth_control_plane.acquisition.models import (
    MAX_COMMENTS,
    MAX_MEDIA_ITEMS,
    MAX_POST_TEXT,
    ReportComment,
    ResolvedMedia,
    SourcePost,
)
from thoth_control_plane.acquisition.normalize import _count, _pick, published_at_from_epoch
from thoth_control_plane.domain.models import StrictModel

CANONICAL_BASE = "https://www.instagram.com"
CODE = re.compile(r"[A-Za-z0-9_-]{1,64}")
# An optional `/<user>/` prefix is accepted, except `share/`, which begins a share link.
POST_PATH = re.compile(
    r"^/(?:(?!share/)[A-Za-z0-9._]{1,64}/)?(?:p|reels?|tv)/(?P<code>[A-Za-z0-9_-]{1,64})/?$"
)
SHARE_PATH = re.compile(r"^/share/(?P<kind>(?:reel|p)/)?(?P<token>[A-Za-z0-9_-]{1,64})/?$")
HANDLE = re.compile(r"[A-Za-z0-9._]{1,64}")
MEDIA_KEY = "xig_polaris_media"
ENGAGEMENT_KEYS = {"like": ("like_count",), "comment": ("comment_count",)}


class InstagramUrlError(ValueError):
    """Raised when a URL is not a safe, supported public Instagram post or share URL."""


class InstagramPostIdentity(StrictModel):
    canonical_url: HttpUrl
    post_id: str


class InstagramParse(StrictModel):
    post: SourcePost
    media: list[ResolvedMedia]
    comments: list[ReportComment]
    dropped_comments: int = 0


def canonicalize_instagram_post_url(url: str) -> InstagramPostIdentity:
    """Reduce any accepted Instagram post URL to `https://www.instagram.com/p/<code>/`."""
    code = _match_safe_path(url, POST_PATH, "instagram", InstagramUrlError).group("code")
    return InstagramPostIdentity(canonical_url=f"{CANONICAL_BASE}/p/{code}/", post_id=code)


def canonical_instagram_share_url(url: str) -> str:
    """Reduce an Instagram share link to its token URL; only following it names the post."""
    match = _match_safe_path(url, SHARE_PATH, "instagram", InstagramUrlError)
    return f"{CANONICAL_BASE}/share/{match.group('kind') or ''}{match.group('token')}/"


def find_instagram_media(
    roots: Iterable[object], code: str
) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
    """The post node for `code` and its comment connection (its sibling, else the first seen)."""
    found: tuple[dict[str, Any], dict[str, Any] | None] | None = None
    loose: dict[str, Any] | None = None
    for root in roots:
        for node in _walk(root):
            media = node.get(MEDIA_KEY)
            if not isinstance(media, dict):
                continue
            connection = media.get("comments_connection")
            connection = connection if isinstance(connection, dict) else None
            if loose is None:
                loose = connection
            post = media.get("if_not_gated_logged_out")
            if (
                found is None
                and isinstance(post, dict)
                and post.get("code") == code
                and isinstance(post.get("user"), dict)
            ):
                found = (post, connection)
    if found is None:
        return None
    return found[0], found[1] or loose


def login_required(roots: Iterable[object]) -> bool:
    """Instagram answers a logged-out API or page request with a root `require_login` flag."""
    return any(isinstance(root, dict) and root.get("require_login") is True for root in roots)


def engagement_of(node: dict[str, Any]) -> dict[str, int]:
    if node.get("like_and_view_counts_disabled") is True:
        return {}
    return {
        key: value
        for key, names in ENGAGEMENT_KEYS.items()
        if (value := _pick(node, names)) is not None
    }


def _media_of(node: dict[str, Any]) -> list[ResolvedMedia]:
    carousel = node.get("carousel_media")
    items = carousel if isinstance(carousel, list) and carousel else [node]
    media: list[ResolvedMedia] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if (video := _widest(item.get("video_versions"))) is not None:
            media.append(ResolvedMedia(kind="video", ephemeral_url=video))
        elif (image := _largest_image_url(item)) is not None:
            media.append(ResolvedMedia(kind="image", ephemeral_url=image, media_type=None))
    return media[:MAX_MEDIA_ITEMS]


def _comment(node: object) -> ReportComment | None:
    if not isinstance(node, dict) or not isinstance(node.get("user"), dict):
        return None
    text = node.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        return ReportComment(
            comment_id=str(node.get("pk")),
            author=node["user"].get("username"),
            text=text,
            likes=_count(node.get("comment_like_count")) or 0,
        )
    except ValueError:
        return None


def _comments(connection: dict[str, Any] | None) -> tuple[list[ReportComment], int]:
    edges = connection.get("edges") if connection is not None else None
    comments: list[ReportComment] = []
    seen: set[str] = set()
    dropped = 0
    for edge in edges if isinstance(edges, list) else []:
        if len(comments) == MAX_COMMENTS:
            break
        comment = _comment(edge.get("node") if isinstance(edge, dict) else None)
        if comment is None or comment.comment_id in seen:
            dropped += 1
            continue
        seen.add(comment.comment_id)
        comments.append(comment)
    return comments, dropped


def parse_post(roots: Iterable[object], identity: InstagramPostIdentity) -> InstagramParse | None:
    """Parse the post named by `identity`; None when no document holds it with a valid owner."""
    found = find_instagram_media(roots, identity.post_id)
    if found is None:
        return None
    node, connection = found
    username = node["user"].get("username")
    if not isinstance(username, str) or HANDLE.fullmatch(username) is None:
        return None
    caption = node.get("caption")
    text = caption.get("text") if isinstance(caption, dict) else None
    comments, dropped = _comments(connection)
    return InstagramParse(
        post=SourcePost(
            post_id=identity.post_id,
            owner_handle=username,
            text=text[:MAX_POST_TEXT] if isinstance(text, str) else "",
            published_at=published_at_from_epoch(node.get("taken_at")),
            engagement=engagement_of(node),
        ),
        media=_media_of(node),
        comments=comments,
        dropped_comments=dropped,
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_instagram_adapter.py tests/acquisition/test_threads_adapter.py tests/acquisition/test_threads_service.py tests/acquisition/test_threads_replay.py tests/operations/test_threads_fixture.py -q`
Expected: PASS (Threads tests unchanged and green after the refactor). If a Threads adapter
test file has a different name, run `tests/acquisition -k threads` instead.

- [ ] **Step 6: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/adapters/threads.py python/src/thoth_control_plane/acquisition/adapters/instagram.py python/tests/acquisition/test_instagram_adapter.py
git commit -m "feat(acquisition): add the instagram url and page adapter"
```

---

### Task 3: Instagram request fetcher, identity, and headless cards

**Files:**
- Modify: `python/src/thoth_control_plane/acquisition/threads_service.py:10-17,137-147`
- Create: `python/src/thoth_control_plane/acquisition/instagram_service.py`
- Test: `python/tests/acquisition/test_instagram_service.py`

**Interfaces:**
- Consumes (Task 2): `CANONICAL_BASE`, `POST_PATH`, `SHARE_PATH`, `InstagramPostIdentity`,
  `InstagramUrlError`, `canonical_instagram_share_url`, `canonicalize_instagram_post_url`;
  `ReportComment` from models.
- Produces:
  - `threads_service._await_post_url(landing: list[str], path: re.Pattern[str] = POST_PATH)`
  - `instagram_service.CONTENT_METHOD: Literal["request", "headless"] = "request"`
  - `instagram_service.SHARE_RESOLUTION_METHOD: Literal["request", "headless"] = "request"`
  - `POST_CARD_SELECTOR`, `PROFILE_CARD_SELECTOR`, `DIALOG_CLOSE_SELECTOR`, `COMMENT_ROW_ATTRIBUTE`, `TAG_COMMENTS_JS`
  - `InstagramRequestFetcher(get=None)` with `async fetch(url) -> list[str]` and `async landing(share_url) -> str`, raising `RequestFetchError`
  - `resolve_instagram_identity(source_url, request, headless) -> InstagramPostIdentity` (raises `InstagramUrlError`, `RequestFetchError`, `HeadlessBrowserError`)
  - `CommentTarget(comment_id: str, author: str, prefix: str)` (frozen dataclass)
  - `comment_targets(comments: list[ReportComment]) -> list[CommentTarget]`
  - `InstagramCards(post_png: bytes | None = None, comment_pngs: dict[str, bytes] = {}, profile_png: bytes | None = None, problems: list[str] = [])`
  - `InstagramHeadlessBrowser(session_factory=_default_session_factory)` with
    `async scripts(url) -> list[str]`, `async resolve(share_url) -> str` (both raise
    `HeadlessBrowserError`), `async cards(post_url, profile_url, *, want_post: bool, targets: list[CommentTarget]) -> InstagramCards` (never raises except cancellation), `async close()`

- [ ] **Step 1: Write the failing tests**

Create `python/tests/acquisition/test_instagram_service.py`:

```python
"""Instagram fetcher, identity resolution, and headless cards over injected fakes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from tests.acquisition.png_fixtures import make_png
from thoth_control_plane.acquisition import instagram_service
from thoth_control_plane.acquisition.adapters.instagram import InstagramUrlError
from thoth_control_plane.acquisition.browser import (
    HeadlessBrowserError,
    active_scrapling_session_count,
)
from thoth_control_plane.acquisition.instagram_service import (
    COMMENT_ROW_ATTRIBUTE,
    DIALOG_CLOSE_SELECTOR,
    POST_CARD_SELECTOR,
    PROFILE_CARD_SELECTOR,
    TAG_COMMENTS_JS,
    CommentTarget,
    InstagramHeadlessBrowser,
    InstagramRequestFetcher,
    RequestFetchError,
    comment_targets,
    resolve_instagram_identity,
)
from thoth_control_plane.acquisition.models import AcquisitionReason, ReportComment

POST = "https://www.instagram.com/p/code_001/"
PROFILE = "https://www.instagram.com/user_001/"
SHARE = "https://www.instagram.com/share/reel/tok_001/"
C1 = "18000000000000000001"


def _response(status: int = 200, url: str = POST):
    return SimpleNamespace(
        status=status, url=url, css=lambda selector: SimpleNamespace(getall=lambda: ["{}", ""])
    )


def _get(result: Any):
    async def get(url: str, **kwargs: Any):
        if isinstance(result, Exception):
            raise result
        return result

    return get


@pytest.mark.asyncio
async def test_request_fetcher_returns_script_texts() -> None:
    seen: dict[str, Any] = {}

    async def get(url: str, **kwargs: Any):
        seen.update(kwargs)
        return _response()

    assert await InstagramRequestFetcher(get).fetch(POST) == ["{}"]
    assert seen["impersonate"] == "chrome"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (_response(status=403), AcquisitionReason.REQUEST_BLOCKED),
        (_response(status=429), AcquisitionReason.REQUEST_BLOCKED),
        (
            _response(url="https://www.instagram.com/accounts/login/?next=%2Fp%2Fx%2F"),
            AcquisitionReason.REQUEST_BLOCKED,
        ),
        (_response(url="https://www.instagram.com/challenge/"), AcquisitionReason.REQUEST_BLOCKED),
        (TimeoutError(), AcquisitionReason.REQUEST_TIMEOUT),
        (RuntimeError("boom"), AcquisitionReason.REQUEST_BLOCKED),
    ],
)
async def test_request_fetcher_classifies_failures(result: Any, reason: AcquisitionReason) -> None:
    with pytest.raises(RequestFetchError) as caught:
        await InstagramRequestFetcher(_get(result)).fetch(POST)
    assert caught.value.reason is reason


@pytest.mark.asyncio
async def test_a_handle_that_starts_with_login_is_not_a_login_wall() -> None:
    fetcher = InstagramRequestFetcher(_get(_response(url="https://www.instagram.com/loginx/")))
    assert await fetcher.fetch("https://www.instagram.com/loginx/") == ["{}"]


@pytest.mark.asyncio
async def test_landing_returns_the_final_url() -> None:
    landing = "https://www.instagram.com/reel/code_001/?igsh=x"
    assert await InstagramRequestFetcher(_get(_response(url=landing))).landing(SHARE) == landing


class _ShareRequest:
    def __init__(self, target: str) -> None:
        self.target, self.calls = target, []

    async def landing(self, share_url: str) -> str:
        self.calls.append(share_url)
        return self.target


class _ShareHeadless:
    def __init__(self, target: str) -> None:
        self.target, self.calls = target, []

    async def resolve(self, share_url: str) -> str:
        self.calls.append(share_url)
        return self.target


@pytest.mark.asyncio
async def test_a_post_url_is_its_own_identity() -> None:
    request, headless = _ShareRequest(POST), _ShareHeadless(POST)
    identity = await resolve_instagram_identity(POST + "?igsh=x", request, headless)
    assert identity.post_id == "code_001"
    assert request.calls == headless.calls == []


@pytest.mark.asyncio
async def test_a_share_link_resolves_through_the_request() -> None:
    request = _ShareRequest("https://www.instagram.com/reel/code_001/?igsh=x")
    headless = _ShareHeadless(POST)
    identity = await resolve_instagram_identity(SHARE + "?igsh=abc", request, headless)
    assert str(identity.canonical_url) == POST
    assert request.calls == [SHARE]
    assert headless.calls == []


@pytest.mark.asyncio
async def test_a_share_link_landing_off_a_post_is_invalid() -> None:
    with pytest.raises(InstagramUrlError):
        await resolve_instagram_identity(SHARE, _ShareRequest(PROFILE), _ShareHeadless(POST))


@pytest.mark.asyncio
async def test_headless_share_resolution_uses_the_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(instagram_service, "SHARE_RESOLUTION_METHOD", "headless")
    request, headless = _ShareRequest(PROFILE), _ShareHeadless(POST)
    identity = await resolve_instagram_identity(SHARE, request, headless)
    assert identity.post_id == "code_001"
    assert request.calls == []
    assert headless.calls == [SHARE]


def test_comment_targets_use_the_first_non_empty_line() -> None:
    comment = ReportComment(
        comment_id=C1,
        author="fan_001",
        text="  \n  a first line that is clearly longer than thirty chars\nsecond",
    )
    assert comment_targets([comment]) == [
        CommentTarget(C1, "fan_001", "a first line that is clearly l")
    ]


def test_the_tagging_script_sets_the_row_attribute() -> None:
    assert COMMENT_ROW_ATTRIBUTE in TAG_COMMENTS_JS


class _Locator:
    def __init__(self, page: _CardPage, selector: str) -> None:
        self.first, self._page, self._selector = self, page, selector

    async def click(self, timeout: int) -> None:
        self._page.clicked.append(self._selector)

    async def scroll_into_view_if_needed(self, timeout: int) -> None:
        return None

    async def screenshot(self, timeout: int) -> bytes:
        self._page.shots.append(self._selector)
        return make_png(400, 200)


class _CardPage:
    def __init__(self, url: str, tagged: list[str] | None = None) -> None:
        self.url, self.tagged = url, tagged or []
        self.clicked: list[str] = []
        self.shots: list[str] = []
        self.evaluated: list[object] = []

    def locator(self, selector: str) -> _Locator:
        return _Locator(self, selector)

    async def evaluate(self, script: str, arg: object) -> list[str]:
        self.evaluated.append(arg)
        return self.tagged


class _CardActive:
    def __init__(self, pages: dict[str, _CardPage]) -> None:
        self.pages, self.visits = pages, []

    async def fetch(self, url: str, **kwargs: Any):
        self.visits.append(url)
        page = self.pages[url]
        if kwargs.get("page_action") is not None:
            await kwargs["page_action"](page)
        return SimpleNamespace(
            url=page.url, css=lambda selector: SimpleNamespace(getall=lambda: ["{}", ""])
        )


class _Session:
    def __init__(self, active: Any = None, enter_error: Exception | None = None) -> None:
        self.active, self.enter_error, self.exited = active, enter_error, 0

    async def __aenter__(self):
        if self.enter_error is not None:
            raise self.enter_error
        return self.active

    async def __aexit__(self, *exc: object) -> None:
        self.exited += 1


def _browser(pages: dict[str, _CardPage]) -> tuple[InstagramHeadlessBrowser, _Session]:
    session = _Session(_CardActive(pages))
    return InstagramHeadlessBrowser(lambda **kwargs: session), session


TARGETS = [CommentTarget(C1, "fan_001", "first comment")]


@pytest.mark.asyncio
async def test_cards_crop_post_comments_and_profile_in_one_session() -> None:
    post_page = _CardPage(POST, tagged=[C1, "99999999"])
    profile_page = _CardPage(PROFILE)
    browser, session = _browser({POST: post_page, PROFILE: profile_page})

    cards = await browser.cards(POST, PROFILE, want_post=True, targets=TARGETS)
    await browser.close()

    assert cards.post_png is not None
    assert list(cards.comment_pngs) == [C1]
    assert cards.profile_png is not None
    assert cards.problems == []
    assert post_page.clicked == [DIALOG_CLOSE_SELECTOR]
    assert post_page.shots == [POST_CARD_SELECTOR, f'[{COMMENT_ROW_ATTRIBUTE}="{C1}"]']
    assert post_page.evaluated == [[{"comment_id": C1, "author": "fan_001", "prefix": "first comment"}]]
    assert profile_page.shots == [PROFILE_CARD_SELECTOR]
    assert session.exited == 1
    assert active_scrapling_session_count() == 0


@pytest.mark.asyncio
async def test_video_post_crops_comments_but_not_the_post() -> None:
    post_page = _CardPage(POST, tagged=[C1])
    browser, _ = _browser({POST: post_page, PROFILE: _CardPage(PROFILE)})
    cards = await browser.cards(POST, PROFILE, want_post=False, targets=TARGETS)
    await browser.close()
    assert cards.post_png is None
    assert POST_CARD_SELECTOR not in post_page.shots
    assert list(cards.comment_pngs) == [C1]


@pytest.mark.asyncio
async def test_nothing_to_crop_on_the_post_skips_its_visit() -> None:
    browser, session = _browser({PROFILE: _CardPage(PROFILE)})
    cards = await browser.cards(POST, PROFILE, want_post=False, targets=[])
    await browser.close()
    assert session.active.visits == [PROFILE]
    assert cards.profile_png is not None


@pytest.mark.asyncio
async def test_a_login_wall_on_the_post_page_is_a_problem_not_a_failure() -> None:
    wall = _CardPage("https://www.instagram.com/accounts/login/?next=x")
    browser, _ = _browser({POST: wall, PROFILE: _CardPage(PROFILE)})
    cards = await browser.cards(POST, PROFILE, want_post=True, targets=TARGETS)
    await browser.close()
    assert cards.post_png is None
    assert cards.comment_pngs == {}
    assert cards.problems == ["headless_blocked"]
    assert cards.profile_png is not None


@pytest.mark.asyncio
async def test_a_browser_that_cannot_start_yields_problems_only() -> None:
    session = _Session(enter_error=TimeoutError())
    browser = InstagramHeadlessBrowser(lambda **kwargs: session)
    cards = await browser.cards(POST, PROFILE, want_post=True, targets=TARGETS)
    await browser.close()
    assert cards.problems == ["headless_timeout", "headless_timeout"]
    assert cards.post_png is cards.profile_png is None
    assert active_scrapling_session_count() == 0


@pytest.mark.asyncio
async def test_scripts_on_a_login_wall_is_blocked() -> None:
    browser, session = _browser({POST: _CardPage("https://www.instagram.com/accounts/login/")})
    with pytest.raises(HeadlessBrowserError) as caught:
        await browser.scripts(POST)
    await browser.close()
    assert caught.value.reason is AcquisitionReason.HEADLESS_BLOCKED
    assert session.exited == 1
    assert active_scrapling_session_count() == 0


@pytest.mark.asyncio
async def test_scripts_returns_the_page_json() -> None:
    browser, _ = _browser({POST: _CardPage(POST)})
    assert await browser.scripts(POST) == ["{}"]
    await browser.close()


class _SharePage:
    def __init__(self, landing: str) -> None:
        self.url, self._landing = SHARE, landing

    async def wait_for_url(self, predicate: Any, timeout: int) -> None:
        self.url = self._landing
        if not predicate(self.url):
            raise TimeoutError()


class _ShareActive:
    def __init__(self, landing: str) -> None:
        self.landing = landing

    async def fetch(self, url: str, **kwargs: Any):
        await kwargs["page_action"](_SharePage(self.landing))
        return SimpleNamespace(url=url)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("landing", "reason"),
    [
        ("https://www.instagram.com/reel/code_001/?igsh=x", None),
        ("https://www.instagram.com/accounts/login/?next=x", AcquisitionReason.HEADLESS_BLOCKED),
        (SHARE, AcquisitionReason.HEADLESS_INCOMPLETE),
    ],
)
async def test_headless_resolve(landing: str, reason: AcquisitionReason | None) -> None:
    session = _Session(_ShareActive(landing))
    browser = InstagramHeadlessBrowser(lambda **kwargs: session)
    try:
        if reason is None:
            assert await browser.resolve(SHARE) == landing
        else:
            with pytest.raises(HeadlessBrowserError) as caught:
                await browser.resolve(SHARE)
            assert caught.value.reason is reason
    finally:
        await browser.close()
    assert session.exited == 1
    assert active_scrapling_session_count() == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_instagram_service.py -q`
Expected: FAIL — `ModuleNotFoundError: ... instagram_service`.

- [ ] **Step 3: Generalize `_await_post_url` in `threads_service.py`**

Add `import re` to the imports and replace `_await_post_url` with:

```python
def _await_post_url(
    landing: list[str], path: re.Pattern[str] = POST_PATH
) -> Callable[[Any], Awaitable[None]]:
    async def wait(page: Any) -> None:
        # A share link redirects client-side; record wherever the page ends up.
        with contextlib.suppress(Exception):
            await page.wait_for_url(
                lambda url: path.fullmatch(urlsplit(url).path) is not None,
                timeout=SHARE_RESOLVE_TIMEOUT_MS,
            )
        landing.append(page.url)

    return wait
```

- [ ] **Step 4: Write `instagram_service.py` (part 1)**

Create `python/src/thoth_control_plane/acquisition/instagram_service.py`:

```python
"""Instagram single-post acquisition: content by one method, first-page comments, and
best-effort headless cards (post, one per comment, profile).

`CONTENT_METHOD` and `SHARE_RESOLUTION_METHOD` are decided once from the Stage 3b
golden-fixture comparison. There is no runtime fallback between methods; the legacy
fallback lives in the workflow. Cards always come from one anonymous headless session.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal
from urllib.parse import urlsplit

from thoth_control_plane.acquisition.adapters.instagram import (
    POST_PATH,
    SHARE_PATH,
    InstagramPostIdentity,
    InstagramUrlError,
    canonical_instagram_share_url,
    canonicalize_instagram_post_url,
)
from thoth_control_plane.acquisition.browser import (
    FETCH_OPTIONS,
    HeadlessBrowserError,
    _classify_fetch_error,
    _decrement_active_sessions,
    _default_session_factory,
    _increment_active_sessions,
    _is_timeout,
)
from thoth_control_plane.acquisition.models import AcquisitionReason, ReportComment
from thoth_control_plane.acquisition.threads_service import (
    REQUEST_OPTIONS,
    SCRIPT_SELECTOR,
    RequestFetchError,
    _await_post_url,
    _scrapling_get,
)

# Provisional until the Stage 3b capture decides them (restricted evidence in the checkpoint).
CONTENT_METHOD: Literal["request", "headless"] = "request"
SHARE_RESOLUTION_METHOD: Literal["request", "headless"] = "request"
DIALOG_CLOSE_SELECTOR = 'div[role=dialog] svg[aria-label="Close"]'
POST_CARD_SELECTOR = "main > div > div"
PROFILE_CARD_SELECTOR = "header"
COMMENT_ROW_ATTRIBUTE = "data-thoth-comment"
COMMENT_PREFIX_CHARS = 30
DIALOG_TIMEOUT_MS = 3_000
LOGIN_PATHS = ("/accounts/login", "/login", "/challenge")
# Tags each matched comment row; targets arrive as the evaluate argument, never interpolated.
TAG_COMMENTS_JS = """
(targets) => {
  const tagged = [];
  const spans = Array.from(document.querySelectorAll("span"));
  for (const target of targets) {
    const link = `a[href="/${CSS.escape(target.author)}/"]`;
    for (const span of spans) {
      if (!(span.textContent || "").trim().startsWith(target.prefix)) continue;
      let row = span;
      while (row && row !== document.body && !(row.querySelector(link) && row.querySelector("img"))) {
        row = row.parentElement;
      }
      if (!row || row === document.body || row.hasAttribute("data-thoth-comment")) continue;
      row.setAttribute("data-thoth-comment", target.comment_id);
      tagged.push(target.comment_id);
      break;
    }
  }
  return tagged;
}
"""


def _blocked(url: object) -> bool:
    path = urlsplit(str(url)).path
    return any(path == prefix or path.startswith(prefix + "/") for prefix in LOGIN_PATHS)


class InstagramRequestFetcher:
    """Plain impersonated HTTP GET; returns embedded JSON script texts or a landing URL."""

    def __init__(self, get: Callable[..., Awaitable[Any]] | None = None) -> None:
        self._get = get or _scrapling_get

    async def _response(self, url: str) -> Any:
        try:
            response = await self._get(url, **REQUEST_OPTIONS)
        except Exception as error:
            reason = (
                AcquisitionReason.REQUEST_TIMEOUT
                if _is_timeout(error)
                else AcquisitionReason.REQUEST_BLOCKED
            )
            raise RequestFetchError(reason) from None
        if getattr(response, "status", None) != 200 or _blocked(response.url):
            raise RequestFetchError(AcquisitionReason.REQUEST_BLOCKED)
        return response

    async def fetch(self, url: str) -> list[str]:
        response = await self._response(url)
        return [text for text in response.css(SCRIPT_SELECTOR).getall() if text]

    async def landing(self, share_url: str) -> str:
        """Follow a share link's safe redirects; return where the request ended up."""
        return str((await self._response(share_url)).url)


async def resolve_instagram_identity(
    source_url: str, request: Any, headless: Any
) -> InstagramPostIdentity:
    """A post URL is its own identity; a share link is followed once by the chosen method."""
    try:
        return canonicalize_instagram_post_url(source_url)
    except InstagramUrlError:
        share_url = canonical_instagram_share_url(source_url)
    if SHARE_RESOLUTION_METHOD == "request":
        landing = await request.landing(share_url)
    else:
        landing = await headless.resolve(share_url)
    return canonicalize_instagram_post_url(landing)


@dataclass(frozen=True)
class CommentTarget:
    comment_id: str
    author: str
    prefix: str


def comment_targets(comments: list[ReportComment]) -> list[CommentTarget]:
    targets: list[CommentTarget] = []
    for comment in comments:
        line = next((part.strip() for part in comment.text.splitlines() if part.strip()), "")
        targets.append(
            CommentTarget(comment.comment_id, comment.author, line[:COMMENT_PREFIX_CHARS])
        )
    return targets


@dataclass
class InstagramCards:
    post_png: bytes | None = None
    comment_pngs: dict[str, bytes] = field(default_factory=dict)
    profile_png: bytes | None = None
    problems: list[str] = field(default_factory=list)


async def _dismiss(page: Any) -> None:
    # The anonymous sign-up dialog covers the page; a missing dialog is fine.
    with contextlib.suppress(Exception):
        await page.locator(DIALOG_CLOSE_SELECTOR).first.click(timeout=DIALOG_TIMEOUT_MS)


async def _crop(page: Any, selector: str) -> bytes | None:
    with contextlib.suppress(Exception):
        element = page.locator(selector).first
        await element.scroll_into_view_if_needed(timeout=5_000)
        return await element.screenshot(timeout=10_000)
    return None


def _on_post(
    cards: InstagramCards, want_post: bool, targets: list[CommentTarget]
) -> Callable[[Any], Awaitable[None]]:
    async def action(page: Any) -> None:
        if _blocked(page.url):
            cards.problems.append(AcquisitionReason.HEADLESS_BLOCKED.value)
            return
        await _dismiss(page)
        if want_post:
            cards.post_png = await _crop(page, POST_CARD_SELECTOR)
        if not targets:
            return
        tagged: object = []
        with contextlib.suppress(Exception):
            tagged = await page.evaluate(TAG_COMMENTS_JS, [asdict(t) for t in targets])
        known = {target.comment_id for target in targets}
        for comment_id in tagged if isinstance(tagged, list) else []:
            # Only ids we sent (validated numeric) ever reach a selector.
            if comment_id in known and comment_id not in cards.comment_pngs:
                png = await _crop(page, f'[{COMMENT_ROW_ATTRIBUTE}="{comment_id}"]')
                if png is not None:
                    cards.comment_pngs[comment_id] = png

    return action


def _on_profile(cards: InstagramCards) -> Callable[[Any], Awaitable[None]]:
    async def action(page: Any) -> None:
        if _blocked(page.url):
            cards.problems.append(AcquisitionReason.HEADLESS_BLOCKED.value)
            return
        await _dismiss(page)
        cards.profile_png = await _crop(page, PROFILE_CARD_SELECTOR)

    return action


class InstagramHeadlessBrowser:
    """One lazily opened stealthy session for share resolution, page JSON, and card crops."""

    def __init__(self, session_factory: Callable[..., Any] = _default_session_factory) -> None:
        self._session_factory = session_factory
        self._session: Any | None = None
        self._active: Any | None = None

    async def _open(self) -> Any:
        if self._active is None:
            session = self._session_factory(headless=True, max_pages=1)
            try:
                active = await session.__aenter__()
            except Exception as error:
                raise HeadlessBrowserError(_classify_fetch_error(error)) from None
            self._session, self._active = session, active
            _increment_active_sessions()
        return self._active

    async def _visit(self, url: str, action: Callable[[Any], Awaitable[None]] | None = None):
        active = await self._open()
        try:
            return await active.fetch(url, page_action=action, **FETCH_OPTIONS)
        except Exception as error:
            raise HeadlessBrowserError(_classify_fetch_error(error)) from None

    async def scripts(self, url: str) -> list[str]:
        response = await self._visit(url)
        if _blocked(response.url):
            raise HeadlessBrowserError(AcquisitionReason.HEADLESS_BLOCKED)
        return [text for text in response.css(SCRIPT_SELECTOR).getall() if text]

    async def resolve(self, share_url: str) -> str:
        landing: list[str] = []
        await self._visit(share_url, _await_post_url(landing, POST_PATH))
        if landing and _blocked(landing[0]):
            raise HeadlessBrowserError(AcquisitionReason.HEADLESS_BLOCKED)
        if not landing or SHARE_PATH.fullmatch(urlsplit(landing[0]).path):
            # The client-side redirect never happened in time; a retry may still land.
            raise HeadlessBrowserError(AcquisitionReason.HEADLESS_INCOMPLETE)
        return landing[0]

    async def _card_visit(
        self, url: str, action: Callable[[Any], Awaitable[None]], cards: InstagramCards
    ) -> None:
        try:
            await self._visit(url, action)
        except HeadlessBrowserError as error:
            cards.problems.append(error.reason.value)

    async def cards(
        self,
        post_url: str,
        profile_url: str,
        *,
        want_post: bool,
        targets: list[CommentTarget],
    ) -> InstagramCards:
        """Best effort: every failure lands in `problems`; only cancellation propagates."""
        cards = InstagramCards()
        if want_post or targets:
            await self._card_visit(post_url, _on_post(cards, want_post, targets), cards)
        await self._card_visit(profile_url, _on_profile(cards), cards)
        return cards

    async def close(self) -> None:
        session, self._session, self._active = self._session, None, None
        if session is None:
            return
        try:
            await session.__aexit__(None, None, None)
        except Exception:
            pass
        finally:
            _decrement_active_sessions()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_instagram_service.py tests/acquisition/test_threads_service.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/threads_service.py python/src/thoth_control_plane/acquisition/instagram_service.py python/tests/acquisition/test_instagram_service.py
git commit -m "feat(acquisition): add instagram fetcher, share resolution, and cards"
```

---

### Task 4: InstagramAcquirer and registry

**Files:**
- Modify: `python/src/thoth_control_plane/acquisition/threads_service.py:286-318,349-354`
- Modify: `python/src/thoth_control_plane/acquisition/instagram_service.py`
- Modify: `python/src/thoth_control_plane/acquisition/registry.py`
- Test: `python/tests/acquisition/test_instagram_acquirer.py`, `python/tests/acquisition/test_registry.py`

**Interfaces:**
- Consumes (Tasks 2–3): `parse_post`, `login_required`, `json_roots`, `CANONICAL_BASE`,
  `InstagramParse`, `resolve_instagram_identity`, `comment_targets`, `InstagramCards`,
  `InstagramRequestFetcher`, `InstagramHeadlessBrowser`.
- Produces:
  - `threads_service.materialize_media(materializer, media: list[ResolvedMedia], name: str, workflow_id: str, strategy: AcquisitionStrategy, artifact_root: Path) -> list[MaterializedMedia]`
  - `InstagramAcquirer(request_fetcher, headless, materializer)` with
    `async inspect(*, workflow_id, source_url, artifact_root) -> AcquisitionResult`
  - `acquirer_for(<instagram url>)` returns an `InstagramAcquirer`.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/acquisition/test_instagram_acquirer.py`:

```python
"""Instagram acquisition over injected fakes: no network, no Scrapling."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.acquisition.png_fixtures import make_png
from thoth_control_plane.acquisition import instagram_service
from thoth_control_plane.acquisition.browser import HeadlessBrowserError
from thoth_control_plane.acquisition.instagram_service import (
    InstagramAcquirer,
    InstagramCards,
    InstagramRequestFetcher,
    RequestFetchError,
)
from thoth_control_plane.acquisition.materializer import MediaMaterializationError
from thoth_control_plane.acquisition.models import (
    AcquisitionReason,
    AcquisitionStrategy,
    MaterializedMedia,
)

URL = "https://www.instagram.com/p/code_001/?igsh=abc"
CANONICAL = "https://www.instagram.com/p/code_001/"
SHARE_URL = "https://www.instagram.com/share/p/tok_001/"
WF = "wf_instagram_001"
C1, C2 = "18000000000000000001", "18000000000000000002"


def _image(n: int) -> dict[str, Any]:
    return {
        "image_versions2": {
            "candidates": [{"url": f"https://img.example.test/{n}.jpg", "width": 9, "height": 9}]
        }
    }


def _video(n: int) -> dict[str, Any]:
    return {
        "video_versions": [
            {"url": f"https://video.example.test/{n}.mp4", "width": 9, "height": 16}
        ]
    }


def _node(**extra: Any) -> dict[str, Any]:
    return {
        "code": "code_001",
        "pk": "3000000000000000001",
        "user": {"username": "user_001"},
        "caption": {"text": "hello world"},
        "taken_at": 1_700_000_000,
        "like_count": 1_200,
        "comment_count": 2,
        **_image(0),
        **extra,
    }


def _comment(pk: str, text: str, author: str) -> dict[str, Any]:
    return {"pk": pk, "text": text, "comment_like_count": 3, "user": {"username": author}}


COMMENTS = (_comment(C1, "first comment here", "fan_001"), _comment(C2, "second", "fan_002"))


def _texts(node: dict[str, Any], comments: tuple[dict[str, Any], ...] = COMMENTS) -> list[str]:
    media = {
        "if_not_gated_logged_out": node,
        "comments_connection": {"edges": [{"node": c} for c in comments]},
    }
    return [json.dumps({"require": [{"data": {"xig_polaris_media": media}}]})]


class FakeRequest:
    def __init__(
        self,
        texts: list[str] | None = None,
        error: AcquisitionReason | None = None,
        landing: str | AcquisitionReason = CANONICAL,
    ) -> None:
        self.texts, self.error, self.landing_to, self.calls = texts or [], error, landing, 0
        self.landed: list[str] = []

    async def fetch(self, url: str) -> list[str]:
        self.calls += 1
        if self.error is not None:
            raise RequestFetchError(self.error)
        return self.texts

    async def landing(self, share_url: str) -> str:
        self.landed.append(share_url)
        if isinstance(self.landing_to, AcquisitionReason):
            raise RequestFetchError(self.landing_to)
        return self.landing_to


class FakeHeadless:
    def __init__(self, cards: InstagramCards | None = None, texts: list[str] | None = None):
        self.result, self.texts = cards or InstagramCards(), texts or []
        self.card_calls: list[dict[str, Any]] = []
        self.script_calls, self.closed = 0, 0

    async def scripts(self, url: str) -> list[str]:
        self.script_calls += 1
        return self.texts

    async def resolve(self, share_url: str) -> str:
        raise HeadlessBrowserError(AcquisitionReason.HEADLESS_INCOMPLETE)

    async def cards(self, post_url: str, profile_url: str, *, want_post: bool, targets: list):
        self.card_calls.append(
            {"post": post_url, "profile": profile_url, "want_post": want_post, "targets": targets}
        )
        return self.result

    async def close(self) -> None:
        self.closed += 1


class FakeMaterializer:
    def __init__(self, fail_at: int | None = None) -> None:
        self.fail_at = fail_at

    async def materialize(
        self, candidate, destination, relative_location, strategy, *, media_id="media_1", index=1
    ):
        if index == self.fail_at:
            raise MediaMaterializationError()
        video = candidate.kind == "video"
        suffix = ".mp4" if video else ".jpg"
        destination.with_suffix(suffix).parent.mkdir(parents=True, exist_ok=True)
        destination.with_suffix(suffix).write_bytes(b"x")
        return MaterializedMedia(
            media_id=media_id,
            kind=candidate.kind,
            index=index,
            location=relative_location.with_suffix(suffix),
            media_type="video/mp4" if video else "image/jpeg",
            bytes=20_000 if video else 5_000,
            checksum="sha256:" + "0" * 64,
            acquisition_strategy=strategy,
        )


def _cards(**overrides: Any) -> InstagramCards:
    values = {
        "post_png": make_png(400, 200),
        "comment_pngs": {C1: make_png(400, 80)},
        "profile_png": make_png(400, 200),
    }
    return InstagramCards(**{**values, **overrides})


async def _inspect(tmp_path: Path, request, headless, materializer=None, url: str = URL):
    acquirer = InstagramAcquirer(request, headless, materializer or FakeMaterializer())
    return await acquirer.inspect(workflow_id=WF, source_url=url, artifact_root=tmp_path)


@pytest.mark.asyncio
async def test_image_post_report_carries_comments_and_cards(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    headless = FakeHeadless(_cards())
    result = await _inspect(tmp_path, FakeRequest(_texts(_node())), headless)

    report = result.report
    assert report is not None
    assert report.source.platform == "instagram"
    assert str(report.source.canonical_url) == CANONICAL
    assert report.post.owner_handle == "user_001"
    assert [item.kind for item in report.media] == ["image"]
    assert [c.comment_id for c in report.comments] == [C1, C2]
    assert str(report.comments[0].card.location).endswith(f"cards/comment-{C1}.png")
    assert report.comments[1].card is None
    assert str(report.post_card.location).endswith("cards/post.png")
    assert str(report.profile_card.location).endswith("cards/profile.png")
    assert (tmp_path / str(report.post_card.location)).is_file()
    assert report.outcome.attempts[0].strategy is AcquisitionStrategy.SCRAPLING_REQUEST
    call = headless.card_calls[0]
    assert (call["post"], call["profile"], call["want_post"]) == (
        CANONICAL,
        "https://www.instagram.com/user_001/",
        True,
    )
    assert [t.comment_id for t in call["targets"]] == [C1, C2]
    assert headless.closed == 1
    assert "instagram.com" not in caplog.text
    assert "hello world" not in caplog.text
    assert "user_001" not in caplog.text


@pytest.mark.asyncio
async def test_video_post_asks_for_no_post_card(tmp_path: Path) -> None:
    node = _node(media_type=2, **_video(0))
    headless = FakeHeadless(_cards(post_png=None))
    result = await _inspect(tmp_path, FakeRequest(_texts(node)), headless)
    assert result.report is not None
    assert [item.kind for item in result.report.media] == ["video"]
    assert headless.card_calls[0]["want_post"] is False
    assert result.report.post_card is None


@pytest.mark.asyncio
async def test_carousel_with_a_video_asks_for_no_post_card(tmp_path: Path) -> None:
    node = _node(carousel_media=[_image(1), _video(2)])
    headless = FakeHeadless(_cards(post_png=None))
    result = await _inspect(tmp_path, FakeRequest(_texts(node)), headless)
    assert result.report is not None
    assert [item.kind for item in result.report.media] == ["image", "video"]
    assert headless.card_calls[0]["want_post"] is False


@pytest.mark.asyncio
async def test_a_flat_card_is_rejected_and_absent(tmp_path: Path) -> None:
    headless = FakeHeadless(_cards(post_png=make_png(400, 200, flat=True)))
    result = await _inspect(tmp_path, FakeRequest(_texts(_node())), headless)
    assert result.report is not None
    assert result.report.post_card is None
    assert result.report.profile_card is not None


@pytest.mark.asyncio
async def test_card_problems_still_give_a_report(tmp_path: Path) -> None:
    headless = FakeHeadless(InstagramCards(problems=["headless_timeout", "headless_timeout"]))
    result = await _inspect(tmp_path, FakeRequest(_texts(_node())), headless)
    report = result.report
    assert report is not None
    assert report.post_card is report.profile_card is None
    assert [c.card for c in report.comments] == [None, None]
    assert len(report.outcome.attempts) == 1


@pytest.mark.asyncio
async def test_a_blocked_request_is_retryable_and_skips_cards(tmp_path: Path) -> None:
    headless = FakeHeadless()
    result = await _inspect(
        tmp_path, FakeRequest(error=AcquisitionReason.REQUEST_BLOCKED), headless
    )
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("request_blocked", True)
    assert headless.card_calls == []
    assert headless.closed == 1


@pytest.mark.asyncio
async def test_require_login_is_request_blocked(tmp_path: Path) -> None:
    texts = [json.dumps({"message": "x", "require_login": True, "status": "fail"})]
    result = await _inspect(tmp_path, FakeRequest(texts), FakeHeadless())
    assert result.failure is not None
    assert result.failure.code == "request_blocked"


@pytest.mark.asyncio
async def test_a_missing_post_node_is_request_incomplete(tmp_path: Path) -> None:
    result = await _inspect(tmp_path, FakeRequest(_texts(_node(code="other_01"))), FakeHeadless())
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("request_incomplete", True)


@pytest.mark.asyncio
async def test_missing_owner_is_request_incomplete(tmp_path: Path) -> None:
    result = await _inspect(tmp_path, FakeRequest(_texts(_node(user={}))), FakeHeadless())
    assert result.failure is not None
    assert result.failure.code == "request_incomplete"


@pytest.mark.asyncio
async def test_whitespace_only_post_without_media_is_no_content(tmp_path: Path) -> None:
    node = _node(caption={"text": "   "}, image_versions2=None)
    result = await _inspect(tmp_path, FakeRequest(_texts(node)), FakeHeadless())
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("no_content", False)


@pytest.mark.asyncio
async def test_an_invalid_url_fails_before_any_fetch(tmp_path: Path) -> None:
    request = FakeRequest(_texts(_node()))
    result = await _inspect(
        tmp_path, request, FakeHeadless(), url="https://www.instagram.com/user_001/"
    )
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("invalid_source_url", False)
    assert request.calls == 0


@pytest.mark.asyncio
async def test_share_link_landing_on_the_login_wall_is_request_blocked(tmp_path: Path) -> None:
    async def get(url: str, **kwargs: Any):
        return SimpleNamespace(
            status=200,
            url="https://www.instagram.com/accounts/login/?next=%2Fshare%2Fp%2Ftok_001%2F",
            css=lambda selector: SimpleNamespace(getall=lambda: []),
        )

    result = await _inspect(tmp_path, InstagramRequestFetcher(get), FakeHeadless(), url=SHARE_URL)
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("request_blocked", True)


@pytest.mark.asyncio
async def test_share_link_resolves_before_the_content_fetch(tmp_path: Path) -> None:
    request = FakeRequest(
        _texts(_node()), landing="https://www.instagram.com/reel/code_001/?igsh=x"
    )
    result = await _inspect(tmp_path, request, FakeHeadless(_cards()), url=SHARE_URL)
    assert result.report is not None
    assert request.landed == [SHARE_URL]
    assert str(result.report.source.canonical_url) == CANONICAL


@pytest.mark.asyncio
async def test_share_link_landing_off_a_post_is_invalid(tmp_path: Path) -> None:
    request = FakeRequest(landing="https://www.instagram.com/user_001/")
    result = await _inspect(tmp_path, request, FakeHeadless(), url=SHARE_URL)
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("invalid_source_url", False)
    assert request.calls == 0


@pytest.mark.asyncio
async def test_mid_carousel_failure_leaves_no_orphans_and_no_cards(tmp_path: Path) -> None:
    node = _node(carousel_media=[_image(1), _image(2), _image(3)])
    headless = FakeHeadless(_cards())
    result = await _inspect(
        tmp_path, FakeRequest(_texts(node)), headless, FakeMaterializer(fail_at=2)
    )
    assert result.failure is not None
    assert result.failure.code == "media_validation_failed"
    assert headless.card_calls == []
    media_dir = tmp_path / "reports" / WF / "media"
    assert not media_dir.exists() or list(media_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_headless_content_method_uses_the_browser_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(instagram_service, "CONTENT_METHOD", "headless")
    request = FakeRequest()
    headless = FakeHeadless(_cards(), texts=_texts(_node()))
    result = await _inspect(tmp_path, request, headless)
    assert result.report is not None
    assert request.calls == 0
    assert headless.script_calls == 1
    assert result.report.outcome.attempts[0].strategy is AcquisitionStrategy.SCRAPLING_HEADLESS


class _HangingHeadless(FakeHeadless):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()

    async def cards(self, *args: Any, **kwargs: Any):
        self.started.set()
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_cancellation_during_cards_still_closes_the_browser(tmp_path: Path) -> None:
    headless = _HangingHeadless()
    task = asyncio.create_task(_inspect(tmp_path, FakeRequest(_texts(_node())), headless))
    await headless.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert headless.closed == 1
```

In `tests/acquisition/test_registry.py`, add the import
`from thoth_control_plane.acquisition.instagram_service import InstagramAcquirer` and, inside
the existing `async with` block after the Threads assertion:

```python
        instagram = acquirer_for(
            "https://www.instagram.com/p/code_001/", client=client, materializer=materializer
        )
        assert isinstance(instagram, InstagramAcquirer)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_instagram_acquirer.py tests/acquisition/test_registry.py -q`
Expected: FAIL — `ImportError: cannot import name 'InstagramAcquirer'`.

- [ ] **Step 3: Extract `materialize_media` in `threads_service.py`**

Add `ResolvedMedia` to the models import. Delete the `ThreadsAcquirer._materialize_all` method
and add this module-level function above `class ThreadsAcquirer`:

```python
async def materialize_media(
    materializer: MediaMaterializer,
    media: list[ResolvedMedia],
    name: str,
    workflow_id: str,
    strategy: AcquisitionStrategy,
    artifact_root: Path,
) -> list[MaterializedMedia]:
    """Materialize `media` in order as `<name>-<index>`; a failure removes what this wrote."""
    done: list[MaterializedMedia] = []
    try:
        for index, candidate in enumerate(media[:MAX_MEDIA_ITEMS], start=1):
            location = PurePosixPath("reports") / workflow_id / "media" / f"{name}-{index}"
            done.append(
                await materializer.materialize(
                    candidate,
                    artifact_root / location,
                    location,
                    strategy,
                    media_id=f"media_{index}",
                    index=index,
                )
            )
    except BaseException:
        # A partial carousel is never reported; remove what this call wrote.
        for item in done:
            with contextlib.suppress(OSError):
                (artifact_root / item.location).unlink(missing_ok=True)
        raise
    return done
```

In `ThreadsAcquirer.inspect`, replace the `self._materialize_all(...)` call with:

```python
                    media = await materialize_media(
                        self._materializer,
                        parsed.media,
                        f"threads-{parsed.post.post_id}",
                        workflow_id,
                        strategy,
                        artifact_root,
                    )
```

- [ ] **Step 4: Add the acquirer to `instagram_service.py`**

Replace the import block of `instagram_service.py` with:

```python
import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import urlsplit

from thoth_control_plane.acquisition.adapters.instagram import (
    CANONICAL_BASE,
    POST_PATH,
    SHARE_PATH,
    InstagramParse,
    InstagramPostIdentity,
    InstagramUrlError,
    canonical_instagram_share_url,
    canonicalize_instagram_post_url,
    login_required,
    parse_post,
)
from thoth_control_plane.acquisition.adapters.threads import json_roots
from thoth_control_plane.acquisition.browser import (
    FETCH_OPTIONS,
    HeadlessBrowserError,
    _classify_fetch_error,
    _decrement_active_sessions,
    _default_session_factory,
    _increment_active_sessions,
    _is_timeout,
)
from thoth_control_plane.acquisition.cards import CardRejected, write_card
from thoth_control_plane.acquisition.materializer import (
    MediaMaterializationError,
    MediaMaterializer,
)
from thoth_control_plane.acquisition.models import (
    AcquisitionFailure,
    AcquisitionOutcome,
    AcquisitionReason,
    AcquisitionResult,
    CardArtifact,
    MaterializedMedia,
    ReportComment,
    ReportSource,
    SourceReport,
)
from thoth_control_plane.acquisition.service import (
    RETRYABLE_FAILURES,
    _elapsed_ms,
    _make_attempt,
)
from thoth_control_plane.acquisition.threads_service import (
    _STRATEGIES,
    REQUEST_OPTIONS,
    SCRIPT_SELECTOR,
    RequestFetchError,
    _await_post_url,
    _scrapling_get,
    materialize_media,
)

logger = logging.getLogger(__name__)
```

(keep the module docstring and `from __future__ import annotations` above it; ruff's isort
decides the final order — run `uvx ruff check --fix` on the file if it reorders). Append to
the end of the module:

```python
def _persist_cards(
    cards: InstagramCards, comments: list[ReportComment], workflow_id: str, artifact_root: Path
) -> tuple[CardArtifact | None, list[ReportComment], CardArtifact | None]:
    base = PurePosixPath("reports") / workflow_id / "cards"

    def save(png: bytes | None, name: str) -> CardArtifact | None:
        if png is None:
            return None
        try:
            return write_card(png, artifact_root, base / name)
        except (CardRejected, OSError):
            return None

    carded = [
        comment.model_copy(
            update={
                "card": save(
                    cards.comment_pngs.get(comment.comment_id),
                    f"comment-{comment.comment_id}.png",
                )
            }
        )
        for comment in comments
    ]
    return save(cards.post_png, "post.png"), carded, save(cards.profile_png, "profile.png")


def _log_outcome(
    parsed: InstagramParse,
    media: list[MaterializedMedia],
    comments: list[ReportComment],
    post_card: CardArtifact | None,
    profile_card: CardArtifact | None,
    want_post: bool,
    problems: list[str],
) -> None:
    carded = sum(comment.card is not None for comment in comments)
    logger.info(
        "instagram acquisition finished method=%s media=%d comments=%d comment_cards=%d "
        "post_card=%s profile_card=%s",
        CONTENT_METHOD,
        len(media),
        len(comments),
        carded,
        post_card is not None,
        profile_card is not None,
    )
    missing = []
    if want_post and post_card is None:
        missing.append("post")
    if profile_card is None:
        missing.append("profile")
    if carded < len(comments):
        missing.append(f"comments={len(comments) - carded}")
    if missing or problems:
        logger.warning(
            "instagram cards missing missing=%s problems=%s",
            ",".join(missing) or "none",
            ",".join(problems) or "none",
        )
    if parsed.dropped_comments:
        logger.debug("instagram comments dropped count=%d", parsed.dropped_comments)


class InstagramAcquirer:
    """One Instagram post: content by `CONTENT_METHOD`, media in order, comments, and cards."""

    def __init__(
        self,
        request_fetcher: InstagramRequestFetcher,
        headless: InstagramHeadlessBrowser,
        materializer: MediaMaterializer,
    ) -> None:
        self._request = request_fetcher
        self._headless = headless
        self._materializer = materializer

    async def _content(
        self, identity: InstagramPostIdentity
    ) -> tuple[InstagramParse | None, AcquisitionReason | None]:
        url = str(identity.canonical_url)
        if CONTENT_METHOD == "request":
            blocked = AcquisitionReason.REQUEST_BLOCKED
            incomplete = AcquisitionReason.REQUEST_INCOMPLETE
        else:
            blocked = AcquisitionReason.HEADLESS_BLOCKED
            incomplete = AcquisitionReason.HEADLESS_INCOMPLETE
        try:
            if CONTENT_METHOD == "request":
                texts = await self._request.fetch(url)
            else:
                texts = await self._headless.scripts(url)
        except (RequestFetchError, HeadlessBrowserError) as error:
            return None, error.reason
        roots = json_roots(texts)
        if login_required(roots):
            return None, blocked
        parsed = parse_post(roots, identity)
        return parsed, None if parsed else incomplete

    async def inspect(
        self, *, workflow_id: str, source_url: str, artifact_root: Path
    ) -> AcquisitionResult:
        strategy = _STRATEGIES[CONTENT_METHOD]
        try:
            try:
                identity = await resolve_instagram_identity(
                    source_url, self._request, self._headless
                )
            except InstagramUrlError:
                return AcquisitionResult(
                    failure=AcquisitionFailure(code="invalid_source_url", retryable=False)
                )
            except (RequestFetchError, HeadlessBrowserError) as error:
                return AcquisitionResult(
                    failure=AcquisitionFailure(
                        code=error.reason.value,
                        retryable=error.reason.value in RETRYABLE_FAILURES,
                    )
                )
            start = time.monotonic()
            parsed, reason = await self._content(identity)
            if parsed is not None and not parsed.post.text.strip() and not parsed.media:
                attempt = _make_attempt(strategy, None, _elapsed_ms(start))
                return AcquisitionResult(
                    failure=AcquisitionFailure(
                        code="no_content", retryable=False, attempts=[attempt]
                    )
                )
            media: list[MaterializedMedia] = []
            if parsed is not None:
                try:
                    media = await materialize_media(
                        self._materializer,
                        parsed.media,
                        f"instagram-{identity.post_id}",
                        workflow_id,
                        strategy,
                        artifact_root,
                    )
                except MediaMaterializationError:
                    reason = AcquisitionReason.MEDIA_VALIDATION_FAILED
            attempt = _make_attempt(strategy, reason, _elapsed_ms(start))
            if reason is not None:
                return AcquisitionResult(
                    failure=AcquisitionFailure(
                        code=reason.value,
                        retryable=reason.value in RETRYABLE_FAILURES,
                        attempts=[attempt],
                    )
                )
            assert parsed is not None  # a None parse always carries a reason
            want_post = not any(item.kind == "video" for item in media)
            cards = await self._headless.cards(
                str(identity.canonical_url),
                f"{CANONICAL_BASE}/{parsed.post.owner_handle}/",
                want_post=want_post,
                targets=comment_targets(parsed.comments),
            )
            post_card, comments, profile_card = await asyncio.to_thread(
                _persist_cards, cards, parsed.comments, workflow_id, artifact_root
            )
            _log_outcome(
                parsed, media, comments, post_card, profile_card, want_post, cards.problems
            )
            return AcquisitionResult(
                report=SourceReport(
                    workflow_id=workflow_id,
                    source=ReportSource(
                        platform="instagram", canonical_url=identity.canonical_url
                    ),
                    post=parsed.post,
                    media=media,
                    outcome=AcquisitionOutcome(attempts=[attempt]),
                    comments=comments,
                    post_card=post_card,
                    profile_card=profile_card,
                )
            )
        finally:
            # Same shielded close as Threads: a second cancellation must not interrupt
            # browser cleanup partway through.
            await asyncio.shield(self._headless.close())
```

- [ ] **Step 5: Add the registry branch**

In `registry.py`, import `InstagramAcquirer`, `InstagramHeadlessBrowser`, and
`InstagramRequestFetcher` from `thoth_control_plane.acquisition.instagram_service`, and add
before `raise LookupError(...)`:

```python
    if platform == "instagram":
        return InstagramAcquirer(
            InstagramRequestFetcher(), InstagramHeadlessBrowser(), materializer
        )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition tests/activities tests/workflows/test_source_investigation.py -q`
Expected: PASS (Threads materialization tests stay green through `materialize_media`).

- [ ] **Step 7: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/threads_service.py python/src/thoth_control_plane/acquisition/instagram_service.py python/src/thoth_control_plane/acquisition/registry.py python/tests/acquisition/test_instagram_acquirer.py python/tests/acquisition/test_registry.py
git commit -m "feat(acquisition): add the instagram acquirer and registry branch"
```

---

### Task 5: Instagram profile discovery

**Files:**
- Create: `python/src/thoth_control_plane/acquisition/instagram_discovery.py`
- Test: `python/tests/acquisition/test_instagram_discovery.py`

**Interfaces:**
- Consumes: `CANONICAL_BASE`, `CODE`, `HANDLE`, `engagement_of`, `login_required` (Task 2);
  `InstagramRequestFetcher` (Task 3); `discovery._empty`, `discovery.MAX_CAPTION`.
- Produces:
  - `GRID_SIZE = 12`, `VIDEO_MEDIA_TYPE = 2`, `TIMELINE_KEY = "polaris_ordered_timeline_connection"`
  - `_timeline(roots, handle: str) -> tuple[str, list[Any]] | None` (owner as the page spells it, raw edges)
  - `parse_profile(roots: Iterable[object], handle: str, limit: int) -> DiscoveryResult`
  - `InstagramProfileDiscovery(fetcher=None)` with `async discover(request: ProfileDiscovery) -> DiscoveryResult` (never raises)

- [ ] **Step 1: Write the failing tests**

Create `python/tests/acquisition/test_instagram_discovery.py`:

```python
"""Instagram profile discovery over a fake fetcher: no network."""

from __future__ import annotations

import json
from typing import Any

import pytest

from thoth_control_plane.acquisition.instagram_discovery import (
    TIMELINE_KEY,
    InstagramProfileDiscovery,
)
from thoth_control_plane.acquisition.models import (
    AcquisitionReason,
    DiscoveryReason,
    ProfileDiscovery,
)
from thoth_control_plane.acquisition.threads_service import RequestFetchError


def _node(n: int, media_type: object = 2, likes: int | None = None, **extra: Any):
    return {
        "pk": str(3_100_000_000_000_000_000 + n),
        "code": f"code_{n:03d}",
        "media_type": media_type,
        "user": {"username": "nasa"},
        "caption": {"text": f"post {n}"},
        "taken_at": 1_700_000_000 + n * 3_600,
        "like_count": n * 10 if likes is None else likes,
        "comment_count": n,
        **extra,
    }


def _page(nodes: list[object], username: str = "nasa") -> list[str]:
    user = {"username": username, TIMELINE_KEY: {"edges": [{"node": n} for n in nodes]}}
    return [json.dumps({"require": [{"data": {"xig_user_by_username": user}}]})]


class FakeFetcher:
    def __init__(self, texts: list[str] | None = None, error: AcquisitionReason | None = None):
        self.texts, self.error, self.urls = texts or [], error, []

    async def fetch(self, url: str) -> list[str]:
        self.urls.append(url)
        if self.error is not None:
            raise RequestFetchError(self.error)
        return self.texts


async def _discover(fetcher: FakeFetcher, handle: str = "nasa", limit: int = 30):
    discovery = InstagramProfileDiscovery(fetcher)
    return await discovery.discover(ProfileDiscovery(handle=handle, limit=limit))


@pytest.mark.asyncio
async def test_videos_only_sorted_by_likes() -> None:
    nodes = [
        _node(1, likes=5),
        _node(2, media_type=1),
        _node(3, media_type=8),
        _node(4, likes=50),
        _node(5, likes=20),
    ]
    fetcher = FakeFetcher(_page(nodes))
    result = await _discover(fetcher)
    assert [v.post_id for v in result.videos] == [
        "3100000000000000004",
        "3100000000000000005",
        "3100000000000000001",
    ]
    first = result.videos[0]
    assert str(first.canonical_url) == "https://www.instagram.com/p/code_004/"
    assert first.owner_handle == "nasa"
    assert first.caption == "post 4"
    assert first.engagement == {"like": 50, "comment": 4}
    assert first.duration_seconds is None
    assert first.hashtags == []
    assert (result.drops.photo_posts, result.drops.invalid) == (2, 0)
    assert (result.pages, result.exhausted, result.reason) == (1, False, None)
    assert fetcher.urls == ["https://www.instagram.com/nasa/"]


@pytest.mark.asyncio
async def test_limit_is_respected() -> None:
    result = await _discover(FakeFetcher(_page([_node(n) for n in range(1, 6)])), limit=2)
    assert [v.engagement["like"] for v in result.videos] == [50, 40]


@pytest.mark.asyncio
async def test_at_most_twelve_whatever_the_limit() -> None:
    result = await _discover(FakeFetcher(_page([_node(n) for n in range(1, 16)])), limit=30)
    assert len(result.videos) == 12


@pytest.mark.asyncio
async def test_malformed_nodes_count_as_invalid() -> None:
    nodes = [
        _node(1, code="bad code"),
        _node(2, media_type="2"),
        _node(3, media_type=True),
        "not a dict",
        _node(4, pk="abc"),
        _node(5),
    ]
    result = await _discover(FakeFetcher(_page(nodes)))
    assert [v.post_id for v in result.videos] == ["3100000000000000005"]
    assert result.drops.invalid == 5


@pytest.mark.asyncio
async def test_duplicate_posts_keep_the_first() -> None:
    result = await _discover(FakeFetcher(_page([_node(1, likes=5), _node(1, likes=99)])))
    assert [v.engagement["like"] for v in result.videos] == [5]
    assert result.drops.invalid == 0


@pytest.mark.asyncio
async def test_handle_match_is_case_insensitive() -> None:
    fetcher = FakeFetcher(_page([_node(1)]))
    result = await _discover(fetcher, handle="NASA")
    assert [v.owner_handle for v in result.videos] == ["nasa"]
    assert fetcher.urls == ["https://www.instagram.com/NASA/"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "texts",
    [
        [json.dumps({"require": [{"data": {"xig_user_by_username": {"username": "nasa"}}}]})],
        # No node anywhere spells the requested handle (grid nodes would carry it).
        _page([], username="someone_else"),
        [],
    ],
)
async def test_no_user_or_timeline_is_no_data(texts: list[str]) -> None:
    result = await _discover(FakeFetcher(texts))
    assert (result.videos, result.reason) == ([], DiscoveryReason.NO_DATA)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (AcquisitionReason.REQUEST_BLOCKED, DiscoveryReason.BLOCKED),
        (AcquisitionReason.REQUEST_TIMEOUT, DiscoveryReason.TIMEOUT),
    ],
)
async def test_fetch_failures_map_to_reasons(
    error: AcquisitionReason, reason: DiscoveryReason
) -> None:
    result = await _discover(FakeFetcher(error=error))
    assert (result.videos, result.pages, result.reason) == ([], 0, reason)


@pytest.mark.asyncio
async def test_require_login_is_blocked() -> None:
    texts = [json.dumps({"require_login": True, "status": "fail"})]
    result = await _discover(FakeFetcher(texts))
    assert result.reason is DiscoveryReason.BLOCKED
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_instagram_discovery.py -q`
Expected: FAIL — `ModuleNotFoundError: ... instagram_discovery`.

- [ ] **Step 3: Write the module**

Create `python/src/thoth_control_plane/acquisition/instagram_discovery.py`:

```python
"""Instagram profile discovery: video posts from the anonymous 12-post profile grid.

Request only: one Scrapling GET of `/<handle>/`. Never raises; every failure is an empty
`DiscoveryResult` with a reason. A library with no caller until Stage 8, like TikTok
discovery.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from thoth_control_plane.acquisition.adapters.instagram import (
    CANONICAL_BASE,
    CODE,
    HANDLE,
    engagement_of,
    login_required,
)
from thoth_control_plane.acquisition.adapters.threads import _walk, json_roots
from thoth_control_plane.acquisition.discovery import MAX_CAPTION, _empty
from thoth_control_plane.acquisition.instagram_service import InstagramRequestFetcher
from thoth_control_plane.acquisition.models import (
    AcquisitionReason,
    DiscoveredVideo,
    DiscoveryDrops,
    DiscoveryReason,
    DiscoveryResult,
    ProfileDiscovery,
)
from thoth_control_plane.acquisition.normalize import published_at_from_epoch
from thoth_control_plane.acquisition.threads_service import RequestFetchError

logger = logging.getLogger(__name__)
GRID_SIZE = 12
VIDEO_MEDIA_TYPE = 2
TIMELINE_KEY = "polaris_ordered_timeline_connection"


def _timeline(roots: Iterable[object], handle: str) -> tuple[str, list[Any]] | None:
    """The owner as the page spells it and the grid edges; handles are case-insensitive."""
    owner: str | None = None
    edges: list[Any] | None = None
    for root in roots:
        for node in _walk(root):
            username = node.get("username")
            if (
                owner is None
                and isinstance(username, str)
                and username.lower() == handle.lower()
                and HANDLE.fullmatch(username)
            ):
                owner = username
            timeline = node.get(TIMELINE_KEY)
            if edges is None and isinstance(timeline, dict):
                found = timeline.get("edges")
                edges = found if isinstance(found, list) else None
    if owner is None or edges is None:
        return None
    return owner, edges


def _video(node: dict[str, Any], owner: str) -> DiscoveredVideo | None:
    code = node.get("code")
    if not isinstance(code, str) or CODE.fullmatch(code) is None:
        return None
    caption = node.get("caption")
    text = caption.get("text") if isinstance(caption, dict) else None
    try:
        return DiscoveredVideo(
            post_id=str(node.get("pk")),
            owner_handle=owner,
            canonical_url=f"{CANONICAL_BASE}/p/{code}/",
            caption=text[:MAX_CAPTION] if isinstance(text, str) else "",
            published_at=published_at_from_epoch(node.get("taken_at")),
            engagement=engagement_of(node),
        )
    except ValueError:
        return None


def parse_profile(roots: Iterable[object], handle: str, limit: int) -> DiscoveryResult:
    found = _timeline(roots, handle)
    if found is None:
        return _empty("profile", DiscoveryReason.NO_DATA)
    owner, edges = found
    videos: dict[str, DiscoveredVideo] = {}
    photo_posts = invalid = 0
    for edge in edges:
        node = edge.get("node") if isinstance(edge, dict) else None
        media_type = node.get("media_type") if isinstance(node, dict) else None
        if not isinstance(media_type, int) or isinstance(media_type, bool):
            invalid += 1
            continue
        if media_type != VIDEO_MEDIA_TYPE:
            photo_posts += 1
            continue
        video = _video(node, owner)
        if video is None:
            invalid += 1
            continue
        videos.setdefault(video.post_id, video)
    # The legacy view sort is unavailable anonymously; likes are the closest signal.
    ranked = sorted(videos.values(), key=lambda video: -video.engagement.get("like", 0))
    return DiscoveryResult(
        kind="profile",
        videos=ranked[: min(limit, GRID_SIZE)],
        pages=1,
        exhausted=False,
        drops=DiscoveryDrops(photo_posts=photo_posts, invalid=invalid),
    )


class InstagramProfileDiscovery:
    def __init__(self, fetcher: InstagramRequestFetcher | None = None) -> None:
        self._fetcher = fetcher or InstagramRequestFetcher()

    async def discover(self, request: ProfileDiscovery) -> DiscoveryResult:
        result = await self._collect(request)
        reason = result.reason.value if result.reason is not None else "none"
        logger.info(
            "instagram discovery finished kind=profile videos=%d photo_posts=%d invalid=%d "
            "reason=%s",
            len(result.videos),
            result.drops.photo_posts,
            result.drops.invalid,
            reason,
        )
        if result.reason is not None:
            logger.warning("instagram discovery stopped early kind=profile reason=%s", reason)
        return result

    async def _collect(self, request: ProfileDiscovery) -> DiscoveryResult:
        try:
            texts = await self._fetcher.fetch(f"{CANONICAL_BASE}/{request.handle}/")
        except RequestFetchError as error:
            timeout = error.reason is AcquisitionReason.REQUEST_TIMEOUT
            return _empty(
                "profile", DiscoveryReason.TIMEOUT if timeout else DiscoveryReason.BLOCKED
            )
        roots = json_roots(texts)
        if login_required(roots):
            return _empty("profile", DiscoveryReason.BLOCKED)
        return parse_profile(roots, request.handle, request.limit)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_instagram_discovery.py tests/acquisition/test_discovery.py -q`
Expected: PASS. (If the TikTok discovery test file has another name, run
`tests/acquisition -k discovery`.)

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/instagram_discovery.py python/tests/acquisition/test_instagram_discovery.py
git commit -m "feat(acquisition): add instagram profile discovery"
```

---

### Task 6: Capture and fixture tooling

**Files:**
- Create: `python/src/thoth_control_plane/operations/instagram_capture.py`
- Create: `python/src/thoth_control_plane/operations/instagram_fixture.py`
- Test: `python/tests/operations/test_instagram_capture.py`, `python/tests/operations/test_instagram_fixture.py`

**Interfaces:**
- Consumes: Tasks 2–5 public names; `threads_fixture.{MEDIA_HOST, _leaves, decide, leak_count, method_roots}`;
  `tiktok_comment_fixture._Pseudonyms`; `tiktok_discovery_fixture.{SYNTHETIC_EPOCH, SYNTHETIC_EPOCH_STEP, _floor}`.
- Produces:
  - capture: `KINDS`, `POST_KINDS`, `main(argv) -> int`, raw files `<kind>.json` with
    post raw `{"kind", "post_id", "request": {"status", "script_texts"}, "headless": {"status", "script_texts"}, "cards": {...} | None}`,
    share raw `{"kind", "request": {"status", "lands_on_post"}, "headless": {...}}`,
    profile raw `{"kind", "handle", "request": {"status", "script_texts"}}`
  - fixture: `counts(parsed) -> dict | None` (adds `comments`), `build_post(raw) -> (fixture, scope)`,
    `build_profile(raw) -> (fixture, scope)`, `decide_share(raw) -> Literal["request", "headless"]`,
    `build_share(raw) -> (fixture, scope)`, `build(raw) -> (fixture, scope)`, `main(argv) -> int`
  - post fixture JSON: `{"kind", "method", "counts": {"request", "headless"}, "document", "expected": {"text", "media_kinds", "engagement", "published_at", "comments"}}`
  - profile fixture JSON: `{"kind": "profile", "method": "request", "handle", "counts": {"raw_edges", "sanitized_edges"}, "document", "expected": {"post_ids", "likes", "drops"}}`
  - share fixture JSON: `{"kind": "share", "method", "results": {"request": {...}, "headless": {...}}}`

- [ ] **Step 1: Write the failing tests**

Create `python/tests/operations/test_instagram_capture.py`:

```python
"""The capture CLI refuses bad input before any network access and never echoes a URL."""

from __future__ import annotations

from pathlib import Path

import pytest

from thoth_control_plane.operations.instagram_capture import main

SECRET_URL = "https://www.instagram.com/secret_person/"


@pytest.mark.parametrize(
    "line", [f"bogus {SECRET_URL}", f"image {SECRET_URL}", f"share {SECRET_URL}", "image"]
)
def test_bad_lines_stop_before_any_fetch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], line: str
) -> None:
    urls = tmp_path / "urls.txt"
    urls.write_text(line + "\n", encoding="utf-8")
    assert main(["--urls", str(urls), "--out", str(tmp_path / "raw")]) == 2
    out = capsys.readouterr().out
    assert "secret_person" not in out
    assert "error" in out
    assert list((tmp_path / "raw").glob("*.json")) == []
```

Create `python/tests/operations/test_instagram_fixture.py`:

```python
"""Instagram fixture tooling: sanitizing, leak checking, and the method decisions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.acquisition.adapters.instagram import (
    canonicalize_instagram_post_url,
    parse_post,
)
from thoth_control_plane.acquisition.instagram_discovery import TIMELINE_KEY, parse_profile
from thoth_control_plane.operations import instagram_fixture
from thoth_control_plane.operations.instagram_fixture import (
    build_post,
    build_profile,
    decide_share,
    main,
)
from thoth_control_plane.operations.threads_fixture import _leaves, leak_count

SECRETS = (
    "realperson",
    "Secret caption about Jakarta",
    "scontent.cdninstagram",
    "Xy9Qk2Lm",
    "fanatic_one",
    "Totally private comment",
    "3141592653589793",
)
IDENTITY = canonicalize_instagram_post_url("https://www.instagram.com/p/code_001/")


def _raw_node(**extra: Any) -> dict[str, Any]:
    return {
        "code": "Xy9Qk2Lm",
        "pk": "3141592653589793",
        "user": {
            "username": "realperson",
            "profile_pic_url": "https://scontent.cdninstagram.com/p.jpg",
        },
        "caption": {"text": "Secret caption about Jakarta"},
        "taken_at": 1_726_000_123,
        "like_count": 1_234,
        "comment_count": 56,
        "media_type": 8,
        "carousel_media": [
            {
                "media_type": 1,
                "image_versions2": {
                    "candidates": [
                        {
                            "url": "https://scontent.cdninstagram.com/a.jpg?sig=1",
                            "width": 1080,
                            "height": 1350,
                        }
                    ]
                },
            },
            {
                "media_type": 2,
                "video_versions": [
                    {
                        "url": "https://scontent.cdninstagram.com/v.mp4?sig=3",
                        "width": 720,
                        "height": 1280,
                    }
                ],
            },
        ],
        **extra,
    }


def _raw_comment() -> dict[str, Any]:
    return {
        "pk": "17900000000000001",
        "text": "Totally private comment",
        "comment_like_count": 7,
        "user": {"username": "fanatic_one"},
    }


def _doc(node: dict[str, Any], comments: list[dict[str, Any]] | None) -> str:
    media: dict[str, Any] = {"if_not_gated_logged_out": node}
    if comments is not None:
        media["comments_connection"] = {"edges": [{"node": c} for c in comments]}
    return json.dumps({"require": [{"xig_polaris_media": media}]})


def _raw(request: dict[str, Any] | None = None) -> dict[str, Any]:
    full = _doc(_raw_node(), [_raw_comment()])
    return {
        "kind": "carousel",
        "post_id": "Xy9Qk2Lm",
        "request": request or {"status": "ok", "script_texts": [full]},
        "headless": {"status": "ok", "script_texts": [full]},
        "cards": None,
    }


def _no_leak(fixture: dict[str, Any], scope: dict[str, Any]) -> None:
    text = json.dumps(fixture, ensure_ascii=False)
    assert [secret for secret in SECRETS if secret in text] == []
    assert leak_count(scope, "\n".join(sorted(_leaves(fixture)))) == 0


def test_post_fixture_carries_no_original_value_and_still_parses() -> None:
    fixture, scope = build_post(_raw())
    _no_leak(fixture, scope)
    assert fixture["method"] == "request"

    parsed = parse_post([fixture["document"]], IDENTITY)
    assert parsed is not None
    assert parsed.post.owner_handle == "user_001"
    assert [item.kind for item in parsed.media] == ["image", "video"]
    assert parsed.post.engagement == {"like": 1_200, "comment": 56}
    assert [(c.author, c.likes) for c in parsed.comments] == [("user_002", 7)]
    assert fixture["expected"]["comments"] == [
        c.model_dump(mode="json", exclude={"card"}) for c in parsed.comments
    ]
    assert fixture["expected"]["media_kinds"] == ["image", "video"]


def test_request_without_comments_loses_to_headless() -> None:
    weaker = {"status": "ok", "script_texts": [_doc(_raw_node(), None)]}
    fixture, _ = build_post(_raw(weaker))
    assert fixture["method"] == "headless"
    assert fixture["counts"]["request"]["comments"] == 0
    assert fixture["counts"]["headless"]["comments"] == 1


def test_blocked_request_uses_the_headless_document() -> None:
    fixture, _ = build_post(_raw({"status": "request_blocked", "script_texts": []}))
    assert fixture["method"] == "headless"
    assert fixture["counts"]["request"] is None


def _grid_node(code: str, pk: str, media_type: int, likes: int) -> dict[str, Any]:
    return {
        "code": code,
        "pk": pk,
        "media_type": media_type,
        "user": {"username": "realperson"},
        "caption": {"text": "Secret caption about Jakarta"},
        "taken_at": 1_726_000_123,
        "like_count": likes,
        "comment_count": 3,
    }


def test_profile_fixture_replays_like_sorted_videos() -> None:
    nodes = [
        _grid_node("AbC123xyz", "3141592653589001", 2, 900),
        _grid_node("DeF456xyz", "3141592653589002", 1, 5_000),
        _grid_node("GhI789xyz", "3141592653589003", 2, 4_000),
    ]
    user = {"username": "realperson", TIMELINE_KEY: {"edges": [{"node": n} for n in nodes]}}
    raw = {
        "kind": "profile",
        "handle": "realperson",
        "request": {
            "status": "ok",
            "script_texts": [json.dumps({"require": [{"xig_user_by_username": user}]})],
        },
    }
    fixture, scope = build_profile(raw)
    _no_leak(fixture, scope)
    assert fixture["handle"] == "user_001"
    assert fixture["expected"]["likes"] == [4_000, 900]
    assert fixture["expected"]["drops"] == {"ads": 0, "photo_posts": 1, "invalid": 0}
    result = parse_profile([fixture["document"]], fixture["handle"], 30)
    assert [v.post_id for v in result.videos] == fixture["expected"]["post_ids"]


@pytest.mark.parametrize(
    ("request_result", "method"),
    [
        ({"status": "ok", "lands_on_post": True}, "request"),
        ({"status": "ok", "lands_on_post": False}, "headless"),
        ({"status": "request_blocked", "lands_on_post": False}, "headless"),
    ],
)
def test_decide_share(request_result: dict[str, Any], method: str) -> None:
    raw = {
        "kind": "share",
        "request": request_result,
        "headless": {"status": "ok", "lands_on_post": True},
    }
    assert decide_share(raw) == method


def test_main_writes_a_clean_fixture(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw_path, out = tmp_path / "carousel.json", tmp_path / "out.json"
    raw_path.write_text(json.dumps(_raw()), encoding="utf-8")
    assert main(["--raw", str(raw_path), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert json.loads(printed)["leaks"] == 0
    assert [secret for secret in SECRETS if secret in printed] == []
    assert json.loads(out.read_text(encoding="utf-8"))["kind"] == "carousel"


def test_main_refuses_to_write_a_leaking_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leaking = ({"kind": "image", "method": "request", "document": {"x": "realperson"}}, {
        "u": "realperson"
    })
    monkeypatch.setattr(instagram_fixture, "build", lambda raw: leaking)
    raw_path, out = tmp_path / "image.json", tmp_path / "out.json"
    raw_path.write_text("{}", encoding="utf-8")
    assert main(["--raw", str(raw_path), "--out", str(out)]) == 1
    assert not out.exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/operations/test_instagram_capture.py tests/operations/test_instagram_fixture.py -q`
Expected: FAIL — `ModuleNotFoundError` for both modules.

- [ ] **Step 3: Write the capture CLI**

Create `python/src/thoth_control_plane/operations/instagram_capture.py`:

```python
"""Operator-run, read-only Instagram capture for the Stage 3b method comparison.

Never run by the test suite and only after the operator authorizes the capture. Reads
`<kind> <url>` lines (kind: video, image, carousel, share, profile) from `--urls` and writes
one raw JSON per line plus the card PNGs under `--out`. URLs, handles, and bodies are never
printed; stdout carries kinds, statuses, and counts only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.adapters.instagram import (
    CANONICAL_BASE,
    InstagramUrlError,
    canonical_instagram_share_url,
    canonicalize_instagram_post_url,
    parse_post,
)
from thoth_control_plane.acquisition.adapters.threads import _match_safe_path, json_roots
from thoth_control_plane.acquisition.browser import HeadlessBrowserError
from thoth_control_plane.acquisition.instagram_service import (
    InstagramHeadlessBrowser,
    InstagramRequestFetcher,
    comment_targets,
)
from thoth_control_plane.acquisition.threads_service import RequestFetchError

KINDS = ("video", "image", "carousel", "share", "profile")
POST_KINDS = ("video", "image", "carousel")
SPACING_SECONDS = 5
PROFILE_PATH = re.compile(r"^/(?P<handle>[A-Za-z0-9._]{1,64})/?$")


async def _post(kind: str, url: str, out: Path) -> dict[str, Any]:
    identity = canonicalize_instagram_post_url(url)
    target = str(identity.canonical_url)
    raw: dict[str, Any] = {"kind": kind, "post_id": identity.post_id, "cards": None}
    try:
        texts = await InstagramRequestFetcher().fetch(target)
        raw["request"] = {"status": "ok", "script_texts": texts}
    except RequestFetchError as error:
        raw["request"] = {"status": error.reason.value, "script_texts": []}
    await asyncio.sleep(SPACING_SECONDS)
    browser = InstagramHeadlessBrowser()
    try:
        try:
            raw["headless"] = {"status": "ok", "script_texts": await browser.scripts(target)}
        except HeadlessBrowserError as error:
            raw["headless"] = {"status": error.reason.value, "script_texts": []}
        parsed = None
        for method in ("request", "headless"):
            parsed = parsed or parse_post(json_roots(raw[method]["script_texts"]), identity)
        if parsed is None:
            return raw
        targets = comment_targets(parsed.comments)
        await asyncio.sleep(SPACING_SECONDS)
        cards = await browser.cards(
            target,
            f"{CANONICAL_BASE}/{parsed.post.owner_handle}/",
            want_post=True,
            targets=targets,
        )
    finally:
        await browser.close()
    if cards.post_png is not None:
        (out / f"{kind}-post.png").write_bytes(cards.post_png)
    for n, png in enumerate(cards.comment_pngs.values(), start=1):
        (out / f"{kind}-comment-{n}.png").write_bytes(png)
    if cards.profile_png is not None:
        (out / f"{kind}-profile.png").write_bytes(cards.profile_png)
    raw["cards"] = {
        "post": cards.post_png is not None,
        "comments": len(cards.comment_pngs),
        "comment_targets": len(targets),
        "profile": cards.profile_png is not None,
        "problems": cards.problems,
    }
    return raw


def _lands_on_post(url: str) -> bool:
    try:
        canonicalize_instagram_post_url(url)
    except InstagramUrlError:
        return False
    return True


async def _share(kind: str, url: str, out: Path) -> dict[str, Any]:
    share_url = canonical_instagram_share_url(url)
    raw: dict[str, Any] = {"kind": kind}
    try:
        landing = await InstagramRequestFetcher().landing(share_url)
        raw["request"] = {"status": "ok", "lands_on_post": _lands_on_post(landing)}
    except RequestFetchError as error:
        raw["request"] = {"status": error.reason.value, "lands_on_post": False}
    await asyncio.sleep(SPACING_SECONDS)
    browser = InstagramHeadlessBrowser()
    try:
        landing = await browser.resolve(share_url)
        raw["headless"] = {"status": "ok", "lands_on_post": _lands_on_post(landing)}
    except HeadlessBrowserError as error:
        raw["headless"] = {"status": error.reason.value, "lands_on_post": False}
    finally:
        await browser.close()
    return raw


async def _profile(kind: str, url: str, out: Path) -> dict[str, Any]:
    handle = _match_safe_path(url, PROFILE_PATH, "instagram", InstagramUrlError).group("handle")
    raw: dict[str, Any] = {"kind": kind, "handle": handle}
    try:
        texts = await InstagramRequestFetcher().fetch(f"{CANONICAL_BASE}/{handle}/")
        raw["request"] = {"status": "ok", "script_texts": texts}
    except RequestFetchError as error:
        raw["request"] = {"status": error.reason.value, "script_texts": []}
    return raw


CAPTURES = {"share": _share, "profile": _profile}


def _summary(raw: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"kind": raw["kind"]}
    for method in ("request", "headless"):
        capture = raw.get(method)
        if capture is None:
            continue
        detail = (
            {"script_texts": len(capture["script_texts"])}
            if "script_texts" in capture
            else {"lands_on_post": capture["lands_on_post"]}
        )
        summary[method] = {"status": capture["status"], **detail}
    if raw.get("cards") is not None:
        summary["cards"] = raw["cards"]
    return summary


async def _run(urls: Path, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    for line in urls.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or parts[0] not in KINDS:
            print(json.dumps({"error": "unknown_kind"}))
            return 2
        kind, url = parts
        try:
            raw = await CAPTURES.get(kind, _post)(kind, url.strip(), out)
        except InstagramUrlError:
            print(json.dumps({"kind": kind, "error": "invalid_source_url"}))
            return 2
        (out / f"{kind}.json").write_text(json.dumps(raw), encoding="utf-8")
        print(json.dumps(_summary(raw)))
        await asyncio.sleep(SPACING_SECONDS)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--urls", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    # Scrapling logs fetched URLs at info level; keep them out of the operator's terminal.
    logging.getLogger("scrapling").setLevel(logging.WARNING)
    return asyncio.run(_run(args.urls, args.out))


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Write the fixture tool**

Create `python/src/thoth_control_plane/operations/instagram_fixture.py`:

```python
"""Turn one raw Instagram capture into a sanitized golden fixture and compare the methods.

Operator-run after an authorized capture. Only allowlisted keys survive; handles, `pk`,
codes, and text are pseudonymized, media URLs replaced, timestamps moved to a synthetic
one-hour grid, and counters floored. Output reports counts only; raw values are never
printed, and a fixture with any surviving raw value is not written.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Literal

from thoth_control_plane.acquisition.adapters.instagram import (
    InstagramParse,
    canonicalize_instagram_post_url,
    find_instagram_media,
    parse_post,
)
from thoth_control_plane.acquisition.instagram_discovery import (
    TIMELINE_KEY,
    _timeline,
    parse_profile,
)
from thoth_control_plane.operations.threads_fixture import (
    MEDIA_HOST,
    _leaves,
    decide,
    leak_count,
    method_roots,
)
from thoth_control_plane.operations.tiktok_comment_fixture import _Pseudonyms
from thoth_control_plane.operations.tiktok_discovery_fixture import (
    SYNTHETIC_EPOCH,
    SYNTHETIC_EPOCH_STEP,
    _floor,
)

CODE = "code_001"
COUNTER_KEYS = ("like_count", "comment_count")
Fixture = tuple[dict[str, Any], dict[str, Any]]


def counts(parsed: InstagramParse | None) -> dict[str, int] | None:
    if parsed is None:
        return None
    return {
        "found": 1,
        "text_chars": len(parsed.post.text),
        "media": len(parsed.media),
        "videos": sum(item.kind == "video" for item in parsed.media),
        "engagement_keys": len(parsed.post.engagement),
        "published_at": int(parsed.post.published_at is not None),
        "comments": len(parsed.comments),
    }


def _int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class _Sanitizer:
    def __init__(self) -> None:
        self.names = _Pseudonyms()
        self.urls = 0
        self.epochs = 0

    def _url(self, kind: str, ext: str) -> str:
        self.urls += 1
        return f"{MEDIA_HOST}/{kind}/{self.urls}.{ext}"

    def _epoch(self) -> int:
        self.epochs += 1
        return SYNTHETIC_EPOCH + self.epochs * SYNTHETIC_EPOCH_STEP

    def _versions(self, versions: list[Any], kind: str, ext: str) -> list[dict[str, Any]]:
        return [
            {
                "url": self._url(kind, ext),
                **{k: v[k] for k in ("width", "height") if _int(v.get(k))},
            }
            for v in versions
            if isinstance(v, dict) and v.get("url")
        ]

    def _media(self, item: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if _int(item.get("media_type")):
            out["media_type"] = item["media_type"]
        if isinstance(item.get("video_versions"), list):
            out["video_versions"] = self._versions(item["video_versions"], "video", "mp4")
        container = item.get("image_versions2")
        candidates = container.get("candidates") if isinstance(container, dict) else None
        if isinstance(candidates, list):
            out["image_versions2"] = {"candidates": self._versions(candidates, "image", "jpg")}
        return out

    def node(self, node: dict[str, Any], code: str) -> dict[str, Any]:
        user = node.get("user") if isinstance(node.get("user"), dict) else {}
        out: dict[str, Any] = {
            "code": code,
            "pk": self.names.comment_id(node.get("pk")),
            "user": {"username": self.names.handle(user.get("username"))},
        }
        caption = node.get("caption")
        if isinstance(caption, dict) and isinstance(caption.get("text"), str):
            out["caption"] = {"text": self.names.text(caption["text"])}
        if node.get("taken_at") is not None:
            out["taken_at"] = self._epoch()
        for key in COUNTER_KEYS:
            if _int(node.get(key)):
                out[key] = _floor(node[key])
        if isinstance(node.get("like_and_view_counts_disabled"), bool):
            out["like_and_view_counts_disabled"] = node["like_and_view_counts_disabled"]
        out.update(self._media(node))
        carousel = node.get("carousel_media")
        if isinstance(carousel, list):
            out["carousel_media"] = [
                self._media(item) for item in carousel if isinstance(item, dict)
            ]
        return out

    def comment(self, node: dict[str, Any]) -> dict[str, Any]:
        user = node.get("user") if isinstance(node.get("user"), dict) else {}
        out: dict[str, Any] = {
            "pk": self.names.comment_id(node.get("pk")),
            "user": {"username": self.names.handle(user.get("username"))},
        }
        if isinstance(node.get("text"), str):
            out["text"] = self.names.text(node["text"])
        if _int(node.get("comment_like_count")):
            out["comment_like_count"] = _floor(node["comment_like_count"])
        return out


def post_document(post: dict[str, Any], comments: list[dict[str, Any]] | None) -> dict[str, Any]:
    media: dict[str, Any] = {"if_not_gated_logged_out": post}
    if comments is not None:
        media["comments_connection"] = {"edges": [{"node": node} for node in comments]}
    return {"data": {"xig_polaris_media": media}}


def build_post(raw: dict[str, Any]) -> Fixture:
    identity = canonicalize_instagram_post_url(f"https://www.instagram.com/p/{raw['post_id']}/")
    parses = {m: parse_post(method_roots(raw, m), identity) for m in ("request", "headless")}
    method = decide([(counts(parses["request"]), counts(parses["headless"]))])
    found = find_instagram_media(method_roots(raw, method), identity.post_id)
    if found is None:
        raise ValueError("neither method captured the post")
    raw_node, raw_connection = found
    sanitizer = _Sanitizer()
    # The owner is sanitized first, so it is always `user_001`.
    post = sanitizer.node(raw_node, CODE)
    comments = None
    if raw_connection is not None:
        edges = raw_connection.get("edges")
        comments = [
            sanitizer.comment(edge["node"])
            for edge in (edges if isinstance(edges, list) else [])
            if isinstance(edge, dict) and isinstance(edge.get("node"), dict)
        ]
    document = post_document(post, comments)
    replay = canonicalize_instagram_post_url(f"https://www.instagram.com/p/{CODE}/")
    parsed = parse_post([document], replay)
    if parsed is None:
        raise ValueError("the sanitized document no longer parses")
    fixture = {
        "kind": raw["kind"],
        "method": method,
        "counts": {m: counts(p) for m, p in parses.items()},
        "document": document,
        "expected": {
            "text": parsed.post.text,
            "media_kinds": [item.kind for item in parsed.media],
            "engagement": parsed.post.engagement,
            "published_at": parsed.post.published_at,
            "comments": [c.model_dump(mode="json", exclude={"card"}) for c in parsed.comments],
        },
    }
    return fixture, {"node": raw_node, "connection": raw_connection}


def build_profile(raw: dict[str, Any]) -> Fixture:
    found = _timeline(method_roots(raw, "request"), raw["handle"])
    if found is None:
        raise ValueError("the profile capture holds no timeline")
    owner, edges = found
    sanitizer = _Sanitizer()
    alias = sanitizer.names.handle(owner)
    raw_nodes = [e["node"] for e in edges if isinstance(e, dict) and isinstance(e.get("node"), dict)]
    nodes = [sanitizer.node(node, f"code_{n:03d}") for n, node in enumerate(raw_nodes, start=1)]
    document = {
        "data": {
            "xig_user_by_username": {
                "username": alias,
                TIMELINE_KEY: {"edges": [{"node": node} for node in nodes]},
            }
        }
    }
    result = parse_profile([document], alias, 30)
    fixture = {
        "kind": "profile",
        "method": "request",
        "handle": alias,
        "counts": {"raw_edges": len(edges), "sanitized_edges": len(nodes)},
        "document": document,
        "expected": {
            "post_ids": [video.post_id for video in result.videos],
            "likes": [video.engagement.get("like", 0) for video in result.videos],
            "drops": result.drops.model_dump(),
        },
    }
    return fixture, {"handle": raw["handle"], "edges": edges}


def decide_share(raw: dict[str, Any]) -> Literal["request", "headless"]:
    """Share links resolve by request only when the request itself lands on a post."""
    return "request" if raw["request"].get("lands_on_post") is True else "headless"


def build_share(raw: dict[str, Any]) -> Fixture:
    results = {
        m: {"status": raw[m]["status"], "lands_on_post": raw[m]["lands_on_post"]}
        for m in ("request", "headless")
    }
    return {"kind": "share", "method": decide_share(raw), "results": results}, {}


def build(raw: dict[str, Any]) -> Fixture:
    if raw["kind"] == "share":
        return build_share(raw)
    if raw["kind"] == "profile":
        return build_profile(raw)
    return build_post(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    raw = json.loads(args.raw.read_text(encoding="utf-8"))
    fixture, scope = build(raw)
    # Compare raw string leaves with fixture string leaves, not JSON text: escaping in the
    # JSON text would hide a surviving value that contains a quote or a newline.
    leaks = leak_count(scope, "\n".join(sorted(_leaves(fixture))))
    print(
        json.dumps(
            {
                "kind": fixture["kind"],
                "method": fixture["method"],
                "counts": fixture.get("counts"),
                "leaks": leaks,
            }
        )
    )
    if leaks:
        return 1
    text = json.dumps(fixture, indent=2, ensure_ascii=False) + "\n"
    args.out.write_bytes(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/operations/test_instagram_capture.py tests/operations/test_instagram_fixture.py tests/operations/test_threads_fixture.py -q`
Expected: PASS.

- [ ] **Step 6: Lint the new code**

Run the ruff command from Global Constraints.
Expected: `All checks passed!` and no files to reformat. Fix and re-run if not (use
`uvx ruff format <file>` for format-only findings).

- [ ] **Step 7: Commit**

```bash
git add python/src/thoth_control_plane/operations/instagram_capture.py python/src/thoth_control_plane/operations/instagram_fixture.py python/tests/operations/test_instagram_capture.py python/tests/operations/test_instagram_fixture.py
git commit -m "feat(operations): add instagram capture and fixture tooling"
```

---

### Task 7: Live capture, golden fixtures, and method decisions (HARD STOP)

**Files:**
- Create: `python/tests/fixtures/instagram/{video,image,carousel,share,profile}.json`
- Create: `python/tests/acquisition/test_instagram_replay.py`
- Modify: `python/src/thoth_control_plane/acquisition/instagram_service.py` (the two method constants, only if the evidence says so)

**Interfaces:**
- Consumes: Task 6 CLIs; `decide`, `decide_share`, `parse_post`, `parse_profile`.
- Produces: committed fixtures and the final `CONTENT_METHOD` / `SHARE_RESOLUTION_METHOD`.

- [ ] **Step 1: STOP and ask for the capture authorization**

Ask the operator in Indonesian for authorization to run one read-only anonymous capture,
and to write `D:/thoth-tmp/bu/instagram/urls.txt` themselves with exactly five lines
`<kind> <url>`: one `video` (a reel), one `image`, one `carousel`, one `share` link, and one
`profile` URL (the owner of one of those posts). Never read, print, or inspect that file,
not even by column. Wait for the explicit authorization. The authorization is not recorded
as an approval in any repo document.

- [ ] **Step 2: Run the capture inside the capture image**

```bash
wsl -e bash -lc 'docker run --rm -v /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python/src:/src:ro -v /mnt/d/thoth-tmp/bu/instagram:/work -e PYTHONPATH=/src ghcr.io/muhfalihr/thoth@sha256:56fa84e6f99fe1d59c94ed0389236866c0b82fd0d5a0119e1d996bd5c9e5adf9 python -m thoth_control_plane.operations.instagram_capture --urls /work/urls.txt --out /work/raw 2>/work/capture.err; echo EXIT=$?'
```

Expected: five JSON summary lines (kinds, statuses, counts, card flags and problem enums),
`EXIT=0`. On a non-zero exit, show only `tail -5 /mnt/d/thoth-tmp/bu/instagram/capture.err | sed -E 's#https?://[^ ]+#<url>#g'`.

- [ ] **Step 3: Probe the page shapes, keys and counts only**

Write `D:/thoth-tmp/bu/instagram/probe.py` (not committed):

```python
import json
from pathlib import Path

from thoth_control_plane.acquisition.adapters.instagram import (
    MEDIA_KEY,
    canonicalize_instagram_post_url,
    find_instagram_media,
    login_required,
    parse_post,
)
from thoth_control_plane.acquisition.adapters.threads import _walk, json_roots
from thoth_control_plane.acquisition.instagram_discovery import TIMELINE_KEY, _timeline

for path in sorted(Path("/work/raw").glob("*.json")):
    raw = json.loads(path.read_text(encoding="utf-8"))
    kind = raw["kind"]
    for method in ("request", "headless"):
        capture = raw.get(method)
        if capture is None or "script_texts" not in capture:
            continue
        roots = json_roots(capture["script_texts"])
        row = {"kind": kind, "method": method, "status": capture["status"], "roots": len(roots)}
        row["login_required"] = login_required(roots)
        if kind == "profile":
            row["timeline_holders"] = sum(
                isinstance(n.get(TIMELINE_KEY), dict) for r in roots for n in _walk(r)
            )
            found = _timeline(roots, raw["handle"])
            row["timeline_edges"] = len(found[1]) if found else None
        else:
            holders = [n[MEDIA_KEY] for r in roots for n in _walk(r) if isinstance(n.get(MEDIA_KEY), dict)]
            row["media_holders"] = len(holders)
            row["holder_keys"] = sorted({k for h in holders for k in h})
            found = find_instagram_media(roots, raw["post_id"])
            row["post_found"] = found is not None
            row["connection_edges"] = (
                len(found[1].get("edges") or []) if found and found[1] else None
            )
            identity = canonicalize_instagram_post_url(
                f"https://www.instagram.com/p/{raw['post_id']}/"
            )
            parsed = parse_post(roots, identity)
            row["parsed"] = None if parsed is None else {
                "media": len(parsed.media),
                "comments": len(parsed.comments),
                "dropped": parsed.dropped_comments,
            }
        print(json.dumps(row))
```

Run it in the same image:

```bash
wsl -e bash -lc 'docker run --rm -v /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python/src:/src:ro -v /mnt/d/thoth-tmp/bu/instagram:/work -e PYTHONPATH=/src ghcr.io/muhfalihr/thoth@sha256:56fa84e6f99fe1d59c94ed0389236866c0b82fd0d5a0119e1d996bd5c9e5adf9 python /work/probe.py'
```

Expected: keys, booleans, and counts only. Check: each post is found by at least one method;
comments come from a sibling or loose connection; the profile timeline has edges.

- [ ] **Step 4: Check the stop conditions**

Stop and report to the operator in Indonesian (counts and enums only) if any holds:
- both methods are blocked or find no post for every post kind;
- neither share method lands on a post;
- every post has comments but zero comment cards were cropped.

Otherwise continue. A parser that misses a shape the probe reveals (for example a
connection under a different key) is fixed in `adapters/instagram.py` with a new failing
adapter test first; ledger it as a ruling.

- [ ] **Step 5: Build the fixtures**

```bash
mkdir -p python/tests/fixtures/instagram
wsl -e bash -lc 'for k in video image carousel share profile; do docker run --rm -v /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python/src:/src:ro -v /mnt/d/thoth-tmp/bu/instagram:/work -v /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python/tests/fixtures/instagram:/out -e PYTHONPATH=/src ghcr.io/muhfalihr/thoth@sha256:56fa84e6f99fe1d59c94ed0389236866c0b82fd0d5a0119e1d996bd5c9e5adf9 python -m thoth_control_plane.operations.instagram_fixture --raw /work/raw/$k.json --out /out/$k.json || echo "FAIL $k"; done'
```

Expected: five summary lines with `"leaks": 0` and five files written. If a kind reports
leaks, run a keys-only probe that prints, for each fixture string leaf that contains a raw
leaf, the JSON key path of the fixture leaf and the raw leaf's length — never the value —
then fix the sanitizer with a failing fixture test first.

- [ ] **Step 6: Write the replay test**

Create `python/tests/acquisition/test_instagram_replay.py`:

```python
"""Sanitized golden fixtures replay through the Instagram parsers and method decisions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thoth_control_plane.acquisition import instagram_service
from thoth_control_plane.acquisition.adapters.instagram import (
    canonicalize_instagram_post_url,
    parse_post,
)
from thoth_control_plane.acquisition.instagram_discovery import parse_profile
from thoth_control_plane.operations.threads_fixture import decide

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "instagram"
FIXTURES = {
    path.stem: json.loads(path.read_text(encoding="utf-8"))
    for path in sorted(FIXTURE_DIR.glob("*.json"))
}
POST_KINDS = ("video", "image", "carousel")
IDENTITY = canonicalize_instagram_post_url("https://www.instagram.com/p/code_001/")


def test_all_five_kinds_are_present() -> None:
    assert set(FIXTURES) == {"video", "image", "carousel", "share", "profile"}


@pytest.mark.parametrize("kind", POST_KINDS)
def test_post_fixture_replays_to_its_expected_parse(kind: str) -> None:
    fixture = FIXTURES[kind]
    parsed = parse_post([fixture["document"]], IDENTITY)
    assert parsed is not None
    assert {
        "text": parsed.post.text,
        "media_kinds": [item.kind for item in parsed.media],
        "engagement": parsed.post.engagement,
        "published_at": parsed.post.published_at,
        "comments": [c.model_dump(mode="json", exclude={"card"}) for c in parsed.comments],
    } == fixture["expected"]


def test_post_kinds_have_their_shape() -> None:
    assert "video" in FIXTURES["video"]["expected"]["media_kinds"]
    assert FIXTURES["image"]["expected"]["media_kinds"] == ["image"]
    assert len(FIXTURES["carousel"]["expected"]["media_kinds"]) > 1
    assert any(FIXTURES[kind]["expected"]["comments"] for kind in POST_KINDS)


def test_content_method_matches_recorded_comparison() -> None:
    pairs = [
        (FIXTURES[kind]["counts"]["request"], FIXTURES[kind]["counts"]["headless"])
        for kind in POST_KINDS
    ]
    assert decide(pairs) == instagram_service.CONTENT_METHOD


def test_share_method_matches_recorded_comparison() -> None:
    assert FIXTURES["share"]["method"] == instagram_service.SHARE_RESOLUTION_METHOD


def test_profile_fixture_replays_like_sorted() -> None:
    fixture = FIXTURES["profile"]
    result = parse_profile([fixture["document"]], fixture["handle"], 30)
    assert [video.post_id for video in result.videos] == fixture["expected"]["post_ids"]
    likes = [video.engagement.get("like", 0) for video in result.videos]
    assert likes == fixture["expected"]["likes"] == sorted(likes, reverse=True)
    assert result.drops.model_dump() == fixture["expected"]["drops"]
    assert len(result.videos) <= 12
```

If `test_content_method_matches_recorded_comparison` or
`test_share_method_matches_recorded_comparison` fails, the evidence chose `headless`: set
the corresponding constant in `instagram_service.py` to `"headless"` and ledger the ruling.

- [ ] **Step 7: Run the replay and the Instagram suites**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition tests/operations -q`
Expected: PASS.

- [ ] **Step 8: Commit**

Check first that only the five fixture files, the replay test, and (if changed)
`instagram_service.py` are staged; never raw captures or PNGs.

```bash
git add python/tests/fixtures/instagram python/tests/acquisition/test_instagram_replay.py python/src/thoth_control_plane/acquisition/instagram_service.py
git status --short
git commit -m "test(acquisition): add instagram golden fixtures and method decision"
```

---

### Task 8: Verification and documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-09-28-stage3b-instagram-design.md:3-4` (status line)
- Modify: `CHANGELOG.md` (CRLF, newest first)
- Modify: `docs/python-scout-migration-roadmap.md` (CRLF, append)
- Modify: `.superpowers/sdd/2026-09-23-python-scout-migration-program/progress.md` (CRLF, append; gitignored)

**Interfaces:**
- Consumes: every earlier task's commits and the Task 7 restricted evidence.
- Produces: the verification record and the next operator gate.

- [ ] **Step 1: Run the full suite into a file**

```bash
MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh -q > D:/thoth-tmp/stage3b-suite.txt 2>&1; echo EXIT=$?
tail -15 D:/thoth-tmp/stage3b-suite.txt
```

Expected: all pass except the pre-existing master failure
`tests/api/test_workflows.py::test_route_modules_do_not_depend_on_a_process_runner`, which is
reported as-is. Any other failure is fixed before continuing.

- [ ] **Step 2: Run ruff and refresh the graph**

Run the ruff command from Global Constraints (expected: clean), then `graphify update .` from
the repository root. Never stage `graphify-out/`.

- [ ] **Step 3: Update the spec status line**

Replace the spec's status paragraph with:

```markdown
Status: written spec approved by the operator on 2026-09-28; implemented on branch
`feat/stage3b-instagram` (see `docs/superpowers/plans/2026-09-28-stage3b-instagram.md`).
```

- [ ] **Step 4: Write the CHANGELOG section and the checkpoint notes**

Write the new section to `D:/thoth-tmp/bu/instagram/changelog-section.md` (LF), with:
- heading `## <today> - Stage 3b: Instagram acquisition and profile discovery`;
- what shipped (routing, adapter, service, cards, discovery, tooling, fixtures), each with
  its commit hash from `git log --oneline master..HEAD`;
- verification: suite pass count, the pre-existing failure by name, ruff clean;
- restricted evidence from Task 7: per kind, the request and headless statuses and counts,
  card flags and problem enums, fixture `leaks: 0`, and the two method decisions — counts,
  keys, and enums only; no URL, handle, caption, or workflow id;
- next gate: operator review of the branch, then push/merge/deploy each by explicit
  authorization; the live smoke waits for final acceptance (ADR 0001).

Insert it into `CHANGELOG.md` before the first `## ` heading, keeping CRLF:

```bash
python - <<'PY'
from pathlib import Path

path = Path("C:/Users/mfr/Documents/MyTools/CLIPPER/CHANGELOG.md")
data = path.read_bytes()
assert data.endswith(b"\r\n")
text = data.decode("utf-8").replace("\r\n", "\n")
section = Path("D:/thoth-tmp/bu/instagram/changelog-section.md").read_text(encoding="utf-8")
at = text.index("\n## ") + 1
text = text[:at] + section.rstrip("\n") + "\n\n" + text[at:]
path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
PY
```

Append a short Stage 3b completion entry (what shipped, evidence pointer to the CHANGELOG
section, next gate) to `docs/python-scout-migration-roadmap.md` and to the checkpoint
`progress.md` with the same script shape, replacing the insertion with
`text = text.rstrip("\n") + "\n\n" + entry.rstrip("\n") + "\n"`.

- [ ] **Step 5: Commit and stop**

```bash
git add python
git add -f docs/superpowers/specs/2026-09-28-stage3b-instagram-design.md
git add CHANGELOG.md docs/python-scout-migration-roadmap.md
git status --short
git commit -m "docs: record stage 3b instagram completion"
```

Check `git status --short` shows nothing from the never-stage list before committing. Then
stop and report to the operator in Indonesian: commits, suite result, the pre-existing
failure, the method decisions, and the next gate (branch review; push, merge, and deploy are
separate operator authorizations).

# Stage 3a Platform Kernel and Threads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Python acquisition platform-neutral (URL routing, a v3 SourceReport that allows text-only and multi-image posts, image materialization, Facebook/Reddit rejection) and port Threads onto it with the request-versus-headless method chosen from live evidence.

**Architecture:** A pure `acquisition/platforms.py` classifies every URL as `python`, `legacy`, or `unsupported`; the API, workflow guard, and activity all route through it. `acquisition/registry.py` maps a Python platform to an acquirer that owns its own browser. TikTok keeps its headless-first service but writes `SourceReport` v3; Threads gets pure parsers (`adapters/threads.py`) plus fetchers and an acquirer (`threads_service.py`) whose content method is one constant decided from sanitized golden fixtures.

**Tech Stack:** Python 3.12, Pydantic v2, httpx, Temporal Python SDK, Scrapling (`AsyncFetcher`, `AsyncStealthySession`; lazily imported, absent from the test environment), pytest via WSL `pt.sh`, ruff.

**Spec:** `docs/superpowers/specs/2026-09-28-stage3a-platform-kernel-threads-design.md`

## Global Constraints

- Branch: execute on `feat/stage3a-platform-kernel-threads`, created from `master` at the plan commit; never on `master`.
- Facebook and Reddit (`facebook.com`, `fb.com`, `fb.watch`, `reddit.com`, `redd.it`, and every subdomain) are rejected as `unsupported_platform` in every activity mode, `legacy_scout` included; they never reach legacy Scout.
- Instagram, X, and YouTube stay `legacy` in this sub-project.
- Text-only posts are first-class: a v3 report may carry `media: []` when `post.text` is non-blank.
- `SourceReport` v3: `schema_version` 3, `media` 0–20 items indexed 1..N, `SourcePost.post_id` matches `^[A-Za-z0-9_-]{1,64}$`, `SourcePost.text` at most 50,000 characters. v1/v2 `TikTokSourceReport` still validates.
- Image media: JPEG, PNG, or WebP; 1,000 bytes to 20 MiB. Video media: MP4 (`ftyp`), 10,000 bytes to 500 MiB. The sniffed magic bytes are authoritative for `media_type` and the file suffix.
- New attempt strategy `scrapling_request`; new reasons and failure codes `request_timeout`, `request_blocked`, `request_incomplete` (fallback-eligible and retryable, like `headless_*`); new non-eligible failure codes `invalid_source_url` and `no_content`.
- Stage names are `<platform>_<method>`; existing TikTok names (`tiktok_headless`, `tiktok_cdn`, `tiktok_cleanup`) stay identical.
- No runtime request→headless fallback: a Threads content attempt uses exactly one method (`CONTENT_METHOD`). The post card is always a headless crop and only for non-video posts; a failed crop is simply absent.
- No live network in the test suite. Never weaken the conftest `_offline_unless_live` guard. Scrapling is not installed in the test environment; tests inject fakes.
- The Threads live capture (Task 10) needs the operator's explicit authorization at capture time. It is a HARD STOP.
- Raw captures, card PNGs, and URL lists stay under `D:/thoth-tmp/bu/threads/`; never commit, print, or describe them. Restricted evidence is reported as counts, keys, and enums only.
- Repository artifacts in English. Commits: exactly one `git commit -m "<subject>"`, subject ≤72 characters, no body, no trailer, no AI attribution.
- Never stage `graphify-out/`, `build_log.txt`, `.superpowers/`, `.understand-anything/`, `.env.stage1.local.bak-*`, or anything under `design/`. `docs/superpowers/` needs `git add -f`.
- Python source, tests, the spec, and this plan are LF. `CHANGELOG.md`, `docs/python-scout-migration-roadmap.md`, and `.superpowers/sdd/2026-09-23-python-scout-migration-program/progress.md` are CRLF: edit them only with a Python binary script (`read_bytes`, assert the file ends with `b"\r\n"`, append `section.replace("\n", "\r\n").encode()`).
- Test command (run from the repo root in Git Bash; paths are relative to `python/`): `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh <pytest args>`. Ruff: `wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff check . && ~/.local/bin/uvx ruff format --check .'`.
- This plan changes no Rust file, so `build_cuda.bat` is not part of its verification; if a task does touch Rust, run it per `AGENTS.md`.

## Refinements to the spec (binding for this plan)

- (a) `platform_support`, `platform_of`, and the host tables live in the pure `acquisition/platforms.py`, not in the registry, so the workflow sandbox and the API import no browser code.
- (b) The `Acquirer` protocol carries only `inspect`; `platforms.py` is the single routing table, so acquirers carry no `platform`/`hosts` attributes.
- (c) Acquirers own and close their browsers (TikTok's service already closes in `finally`); the runner builds only the shared `httpx.AsyncClient` and `MediaMaterializer`.
- (d) Threads parsers are pure in `acquisition/adapters/threads.py`; fetchers and the acquirer are in `acquisition/threads_service.py`.
- (e) One `CONTENT_METHOD` constant covers post and media. Under `headless`, the card is cropped during the same visit; under `request`, a separate best-effort headless visit crops it. Either way it is kept only for non-video posts.
- (f) The activity returns `unsupported_platform` with no events when `platform_of` is `None`, before the capability gate.
- (g) `ResolvedMedia.media_type` becomes `Literal["video/mp4"] | None`; images pass `None` and the sniffed type wins.
- (h) The method comparison (`counts`, `decide`) lives in `operations/threads_fixture.py`; the fixtures record per-method counts so a test pins `CONTENT_METHOD` to the evidence.

## Review Focus

1. A Threads URL with a query string, a trailing slash, or a `threads.net`/`m.` host is accepted and canonicalized to `https://www.threads.com/@<owner>/post/<code>` — Task 7 `test_canonicalize_threads_post_url_accepts_variants`.
2. Facebook hosts with mixed case, a trailing dot, or an `m.`/`web.` prefix are rejected, while a lookalike (`notfacebook.com`) is not — Task 1 `test_platform_support_classifies_hosts`.
3. A carousel with more than 20 items is capped at 20, not failed — Task 8 `test_carousel_is_capped_at_twenty`.
4. A mid-carousel materialization failure leaves no orphan media files — Task 8 `test_mid_carousel_failure_leaves_no_orphans`.
5. A whitespace-only post with no media fails as `no_content`, not a `ValidationError` crash — Task 8 `test_whitespace_only_post_is_no_content`.

## File Structure

- Create `python/src/thoth_control_plane/acquisition/platforms.py` — pure URL→platform routing.
- Modify `python/src/thoth_control_plane/acquisition/models.py` — v3 report, media kinds, new enums, neutral result types.
- Modify `python/src/thoth_control_plane/acquisition/materializer.py` — magic-byte sniffing, per-kind bounds, indexed media.
- Modify `python/src/thoth_control_plane/acquisition/service.py` — TikTok writes v3; shared attempt helpers.
- Create `python/src/thoth_control_plane/acquisition/registry.py` — `Acquirer` protocol and `acquirer_for`.
- Modify `python/src/thoth_control_plane/activities/source_investigation.py` — neutral types, platform stage names, registry runner.
- Modify `python/src/thoth_control_plane/domain/models.py` — event reasons and fallback-eligible codes.
- Modify `python/src/thoth_control_plane/workflows/source_investigation.py` — platform guard.
- Modify `python/src/thoth_control_plane/application/workflows.py`, `application/__init__.py`, `api/app.py` — intake rejection.
- Create `python/src/thoth_control_plane/acquisition/adapters/threads.py` — Threads URL identity and parsers.
- Create `python/src/thoth_control_plane/acquisition/threads_service.py` — request fetcher, headless browser, acquirer.
- Create `python/src/thoth_control_plane/operations/threads_capture.py` — operator-run live capture.
- Create `python/src/thoth_control_plane/operations/threads_fixture.py` — sanitizer, leak check, method comparison.
- Modify `python/src/thoth_control_plane/operations/tiktok_parity.py` — read v3 reports.
- Tests and fixtures under `python/tests/` as named per task.

---

### Task 1: Pure platform routing

**Files:**
- Create: `python/src/thoth_control_plane/acquisition/platforms.py`
- Test: `python/tests/acquisition/test_platforms.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `bare_host(host: str) -> str`; `PYTHON_PLATFORM_HOSTS: dict[str, frozenset[str]]` (keys `"tiktok"`, `"threads"`); `UNSUPPORTED_DOMAINS: tuple[str, ...]`; `platform_of(url: str) -> str | None`; `platform_support(url: str) -> Literal["python", "legacy", "unsupported"]`. Stdlib-only imports.

- [ ] **Step 1: Write the failing test**

```python
"""URL-to-platform routing is pure and conservative."""

from __future__ import annotations

import pytest

from thoth_control_plane.acquisition.platforms import platform_of, platform_support


@pytest.mark.parametrize(
    ("url", "support"),
    [
        ("https://www.facebook.com/story.php?id=1", "unsupported"),
        ("https://m.facebook.com/watch/?v=1", "unsupported"),
        ("https://WEB.Facebook.COM./reel/1", "unsupported"),
        ("https://fb.watch/abc/", "unsupported"),
        ("https://fb.com/x", "unsupported"),
        ("https://old.reddit.com/r/x/comments/abc/", "unsupported"),
        ("https://redd.it/abc", "unsupported"),
        ("https://notfacebook.com/x", "legacy"),
        ("https://www.instagram.com/p/abc/", "legacy"),
        ("https://x.com/a/status/1", "legacy"),
        ("https://www.youtube.com/watch?v=abc", "legacy"),
        ("https://example.test/post", "legacy"),
        ("https://[::1", "legacy"),
        ("https://www.tiktok.com/@a/video/1234567", "python"),
        ("https://m.tiktok.com/@a/video/1234567", "python"),
        ("https://vm.tiktok.com/ZMabc/", "python"),
        ("https://vt.tiktok.com/ZSabc/", "python"),
        ("https://www.threads.net/@a/post/B", "python"),
        ("https://threads.com/@a/post/B", "python"),
        ("https://www.Threads.COM./@a/post/B", "python"),
    ],
)
def test_platform_support_classifies_hosts(url: str, support: str) -> None:
    assert platform_support(url) == support


def test_platform_of_names_python_platforms_only() -> None:
    assert platform_of("https://www.tiktok.com/@a/video/1234567") == "tiktok"
    assert platform_of("https://www.threads.net/@a/post/B") == "threads"
    assert platform_of("https://www.instagram.com/p/abc/") is None
    assert platform_of("https://www.facebook.com/x") is None
    assert platform_of("not a url") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_platforms.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'thoth_control_plane.acquisition.platforms'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Pure URL-to-platform routing shared by the API, the workflow guard, and the activity.

Stdlib only: the Temporal workflow sandbox imports this module, so it must never pull in
browser or HTTP code.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

PYTHON_PLATFORM_HOSTS: dict[str, frozenset[str]] = {
    "tiktok": frozenset({"tiktok.com", "vm.tiktok.com", "vt.tiktok.com"}),
    "threads": frozenset({"threads.net", "threads.com"}),
}
# Rejected in every mode by operator decision; never routed to legacy Scout.
UNSUPPORTED_DOMAINS = ("facebook.com", "fb.com", "fb.watch", "reddit.com", "redd.it")


def bare_host(host: str) -> str:
    """Lowercase, drop a trailing dot, then drop one `www.` or `m.` prefix."""
    host = host.lower().rstrip(".")
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            return host[len(prefix) :]
    return host


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def platform_of(url: str) -> str | None:
    host = bare_host(_host(url))
    for platform, hosts in PYTHON_PLATFORM_HOSTS.items():
        if host in hosts:
            return platform
    return None


def platform_support(url: str) -> Literal["python", "legacy", "unsupported"]:
    host = _host(url)
    if any(host == domain or host.endswith("." + domain) for domain in UNSUPPORTED_DOMAINS):
        return "unsupported"
    return "python" if platform_of(url) is not None else "legacy"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_platforms.py`
Expected: PASS (21 passed)

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/platforms.py python/tests/acquisition/test_platforms.py
git commit -m "feat(acquisition): add pure platform routing"
```

---

### Task 2: Platform-neutral contracts

**Files:**
- Modify: `python/src/thoth_control_plane/acquisition/models.py`
- Test: `python/tests/acquisition/test_models.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces (all in `acquisition/models.py`):
  - `AcquisitionStrategy.SCRAPLING_REQUEST = "scrapling_request"`; `AcquisitionReason.REQUEST_TIMEOUT/REQUEST_BLOCKED/REQUEST_INCOMPLETE` (values `request_timeout`, `request_blocked`, `request_incomplete`).
  - `MAX_MEDIA_ITEMS = 20`, `MAX_POST_TEXT = 50_000`, `SafeId`, `MediaKind = Literal["video", "image"]`, `MediaType = Literal["video/mp4", "image/jpeg", "image/png", "image/webp"]`, `MEDIA_TYPES: dict[str, frozenset[str]]`, `MEDIA_BYTE_BOUNDS: dict[str, tuple[int, int]]`.
  - `ResolvedMedia.kind: MediaKind = "video"`, `ResolvedMedia.media_type: Literal["video/mp4"] | None = "video/mp4"`.
  - `MaterializedMedia.kind: MediaKind`, `.index: int` (1..20), `.media_type: MediaType`, validated per kind.
  - `SourcePost(post_id, owner_handle, text, published_at, engagement)`, `ReportSource(platform, canonical_url)`, `SourceReport` (v3), `AcquisitionFailure`, `AcquisitionResult`.
  - `TikTokAcquisitionFailure`/`TikTokAcquisitionResult` stay until Task 4 deletes them.

- [ ] **Step 1: Write the failing tests** (append to `tests/acquisition/test_models.py`; add the new names to its import block from `thoth_control_plane.acquisition.models`: `AcquisitionFailure`, `AcquisitionResult`, `MaterializedMedia`, `SourceReport`, and `from pathlib import PurePosixPath`, `from pydantic import ValidationError` if absent)

```python
_CHECKSUM = "sha256:" + "0" * 64


def _media(index: int, kind: str, media_type: str, bytes_: int) -> MaterializedMedia:
    suffix = {"video/mp4": "mp4", "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
    return MaterializedMedia(
        media_id=f"media_{index}",
        kind=kind,
        index=index,
        location=PurePosixPath(f"reports/wf_contract_001/media/m{index}.{suffix[media_type]}"),
        media_type=media_type,
        bytes=bytes_,
        checksum=_CHECKSUM,
        acquisition_strategy="scrapling_request",
    )


def _image(index: int, bytes_: int = 5_000, media_type: str = "image/jpeg") -> MaterializedMedia:
    return _media(index, "image", media_type, bytes_)


def _v3(**overrides: object) -> SourceReport:
    data: dict[str, object] = {
        "workflow_id": "wf_contract_001",
        "source": {
            "platform": "threads",
            "canonical_url": "https://www.threads.com/@user_001/post/code_001",
        },
        "post": {"post_id": "code_001", "owner_handle": "user_001", "text": "hello"},
        "media": [],
        "outcome": {
            "attempts": [
                {
                    "strategy": "scrapling_request",
                    "status": "succeeded",
                    "attempt_count": 1,
                    "elapsed_ms": 5,
                }
            ]
        },
    }
    data.update(overrides)
    return SourceReport.model_validate(data)


def test_v3_accepts_a_text_only_post() -> None:
    report = _v3()
    assert report.schema_version == 3
    assert report.media == []
    assert report.post_card is None


def test_v3_accepts_ordered_images() -> None:
    report = _v3(media=[_image(1), _image(2, media_type="image/png")])
    assert [item.index for item in report.media] == [1, 2]


def test_v3_rejects_a_post_with_neither_text_nor_media() -> None:
    with pytest.raises(ValidationError):
        _v3(post={"post_id": "code_001", "owner_handle": "user_001", "text": "  \n "})


@pytest.mark.parametrize("indexes", [[2], [1, 1], [2, 1]])
def test_v3_rejects_out_of_order_media(indexes: list[int]) -> None:
    with pytest.raises(ValidationError):
        _v3(media=[_image(index) for index in indexes])


def test_v3_rejects_more_than_twenty_media() -> None:
    with pytest.raises(ValidationError):
        _v3(media=[_image(index) for index in range(1, 22)])


@pytest.mark.parametrize(
    "post",
    [
        {"post_id": "code/001", "owner_handle": "user_001", "text": "x"},
        {"post_id": "code_001", "owner_handle": "user_001", "text": "x" * 50_001},
    ],
)
def test_v3_rejects_unsafe_post_fields(post: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        _v3(post=post)


@pytest.mark.parametrize(
    ("kind", "media_type", "bytes_"),
    [
        ("image", "image/jpeg", 999),
        ("image", "image/jpeg", 20 * 1024 * 1024 + 1),
        ("image", "video/mp4", 5_000),
        ("video", "image/jpeg", 20_000),
        ("video", "video/mp4", 5_000),
    ],
)
def test_materialized_media_bounds_follow_the_kind(kind: str, media_type: str, bytes_: int) -> None:
    with pytest.raises(ValidationError):
        _media(1, kind, media_type, bytes_)


def test_v1_and_v2_reports_still_reject_images() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["media"] = [_image(1).model_dump(mode="json")]
    with pytest.raises(ValidationError):
        TikTokSourceReport.model_validate(payload)


@pytest.mark.parametrize(
    "code", ["invalid_source_url", "no_content", "request_blocked", "request_timeout"]
)
def test_neutral_failure_accepts_new_codes(code: str) -> None:
    assert AcquisitionFailure(code=code, retryable=False).code == code


def test_neutral_result_requires_exactly_one_outcome() -> None:
    with pytest.raises(ValidationError):
        AcquisitionResult()
    with pytest.raises(ValidationError):
        AcquisitionResult(report=_v3(), failure=AcquisitionFailure(code="no_content", retryable=False))
```

`FIXTURE_PATH` must name `tests/fixtures/tiktok/normalized_report.json`; if the module uses another constant name for that path, use it and ledger the substitution.

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_models.py`
Expected: FAIL with `ImportError: cannot import name 'AcquisitionFailure'`

- [ ] **Step 3: Implement**

In `models.py`:

1. Add the constants and types after `PublishedAt`:

```python
MAX_MEDIA_ITEMS = 20
MAX_POST_TEXT = 50_000
SafeId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
MediaKind = Literal["video", "image"]
MediaType = Literal["video/mp4", "image/jpeg", "image/png", "image/webp"]
MEDIA_TYPES: dict[str, frozenset[str]] = {
    "video": frozenset({"video/mp4"}),
    "image": frozenset({"image/jpeg", "image/png", "image/webp"}),
}
MEDIA_BYTE_BOUNDS: dict[str, tuple[int, int]] = {
    "video": (10_000, 500 * 1024 * 1024),
    "image": (1_000, 20 * 1024 * 1024),
}
```

2. `AcquisitionStrategy` gains `SCRAPLING_REQUEST = "scrapling_request"`. `AcquisitionReason` gains `REQUEST_TIMEOUT = "request_timeout"`, `REQUEST_BLOCKED = "request_blocked"`, `REQUEST_INCOMPLETE = "request_incomplete"` (after the `HEADLESS_*` members).

3. `ResolvedMedia`:

```python
class ResolvedMedia(StrictModel):
    kind: MediaKind = "video"
    ephemeral_url: SecretStr = Field(exclude=True, repr=False)
    # Images carry None: the materializer's magic-byte sniff decides their type.
    media_type: Literal["video/mp4"] | None = "video/mp4"
    duration_seconds: Annotated[float, Field(ge=0)] | None = None
    request_context: MediaRequestContext | None = Field(default=None, exclude=True, repr=False)
```

4. `MaterializedMedia`:

```python
class MaterializedMedia(StrictModel):
    media_id: OpaqueId
    kind: MediaKind = "video"
    index: Annotated[int, Field(ge=1, le=MAX_MEDIA_ITEMS)] = 1
    location: SafeRelativeLocation
    media_type: MediaType = "video/mp4"
    bytes: Annotated[int, Field(ge=1_000, le=524_288_000)]
    checksum: Checksum
    acquisition_strategy: AcquisitionStrategy
    width: Annotated[int, Field(gt=0)] | None = None
    height: Annotated[int, Field(gt=0)] | None = None
    duration_seconds: Annotated[float, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def match_kind(self) -> MaterializedMedia:
        low, high = MEDIA_BYTE_BOUNDS[self.kind]
        if self.media_type not in MEDIA_TYPES[self.kind] or not low <= self.bytes <= high:
            raise ValueError("media type and size must match the media kind")
        return self
```

5. `TikTokSourceReport.keep_v1_free_of_enrichment` also pins its single media item:

```python
    @model_validator(mode="after")
    def keep_v1_free_of_enrichment(self) -> TikTokSourceReport:
        if self.schema_version == 1 and (self.comments or self.profile_card is not None):
            raise ValueError("schema_version 1 reports carry no comments or cards")
        if any(item.kind != "video" or item.index != 1 for item in self.media):
            raise ValueError("schema_version 1 and 2 reports carry one video at index 1")
        return self
```

6. After `TikTokAcquisitionResult`, add:

```python
class SourcePost(StrictModel):
    post_id: SafeId
    owner_handle: TikTokHandle
    text: Annotated[str, Field(max_length=MAX_POST_TEXT)] = ""
    published_at: PublishedAt | None = None
    engagement: dict[str, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)


class ReportSource(StrictModel):
    platform: Literal["tiktok", "threads"]
    canonical_url: HttpUrl


class SourceReport(StrictModel):
    """Platform-neutral report (schema 3): a text-only post carries an empty media list."""

    schema_version: Literal[3] = 3
    workflow_id: OpaqueId
    source: ReportSource
    post: SourcePost
    media: list[MaterializedMedia] = Field(default_factory=list, max_length=MAX_MEDIA_ITEMS)
    outcome: AcquisitionOutcome
    comments: list[ReportComment] = Field(default_factory=list, max_length=MAX_COMMENTS)
    post_card: CardArtifact | None = None
    profile_card: CardArtifact | None = None

    @model_validator(mode="after")
    def require_ordered_content(self) -> SourceReport:
        if [item.index for item in self.media] != list(range(1, len(self.media) + 1)):
            raise ValueError("media indexes must run 1..N in order")
        if not self.media and not self.post.text.strip():
            raise ValueError("a post needs text or media")
        return self


class AcquisitionFailure(StrictModel):
    code: Literal[
        "invalid_tiktok_url",
        "invalid_source_url",
        "unsupported_platform",
        "headless_timeout",
        "headless_blocked",
        "headless_incomplete",
        "request_timeout",
        "request_blocked",
        "request_incomplete",
        "cdn_rate_limited",
        "cdn_unavailable",
        "media_validation_failed",
        "no_content",
        "artifact_persistence_failed",
        "acquisition_dependency_unavailable",
    ]
    retryable: bool
    attempts: Annotated[list[AcquisitionAttempt], Field(max_length=3)] = Field(default_factory=list)


class AcquisitionResult(StrictModel):
    report: SourceReport | None = None
    failure: AcquisitionFailure | None = None

    @model_validator(mode="after")
    def require_exactly_one_outcome(self) -> AcquisitionResult:
        if (self.report is None) == (self.failure is None):
            raise ValueError("acquisition result requires exactly one outcome")
        return self
```

7. Update the module docstring to `"""Strict, serializable acquisition contracts: single-post reports and TikTok discovery."""`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition`
Expected: PASS (whole `tests/acquisition` directory green; the TikTok model, service, and materializer tests are unaffected)

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/models.py python/tests/acquisition/test_models.py
git commit -m "feat(acquisition): add platform-neutral v3 source report"
```

---

### Task 3: Image-aware materializer

**Files:**
- Modify: `python/src/thoth_control_plane/acquisition/materializer.py`
- Test: `python/tests/acquisition/test_materializer.py` (append)

**Interfaces:**
- Consumes: Task 2 `MEDIA_BYTE_BOUNDS`, `MEDIA_TYPES`, `MaterializedMedia`, `ResolvedMedia.kind`.
- Produces: `MediaMaterializer.materialize(candidate, destination, relative_location, strategy, *, media_id: str = "media_1", index: int = 1) -> MaterializedMedia`. The written file and `result.location` get the suffix of the sniffed type (`.mp4`, `.jpg`, `.png`, `.webp`), replacing any suffix the caller passed. `MIN_MEDIA_BYTES`/`MAX_MEDIA_BYTES` stay exported (video bounds).

- [ ] **Step 1: Write the failing tests** (append; reuse the module's existing `public_resolver` helper and `MP4_BODY` constant; add `ResolvedMedia` and `PNG_SIGNATURE` imports if absent)

```python
JPEG_BODY = b"\xff\xd8\xff\xe0" + b"0" * 5_000
PNG_BODY = PNG_SIGNATURE + b"0" * 5_000
WEBP_BODY = b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 5_000


def _candidate(kind: str) -> ResolvedMedia:
    return ResolvedMedia(
        kind=kind,
        ephemeral_url="https://cdn.example.test/item",
        media_type="video/mp4" if kind == "video" else None,
    )


async def _materialize(tmp_path: Path, kind: str, body: bytes, name: str = "threads-x-2"):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    async with httpx.AsyncClient(transport=transport) as client:
        return await MediaMaterializer(client, public_resolver).materialize(
            _candidate(kind),
            tmp_path / name,
            PurePosixPath("reports/wf/media") / name,
            "scrapling_request",
            media_id="media_2",
            index=2,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "media_type", "suffix"),
    [(JPEG_BODY, "image/jpeg", ".jpg"), (PNG_BODY, "image/png", ".png"), (WEBP_BODY, "image/webp", ".webp")],
)
async def test_materialize_names_images_by_sniffed_type(
    tmp_path: Path, body: bytes, media_type: str, suffix: str
) -> None:
    result = await _materialize(tmp_path, "image", body)

    assert result.kind == "image"
    assert result.media_type == media_type
    assert (result.media_id, result.index) == ("media_2", 2)
    assert result.location == PurePosixPath(f"reports/wf/media/threads-x-2{suffix}")
    assert (tmp_path / f"threads-x-2{suffix}").read_bytes() == body
    assert sorted(path.name for path in tmp_path.iterdir()) == [f"threads-x-2{suffix}"]


@pytest.mark.asyncio
async def test_materialize_keeps_the_tiktok_video_name(tmp_path: Path) -> None:
    result = await _materialize(tmp_path, "video", MP4_BODY, name="tiktok-1234567.mp4")
    assert result.location == PurePosixPath("reports/wf/media/tiktok-1234567.mp4")
    assert (tmp_path / "tiktok-1234567.mp4").read_bytes() == MP4_BODY


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "body"),
    [
        ("image", MP4_BODY),
        ("video", JPEG_BODY),
        ("image", b"GIF89a" + b"0" * 5_000),
        ("image", b"\xff\xd8\xff" + b"0" * 996),
        ("image", b"\xff\xd8\xff\xe0" + b"0" * (20 * 1024 * 1024)),
    ],
)
async def test_materialize_rejects_mismatched_or_out_of_bounds_media(
    tmp_path: Path, kind: str, body: bytes
) -> None:
    with pytest.raises(MediaMaterializationError):
        await _materialize(tmp_path, kind, body)
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_materializer.py`
Expected: FAIL with `TypeError: ... got an unexpected keyword argument 'media_id'`

- [ ] **Step 3: Implement**

In `materializer.py`:

1. Docstring line 1: `"""SSRF-safe, atomic streaming download of a resolved media URL."""`.
2. Imports: add `from thoth_control_plane.acquisition.cards import PNG_SIGNATURE` and `MEDIA_BYTE_BOUNDS`, `MEDIA_TYPES` to the models import.
3. After `_HEADER_PROBE_BYTES = 12` add:

```python
_SUFFIXES = {"video/mp4": ".mp4", "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def _sniff(header: bytes) -> str | None:
    """The media type the leading bytes prove, else None; declared types are never trusted."""
    if header[_FTYP_OFFSET : _FTYP_OFFSET + len(_FTYP_MAGIC)] == _FTYP_MAGIC:
        return "video/mp4"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(PNG_SIGNATURE):
        return "image/png"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    return None
```

4. `materialize` signature gains `*, media_id: str = "media_1", index: int = 1`. At the top: `low, high = MEDIA_BYTE_BOUNDS[candidate.kind]`. Replace both `MAX_MEDIA_BYTES` comparisons inside the method (Content-Length and streaming) with `high`.
5. Replace the block from the `ftyp` check through `return result` with:

```python
            media_type = _sniff(header) if len(header) >= _HEADER_PROBE_BYTES else None
            if media_type not in MEDIA_TYPES[candidate.kind] or total_bytes < low:
                raise MediaMaterializationError()

            try:
                suffix = _SUFFIXES[media_type]
                final_destination = destination.with_suffix(suffix)
                result = MaterializedMedia(
                    media_id=media_id,
                    kind=candidate.kind,
                    index=index,
                    location=relative_location.with_suffix(suffix),
                    media_type=media_type,
                    bytes=total_bytes,
                    checksum=f"sha256:{digest.hexdigest()}",
                    acquisition_strategy=acquisition_strategy,
                    duration_seconds=candidate.duration_seconds,
                )
            except ValueError:
                # ValidationError is a ValueError; so is `with_suffix` on a bare `..`.
                raise MediaMaterializationError() from None

            os.replace(part_path, final_destination)
            return result
```

`MIN_MEDIA_BYTES` and `MAX_MEDIA_BYTES` stay defined (imported by existing tests).

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition`
Expected: PASS (all existing materializer and service tests still green)

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/materializer.py python/tests/acquisition/test_materializer.py
git commit -m "feat(acquisition): materialize sniffed images alongside video"
```

---

### Task 4: TikTok writes SourceReport v3

**Files:**
- Create: `python/tests/fixtures/tiktok/source_report_v3.json`
- Modify: `python/src/thoth_control_plane/acquisition/models.py` (delete `TikTokAcquisitionFailure`, `TikTokAcquisitionResult`)
- Modify: `python/src/thoth_control_plane/acquisition/service.py`
- Modify: `python/src/thoth_control_plane/activities/source_investigation.py` (types and cleanup only)
- Modify: `python/src/thoth_control_plane/operations/tiktok_parity.py`
- Modify tests: `tests/acquisition/test_models.py`, `tests/acquisition/test_service.py`, `tests/activities/test_source_investigation.py`, `tests/integration/test_control_plane_smoke.py`, `tests/workflows/test_source_investigation.py`, `tests/operations/test_tiktok_parity.py`

**Interfaces:**
- Consumes: Task 2 `SourceReport`, `SourcePost`, `ReportSource`, `AcquisitionResult`, `AcquisitionFailure`.
- Produces: `TikTokAcquisitionService.inspect(...) -> AcquisitionResult` whose report is `SourceReport` v3 with `source.platform == "tiktok"` and `post.text` = the TikTok caption. `AcquisitionRunner = Callable[[str, str, Path], Awaitable[AcquisitionResult]]`. The v3 fixture path `tests/fixtures/tiktok/source_report_v3.json`.

- [ ] **Step 1: Create the v3 fixture from the v1 fixture**

Run from the repo root:

```bash
cd python && python - <<'PY'
import json
from pathlib import Path

source = Path("tests/fixtures/tiktok/normalized_report.json")
report = json.loads(source.read_text(encoding="utf-8"))
report["schema_version"] = 3
report["post"]["text"] = report["post"].pop("caption", "")
report["comments"] = []
report["post_card"] = None
report["profile_card"] = None
Path("tests/fixtures/tiktok/source_report_v3.json").write_bytes(
    (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
)
PY
```

Expected: the new file exists, LF line endings (`write_bytes` of `\n` text), and `python -c "import json;print(json.load(open('tests/fixtures/tiktok/source_report_v3.json'))['schema_version'])"` prints `3`.

- [ ] **Step 2: Migrate the tests to the neutral types (they become the failing tests)**

Apply exactly these edits (line numbers are from `a55524b`; match on the quoted text):

- `tests/acquisition/test_models.py`: replace imports of `TikTokAcquisitionResult`/`TikTokAcquisitionFailure` with `AcquisitionResult`/`AcquisitionFailure`. The result tests near lines 86-89 validate `tests/fixtures/tiktok/source_report_v3.json` with `SourceReport.model_validate_json` and wrap it in `AcquisitionResult(report=...)`. The failure usages near lines 123 and 141 become `AcquisitionFailure`. Keep the v1/v2 `TikTokSourceReport` tests.
- `tests/acquisition/test_service.py`: rename the imports as above; `.post.caption` on a service result (near lines 160 and 272) becomes `.post.text`; `schema_version == 2` (near line 693) becomes `== 3`; add `assert result.report.source.platform == "tiktok"` beside that assertion. `resolution.post.caption` (a TikWM `TikTokPost`, near lines 456 and 519) stays.
- `tests/activities/test_source_investigation.py`: imports; `FIXTURE_PATH` points to `source_report_v3.json`; `_load_fixture_report` validates `SourceReport`; every `TikTokAcquisitionResult(` becomes `AcquisitionResult(` and every `TikTokAcquisitionFailure(` becomes `AcquisitionFailure(`. The card test near lines 595-630 drops `"schema_version": 2` from its `update=` and additionally sets a `post_card` built the same way as its profile card at `reports/<wf>/cards/post.png`; it asserts the persistence-failure cleanup removes the post card file too.
- `tests/integration/test_control_plane_smoke.py` and `tests/workflows/test_source_investigation.py`: `_FIXTURE_REPORT_PATH` points to `source_report_v3.json`; the offline runners use `SourceReport.model_validate_json(...)` and return `AcquisitionResult(report=report)`; imports follow.
- `tests/operations/test_tiktok_parity.py`: add `_V3_FIXTURE = _FIXTURE.parent / "source_report_v3.json"`, give `_pair` a `fixture: Path = _FIXTURE` parameter used where it reads `_FIXTURE`, and add:

```python
def test_parity_accepts_a_v3_python_report(tmp_path: Path) -> None:
    assert compare_parity_sample(**_pair(tmp_path, fixture=_V3_FIXTURE)).passed is True
```

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition tests/activities tests/operations/test_tiktok_parity.py`
Expected: FAIL (the service still returns `TikTokSourceReport`; `.post.text` and `schema_version == 3` assertions fail; the activity card test fails on `post_card`).

- [ ] **Step 3: Implement**

`service.py`:
- Imports: drop `TikTokAcquisitionFailure`, `TikTokAcquisitionResult`, `TikTokSource`, `TikTokSourceReport`; add `AcquisitionFailure`, `AcquisitionResult`, `ReportSource`, `SourcePost`, `SourceReport`.
- `_build_report` returns `SourceReport`:

```python
    return SourceReport(
        workflow_id=workflow_id,
        source=ReportSource(platform="tiktok", canonical_url=canonical_url),
        post=SourcePost(
            post_id=post.post_id,
            owner_handle=post.owner_handle,
            text=post.caption,
            published_at=post.published_at,
            engagement=post.engagement,
        ),
        media=[materialized],
        outcome=AcquisitionOutcome(attempts=attempts),
        comments=comments,
        profile_card=profile_card,
    )
```

- Every `TikTokAcquisitionResult(` → `AcquisitionResult(`, every `TikTokAcquisitionFailure(` → `AcquisitionFailure(`, and `inspect`'s return annotation → `AcquisitionResult`.

`models.py`: delete `TikTokAcquisitionFailure` and `TikTokAcquisitionResult`.

`activities/source_investigation.py`:
- Imports: `AcquisitionResult` and `SourceReport` replace `TikTokAcquisitionResult` and `TikTokSourceReport`.
- `AcquisitionRunner = Callable[[str, str, Path], Awaitable[AcquisitionResult]]`; the runner's `run` return annotation follows.
- `_cleanup_after_persistence_failure(part_path: Path, report: SourceReport, artifact_root: Path)`; after the profile card lines add:

```python
    if report.post_card is not None:
        locations.append(report.post_card.location)
```

- The `assert report is not None` comment names `AcquisitionResult`.

`operations/tiktok_parity.py`:
- Import `SourceReport` beside `TikTokSourceReport`; at the Python-report validation site (near line 427) use a module-level `_PYTHON_REPORT = TypeAdapter(TikTokSourceReport | SourceReport)` and `_PYTHON_REPORT.validate_json(python_text)` (import `TypeAdapter` from pydantic).
- Near line 170 read the caption as `payload["post"].get("text", payload["post"].get("caption"))`. `PARITY_FIELDS` keeps `"caption"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition tests/activities tests/operations tests/workflows tests/integration`
Expected: PASS. Then `rg -n "TikTokAcquisitionResult|TikTokAcquisitionFailure" python/` prints nothing.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/acquisition python/src/thoth_control_plane/activities/source_investigation.py python/src/thoth_control_plane/operations/tiktok_parity.py python/tests/fixtures/tiktok/source_report_v3.json python/tests/acquisition python/tests/activities python/tests/integration python/tests/workflows python/tests/operations/test_tiktok_parity.py
git commit -m "feat(acquisition): write tiktok reports as source report v3"
```

---

### Task 5: Registry runner and platform stage names

**Files:**
- Create: `python/src/thoth_control_plane/acquisition/registry.py`
- Modify: `python/src/thoth_control_plane/activities/source_investigation.py`
- Modify: `python/src/thoth_control_plane/domain/models.py` (`SOURCE_EVENT_REASONS`)
- Test: `python/tests/acquisition/test_registry.py` (create), `python/tests/activities/test_source_investigation.py` (append)

**Interfaces:**
- Consumes: Task 1 `platform_of`; Task 4 `AcquisitionResult`, `TikTokAcquisitionService`.
- Produces: `class Acquirer(Protocol): async def inspect(self, *, workflow_id: str, source_url: str, artifact_root: Path) -> AcquisitionResult`; `acquirer_for(source_url: str, *, client: httpx.AsyncClient, materializer: MediaMaterializer) -> Acquirer` (raises `LookupError` for a non-Python platform). Activity stage names `f"{platform}_{suffix}"` with suffixes `headless`, `cdn`, `request`, and `f"{platform}_cleanup"`.

- [ ] **Step 1: Write the failing tests**

`tests/acquisition/test_registry.py`:

```python
"""The registry maps a Python platform URL to its acquirer."""

from __future__ import annotations

import httpx
import pytest

from thoth_control_plane.acquisition.materializer import (
    MediaMaterializer,
    resolve_host_via_getaddrinfo,
)
from thoth_control_plane.acquisition.registry import acquirer_for
from thoth_control_plane.acquisition.service import TikTokAcquisitionService


@pytest.mark.asyncio
async def test_acquirer_for_routes_tiktok_and_refuses_legacy_hosts() -> None:
    async with httpx.AsyncClient() as client:
        materializer = MediaMaterializer(client, resolve_host_via_getaddrinfo)
        acquirer = acquirer_for(
            "https://www.tiktok.com/@a/video/1234567", client=client, materializer=materializer
        )
        assert isinstance(acquirer, TikTokAcquisitionService)
        with pytest.raises(LookupError):
            acquirer_for(
                "https://www.instagram.com/p/abc/", client=client, materializer=materializer
            )
```

Append to `tests/activities/test_source_investigation.py` (it already defines `INPUT` and `_settings(tmp_path)`):

```python
@pytest.mark.asyncio
async def test_unknown_platform_never_enters_the_runner(tmp_path: Path) -> None:
    calls: list[str] = []

    async def runner(workflow_id: str, source_url: str, artifact_root: Path) -> AcquisitionResult:
        calls.append(source_url)
        raise AssertionError("runner must not run")

    activity_fn = build_source_investigation_activity(_settings(tmp_path), runner=runner)
    result = await activity_fn(
        INPUT.model_copy(update={"canonical_source_url": "https://www.instagram.com/p/abc/"})
    )

    assert result.failure == SafeActivityError(code="unsupported_platform", retryable=False)
    assert result.events == []
    assert calls == []


@pytest.mark.asyncio
async def test_threads_attempts_use_platform_stage_names(tmp_path: Path) -> None:
    async def runner(workflow_id: str, source_url: str, artifact_root: Path) -> AcquisitionResult:
        attempt = AcquisitionAttempt(
            strategy=AcquisitionStrategy.SCRAPLING_REQUEST,
            status=AttemptStatus.FAILED,
            reason=AcquisitionReason.REQUEST_BLOCKED,
            attempt_count=1,
            elapsed_ms=5,
        )
        return AcquisitionResult(
            failure=AcquisitionFailure(code="request_blocked", retryable=True, attempts=[attempt])
        )

    activity_fn = build_source_investigation_activity(_settings(tmp_path), runner=runner)
    result = await activity_fn(
        INPUT.model_copy(
            update={"canonical_source_url": "https://www.threads.com/@user_001/post/code_001"}
        )
    )

    assert result.failure == SafeActivityError(code="request_blocked", retryable=True)
    assert [event.payload["stage"] for event in result.events] == [
        "threads_request",
        "threads_request",
        "threads_cleanup",
    ]
    assert result.events[1].payload["reason"] == "request_blocked"
```

Add any missing imports (`AcquisitionAttempt`, `AcquisitionFailure`, `AcquisitionReason`, `AcquisitionStrategy`, `AttemptStatus`, `SafeActivityError`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_registry.py tests/activities/test_source_investigation.py`
Expected: FAIL (`No module named '...registry'`; the unknown-platform test calls the runner; the Threads test raises `KeyError`/`ValidationError` on stage `tiktok_request` or reason `request_blocked`).

- [ ] **Step 3: Implement**

`acquisition/registry.py`:

```python
"""Map a Python-platform source URL to the acquirer that inspects it."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import httpx

from thoth_control_plane.acquisition.adapters.tikwm import TikWmResolver
from thoth_control_plane.acquisition.browser import ScraplingHeadlessBrowser
from thoth_control_plane.acquisition.materializer import MediaMaterializer
from thoth_control_plane.acquisition.models import AcquisitionResult
from thoth_control_plane.acquisition.platforms import platform_of
from thoth_control_plane.acquisition.service import TikTokAcquisitionService


class Acquirer(Protocol):
    """One platform's single-post acquisition; it owns and closes its own browser."""

    async def inspect(
        self, *, workflow_id: str, source_url: str, artifact_root: Path
    ) -> AcquisitionResult: ...


def acquirer_for(
    source_url: str, *, client: httpx.AsyncClient, materializer: MediaMaterializer
) -> Acquirer:
    platform = platform_of(source_url)
    if platform == "tiktok":
        return TikTokAcquisitionService(
            ScraplingHeadlessBrowser(), TikWmResolver(client), materializer
        )
    raise LookupError("no python acquirer for this platform")
```

`domain/models.py` `SOURCE_EVENT_REASONS` adds `"request_timeout"`, `"request_blocked"`, `"request_incomplete"`.

`activities/source_investigation.py`:
- Drop the now-unused `TikWmResolver`, `ScraplingHeadlessBrowser`, and `TikTokAcquisitionService` imports; add `from thoth_control_plane.acquisition.platforms import platform_of` and `from thoth_control_plane.acquisition.registry import acquirer_for`.
- Replace `_STAGE_NAMES` with:

```python
_STAGE_SUFFIXES: dict[AcquisitionStrategy, str] = {
    AcquisitionStrategy.SCRAPLING_HEADLESS: "headless",
    AcquisitionStrategy.TIKWM_CDN: "cdn",
    AcquisitionStrategy.SCRAPLING_REQUEST: "request",
}
```

- `build_production_acquisition_runner`'s docstring becomes "Build a fresh HTTP client and materializer per activity call; the acquirer owns its browser." and `run` becomes:

```python
    async def run(workflow_id: str, source_url: str, artifact_root: Path) -> AcquisitionResult:
        async with httpx.AsyncClient(follow_redirects=False) as client:
            materializer = MediaMaterializer(client, resolve_host_via_getaddrinfo)
            acquirer = acquirer_for(source_url, client=client, materializer=materializer)
            return await acquirer.inspect(
                workflow_id=workflow_id, source_url=source_url, artifact_root=artifact_root
            )
```

- `_attempt_events(attempts, platform: str)` uses `stage = f"{platform}_{_STAGE_SUFFIXES[attempt.strategy]}"`; `_cleanup_event(artifact_root, workflow_id, platform: str)` uses `"stage": f"{platform}_cleanup"`; `_terminal_events(attempts, artifact_root, workflow_id, platform: str)` passes it through.
- `_run` starts with:

```python
    platform = platform_of(str(input_.canonical_source_url))
    if platform is None:
        # The workflow guard routes only Python platforms here; anything else is
        # refused before the capability gate and never enters the runner.
        return SourceInvestigationActivityResult(
            failure=SafeActivityError(code="unsupported_platform", retryable=False)
        )
```

  and every `_terminal_events(...)` call in `_run` gains `, platform`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition tests/activities tests/workflows tests/integration`
Expected: PASS. A test that drives the real activity with an offline runner and a non-Python URL now gets `unsupported_platform`; if one fails that way, change its URL to a TikTok post URL that keeps every substring the test or `conftest.py` keys on (for example `retryable-failure`, `block-until-cancelled`, `signature=must-not-leak`) and ledger the migration. Task 6 migrates the known ones.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/registry.py python/src/thoth_control_plane/activities/source_investigation.py python/src/thoth_control_plane/domain/models.py python/tests/acquisition/test_registry.py python/tests/activities/test_source_investigation.py
git commit -m "feat(activities): route acquisition through the platform registry"
```

---

### Task 6: Unsupported-platform guard at intake and in the workflow

**Files:**
- Modify: `python/src/thoth_control_plane/domain/models.py` (`LEGACY_FALLBACK_ELIGIBLE_CODES`)
- Modify: `python/src/thoth_control_plane/workflows/source_investigation.py`
- Modify: `python/src/thoth_control_plane/application/workflows.py`, `python/src/thoth_control_plane/application/__init__.py`, `python/src/thoth_control_plane/api/app.py`
- Test: `python/tests/workflows/test_source_investigation.py`, `python/tests/api/test_workflows.py`, `python/tests/integration/test_control_plane_smoke.py`

**Interfaces:**
- Consumes: Task 1 `platform_support`.
- Produces: `UnsupportedPlatform(WorkflowApplicationError)` exported from `thoth_control_plane.application`; API 422 body `{"detail": {"code": "unsupported_platform"}}`; `LEGACY_FALLBACK_ELIGIBLE_CODES` includes `request_timeout`, `request_blocked`, `request_incomplete`.

- [ ] **Step 1: Write the failing tests**

`tests/workflows/test_source_investigation.py` — add beside the other routing activities:

```python
@activity.defn(name="inspect_source_candidates")
async def request_blocked_python_failure(input_: SourceInvestigationActivityInput):
    global PYTHON_CALLS
    PYTHON_CALLS += 1
    return SourceInvestigationActivityResult(failure={"code": "request_blocked", "retryable": True})
```

and append these rows to the `test_activity_mode_routing` parametrize list:

```python
        (
            "https://m.facebook.com/story.php?id=1",
            "python_tiktok_with_legacy_fallback",
            counted_python_success,
            "failed",
            "unsupported_platform",
            0,
            0,
        ),
        (
            "https://m.facebook.com/story.php?id=1",
            "python",
            counted_python_success,
            "failed",
            "unsupported_platform",
            0,
            0,
        ),
        (
            "https://m.facebook.com/story.php?id=1",
            "legacy_scout",
            counted_python_success,
            "failed",
            "unsupported_platform",
            0,
            0,
        ),
        (
            "https://www.reddit.com/r/x/comments/abc/",
            "python_tiktok_with_legacy_fallback",
            counted_python_success,
            "failed",
            "unsupported_platform",
            0,
            0,
        ),
        (
            "https://www.threads.com/@user_001/post/code_001",
            "python_tiktok_with_legacy_fallback",
            counted_python_success,
            "succeeded",
            None,
            1,
            0,
        ),
        (
            "https://www.threads.com/@user_001/post/code_001",
            "python_tiktok_with_legacy_fallback",
            request_blocked_python_failure,
            "succeeded",
            None,
            1,
            1,
        ),
        (
            "https://www.instagram.com/p/abc/",
            "python_tiktok_with_legacy_fallback",
            counted_python_success,
            "succeeded",
            None,
            0,
            1,
        ),
        (
            "https://www.instagram.com/p/abc/",
            "python",
            counted_python_success,
            "failed",
            "unsupported_platform",
            0,
            0,
        ),
```

`tests/api/test_workflows.py`:

```python
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url", ["https://m.facebook.com/story.php?id=1", "https://www.reddit.com/r/x/comments/abc/"]
)
async def test_unsupported_platform_is_rejected_before_any_workflow_starts(
    client: httpx.AsyncClient, gateway, url: str
) -> None:
    response = await client.post(
        "/api/v1/workflows",
        headers={**AUTH_HEADERS, "Idempotency-Key": "create-unsupported"},
        json={**VALID_REQUEST, "source": {**VALID_REQUEST["source"], "url": url}},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "unsupported_platform"}}
    assert gateway.workflows == {}
```

(If the `gateway` fixture records starts under another attribute than `workflows`, assert on that attribute and ledger it.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/workflows/test_source_investigation.py tests/api/test_workflows.py`
Expected: FAIL (Facebook rows reach legacy or Python; the Instagram `python` row calls the Python activity; the API returns 201/202 instead of 422; the Threads `request_blocked` row does not fall back because the code is not eligible yet).

- [ ] **Step 3: Implement**

`domain/models.py`: add `"request_timeout"`, `"request_blocked"`, `"request_incomplete"` to `LEGACY_FALLBACK_ELIGIBLE_CODES` and extend its docstring's list of eligible code families with the `request_*` codes.

`workflows/source_investigation.py`: inside the existing `workflow.unsafe.imports_passed_through()` block add `from thoth_control_plane.acquisition.platforms import platform_support` (and `SafeActivityError` from `domain.models` if not yet imported). Replace the head of `_execute_source_activity` (the two early `if` blocks) with:

```python
        support = platform_support(str(input_.source.display_url))
        if support == "unsupported":
            return SourceInvestigationActivityResult(
                failure=SafeActivityError(code="unsupported_platform", retryable=False)
            )
        if input_.activity_mode == "legacy_scout":
            return await self._execute_legacy_activity(input_)
        if support == "legacy":
            if input_.activity_mode == "python":
                return SourceInvestigationActivityResult(
                    failure=SafeActivityError(code="unsupported_platform", retryable=False)
                )
            return await self._execute_legacy_activity(input_)
```

Keep the rest (Python activity plus eligible fallback) unchanged, and add one docstring sentence: "Facebook and Reddit are refused in every mode before any activity runs; a legacy-only platform in `python` mode is refused the same way."

`application/workflows.py`: after `IdempotencyConflict` add

```python
class UnsupportedPlatform(WorkflowApplicationError):
    """The source URL belongs to a platform Thoth refuses in every mode."""

    default_detail = "unsupported_platform"
```

and make the first statement of `WorkflowService.start`:

```python
        if platform_support(str(request.source.url)) == "unsupported":
            raise UnsupportedPlatform
```

with `from thoth_control_plane.acquisition.platforms import platform_support` at the top. Export `UnsupportedPlatform` from `application/__init__.py` (import list and `__all__`, alphabetical).

`api/app.py`: import `UnsupportedPlatform` in the application import block and, after the `exception_statuses` loop, add

```python
    @app.exception_handler(UnsupportedPlatform)
    async def unsupported_platform_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": {"code": "unsupported_platform"}},
        )
```

Test URL migrations (these tests run the default `python` mode, where an `example.*` host is now refused):
- `tests/workflows/test_source_investigation.py` `VALID_IDENTIFY_REQUEST` URL → `https://www.tiktok.com/@creator/video/1234567890?signature=must-not-leak`.
- `tests/integration/test_control_plane_smoke.py` URLs (near lines 47, 97, 112, 163): `https://example.com/source/ready` → `https://www.tiktok.com/@ready/video/1000000001`, `.../retryable-failure` → `https://www.tiktok.com/@retryable-failure/video/1000000002`, `.../block-until-cancelled` → `https://www.tiktok.com/@block-until-cancelled/video/1000000003`, and the custom-root URL → `https://www.tiktok.com/@custom-root/video/1000000004`. Every substring `conftest.py` keys on survives.
- Any further failure of the same kind: `rg -n "https://example\.(test|com)" python/tests/workflows python/tests/integration` and migrate only URLs that run in `python` mode, keeping key substrings; ledger each.

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/workflows tests/integration tests/api tests/activities tests/application`
Expected: PASS (drop `tests/application` from the command if that directory does not exist).

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/domain/models.py python/src/thoth_control_plane/workflows/source_investigation.py python/src/thoth_control_plane/application python/src/thoth_control_plane/api/app.py python/tests/workflows python/tests/api python/tests/integration
git commit -m "feat(workflows): refuse facebook and reddit at intake and in routing"
```

---

### Task 7: Threads URL identity and pure parsers

**Files:**
- Create: `python/src/thoth_control_plane/acquisition/adapters/threads.py`
- Test: `python/tests/acquisition/test_threads_adapter.py`

**Interfaces:**
- Consumes: Task 1 `bare_host`, `PYTHON_PLATFORM_HOSTS`; Task 2 `SourcePost`, `ResolvedMedia`, `MAX_POST_TEXT`; `normalize._count`, `normalize._pick`, `normalize.published_at_from_epoch`.
- Produces: `ThreadsUrlError(ValueError)`; `ThreadsPostIdentity(canonical_url: HttpUrl, post_id: str, owner_handle: str)`; `canonicalize_threads_post_url(url: str) -> ThreadsPostIdentity`; `ThreadsParse(post: SourcePost, media: list[ResolvedMedia])`; `json_roots(texts: Iterable[str]) -> list[object]`; `find_post_node(roots: Iterable[object], code: str) -> dict | None`; `parse_documents(roots: Iterable[object], identity: ThreadsPostIdentity) -> ThreadsParse | None`. The JSON keys used (`code`, `user`, `caption.text`, `taken_at`, `like_count`, `text_post_app_info.*`, `carousel_media`, `video_versions`, `image_versions2.candidates`) are a hypothesis; Task 10 may change them by a ledgered ruling backed by the captured shape.

- [ ] **Step 1: Write the failing tests**

```python
"""Threads URL identity and pure post parsing over synthetic documents."""

from __future__ import annotations

import json

import pytest

from thoth_control_plane.acquisition.adapters.threads import (
    ThreadsUrlError,
    canonicalize_threads_post_url,
    json_roots,
    parse_documents,
)
from thoth_control_plane.acquisition.models import MAX_POST_TEXT

IDENTITY = canonicalize_threads_post_url("https://www.threads.com/@user_001/post/code_001")


def _node(**extra: object) -> dict[str, object]:
    return {
        "code": "code_001",
        "user": {"username": "user_001"},
        "caption": {"text": "hello world"},
        "taken_at": 1_700_000_000,
        "like_count": 12,
        "text_post_app_info": {
            "direct_reply_count": 3,
            "repost_count": 2,
            "quote_count": 1,
            "reshare_count": 4,
        },
        "image_versions2": {"candidates": []},
        **extra,
    }


def _doc(node: dict[str, object]) -> dict[str, object]:
    return {"require": [{"data": {"thread_items": [{"post": node}]}}]}


def _image(n: int) -> dict[str, object]:
    return {
        "image_versions2": {
            "candidates": [
                {"url": f"https://img.example.test/{n}-small.jpg", "width": 320, "height": 320},
                {"url": f"https://img.example.test/{n}-large.jpg", "width": 1080, "height": 1350},
            ]
        }
    }


@pytest.mark.parametrize(
    "url",
    [
        "https://www.threads.com/@user_001/post/code_001",
        "https://www.threads.net/@user_001/post/code_001/",
        "https://threads.net/@user_001/post/code_001?xmt=abc&slof=1",
        "https://m.threads.com/@user_001/post/code_001#frag",
        "https://WWW.THREADS.NET/@user_001/post/code_001",
    ],
)
def test_canonicalize_threads_post_url_accepts_variants(url: str) -> None:
    identity = canonicalize_threads_post_url(url)
    assert str(identity.canonical_url) == "https://www.threads.com/@user_001/post/code_001"
    assert (identity.post_id, identity.owner_handle) == ("code_001", "user_001")


@pytest.mark.parametrize(
    "url",
    [
        "http://www.threads.com/@user_001/post/code_001",
        "https://www.threads.com/@user_001",
        "https://www.threads.com/@user_001/post/code/001",
        "https://www.instagram.com/@user_001/post/code_001",
        "https://user:pw@www.threads.com/@user_001/post/code_001",
        "https://www.threads.com:8443/@user_001/post/code_001",
        "https://[::1",
    ],
)
def test_canonicalize_threads_post_url_rejects_other_shapes(url: str) -> None:
    with pytest.raises(ThreadsUrlError):
        canonicalize_threads_post_url(url)


def test_text_only_post_parses_without_media() -> None:
    parsed = parse_documents([_doc(_node())], IDENTITY)
    assert parsed is not None
    assert parsed.post.text == "hello world"
    assert parsed.media == []
    assert parsed.post.published_at == "2023-11-14T22:13:20Z"
    assert parsed.post.engagement == {"like": 12, "comment": 3, "repost": 2, "quote": 1, "share": 4}


def test_video_post_yields_one_video() -> None:
    node = _node(video_versions=[{"url": "https://v.example.test/1.mp4"}], **_image(0))
    parsed = parse_documents([_doc(node)], IDENTITY)
    assert parsed is not None
    assert [item.kind for item in parsed.media] == ["video"]
    assert parsed.media[0].ephemeral_url.get_secret_value() == "https://v.example.test/1.mp4"


def test_carousel_keeps_every_item_and_picks_the_largest_image() -> None:
    node = _node(carousel_media=[_image(n) for n in range(22)])
    parsed = parse_documents([_doc(node)], IDENTITY)
    assert parsed is not None
    assert len(parsed.media) == 22  # the acquirer caps; the parser reports what it saw
    assert {item.kind for item in parsed.media} == {"image"}
    assert parsed.media[0].media_type is None
    assert parsed.media[0].ephemeral_url.get_secret_value() == "https://img.example.test/0-large.jpg"


@pytest.mark.parametrize(
    "node",
    [
        {k: v for k, v in _node().items() if k != "user"},
        _node(code="other_code"),
    ],
)
def test_parse_returns_none_without_the_matching_post(node: dict[str, object]) -> None:
    assert parse_documents([_doc(node)], IDENTITY) is None


def test_missing_optional_fields_degrade_to_defaults() -> None:
    node = {"code": "code_001", "user": {"username": "user_001"}}
    parsed = parse_documents([_doc(node)], IDENTITY)
    assert parsed is not None
    assert (parsed.post.text, parsed.post.published_at, parsed.post.engagement) == ("", None, {})


def test_text_is_truncated_to_the_contract_limit() -> None:
    node = _node(caption={"text": "x" * (MAX_POST_TEXT + 10)})
    parsed = parse_documents([_doc(node)], IDENTITY)
    assert parsed is not None
    assert len(parsed.post.text) == MAX_POST_TEXT


def test_json_roots_skips_non_json_texts() -> None:
    assert json_roots(["not json", json.dumps({"a": 1}), ""]) == [{"a": 1}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_threads_adapter.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'thoth_control_plane.acquisition.adapters.threads'`

- [ ] **Step 3: Implement**

```python
"""SSRF-safe Threads URL identity and pure parsing of Threads post documents.

The documents are either the page's embedded `application/json` scripts (request method)
or captured GraphQL bodies (headless method); both nest the same post node, found by its
`code`. Nothing here performs I/O.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from typing import Any
from urllib.parse import urlsplit

from pydantic import HttpUrl

from thoth_control_plane.acquisition.models import (
    MAX_POST_TEXT,
    ResolvedMedia,
    SourcePost,
)
from thoth_control_plane.acquisition.normalize import _count, _pick, published_at_from_epoch
from thoth_control_plane.acquisition.platforms import PYTHON_PLATFORM_HOSTS, bare_host
from thoth_control_plane.domain.models import StrictModel

CANONICAL_BASE = "https://www.threads.com"
POST_PATH = re.compile(r"^/@(?P<owner>[A-Za-z0-9._]{1,64})/post/(?P<code>[A-Za-z0-9_-]{1,64})/?$")
ENGAGEMENT_KEYS = {
    "like": ("like_count",),
    "comment": ("direct_reply_count",),
    "repost": ("repost_count",),
    "quote": ("quote_count",),
    "share": ("reshare_count",),
}


class ThreadsUrlError(ValueError):
    """Raised when a URL is not a safe, supported public Threads post URL."""


class ThreadsPostIdentity(StrictModel):
    canonical_url: HttpUrl
    post_id: str
    owner_handle: str


class ThreadsParse(StrictModel):
    post: SourcePost
    media: list[ResolvedMedia]


def canonicalize_threads_post_url(url: str) -> ThreadsPostIdentity:
    """Reduce any accepted Threads post URL (query, fragment, slash, host alias) to its identity."""
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        # The bare ValueError embeds the raw offending substring; never chain it.
        raise ThreadsUrlError("invalid_source_url") from None
    match = POST_PATH.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or bare_host(host) not in PYTHON_PLATFORM_HOSTS["threads"]
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or match is None
    ):
        raise ThreadsUrlError("invalid_source_url")
    owner, code = match.group("owner"), match.group("code")
    return ThreadsPostIdentity(
        canonical_url=f"{CANONICAL_BASE}/@{owner}/post/{code}", post_id=code, owner_handle=owner
    )


def json_roots(texts: Iterable[str]) -> list[object]:
    roots: list[object] = []
    for text in texts:
        try:
            roots.append(json.loads(text))
        except ValueError:
            continue
    return roots


def _walk(value: object) -> Iterator[dict[str, Any]]:
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            yield current
            stack.extend(reversed(list(current.values())))
        elif isinstance(current, list):
            stack.extend(reversed(current))


def find_post_node(roots: Iterable[object], code: str) -> dict[str, Any] | None:
    for root in roots:
        for node in _walk(root):
            if node.get("code") == code and isinstance(node.get("user"), dict):
                return node
    return None


def _https(value: object) -> str | None:
    return value if isinstance(value, str) and value.startswith("https://") else None


def _video_url(item: dict[str, Any]) -> str | None:
    versions = item.get("video_versions")
    if isinstance(versions, list) and versions and isinstance(versions[0], dict):
        return _https(versions[0].get("url"))
    return None


def _largest_image_url(item: dict[str, Any]) -> str | None:
    container = item.get("image_versions2")
    candidates = container.get("candidates") if isinstance(container, dict) else None
    best: tuple[int, str] | None = None
    for candidate in candidates if isinstance(candidates, list) else []:
        if not isinstance(candidate, dict) or (url := _https(candidate.get("url"))) is None:
            continue
        area = (_count(candidate.get("width")) or 0) * (_count(candidate.get("height")) or 0)
        if best is None or area > best[0]:
            best = (area, url)
    return best[1] if best else None


def _media_of(node: dict[str, Any]) -> list[ResolvedMedia]:
    carousel = node.get("carousel_media")
    items = carousel if isinstance(carousel, list) and carousel else [node]
    media: list[ResolvedMedia] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if (video := _video_url(item)) is not None:
            media.append(ResolvedMedia(kind="video", ephemeral_url=video))
        elif (image := _largest_image_url(item)) is not None:
            media.append(ResolvedMedia(kind="image", ephemeral_url=image, media_type=None))
    return media


def parse_documents(
    roots: Iterable[object], identity: ThreadsPostIdentity
) -> ThreadsParse | None:
    """Parse the post named by `identity`; None when no document holds it."""
    node = find_post_node(roots, identity.post_id)
    if node is None:
        return None
    caption = node.get("caption")
    text = caption.get("text") if isinstance(caption, dict) else None
    info = node.get("text_post_app_info")
    counters = {**node, **info} if isinstance(info, dict) else node
    engagement = {
        key: value for key, names in ENGAGEMENT_KEYS.items() if (value := _pick(counters, names)) is not None
    }
    return ThreadsParse(
        post=SourcePost(
            post_id=identity.post_id,
            owner_handle=identity.owner_handle,
            text=text[:MAX_POST_TEXT] if isinstance(text, str) else "",
            published_at=published_at_from_epoch(node.get("taken_at")),
            engagement=engagement,
        ),
        media=_media_of(node),
    )
```

The canonical URL's identity wins over the node's own `user.username`, as for TikTok; the node only has to carry a `user` object to count as the post.

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_threads_adapter.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/adapters/threads.py python/tests/acquisition/test_threads_adapter.py
git commit -m "feat(acquisition): add threads url identity and post parsers"
```

---

### Task 8: Threads fetchers and acquirer

**Files:**
- Create: `python/src/thoth_control_plane/acquisition/threads_service.py`
- Modify: `python/src/thoth_control_plane/acquisition/service.py` (`RETRYABLE_FAILURES`, `_make_attempt`)
- Modify: `python/src/thoth_control_plane/acquisition/registry.py`
- Test: `python/tests/acquisition/test_threads_service.py` (create), `python/tests/acquisition/test_registry.py` (extend)

**Interfaces:**
- Consumes: Task 3 `MediaMaterializer.materialize(..., media_id=, index=)`; Task 7 parsers; `browser.HeadlessBrowserError`, `_default_session_factory`, `_increment_active_sessions`, `_decrement_active_sessions`, `_classify_fetch_error`, `_is_timeout`, `_parse_captured_xhr`, `FETCH_OPTIONS`; `cards.write_card`, `cards.CardRejected`; `service._elapsed_ms`, `service._make_attempt`, `service.RETRYABLE_FAILURES`.
- Produces: `RequestFetchError(reason)`; `ThreadsRequestFetcher(get=None).fetch(url) -> list[str]`; `ThreadsPage(xhr_bodies: list[object], script_texts: list[str], card_png: bytes | None)`; `ThreadsHeadlessBrowser(session_factory=_default_session_factory)` with `fetch(url) -> ThreadsPage` and `close()`; `CONTENT_METHOD: Literal["request", "headless"]`; `ThreadsAcquirer(request_fetcher, headless, materializer).inspect(...) -> AcquisitionResult`; `acquirer_for` returns a `ThreadsAcquirer` for Threads URLs. `POST_CARD_SELECTOR = 'div[data-pressable-container="true"]'`.

- [ ] **Step 1: Write the failing tests**

`tests/acquisition/test_threads_service.py`:

```python
"""Threads acquisition over injected fakes: no network, no Scrapling."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any

import pytest

from thoth_control_plane.acquisition import threads_service
from thoth_control_plane.acquisition.browser import (
    HeadlessBrowserError,
    active_scrapling_session_count,
)
from thoth_control_plane.acquisition.materializer import MediaMaterializationError
from thoth_control_plane.acquisition.models import AcquisitionReason, MaterializedMedia
from thoth_control_plane.acquisition.threads_service import (
    POST_CARD_SELECTOR,
    RequestFetchError,
    ThreadsAcquirer,
    ThreadsHeadlessBrowser,
    ThreadsPage,
    ThreadsRequestFetcher,
)
from tests.acquisition.png_fixtures import make_png

URL = "https://www.threads.net/@user_001/post/code_001?xmt=abc"
WF = "wf_threads_001"


def _node(**extra: object) -> dict[str, object]:
    return {
        "code": "code_001",
        "user": {"username": "user_001"},
        "caption": {"text": "hello world"},
        "taken_at": 1_700_000_000,
        **extra,
    }


def _texts(node: dict[str, object]) -> list[str]:
    return [json.dumps({"data": {"thread_items": [{"post": node}]}})]


def _images(count: int) -> list[dict[str, object]]:
    return [
        {"image_versions2": {"candidates": [{"url": f"https://img.example.test/{n}.jpg", "width": 9, "height": 9}]}}
        for n in range(count)
    ]


class FakeRequest:
    def __init__(self, texts: list[str] | None = None, error: AcquisitionReason | None = None):
        self.texts, self.error, self.calls = texts or [], error, 0

    async def fetch(self, url: str) -> list[str]:
        self.calls += 1
        if self.error is not None:
            raise RequestFetchError(self.error)
        return self.texts


class FakeHeadless:
    def __init__(self, page: ThreadsPage | None = None, error: AcquisitionReason | None = None):
        self.page, self.error, self.calls, self.closed = page, error, 0, 0

    async def fetch(self, url: str) -> ThreadsPage:
        self.calls += 1
        if self.error is not None:
            raise HeadlessBrowserError(self.error)
        assert self.page is not None
        return self.page

    async def close(self) -> None:
        self.closed += 1


class FakeMaterializer:
    def __init__(self, fail_at: int | None = None) -> None:
        self.fail_at = fail_at

    async def materialize(self, candidate, destination, relative_location, strategy, *, media_id="media_1", index=1):
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


def _card_page() -> ThreadsPage:
    return ThreadsPage(xhr_bodies=[], script_texts=[], card_png=make_png(400, 200))


async def _inspect(tmp_path: Path, request: FakeRequest, headless: FakeHeadless, materializer=None, url=URL):
    acquirer = ThreadsAcquirer(request, headless, materializer or FakeMaterializer())
    return await acquirer.inspect(workflow_id=WF, source_url=url, artifact_root=tmp_path)


@pytest.mark.asyncio
async def test_text_only_post_gets_a_report_and_a_post_card(tmp_path: Path) -> None:
    headless = FakeHeadless(_card_page())
    result = await _inspect(tmp_path, FakeRequest(_texts(_node())), headless)

    report = result.report
    assert report is not None
    assert (report.schema_version, report.source.platform, report.media) == (3, "threads", [])
    assert str(report.source.canonical_url) == "https://www.threads.com/@user_001/post/code_001"
    assert report.post.text == "hello world"
    assert report.post_card is not None
    assert report.post_card.location == PurePosixPath(f"reports/{WF}/cards/post.png")
    assert (tmp_path / report.post_card.location).is_file()
    assert [a.strategy.value for a in report.outcome.attempts] == ["scrapling_request"]
    assert headless.closed >= 1


@pytest.mark.asyncio
async def test_video_post_skips_the_card_visit(tmp_path: Path) -> None:
    node = _node(video_versions=[{"url": "https://v.example.test/1.mp4"}])
    headless = FakeHeadless(_card_page())
    result = await _inspect(tmp_path, FakeRequest(_texts(node)), headless)

    assert result.report is not None
    assert [m.kind for m in result.report.media] == ["video"]
    assert result.report.post_card is None
    assert headless.calls == 0


@pytest.mark.asyncio
async def test_rejected_card_is_simply_absent(tmp_path: Path) -> None:
    page = ThreadsPage(xhr_bodies=[], script_texts=[], card_png=make_png(400, 200, flat=True))
    result = await _inspect(tmp_path, FakeRequest(_texts(_node())), FakeHeadless(page))
    assert result.report is not None
    assert result.report.post_card is None


@pytest.mark.asyncio
async def test_failed_card_visit_is_simply_absent(tmp_path: Path) -> None:
    headless = FakeHeadless(error=AcquisitionReason.HEADLESS_BLOCKED)
    result = await _inspect(tmp_path, FakeRequest(_texts(_node())), headless)
    assert result.report is not None
    assert result.report.post_card is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("request_", "code", "status"),
    [
        (FakeRequest(error=AcquisitionReason.REQUEST_BLOCKED), "request_blocked", "failed"),
        (FakeRequest(error=AcquisitionReason.REQUEST_TIMEOUT), "request_timeout", "failed"),
        (FakeRequest(["{}"]), "request_incomplete", "incomplete"),
    ],
)
async def test_request_failures_are_retryable_and_eligible(
    tmp_path: Path, request_: FakeRequest, code: str, status: str
) -> None:
    result = await _inspect(tmp_path, request_, FakeHeadless(_card_page()))
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == (code, True)
    assert [a.status.value for a in result.failure.attempts] == [status]


@pytest.mark.asyncio
async def test_whitespace_only_post_is_no_content(tmp_path: Path) -> None:
    node = _node(caption={"text": " \n\t "})
    result = await _inspect(tmp_path, FakeRequest(_texts(node)), FakeHeadless(_card_page()))
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("no_content", False)


@pytest.mark.asyncio
async def test_carousel_is_capped_at_twenty(tmp_path: Path) -> None:
    node = _node(carousel_media=_images(22))
    result = await _inspect(tmp_path, FakeRequest(_texts(node)), FakeHeadless(_card_page()))
    assert result.report is not None
    assert [m.index for m in result.report.media] == list(range(1, 21))
    assert result.report.media[19].location == PurePosixPath(f"reports/{WF}/media/threads-code_001-20.jpg")


@pytest.mark.asyncio
async def test_mid_carousel_failure_leaves_no_orphans(tmp_path: Path) -> None:
    node = _node(carousel_media=_images(3))
    result = await _inspect(
        tmp_path, FakeRequest(_texts(node)), FakeHeadless(_card_page()), FakeMaterializer(fail_at=2)
    )
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("media_validation_failed", True)
    media_dir = tmp_path / "reports" / WF / "media"
    assert not media_dir.exists() or list(media_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_invalid_url_fails_before_any_fetch(tmp_path: Path) -> None:
    request, headless = FakeRequest(_texts(_node())), FakeHeadless(_card_page())
    result = await _inspect(tmp_path, request, headless, url="https://www.threads.com/@user_001")
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("invalid_source_url", False)
    assert (request.calls, headless.calls) == (0, 0)


@pytest.mark.asyncio
async def test_headless_method_uses_one_visit_for_post_and_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(threads_service, "CONTENT_METHOD", "headless")
    page = ThreadsPage(xhr_bodies=[], script_texts=_texts(_node()), card_png=make_png(400, 200))
    request, headless = FakeRequest(), FakeHeadless(page)
    result = await _inspect(tmp_path, request, headless)

    assert result.report is not None
    assert result.report.post_card is not None
    assert [a.strategy.value for a in result.report.outcome.attempts] == ["scrapling_headless"]
    assert (request.calls, headless.calls) == (0, 1)


@pytest.mark.asyncio
async def test_headless_method_incomplete_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(threads_service, "CONTENT_METHOD", "headless")
    page = ThreadsPage(xhr_bodies=[{"data": {}}], script_texts=[], card_png=None)
    result = await _inspect(tmp_path, FakeRequest(), FakeHeadless(page))
    assert result.failure is not None
    assert result.failure.code == "headless_incomplete"


def _response(status: int = 200, url: str = "https://www.threads.com/@user_001/post/code_001"):
    return SimpleNamespace(
        status=status, url=url, css=lambda selector: SimpleNamespace(getall=lambda: ["{}", ""])
    )


@pytest.mark.asyncio
async def test_request_fetcher_returns_script_texts() -> None:
    seen: dict[str, Any] = {}

    async def get(url: str, **kwargs: Any):
        seen.update(kwargs)
        return _response()

    assert await ThreadsRequestFetcher(get).fetch(URL) == ["{}"]
    assert seen["impersonate"] == "chrome"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("get_result", "reason"),
    [
        (_response(status=403), AcquisitionReason.REQUEST_BLOCKED),
        (_response(url="https://www.threads.com/login?next=x"), AcquisitionReason.REQUEST_BLOCKED),
        (TimeoutError(), AcquisitionReason.REQUEST_TIMEOUT),
        (RuntimeError("boom"), AcquisitionReason.REQUEST_BLOCKED),
    ],
)
async def test_request_fetcher_classifies_failures(get_result: Any, reason: AcquisitionReason) -> None:
    async def get(url: str, **kwargs: Any):
        if isinstance(get_result, Exception):
            raise get_result
        return get_result

    with pytest.raises(RequestFetchError) as caught:
        await ThreadsRequestFetcher(get).fetch(URL)
    assert caught.value.reason is reason


class _Locator:
    def __init__(self, png: bytes) -> None:
        self.first, self._png = self, png

    async def scroll_into_view_if_needed(self, timeout: int) -> None:
        return None

    async def screenshot(self, timeout: int) -> bytes:
        return self._png


class _Page:
    def locator(self, selector: str) -> _Locator:
        assert selector == POST_CARD_SELECTOR
        return _Locator(make_png(400, 200))


class _Active:
    async def fetch(self, url: str, **kwargs: Any):
        await kwargs["page_action"](_Page())
        return SimpleNamespace(
            url=url,
            captured_xhr=[{"status": 200, "body": {"data": {}}}],
            css=lambda selector: SimpleNamespace(getall=lambda: ["{}"]),
        )


class _Session:
    def __init__(self, active: Any = None, enter_error: Exception | None = None) -> None:
        self.active, self.enter_error, self.exited = active or _Active(), enter_error, 0

    async def __aenter__(self):
        if self.enter_error is not None:
            raise self.enter_error
        return self.active

    async def __aexit__(self, *exc: object) -> None:
        self.exited += 1


@pytest.mark.asyncio
async def test_headless_browser_returns_page_and_releases_the_session() -> None:
    session = _Session()
    browser = ThreadsHeadlessBrowser(lambda **kwargs: session)
    page = await browser.fetch("https://www.threads.com/@user_001/post/code_001")
    await browser.close()

    assert page.script_texts == ["{}"]
    assert page.xhr_bodies == [{"data": {}}]
    assert page.card_png is not None
    assert session.exited == 1
    assert active_scrapling_session_count() == 0


@pytest.mark.asyncio
async def test_headless_browser_classifies_a_startup_timeout() -> None:
    browser = ThreadsHeadlessBrowser(lambda **kwargs: _Session(enter_error=TimeoutError()))
    with pytest.raises(HeadlessBrowserError) as caught:
        await browser.fetch("https://www.threads.com/@user_001/post/code_001")
    assert caught.value.reason is AcquisitionReason.HEADLESS_TIMEOUT
    assert active_scrapling_session_count() == 0
```

If `HeadlessBrowserError` exposes its reason under a different attribute than `reason`, use that attribute and ledger it. If `tests.acquisition.png_fixtures` is imported under another module path in sibling tests, match their import.

Extend `tests/acquisition/test_registry.py`'s test with:

```python
        threads = acquirer_for(
            "https://www.threads.net/@a/post/B", client=client, materializer=materializer
        )
        assert isinstance(threads, ThreadsAcquirer)
```

(import `ThreadsAcquirer` from `thoth_control_plane.acquisition.threads_service`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_threads_service.py tests/acquisition/test_registry.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'thoth_control_plane.acquisition.threads_service'`

- [ ] **Step 3: Implement**

`service.py`: `RETRYABLE_FAILURES` gains `"request_timeout"`, `"request_blocked"`, `"request_incomplete"`; in `_make_attempt` the incomplete branch becomes `elif reason in (AcquisitionReason.HEADLESS_INCOMPLETE, AcquisitionReason.REQUEST_INCOMPLETE):`.

`acquisition/threads_service.py`:

```python
"""Threads single-post acquisition: one content method, a best-effort headless post card.

`CONTENT_METHOD` is decided once from the Stage 3a golden-fixture comparison (request wins
when it matches or beats headless on every count). There is no runtime fallback between
methods; the legacy fallback lives in the workflow.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import urlsplit

from thoth_control_plane.acquisition.adapters.threads import (
    ThreadsParse,
    ThreadsPostIdentity,
    ThreadsUrlError,
    canonicalize_threads_post_url,
    json_roots,
    parse_documents,
)
from thoth_control_plane.acquisition.browser import (
    FETCH_OPTIONS,
    HeadlessBrowserError,
    _classify_fetch_error,
    _decrement_active_sessions,
    _default_session_factory,
    _increment_active_sessions,
    _is_timeout,
    _parse_captured_xhr,
)
from thoth_control_plane.acquisition.cards import CardRejected, write_card
from thoth_control_plane.acquisition.materializer import (
    MediaMaterializationError,
    MediaMaterializer,
)
from thoth_control_plane.acquisition.models import (
    MAX_MEDIA_ITEMS,
    AcquisitionFailure,
    AcquisitionOutcome,
    AcquisitionReason,
    AcquisitionResult,
    AcquisitionStrategy,
    CardArtifact,
    MaterializedMedia,
    ReportSource,
    SourceReport,
)
from thoth_control_plane.acquisition.service import (
    RETRYABLE_FAILURES,
    _elapsed_ms,
    _make_attempt,
)

# Provisional until Task 10 records the comparison; a test pins it to the fixtures.
CONTENT_METHOD: Literal["request", "headless"] = "request"
REQUEST_OPTIONS: dict[str, Any] = {
    "impersonate": "chrome",
    "stealthy_headers": True,
    "follow_redirects": "safe",
    "timeout": 30,
    "retries": 1,
}
THREADS_CAPTURE_XHR = r"https://www\.threads\.(?:com|net)/(?:api/)?graphql.*"
POST_CARD_SELECTOR = 'div[data-pressable-container="true"]'
SCRIPT_SELECTOR = 'script[type="application/json"]::text'
_STRATEGIES = {
    "request": AcquisitionStrategy.SCRAPLING_REQUEST,
    "headless": AcquisitionStrategy.SCRAPLING_HEADLESS,
}


class RequestFetchError(Exception):
    def __init__(self, reason: AcquisitionReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


async def _scrapling_get(url: str, **kwargs: Any) -> Any:
    from scrapling.fetchers import AsyncFetcher

    return await AsyncFetcher.get(url, **kwargs)


def _blocked(final_url: object) -> bool:
    return urlsplit(str(final_url)).path.startswith("/login")


class ThreadsRequestFetcher:
    """Plain impersonated HTTP GET; returns the page's embedded JSON script texts."""

    def __init__(self, get: Callable[..., Awaitable[Any]] | None = None) -> None:
        self._get = get or _scrapling_get

    async def fetch(self, url: str) -> list[str]:
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
        return [text for text in response.css(SCRIPT_SELECTOR).getall() if text]


@dataclass(frozen=True)
class ThreadsPage:
    xhr_bodies: list[object]
    script_texts: list[str]
    card_png: bytes | None


def _crop_post_card(cards: list[bytes]) -> Callable[[Any], Awaitable[None]]:
    async def crop(page: Any) -> None:
        # Best effort: a card that cannot be cropped is simply absent.
        with contextlib.suppress(Exception):
            card = page.locator(POST_CARD_SELECTOR).first
            await card.scroll_into_view_if_needed(timeout=5_000)
            cards.append(await card.screenshot(timeout=10_000))

    return crop


class ThreadsHeadlessBrowser:
    """A stealthy headless visit: GraphQL bodies, embedded JSON, and a post-card crop."""

    def __init__(self, session_factory: Callable[..., Any] = _default_session_factory) -> None:
        self._session_factory = session_factory
        self._session: Any | None = None

    async def fetch(self, url: str) -> ThreadsPage:
        session = self._session_factory(headless=True, max_pages=1, capture_xhr=THREADS_CAPTURE_XHR)
        try:
            active = await session.__aenter__()
        except Exception as error:
            raise HeadlessBrowserError(_classify_fetch_error(error)) from None

        self._session = session
        _increment_active_sessions()
        cards: list[bytes] = []
        try:
            response = await active.fetch(url, page_action=_crop_post_card(cards), **FETCH_OPTIONS)
            if _blocked(response.url):
                raise HeadlessBrowserError(AcquisitionReason.HEADLESS_BLOCKED)
            xhr = _parse_captured_xhr(list(getattr(response, "captured_xhr", None) or []))
            return ThreadsPage(
                xhr_bodies=[entry.get("body") for entry in xhr if entry.get("status") == 200],
                script_texts=[text for text in response.css(SCRIPT_SELECTOR).getall() if text],
                card_png=cards[0] if cards else None,
            )
        except HeadlessBrowserError:
            await self.close()
            raise
        except Exception as error:
            await self.close()
            raise HeadlessBrowserError(_classify_fetch_error(error)) from None
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        session, self._session = self._session, None
        if session is None:
            return
        try:
            await session.__aexit__(None, None, None)
        except Exception:
            pass
        finally:
            _decrement_active_sessions()


def _persist_post_card(
    card_png: bytes | None, workflow_id: str, artifact_root: Path
) -> CardArtifact | None:
    if card_png is None:
        return None
    location = PurePosixPath("reports") / workflow_id / "cards" / "post.png"
    try:
        return write_card(card_png, artifact_root, location)
    except (CardRejected, OSError):
        return None


class ThreadsAcquirer:
    """One Threads post: content by `CONTENT_METHOD`, media in order, a card for non-video."""

    def __init__(
        self,
        request_fetcher: ThreadsRequestFetcher,
        headless: ThreadsHeadlessBrowser,
        materializer: MediaMaterializer,
    ) -> None:
        self._request = request_fetcher
        self._headless = headless
        self._materializer = materializer

    async def _content(
        self, identity: ThreadsPostIdentity
    ) -> tuple[ThreadsParse | None, AcquisitionReason | None, bytes | None]:
        url = str(identity.canonical_url)
        if CONTENT_METHOD == "request":
            try:
                texts = await self._request.fetch(url)
            except RequestFetchError as error:
                return None, error.reason, None
            parsed = parse_documents(json_roots(texts), identity)
            return parsed, None if parsed else AcquisitionReason.REQUEST_INCOMPLETE, None
        try:
            page = await self._headless.fetch(url)
        except HeadlessBrowserError as error:
            return None, error.reason, None
        parsed = parse_documents([*page.xhr_bodies, *json_roots(page.script_texts)], identity)
        return parsed, None if parsed else AcquisitionReason.HEADLESS_INCOMPLETE, page.card_png

    async def _card_visit(self, identity: ThreadsPostIdentity) -> bytes | None:
        try:
            return (await self._headless.fetch(str(identity.canonical_url))).card_png
        except HeadlessBrowserError:
            return None

    async def _materialize_all(
        self,
        parsed: ThreadsParse,
        workflow_id: str,
        strategy: AcquisitionStrategy,
        artifact_root: Path,
    ) -> list[MaterializedMedia]:
        done: list[MaterializedMedia] = []
        try:
            for index, candidate in enumerate(parsed.media[:MAX_MEDIA_ITEMS], start=1):
                location = (
                    PurePosixPath("reports") / workflow_id / "media"
                    / f"threads-{parsed.post.post_id}-{index}"
                )
                done.append(
                    await self._materializer.materialize(
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

    async def inspect(
        self, *, workflow_id: str, source_url: str, artifact_root: Path
    ) -> AcquisitionResult:
        try:
            identity = canonicalize_threads_post_url(source_url)
        except ThreadsUrlError:
            return AcquisitionResult(
                failure=AcquisitionFailure(code="invalid_source_url", retryable=False)
            )
        strategy = _STRATEGIES[CONTENT_METHOD]
        start = time.monotonic()
        try:
            parsed, reason, card_png = await self._content(identity)
            if parsed is not None and not parsed.post.text.strip() and not parsed.media:
                attempt = _make_attempt(strategy, None, _elapsed_ms(start))
                return AcquisitionResult(
                    failure=AcquisitionFailure(code="no_content", retryable=False, attempts=[attempt])
                )
            media: list[MaterializedMedia] = []
            if parsed is not None:
                try:
                    media = await self._materialize_all(parsed, workflow_id, strategy, artifact_root)
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
            post_card = None
            if not any(item.kind == "video" for item in media):
                if CONTENT_METHOD == "request":
                    card_png = await self._card_visit(identity)
                post_card = await asyncio.to_thread(
                    _persist_post_card, card_png, workflow_id, artifact_root
                )
            return AcquisitionResult(
                report=SourceReport(
                    workflow_id=workflow_id,
                    source=ReportSource(platform="threads", canonical_url=identity.canonical_url),
                    post=parsed.post,
                    media=media,
                    outcome=AcquisitionOutcome(attempts=[attempt]),
                    post_card=post_card,
                )
            )
        finally:
            # Same shielded close as the TikTok service: a second cancellation must not
            # interrupt browser cleanup partway through.
            await asyncio.shield(self._headless.close())
```

`registry.py`: import `ThreadsAcquirer`, `ThreadsHeadlessBrowser`, `ThreadsRequestFetcher` from `threads_service` and add before the `raise`:

```python
    if platform == "threads":
        return ThreadsAcquirer(ThreadsRequestFetcher(), ThreadsHeadlessBrowser(), materializer)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition tests/activities`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/threads_service.py python/src/thoth_control_plane/acquisition/service.py python/src/thoth_control_plane/acquisition/registry.py python/tests/acquisition/test_threads_service.py python/tests/acquisition/test_registry.py
git commit -m "feat(acquisition): add threads acquirer with request and headless"
```

---

### Task 9: Capture, sanitizer, and method comparison tooling

**Files:**
- Create: `python/src/thoth_control_plane/operations/threads_capture.py`
- Create: `python/src/thoth_control_plane/operations/threads_fixture.py`
- Test: `python/tests/operations/test_threads_fixture.py`

**Interfaces:**
- Consumes: Task 7 `canonicalize_threads_post_url`, `find_post_node`, `json_roots`, `parse_documents`, `ThreadsParse`; Task 8 `ThreadsRequestFetcher`, `ThreadsHeadlessBrowser`, `RequestFetchError`; `tiktok_comment_fixture._Pseudonyms`; `tiktok_discovery_fixture._floor`, `SYNTHETIC_EPOCH`, `MIN_SECRET_LENGTH`.
- Produces:
  - Raw capture file (never committed): `{"kind": "video"|"image"|"text", "post_id": str, "owner": str, "request": {"status": "ok"|<reason>, "script_texts": [...]}, "headless": {"status": "ok"|<reason>, "xhr_bodies": [...], "script_texts": [...], "card": bool}}`.
  - `COUNT_KEYS`; `counts(parsed: ThreadsParse | None) -> dict[str, int] | None`; `decide(pairs: list[tuple[dict[str, int] | None, dict[str, int] | None]]) -> Literal["request", "headless"]`; `method_roots(raw, method) -> list[object]`; `sanitize(raw_node: dict) -> dict`; `leak_count(raw_node: dict, text: str) -> int`; `build_fixture(raw: dict) -> dict` returning `{"kind", "method", "identity": {"post_id": "code_001", "owner_handle": "user_001"}, "counts": {"request": ..., "headless": ...}, "document": ..., "expected": {"text", "media_kinds", "engagement", "published_at"}}`; CLI `python -m thoth_control_plane.operations.threads_fixture --raw <file> --out <fixture>`.

- [ ] **Step 1: Write the failing tests**

```python
"""Threads fixture tooling: sanitizing, leak checking, and the method decision."""

from __future__ import annotations

import json

import pytest

from thoth_control_plane.acquisition.adapters.threads import (
    canonicalize_threads_post_url,
    parse_documents,
)
from thoth_control_plane.operations.threads_fixture import (
    build_fixture,
    counts,
    decide,
    leak_count,
)

SECRETS = ("realperson", "Secret caption about Jakarta", "scontent.cdninstagram", "Xy9Qk2Lm")


def _raw_node() -> dict[str, object]:
    return {
        "code": "Xy9Qk2Lm",
        "pk": "3141592653589793",
        "user": {"username": "realperson", "profile_pic_url": "https://scontent.cdninstagram.com/p.jpg"},
        "caption": {"text": "Secret caption about Jakarta"},
        "taken_at": 1_726_000_123,
        "like_count": 1_234,
        "text_post_app_info": {"direct_reply_count": 56, "repost_count": 7, "quote_count": 0, "reshare_count": 89},
        "carousel_media": [
            {
                "image_versions2": {
                    "candidates": [
                        {"url": "https://scontent.cdninstagram.com/a.jpg?sig=1", "width": 1080, "height": 1350},
                        {"url": "https://scontent.cdninstagram.com/b.jpg?sig=2", "width": 320, "height": 400},
                    ]
                }
            },
            {"video_versions": [{"url": "https://scontent.cdninstagram.com/v.mp4?sig=3"}]},
        ],
    }


def _raw(request_status: str = "ok") -> dict[str, object]:
    document = json.dumps({"require": [{"thread_items": [{"post": _raw_node()}]}]})
    return {
        "kind": "image",
        "post_id": "Xy9Qk2Lm",
        "owner": "realperson",
        "request": {"status": request_status, "script_texts": [document] if request_status == "ok" else []},
        "headless": {"status": "ok", "xhr_bodies": [], "script_texts": [document], "card": True},
    }


def test_fixture_carries_no_original_value_and_still_parses() -> None:
    fixture = build_fixture(_raw())
    text = json.dumps(fixture, ensure_ascii=False)

    assert [secret for secret in SECRETS if secret in text] == []
    assert leak_count(_raw_node(), text) == 0
    assert fixture["identity"] == {"post_id": "code_001", "owner_handle": "user_001"}
    assert fixture["method"] == "request"

    identity = canonicalize_threads_post_url("https://www.threads.com/@user_001/post/code_001")
    parsed = parse_documents([fixture["document"]], identity)
    assert parsed is not None
    assert [item.kind for item in parsed.media] == ["image", "video"]
    assert parsed.post.engagement == {"like": 1_200, "comment": 56, "repost": 7, "quote": 0, "share": 89}
    assert fixture["expected"]["media_kinds"] == ["image", "video"]
    assert fixture["expected"]["text"] == parsed.post.text != "Secret caption about Jakarta"


def test_blocked_request_falls_back_to_the_headless_document() -> None:
    fixture = build_fixture(_raw(request_status="request_blocked"))
    assert fixture["method"] == "headless"
    assert fixture["counts"]["request"] is None
    assert fixture["counts"]["headless"]["media"] == 2


def test_leak_count_flags_a_surviving_value() -> None:
    assert leak_count(_raw_node(), "... realperson ...") == 1


def test_counts_of_a_missing_parse_are_none() -> None:
    assert counts(None) is None


@pytest.mark.parametrize(
    ("pairs", "method"),
    [
        ([({"found": 1, "media": 2}, {"found": 1, "media": 2})], "request"),
        ([({"found": 1, "media": 3}, {"found": 1, "media": 2})], "request"),
        ([({"found": 1, "media": 1}, {"found": 1, "media": 2})], "headless"),
        ([(None, {"found": 1, "media": 2})], "headless"),
        ([({"found": 1, "media": 2}, None)], "request"),
        (
            [({"found": 1, "media": 2}, {"found": 1, "media": 2}), (None, {"found": 1, "media": 0})],
            "headless",
        ),
    ],
)
def test_decide_prefers_request_only_when_it_never_loses(pairs, method) -> None:
    assert decide(pairs) == method
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/operations/test_threads_fixture.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'thoth_control_plane.operations.threads_fixture'`

- [ ] **Step 3: Implement**

`operations/threads_fixture.py`:

```python
"""Turn one raw Threads capture into a sanitized golden fixture and compare the methods.

Operator-run after an authorized capture. Only allowlisted keys survive; handles, codes,
and text are pseudonymized, media URLs replaced, timestamps moved to a synthetic grid, and
counters floored. Output reports counts only; raw values are never printed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Literal

from thoth_control_plane.acquisition.adapters.threads import (
    ThreadsParse,
    canonicalize_threads_post_url,
    find_post_node,
    json_roots,
    parse_documents,
)
from thoth_control_plane.operations.tiktok_comment_fixture import _Pseudonyms
from thoth_control_plane.operations.tiktok_discovery_fixture import (
    MIN_SECRET_LENGTH,
    SYNTHETIC_EPOCH,
    _floor,
)

CODE = "code_001"
COUNT_KEYS = ("found", "text_chars", "media", "videos", "engagement_keys", "published_at")
COUNTER_KEYS = ("like_count",)
INFO_KEYS = ("direct_reply_count", "repost_count", "quote_count", "reshare_count")
MEDIA_HOST = "https://media.example.test"


def counts(parsed: ThreadsParse | None) -> dict[str, int] | None:
    if parsed is None:
        return None
    return {
        "found": 1,
        "text_chars": len(parsed.post.text),
        "media": len(parsed.media),
        "videos": sum(item.kind == "video" for item in parsed.media),
        "engagement_keys": len(parsed.post.engagement),
        "published_at": int(parsed.post.published_at is not None),
    }


def decide(
    pairs: list[tuple[dict[str, int] | None, dict[str, int] | None]],
) -> Literal["request", "headless"]:
    """Request wins only if, on every post, it was not blocked and never counted less."""
    for request, headless in pairs:
        if request is None:
            return "headless"
        if headless is not None and any(request.get(k, 0) < v for k, v in headless.items()):
            return "headless"
    return "request"


def method_roots(raw: dict[str, Any], method: str) -> list[object]:
    capture = raw.get(method) or {}
    if capture.get("status") != "ok":
        return []
    return [*capture.get("xhr_bodies", []), *json_roots(capture.get("script_texts", []))]


class _Sanitizer:
    def __init__(self) -> None:
        self.names = _Pseudonyms()
        self.urls = 0

    def _url(self, kind: str, ext: str) -> str:
        self.urls += 1
        return f"{MEDIA_HOST}/{kind}/{self.urls}.{ext}"

    def _media(self, item: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        versions = item.get("video_versions")
        if isinstance(versions, list):
            out["video_versions"] = [
                {"url": self._url("video", "mp4")} for v in versions if isinstance(v, dict) and v.get("url")
            ]
        container = item.get("image_versions2")
        candidates = container.get("candidates") if isinstance(container, dict) else None
        if isinstance(candidates, list):
            out["image_versions2"] = {
                "candidates": [
                    {
                        "url": self._url("image", "jpg"),
                        **{k: c[k] for k in ("width", "height") if isinstance(c.get(k), int)},
                    }
                    for c in candidates
                    if isinstance(c, dict) and c.get("url")
                ]
            }
        return out

    def node(self, node: dict[str, Any]) -> dict[str, Any]:
        user = node.get("user") if isinstance(node.get("user"), dict) else {}
        out: dict[str, Any] = {"code": CODE, "user": {"username": self.names.handle(user.get("username"))}}
        caption = node.get("caption")
        if isinstance(caption, dict) and isinstance(caption.get("text"), str):
            out["caption"] = {"text": self.names.text(caption["text"])}
        if node.get("taken_at") is not None:
            out["taken_at"] = SYNTHETIC_EPOCH
        for key in COUNTER_KEYS:
            if isinstance(node.get(key), int):
                out[key] = _floor(node[key])
        info = node.get("text_post_app_info")
        if isinstance(info, dict):
            out["text_post_app_info"] = {k: _floor(info[k]) for k in INFO_KEYS if isinstance(info.get(k), int)}
        out.update(self._media(node))
        carousel = node.get("carousel_media")
        if isinstance(carousel, list):
            out["carousel_media"] = [self._media(item) for item in carousel if isinstance(item, dict)]
        return out


def sanitize(raw_node: dict[str, Any]) -> dict[str, Any]:
    """The post node alone, sanitized, under a neutral wrapper the parser walks through."""
    return {"data": {"thread_items": [{"post": _Sanitizer().node(raw_node)}]}}


def _leaves(value: object) -> set[str]:
    if isinstance(value, dict):
        return set().union(*(_leaves(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_leaves(v) for v in value)) if value else set()
    return {value} if isinstance(value, str) and len(value) >= MIN_SECRET_LENGTH else set()


def leak_count(raw_node: dict[str, Any], text: str) -> int:
    return sum(leaf in text for leaf in _leaves(raw_node))


def build_fixture(raw: dict[str, Any]) -> dict[str, Any]:
    identity = canonicalize_threads_post_url(
        f"https://www.threads.com/@{raw['owner']}/post/{raw['post_id']}"
    )
    parses = {m: parse_documents(method_roots(raw, m), identity) for m in ("request", "headless")}
    method = "request" if parses["request"] is not None else "headless"
    raw_node = find_post_node(method_roots(raw, method), identity.post_id)
    if raw_node is None:
        raise ValueError("neither method captured the post")
    document = sanitize(raw_node)
    # The pseudonymized handle is `user_001`: the sanitizer sees exactly one handle.
    owner = document["data"]["thread_items"][0]["post"]["user"]["username"]
    replay = canonicalize_threads_post_url(f"https://www.threads.com/@{owner}/post/{CODE}")
    parsed = parse_documents([document], replay)
    if parsed is None:
        raise ValueError("the sanitized document no longer parses")
    return {
        "kind": raw["kind"],
        "method": method,
        "identity": {"post_id": CODE, "owner_handle": parsed.post.owner_handle},
        "counts": {m: counts(p) for m, p in parses.items()},
        "document": document,
        "expected": {
            "text": parsed.post.text,
            "media_kinds": [item.kind for item in parsed.media],
            "engagement": parsed.post.engagement,
            "published_at": parsed.post.published_at,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    raw = json.loads(args.raw.read_text(encoding="utf-8"))
    fixture = build_fixture(raw)
    text = json.dumps(fixture, indent=2, ensure_ascii=False) + "\n"
    raw_node = find_post_node(method_roots(raw, fixture["method"]), raw["post_id"]) or {}
    leaks = leak_count(raw_node, text)
    print(json.dumps({"kind": fixture["kind"], "method": fixture["method"], "counts": fixture["counts"], "leaks": leaks}))
    if leaks:
        return 1
    args.out.write_bytes(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

The sanitized handle comes from `_Pseudonyms.handle`, which yields `user_001` for the first handle; the replayed identity is built from it so the fixture never depends on that numbering by accident.

`operations/threads_capture.py`:

```python
"""Operator-run, read-only Threads capture for the Stage 3a method comparison.

Never run by the test suite and only after the operator authorizes the capture. Reads
`<kind> <url>` lines (kind: video, image, text) from `--urls`, fetches each post once per
method, and writes one raw JSON per post plus the card PNG under `--out`. URLs, handles,
and bodies are never printed; stdout carries kinds, statuses, and counts only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.adapters.threads import canonicalize_threads_post_url
from thoth_control_plane.acquisition.browser import HeadlessBrowserError
from thoth_control_plane.acquisition.threads_service import (
    RequestFetchError,
    ThreadsHeadlessBrowser,
    ThreadsRequestFetcher,
)

KINDS = ("video", "image", "text")


async def _capture(kind: str, url: str, out: Path) -> dict[str, Any]:
    identity = canonicalize_threads_post_url(url)
    target = str(identity.canonical_url)
    raw: dict[str, Any] = {"kind": kind, "post_id": identity.post_id, "owner": identity.owner_handle}
    try:
        raw["request"] = {"status": "ok", "script_texts": await ThreadsRequestFetcher().fetch(target)}
    except RequestFetchError as error:
        raw["request"] = {"status": error.reason.value, "script_texts": []}
    browser = ThreadsHeadlessBrowser()
    try:
        page = await browser.fetch(target)
        raw["headless"] = {
            "status": "ok",
            "xhr_bodies": page.xhr_bodies,
            "script_texts": page.script_texts,
            "card": page.card_png is not None,
        }
        if page.card_png is not None:
            (out / f"{kind}-card.png").write_bytes(page.card_png)
    except HeadlessBrowserError as error:
        raw["headless"] = {"status": error.reason.value, "xhr_bodies": [], "script_texts": [], "card": False}
    finally:
        await browser.close()
    (out / f"{kind}.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return raw


async def _run(urls: Path, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    for line in urls.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        kind, url = line.split(maxsplit=1)
        if kind not in KINDS:
            print(json.dumps({"error": "unknown_kind"}))
            return 2
        raw = await _capture(kind, url.strip(), out)
        print(
            json.dumps(
                {
                    "kind": kind,
                    "request": [raw["request"]["status"], len(raw["request"]["script_texts"])],
                    "headless": [raw["headless"]["status"], len(raw["headless"]["xhr_bodies"]), len(raw["headless"]["script_texts"]), raw["headless"]["card"]],
                }
            )
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--urls", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.urls, args.out))


if __name__ == "__main__":
    sys.exit(main())
```

`threads_capture.py` performs live I/O and gets no unit test (the suite is offline); its parts are tested through Task 8.

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/operations/test_threads_fixture.py`
Expected: PASS. Then run ruff (Global Constraints); fix any line-length findings by reformatting, not by disabling rules.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/operations/threads_capture.py python/src/thoth_control_plane/operations/threads_fixture.py python/tests/operations/test_threads_fixture.py
git commit -m "feat(operations): add threads capture and fixture sanitizer"
```

---

### Task 10: Golden fixtures and the method decision — HARD STOP first

**HARD STOP.** Before any live request, stop and ask the operator, in Indonesian, for explicit authorization of one read-only Threads capture of three public posts (one video, one image/carousel, one text-only), once per method. Earlier approvals (spec, plan, Stage 2, any earlier capture) do not authorize it. Do not record the authorization as an approval in any repository document; the operator records their own approvals. If authorization is refused, stop the plan here and report Tasks 1–9 as complete with `CONTENT_METHOD` still provisional.

**Files (after authorization):**
- Create: `python/tests/fixtures/threads/video.json`, `image.json`, `text.json`
- Create: `python/tests/acquisition/test_threads_replay.py`
- Modify: `python/src/thoth_control_plane/acquisition/threads_service.py` (`CONTENT_METHOD`)
- Possibly modify: `python/src/thoth_control_plane/acquisition/adapters/threads.py` (key paths, only by ledgered ruling)

**Interfaces:**
- Consumes: Task 9 CLIs and `decide`; Task 7 `parse_documents`; Task 8 `ThreadsAcquirer`.
- Produces: committed sanitized fixtures and the decided `CONTENT_METHOD`.

- [ ] **Step 1: Capture (operator-authorized, live)**

The operator writes `D:/thoth-tmp/bu/threads/urls.txt` with three lines `video <url>`, `image <url>`, `text <url>`. Never print or cat it. Run the capture in the Stage 2 control-plane image (Scrapling and Patchright installed; take `THOTH_IMAGE` from the program checkpoint, or ask the operator if it is not recorded):

```bash
wsl -e bash -lc 'docker run --rm -v /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python/src:/src:ro -v /mnt/d/thoth-tmp/bu/threads:/work -e PYTHONPATH=/src "$THOTH_IMAGE" python -m thoth_control_plane.operations.threads_capture --urls /work/urls.txt --out /work/raw'
```

Expected: three stdout lines of kinds, statuses, and counts; raw JSON and card PNGs under `D:/thoth-tmp/bu/threads/raw/`.

- [ ] **Step 2: Keys-only shape probe**

```bash
cd python && python - <<'PY'
import json
from pathlib import Path
from thoth_control_plane.acquisition.adapters.threads import find_post_node, json_roots

for path in sorted(Path("D:/thoth-tmp/bu/threads/raw").glob("*.json")):
    raw = json.loads(path.read_text(encoding="utf-8"))
    for method in ("request", "headless"):
        capture = raw[method]
        roots = [*capture.get("xhr_bodies", []), *json_roots(capture.get("script_texts", []))]
        node = find_post_node(roots, raw["post_id"])
        print(raw["kind"], method, capture["status"], sorted(node) if node else None)
PY
```

Expected: key names only (no values). If the post node is not found or uses different keys than Task 7 assumed, change the parser's key paths in `adapters/threads.py`, add a synthetic test for the observed shape in `test_threads_adapter.py`, and ledger `Ruling: Threads key paths <old> → <new> — observed in the authorized capture — cost if wrong: replay tests fail`. Rerun `tests/acquisition/test_threads_adapter.py` until green.

- [ ] **Step 3: Sanitize with zero leaks**

```bash
cd python && for kind in video image text; do PYTHONPATH=src python -m thoth_control_plane.operations.threads_fixture --raw "D:/thoth-tmp/bu/threads/raw/$kind.json" --out "tests/fixtures/threads/$kind.json" || break; done
```

(Create `python/tests/fixtures/threads/` first.) Expected: each line reports `"leaks": 0`; a non-zero exit writes no fixture. On a leak, extend the sanitizer allowlist handling, add a test reproducing the leak in `test_threads_fixture.py`, and rerun.

- [ ] **Step 4: Write the replay tests**

`tests/acquisition/test_threads_replay.py`:

```python
"""Sanitized golden fixtures replay through the Threads parser and acquirer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thoth_control_plane.acquisition import threads_service
from thoth_control_plane.acquisition.adapters.threads import (
    canonicalize_threads_post_url,
    parse_documents,
)
from thoth_control_plane.operations.threads_fixture import decide

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "threads"
FIXTURES = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(FIXTURE_DIR.glob("*.json"))}


def _identity(fixture: dict):
    owner, code = fixture["identity"]["owner_handle"], fixture["identity"]["post_id"]
    return canonicalize_threads_post_url(f"https://www.threads.com/@{owner}/post/{code}")


def test_all_three_post_kinds_are_present() -> None:
    assert set(FIXTURES) == {"video", "image", "text"}


@pytest.mark.parametrize("kind", ["video", "image", "text"])
def test_fixture_replays_to_its_expected_parse(kind: str) -> None:
    fixture = FIXTURES[kind]
    parsed = parse_documents([fixture["document"]], _identity(fixture))
    assert parsed is not None
    assert {
        "text": parsed.post.text,
        "media_kinds": [item.kind for item in parsed.media],
        "engagement": parsed.post.engagement,
        "published_at": parsed.post.published_at,
    } == fixture["expected"]


def test_post_kinds_have_their_shape() -> None:
    assert FIXTURES["text"]["expected"]["media_kinds"] == []
    assert FIXTURES["text"]["expected"]["text"].strip()
    assert "video" in FIXTURES["video"]["expected"]["media_kinds"]
    assert FIXTURES["image"]["expected"]["media_kinds"]
    assert set(FIXTURES["image"]["expected"]["media_kinds"]) == {"image"}


def test_content_method_matches_recorded_comparison() -> None:
    pairs = [(f["counts"]["request"], f["counts"]["headless"]) for f in FIXTURES.values()]
    assert threads_service.CONTENT_METHOD == decide(pairs)
```

If the captured image post turns out to mix videos into its carousel, relax only `test_post_kinds_have_their_shape`'s image line to `"image" in ...` and ledger it.

- [ ] **Step 5: Run the replay tests; set the method**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_threads_replay.py`
Expected: every test passes except possibly `test_content_method_matches_recorded_comparison`. If that one fails, set `CONTENT_METHOD` in `threads_service.py` to the value `decide` returns, update its comment to `# Decided by the Stage 3a comparison (restricted evidence in the checkpoint).`, and rerun until PASS. Record the per-kind counts (numbers and statuses only) for Task 11.

- [ ] **Step 6: Commit**

```bash
git add python/tests/fixtures/threads python/tests/acquisition/test_threads_replay.py python/src/thoth_control_plane/acquisition/threads_service.py python/src/thoth_control_plane/acquisition/adapters/threads.py python/tests/acquisition/test_threads_adapter.py python/tests/operations/test_threads_fixture.py python/src/thoth_control_plane/operations/threads_fixture.py
git commit -m "test(acquisition): add threads golden fixtures and method decision"
```

(Only files that actually changed get staged; `git add` of an unchanged path is a no-op.) Never stage `D:/thoth-tmp` content or any PNG.

---

### Task 11: Documentation, full verification, and checkpoint

**Files:**
- Modify: `docs/superpowers/specs/2026-09-28-stage3a-platform-kernel-threads-design.md` (status line, LF)
- Modify: `docs/python-scout-migration-roadmap.md` (CRLF)
- Modify: `CHANGELOG.md` (CRLF)
- Modify: `.superpowers/sdd/2026-09-23-python-scout-migration-program/progress.md` (CRLF, gitignored)

**Interfaces:**
- Consumes: every earlier task's commits and the Task 10 counts.
- Produces: an updated roadmap and changelog, and the checkpoint naming the next gate.

- [ ] **Step 1: Full verification**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests > D:/thoth-tmp/stage3a-suite.txt 2>&1; tail -5 D:/thoth-tmp/stage3a-suite.txt`
Expected: the final summary line reports `passed` with zero `failed`/`error`. Then run ruff (Global Constraints). Expected: `All checks passed!` and no files to reformat. Then run `graphify update .` from the repo root (index only; never staged).

- [ ] **Step 2: Update the spec status line**

Replace line 3 `Status: design approved in chat on 2026-09-28; this written spec awaits operator review.` with `Status: approved by the operator on 2026-09-28; implemented by the Stage 3a plan.`

- [ ] **Step 3: Append the CRLF records**

Use one Python binary script per file (read bytes, assert `endswith(b"\r\n")`, append `section.replace("\n", "\r\n").encode("utf-8")`). Content:
- Roadmap: under the Stage 3 entry, one bullet: Stage 3a implemented (kernel, v3 report, Facebook/Reddit rejection, Threads via `<CONTENT_METHOD>`), Stage 3b Instagram next.
- CHANGELOG: a dated `2026-09-28` entry listing the commits (`git log --oneline master..HEAD`), the suite result line, ruff result, the Threads method decision, and the per-kind counts from Task 10 (numbers and statuses only).
- Checkpoint: a bullet with the branch name, head commit, suite result, the method decision, and `Next gate: operator review of the Stage 3a branch; push and merge are operator actions.`

Do not write that any gate was approved; list the Task 10 capture only as "captured under operator authorization at capture time" with no URL, handle, or path.

- [ ] **Step 4: Commit**

```bash
git add -f docs/superpowers/specs/2026-09-28-stage3a-platform-kernel-threads-design.md
git add docs/python-scout-migration-roadmap.md CHANGELOG.md
git commit -m "docs: record stage 3a platform kernel and threads completion"
```

Stop here. Push, merge, and any live smoke are operator gates.

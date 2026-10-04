# Stage 3d: YouTube Acquisition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route YouTube video and Short URLs to the Python acquisition kernel. Each becomes a
v3 report with a merged MP4 at the highest height that fits under 450 MB, first-page
comments with real cards, and a channel card. Add channel discovery ranked by likes, views,
and recency, and keep yt-dlp fresh with a daily bump workflow and a startup warning.

**Architecture:**
- yt-dlp runs as a Python library (`YtDlpClient`, in a worker thread under a timeout, with
  the `bun` JavaScript runtime) for metadata, first-page comments, flat channel listings,
  and the DASH download that ffmpeg merges into MP4.
- Pure parsers (`adapters/youtube.py`) map yt-dlp's info dict to the report and choose the
  format pair. `MediaMaterializer.adopt` validates and places the merged file like any
  streamed download.
- Cards reuse Stage 3c's `CardBrowser` with a YouTube layout: comment cards from the watch
  page, the profile card from the channel header, no post card.
- Discovery (`youtube_discovery.py`) details the 12 most viewed listed videos and ranks them
  with Instagram's `rank_videos`.
- `operations/yt_dlp_version.py`, a worker startup hook, and `.github/workflows/yt-dlp-update.yml`
  keep yt-dlp current without the worker ever installing anything.

**Tech Stack:** Python 3.12, Pydantic v2, yt-dlp 2026.8.19 (library), Scrapling
(`AsyncStealthySession`) for cards, httpx, pytest with pytest-asyncio (auto mode), Ruff,
GitHub Actions, actionlint.

**Spec:** `docs/superpowers/specs/2026-10-04-stage3d-youtube-design.md` (operator-approved
2026-10-04).

**Names that differ from the spec's sketch** (the behavior is the spec's):
- The spec's `parse_channel(entries)` is `channel_candidates(listings, limit)`.
- The spec's `download(video_id, choice, destination)` is `download(url, choice, directory)`.
- The spec's `latest_from_pypi(fetch)` is split: `latest_from_pypi(payload)` reads the
  answer, and `check_freshness(fetch=None, installed=None)` does the fetch and the warning.

## Global Constraints

**Branch and stability**
- Branch `feat/stage3d-youtube` from `master`.
- Do not push before Task 9. Between Task 1 (YouTube routes to `python`) and Task 4 (the
  registry branch), the branch is not deployable.
- TikTok, Threads, Instagram, and X behavior is unchanged. Facebook and Reddit stay
  `unsupported`. After this stage no post URL routes to legacy Scout for acquisition.
- No new failure codes. `RETRYABLE_FAILURES` and `LEGACY_FALLBACK_ELIGIBLE_CODES` are
  unchanged.
- yt-dlp is pinned identically in the `acquisition` and `scout-runtime` extras
  (`yt-dlp==2026.8.19`).

**Media policy**
- Heights 1080, then 720, then 480, by the shorter side (a vertical Short is classed by its
  width). Only `protocol == "https"` MP4 video-only plus `m4a` audio.
- The estimated video plus audio size must stay under 450 MB (`filesize`, else
  `filesize_approx`, else `tbr * 1000 / 8 * duration`). Otherwise `media_validation_failed`.

**Safety**
- No live test in the suite. Never change the conftest `_offline_unless_live` guard.
- A card is never synthetic. Card failures never fail acquisition and never enter
  `outcome.attempts`.
- yt-dlp's own log messages are discarded (`_Silent`); they can carry URLs.
- Logs never carry a URL, a raw handle, a title, a description, or comment text.
- The worker never installs or upgrades anything. The API health route never calls PyPI.

**Live capture**
- Task 8 is a HARD STOP. The live capture needs operator authorization at capture time.
- Raw captures, URL files, and PNGs live only under `D:/thoth-tmp/bu/youtube/`.
  - Never commit, print, or describe them beyond counts, keys, and enums.
  - Never print a field of `urls.txt`, a page path, or a handle.
  - Mask any URL in shell output with `sed -E 's#https?://[^ "]+#<url>#g'`.

**Commands**
- Tests: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh <paths relative to python/> -q`.
- Ruff: `wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff check . && ~/.local/bin/uvx ruff format --check .'`.
- actionlint: `wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER && docker run --rm -v "$PWD":/repo -w /repo rhysd/actionlint:latest -shellcheck= .github/workflows/yt-dlp-update.yml .github/workflows/container-image.yml'`.
- Browser tagging tests skip locally without Playwright. Run them in the capture image
  (`<paths>` relative to `python/`):
  `wsl -e bash -lc 'docker run --rm -v /mnt/c/Users/mfr/Documents/MyTools/CLIPPER:/repo ghcr.io/muhfalihr/thoth@sha256:56fa84e6f99fe1d59c94ed0389236866c0b82fd0d5a0119e1d996bd5c9e5adf9 bash -c "pip install -q --target /tmp/pt pytest pytest-asyncio >/dev/null 2>&1 && cd /repo/python && PYTHONPATH=/tmp/pt:/repo/python/src python -m pytest <paths> -q -p no:cacheprovider -o asyncio_mode=auto"'`.

**Files with CRLF working copies**
- `.github/workflows/container-image.yml`, `python/pyproject.toml`, `CHANGELOG.md`, the
  roadmap, `AGENTS.md`, and the program checkpoint are edited only with binary Python that
  preserves CRLF. Never `sed -i` them.

**Commits and staging**
- Exactly one `git commit -m "<subject>"`, at most 72 characters, with no body, no
  trailer, and no AI attribution. `docs/superpowers/` needs `git add -f`.
- Never stage `graphify-out/`, `build_log.txt`, `.superpowers`, `.understand-anything`,
  `.env.stage1.local.bak-*`, or the untracked `design/` files.

## Review Focus

1. **A Short.** Its formats are vertical (1080×1920). It must be classed by its shorter
   side, so 1080 wide is 1080p, not 1920p, and its comments come from `/watch?v=<id>`, never
   the Shorts page. Task 2: `test_a_vertical_short_is_classed_by_its_short_side`. Task 4:
   `test_cards_crop_comments_and_the_channel_header_never_a_post`.
2. **Formats without a declared size, or only HLS and WebM.** Size is estimated from
   bitrate times duration; HLS, WebM, and formats with no size and no bitrate are never
   chosen. Task 2: `test_size_is_estimated_from_bitrate_when_undeclared`,
   `test_hls_webm_and_unsized_formats_are_never_chosen`.
3. **A download or merge that fails half-way.** Nothing stays under the artifact root: no
   work directory, no partial file. Task 4:
   `test_a_failed_download_or_adopt_leaves_nothing_behind`.
4. **A comment author whose handle has characters outside the handle pattern** (YouTube
   allows non-ASCII handles). The comment is kept, credited to the author's channel id.
   Task 2: `test_a_comment_author_outside_the_pattern_falls_back_to_the_author_id`.
5. **A worker stopped while the yt-dlp check is still waiting on PyPI.** The background task
   is cancelled with the worker and never blocks startup. Task 6:
   `test_the_yt_dlp_check_runs_in_the_background_and_stops_with_the_worker`.

## File Structure

| File | Responsibility |
|---|---|
| `python/src/thoth_control_plane/acquisition/platforms.py` | Add the `youtube` host set. |
| `python/src/thoth_control_plane/acquisition/models.py` | `CommentId`, `DiscoveredVideo.post_id: SafeId`, `YT_DLP`, `"youtube"` source. |
| `python/src/thoth_control_plane/acquisition/normalize.py` | `numeric_id`, so numeric platforms keep numeric ids. |
| `python/src/thoth_control_plane/acquisition/{discovery,instagram_discovery,x_discovery}.py`, `adapters/{instagram,x}.py` | Apply `numeric_id`. |
| `python/src/thoth_control_plane/acquisition/adapters/youtube.py` (new) | URL identity, `parse_info`, `select_formats`, `channel_candidates`. |
| `python/src/thoth_control_plane/acquisition/materializer.py` | `MediaMaterializer.adopt`. |
| `python/src/thoth_control_plane/acquisition/youtube_service.py` (new) | `YtDlpClient`, `classify`, `YouTubeHeadlessBrowser`, `YouTubeAcquirer`. |
| `python/src/thoth_control_plane/acquisition/registry.py` | YouTube branch. |
| `python/src/thoth_control_plane/acquisition/youtube_discovery.py` (new) | Channel discovery. |
| `python/src/thoth_control_plane/operations/yt_dlp_version.py` (new) | Freshness check. |
| `python/src/thoth_control_plane/worker.py` | Background freshness check at startup. |
| `.github/workflows/yt-dlp-update.yml` (new), `.github/workflows/container-image.yml` | Daily bump, and the dispatch trigger. |
| `python/pyproject.toml`, `python/uv.lock` | yt-dlp in the `acquisition` extra. |
| `python/src/thoth_control_plane/operations/youtube_capture.py`, `youtube_fixture.py` (new) | Operator capture CLI, sanitizer and leak check. |
| `python/tests/acquisition/test_youtube_{adapter,service,acquirer,comment_tagging,discovery,replay}.py`, `test_materializer_adopt.py` (new) | Offline tests. |
| `python/tests/operations/test_youtube_{capture,fixture}.py`, `test_yt_dlp_version.py` (new) | Tool tests. |
| `python/tests/fixtures/youtube/{video,short,channel}.json` (new, Task 8) | Golden fixtures. |

---

### Task 1: Route YouTube to the Python kernel and widen the shared ids

**Files:**
- Modify: `python/src/thoth_control_plane/acquisition/platforms.py:12-19`
- Modify: `python/src/thoth_control_plane/acquisition/models.py` (`CommentId`,
  `AcquisitionStrategy`, `ReportComment`, `ReportSource`, `DiscoveredVideo`)
- Modify: `python/src/thoth_control_plane/acquisition/normalize.py`
- Modify: `python/src/thoth_control_plane/acquisition/discovery.py` (`_video`),
  `instagram_discovery.py` (`_video`), `x_discovery.py` (`_video`),
  `adapters/instagram.py` (`_comment`), `adapters/x.py` (`_comment`)
- Test: `python/tests/acquisition/test_platforms.py`, `test_models.py`, `test_registry.py`,
  `test_x_adapter.py`, `test_discovery.py`, `python/tests/activities/test_source_investigation.py`,
  `python/tests/workflows/test_source_investigation.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `PYTHON_PLATFORM_HOSTS["youtube"]`; `platform_of(url) == "youtube"` for YouTube hosts.
  - `ReportSource(platform="youtube")`; `AcquisitionStrategy.YT_DLP` (`"yt_dlp"`).
  - `CommentId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{5,64}$")]`, used by
    `ReportComment.comment_id`.
  - `DiscoveredVideo.post_id: SafeId`.
  - `normalize.numeric_id(value: object) -> str | None`.

Widening the comment and discovery ids would let a non-numeric TikTok, Instagram, or X id
through; `numeric_id` keeps those platforms numeric. `bare_host` already strips `www.` and
`m.`, so `m.youtube.com` routes, while `music.youtube.com` stays legacy. Tests that used a
YouTube URL as their legacy example switch to `https://vimeo.com/123`.

- [ ] **Step 1: Write the failing tests**

In `python/tests/acquisition/test_platforms.py`, replace the row
`("https://www.youtube.com/watch?v=abc", "legacy"),` with:

```python
        ("https://www.youtube.com/watch?v=abc", "python"),
        ("https://m.youtube.com/watch?v=abc", "python"),
        ("https://youtu.be/abc", "python"),
        ("https://music.youtube.com/watch?v=abc", "legacy"),
        ("https://vimeo.com/123", "legacy"),
```

In `test_platform_of_names_python_platforms_only`, replace
`assert platform_of("https://www.youtube.com/watch?v=abc") is None` with:

```python
    assert platform_of("https://www.youtube.com/watch?v=abc") == "youtube"
    assert platform_of("https://vimeo.com/123") is None
```

In `python/tests/acquisition/test_models.py`, after `test_v3_report_accepts_an_x_source`,
add:

```python
def test_v3_report_accepts_a_youtube_source_and_string_comment_ids() -> None:
    report = _v3(
        source={"platform": "youtube", "canonical_url": "https://www.youtube.com/watch?v=abc"},
        comments=[{"comment_id": "UgzAbC-1_x", "author": "user_001", "text": "x"}],
    )
    assert (report.source.platform, report.comments[0].comment_id) == ("youtube", "UgzAbC-1_x")


@pytest.mark.parametrize("comment_id", ["abc", "has space", "a/b", "x" * 65])
def test_a_comment_id_outside_the_safe_pattern_is_rejected(comment_id: str) -> None:
    with pytest.raises(ValidationError):
        ReportComment(comment_id=comment_id, author="user_001", text="x")


def test_the_yt_dlp_strategy_is_a_method_label() -> None:
    assert AcquisitionStrategy("yt_dlp") is AcquisitionStrategy.YT_DLP
```

At the end of `python/tests/acquisition/test_x_adapter.py`, add:

```python
def test_a_reply_with_a_non_numeric_id_is_dropped() -> None:
    # The report's comment id admits YouTube's string ids; X ids stay numeric.
    page = parse_page(_roots(POST_NODE, _tweet("abc12345")), IDENTITY)
    assert (page.comments, page.dropped_comments) == ([], 1)
```

In `python/tests/acquisition/test_discovery.py`,
`test_ads_photo_posts_and_invalid_items_are_dropped_and_counted`, add one item after
`_item("1000000006", author={}),` and raise the invalid count from 4 to 5:

```python
        # The model admits YouTube's string ids; TikTok ids stay numeric.
        _item("abcdefghijk"),
```

```python
    assert page.drops == DiscoveryDrops(ads=1, photo_posts=1, invalid=5)
```

Replace `"https://www.youtube.com/watch?v=abc"` with `"https://vimeo.com/123"` in:
- `python/tests/acquisition/test_registry.py`: the `pytest.raises(LookupError)` call, which
  then fits on one line:
  `acquirer_for("https://vimeo.com/123", client=client, materializer=materializer)`;
- `python/tests/activities/test_source_investigation.py`:
  `test_unknown_platform_never_enters_the_runner`;
- `python/tests/workflows/test_source_investigation.py`: both routing rows that use it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_platforms.py tests/acquisition/test_models.py tests/acquisition/test_discovery.py tests/acquisition/test_x_adapter.py -q`
Expected: FAIL on the new `python` rows, on `platform_of(...) == "youtube"`, on the YouTube
model test, and on the `yt_dlp` label. The X and TikTok drop tests still pass here (the
narrow model rejects their ids); they turn into the guard's tests in Step 3.

- [ ] **Step 3: Implement**

In `platforms.py`, add the row after `"x"`:

```python
    "youtube": frozenset({"youtube.com", "youtu.be"}),
```

In `models.py`, add after `TikTokNumericId`:

```python
# Report comment ids: numeric on TikTok, Instagram, and X; base64-like on YouTube (`Ugz…`).
CommentId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{5,64}$")]
```

Then:
- add `YT_DLP = "yt_dlp"` as the last `AcquisitionStrategy` member;
- `ReportComment.comment_id: CommentId`;
- `ReportSource.platform: Literal["tiktok", "threads", "instagram", "x", "youtube"]`;
- in `DiscoveredVideo`:

```python
    # Numeric on TikTok, Instagram, and X (their parsers check); an 11-character id on YouTube.
    post_id: SafeId
```

In `normalize.py`, add `import re`, then after `MAX_INT64_DIGITS`:

```python
# TikTok, Instagram, and X ids are numeric. Report and discovery models admit YouTube's string
# ids too, so the numeric platforms check theirs here.
NUMERIC_ID = re.compile(r"[0-9]{5,32}")
```

and after `_pick`:

```python
def numeric_id(value: object) -> str | None:
    """`value` as a numeric id string (an int or an ASCII digit string of 5-32), else None."""
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    return value if isinstance(value, str) and NUMERIC_ID.fullmatch(value) else None
```

Apply it (import `numeric_id` from `normalize` in each file):

`discovery.py`, `_video`:

```python
    post_id = numeric_id(item.get("id")) if isinstance(item.get("id"), str) else None
    author = item.get("author")
    handle = author.get("uniqueId") if isinstance(author, dict) else None
    if post_id is None or not isinstance(handle, str):
        return None
```

`instagram_discovery.py`, `_video`:

```python
    code = node.get("code")
    pk = numeric_id(node.get("pk"))
    if not isinstance(code, str) or CODE.fullmatch(code) is None or pk is None:
        return None
```

and `post_id=pk,` in the `DiscoveredVideo(...)` call.

`x_discovery.py`, `_video`, before the `try`:

```python
    rest_id = numeric_id(tweet["rest_id"])
    if rest_id is None:
        return None
```

and `post_id=rest_id,` plus `canonical_url=post_url(owner, rest_id),`.

`adapters/instagram.py`, `_comment`:

```python
    text = node.get("text")
    pk = numeric_id(node.get("pk"))
    if not isinstance(text, str) or not text.strip() or pk is None:
        return None
```

and `comment_id=pk,`.

`adapters/x.py`, `_comment`:

```python
    author, text = author_of(tweet), tweet_text(tweet)
    rest_id = numeric_id(tweet["rest_id"])
    if author is None or not text or rest_id is None:
        return None
```

and `comment_id=rest_id,`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition tests/activities tests/workflows -q`
Expected: PASS. To prove the guards matter, temporarily make `numeric_id` return
`str(value)` for any string: `test_a_reply_with_a_non_numeric_id_is_dropped`, the TikTok
drop test, and Instagram's `pk="not-numeric"` test fail. Restore it.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/platforms.py python/src/thoth_control_plane/acquisition/models.py python/src/thoth_control_plane/acquisition/normalize.py python/src/thoth_control_plane/acquisition/discovery.py python/src/thoth_control_plane/acquisition/instagram_discovery.py python/src/thoth_control_plane/acquisition/x_discovery.py python/src/thoth_control_plane/acquisition/adapters/instagram.py python/src/thoth_control_plane/acquisition/adapters/x.py python/tests/acquisition/test_platforms.py python/tests/acquisition/test_models.py python/tests/acquisition/test_registry.py python/tests/acquisition/test_x_adapter.py python/tests/acquisition/test_discovery.py python/tests/activities/test_source_investigation.py python/tests/workflows/test_source_investigation.py
git commit -m "feat(acquisition): route youtube urls to the python kernel"
```

---

### Task 2: YouTube URL identity and parsers

**Files:**
- Create: `python/src/thoth_control_plane/acquisition/adapters/youtube.py`
- Test: `python/tests/acquisition/test_youtube_adapter.py`

**Interfaces:**
- Consumes: Task 1's `CommentId` (through `ReportComment`) and `PYTHON_PLATFORM_HOSTS["youtube"]`,
  through `_match_safe_path(url, pattern, "youtube", YouTubeUrlError)`. Also `_https`,
  `_match_safe_path` (`adapters/threads.py`), `_count`, `published_at_from_epoch`
  (`normalize.py`), and `MAX_POST_TEXT`.
- Produces:
  - Constants: `CANONICAL_BASE = "https://www.youtube.com"`, `VIDEO_ID`, `HANDLE`,
    `CHANNEL_ID`, `TARGET_HEIGHTS = (1080, 720, 480)`, `MAX_DOWNLOAD_BYTES = 450 * 1024 * 1024`.
  - Types:
    - `YouTubeUrlError(ValueError)`;
    - `YouTubeIdentity(canonical_url: HttpUrl, video_id: str)`;
    - `YouTubeParse(post, comments, dropped_comments=0, duration_seconds=None, channel_url: str)`;
    - `@dataclass(frozen=True) FormatChoice(video_format: str, audio_format: str, short_side: int, estimated_bytes: int)`.
  - Functions:
    - `canonicalize_youtube_url(url: str) -> YouTubeIdentity`;
    - `video_url(video_id: str) -> str` (`https://www.youtube.com/watch?v=<id>`);
    - `parse_info(info: object, identity: YouTubeIdentity) -> YouTubeParse | None`;
    - `select_formats(formats: object, duration: float | None) -> FormatChoice | None`;
    - `channel_candidates(listings: Iterable[object], limit: int) -> list[str]`.

Facts from the probe (spec section 2): there are no progressive formats; video-only MP4
reaches 2160p (1920 on a vertical Short); audio is `m4a` or `webm`. yt-dlp's comment
dicts carry `id`, `parent` (`"root"` for top level), `author` (with `@`), `author_id`,
`text`, and `like_count`. Flat channel listings carry ids and `view_count` only.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/acquisition/test_youtube_adapter.py`:

```python
"""YouTube URL identity and the pure yt-dlp info parsers; no network."""

from __future__ import annotations

from typing import Any

import pytest

from thoth_control_plane.acquisition.adapters.youtube import (
    MAX_DOWNLOAD_BYTES,
    YouTubeIdentity,
    YouTubeUrlError,
    canonicalize_youtube_url,
    channel_candidates,
    parse_info,
    select_formats,
)

VIDEO_ID = "abcDEF123_-"
IDENTITY = YouTubeIdentity(
    canonical_url=f"https://www.youtube.com/watch?v={VIDEO_ID}", video_id=VIDEO_ID
)
MB = 1024 * 1024


def _comment(n: int, **extra: Any) -> dict[str, Any]:
    return {
        "id": f"UgzComment{n:03d}",
        "parent": "root",
        "author": f"@fan_{n:03d}",
        "author_id": f"UCfan{n:03d}",
        "text": f"comment {n}",
        "like_count": n,
        **extra,
    }


def _info(**extra: Any) -> dict[str, Any]:
    return {
        "id": VIDEO_ID,
        "title": "A title",
        "description": "A description",
        "uploader_id": "@user_001",
        "channel_id": "UCuser001abcdefghijklmno",
        "timestamp": 1_714_566_896,
        "view_count": 4_500,
        "like_count": 120,
        "comment_count": 34,
        "duration": 600,
        "live_status": "not_live",
        "comments": [_comment(1), _comment(2)],
        **extra,
    }


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VIDEO_ID}",
        f"https://youtube.com/watch?v={VIDEO_ID}&t=42s&si=abc",
        f"https://m.youtube.com/watch?v={VIDEO_ID}",
        f"https://www.youtube.com/shorts/{VIDEO_ID}?feature=share",
        f"https://www.youtube.com/embed/{VIDEO_ID}",
        f"https://www.youtube.com/live/{VIDEO_ID}/",
        f"https://youtu.be/{VIDEO_ID}?si=abc",
        f"https://WWW.YouTube.COM./watch?v={VIDEO_ID}#frag",
    ],
)
def test_video_url_shapes_canonicalize(url: str) -> None:
    assert canonicalize_youtube_url(url) == IDENTITY


@pytest.mark.parametrize(
    "url",
    [
        f"http://www.youtube.com/watch?v={VIDEO_ID}",
        "https://www.youtube.com/@someone",
        "https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv",
        f"https://www.youtube.com/{VIDEO_ID}",
        "https://www.youtube.com/watch?v=short",
        f"https://www.youtube.com/watch?v={VIDEO_ID}&v=zzzzzzzzzzz",
        f"https://youtu.be/{VIDEO_ID}/extra",
        f"https://evil.example/watch?v={VIDEO_ID}",
        f"https://www.youtube.com:8443/watch?v={VIDEO_ID}",
        f"https://music.youtube.com/watch?v={VIDEO_ID}",
        "not a url",
    ],
)
def test_non_video_urls_are_rejected(url: str) -> None:
    with pytest.raises(YouTubeUrlError):
        canonicalize_youtube_url(url)


def test_info_parses_text_counts_date_and_comments() -> None:
    parsed = parse_info(_info(), IDENTITY)
    assert parsed is not None
    assert parsed.post.post_id == VIDEO_ID
    assert parsed.post.owner_handle == "user_001"
    assert parsed.post.text == "A title\n\nA description"
    assert parsed.post.engagement == {"play": 4_500, "like": 120, "comment": 34}
    assert parsed.post.published_at == "2024-05-01T12:34:56Z"
    assert parsed.duration_seconds == 600.0
    assert parsed.channel_url == "https://www.youtube.com/channel/UCuser001abcdefghijklmno"


def test_a_channel_without_a_valid_id_is_reached_by_handle() -> None:
    parsed = parse_info(_info(channel_id="not-a-channel"), IDENTITY)
    assert parsed.channel_url == "https://www.youtube.com/@user_001"
    assert [(c.comment_id, c.author, c.text, c.likes) for c in parsed.comments] == [
        ("UgzComment001", "fan_001", "comment 1", 1),
        ("UgzComment002", "fan_002", "comment 2", 2),
    ]


def test_an_owner_without_a_handle_falls_back_to_the_channel_id() -> None:
    parsed = parse_info(_info(uploader_id=None), IDENTITY)
    assert parsed is not None
    assert parsed.post.owner_handle == "UCuser001abcdefghijklmno"


def test_a_comment_author_outside_the_pattern_falls_back_to_the_author_id() -> None:
    parsed = parse_info(_info(comments=[_comment(1, author="@名前")]), IDENTITY)
    assert [c.author for c in parsed.comments] == ["UCfan001"]


def test_replies_duplicates_and_invalid_comments() -> None:
    comments = [
        _comment(1),
        _comment(1),
        _comment(2, parent="UgzComment001"),
        _comment(3, text="   "),
        _comment(4, id="bad id"),
        _comment(5),
    ]
    parsed = parse_info(_info(comments=comments), IDENTITY)
    assert [c.comment_id for c in parsed.comments] == ["UgzComment001", "UgzComment005"]
    assert parsed.dropped_comments == 3


def test_comments_cap_at_fifty() -> None:
    parsed = parse_info(_info(comments=[_comment(n) for n in range(60)]), IDENTITY)
    assert len(parsed.comments) == 50


@pytest.mark.parametrize(
    "info",
    [
        _info(id="otherVideo1"),
        _info(live_status="is_live"),
        _info(live_status="is_upcoming"),
        _info(uploader_id="bad handle", channel_id=None),
        "not a dict",
    ],
)
def test_other_ids_unfinished_streams_and_bad_owners_are_no_parse(info: object) -> None:
    assert parse_info(info, IDENTITY) is None


def test_missing_counts_and_text_are_skipped() -> None:
    parsed = parse_info(
        _info(title=None, description="  ", view_count=None, like_count=-1, timestamp="x"),
        IDENTITY,
    )
    assert parsed is not None
    assert (parsed.post.text, parsed.post.engagement, parsed.post.published_at) == (
        "",
        {"comment": 34},
        None,
    )


def _video(fid: str, width: int, height: int, size: int | None, tbr: float = 1_000.0, **extra):
    return {
        "format_id": fid,
        "protocol": "https",
        "url": f"https://media.example.test/{fid}",
        "ext": "mp4",
        "vcodec": "avc1",
        "acodec": "none",
        "width": width,
        "height": height,
        "tbr": tbr,
        "filesize": size,
        **extra,
    }


AUDIO = {
    "format_id": "140",
    "protocol": "https",
    "url": "https://media.example.test/140",
    "ext": "m4a",
    "vcodec": "none",
    "acodec": "mp4a",
    "tbr": 128.0,
    "filesize": 10 * MB,
}


def test_the_highest_fitting_height_wins() -> None:
    formats = [
        _video("137", 1920, 1080, 200 * MB),
        _video("136", 1280, 720, 100 * MB),
        _video("313", 3840, 2160, 900 * MB),
        AUDIO,
    ]
    choice = select_formats(formats, 600.0)
    assert (choice.video_format, choice.audio_format, choice.short_side) == ("137", "140", 1080)
    assert choice.estimated_bytes == 210 * MB


def test_a_too_large_1080p_steps_down_to_720p_then_480p() -> None:
    formats = [
        _video("137", 1920, 1080, 600 * MB),
        _video("136", 1280, 720, 445 * MB),
        _video("135", 854, 480, 100 * MB),
        AUDIO,
    ]
    assert select_formats(formats, 600.0).video_format == "135"


def test_a_vertical_short_is_classed_by_its_short_side() -> None:
    formats = [_video("137", 1080, 1920, 20 * MB), _video("136", 720, 1280, 10 * MB), AUDIO]
    choice = select_formats(formats, 40.0)
    assert (choice.video_format, choice.short_side) == ("137", 1080)


def test_size_is_estimated_from_bitrate_when_undeclared() -> None:
    # 2,000 kbit/s for 600 s is 150,000,000 bytes; with 10 MB of audio it fits.
    formats = [_video("137", 1920, 1080, None, tbr=2_000.0), AUDIO]
    choice = select_formats(formats, 600.0)
    assert choice.estimated_bytes == 150_000_000 + 10 * MB


def test_hls_webm_and_unsized_formats_are_never_chosen() -> None:
    formats = [
        _video("hls", 1920, 1080, 10 * MB, protocol="m3u8_native"),
        _video("webm", 1920, 1080, 10 * MB, ext="webm"),
        _video("nosize", 1920, 1080, None, tbr=None),
        _video("135", 854, 480, 10 * MB),
        AUDIO,
    ]
    assert select_formats(formats, None).video_format == "135"


def test_nothing_fits_or_no_audio_is_no_choice() -> None:
    too_big = [_video("135", 854, 480, MAX_DOWNLOAD_BYTES), AUDIO]
    assert select_formats(too_big, 600.0) is None
    assert select_formats([_video("135", 854, 480, MB)], 600.0) is None
    assert select_formats("not a list", 600.0) is None


def test_channel_candidates_are_the_most_viewed_each_once() -> None:
    videos = {
        "entries": [{"id": "aaaaaaaaaaa", "view_count": 5}, {"id": "bbbbbbbbbbb", "view_count": 50}]
    }
    shorts = {
        "entries": [
            {"id": "ccccccccccc", "view_count": 500},
            {"id": "aaaaaaaaaaa", "view_count": 999},
            {"id": "bad", "view_count": 1},
            {"id": "ddddddddddd"},
        ]
    }
    assert channel_candidates([videos, shorts], 2) == ["ccccccccccc", "bbbbbbbbbbb"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_youtube_adapter.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'thoth_control_plane.acquisition.adapters.youtube'`.

- [ ] **Step 3: Implement**

Create `python/src/thoth_control_plane/acquisition/adapters/youtube.py`:

```python
"""SSRF-safe YouTube URL identity and pure parsing of yt-dlp's extracted info.

yt-dlp (a library, run by the service) answers metadata, formats, and first-page comments;
everything here only reads its dicts. The format choice takes the highest of 1080p, 720p,
and 480p whose MP4 video and M4A audio fit the download cap. Nothing here performs I/O.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

from pydantic import HttpUrl

from thoth_control_plane.acquisition.adapters.threads import _match_safe_path
from thoth_control_plane.acquisition.models import (
    MAX_COMMENTS,
    MAX_POST_TEXT,
    ReportComment,
    SourcePost,
)
from thoth_control_plane.acquisition.normalize import _count, published_at_from_epoch
from thoth_control_plane.acquisition.platforms import bare_host
from thoth_control_plane.domain.models import StrictModel

CANONICAL_BASE = "https://www.youtube.com"
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
ANY_PATH = re.compile(r"/.*")
WATCH_PATH = re.compile(r"/watch/?")
ID_PATH = re.compile(r"/(?:shorts|embed|live)/(?P<id>[A-Za-z0-9_-]{11})/?")
SHORT_LINK_PATH = re.compile(r"/(?P<id>[A-Za-z0-9_-]{11})/?")
HANDLE = re.compile(r"[A-Za-z0-9._-]{1,64}")
CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")
MAX_COMMENT_TEXT = 2_000
UNFINISHED = ("is_live", "is_upcoming")
TARGET_HEIGHTS = (1080, 720, 480)
MAX_DOWNLOAD_BYTES = 450 * 1024 * 1024


class YouTubeUrlError(ValueError):
    """Raised when a URL is not a safe, supported public YouTube video URL."""


class YouTubeIdentity(StrictModel):
    canonical_url: HttpUrl
    video_id: str


class YouTubeParse(StrictModel):
    post: SourcePost
    comments: list[ReportComment]
    dropped_comments: int = 0
    duration_seconds: float | None = None
    # The owner's channel page, for the profile card: by channel id, else by handle.
    channel_url: str


@dataclass(frozen=True)
class FormatChoice:
    video_format: str
    audio_format: str
    short_side: int
    estimated_bytes: int


def canonicalize_youtube_url(url: str) -> YouTubeIdentity:
    """Reduce a watch, Shorts, embed, live, or youtu.be URL to `/watch?v=<id>`."""
    _match_safe_path(url, ANY_PATH, "youtube", YouTubeUrlError)
    parts = urlsplit(url)
    found: str | None = None
    if bare_host(parts.hostname or "") == "youtu.be":
        match = SHORT_LINK_PATH.fullmatch(parts.path)
        found = match.group("id") if match else None
    elif WATCH_PATH.fullmatch(parts.path):
        values = parse_qs(parts.query).get("v", [])
        found = values[0] if len(values) == 1 and VIDEO_ID.fullmatch(values[0]) else None
    else:
        match = ID_PATH.fullmatch(parts.path)
        found = match.group("id") if match else None
    if found is None:
        raise YouTubeUrlError("invalid_source_url")
    return YouTubeIdentity(canonical_url=video_url(found), video_id=found)


def video_url(video_id: str) -> str:
    return f"{CANONICAL_BASE}/watch?v={video_id}"


def _handle(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    handle = value.removeprefix("@")
    return handle if HANDLE.fullmatch(handle) else None


def _comment(node: object) -> ReportComment | None:
    if not isinstance(node, dict) or node.get("parent") != "root":
        return None
    text = node.get("text")
    author = _handle(node.get("author")) or _handle(node.get("author_id"))
    if not isinstance(text, str) or not text.strip() or author is None:
        return None
    try:
        return ReportComment(
            comment_id=str(node.get("id")),
            author=author,
            text=text[:MAX_COMMENT_TEXT],
            likes=_count(node.get("like_count")) or 0,
        )
    except ValueError:
        return None


def _comments(nodes: object) -> tuple[list[ReportComment], int]:
    comments: list[ReportComment] = []
    seen: set[str] = set()
    dropped = 0
    for node in nodes if isinstance(nodes, list) else []:
        if isinstance(node, dict) and node.get("parent") not in (None, "root"):
            continue  # A reply; first-page top-level comments only.
        if len(comments) == MAX_COMMENTS:
            break
        comment = _comment(node)
        if comment is None or comment.comment_id in seen:
            dropped += 1
            continue
        seen.add(comment.comment_id)
        comments.append(comment)
    return comments, dropped


def parse_info(info: object, identity: YouTubeIdentity) -> YouTubeParse | None:
    """Parse yt-dlp's info for the identity's video; None for another id, a live or upcoming
    stream (no final video yet), or no valid owner."""
    if not isinstance(info, dict) or info.get("id") != identity.video_id:
        return None
    if info.get("live_status") in UNFINISHED:
        return None
    owner = _handle(info.get("uploader_id")) or _handle(info.get("channel_id"))
    if owner is None:
        return None
    channel_id = info.get("channel_id")
    channel = (
        f"{CANONICAL_BASE}/channel/{channel_id}"
        if isinstance(channel_id, str) and CHANNEL_ID.fullmatch(channel_id)
        else f"{CANONICAL_BASE}/@{owner}"
    )
    parts = [info.get(key) for key in ("title", "description")]
    text = "\n\n".join(part for part in parts if isinstance(part, str) and part.strip())
    names = (("play", "view_count"), ("like", "like_count"), ("comment", "comment_count"))
    engagement = {
        key: count for key, name in names if (count := _count(info.get(name))) is not None
    }
    duration = info.get("duration")
    comments, dropped = _comments(info.get("comments"))
    return YouTubeParse(
        post=SourcePost(
            post_id=identity.video_id,
            owner_handle=owner,
            text=text[:MAX_POST_TEXT],
            published_at=published_at_from_epoch(info.get("timestamp")),
            engagement=engagement,
        ),
        comments=comments,
        dropped_comments=dropped,
        duration_seconds=float(duration)
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration >= 0
        else None,
        channel_url=channel,
    )


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return float(value)


def _size(fmt: dict[str, Any], duration: float | None) -> int | None:
    """Declared bytes, else bitrate (kbit/s) x duration."""
    for key in ("filesize", "filesize_approx"):
        if (declared := _number(fmt.get(key))) is not None:
            return int(declared)
    bitrate = _number(fmt.get("tbr"))
    if bitrate is None or duration is None:
        return None
    return int(bitrate * 1000 / 8 * duration)


def _short_side(fmt: dict[str, Any]) -> int | None:
    """The resolution class: 1080 for both 1920x1080 and a vertical 1080x1920 Short."""
    sides = [int(n) for n in (fmt.get("width"), fmt.get("height")) if _number(n) is not None]
    if not sides:
        return None
    return min(sides) if len(sides) == 2 else sides[0]


def _plain_https(fmt: object) -> bool:
    return (
        isinstance(fmt, dict)
        and fmt.get("protocol") == "https"
        and isinstance(fmt.get("format_id"), str)
        and bool(fmt.get("url"))
    )


def select_formats(formats: object, duration: float | None) -> FormatChoice | None:
    """The highest of 1080p, 720p, 480p whose MP4 video plus M4A audio stays under the cap."""
    listed = [f for f in (formats if isinstance(formats, list) else []) if _plain_https(f)]
    audios = [
        f
        for f in listed
        if f.get("vcodec") == "none"
        and f.get("acodec") not in (None, "none")
        and f.get("ext") == "m4a"
    ]
    if not audios:
        return None
    audio = max(audios, key=lambda f: _number(f.get("tbr")) or 0.0)
    audio_bytes = _size(audio, duration)
    if audio_bytes is None:
        return None
    videos = [
        f
        for f in listed
        if f.get("acodec") == "none"
        and f.get("vcodec") not in (None, "none")
        and f.get("ext") == "mp4"
        and _short_side(f) is not None
    ]
    for target in TARGET_HEIGHTS:
        fitting = [f for f in videos if (_short_side(f) or 0) <= target]
        if not fitting:
            continue
        video = max(fitting, key=lambda f: (_short_side(f) or 0, _number(f.get("tbr")) or 0.0))
        video_bytes = _size(video, duration)
        if video_bytes is None:
            continue
        total = video_bytes + audio_bytes
        if total < MAX_DOWNLOAD_BYTES:
            return FormatChoice(
                video_format=video["format_id"],
                audio_format=audio["format_id"],
                short_side=_short_side(video) or 0,
                estimated_bytes=total,
            )
    return None


def channel_candidates(listings: Iterable[object], limit: int) -> list[str]:
    """Video ids from flat channel listings, the most viewed first, each once."""
    views: dict[str, int] = {}
    for listing in listings:
        entries = listing.get("entries") if isinstance(listing, dict) else None
        for entry in entries if isinstance(entries, list) else []:
            video_id = entry.get("id") if isinstance(entry, dict) else None
            count = _count(entry.get("view_count")) if isinstance(entry, dict) else None
            if isinstance(video_id, str) and VIDEO_ID.fullmatch(video_id) and count is not None:
                views.setdefault(video_id, count)
    ranked: Sequence[str] = sorted(views, key=lambda video_id: -views[video_id])
    return list(ranked[:limit])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_youtube_adapter.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/adapters/youtube.py python/tests/acquisition/test_youtube_adapter.py
git commit -m "feat(acquisition): add youtube url identity and info parsers"
```

---

### Task 3: Adopt a locally downloaded file

**Files:**
- Modify: `python/src/thoth_control_plane/acquisition/materializer.py`
- Test: `python/tests/acquisition/test_materializer_adopt.py`

**Interfaces:**
- Consumes: the existing `MEDIA_BYTE_BOUNDS`, `MEDIA_TYPES`, `_sniff`, `_SUFFIXES`,
  `_HEADER_PROBE_BYTES`, and `MediaMaterializationError` in `materializer.py`; `MediaKind`
  from `models.py`.
- Produces: `async MediaMaterializer.adopt(source: Path, destination: Path, relative_location: PurePosixPath, strategy: AcquisitionStrategy | str, *, kind: MediaKind = "video", media_id: str = "media_1", index: int = 1, duration_seconds: float | None = None) -> MaterializedMedia`.
  It applies the byte bounds, the magic-byte sniff, and the SHA-256 checksum; places the file
  at `destination` with the sniffed suffix by `os.replace`; and always removes `source`.
  Any failure raises `MediaMaterializationError` with no path in its message.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/acquisition/test_materializer_adopt.py`:

```python
"""`MediaMaterializer.adopt`: a local file gets the same validation as a download."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

import httpx
import pytest

from thoth_control_plane.acquisition import materializer as materializer_module
from thoth_control_plane.acquisition.materializer import (
    MediaMaterializationError,
    MediaMaterializer,
    resolve_host_via_getaddrinfo,
)
from thoth_control_plane.acquisition.models import AcquisitionStrategy

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 20_000
LOCATION = PurePosixPath("reports/wf_yt_001/media/youtube-abc-1")


async def _adopt(tmp_path: Path, payload: bytes | None, **kwargs) -> tuple[object, Path]:
    source = tmp_path / "download" / "merged.mp4"
    source.parent.mkdir(parents=True)
    if payload is not None:
        source.write_bytes(payload)
    async with httpx.AsyncClient() as client:
        materializer = MediaMaterializer(client, resolve_host_via_getaddrinfo)
        result = await materializer.adopt(
            source,
            tmp_path / LOCATION,
            LOCATION,
            AcquisitionStrategy.YT_DLP,
            duration_seconds=12.5,
            **kwargs,
        )
    return result, source


@pytest.mark.asyncio
async def test_a_valid_mp4_is_placed_and_described(tmp_path: Path) -> None:
    result, source = await _adopt(tmp_path, MP4)
    assert result.location == LOCATION.with_suffix(".mp4")
    assert (result.media_type, result.bytes, result.kind) == ("video/mp4", len(MP4), "video")
    assert result.checksum == "sha256:" + hashlib.sha256(MP4).hexdigest()
    assert result.acquisition_strategy is AcquisitionStrategy.YT_DLP
    assert result.duration_seconds == 12.5
    assert (tmp_path / LOCATION.with_suffix(".mp4")).read_bytes() == MP4
    assert not source.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [b"<html>not a video</html>" + b"\x00" * 20_000, MP4[:5_000], b"", None],
)
async def test_a_bad_file_is_rejected_and_removed(tmp_path: Path, payload: bytes | None) -> None:
    with pytest.raises(MediaMaterializationError):
        await _adopt(tmp_path, payload)
    assert not (tmp_path / "download" / "merged.mp4").exists()
    assert not (tmp_path / LOCATION.with_suffix(".mp4")).exists()


@pytest.mark.asyncio
async def test_a_file_over_the_bound_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(materializer_module.MEDIA_BYTE_BOUNDS, "video", (10, 1_000))
    with pytest.raises(MediaMaterializationError):
        await _adopt(tmp_path, MP4)
    assert not (tmp_path / "download" / "merged.mp4").exists()


@pytest.mark.asyncio
async def test_an_image_kind_must_be_an_image(tmp_path: Path) -> None:
    with pytest.raises(MediaMaterializationError):
        await _adopt(tmp_path, MP4, kind="image")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_materializer_adopt.py -q`
Expected: FAIL with `AttributeError: 'MediaMaterializer' object has no attribute 'adopt'`.

- [ ] **Step 3: Implement**

In `materializer.py`, add `MediaKind,` to the `models` import (alphabetical, after
`MaterializedMedia,`). Add this module function before `class MediaMaterializer`:

```python
def _adopt(
    source: Path,
    destination: Path,
    relative_location: PurePosixPath,
    strategy: AcquisitionStrategy | str,
    kind: MediaKind,
    media_id: str,
    index: int,
    duration_seconds: float | None,
) -> MaterializedMedia:
    acquisition_strategy = AcquisitionStrategy(strategy)
    low, high = MEDIA_BYTE_BOUNDS[kind]
    digest = hashlib.sha256()
    header = b""
    total_bytes = 0
    try:
        with source.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                total_bytes += len(chunk)
                if total_bytes > high:
                    raise MediaMaterializationError()
                if len(header) < _HEADER_PROBE_BYTES:
                    header += chunk[: _HEADER_PROBE_BYTES - len(header)]
                digest.update(chunk)
        media_type = _sniff(header) if len(header) >= _HEADER_PROBE_BYTES else None
        if media_type not in MEDIA_TYPES[kind] or total_bytes < low:
            raise MediaMaterializationError()
        try:
            suffix = _SUFFIXES[media_type]
            final_destination = destination.with_suffix(suffix)
            result = MaterializedMedia(
                media_id=media_id,
                kind=kind,
                index=index,
                location=relative_location.with_suffix(suffix),
                media_type=media_type,
                bytes=total_bytes,
                checksum=f"sha256:{digest.hexdigest()}",
                acquisition_strategy=acquisition_strategy,
                duration_seconds=duration_seconds,
            )
        except ValueError:
            raise MediaMaterializationError() from None
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, final_destination)
        return result
    except OSError:
        # Filesystem errors can carry an absolute path in their message; never let it escape.
        raise MediaMaterializationError() from None
    finally:
        # A rejected file never lingers; after `os.replace` there is nothing left to remove.
        with contextlib.suppress(OSError):
            source.unlink(missing_ok=True)
```

Add this method at the end of `MediaMaterializer`:

```python
    async def adopt(
        self,
        source: Path,
        destination: Path,
        relative_location: PurePosixPath,
        strategy: AcquisitionStrategy | str,
        *,
        kind: MediaKind = "video",
        media_id: str = "media_1",
        index: int = 1,
        duration_seconds: float | None = None,
    ) -> MaterializedMedia:
        """Validate a file a local downloader wrote (yt-dlp) and place it as `materialize` does.

        The same byte bounds, magic-byte sniff, and checksum apply. `source` must sit on the
        destination's filesystem, and it is always removed: a rejected file never lingers.
        """
        return await asyncio.to_thread(
            _adopt,
            source,
            destination,
            relative_location,
            strategy,
            kind,
            media_id,
            index,
            duration_seconds,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_materializer_adopt.py tests/acquisition/test_materializer.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/materializer.py python/tests/acquisition/test_materializer_adopt.py
git commit -m "feat(acquisition): validate and adopt locally downloaded media"
```

---

### Task 4: yt-dlp client, YouTube cards, acquirer, and registry

**Files:**
- Create: `python/src/thoth_control_plane/acquisition/youtube_service.py`
- Modify: `python/src/thoth_control_plane/acquisition/registry.py`
- Modify: `python/tests/acquisition/fakes.py` (`FakeMaterializer.adopt`)
- Test: `python/tests/acquisition/test_youtube_service.py`, `test_youtube_acquirer.py`,
  `test_youtube_comment_tagging.py`, `test_registry.py`

**Interfaces:**
- Consumes:
  - Task 2: `canonicalize_youtube_url`, `parse_info`, `select_formats`, `video_url`,
    `YouTubeIdentity`, `YouTubeParse`, `YouTubeUrlError`, `FormatChoice`.
  - Task 3: `MediaMaterializer.adopt`.
  - Stage 3c's `card_browser.py`: `CardBrowser`, `CardLayout`, `comment_targets`.
- Produces:
  - `CONTENT_METHOD = "yt_dlp"`, `PROFILE_CARD_SELECTOR = "#page-header"`, `TAG_COMMENTS_JS`,
    `YOUTUBE_LAYOUT`.
  - `YtDlpError(reason: AcquisitionReason)` with `.reason`; `classify(error) -> AcquisitionReason`.
  - `YtDlpClient(factory: Callable[[dict], Any] | None = None)` with
    `async extract(url, *, comments: bool) -> dict`, `async listing(url, limit: int) -> dict`,
    and `async download(url, choice: FormatChoice, directory: Path) -> Path`. The factory
    builds a `yt_dlp.YoutubeDL`-like context manager; the default imports `yt_dlp` lazily.
  - `YouTubeHeadlessBrowser(CardBrowser)`.
  - `YouTubeAcquirer(client, headless, materializer)` with
    `async inspect(*, workflow_id, source_url, artifact_root) -> AcquisitionResult`.
  - `acquirer_for(...)` returns a `YouTubeAcquirer` for YouTube URLs.
  - `FakeMaterializer(fail_at=None, fail_adopt=False)` with `.adopted` and `adopt(...)`.

The error table is spec section 4. A bot check, a stale extractor, or an unknown error is
`request_blocked`; a private, removed, unavailable, live, or upcoming video is
`request_incomplete`; a timeout is `request_timeout`. No fitting format pair, a failed
download or merge, or a failed `adopt` is `media_validation_failed`. Cards come from
`/watch?v=<id>` (a Short's own page never renders comments) and the channel page; there is
no post card.

- [ ] **Step 1: Write the failing tests**

In `python/tests/acquisition/fakes.py`, add `from pathlib import Path`, then replace
`FakeMaterializer.__init__` with:

```python
    def __init__(self, fail_at: int | None = None, fail_adopt: bool = False) -> None:
        self.fail_at, self.fail_adopt = fail_at, fail_adopt
        self.adopted: list[Path] = []

    async def adopt(
        self, source, destination, relative_location, strategy, *, kind="video", **kwargs
    ):
        self.adopted.append(source)
        if self.fail_adopt or not source.is_file():
            source.unlink(missing_ok=True)
            raise MediaMaterializationError()
        destination.with_suffix(".mp4").parent.mkdir(parents=True, exist_ok=True)
        source.replace(destination.with_suffix(".mp4"))
        return MaterializedMedia(
            media_id=kwargs.get("media_id", "media_1"),
            kind=kind,
            index=kwargs.get("index", 1),
            location=relative_location.with_suffix(".mp4"),
            media_type="video/mp4",
            bytes=20_000,
            checksum="sha256:" + "0" * 64,
            acquisition_strategy=strategy,
            duration_seconds=kwargs.get("duration_seconds"),
        )
```

Create `python/tests/acquisition/test_youtube_service.py`:

```python
"""The yt-dlp client and the YouTube card browser over injected fakes; no network."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import pytest

from tests.acquisition.fakes import FakeCardPage, card_session
from thoth_control_plane.acquisition import youtube_service
from thoth_control_plane.acquisition.adapters.youtube import FormatChoice
from thoth_control_plane.acquisition.browser import active_scrapling_session_count
from thoth_control_plane.acquisition.card_browser import COMMENT_ROW_ATTRIBUTE, CommentTarget
from thoth_control_plane.acquisition.materializer import MediaMaterializationError
from thoth_control_plane.acquisition.models import AcquisitionReason
from thoth_control_plane.acquisition.youtube_service import (
    PROFILE_CARD_SELECTOR,
    TAG_COMMENTS_JS,
    YouTubeHeadlessBrowser,
    YtDlpClient,
    YtDlpError,
    classify,
)

URL = "https://www.youtube.com/watch?v=abcDEF123_-"
CHANNEL = "https://www.youtube.com/channel/UCuser001abcdefghijklmno"
CHOICE = FormatChoice(video_format="137", audio_format="140", short_side=1080, estimated_bytes=1)


class FakeYdl:
    """Records the options it was built with; returns or raises what it was given."""

    def __init__(self, options: dict[str, Any], result: Any, on_download=None) -> None:
        self.options, self.result, self.on_download = options, result, on_download

    def __enter__(self) -> FakeYdl:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def extract_info(self, url: str, download: bool) -> Any:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def download(self, urls: list[str]) -> int:
        if isinstance(self.result, Exception):
            raise self.result
        if self.on_download is not None:
            self.on_download(self.options)
        return 0


def _client(result: Any, seen: list[dict[str, Any]], on_download=None) -> YtDlpClient:
    def factory(options: dict[str, Any]) -> FakeYdl:
        seen.append(options)
        return FakeYdl(options, result, on_download)

    return YtDlpClient(factory)


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("ERROR: Sign in to confirm you're not a bot", AcquisitionReason.REQUEST_BLOCKED),
        ("ERROR: Sign in to confirm your age", AcquisitionReason.REQUEST_BLOCKED),
        (
            "ERROR: Private video. Sign in if you've been granted access",
            AcquisitionReason.REQUEST_INCOMPLETE,
        ),
        ("ERROR: Video unavailable", AcquisitionReason.REQUEST_INCOMPLETE),
        (
            "ERROR: This video has been removed by the uploader",
            AcquisitionReason.REQUEST_INCOMPLETE,
        ),
        ("ERROR: Read timed out", AcquisitionReason.REQUEST_TIMEOUT),
        ("ERROR: Requested format is not available", AcquisitionReason.REQUEST_BLOCKED),
        ("something new", AcquisitionReason.REQUEST_BLOCKED),
    ],
)
def test_classify_maps_message_classes(message: str, reason: AcquisitionReason) -> None:
    assert classify(RuntimeError(message)) is reason


def test_a_stale_extractor_warns_without_the_message(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    classify(RuntimeError("nsig extraction failed for https://www.youtube.com/watch?v=x"))
    assert "yt-dlp needs an update" in caplog.text
    assert "youtube.com" not in caplog.text


def test_a_timeout_error_is_a_timeout() -> None:
    assert classify(TimeoutError()) is AcquisitionReason.REQUEST_TIMEOUT


@pytest.mark.asyncio
async def test_extract_asks_for_first_page_comments_with_bun() -> None:
    seen: list[dict[str, Any]] = []
    info = await _client({"id": "x"}, seen).extract(URL, comments=True)
    assert info == {"id": "x"}
    options = seen[0]
    assert options["getcomments"] is True
    assert options["extractor_args"] == {"youtube": {"max_comments": ["50", "50", "0", "0"]}}
    assert options["js_runtimes"] == {"bun": {}}
    assert options["skip_download"] is True
    assert options["quiet"] is True


@pytest.mark.asyncio
async def test_extract_without_comments_skips_them() -> None:
    seen: list[dict[str, Any]] = []
    await _client({"id": "x"}, seen).extract(URL, comments=False)
    assert "getcomments" not in seen[0]


@pytest.mark.asyncio
async def test_extract_failures_become_reasons() -> None:
    with pytest.raises(YtDlpError) as caught:
        await _client(RuntimeError("Video unavailable"), []).extract(URL, comments=True)
    assert caught.value.reason is AcquisitionReason.REQUEST_INCOMPLETE
    with pytest.raises(YtDlpError) as caught:
        await _client(["not", "a", "dict"], []).extract(URL, comments=True)
    assert caught.value.reason is AcquisitionReason.REQUEST_INCOMPLETE


@pytest.mark.asyncio
async def test_extract_has_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(youtube_service, "EXTRACT_TIMEOUT_SECONDS", 0.05)

    class Slow(FakeYdl):
        def extract_info(self, url: str, download: bool) -> Any:
            time.sleep(0.5)
            return {}

    client = YtDlpClient(lambda options: Slow(options, None))
    with pytest.raises(YtDlpError) as caught:
        await client.extract(URL, comments=False)
    assert caught.value.reason is AcquisitionReason.REQUEST_TIMEOUT


@pytest.mark.asyncio
async def test_download_merges_the_chosen_pair_into_mp4(tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []

    def write(options: dict[str, Any]) -> None:
        (tmp_path / "merged.mp4").write_bytes(b"x")

    merged = await _client(None, seen, write).download(URL, CHOICE, tmp_path)
    assert merged == tmp_path / "merged.mp4"
    options = seen[0]
    assert options["format"] == "137+140"
    assert options["merge_output_format"] == "mp4"
    assert options["outtmpl"] == {"default": str(tmp_path / "merged.%(ext)s")}


@pytest.mark.asyncio
async def test_a_failed_or_empty_download_is_a_media_failure(tmp_path: Path) -> None:
    with pytest.raises(MediaMaterializationError):
        await _client(RuntimeError("HTTP Error 403"), []).download(URL, CHOICE, tmp_path)
    with pytest.raises(MediaMaterializationError):
        await _client(None, []).download(URL, CHOICE, tmp_path)


C1 = "UgzComment001"
TARGETS = [CommentTarget(C1, "fan_001", "first comment")]


@pytest.mark.asyncio
async def test_cards_crop_comments_and_the_channel_header_never_a_post() -> None:
    post_page, channel_page = FakeCardPage(URL, tagged=[C1]), FakeCardPage(CHANNEL)
    session = card_session({URL: post_page, CHANNEL: channel_page})
    browser = YouTubeHeadlessBrowser(lambda **kwargs: session)

    cards = await browser.cards(URL, CHANNEL, want_post=False, targets=TARGETS)
    await browser.close()

    assert cards.post_png is None
    assert list(cards.comment_pngs) == [C1]
    assert cards.profile_png is not None
    assert post_page.shots == [f'[{COMMENT_ROW_ATTRIBUTE}="{C1}"]']
    assert post_page.evaluated == [
        (TAG_COMMENTS_JS, [{"comment_id": C1, "author": "fan_001", "prefix": "first comment"}])
    ]
    assert channel_page.shots == [PROFILE_CARD_SELECTOR] == ["#page-header"]
    assert post_page.clicked == channel_page.clicked == []
    assert session.exited == 1
    assert active_scrapling_session_count() == 0
```

Create `python/tests/acquisition/test_youtube_acquirer.py`:

```python
"""YouTube acquisition over injected fakes: no network, no yt-dlp, no Scrapling."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import pytest

from tests.acquisition.fakes import FakeMaterializer
from tests.acquisition.png_fixtures import make_png
from thoth_control_plane.acquisition.card_browser import Cards
from thoth_control_plane.acquisition.materializer import MediaMaterializationError
from thoth_control_plane.acquisition.models import AcquisitionReason, AcquisitionStrategy
from thoth_control_plane.acquisition.youtube_service import YouTubeAcquirer, YtDlpError

VIDEO_ID = "abcDEF123_-"
URL = f"https://youtu.be/{VIDEO_ID}?si=share"
CANONICAL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
CHANNEL = "https://www.youtube.com/channel/UCuser001abcdefghijklmno"
WF = "wf_youtube_001"
C1, C2 = "UgzComment001", "UgzComment002"
MB = 1024 * 1024


def _info(**extra: Any) -> dict[str, Any]:
    return {
        "id": VIDEO_ID,
        "title": "secret title",
        "description": "secret description",
        "uploader_id": "@user_001",
        "channel_id": "UCuser001abcdefghijklmno",
        "timestamp": 1_714_566_896,
        "view_count": 4_500,
        "like_count": 120,
        "comment_count": 34,
        "duration": 600,
        "live_status": "not_live",
        "comments": [
            {"id": C1, "parent": "root", "author": "@fan_001", "text": "first", "like_count": 3},
            {"id": C2, "parent": "root", "author": "@fan_002", "text": "second", "like_count": 1},
        ],
        "formats": [
            {
                "format_id": "137",
                "protocol": "https",
                "url": "https://media.example.test/137",
                "ext": "mp4",
                "vcodec": "avc1",
                "acodec": "none",
                "width": 1920,
                "height": 1080,
                "filesize": 100 * MB,
            },
            {
                "format_id": "140",
                "protocol": "https",
                "url": "https://media.example.test/140",
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "mp4a",
                "filesize": 10 * MB,
            },
        ],
        **extra,
    }


class FakeClient:
    def __init__(
        self,
        info: Any = None,
        error: AcquisitionReason | None = None,
        download_error: bool = False,
    ) -> None:
        self.info = _info() if info is None else info
        self.error, self.download_error = error, download_error
        self.calls: list[tuple[str, Any]] = []

    async def extract(self, url: str, *, comments: bool) -> dict[str, Any]:
        self.calls.append(("extract", (url, comments)))
        if self.error is not None:
            raise YtDlpError(self.error)
        return self.info

    async def download(self, url: str, choice, directory: Path) -> Path:
        self.calls.append(("download", (url, choice.video_format, choice.audio_format)))
        (directory / "merged.f137.mp4").write_bytes(b"part")
        if self.download_error:
            raise MediaMaterializationError()
        merged = directory / "merged.mp4"
        merged.write_bytes(b"x")
        return merged


class FakeHeadless:
    def __init__(self, cards: Cards | None = None) -> None:
        self.result = cards or Cards()
        self.card_calls: list[dict[str, Any]] = []
        self.closed = 0

    async def cards(self, post_url: str, profile_url: str, *, want_post: bool, targets: list):
        self.card_calls.append(
            {"post": post_url, "profile": profile_url, "want_post": want_post, "targets": targets}
        )
        return self.result

    async def close(self) -> None:
        self.closed += 1


def _cards() -> Cards:
    return Cards(comment_pngs={C1: make_png(400, 80)}, profile_png=make_png(400, 200))


async def _inspect(tmp_path: Path, client, headless, materializer=None, url: str = URL):
    acquirer = YouTubeAcquirer(client, headless, materializer or FakeMaterializer())
    return await acquirer.inspect(workflow_id=WF, source_url=url, artifact_root=tmp_path)


def _work_dirs(tmp_path: Path) -> list[Path]:
    media = tmp_path / "reports" / WF / "media"
    return [p for p in media.iterdir() if p.name.endswith(".download")] if media.exists() else []


@pytest.mark.asyncio
async def test_a_video_report_carries_the_merged_mp4_comments_and_cards(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    client, headless = FakeClient(), FakeHeadless(_cards())
    result = await _inspect(tmp_path, client, headless)

    report = result.report
    assert report is not None
    assert (report.source.platform, str(report.source.canonical_url)) == ("youtube", CANONICAL)
    assert report.post.owner_handle == "user_001"
    assert report.post.engagement == {"play": 4_500, "like": 120, "comment": 34}
    assert [(m.kind, m.media_type) for m in report.media] == [("video", "video/mp4")]
    assert str(report.media[0].location).endswith(f"media/youtube-{VIDEO_ID}-1.mp4")
    assert report.media[0].acquisition_strategy is AcquisitionStrategy.YT_DLP
    assert report.media[0].duration_seconds == 600.0
    assert [c.comment_id for c in report.comments] == [C1, C2]
    assert str(report.comments[0].card.location).endswith(f"cards/comment-{C1}.png")
    assert report.comments[1].card is None
    assert report.post_card is None
    assert report.profile_card is not None
    assert report.outcome.attempts[0].strategy is AcquisitionStrategy.YT_DLP
    assert client.calls == [
        ("extract", (CANONICAL, True)),
        ("download", (CANONICAL, "137", "140")),
    ]
    call = headless.card_calls[0]
    assert (call["post"], call["profile"], call["want_post"]) == (CANONICAL, CHANNEL, False)
    assert [t.comment_id for t in call["targets"]] == [C1, C2]
    assert _work_dirs(tmp_path) == []
    assert headless.closed == 1
    for secret in ("youtube.com", "youtu.be", "secret title", "user_001", "fan_001"):
        assert secret not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    [
        AcquisitionReason.REQUEST_BLOCKED,
        AcquisitionReason.REQUEST_TIMEOUT,
        AcquisitionReason.REQUEST_INCOMPLETE,
    ],
)
async def test_extract_failures_are_retryable_and_skip_the_rest(
    tmp_path: Path, reason: AcquisitionReason
) -> None:
    client, headless = FakeClient(error=reason), FakeHeadless()
    result = await _inspect(tmp_path, client, headless)
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == (reason.value, True)
    assert len(result.failure.attempts) == 1
    assert [name for name, _ in client.calls] == ["extract"]
    assert headless.card_calls == []
    assert headless.closed == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "info",
    [
        _info(id="otherVideo1"),
        _info(live_status="is_live"),
        _info(live_status="is_upcoming"),
        _info(uploader_id="bad handle", channel_id=None),
    ],
)
async def test_another_video_a_live_stream_or_no_owner_is_request_incomplete(
    tmp_path: Path, info: dict[str, Any]
) -> None:
    client = FakeClient(info=info)
    result = await _inspect(tmp_path, client, FakeHeadless())
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("request_incomplete", True)
    assert [name for name, _ in client.calls] == ["extract"]


@pytest.mark.asyncio
async def test_no_fitting_format_is_a_media_failure_without_a_download(tmp_path: Path) -> None:
    client, headless = FakeClient(info=_info(formats=[])), FakeHeadless()
    result = await _inspect(tmp_path, client, headless)
    assert result.failure is not None
    assert result.failure.code == "media_validation_failed"
    assert [name for name, _ in client.calls] == ["extract"]
    assert headless.card_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("client", "materializer"),
    [
        (FakeClient(download_error=True), FakeMaterializer()),
        (FakeClient(), FakeMaterializer(fail_adopt=True)),
    ],
)
async def test_a_failed_download_or_adopt_leaves_nothing_behind(
    tmp_path: Path, client: FakeClient, materializer: FakeMaterializer
) -> None:
    headless = FakeHeadless()
    result = await _inspect(tmp_path, client, headless, materializer)
    assert result.failure is not None
    assert result.failure.code == "media_validation_failed"
    assert _work_dirs(tmp_path) == []
    media = tmp_path / "reports" / WF / "media"
    assert not media.exists() or list(media.iterdir()) == []
    assert headless.card_calls == []


@pytest.mark.asyncio
async def test_an_invalid_url_fails_before_any_extraction(tmp_path: Path) -> None:
    client = FakeClient()
    result = await _inspect(
        tmp_path, client, FakeHeadless(), url="https://www.youtube.com/@someone"
    )
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("invalid_source_url", False)
    assert client.calls == []


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
    task = asyncio.create_task(_inspect(tmp_path, FakeClient(), headless))
    await headless.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert headless.closed == 1
```

Create `python/tests/acquisition/test_youtube_comment_tagging.py` (it skips without
Playwright; Step 4 runs it in the capture image):

```python
"""TAG_COMMENTS_JS against a synthetic YouTube comment list in a real browser; no network.

Skipped unless Playwright and a Chromium build are installed (the acquisition extra).
"""

from __future__ import annotations

from typing import Any

import pytest

from thoth_control_plane.acquisition.card_browser import COMMENT_ROW_ATTRIBUTE
from thoth_control_plane.acquisition.youtube_service import TAG_COMMENTS_JS

async_api = pytest.importorskip("playwright.async_api")


def _thread(cid: str, author: str, text: str, reply: str = "") -> str:
    return (
        f'<ytd-comment-thread-renderer id="t{cid}"><ytd-comment-view-model id="c{cid}">'
        f'<a href="/{author}">{author}</a>'
        f'<a href="/watch?v=abcDEF123_-&lc={cid}">1 day ago</a><span>{text}</span>'
        f"</ytd-comment-view-model>{reply}</ytd-comment-thread-renderer>"
    )


async def _tag(html: str, targets: list[dict[str, str]]) -> tuple[Any, Any]:
    async with async_api.async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch()
        except Exception:
            pytest.skip("no Chromium build installed")
        try:
            page = await browser.new_page()
            await page.set_content(f"<div id='comments'>{html}</div>")
            tagged = await page.evaluate(TAG_COMMENTS_JS, targets)
            owners = await page.eval_on_selector_all(
                f"[{COMMENT_ROW_ATTRIBUTE}]", "els => els.map(e => e.id)"
            )
        finally:
            await browser.close()
    return tagged, owners


@pytest.mark.asyncio
async def test_each_comment_is_found_by_its_own_lc_link() -> None:
    html = _thread("UgzA", "@ann", "Yes") + _thread("UgzAB", "@ann", "Yesterday")
    targets = [
        {"comment_id": "UgzAB", "author": "ann", "prefix": "Yesterday"},
        {"comment_id": "UgzA", "author": "ann", "prefix": "Yes"},
    ]
    assert await _tag(html, targets) == (["UgzAB", "UgzA"], ["cUgzA", "cUgzAB"])


@pytest.mark.asyncio
async def test_the_comment_is_tagged_not_its_thread_of_replies() -> None:
    reply = '<div class="replies"><a href="/watch?v=abcDEF123_-&lc=UgzA.reply1">r</a></div>'
    tagged, owners = await _tag(
        _thread("UgzA", "@ann", "hello", reply),
        [{"comment_id": "UgzA", "author": "ann", "prefix": "hello"}],
    )
    assert (tagged, owners) == (["UgzA"], ["cUgzA"])


@pytest.mark.asyncio
async def test_without_a_link_the_author_and_text_decide() -> None:
    html = (
        '<ytd-comment-thread-renderer><ytd-comment-view-model id="c1">'
        "<div>@anna</div><div>same words</div></ytd-comment-view-model>"
        "</ytd-comment-thread-renderer>"
        '<ytd-comment-thread-renderer><ytd-comment-view-model id="c2">'
        "<div>@ann</div><div>same words</div></ytd-comment-view-model>"
        "</ytd-comment-thread-renderer>"
    )
    target = {"comment_id": "UgzZZ", "author": "ann", "prefix": "same words"}
    # The author and the text are separate blocks, as on YouTube; "@ann" must not match the
    # "@anna" thread above it.
    assert await _tag(html, [target]) == (["UgzZZ"], ["c2"])
```

In `python/tests/acquisition/test_registry.py`, import
`from thoth_control_plane.acquisition.youtube_service import YouTubeAcquirer` and add at the
end of `test_acquirer_for_routes_tiktok_and_refuses_legacy_hosts`:

```python
        youtube = acquirer_for(
            "https://youtu.be/abcDEF123_-", client=client, materializer=materializer
        )
        assert isinstance(youtube, YouTubeAcquirer)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_youtube_service.py tests/acquisition/test_youtube_acquirer.py tests/acquisition/test_registry.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'thoth_control_plane.acquisition.youtube_service'`.

- [ ] **Step 3: Implement**

Create `python/src/thoth_control_plane/acquisition/youtube_service.py`:

```python
"""YouTube single-video acquisition: yt-dlp (a library) for metadata, first-page comments,
and the merged MP4, then best-effort headless cards (comments on the watch page, the channel
header).

YouTube serves only DASH streams with signed, scrambled URLs, so a plain page request yields
no playable media; yt-dlp's JavaScript challenge solver (on `bun`) does. There is no post
card: every YouTube post is a video.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from thoth_control_plane.acquisition.adapters.youtube import (
    FormatChoice,
    YouTubeIdentity,
    YouTubeParse,
    YouTubeUrlError,
    canonicalize_youtube_url,
    parse_info,
    select_formats,
)
from thoth_control_plane.acquisition.browser import _default_session_factory
from thoth_control_plane.acquisition.card_browser import (
    CardBrowser,
    CardLayout,
    comment_targets,
    log_outcome,
    persist_cards,
)
from thoth_control_plane.acquisition.materializer import (
    MediaMaterializationError,
    MediaMaterializer,
)
from thoth_control_plane.acquisition.models import (
    AcquisitionFailure,
    AcquisitionOutcome,
    AcquisitionReason,
    AcquisitionResult,
    AcquisitionStrategy,
    MaterializedMedia,
    ReportSource,
    SourceReport,
)
from thoth_control_plane.acquisition.service import (
    RETRYABLE_FAILURES,
    _elapsed_ms,
    _make_attempt,
)

logger = logging.getLogger(__name__)

CONTENT_METHOD = "yt_dlp"
EXTRACT_TIMEOUT_SECONDS = 90.0
DOWNLOAD_TIMEOUT_SECONDS = 600.0
COMMENT_PAGE = "50"
YTDLP_OPTIONS: dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "noprogress": True,
    "socket_timeout": 30,
    "retries": 2,
    # yt-dlp solves YouTube's JavaScript challenges with an external runtime.
    "js_runtimes": {"bun": {}},
}
BOT_CHECK = ("sign in to confirm",)
GONE = (
    "private video",
    "video unavailable",
    "has been removed",
    "is not available",
    "members-only",
    "account associated with this video has been terminated",
)
STALE = (
    "signature",
    "nsig",
    "n challenge",
    "requested format is not available",
    "unable to extract",
)
PROFILE_CARD_SELECTOR = "#page-header"
LOGIN_PATHS = ("/signin",)
# Tags each matched comment; targets arrive as the evaluate argument, never interpolated.
# Comments load as the page scrolls. A thread linking to the comment's own `lc=` id is exact;
# the author's `@handle` plus the text prefix is the fallback. The comment itself is tagged,
# not its whole thread of replies.
TAG_COMMENTS_JS = """
async (targets) => {
  const threads = () => Array.from(document.querySelectorAll("ytd-comment-thread-renderer"));
  for (let step = 0; step < 8 && threads().length < targets.length; step++) {
    window.scrollBy(0, 1500);
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }
  const head = (thread) => thread.querySelector("ytd-comment-view-model, #comment") || thread;
  const free = (thread) => !head(thread).hasAttribute("data-thoth-comment");
  // `@ann` must not match inside `@anna` (handles also allow `.` and `-`).
  const mentions = (text, handle) => {
    for (let at = text.indexOf(handle); at !== -1; at = text.indexOf(handle, at + 1)) {
      if (!/[a-z0-9_.-]/.test(text.charAt(at + handle.length))) return true;
    }
    return false;
  };
  const tagged = [];
  for (const target of targets) {
    const id = target.comment_id;
    const linked = threads().find((thread) => free(thread)
      && thread.querySelector('a[href$="lc=' + id + '"], a[href*="lc=' + id + '&"]'));
    const handle = "@" + target.author.toLowerCase();
    const row = linked || threads().find((thread) => {
      const text = head(thread).innerText || "";
      return free(thread) && mentions(text.toLowerCase(), handle) && text.includes(target.prefix);
    });
    if (!row) continue;
    head(row).setAttribute("data-thoth-comment", id);
    tagged.push(id);
  }
  return tagged;
}
"""
YOUTUBE_LAYOUT = CardLayout(
    # Unused: a YouTube post is always a video, so no post card is asked for.
    post_selector="ytd-watch-metadata",
    profile_selector=PROFILE_CARD_SELECTOR,
    tag_js=TAG_COMMENTS_JS,
    login_paths=LOGIN_PATHS,
)


class YtDlpError(Exception):
    """An extraction failure, already mapped to its acquisition reason."""

    def __init__(self, reason: AcquisitionReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


def classify(error: BaseException) -> AcquisitionReason:
    """Map a yt-dlp failure to a reason by message class; the message never leaves here."""
    text = str(error).lower()
    if isinstance(error, TimeoutError) or "timed out" in text:
        return AcquisitionReason.REQUEST_TIMEOUT
    if any(phrase in text for phrase in BOT_CHECK):
        return AcquisitionReason.REQUEST_BLOCKED
    if any(phrase in text for phrase in STALE):
        logger.warning("youtube extraction failed in a way that suggests yt-dlp needs an update")
        return AcquisitionReason.REQUEST_BLOCKED
    if any(phrase in text for phrase in GONE):
        return AcquisitionReason.REQUEST_INCOMPLETE
    return AcquisitionReason.REQUEST_BLOCKED


class _Silent:
    """yt-dlp's logger: its messages can carry URLs, so none are kept."""

    def debug(self, message: str) -> None: ...

    def info(self, message: str) -> None: ...

    def warning(self, message: str) -> None: ...

    def error(self, message: str) -> None: ...


def _default_factory(options: dict[str, Any]) -> Any:
    import yt_dlp

    return yt_dlp.YoutubeDL(options)


class YtDlpClient:
    """yt-dlp as a library, run in a worker thread under a timeout."""

    def __init__(self, factory: Callable[[dict[str, Any]], Any] | None = None) -> None:
        self._factory = factory or _default_factory

    async def _run(
        self, options: dict[str, Any], call: Callable[[Any], Any], timeout: float
    ) -> Any:
        def work() -> Any:
            with self._factory({**YTDLP_OPTIONS, "logger": _Silent(), **options}) as ydl:
                return call(ydl)

        # ponytail: a timed-out thread finishes in the background (socket_timeout bounds it);
        # yt-dlp offers no cancellation.
        return await asyncio.wait_for(asyncio.to_thread(work), timeout)

    async def extract(self, url: str, *, comments: bool) -> dict[str, Any]:
        options: dict[str, Any] = {"skip_download": True}
        if comments:
            options["getcomments"] = True
            options["extractor_args"] = {
                "youtube": {"max_comments": [COMMENT_PAGE, COMMENT_PAGE, "0", "0"]}
            }
        return await self._info(url, options)

    async def listing(self, url: str, limit: int) -> dict[str, Any]:
        """A channel tab's newest entries, flat: ids and views, no per-video extraction."""
        options = {"skip_download": True, "extract_flat": "in_playlist", "playlistend": limit}
        return await self._info(url, options)

    async def _info(self, url: str, options: dict[str, Any]) -> dict[str, Any]:
        try:
            info = await self._run(
                options, lambda ydl: ydl.extract_info(url, download=False), EXTRACT_TIMEOUT_SECONDS
            )
        except Exception as error:
            raise YtDlpError(classify(error)) from None
        if not isinstance(info, dict):
            raise YtDlpError(AcquisitionReason.REQUEST_INCOMPLETE)
        return info

    async def download(self, url: str, choice: FormatChoice, directory: Path) -> Path:
        """Download the chosen video and audio and merge them into `directory/merged.mp4`."""
        options = {
            "format": f"{choice.video_format}+{choice.audio_format}",
            "merge_output_format": "mp4",
            "outtmpl": {"default": str(directory / "merged.%(ext)s")},
            "overwrites": True,
        }
        try:
            await self._run(options, lambda ydl: ydl.download([url]), DOWNLOAD_TIMEOUT_SECONDS)
        except Exception:
            raise MediaMaterializationError() from None
        merged = directory / "merged.mp4"
        if not merged.is_file():
            raise MediaMaterializationError()
        return merged


class YouTubeHeadlessBrowser(CardBrowser):
    """The YouTube card session: comment cards on the watch page, the channel header."""

    def __init__(self, session_factory: Callable[..., Any] = _default_session_factory) -> None:
        super().__init__(YOUTUBE_LAYOUT, session_factory)


class YouTubeAcquirer:
    """One YouTube video: yt-dlp metadata and comments, the merged MP4, and cards."""

    def __init__(
        self,
        client: YtDlpClient,
        headless: YouTubeHeadlessBrowser,
        materializer: MediaMaterializer,
    ) -> None:
        self._client = client
        self._headless = headless
        self._materializer = materializer

    async def _media(
        self,
        identity: YouTubeIdentity,
        choice: FormatChoice,
        parsed: YouTubeParse,
        workflow_id: str,
        artifact_root: Path,
    ) -> MaterializedMedia:
        name = f"youtube-{identity.video_id}-1"
        location = PurePosixPath("reports") / workflow_id / "media" / name
        # On the artifact filesystem, so `adopt` places the file with an atomic rename.
        work = artifact_root / location.parent / f".youtube-{identity.video_id}.download"
        try:
            work.mkdir(parents=True, exist_ok=True)
            merged = await self._client.download(str(identity.canonical_url), choice, work)
            return await self._materializer.adopt(
                merged,
                artifact_root / location,
                location,
                AcquisitionStrategy.YT_DLP,
                duration_seconds=parsed.duration_seconds,
            )
        except OSError:
            raise MediaMaterializationError() from None
        finally:
            shutil.rmtree(work, ignore_errors=True)

    async def inspect(
        self, *, workflow_id: str, source_url: str, artifact_root: Path
    ) -> AcquisitionResult:
        strategy = AcquisitionStrategy.YT_DLP
        try:
            try:
                identity = canonicalize_youtube_url(source_url)
            except YouTubeUrlError:
                return AcquisitionResult(
                    failure=AcquisitionFailure(code="invalid_source_url", retryable=False)
                )
            start = time.monotonic()
            reason: AcquisitionReason | None = None
            info: dict[str, Any] | None = None
            try:
                info = await self._client.extract(str(identity.canonical_url), comments=True)
            except YtDlpError as error:
                reason = error.reason
            parsed = parse_info(info, identity) if info is not None else None
            if parsed is None and reason is None:
                # Another video, a live or upcoming stream, or no valid owner.
                reason = AcquisitionReason.REQUEST_INCOMPLETE
            media: list[MaterializedMedia] = []
            if parsed is not None and info is not None:
                choice = select_formats(info.get("formats"), parsed.duration_seconds)
                if choice is None:
                    reason = AcquisitionReason.MEDIA_VALIDATION_FAILED
                else:
                    try:
                        media = [
                            await self._media(identity, choice, parsed, workflow_id, artifact_root)
                        ]
                    except MediaMaterializationError:
                        reason = AcquisitionReason.MEDIA_VALIDATION_FAILED
            attempt = _make_attempt(strategy, reason, _elapsed_ms(start))
            if reason is not None or parsed is None:
                code = (reason or AcquisitionReason.REQUEST_INCOMPLETE).value
                return AcquisitionResult(
                    failure=AcquisitionFailure(
                        code=code, retryable=code in RETRYABLE_FAILURES, attempts=[attempt]
                    )
                )
            cards = await self._headless.cards(
                str(identity.canonical_url),
                parsed.channel_url,
                want_post=False,
                targets=comment_targets(parsed.comments),
            )
            _, comments, profile_card = await asyncio.to_thread(
                persist_cards, cards, parsed.comments, workflow_id, artifact_root
            )
            log_outcome(
                "youtube",
                CONTENT_METHOD,
                len(media),
                comments,
                None,
                profile_card,
                want_post=False,
                problems=cards.problems,
                dropped=parsed.dropped_comments,
            )
            return AcquisitionResult(
                report=SourceReport(
                    workflow_id=workflow_id,
                    source=ReportSource(platform="youtube", canonical_url=identity.canonical_url),
                    post=parsed.post,
                    media=media,
                    outcome=AcquisitionOutcome(attempts=[attempt]),
                    comments=comments,
                    profile_card=profile_card,
                )
            )
        finally:
            # Same shielded close as the other acquirers: a second cancellation must not
            # interrupt browser cleanup partway through.
            await asyncio.shield(self._headless.close())
```

In `registry.py`, add the import after the `x_service` import:

```python
from thoth_control_plane.acquisition.youtube_service import (
    YouTubeAcquirer,
    YouTubeHeadlessBrowser,
    YtDlpClient,
)
```

and the branch before `raise LookupError(...)`:

```python
    if platform == "youtube":
        return YouTubeAcquirer(YtDlpClient(), YouTubeHeadlessBrowser(), materializer)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition -q`
Expected: PASS (the tagging tests skip locally).

Then run the browser tests in the capture image with the Global Constraints command and
`<paths>` = `tests/acquisition/test_youtube_comment_tagging.py tests/acquisition/test_x_comment_tagging.py tests/acquisition/test_instagram_comment_tagging.py`.
Expected: `11 passed`.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/youtube_service.py python/src/thoth_control_plane/acquisition/registry.py python/tests/acquisition/fakes.py python/tests/acquisition/test_youtube_service.py python/tests/acquisition/test_youtube_acquirer.py python/tests/acquisition/test_youtube_comment_tagging.py python/tests/acquisition/test_registry.py
git commit -m "feat(acquisition): add the youtube acquirer over yt-dlp"
```

---

### Task 5: Channel discovery

**Files:**
- Create: `python/src/thoth_control_plane/acquisition/youtube_discovery.py`
- Test: `python/tests/acquisition/test_youtube_discovery.py`

**Interfaces:**
- Consumes: Task 2's `CANONICAL_BASE`, `YouTubeIdentity`, `channel_candidates`, `parse_info`,
  `video_url`; Task 4's `YtDlpClient`, `YtDlpError`; `rank_videos`
  (`instagram_discovery.py`); `MAX_CAPTION`, `_empty` (`discovery.py`).
- Produces: `GRID_SIZE = 12`, `TABS = ("videos", "shorts")`, `DETAIL_SPACING_SECONDS = 2.0`,
  and `YouTubeChannelDiscovery(client: YtDlpClient | None = None, sleep=asyncio.sleep)` with
  `async discover(request: ProfileDiscovery) -> DiscoveryResult`. It never raises.

A channel without Shorts has no `/shorts` tab; only both tabs failing is a failure. A
timeout maps to `DiscoveryReason.TIMEOUT`, any other `YtDlpError` to `BLOCKED`. A detail
failure returns the videos gathered so far, ranked, with its reason. A library with no
caller until Stage 8.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/acquisition/test_youtube_discovery.py`:

```python
"""YouTube channel discovery over a fake yt-dlp client: no network."""

from __future__ import annotations

from typing import Any

import pytest

from thoth_control_plane.acquisition.models import (
    AcquisitionReason,
    DiscoveryReason,
    ProfileDiscovery,
)
from thoth_control_plane.acquisition.youtube_discovery import (
    DETAIL_SPACING_SECONDS,
    YouTubeChannelDiscovery,
)
from thoth_control_plane.acquisition.youtube_service import YtDlpError


def _vid(n: int) -> str:
    return f"video{n:06d}"


def _listing(*pairs: tuple[int, int]) -> dict[str, Any]:
    return {"entries": [{"id": _vid(n), "view_count": views} for n, views in pairs]}


def _detail(n: int, likes: int, views: int, day: int) -> dict[str, Any]:
    return {
        "id": _vid(n),
        "title": f"title {n}",
        "uploader_id": "@nasa",
        "channel_id": "UCnasa0000000000000000aa",
        "timestamp": 1_700_000_000 + day * 86_400,
        "view_count": views,
        "like_count": likes,
        "duration": 30 + n,
        "live_status": "not_live",
    }


class FakeClient:
    def __init__(
        self,
        listings: dict[str, Any],
        details: dict[str, Any] | None = None,
    ) -> None:
        self.listings, self.details = listings, details or {}
        self.calls: list[str] = []

    async def listing(self, url: str, limit: int) -> dict[str, Any]:
        self.calls.append(url)
        result = self.listings.get(url.rsplit("/", 1)[-1])
        if isinstance(result, AcquisitionReason):
            raise YtDlpError(result)
        return result if result is not None else {"entries": []}

    async def extract(self, url: str, *, comments: bool) -> dict[str, Any]:
        assert comments is False
        self.calls.append(url)
        result = self.details.get(url.rsplit("=", 1)[-1])
        if isinstance(result, AcquisitionReason):
            raise YtDlpError(result)
        return result if result is not None else {}


async def _discover(client: FakeClient, handle: str = "nasa", limit: int = 30, sleeps=None):
    async def sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    discovery = YouTubeChannelDiscovery(client, sleep=sleep)
    return await discovery.discover(ProfileDiscovery(handle=handle, limit=limit))


@pytest.mark.asyncio
async def test_the_most_viewed_are_detailed_and_ranked() -> None:
    client = FakeClient(
        {"videos": _listing((1, 100), (2, 900)), "shorts": _listing((3, 5_000))},
        {
            _vid(1): _detail(1, likes=50, views=100, day=3),
            _vid(2): _detail(2, likes=10, views=900, day=1),
            _vid(3): _detail(3, likes=900, views=5_000, day=2),
        },
    )
    sleeps: list[float] = []
    result = await _discover(client, sleeps=sleeps)
    assert [v.post_id for v in result.videos] == [_vid(3), _vid(1), _vid(2)]
    first = result.videos[0]
    assert str(first.canonical_url) == f"https://www.youtube.com/watch?v={_vid(3)}"
    assert (first.owner_handle, first.caption, first.duration_seconds) == ("nasa", "title 3", 33.0)
    assert first.engagement == {"play": 5_000, "like": 900}
    assert first.published_at == "2023-11-16T22:13:20Z"
    assert client.calls[:2] == [
        "https://www.youtube.com/@nasa/videos",
        "https://www.youtube.com/@nasa/shorts",
    ]
    assert sleeps == [DETAIL_SPACING_SECONDS] * 3
    assert (result.pages, result.exhausted, result.reason) == (1, False, None)


@pytest.mark.asyncio
async def test_a_channel_without_shorts_still_discovers() -> None:
    client = FakeClient(
        {"videos": _listing((1, 100)), "shorts": AcquisitionReason.REQUEST_BLOCKED},
        {_vid(1): _detail(1, likes=5, views=100, day=1)},
    )
    result = await _discover(client)
    assert ([v.post_id for v in result.videos], result.reason) == ([_vid(1)], None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (AcquisitionReason.REQUEST_BLOCKED, DiscoveryReason.BLOCKED),
        (AcquisitionReason.REQUEST_TIMEOUT, DiscoveryReason.TIMEOUT),
    ],
)
async def test_both_tabs_failing_is_the_failure_reason(
    error: AcquisitionReason, reason: DiscoveryReason
) -> None:
    result = await _discover(FakeClient({"videos": error, "shorts": error}))
    assert (result.videos, result.pages, result.reason) == ([], 0, reason)


@pytest.mark.asyncio
async def test_empty_tabs_are_no_data() -> None:
    result = await _discover(FakeClient({}))
    assert (result.videos, result.reason) == ([], DiscoveryReason.NO_DATA)


@pytest.mark.asyncio
async def test_a_detail_failure_returns_what_was_gathered() -> None:
    client = FakeClient(
        {"videos": _listing((1, 900), (2, 500), (3, 100))},
        {
            _vid(1): _detail(1, likes=5, views=900, day=1),
            _vid(2): AcquisitionReason.REQUEST_BLOCKED,
        },
    )
    result = await _discover(client)
    assert [v.post_id for v in result.videos] == [_vid(1)]
    assert result.reason is DiscoveryReason.BLOCKED
    assert f"https://www.youtube.com/watch?v={_vid(3)}" not in client.calls


@pytest.mark.asyncio
async def test_unreadable_details_are_invalid() -> None:
    client = FakeClient(
        {"videos": _listing((1, 900), (2, 500))},
        {_vid(1): {"id": "someoneelse"}, _vid(2): _detail(2, likes=1, views=500, day=1)},
    )
    result = await _discover(client)
    assert [v.post_id for v in result.videos] == [_vid(2)]
    assert result.drops.invalid == 1


@pytest.mark.asyncio
async def test_limit_is_respected() -> None:
    pairs = [(n, n * 100) for n in range(1, 6)]
    details = {_vid(n): _detail(n, likes=n, views=n * 100, day=n) for n in range(1, 6)}
    result = await _discover(FakeClient({"videos": _listing(*pairs)}, details), limit=2)
    assert [v.post_id for v in result.videos] == [_vid(5), _vid(4)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_youtube_discovery.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'thoth_control_plane.acquisition.youtube_discovery'`.

- [ ] **Step 3: Implement**

Create `python/src/thoth_control_plane/acquisition/youtube_discovery.py`:

```python
"""YouTube channel discovery: the most-viewed recent videos and Shorts, ranked by likes,
views, and recency.

yt-dlp lists the channel's `/videos` and `/shorts` tabs flat (ids and views only); the most
viewed candidates then get a detail extract, without comments, for their likes and upload
time. Never raises; every failure is a `DiscoveryResult` with a reason, and a detail failure
returns what was gathered. A library with no caller until Stage 8.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from thoth_control_plane.acquisition.adapters.youtube import (
    CANONICAL_BASE,
    YouTubeIdentity,
    channel_candidates,
    parse_info,
    video_url,
)
from thoth_control_plane.acquisition.discovery import MAX_CAPTION, _empty
from thoth_control_plane.acquisition.instagram_discovery import rank_videos
from thoth_control_plane.acquisition.models import (
    AcquisitionReason,
    DiscoveredVideo,
    DiscoveryDrops,
    DiscoveryReason,
    DiscoveryResult,
    ProfileDiscovery,
)
from thoth_control_plane.acquisition.youtube_service import YtDlpClient, YtDlpError

logger = logging.getLogger(__name__)
GRID_SIZE = 12
TABS = ("videos", "shorts")
DETAIL_SPACING_SECONDS = 2.0


def _reason(error: YtDlpError) -> DiscoveryReason:
    timeout = error.reason is AcquisitionReason.REQUEST_TIMEOUT
    return DiscoveryReason.TIMEOUT if timeout else DiscoveryReason.BLOCKED


def _video(info: dict[str, object], video_id: str) -> DiscoveredVideo | None:
    identity = YouTubeIdentity(canonical_url=video_url(video_id), video_id=video_id)
    parsed = parse_info(info, identity)
    if parsed is None:
        return None
    title = info.get("title")
    try:
        return DiscoveredVideo(
            post_id=video_id,
            owner_handle=parsed.post.owner_handle,
            canonical_url=identity.canonical_url,
            caption=title[:MAX_CAPTION] if isinstance(title, str) else "",
            published_at=parsed.post.published_at,
            duration_seconds=parsed.duration_seconds,
            engagement=parsed.post.engagement,
        )
    except ValueError:
        return None


class YouTubeChannelDiscovery:
    def __init__(
        self,
        client: YtDlpClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client or YtDlpClient()
        self._sleep = sleep

    async def discover(self, request: ProfileDiscovery) -> DiscoveryResult:
        result = await self._collect(request)
        reason = result.reason.value if result.reason is not None else "none"
        logger.info(
            "youtube discovery finished kind=profile videos=%d invalid=%d reason=%s",
            len(result.videos),
            result.drops.invalid,
            reason,
        )
        if result.reason is not None:
            logger.warning("youtube discovery stopped early kind=profile reason=%s", reason)
        return result

    async def _collect(self, request: ProfileDiscovery) -> DiscoveryResult:
        base = f"{CANONICAL_BASE}/@{request.handle}"
        listings: list[object] = []
        reason: DiscoveryReason | None = None
        for tab in TABS:
            try:
                listings.append(await self._client.listing(f"{base}/{tab}", GRID_SIZE))
            except YtDlpError as error:
                # A channel without Shorts has no such tab; only both failing is a failure.
                reason = reason or _reason(error)
        candidates = channel_candidates(listings, GRID_SIZE)
        if not candidates:
            return _empty("profile", reason if not listings else DiscoveryReason.NO_DATA)
        videos: list[DiscoveredVideo] = []
        invalid = 0
        stopped: DiscoveryReason | None = None
        for video_id in candidates:
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
            kind="profile",
            videos=rank_videos(videos)[: request.limit],
            pages=1,
            exhausted=False,
            drops=DiscoveryDrops(invalid=invalid),
            reason=stopped,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition/test_youtube_discovery.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/acquisition/youtube_discovery.py python/tests/acquisition/test_youtube_discovery.py
git commit -m "feat(acquisition): add youtube channel discovery"
```

---

### Task 6: Keep yt-dlp fresh

**Files:**
- Create: `python/src/thoth_control_plane/operations/yt_dlp_version.py`
- Create: `.github/workflows/yt-dlp-update.yml`
- Modify: `python/src/thoth_control_plane/worker.py` (`run_worker`)
- Modify: `.github/workflows/container-image.yml` (CRLF: the `on:` block)
- Modify: `python/pyproject.toml` (CRLF working copy: the `acquisition` extra), `python/uv.lock`
- Test: `python/tests/operations/test_yt_dlp_version.py`, `python/tests/test_worker.py`,
  `python/tests/deployment/test_container_contract.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (the image needs yt-dlp for Task 4 at run time).
- Produces:
  - `parse_version(text: object) -> tuple[int, ...] | None`;
    `is_behind(installed: object, latest: object) -> bool`;
    `latest_from_pypi(payload: object) -> str | None`; `installed_version() -> str | None`;
    `async check_freshness(fetch=None, installed=None) -> bool | None`, which warns with both
    versions when behind and never raises.
  - The worker starts `check_freshness()` as a background task after the Scrapling check and
    cancels it when the worker stops.
  - The daily workflow and the `workflow_dispatch` trigger on the image build.

A pull request opened with the default `GITHUB_TOKEN` starts no other workflow, so the
update job runs the offline suite itself and dispatches the image build explicitly. Its
automatic merge relies on the repository setting "Allow GitHub Actions to create and
approve pull requests", which the operator has enabled; no agent changes repository
settings.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/operations/test_yt_dlp_version.py`:

```python
"""yt-dlp freshness: version comparison and the PyPI check over a fake fetch; no network."""

from __future__ import annotations

import logging

import pytest

from thoth_control_plane.operations.yt_dlp_version import (
    check_freshness,
    is_behind,
    latest_from_pypi,
    parse_version,
)


@pytest.mark.parametrize(
    ("text", "parsed"),
    [
        ("2026.8.19", (2026, 8, 19)),
        ("2026.08.19", (2026, 8, 19)),
        ("2026.08.19.1", (2026, 8, 19, 1)),
        ("2026.8", None),
        ("2026.8.19rc1", None),
        ("v2026.8.19", None),
        (None, None),
    ],
)
def test_parse_version(text: object, parsed: tuple[int, ...] | None) -> None:
    assert parse_version(text) == parsed


@pytest.mark.parametrize(
    ("installed", "latest", "behind"),
    [
        ("2026.8.19", "2026.9.1", True),
        ("2026.08.19", "2026.8.19", False),
        ("2026.8.19", "2026.8.19.1", True),
        ("2026.9.1", "2026.8.19", False),
        ("2026.8.19", "garbage", False),
    ],
)
def test_is_behind(installed: str, latest: str, behind: bool) -> None:
    assert is_behind(installed, latest) is behind


def test_latest_from_pypi_reads_info_version() -> None:
    assert latest_from_pypi({"info": {"version": "2026.9.1"}}) == "2026.9.1"
    assert latest_from_pypi({"info": {"version": "nope"}}) is None
    assert latest_from_pypi([]) is None


def _fetch(payload: object):
    async def fetch(url: str) -> object:
        assert url == "https://pypi.org/pypi/yt-dlp/json"
        if isinstance(payload, Exception):
            raise payload
        return payload

    return fetch


@pytest.mark.asyncio
async def test_a_stale_install_warns_with_both_versions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    fetch = _fetch({"info": {"version": "2026.9.1"}})
    assert await check_freshness(fetch, installed="2026.8.19") is True
    assert "installed=2026.8.19 latest=2026.9.1" in caplog.text


@pytest.mark.asyncio
async def test_a_current_install_is_quiet(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    assert await check_freshness(_fetch({"info": {"version": "2026.8.19"}}), "2026.8.19") is False
    assert "behind" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [RuntimeError("offline"), {"info": {}}])
async def test_an_unknown_answer_never_raises(payload: object) -> None:
    assert await check_freshness(_fetch(payload), installed="2026.8.19") is None
```

In `python/tests/test_worker.py`, add `import asyncio` above `import pytest`, and at the end:

```python


@pytest.mark.asyncio
async def test_the_yt_dlp_check_runs_in_the_background_and_stops_with_the_worker(
    monkeypatch,
) -> None:
    started = asyncio.Event()
    cancelled: list[bool] = []

    async def capability():
        return None

    async def freshness():
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    async def connect(*args, **kwargs):
        await started.wait()
        raise _StopWorker

    monkeypatch.setattr(worker, "configure_provider_logging", lambda: None)
    monkeypatch.setattr(worker, "check_scrapling_capability", capability)
    monkeypatch.setattr(worker, "check_freshness", freshness)
    monkeypatch.setattr(worker.Client, "connect", connect)
    with pytest.raises(_StopWorker):
        await worker.run_worker(Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"))
    await asyncio.sleep(0)
    assert cancelled == [True]
```

At the end of `python/tests/deployment/test_container_contract.py`, add:

```python
def test_the_yt_dlp_update_workflow_bumps_tests_merges_and_builds() -> None:
    workflow = _repo_text(".github/workflows/yt-dlp-update.yml")
    assert 'cron: "17 3 * * *"' in workflow
    assert "https://pypi.org/pypi/yt-dlp/json" in workflow
    assert "uv lock --project python --upgrade-package yt-dlp" in workflow
    assert 'uv run pytest -m "not live" -q' in workflow
    assert 'gh pr merge "$branch" --squash --delete-branch' in workflow
    assert "gh workflow run container-image.yml --ref master" in workflow
    # The image build must accept the dispatch the update workflow sends.
    assert "workflow_dispatch:" in _repo_text(".github/workflows/container-image.yml")


def test_yt_dlp_is_pinned_identically_in_both_extras() -> None:
    pyproject = _repo_text("python/pyproject.toml")
    pins = re.findall(r'"yt-dlp==([0-9.]+)"', pyproject)
    assert len(pins) == 2 and len(set(pins)) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/operations/test_yt_dlp_version.py tests/test_worker.py tests/deployment/test_container_contract.py -q`
Expected: FAIL: `ModuleNotFoundError` for `yt_dlp_version`, `AttributeError` on
`worker.check_freshness`, a missing workflow file, and one pin instead of two.

- [ ] **Step 3: Implement**

Create `python/src/thoth_control_plane/operations/yt_dlp_version.py`:

```python
"""How far the installed yt-dlp is behind PyPI.

yt-dlp releases often, and YouTube changes often; a stale yt-dlp fails YouTube extraction.
The worker calls `check_freshness` once at startup and warns when it is behind; the daily
`.github/workflows/yt-dlp-update.yml` bumps the pin. Nothing here installs anything.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)
PYPI_URL = "https://pypi.org/pypi/yt-dlp/json"
TIMEOUT_SECONDS = 5.0


def parse_version(text: object) -> tuple[int, ...] | None:
    """yt-dlp's date versions: `2026.8.19`, `2026.08.19`, or `2026.08.19.1`."""
    if not isinstance(text, str):
        return None
    parts = text.split(".")
    if not 3 <= len(parts) <= 4 or not all(p.isascii() and p.isdecimal() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def is_behind(installed: object, latest: object) -> bool:
    current, newest = parse_version(installed), parse_version(latest)
    return current is not None and newest is not None and current < newest


def latest_from_pypi(payload: object) -> str | None:
    info = payload.get("info") if isinstance(payload, dict) else None
    version = info.get("version") if isinstance(info, dict) else None
    return version if parse_version(version) is not None else None


def installed_version() -> str | None:
    try:
        from yt_dlp.version import __version__
    except ImportError:
        return None
    return __version__ if isinstance(__version__, str) else None


async def _fetch_json(url: str) -> object:
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


async def check_freshness(
    fetch: Callable[[str], Awaitable[object]] | None = None,
    installed: str | None = None,
) -> bool | None:
    """True when behind (and warn), False when current, None when unknown. Never raises."""
    current = installed or installed_version()
    if current is None:
        return None
    try:
        payload = await asyncio.wait_for((fetch or _fetch_json)(PYPI_URL), TIMEOUT_SECONDS)
    except Exception:
        logger.info("yt-dlp freshness unknown: pypi unreachable")
        return None
    latest = latest_from_pypi(payload)
    if latest is None:
        return None
    behind = is_behind(current, latest)
    if behind:
        logger.warning(
            "yt-dlp is behind pypi installed=%s latest=%s; the daily update workflow bumps it",
            current,
            latest,
        )
    return behind
```

In `worker.py`, import `from thoth_control_plane.operations.yt_dlp_version import check_freshness`
(after the `observability` import). In `run_worker`, after
`capability = await check_scrapling_capability()`, start the task and wrap the rest of the
body so the task stops with the worker:

```python
    # A stale yt-dlp fails YouTube extraction; warn once, in the background, never block.
    freshness = asyncio.create_task(check_freshness())
    try:
        client = await Client.connect(
            runtime_settings.THOTH_TEMPORAL_TARGET,
            namespace=runtime_settings.THOTH_TEMPORAL_NAMESPACE,
            data_converter=pydantic_data_converter,
        )
        async with (
            build_source_investigation_worker(client, runtime_settings, capability=capability),
            Worker(
                client,
                task_queue=LEGACY_ADAPTER_TASK_QUEUE,
                activities=[
                    build_legacy_scout_activity(runtime_settings.THOTH_CONTROL_PLANE_ARTIFACT_ROOT)
                ],
                max_concurrent_activities=LEGACY_ADAPTER_MAX_CONCURRENT_ACTIVITIES,
            ),
        ):
            await asyncio.Future()
    finally:
        freshness.cancel()
```

Create `.github/workflows/yt-dlp-update.yml`:

```yaml
name: yt-dlp update

# yt-dlp releases often and YouTube changes often. Daily: when PyPI has a newer yt-dlp, bump
# the pin and the lock, run the offline suite here, merge the pull request, and dispatch the
# image build. A pull request opened with the default token starts no other workflow, so the
# tests run in this job and the build is dispatched explicitly.

on:
  schedule:
    - cron: "17 3 * * *"
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write
  actions: write

concurrency:
  group: yt-dlp-update
  cancel-in-progress: false

jobs:
  bump:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    env:
      THOTH_FFMPEG: /usr/bin/ffmpeg
      THOTH_FFPROBE: /usr/bin/ffprobe
    steps:
      - name: Check out repository
        uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4

      - name: Compare the pin with PyPI
        id: versions
        run: |
          latest="$(curl -fsS https://pypi.org/pypi/yt-dlp/json | jq -r .info.version)"
          pinned="$(grep -oP 'yt-dlp==\K[0-9.]+' python/pyproject.toml | head -n 1)"
          newest="$(printf '%s\n%s\n' "$pinned" "$latest" | sort -V | tail -n 1)"
          echo "latest=$latest" >> "$GITHUB_OUTPUT"
          echo "pinned=$pinned" >> "$GITHUB_OUTPUT"
          if [ -n "$latest" ] && [ "$latest" != "$pinned" ] && [ "$newest" = "$latest" ]; then
            echo "newer=true" >> "$GITHUB_OUTPUT"
          else
            echo "newer=false" >> "$GITHUB_OUTPUT"
          fi

      - name: Install media test dependencies
        if: steps.versions.outputs.newer == 'true'
        run: |
          sudo apt-get update
          sudo apt-get install --yes --no-install-recommends ffmpeg

      - name: Set up Python
        if: steps.versions.outputs.newer == 'true'
        uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5
        with:
          python-version: "3.12"

      - name: Set up uv
        if: steps.versions.outputs.newer == 'true'
        uses: astral-sh/setup-uv@d0cc045d04ccac9d8b7881df0226f9e82c39688e # v6
        with:
          version: "0.10.8"

      - name: Set up Bun
        if: steps.versions.outputs.newer == 'true'
        uses: oven-sh/setup-bun@0c5077e51419868618aeaa5fe8019c62421857d6 # v2
        with:
          bun-version: "1.3.14"

      - name: Bump the pin and the lock
        if: steps.versions.outputs.newer == 'true'
        env:
          LATEST: ${{ steps.versions.outputs.latest }}
          PINNED: ${{ steps.versions.outputs.pinned }}
        run: |
          sed -i "s/yt-dlp==${PINNED}/yt-dlp==${LATEST}/g" python/pyproject.toml
          uv lock --project python --upgrade-package yt-dlp

      - name: Run the offline tests
        if: steps.versions.outputs.newer == 'true'
        working-directory: python
        run: |
          uv sync --frozen --all-groups --extra acquisition
          uv run pytest -m "not live" -q

      - name: Open and merge the pull request
        if: steps.versions.outputs.newer == 'true'
        env:
          GH_TOKEN: ${{ github.token }}
          LATEST: ${{ steps.versions.outputs.latest }}
        run: |
          branch="chore/yt-dlp-${LATEST}"
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git switch -c "$branch"
          git add python/pyproject.toml python/uv.lock
          git commit -m "chore(deps): bump yt-dlp to ${LATEST}"
          git push --force origin "$branch"
          gh pr view "$branch" > /dev/null 2>&1 || gh pr create --base master --head "$branch" \
            --title "chore(deps): bump yt-dlp to ${LATEST}" \
            --body "Automated daily bump. The offline suite passed in the yt-dlp update job."
          gh pr merge "$branch" --squash --delete-branch

      - name: Build the image from master
        if: steps.versions.outputs.newer == 'true'
        env:
          GH_TOKEN: ${{ github.token }}
        run: gh workflow run container-image.yml --ref master
```

In `.github/workflows/container-image.yml` (CRLF), add the dispatch trigger after
`pull_request:`, preserving CRLF:

```bash
python - <<'PY'
from pathlib import Path

path = Path("C:/Users/mfr/Documents/MyTools/CLIPPER/.github/workflows/container-image.yml")
data = path.read_bytes()
old = b"  pull_request:\r\n"
assert data.count(old) == 1
new = old + b"  # The yt-dlp update workflow dispatches a build after it merges a bump.\r\n  workflow_dispatch:\r\n"
path.write_bytes(data.replace(old, new))
PY
```

In `python/pyproject.toml` (CRLF working copy), add yt-dlp to the `acquisition` extra:

```bash
python - <<'PY'
from pathlib import Path

path = Path("C:/Users/mfr/Documents/MyTools/CLIPPER/python/pyproject.toml")
data = path.read_bytes()
nl = b"\r\n" if b"\r\n" in data else b"\n"
old = b'acquisition = ["scrapling[fetchers]>=0.4.15,<0.5"]' + nl
assert data.count(old) == 1
new = (
    b"# yt-dlp is pinned in both extras; the yt-dlp update workflow bumps both." + nl
    + b'acquisition = ["scrapling[fetchers]>=0.4.15,<0.5", "yt-dlp==2026.8.19"]' + nl
)
path.write_bytes(data.replace(old, new))
PY
```

Then relock and check the lock:

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER && ~/.local/bin/uv lock --project python && ~/.local/bin/uv lock --project python --locked >/dev/null 2>&1; echo EXIT=$?'
git diff --stat -- python/uv.lock
```

Expected: `EXIT=0` and `python/uv.lock | 2 +`: yt-dlp joins the `acquisition`
optional dependencies and `requires-dist` (`marker = "extra == 'acquisition'"`,
`specifier = "==2026.8.19"`). Nothing else changes.

- [ ] **Step 4: Run the tests and actionlint to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/operations/test_yt_dlp_version.py tests/test_worker.py tests/deployment/test_container_contract.py -q`
Expected: PASS. To prove the worker test, temporarily replace `freshness.cancel()` with
`pass`: the test fails. Restore it.

Run the actionlint command from Global Constraints. Expected: no output, exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/operations/yt_dlp_version.py python/src/thoth_control_plane/worker.py .github/workflows/yt-dlp-update.yml .github/workflows/container-image.yml python/pyproject.toml python/uv.lock python/tests/operations/test_yt_dlp_version.py python/tests/test_worker.py python/tests/deployment/test_container_contract.py
git commit -m "feat(ops): keep yt-dlp fresh with a daily bump and a startup check"
```

---

### Task 7: Capture and fixture tools

**Files:**
- Create: `python/src/thoth_control_plane/operations/youtube_capture.py`
- Create: `python/src/thoth_control_plane/operations/youtube_fixture.py`
- Test: `python/tests/operations/test_youtube_capture.py`,
  `python/tests/operations/test_youtube_fixture.py`

**Interfaces:**
- Consumes: Tasks 2–5 (`canonicalize_youtube_url`, `parse_info`, `select_formats`,
  `channel_candidates`, `video_url`, `YtDlpClient`, `YouTubeHeadlessBrowser`, `adopt`,
  `GRID_SIZE`, `TABS`); `comment_targets` (`card_browser.py`); the shared sanitizer helpers
  `MEDIA_HOST`, `_leaves`, `leak_count` (`threads_fixture.py`), `_Pseudonyms`
  (`tiktok_comment_fixture.py`), `SYNTHETIC_EPOCH`, `SYNTHETIC_EPOCH_STEP`, `_floor`
  (`tiktok_discovery_fixture.py`).
- Produces:
  - `youtube_capture.main(argv) -> int`: reads `<kind> <url>` lines (kinds `video`, `short`,
    `channel`); a bad line returns 2 before any network access and never echoes the URL;
    writes `<kind>.json` and card PNGs under `--out`; validates the merged MP4 through
    `adopt`, then deletes it; prints kinds, statuses, counts, and size buckets only.
  - `_bucket(size: int) -> str`.
  - `youtube_fixture.build_post(raw)`, `build_channel(raw)`, `build(raw)`, each returning
    `(fixture, leak_scope)`; `main(argv) -> int` writes the fixture only with 0 leaks.
  - Fixture shape: `{"kind", "method": "yt_dlp", "counts", "document", "expected"}`, plus
    `"handle"` for a channel. A post's `expected` holds `post`, `channel_url`,
    `duration_seconds`, `comments`, `dropped_comments`, and `choice`; a channel's holds
    `candidates`.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/operations/test_youtube_capture.py`:

```python
"""The YouTube capture CLI refuses bad input before any network access and never echoes a URL."""

from __future__ import annotations

from pathlib import Path

import pytest

from thoth_control_plane.operations.youtube_capture import _bucket, main

SECRET = "secret_person"


@pytest.mark.parametrize(
    "line",
    [
        f"bogus https://www.youtube.com/@{SECRET}",
        f"video https://www.youtube.com/@{SECRET}",
        f"short http://www.youtube.com/watch?v={SECRET}x",
        "channel https://www.youtube.com/watch?v=abcDEF123_-",
        "video",
    ],
)
def test_bad_lines_stop_before_any_fetch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], line: str
) -> None:
    urls = tmp_path / "urls.txt"
    urls.write_text(line + "\n", encoding="utf-8")
    assert main(["--urls", str(urls), "--out", str(tmp_path / "raw")]) == 2
    out = capsys.readouterr().out
    assert SECRET not in out and "youtube.com" not in out
    assert "error" in out
    assert list((tmp_path / "raw").glob("*.json")) == []


@pytest.mark.parametrize(
    ("size", "bucket"),
    [(1, "<10MB"), (60 * 1024 * 1024, "<100MB"), (500 * 1024 * 1024, ">=450MB")],
)
def test_sizes_are_reported_as_buckets(size: int, bucket: str) -> None:
    assert _bucket(size) == bucket
```

Create `python/tests/operations/test_youtube_fixture.py`:

```python
"""YouTube fixture tooling: sanitizing, leak checking, and the replay of sanitized documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.acquisition.adapters.youtube import (
    YouTubeIdentity,
    parse_info,
    select_formats,
    video_url,
)
from thoth_control_plane.operations import youtube_fixture
from thoth_control_plane.operations.threads_fixture import _leaves, leak_count
from thoth_control_plane.operations.youtube_fixture import build_channel, build_post, main

MB = 1024 * 1024
SECRETS = (
    "realVideo01",
    "realperson",
    "UCrealchannel0000000000a",
    "Secret title about Jakarta",
    "Secret description",
    "fan_one",
    "Totally private comment",
    "UgzRealCommentId",
    "googlevideo",
    "2024-05-01",
)


def _raw_info() -> dict[str, Any]:
    return {
        "id": "realVideo01",
        "title": "Secret title about Jakarta",
        "description": "Secret description",
        "uploader": "Real Person",
        "uploader_id": "@realperson",
        "uploader_url": "https://www.youtube.com/@realperson",
        "channel_id": "UCrealchannel0000000000a",
        "channel_url": "https://www.youtube.com/channel/UCrealchannel0000000000a",
        "upload_date": "2024-05-01",
        "timestamp": 1_714_566_896,
        "duration": 600,
        "view_count": 4_537,
        "like_count": 123,
        "comment_count": 45,
        "live_status": "not_live",
        "formats": [
            {
                "format_id": "137",
                "protocol": "https",
                "url": "https://rr1.googlevideo.com/videoplayback?sig=secret",
                "ext": "mp4",
                "vcodec": "avc1.640028",
                "acodec": "none",
                "width": 1920,
                "height": 1080,
                "tbr": 2_000.5,
                "filesize": 150 * MB + 7,
            },
            {
                "format_id": "140",
                "protocol": "https",
                "url": "https://rr1.googlevideo.com/audio?sig=secret",
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "tbr": 129.5,
                "filesize": 10 * MB + 3,
            },
        ],
        "comments": [
            {
                "id": "UgzRealCommentId",
                "parent": "root",
                "author": "@fan_one",
                "author_id": "UCfanchannel00000000000a",
                "text": "Totally private comment",
                "like_count": 7,
            }
        ],
    }


def _no_leak(fixture: dict[str, Any], scope: dict[str, Any]) -> None:
    text = json.dumps(fixture, ensure_ascii=False)
    assert [secret for secret in SECRETS if secret in text] == []
    assert leak_count(scope, "\n".join(sorted(_leaves(fixture)))) == 0


def test_post_fixture_carries_no_original_value_and_replays() -> None:
    fixture, scope = build_post({"kind": "video", "extract": {"status": "ok", "info": _raw_info()}})
    _no_leak(fixture, scope)
    document = fixture["document"]
    identity = YouTubeIdentity(canonical_url=video_url(document["id"]), video_id=document["id"])
    parsed = parse_info(document, identity)
    assert parsed is not None
    assert parsed.post.owner_handle == "user_001"
    assert parsed.post.engagement == {"play": 4_500, "like": 120, "comment": 45}
    assert [(c.author, c.likes) for c in parsed.comments] == [("user_002", 7)]
    choice = select_formats(document["formats"], parsed.duration_seconds)
    assert (choice.video_format, choice.audio_format, choice.short_side) == ("137", "140", 1080)
    assert fixture["expected"]["choice"] == {
        "video_format": "137",
        "audio_format": "140",
        "short_side": 1080,
    }
    assert all(f["url"].startswith("https://media.example.test/") for f in document["formats"])


def test_a_capture_without_info_is_refused() -> None:
    with pytest.raises(ValueError):
        build_post({"kind": "video", "extract": {"status": "request_blocked", "info": None}})


def test_channel_fixture_keeps_listings_and_details_consistent() -> None:
    raw = {
        "kind": "channel",
        "handle": "realperson",
        "listings": {
            "videos": {
                "status": "ok",
                "listing": {"entries": [{"id": "realVideo01", "view_count": 999}]},
            },
            "shorts": {"status": "request_blocked", "listing": None},
        },
        "details": {"realVideo01": _raw_info(), "realVideo02": {"error": "request_blocked"}},
    }
    fixture, scope = build_channel(raw)
    _no_leak(fixture, scope)
    document = fixture["document"]
    (alias,) = document["details"]
    assert document["listings"]["videos"]["entries"] == [{"id": alias, "view_count": 990}]
    assert fixture["expected"]["candidates"] == [alias]
    assert fixture["handle"] == "user_001"


def test_main_writes_a_clean_fixture(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw_path, out = tmp_path / "video.json", tmp_path / "out.json"
    raw_path.write_text(
        json.dumps({"kind": "video", "extract": {"status": "ok", "info": _raw_info()}}),
        encoding="utf-8",
    )
    assert main(["--raw", str(raw_path), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert json.loads(printed)["leaks"] == 0
    assert [secret for secret in SECRETS if secret in printed] == []
    assert json.loads(out.read_text(encoding="utf-8"))["kind"] == "video"


def test_main_refuses_to_write_a_leaking_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leaking = (
        {"kind": "video", "counts": {}, "document": {"x": "realperson"}},
        {"secrets": ["realperson"]},
    )
    monkeypatch.setattr(youtube_fixture, "build", lambda raw: leaking)
    raw_path, out = tmp_path / "video.json", tmp_path / "out.json"
    raw_path.write_text("{}", encoding="utf-8")
    assert main(["--raw", str(raw_path), "--out", str(out)]) == 1
    assert not out.exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/operations/test_youtube_capture.py tests/operations/test_youtube_fixture.py -q`
Expected: FAIL with `ModuleNotFoundError` for both modules.

- [ ] **Step 3: Implement**

Create `python/src/thoth_control_plane/operations/youtube_capture.py`:

```python
"""Operator-run, read-only YouTube capture for the Stage 3d evidence and golden fixtures.

Never run by the test suite and only after the operator authorizes the capture. Reads
`<kind> <url>` lines (kind: video, short, channel) from `--urls`. For a video it runs the
real extract, format choice, download, merge, and validation, then the card crops; for a
channel, the flat listings and the candidates' details. Raw JSON and card PNGs go under
`--out`; the merged video is validated and then deleted. URLs, handles, titles, and text are
never printed; stdout carries kinds, statuses, and counts only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import shutil
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from thoth_control_plane.acquisition.adapters.threads import _match_safe_path
from thoth_control_plane.acquisition.adapters.youtube import (
    CANONICAL_BASE,
    YouTubeUrlError,
    canonicalize_youtube_url,
    channel_candidates,
    parse_info,
    select_formats,
    video_url,
)
from thoth_control_plane.acquisition.card_browser import comment_targets
from thoth_control_plane.acquisition.materializer import (
    MediaMaterializationError,
    MediaMaterializer,
    resolve_host_via_getaddrinfo,
)
from thoth_control_plane.acquisition.models import AcquisitionStrategy
from thoth_control_plane.acquisition.youtube_discovery import GRID_SIZE, TABS
from thoth_control_plane.acquisition.youtube_service import (
    YouTubeHeadlessBrowser,
    YtDlpClient,
    YtDlpError,
)

KINDS = ("video", "short", "channel")
SPACING_SECONDS = 5
CHANNEL_PATH = re.compile(r"/@(?P<handle>[A-Za-z0-9._-]{1,64})/?")
MB = 1024 * 1024


def _bucket(size: int) -> str:
    """Size as a coarse bucket, never an exact value."""
    for limit in (10, 50, 100, 250, 450):
        if size < limit * MB:
            return f"<{limit}MB"
    return ">=450MB"


async def _video(kind: str, url: str, out: Path) -> dict[str, Any]:
    identity = canonicalize_youtube_url(url)
    client = YtDlpClient()
    raw: dict[str, Any] = {"kind": kind, "video_id": identity.video_id}
    try:
        info = await client.extract(str(identity.canonical_url), comments=True)
        raw["extract"] = {"status": "ok", "info": info}
    except YtDlpError as error:
        raw["extract"] = {"status": error.reason.value, "info": None}
        return raw
    parsed = parse_info(info, identity)
    choice = select_formats(info.get("formats"), parsed.duration_seconds if parsed else None)
    raw["media"] = {"choice": None, "valid": False}
    if parsed is None or choice is None:
        return raw
    raw["media"]["choice"] = {
        "short_side": choice.short_side,
        "estimate": _bucket(choice.estimated_bytes),
    }
    work = out / f"{kind}.download"
    try:
        work.mkdir(parents=True, exist_ok=True)
        merged = await client.download(str(identity.canonical_url), choice, work)
        async with httpx.AsyncClient() as http:
            location = PurePosixPath(f"{kind}-media")
            media = await MediaMaterializer(http, resolve_host_via_getaddrinfo).adopt(
                merged, work / location, location, AcquisitionStrategy.YT_DLP
            )
        raw["media"].update({"valid": True, "size": _bucket(media.bytes)})
    except MediaMaterializationError:
        raw["media"]["valid"] = False
    finally:
        shutil.rmtree(work, ignore_errors=True)
    await asyncio.sleep(SPACING_SECONDS)
    browser = YouTubeHeadlessBrowser()
    try:
        cards = await browser.cards(
            str(identity.canonical_url),
            parsed.channel_url,
            want_post=False,
            targets=comment_targets(parsed.comments),
        )
    finally:
        await browser.close()
    for n, png in enumerate(cards.comment_pngs.values(), start=1):
        (out / f"{kind}-comment-{n}.png").write_bytes(png)
    if cards.profile_png is not None:
        (out / f"{kind}-profile.png").write_bytes(cards.profile_png)
    raw["cards"] = {
        "comments": len(cards.comment_pngs),
        "comment_targets": len(parsed.comments),
        "profile": cards.profile_png is not None,
        "problems": cards.problems,
    }
    return raw


async def _channel(kind: str, url: str, out: Path) -> dict[str, Any]:
    handle = _match_safe_path(url, CHANNEL_PATH, "youtube", YouTubeUrlError).group("handle")
    client = YtDlpClient()
    raw: dict[str, Any] = {"kind": kind, "handle": handle, "listings": {}, "details": {}}
    for tab in TABS:
        try:
            listing = await client.listing(f"{CANONICAL_BASE}/@{handle}/{tab}", GRID_SIZE)
            raw["listings"][tab] = {"status": "ok", "listing": listing}
        except YtDlpError as error:
            raw["listings"][tab] = {"status": error.reason.value, "listing": None}
        await asyncio.sleep(SPACING_SECONDS)
    listings = [v["listing"] for v in raw["listings"].values() if v["listing"] is not None]
    for video_id in channel_candidates(listings, GRID_SIZE):
        try:
            raw["details"][video_id] = await client.extract(video_url(video_id), comments=False)
        except YtDlpError as error:
            raw["details"][video_id] = {"error": error.reason.value}
        await asyncio.sleep(SPACING_SECONDS)
    return raw


def _summary(raw: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"kind": raw["kind"]}
    if "extract" in raw:
        info = raw["extract"]["info"] or {}
        formats = info.get("formats") or []
        summary["extract"] = {
            "status": raw["extract"]["status"],
            "comments": len(info.get("comments") or []),
            "formats": len(formats),
        }
    if "media" in raw:
        summary["media"] = raw["media"]
    if raw.get("cards") is not None:
        summary["cards"] = raw["cards"]
    if "listings" in raw:
        summary["listings"] = {
            tab: {
                "status": value["status"],
                "entries": len((value["listing"] or {}).get("entries") or []),
            }
            for tab, value in raw["listings"].items()
        }
        summary["details"] = {
            "count": len(raw["details"]),
            "ok": sum("error" not in detail for detail in raw["details"].values()),
        }
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
        capture = _channel if kind == "channel" else _video
        try:
            raw = await capture(kind, url.strip(), out)
        except YouTubeUrlError:
            print(json.dumps({"kind": kind, "error": "invalid_source_url"}))
            return 2
        (out / f"{kind}.json").write_text(json.dumps(raw, default=str), encoding="utf-8")
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

Create `python/src/thoth_control_plane/operations/youtube_fixture.py`:

```python
"""Turn one raw YouTube capture into a sanitized golden fixture.

Operator-run after an authorized capture. Only the keys the parsers read survive. Video,
channel, and comment ids, handles, titles, descriptions, and comment text are pseudonymized;
format URLs become synthetic; timestamps move to a synthetic one-hour grid; counters are
floored. The leak check compares the capture's identifying strings (ids, handles, text, URLs)
with the fixture; a fixture with any surviving one is not written. Output reports counts only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.adapters.youtube import (
    YouTubeIdentity,
    channel_candidates,
    parse_info,
    select_formats,
    video_url,
)
from thoth_control_plane.acquisition.normalize import _count
from thoth_control_plane.operations.threads_fixture import MEDIA_HOST, _leaves, leak_count
from thoth_control_plane.operations.tiktok_comment_fixture import _Pseudonyms
from thoth_control_plane.operations.tiktok_discovery_fixture import (
    SYNTHETIC_EPOCH,
    SYNTHETIC_EPOCH_STEP,
    _floor,
)

FORMAT_KEYS = ("format_id", "protocol", "ext", "vcodec", "acodec", "width", "height", "tbr")
SIZE_KEYS = ("filesize", "filesize_approx")
COUNTERS = ("view_count", "like_count", "comment_count")
# Strings that identify a person or a video: the leak check's whole scope.
SECRET_KEYS = frozenset(
    {
        "id",
        "title",
        "description",
        "uploader",
        "uploader_id",
        "uploader_url",
        "channel",
        "channel_id",
        "channel_url",
        "author",
        "author_id",
        "author_url",
        "author_thumbnail",
        "text",
        "url",
        "webpage_url",
        "thumbnail",
    }
)
Fixture = tuple[dict[str, Any], dict[str, Any]]


def _secrets(value: Any) -> Any:
    """Every identifying string anywhere in the raw capture, kept for the leak check."""
    found: list[str] = []
    stack = [value]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, item in node.items():
                if key in SECRET_KEYS and isinstance(item, str):
                    found.append(item)
                    found.append(item.removeprefix("@"))
                else:
                    stack.append(item)
        elif isinstance(node, list):
            stack.extend(node)
    return {"secrets": found}


class _Sanitizer:
    def __init__(self) -> None:
        self.names = _Pseudonyms()
        self.videos: dict[str, str] = {}
        self.channels: dict[str, str] = {}
        self.comments: dict[str, str] = {}
        self.urls = 0
        self.epochs = 0

    def video_id(self, value: object) -> str:
        key = str(value)
        return self.videos.setdefault(key, f"vid{len(self.videos) + 1:08d}")

    def channel_id(self, value: object) -> str:
        key = str(value)
        return self.channels.setdefault(key, f"UC{len(self.channels) + 1:022d}")

    def comment_id(self, value: object) -> str:
        key = str(value)
        return self.comments.setdefault(key, f"Ugz{len(self.comments) + 1:08d}")

    def handle(self, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        alias = self.names.handle(value.removeprefix("@"))
        return f"@{alias}" if value.startswith("@") else alias

    def epoch(self) -> int:
        self.epochs += 1
        return SYNTHETIC_EPOCH + self.epochs * SYNTHETIC_EPOCH_STEP

    def counter(self, value: object) -> int | None:
        count = _count(value)
        return None if count is None else _floor(count)

    def _format(self, fmt: dict[str, Any]) -> dict[str, Any]:
        out = {key: fmt[key] for key in FORMAT_KEYS if key in fmt}
        for key in SIZE_KEYS:
            if (size := self.counter(fmt.get(key))) is not None:
                out[key] = size
        if fmt.get("url"):
            self.urls += 1
            out["url"] = f"{MEDIA_HOST}/youtube/{self.urls}"
        return out

    def _comment(self, comment: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.comment_id(comment.get("id")),
            "parent": comment.get("parent") if comment.get("parent") == "root" else "reply",
            "author": self.handle(comment.get("author")),
            "author_id": self.channel_id(comment.get("author_id")),
            "text": self.names.text(comment.get("text")),
        }
        if (likes := self.counter(comment.get("like_count"))) is not None:
            out["like_count"] = likes
        return out

    def info(self, info: dict[str, Any], *, formats: bool, comments: bool) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.video_id(info.get("id")),
            "uploader_id": self.handle(info.get("uploader_id")),
            "channel_id": self.channel_id(info.get("channel_id")),
            "live_status": info.get("live_status"),
        }
        for key in ("title", "description"):
            if isinstance(info.get(key), str):
                out[key] = self.names.text(info[key])
        if info.get("timestamp") is not None:
            out["timestamp"] = self.epoch()
        if isinstance(info.get("duration"), (int, float)):
            out["duration"] = info["duration"]
        for key in COUNTERS:
            if (count := self.counter(info.get(key))) is not None:
                out[key] = count
        if formats and isinstance(info.get("formats"), list):
            out["formats"] = [self._format(f) for f in info["formats"] if isinstance(f, dict)]
        if comments and isinstance(info.get("comments"), list):
            out["comments"] = [self._comment(c) for c in info["comments"] if isinstance(c, dict)]
        return out

    def listing(self, listing: dict[str, Any]) -> dict[str, Any]:
        entries = listing.get("entries") if isinstance(listing.get("entries"), list) else []
        return {
            "entries": [
                {"id": self.video_id(e.get("id")), "view_count": self.counter(e.get("view_count"))}
                for e in entries
                if isinstance(e, dict)
            ]
        }


def _expected_post(info: dict[str, Any]) -> dict[str, Any]:
    identity = YouTubeIdentity(canonical_url=video_url(info["id"]), video_id=info["id"])
    parsed = parse_info(info, identity)
    if parsed is None:
        raise ValueError("the sanitized info no longer parses")
    choice = select_formats(info.get("formats"), parsed.duration_seconds)
    return {
        "post": parsed.post.model_dump(mode="json"),
        "channel_url": parsed.channel_url,
        "duration_seconds": parsed.duration_seconds,
        "comments": [c.model_dump(mode="json", exclude={"card"}) for c in parsed.comments],
        "dropped_comments": parsed.dropped_comments,
        "choice": None
        if choice is None
        else {
            "video_format": choice.video_format,
            "audio_format": choice.audio_format,
            "short_side": choice.short_side,
        },
    }


def build_post(raw: dict[str, Any]) -> Fixture:
    info = raw["extract"]["info"]
    if not isinstance(info, dict):
        raise ValueError("the capture holds no info")
    document = _Sanitizer().info(info, formats=True, comments=True)
    fixture = {
        "kind": raw["kind"],
        "method": "yt_dlp",
        "counts": {
            "formats": len(info.get("formats") or []),
            "comments": len(info.get("comments") or []),
        },
        "document": document,
        "expected": _expected_post(document),
    }
    return fixture, _secrets(info)


def build_channel(raw: dict[str, Any]) -> Fixture:
    sanitizer = _Sanitizer()
    listings = {
        tab: sanitizer.listing(value["listing"])
        for tab, value in raw["listings"].items()
        if isinstance(value.get("listing"), dict)
    }
    details = {
        sanitizer.video_id(video_id): sanitizer.info(detail, formats=False, comments=False)
        for video_id, detail in raw["details"].items()
        if isinstance(detail, dict) and "error" not in detail
    }
    alias = sanitizer.names.handle(raw["handle"])
    fixture = {
        "kind": "channel",
        "method": "yt_dlp",
        "handle": alias,
        "counts": {
            "entries": sum(len(v["entries"]) for v in listings.values()),
            "details": len(details),
        },
        "document": {"listings": listings, "details": details},
        "expected": {"candidates": channel_candidates(listings.values(), 12)},
    }
    scope = _secrets({"listings": raw["listings"], "details": raw["details"]})
    scope["secrets"].append(raw["handle"])
    return fixture, scope


def build(raw: dict[str, Any]) -> Fixture:
    return build_channel(raw) if raw["kind"] == "channel" else build_post(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    raw = json.loads(args.raw.read_text(encoding="utf-8"))
    fixture, scope = build(raw)
    leaks = leak_count(scope, "\n".join(sorted(_leaves(fixture))))
    summary = {"kind": fixture["kind"], "counts": fixture["counts"], "leaks": leaks}
    print(json.dumps(summary))
    if leaks:
        return 1
    text = json.dumps(fixture, indent=2, ensure_ascii=False) + "\n"
    args.out.write_bytes(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/operations -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/src/thoth_control_plane/operations/youtube_capture.py python/src/thoth_control_plane/operations/youtube_fixture.py python/tests/operations/test_youtube_capture.py python/tests/operations/test_youtube_fixture.py
git commit -m "feat(ops): add youtube capture and fixture tools"
```

---

### Task 8: Live capture, card check, golden fixtures, and replay (HARD STOP)

**Files:**
- Create: `python/tests/fixtures/youtube/{video,short,channel}.json`
- Create: `python/tests/acquisition/test_youtube_replay.py`
- Modify (only if Step 4 requires it): `python/src/thoth_control_plane/acquisition/youtube_service.py`
  (`PROFILE_CARD_SELECTOR` or `TAG_COMMENTS_JS`)

**Interfaces:**
- Consumes: Task 7's tools; Tasks 2, 4, and 5 for the replay.
- Produces: three sanitized fixtures with 0 leaks and a replay test.

- [ ] **Step 1: HARD STOP — ask for capture authorization**

Ask the operator in Indonesian to authorize a live, anonymous, read-only capture of three
YouTube URLs: one video, one Short, and one channel. The operator's URL file is
`D:/thoth-tmp/bu/youtube/urls.txt`, one `<kind> <url>` line per kind (`video`, `short`,
`channel`). Never open, print, or inspect that file. Wait for the explicit authorization.
Never record it as an approval in any repository document.

- [ ] **Step 2: Run the capture inside the capture image**

The image carries yt-dlp 2026.08.19, ffmpeg, bun, and the Scrapling browsers.

```bash
wsl -e bash -lc 'docker run --rm -v /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python/src:/src:ro -v /mnt/d/thoth-tmp/bu/youtube:/work -e PYTHONPATH=/src ghcr.io/muhfalihr/thoth@sha256:56fa84e6f99fe1d59c94ed0389236866c0b82fd0d5a0119e1d996bd5c9e5adf9 python -m thoth_control_plane.operations.youtube_capture --urls /work/urls.txt --out /work/capture 2>/mnt/d/thoth-tmp/bu/youtube/capture.err; echo EXIT=$?' | sed -E 's#https?://[^ "]+#<url>#g'
```

Expected: three summary lines and `EXIT=0`:
- `video` and `short`: `extract.status` `ok`, a comment count, `media.choice.short_side`
  in 1080/720/480, `media.valid: true`, a size bucket, card counts, `profile: true`;
- `channel`: both listings with their entry counts, and `details.ok` greater than 0.

If `EXIT` is not 0, read only `tail -n 5` of `capture.err` through the same `sed` mask.

- [ ] **Step 3: Check the stop conditions**

Stop and report to the operator in Indonesian, with counts and enums only, if any of these
hold:
- an extract is not `ok` for the video or the Short;
- `media.valid` is false for both;
- both have comments, but no comment card was cropped;
- the profile card is missing on both;
- the channel has no detail that succeeded.

- [ ] **Step 4: Survey the cards when one is missing (dimensions and counts only)**

Run this only if a post kind has comments but no comment cards, or no profile card. Write
`D:/thoth-tmp/bu/youtube/card_survey.py` (not committed; never name it `selectors.py`,
which shadows the standard library):

```python
import asyncio
import json
from pathlib import Path

from scrapling.fetchers import AsyncStealthySession

from thoth_control_plane.acquisition.adapters.youtube import canonicalize_youtube_url

SURVEY_JS = """async () => {
  for (let i = 0; i < 8 && !document.querySelector("ytd-comment-thread-renderer"); i++) {
    window.scrollBy(0, 1200);
    await new Promise((r) => setTimeout(r, 1500));
  }
  const box = (el) => el ? [Math.round(el.getBoundingClientRect().width),
                            Math.round(el.getBoundingClientRect().height)] : null;
  const out = {};
  for (const s of ["ytd-comment-thread-renderer", "ytd-comment-view-model", "a[href*='lc=']",
                   "#page-header", "yt-page-header-renderer", "#channel-header"]) {
    out[s] = {count: document.querySelectorAll(s).length, box: box(document.querySelector(s))};
  }
  return out;
}"""


async def main() -> None:
    lines = dict(line.split(maxsplit=1) for line in Path("/work/urls.txt").read_text().splitlines() if line.strip())
    pages = {"watch": str(canonicalize_youtube_url(lines["video"].strip()).canonical_url),
             "channel": lines["channel"].strip()}
    for name, url in pages.items():
        found: dict = {}

        async def action(page):
            await page.wait_for_timeout(4_000)
            found.update(await page.evaluate(SURVEY_JS))

        session = AsyncStealthySession(headless=True, max_pages=1)
        try:
            active = await session.__aenter__()
            await active.fetch(url, page_action=action, timeout=90_000, wait=2_000)
        finally:
            await session.__aexit__(None, None, None)
        print(json.dumps({"page": name, **found}))
        await asyncio.sleep(5)


asyncio.run(main())
```

```bash
wsl -e bash -lc 'docker run --rm -v /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python/src:/src:ro -v /mnt/d/thoth-tmp/bu/youtube:/work -e PYTHONPATH=/src ghcr.io/muhfalihr/thoth@sha256:56fa84e6f99fe1d59c94ed0389236866c0b82fd0d5a0119e1d996bd5c9e5adf9 python /work/card_survey.py 2>/dev/null'
```

How to read the output:
- **Profile selector:** choose the smallest candidate on the `channel` page whose box is
  wider than 300 px and between 100 and 900 px tall. Set it as `PROFILE_CARD_SELECTOR`.
- **Comments:** if threads render but `a[href*='lc=']` is 0, the link tagging cannot work;
  the text fallback still tags. If threads are 0, the scroll in `TAG_COMMENTS_JS` needs
  more rounds.
- **Record it:** write each decision as a ledger ruling, change the constant, rerun
  `tests/acquisition/test_youtube_service.py` and the in-image tagging tests, then rerun
  Step 2.
- **If no candidate fits:** stop and report to the controller with the survey output.
  Never guess a selector.

- [ ] **Step 5: Build the fixtures**

```bash
mkdir -p python/tests/fixtures/youtube
wsl -e bash -lc 'for k in video short channel; do docker run --rm -v /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python/src:/src:ro -v /mnt/d/thoth-tmp/bu/youtube:/work -v /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python/tests/fixtures/youtube:/out -e PYTHONPATH=/src ghcr.io/muhfalihr/thoth@sha256:56fa84e6f99fe1d59c94ed0389236866c0b82fd0d5a0119e1d996bd5c9e5adf9 python -m thoth_control_plane.operations.youtube_fixture --raw /work/capture/$k.json --out /out/$k.json || echo "FAIL $k"; done'
```

Expected: three summary lines with `"leaks": 0`, and three files written.

If a kind reports leaks, find them with a keys-only probe:
- For each raw leaf found in a fixture leaf, print only the raw leaf's key path and its
  length. Never print the value.
- Then fix the sanitizer, writing a failing `test_youtube_fixture.py` test first.

Then scan the fixtures for real hosts:
`grep -c 'googlevideo\|ytimg\|ggpht\|youtube.com/@' python/tests/fixtures/youtube/*.json`.
Expected: `0` for each file. The only YouTube URL allowed is the synthetic
`channel_url` built from the pseudonymized channel id (`https://www.youtube.com/channel/UC000…`).

- [ ] **Step 6: Write the replay test**

Create `python/tests/acquisition/test_youtube_replay.py`:

```python
"""Sanitized golden fixtures replay through the YouTube parser, the format choice, and discovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.acquisition import youtube_service
from thoth_control_plane.acquisition.adapters.youtube import (
    MAX_DOWNLOAD_BYTES,
    YouTubeIdentity,
    channel_candidates,
    parse_info,
    select_formats,
    video_url,
)
from thoth_control_plane.acquisition.models import AcquisitionReason, ProfileDiscovery
from thoth_control_plane.acquisition.youtube_discovery import GRID_SIZE, YouTubeChannelDiscovery
from thoth_control_plane.acquisition.youtube_service import YtDlpError

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "youtube"
FIXTURES = {
    path.stem: json.loads(path.read_text(encoding="utf-8"))
    for path in sorted(FIXTURE_DIR.glob("*.json"))
}
POST_KINDS = ("video", "short")


def test_all_three_kinds_are_present() -> None:
    assert set(FIXTURES) == {"video", "short", "channel"}


@pytest.mark.parametrize("kind", POST_KINDS)
def test_post_fixture_replays_to_its_expected_parse(kind: str) -> None:
    fixture = FIXTURES[kind]
    document = fixture["document"]
    identity = YouTubeIdentity(canonical_url=video_url(document["id"]), video_id=document["id"])
    parsed = parse_info(document, identity)
    assert parsed is not None
    choice = select_formats(document["formats"], parsed.duration_seconds)
    assert choice is not None
    assert {
        "post": parsed.post.model_dump(mode="json"),
        "channel_url": parsed.channel_url,
        "duration_seconds": parsed.duration_seconds,
        "comments": [c.model_dump(mode="json", exclude={"card"}) for c in parsed.comments],
        "dropped_comments": parsed.dropped_comments,
        "choice": {
            "video_format": choice.video_format,
            "audio_format": choice.audio_format,
            "short_side": choice.short_side,
        },
    } == fixture["expected"]
    assert choice.estimated_bytes < MAX_DOWNLOAD_BYTES


def test_post_kinds_have_their_shape() -> None:
    for kind in POST_KINDS:
        expected = FIXTURES[kind]["expected"]
        assert expected["comments"], kind
        assert set(expected["post"]["engagement"]) >= {"play", "like"}
        assert expected["choice"]["short_side"] in (1080, 720, 480)
    # A Short is vertical: its resolution class is its width, the shorter side.
    short = FIXTURES["short"]["document"]
    video_format = FIXTURES["short"]["expected"]["choice"]["video_format"]
    chosen = next(f for f in short["formats"] if f["format_id"] == video_format)
    assert chosen["height"] > chosen["width"]


def test_content_is_yt_dlp_by_construction() -> None:
    assert youtube_service.CONTENT_METHOD == "yt_dlp"
    assert {FIXTURES[kind]["method"] for kind in FIXTURES} == {"yt_dlp"}


class _ReplayClient:
    def __init__(self, document: dict[str, Any]) -> None:
        self._document = document

    async def listing(self, url: str, limit: int) -> dict[str, Any]:
        return self._document["listings"][url.rsplit("/", 1)[1]]

    async def extract(self, url: str, *, comments: bool) -> dict[str, Any]:
        # The fixture keeps only the details the capture read; a missing one failed live.
        detail = self._document["details"].get(url.rsplit("=", 1)[1])
        if detail is None:
            raise YtDlpError(AcquisitionReason.REQUEST_BLOCKED)
        return detail


async def test_channel_fixture_replays_ranked() -> None:
    fixture = FIXTURES["channel"]
    document = fixture["document"]
    candidates = channel_candidates(document["listings"].values(), GRID_SIZE)
    assert candidates == fixture["expected"]["candidates"]

    async def no_sleep(seconds: float) -> None:
        return None

    discovery = YouTubeChannelDiscovery(_ReplayClient(document), no_sleep)  # type: ignore[arg-type]
    result = await discovery.discover(ProfileDiscovery(handle=fixture["handle"], limit=30))
    details = document["details"]
    assert details, "the capture must hold the candidates' details"
    assert {video.post_id for video in result.videos} <= set(candidates) & set(details)
    if set(candidates) <= set(details):
        assert result.reason is None
        assert len(result.videos) + result.drops.invalid == len(candidates)
```

- [ ] **Step 7: Run the replay and the YouTube suites**

Run: `MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/acquisition tests/operations -q`
Expected: PASS.

- [ ] **Step 8: Commit**

Check first that only these are staged: the three fixtures, the replay test, and
`youtube_service.py` if Step 4 changed it. Never stage raw captures, `urls.txt`, or PNGs.

```bash
git add python/tests/fixtures/youtube python/tests/acquisition/test_youtube_replay.py python/src/thoth_control_plane/acquisition/youtube_service.py
git status --short
git commit -m "test(acquisition): add youtube golden fixtures and replay"
```

---

### Task 9: Verification and documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-10-04-stage3d-youtube-design.md` (status line)
- Modify: `CHANGELOG.md` (CRLF, newest first)
- Modify: `docs/python-scout-migration-roadmap.md` (CRLF, append)
- Modify: `.superpowers/sdd/2026-09-23-python-scout-migration-program/progress.md` (CRLF,
  append; gitignored)

**Interfaces:**
- Consumes: every earlier task's commits and the Task 8 restricted evidence.
- Produces: the verification record and the next operator gate.

- [ ] **Step 1: Run the full suite into a file**

```bash
MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests -q -rA > D:/thoth-tmp/stage3d-suite.txt 2>&1; echo EXIT=$?
for s in PASSED FAILED SKIPPED ERROR; do echo "$s $(grep -c "^$s" D:/thoth-tmp/stage3d-suite.txt)"; done
```

Expected: 0 failed. Any failure is fixed before continuing.

- [ ] **Step 2: Run Ruff and actionlint, and refresh the graph**

Run the Ruff and actionlint commands from Global Constraints (expected: clean). Then run
`graphify update .` from the repository root. Never stage `graphify-out/`.

- [ ] **Step 3: Update the spec status line**

Replace the spec's `Status:` lines with:

```markdown
Status: written spec approved by the operator on 2026-10-04; implemented on branch
`feat/stage3d-youtube` (see `docs/superpowers/plans/2026-10-04-stage3d-youtube.md`).
```

- [ ] **Step 4: Write the CHANGELOG section and the checkpoint notes**

Write the new section to `D:/thoth-tmp/bu/youtube/changelog-section.md` (LF). It contains:
- the heading `## <today> - Stage 3d: YouTube acquisition, channel discovery, and yt-dlp freshness`;
- what shipped (routing and ids, parsers, `adopt`, acquirer and cards, discovery, yt-dlp
  freshness and the update workflow, tooling, fixtures), each item with its commit hash
  from `git log --oneline master..HEAD`;
- verification: the suite counts, plus clean Ruff and actionlint runs;
- restricted evidence from Task 8, as counts, keys, and enums only. Never a URL, a handle,
  a title, text, or a workflow id:
  - per kind: extract status, comment count, chosen short side, size bucket, media valid;
  - card counts, profile flag, and problem enums;
  - channel listing entry counts and detail successes;
  - fixture `leaks: 0`;
  - any selector rulings;
- `Next steps`, as AGENTS.md requires:
  - the operator reviews the branch; push, merge, and deploy each need their own
    authorization;
  - after the merge, the first scheduled or dispatched `yt-dlp update` run is the
    workflow's own proof; the operator watches it once;
  - the multi-account rotating login feature with UI integration is next;
  - the live smoke waits for final acceptance (ADR 0001).

Insert it into `CHANGELOG.md` before the first `## ` heading, keeping CRLF:

```bash
python - <<'PY'
from pathlib import Path

path = Path("C:/Users/mfr/Documents/MyTools/CLIPPER/CHANGELOG.md")
data = path.read_bytes()
assert data.endswith(b"\r\n")
text = data.decode("utf-8").replace("\r\n", "\n")
section = Path("D:/thoth-tmp/bu/youtube/changelog-section.md").read_text(encoding="utf-8")
at = text.index("\n## ") + 1
text = text[:at] + section.rstrip("\n") + "\n\n" + text[at:]
path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
PY
```

Append a short Stage 3d status entry to `docs/python-scout-migration-roadmap.md` and to the
checkpoint `progress.md`. It covers what shipped, a pointer to the CHANGELOG section, and
the same next steps. Use the same script shape, replacing the insertion with
`text = text.rstrip("\n") + "\n\n" + entry.rstrip("\n") + "\n"`. Never use `sed -i` on a
CRLF file.

- [ ] **Step 5: Commit and stop**

```bash
git add -f docs/superpowers/specs/2026-10-04-stage3d-youtube-design.md
git add CHANGELOG.md docs/python-scout-migration-roadmap.md
git status --short
git commit -m "docs: record stage 3d youtube completion"
```

Before committing, check that `git status --short` shows nothing from the never-stage list.
Then stop and report to the operator in Indonesian. The report covers:
- the commits;
- the suite result;
- any selector rulings;
- a **Next steps** section: branch review, then push, merge, and deploy (each its own
  authorization), the first `yt-dlp update` run, and the multi-account login feature.

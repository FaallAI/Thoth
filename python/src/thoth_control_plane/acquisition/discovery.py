"""Headless TikTok discovery: profile, keyword, and trending video lists.

TikTok signs its list APIs inside the page, so this module never builds an API request. It
opens the ordinary page in a stealthy headless session, scrolls it, and reads the list
responses the page itself makes. A captcha is avoided, never solved or blocked: when TikTok
refuses, the result is returned partial with a typed reason.

This is the sole boundary where raw list payloads are inspected. Only validated
`DiscoveredVideo` records and drop counts cross back out; nothing raw is retained or logged.
"""

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

MAX_CAPTION = 10_000
MAX_HASHTAG = 100
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

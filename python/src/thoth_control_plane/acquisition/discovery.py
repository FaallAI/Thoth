"""Headless TikTok discovery: profile, keyword, and trending video lists.

TikTok signs its list APIs inside the page, so this module never builds an API request. It
opens the ordinary page in a stealthy headless session, scrolls it, and reads the list
responses the page itself makes. A captcha is solved in the page when its drag subtypes
rise (see `captcha.py`); the rest are avoided, and when TikTok still refuses, the result is
returned partial with a typed reason.

This is the sole boundary where raw list payloads are inspected. Only validated
`DiscoveredVideo` records and drop counts cross back out; nothing raw is retained or logged.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from pydantic import ValidationError

from thoth_control_plane.acquisition.browser import (
    FETCH_OPTIONS,
    _decrement_active_sessions,
    _default_session_factory,
    _increment_active_sessions,
    _is_timeout,
)
from thoth_control_plane.acquisition.captcha import solve as solve_captcha
from thoth_control_plane.acquisition.cards import PROFILE_PAGE_JS
from thoth_control_plane.acquisition.models import (
    DiscoveredPhoto,
    DiscoveredVideo,
    DiscoveryDrops,
    DiscoveryKind,
    DiscoveryReason,
    DiscoveryRequest,
    DiscoveryResult,
    KeywordDiscovery,
    ProfileDiscovery,
)
from thoth_control_plane.acquisition.normalize import (
    normalize_engagement,
    numeric_id,
    published_at_from_epoch,
)

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
# Solving a captcha buys the scroll nothing once TikTok keeps re-raising it, so each
# discovery may try the solver this many times before falling back to the captcha reason.
MAX_SOLVES = 3
# The profile page card (spec 5c-2, G2): signed out, TikTok's grid answers "Something went
# wrong" (recorded 2026-10-22), so the card is cropped here, in the listing visit that the
# access policy signs in when it must. The avatar anchors the header; the clip spans the rest.
PROFILE_GRID_ITEMS = '[data-e2e="user-post-item"]'
PROFILE_HEADER = '[data-e2e="user-avatar"]'
GRID_WAIT_S = 10


@dataclass(frozen=True, slots=True)
class DiscoveryPage:
    """One parsed list response; internal, not a contract."""

    videos: list[DiscoveredVideo]
    has_more: bool
    drops: DiscoveryDrops
    reason: DiscoveryReason | None = None
    photos: list[DiscoveredPhoto] = field(default_factory=list)


def parse_discovery_page(
    kind: DiscoveryKind, body: bytes, http_status: int | None = None
) -> DiscoveryPage:
    """Reduce one raw list response body to validated videos and drop counts.

    A non-2xx HTTP status or a non-zero TikTok status code maps to `blocked`, whatever the
    body. Otherwise a body that is not a JSON object is what TikTok serves a refused request,
    so it maps to `captcha`.
    """
    if isinstance(http_status, int) and not 200 <= http_status < 300:
        return DiscoveryPage([], False, DiscoveryDrops(), DiscoveryReason.BLOCKED)
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        payload = None
    if not isinstance(payload, dict):
        return DiscoveryPage([], False, DiscoveryDrops(), DiscoveryReason.CAPTCHA)
    status = payload.get("statusCode", payload.get("status_code"))
    if status not in (None, 0, "0"):
        return DiscoveryPage([], False, DiscoveryDrops(), DiscoveryReason.BLOCKED)

    videos: list[DiscoveredVideo] = []
    photos: list[DiscoveredPhoto] = []
    ads = photo_posts = invalid = 0
    for item in _items(kind, payload):
        if not isinstance(item, dict):
            invalid += 1
        elif item.get("isAd") is True:
            ads += 1
        elif item.get("imagePost") is not None:
            photo_posts += 1
            if (photo := _photo(item)) is not None:
                photos.append(photo)
        elif (video := _video(item)) is not None:
            videos.append(video)
        else:
            invalid += 1
    has_more = payload.get("hasMore", payload.get("has_more")) in (True, 1)
    drops = DiscoveryDrops(ads=ads, photo_posts=photo_posts, invalid=invalid)
    return DiscoveryPage(videos, has_more, drops, photos=photos)


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
    post_id = numeric_id(item.get("id")) if isinstance(item.get("id"), str) else None
    author = item.get("author")
    handle = author.get("uniqueId") if isinstance(author, dict) else None
    if post_id is None or not isinstance(handle, str):
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


def _photo(item: dict[str, Any]) -> DiscoveredPhoto | None:
    """A photo post with the first link of each image; None without a usable one."""
    post_id = numeric_id(item.get("id")) if isinstance(item.get("id"), str) else None
    author = item.get("author")
    handle = author.get("uniqueId") if isinstance(author, dict) else None
    images = item.get("imagePost")
    listed = images.get("images") if isinstance(images, dict) else None
    urls: list[str] = []
    for image in listed if isinstance(listed, list) else []:
        links = image.get("imageURL", {}).get("urlList") if isinstance(image, dict) else None
        if isinstance(links, list) and links and isinstance(links[0], str):
            urls.append(links[0])
    if post_id is None or not isinstance(handle, str) or not urls:
        return None
    desc = item.get("desc")
    try:
        return DiscoveredPhoto(
            post_id=post_id,
            owner_handle=handle,
            canonical_url=f"https://www.tiktok.com/@{handle}/photo/{post_id}",
            caption=desc[:MAX_CAPTION] if isinstance(desc, str) else "",
            published_at=published_at_from_epoch(item.get("createTime")),
            hashtags=_hashtags(item.get("challenges")),
            image_urls=urls[:20],
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
    solves: int = 0
    # How many list responses had arrived when a captcha was last solved: a refusal among
    # them predates the solve and is stale, never a reason to stop.
    solved_after: int = 0
    timed_out: bool = False
    stop: str = "none"
    page_png: bytes | None = None

    def on_response(self, response: Any) -> None:
        if re.search(XHR_PATTERNS[self.kind], response.url):
            self.responses.append(response)

    async def attach(self, page: Any) -> None:
        # A session retry re-runs page_setup on a fresh page; start a clean tally so a
        # stale response or flag from the failed attempt never carries into this one.
        self.responses = []
        self.parsed = 0
        self.seen = set()
        self.done = False
        self.captcha = False
        self.solves = 0
        self.solved_after = 0
        self.timed_out = False
        self.stop = "none"
        self.page_png = None
        page.on("response", self.on_response)

    async def absorb(self) -> None:
        while self.parsed < len(self.responses):
            response = self.responses[self.parsed]
            self.parsed += 1
            try:
                body = await response.body()
            except Exception:
                body = b""
            page = parse_discovery_page(self.kind, body, getattr(response, "status", None))
            if _stale_refusal(page, self.parsed - 1, self.solved_after):
                continue
            self.seen.update(video.post_id for video in page.videos)
            if page.reason is not None or not page.has_more:
                self.done = True


async def _solve(page: Any, scroll: _Scroll) -> bool:
    """One budgeted solver run: a discovery never spends more than MAX_SOLVES on captchas."""
    if scroll.solves >= MAX_SOLVES:
        return False
    scroll.solves += 1
    solved = await solve_captcha(page)
    if solved:
        scroll.solved_after = len(scroll.responses)
    return solved


def _stale_refusal(page: DiscoveryPage, index: int, solved_after: int) -> bool:
    """A list response TikTok refused before a captcha was solved says nothing about after."""
    return page.reason is DiscoveryReason.CAPTCHA and index < solved_after


def _scroll_action(scroll: _Scroll) -> Callable[[Any], Awaitable[None]]:
    async def action(page: Any) -> None:
        if scroll.kind == "profile":
            # The modal hides the grid the crop below waits for, so clear it first.
            if await page.query_selector(CAPTCHA_SELECTOR) is not None:
                await _solve(page, scroll)
            # Before scrolling, while the grid's first rows sit under the header.
            with contextlib.suppress(Exception):
                scroll.page_png = await _crop_profile_page(page)
        # A failed or overlong scroll must never discard the pages Scrapling already captured.
        try:
            # A hard bound: a page await that never returns cannot outlive the deadline.
            await asyncio.wait_for(_paginate(page, scroll), SCROLL_DEADLINE_S)
        except TimeoutError:
            scroll.timed_out = True
            scroll.stop = "deadline"
        except Exception as error:
            scroll.stop = f"error:{type(error).__name__}"
            logger.warning(
                "tiktok discovery scroll failed kind=%s error=%s", scroll.kind, type(error).__name__
            )

    return action


async def _crop_profile_page(page: Any) -> bytes | None:
    for _ in range(GRID_WAIT_S):
        if await page.locator(PROFILE_GRID_ITEMS).count():
            head = await page.locator(PROFILE_HEADER).first.bounding_box()
            if head is None:
                return None
            rect = await page.evaluate(PROFILE_PAGE_JS, [head, PROFILE_GRID_ITEMS, 2])
            if not isinstance(rect, dict):
                return None
            return await page.screenshot(clip=rect, full_page=True, scale="css", timeout=10_000)
        await page.wait_for_timeout(1_000)
    return None


async def _paginate(page: Any, scroll: _Scroll) -> None:
    idle = 0
    for _ in range(MAX_SCROLLS):
        # The modal first: a list response refused while it shows is stale once it is solved.
        if await page.query_selector(CAPTCHA_SELECTOR) is not None:
            if not await _solve(page, scroll):
                scroll.captcha = True
                scroll.stop = "captcha"
                return
            idle = 0
        await scroll.absorb()
        if len(scroll.seen) >= scroll.limit:
            scroll.stop = "limit"
            return
        if scroll.done:
            scroll.stop = "done"
            return
        before = len(scroll.responses)
        await page.mouse.wheel(0, SCROLL_PX)
        if await _wait_for_new(page, scroll, before):
            idle = 0
        else:
            idle += 1
            if idle >= IDLE_SCROLLS:
                scroll.stop = "idle"
                return
    scroll.stop = "max_scrolls"


async def _wait_for_new(page: Any, scroll: _Scroll, before: int) -> bool:
    for _ in range(SCROLL_WAIT_MS // POLL_MS):
        if len(scroll.responses) > before:
            return True
        await page.wait_for_timeout(POLL_MS)
    return len(scroll.responses) > before


def _assemble(
    kind: DiscoveryKind,
    limit: int,
    parsed: list[DiscoveryPage],
    *,
    captcha: bool,
    timed_out: bool,
    solved_after: int = 0,
) -> DiscoveryResult:
    """Merge parsed pages in capture order; the first page reason stops assembly, except a
    refusal captured before a captcha was solved, which is stale."""
    videos: dict[str, DiscoveredVideo] = {}
    photos: dict[str, DiscoveredPhoto] = {}
    pages = ads = photo_posts = invalid = 0
    exhausted = False
    reason: DiscoveryReason | None = None
    for index, page in enumerate(parsed):
        if _stale_refusal(page, index, solved_after):
            continue
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
        for photo in page.photos:
            photos.setdefault(photo.post_id, photo)
        exhausted = not page.has_more
    if reason is None:
        if captcha:
            reason = DiscoveryReason.CAPTCHA
        elif not parsed:
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
        photos=list(photos.values())[:limit],
    )


def _empty(kind: DiscoveryKind, reason: DiscoveryReason) -> DiscoveryResult:
    return DiscoveryResult(
        kind=kind, videos=[], pages=0, exhausted=False, drops=DiscoveryDrops(), reason=reason
    )


def _parse_entry(kind: DiscoveryKind, entry: Any) -> DiscoveryPage:
    body = getattr(entry, "body", None)
    body = body if isinstance(body, bytes) else b""
    return parse_discovery_page(kind, body, getattr(entry, "status", None))


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
        pattern = XHR_PATTERNS[kind]
        try:
            session = self._session_factory(headless=True, max_pages=1, capture_xhr=pattern)
            active = await session.__aenter__()
        except Exception:
            return _empty(kind, DiscoveryReason.BROWSER_UNAVAILABLE)

        _increment_active_sessions()
        scroll = _Scroll(kind=kind, limit=request.limit)
        try:
            if isinstance(request, KeywordDiscovery):
                # Search answers only a session warmed on /explore; that visit is discarded.
                await active.fetch(EXPLORE_URL, **FETCH_OPTIONS)
            response = await active.fetch(
                _page_url(request),
                page_setup=scroll.attach,
                page_action=_scroll_action(scroll),
                **FETCH_OPTIONS,
            )
        except Exception as error:
            if _is_timeout(error):
                return _empty(kind, DiscoveryReason.TIMEOUT)
            return _empty(kind, DiscoveryReason.BROWSER_UNAVAILABLE)
        finally:
            try:
                with contextlib.suppress(Exception):
                    await session.__aexit__(None, None, None)
            finally:
                _decrement_active_sessions()

        logger.debug("tiktok discovery scroll ended kind=%s stop=%s", kind, scroll.stop)
        captured = getattr(response, "captured_xhr", None) or []
        result = _assemble(
            kind,
            request.limit,
            [_parse_entry(kind, entry) for entry in captured],
            captcha=scroll.captcha or _captcha_rendered(response),
            timed_out=scroll.timed_out,
            solved_after=scroll.solved_after,
        )
        return result.model_copy(update={"page_png": scroll.page_png})

"""X keyword search for footage: one signed-in browser session opens the search page for each
query and captures the page's own `SearchTimeline` response (verified live 2026-10-15, research
section 10). Only video tweets of their own author are kept; retweets are dropped.

Operator decision 2026-10-15 (option A): one session, so one lease and one unit of the X budget,
serves every query of a footage run, 5-10 s apart. A refusal (HTTP 400 or above, or a GraphQL
error body) stops the remaining queries; an empty timeline is an answer (ruling P3). Never
raises.
"""

from __future__ import annotations

import asyncio
import html
import random
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
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
)
from thoth_control_plane.acquisition.discovery import MAX_CAPTION, _empty
from thoth_control_plane.acquisition.models import (
    DiscoveredVideo,
    DiscoveryDrops,
    DiscoveryReason,
    DiscoveryResult,
)
from thoth_control_plane.acquisition.normalize import numeric_id, published_at_from_epoch

XHR_PATTERN = r"/SearchTimeline"
VIDEO_TYPES = frozenset({"video", "animated_gif"})
CREATED_AT = "%a %b %d %H:%M:%S %z %Y"
FETCH_TIMEOUT_MS = 60_000
X_PAUSE_SECONDS = (5.0, 10.0)


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
    if rest_id is None:
        return None
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
    try:
        return DiscoveredVideo(
            post_id=rest_id,
            owner_handle=owner,
            canonical_url=post_url(owner, rest_id),
            caption=display_text(html.unescape(text))[:MAX_CAPTION]
            if isinstance(text, str)
            else "",
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


def _answer(response: Any, limit: int) -> DiscoveryResult:
    """One search page's captured responses: an answer, a refusal (BLOCKED), or unknown
    (NO_DATA: nothing captured — a slow load, a changed page, a logged-out session)."""
    captured = getattr(response, "captured_xhr", None) or []
    if not captured:
        return _empty("keyword", DiscoveryReason.NO_DATA)
    roots: list[object] = []
    refused = False
    for entry in captured:
        status = getattr(entry, "status", None)
        if not isinstance(status, int):
            continue  # an unknown shape is neither a refusal nor an answer (ruling P3)
        if status >= 400:
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
        return _empty("keyword", DiscoveryReason.BLOCKED if refused else DiscoveryReason.NO_DATA)
    return parse_search(roots, limit)


def search_url(query: str) -> str:
    return f"{CANONICAL_BASE}/search?q={quote(query, safe='')}&f=video&src=typed_query"


@dataclass(frozen=True)
class XSearchBatch:
    found: dict[str, list[DiscoveredVideo]] = field(default_factory=dict)
    refused: bool = False
    unavailable: bool = False


class XSearchDiscovery:
    def __init__(
        self,
        session_factory: Callable[..., Any] = _default_session_factory,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        pause: Callable[[], float] = lambda: random.uniform(*X_PAUSE_SECONDS),
    ) -> None:
        self._session_factory = session_factory
        self._sleep = sleep
        self._pause = pause

    async def search_many(self, queries: Sequence[str], limit: int) -> XSearchBatch:
        try:
            session = self._session_factory(headless=True, max_pages=1, capture_xhr=XHR_PATTERN)
            active = await session.__aenter__()
        except Exception:
            return XSearchBatch(unavailable=True)
        _increment_active_sessions()
        found: dict[str, list[DiscoveredVideo]] = {}
        refused = unavailable = False
        try:
            for index, query in enumerate(queries):
                if index:
                    await self._sleep(self._pause())
                try:
                    response = await active.fetch(
                        search_url(query), network_idle=True, timeout=FETCH_TIMEOUT_MS
                    )
                except Exception:
                    unavailable = True  # a timeout or a dead browser: stop, keep what we have
                    break
                result = _answer(response, limit)
                if result.reason is DiscoveryReason.BLOCKED:
                    refused = True
                    break
                if result.reason is None:
                    found[query] = list(result.videos)
        finally:
            try:
                await session.__aexit__(None, None, None)
            except Exception:
                pass
            finally:
                _decrement_active_sessions()
        return XSearchBatch(found=found, refused=refused, unavailable=unavailable)

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

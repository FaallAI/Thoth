"""X profile discovery: the handle's own video tweets from its anonymous profile page.

Request only: one Scrapling GET of `/<handle>`, decoded from the page's seroval stream.
Anonymous pages serve about six recent tweets, so a profile often yields few videos; the
login feature that follows Stage 3d lengthens the timeline. Never raises; every failure is
a `DiscoveryResult` with a reason. A library with no caller until Stage 8.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from thoth_control_plane.acquisition.adapters.seroval import decode_scripts
from thoth_control_plane.acquisition.adapters.x import (
    CANONICAL_BASE,
    HANDLE,
    _get,
    author_of,
    page_tweets,
    post_url,
    tweet_engagement,
    tweet_photos,
    tweet_published,
    tweet_text,
    tweet_videos,
)
from thoth_control_plane.acquisition.discovery import MAX_CAPTION, _empty
from thoth_control_plane.acquisition.instagram_discovery import _reason, rank_videos
from thoth_control_plane.acquisition.models import (
    DiscoveredPhoto,
    DiscoveredVideo,
    DiscoveryDrops,
    DiscoveryReason,
    DiscoveryResult,
    ProfileDiscovery,
)
from thoth_control_plane.acquisition.normalize import numeric_id
from thoth_control_plane.acquisition.threads_service import RequestFetchError
from thoth_control_plane.acquisition.x_service import XRequestFetcher

logger = logging.getLogger(__name__)


# The shapes X has used for a repost's original; none was seen live in Stage 3c.
REPOST_PATHS = (
    ("retweeted_status_results",),
    ("retweeted_status_result",),
    ("legacy", "retweeted_status_result"),
)


def _repost(tweet: dict[str, Any]) -> bool:
    return any(isinstance(_get(tweet, *path), dict) for path in REPOST_PATHS)


def _video(tweet: dict[str, Any], owner: str) -> DiscoveredVideo | None:
    rest_id = numeric_id(tweet["rest_id"])
    if rest_id is None:
        return None
    try:
        return DiscoveredVideo(
            post_id=rest_id,
            owner_handle=owner,
            canonical_url=post_url(owner, rest_id),
            caption=(tweet_text(tweet) or "")[:MAX_CAPTION],
            published_at=tweet_published(tweet),
            engagement=tweet_engagement(tweet),
        )
    except ValueError:
        return None


def _photo(tweet: dict[str, Any], owner: str, images: list[str]) -> DiscoveredPhoto | None:
    rest_id = numeric_id(tweet["rest_id"])
    if rest_id is None:
        return None
    try:
        return DiscoveredPhoto(
            post_id=rest_id,
            owner_handle=owner,
            canonical_url=post_url(owner, rest_id),
            caption=(tweet_text(tweet) or "")[:MAX_CAPTION],
            published_at=tweet_published(tweet),
            image_urls=images[:20],
        )
    except ValueError:
        return None


def parse_profile(roots: Iterable[object], handle: str, limit: int) -> DiscoveryResult:
    tweets = page_tweets(roots)
    if not tweets:
        return _empty("profile", DiscoveryReason.NO_DATA)
    videos: list[DiscoveredVideo] = []
    photos: list[DiscoveredPhoto] = []
    photo_posts = invalid = 0
    for tweet in tweets:
        owner = author_of(tweet)
        # Another author's tweet (a repost's original, a quote) is not the handle's post.
        if owner is None or owner.lower() != handle.lower() or _repost(tweet):
            invalid += 1
            continue
        if not tweet_videos(tweet):
            photo_posts += 1
            images = tweet_photos(tweet)
            if images and (photo := _photo(tweet, owner, images)) is not None:
                photos.append(photo)
            continue
        video = _video(tweet, owner)
        if video is None:
            invalid += 1
            continue
        videos.append(video)
    return DiscoveryResult(
        kind="profile",
        videos=rank_videos(videos)[:limit],
        pages=1,
        exhausted=False,
        drops=DiscoveryDrops(photo_posts=photo_posts, invalid=invalid),
        photos=photos[:limit],
    )


class XProfileDiscovery:
    def __init__(self, fetcher: XRequestFetcher | None = None) -> None:
        self._fetcher = fetcher or XRequestFetcher()

    async def discover(self, request: ProfileDiscovery) -> DiscoveryResult:
        result = await self._collect(request)
        reason = result.reason.value if result.reason is not None else "none"
        logger.info(
            "x discovery finished kind=profile videos=%d photo_posts=%d invalid=%d reason=%s",
            len(result.videos),
            result.drops.photo_posts,
            result.drops.invalid,
            reason,
        )
        if result.reason is not None:
            logger.warning("x discovery stopped early kind=profile reason=%s", reason)
        return result

    async def _collect(self, request: ProfileDiscovery) -> DiscoveryResult:
        if HANDLE.fullmatch(request.handle) is None:
            # A handle X cannot have names no profile; skip the fetch.
            return _empty("profile", DiscoveryReason.NO_DATA)
        try:
            html = await self._fetcher.page(f"{CANONICAL_BASE}/{request.handle}")
        except RequestFetchError as error:
            return _empty("profile", _reason(error))
        try:
            return parse_profile(decode_scripts(html), request.handle, request.limit)
        except Exception:
            # Defense in depth: discovery never raises on an unforeseen page shape.
            return _empty("profile", DiscoveryReason.NO_DATA)

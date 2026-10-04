"""Instagram profile discovery: video posts from the anonymous 12-post profile grid.

Request only: one Scrapling GET of `/<handle>/`, then one GET per grid video's post page,
because the anonymous grid carries no like, view, or date fields. Never raises; every
failure is a `DiscoveryResult` with a reason. A library with no caller until Stage 8, like
TikTok discovery.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable, Sequence
from fractions import Fraction
from typing import Any

from thoth_control_plane.acquisition.adapters.instagram import (
    CANONICAL_BASE,
    CODE,
    HANDLE,
    engagement_of,
    find_instagram_media,
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
DETAIL_SPACING_SECONDS = 3.0


def _recency(video: DiscoveredVideo) -> str | None:
    # `YYYY-MM-DDTHH:MM:SSZ` strings sort chronologically.
    return video.published_at


SIGNALS: tuple[Callable[[DiscoveredVideo], int | str | None], ...] = (
    lambda video: video.engagement.get("like"),
    lambda video: video.engagement.get("play"),
    _recency,
)


def rank_videos(videos: Sequence[DiscoveredVideo]) -> list[DiscoveredVideo]:
    """Order by the mean of per-signal ranks: likes, views, and upload date.

    Each signal ranks the videos 0..1 by distinct value. A signal with fewer than two
    distinct values carries no order and is skipped; a video missing a signal the others
    have ranks lowest on it. Ties, and the no-signal case, keep the grid order.
    """
    # Exact fractions: equal scores must tie, so the grid order breaks them, not rounding.
    scores = [Fraction(0)] * len(videos)
    for signal in SIGNALS:
        values = [signal(video) for video in videos]
        levels = sorted({value for value in values if value is not None})
        if len(levels) < 2:
            continue
        for index, value in enumerate(values):
            if value is not None:
                scores[index] += Fraction(levels.index(value), len(levels) - 1)
    # Every video is scored over the same signals, so the sum orders like the mean.
    order = sorted(range(len(videos)), key=lambda index: -scores[index])
    return [videos[index] for index in order]


def _reason(error: RequestFetchError) -> DiscoveryReason:
    timeout = error.reason is AcquisitionReason.REQUEST_TIMEOUT
    return DiscoveryReason.TIMEOUT if timeout else DiscoveryReason.BLOCKED


def _with_detail(video: DiscoveredVideo, roots: list[object]) -> DiscoveredVideo:
    """Take likes, comments, and the upload date from the video's own post node."""
    code = str(video.canonical_url).rstrip("/").rsplit("/", 1)[-1]
    found = find_instagram_media(roots, code)
    if found is None:
        return video
    node = found[0]
    return video.model_copy(
        update={
            "engagement": engagement_of(node) or video.engagement,
            "published_at": published_at_from_epoch(node.get("taken_at")) or video.published_at,
        }
    )


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
    ranked = rank_videos(list(videos.values()))
    return DiscoveryResult(
        kind="profile",
        videos=ranked[: min(limit, GRID_SIZE)],
        pages=1,
        exhausted=False,
        drops=DiscoveryDrops(photo_posts=photo_posts, invalid=invalid),
    )


class InstagramProfileDiscovery:
    def __init__(
        self,
        fetcher: InstagramRequestFetcher | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._fetcher = fetcher or InstagramRequestFetcher()
        self._sleep = sleep

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
            return _empty("profile", _reason(error))
        roots = json_roots(texts)
        if login_required(roots):
            return _empty("profile", DiscoveryReason.BLOCKED)
        grid = parse_profile(roots, request.handle, GRID_SIZE)
        if grid.reason is not None:
            return grid
        videos, reason = await self._details(grid.videos)
        return grid.model_copy(
            update={"videos": rank_videos(videos)[: request.limit], "reason": reason}
        )

    async def _details(
        self, videos: list[DiscoveredVideo]
    ) -> tuple[list[DiscoveredVideo], DiscoveryReason | None]:
        """Each video's post page carries the signals the anonymous grid lacks.

        The first failure stops the remaining fetches: the rest keep their grid fields.
        """
        enriched: list[DiscoveredVideo] = []
        for index, video in enumerate(videos):
            await self._sleep(DETAIL_SPACING_SECONDS)
            try:
                roots = json_roots(await self._fetcher.fetch(str(video.canonical_url)))
            except RequestFetchError as error:
                return enriched + videos[index:], _reason(error)
            if login_required(roots):
                return enriched + videos[index:], DiscoveryReason.BLOCKED
            enriched.append(_with_detail(video, roots))
        return enriched, None

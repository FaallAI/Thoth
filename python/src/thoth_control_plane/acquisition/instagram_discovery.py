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

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

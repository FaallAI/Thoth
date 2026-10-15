"""YouTube keyword search for footage: yt-dlp's `ytsearch`, flat, then a detail extract of the
five most viewed results (likes, upload time, duration). Never raises."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from thoth_control_plane.acquisition.adapters.youtube import channel_candidates, video_url
from thoth_control_plane.acquisition.discovery import _empty
from thoth_control_plane.acquisition.models import (
    DiscoveredVideo,
    DiscoveryDrops,
    DiscoveryReason,
    DiscoveryResult,
    KeywordDiscovery,
)
from thoth_control_plane.acquisition.youtube_discovery import (
    DETAIL_SPACING_SECONDS,
    _reason,
    _video,
)
from thoth_control_plane.acquisition.youtube_service import YtDlpClient, YtDlpError

SEARCH_RESULTS = 8
DETAILS = 5


class YouTubeSearchDiscovery:
    def __init__(
        self,
        client: YtDlpClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client or YtDlpClient()
        self._sleep = sleep

    async def discover(self, request: KeywordDiscovery) -> DiscoveryResult:
        try:
            listing = await self._client.listing(
                f"ytsearch{SEARCH_RESULTS}:{request.query}", SEARCH_RESULTS
            )
        except YtDlpError as error:
            return _empty("keyword", _reason(error))
        candidates = channel_candidates([listing], DETAILS)
        if not candidates:
            return _empty("keyword", DiscoveryReason.NO_DATA)
        videos: list[DiscoveredVideo] = []
        invalid = 0
        last_error: YtDlpError | None = None
        for index, video_id in enumerate(candidates):
            if index:
                await self._sleep(DETAIL_SPACING_SECONDS)
            try:
                info = await self._client.extract(video_url(video_id), comments=False)
            except YtDlpError as error:
                # One private or age-gated video says nothing about the search itself.
                last_error = error
                invalid += 1
                continue
            video = _video(info, video_id)
            if video is None:
                invalid += 1
                continue
            videos.append(video)
        return DiscoveryResult(
            kind="keyword",
            videos=videos[: request.limit],
            pages=1,
            exhausted=False,
            drops=DiscoveryDrops(invalid=invalid),
            reason=_reason(last_error) if last_error is not None and not videos else None,
        )

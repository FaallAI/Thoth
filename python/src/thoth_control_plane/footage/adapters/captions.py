"""A long video's captions in one language as json3, without downloading the video: yt-dlp's
info dict names the caption URLs; the json3 one is fetched (footage library spec 4.4). The same
info dict carries the chapters and the Most Replayed heatmap (spec 2026-11-27, 5.2)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import httpx

from thoth_control_plane.acquisition.youtube_service import YtDlpClient, YtDlpError
from thoth_control_plane.footage.moments import LongVideoHints, parse_chapters, parse_heatmap

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 20.0
# YouTube rate-limits caption tracks in bursts; one paced retry (live wf_a91d3f0f).
RETRY_SECONDS = 8.0
RATE_LIMITED = 429


def _json3_url(info: dict[str, Any], language: str) -> str | None:
    """The json3 track nearest the language: the language, its variants ("id-orig"), then
    English and its variants; within one, auto captions before uploaded subtitles."""
    wanted: list[Callable[[str], bool]] = [
        lambda key: key == language,
        lambda key: key.startswith(f"{language}-"),
        lambda key: key == "en",
        lambda key: key.startswith("en-"),
    ]
    for matches in wanted:
        for source in ("automatic_captions", "subtitles"):
            languages = info.get(source)
            for key, tracks in languages.items() if isinstance(languages, dict) else []:
                if not isinstance(key, str) or not matches(key):
                    continue
                for track in tracks if isinstance(tracks, list) else []:
                    if isinstance(track, dict) and track.get("ext") == "json3" and track.get("url"):
                        return str(track["url"])
    return None


class YtDlpCaptionFetcher:
    def __init__(
        self,
        client: YtDlpClient,
        http: httpx.AsyncClient | None = None,
        retry_seconds: float = RETRY_SECONDS,
    ) -> None:
        self._client = client
        self._http = http
        self._retry_seconds = retry_seconds

    async def captions(self, url: str, language: str) -> bytes | None:
        return (await self.hints(url, language)).captions

    async def hints(self, url: str, language: str) -> LongVideoHints:
        """One metadata call (no video bytes): captions, chapters and heatmap."""
        try:
            info = await self._client.extract(url, comments=False)
        except YtDlpError:
            logger.warning("footage captions unavailable step=extract")
            return LongVideoHints()
        chapters = parse_chapters(info.get("chapters"))
        heatmap = parse_heatmap(info.get("heatmap"))
        track = _json3_url(info, language)
        if track is None:
            logger.warning("footage captions missing language=%s", language)
            return LongVideoHints(None, chapters, heatmap)
        return LongVideoHints(await self._fetch(track), chapters, heatmap)

    async def _fetch(self, track: str) -> bytes | None:
        http = self._http or httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
        try:
            response = await http.get(track, timeout=TIMEOUT_SECONDS)
            if response.status_code == RATE_LIMITED:
                logger.warning("footage captions refused status=429; retrying once")
                await asyncio.sleep(self._retry_seconds)
                response = await http.get(track, timeout=TIMEOUT_SECONDS)
            if response.status_code != 200:
                logger.warning("footage captions refused status=%d", response.status_code)
                return None
            return response.content
        except httpx.HTTPError:
            logger.warning("footage captions unavailable step=fetch")
            return None
        finally:
            if self._http is None:
                await http.aclose()

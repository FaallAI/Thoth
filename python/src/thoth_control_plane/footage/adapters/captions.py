"""A long video's captions in one language as json3, without downloading the video: yt-dlp's
info dict names the caption URLs; the json3 one is fetched (footage library spec 4.4)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from thoth_control_plane.acquisition.youtube_service import YtDlpClient, YtDlpError

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 20.0


def _json3_url(info: dict[str, Any], language: str) -> str | None:
    for key in ("automatic_captions", "subtitles"):
        tracks = (info.get(key) or {}).get(language) or []
        for track in tracks if isinstance(tracks, list) else []:
            if isinstance(track, dict) and track.get("ext") == "json3" and track.get("url"):
                return str(track["url"])
    return None


class YtDlpCaptionFetcher:
    def __init__(self, client: YtDlpClient, http: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._http = http

    async def captions(self, url: str, language: str) -> bytes | None:
        try:
            info = await self._client.extract(url, comments=False)
        except YtDlpError:
            logger.warning("footage captions unavailable step=extract")
            return None
        track = _json3_url(info, language)
        if track is None:
            logger.warning("footage captions missing language=%s", language)
            return None
        http = self._http or httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
        try:
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

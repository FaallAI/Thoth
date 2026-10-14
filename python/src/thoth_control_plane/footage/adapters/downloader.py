"""Download a footage clip, or only its window, with yt-dlp; directly, never through an
account proxy (spec 2026-10-14, decision 7). The file lands through `.part` and `os.replace`."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

FORMAT = "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/b[ext=mp4]/b"
TIMEOUT_SECONDS = 75.0


class ClipError(Exception):
    """The clip could not be downloaded: a media failure of this candidate only."""


def _run_yt_dlp(url: str, options: dict[str, Any]) -> None:
    from yt_dlp import YoutubeDL

    with YoutubeDL(options) as ydl:
        ydl.download([url])


class YtDlpClipDownloader:
    def __init__(self, ffmpeg: str, timeout: float = TIMEOUT_SECONDS) -> None:
        self._ffmpeg = shutil.which(ffmpeg) or ffmpeg
        self._timeout = timeout

    async def download(self, url: str, window: tuple[float, float] | None, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="thoth-footage-", dir=target.parent) as scratch:
            options: dict[str, Any] = {
                "format": FORMAT,
                "merge_output_format": "mp4",
                "outtmpl": str(Path(scratch) / "clip.%(ext)s"),
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "socket_timeout": 20,
                "ffmpeg_location": self._ffmpeg,
            }
            if window is not None:
                from yt_dlp.utils import download_range_func

                options["download_ranges"] = download_range_func(None, [window])
                options["force_keyframes_at_cuts"] = True
            try:
                # ponytail: a timed-out download finishes in its thread; the scratch directory
                # is removed with it. Bounded by socket_timeout and the window's size.
                await asyncio.wait_for(asyncio.to_thread(_run_yt_dlp, url, options), self._timeout)
            except Exception as error:
                raise ClipError(type(error).__name__) from None
            produced = sorted(Path(scratch).glob("clip.*"))
            if not produced or produced[0].stat().st_size == 0:
                raise ClipError("no file")
            part = target.with_name(target.name + ".part")
            shutil.move(produced[0], part)
            os.replace(part, target)
        return target

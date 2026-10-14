"""Download a footage clip, or only its window, with yt-dlp; directly, never through an
account proxy (spec 2026-10-14, decision 7). The file lands through `.part` and `os.replace`."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.youtube_service import STOP_GRACE_SECONDS

FORMAT = "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/b[ext=mp4]/b"
TIMEOUT_SECONDS = 75.0


class ClipError(Exception):
    """The clip could not be downloaded: a media failure of this candidate only."""


class _Stopped(Exception):
    """Raised from a yt-dlp hook to end a download its caller abandoned."""


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
        stop = threading.Event()

        def check(_status: object) -> None:
            if stop.is_set():
                raise _Stopped

        with tempfile.TemporaryDirectory(
            prefix="thoth-footage-", dir=target.parent, ignore_cleanup_errors=True
        ) as scratch:
            options: dict[str, Any] = {
                "format": FORMAT,
                "merge_output_format": "mp4",
                "outtmpl": str(Path(scratch) / "clip.%(ext)s"),
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "socket_timeout": 20,
                "proxy": "",  # direct, even when the environment sets HTTP(S)_PROXY
                "progress_hooks": [check],
                "postprocessor_hooks": [check],
                "ffmpeg_location": self._ffmpeg,
            }
            if window is not None:
                from yt_dlp.utils import download_range_func

                options["download_ranges"] = download_range_func(None, [window])
                options["force_keyframes_at_cuts"] = True
            work = asyncio.ensure_future(asyncio.to_thread(_run_yt_dlp, url, options))
            # A stopped download ends in `_Stopped`; that end is expected, so it is not logged.
            work.add_done_callback(lambda done: done.cancelled() or done.exception())
            try:
                await asyncio.wait_for(asyncio.shield(work), self._timeout)
            except BaseException as error:
                # yt-dlp cannot be cancelled: stop it at its next progress or postprocessor
                # hook and wait for the thread, so nothing writes while the scratch is removed.
                # ponytail: the stop lands at the next hook, bounded by the grace; a thread that
                # outlives it is abandoned, its scratch directory removed best-effort.
                stop.set()
                await asyncio.wait({work}, timeout=STOP_GRACE_SECONDS)
                if isinstance(error, Exception):
                    raise ClipError(type(error).__name__) from None
                raise
            produced = Path(scratch) / "clip.mp4"
            if not produced.is_file() or produced.stat().st_size == 0:
                raise ClipError("no file")
            part = target.with_name(target.name + ".part")
            shutil.move(produced, part)
            os.replace(part, target)
        return target

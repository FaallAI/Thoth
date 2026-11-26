"""Download a footage clip, or only its window, with yt-dlp. The download is direct (spec
2026-10-14, decision 7); only after a TikTok or a blocked YouTube download fails does one retry
go through a leased account and proxy (spec 2026-11-27, 3.2). The file lands through `.part` and
`os.replace`."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.adapters.tikwm import TikWmError
from thoth_control_plane.acquisition.platforms import platform_of
from thoth_control_plane.acquisition.youtube_service import STOP_GRACE_SECONDS, _Silent

FORMAT = "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/b[ext=mp4]/b"
TIMEOUT_SECONDS = 75.0
#: With a fallback, the direct attempt leaves at least 35 s of the clip's budget for it.
DIRECT_FALLBACK_CAP_SECONDS = 40.0
MIN_FALLBACK_SECONDS = 10.0
#: The YouTube causes a leased account and proxy can get past; others fail the same way.
BLOCKED_CAUSES = frozenset({"bot_check", "http_403", "http_429"})

#: (platform, scratch) -> extra yt-dlp options for one leased attempt, or None for no lease.
#: A `ClipError` raised from its body carries the attempt's cause.
FallbackSession = Callable[[str, Path], AbstractAsyncContextManager[dict[str, Any] | None]]


class ClipError(Exception):
    """The clip could not be downloaded: a media failure of this candidate only. Its message is
    a cause with no URL (spec 10.8)."""


# yt-dlp's messages carry the URL; the cause keeps only what they say (spec 10.8 and 10.12).
CAUSES = (
    ("confirm you", "bot_check"),
    ("http error 403", "http_403"),
    ("http error 429", "http_429"),
)


def cause_of(error: BaseException) -> str:
    text = str(error).lower()
    return next((cause for marker, cause in CAUSES if marker in text), type(error).__name__)


class _Stopped(Exception):
    """Raised from a yt-dlp hook to end a download its caller abandoned."""


def _run_yt_dlp(url: str, options: dict[str, Any]) -> None:
    from yt_dlp import YoutubeDL

    with YoutubeDL(options) as ydl:
        ydl.download([url])


class YtDlpClipDownloader:
    def __init__(
        self,
        ffmpeg: str,
        timeout: float = TIMEOUT_SECONDS,
        resolve_tiktok: Callable[[str], Awaitable[str]] | None = None,
        fallback_session: FallbackSession | None = None,
    ) -> None:
        self._ffmpeg = shutil.which(ffmpeg) or ffmpeg
        self._timeout = timeout
        self._resolve_tiktok = resolve_tiktok
        self._fallback_session = fallback_session

    async def download(self, url: str, window: tuple[float, float] | None, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        # One budget for both attempts: the clip's checks still need time after the download.
        deadline = time.monotonic() + self._timeout
        platform = platform_of(url)
        fallback = self._fallback_session if platform in ("tiktok", "youtube") else None
        cap = DIRECT_FALLBACK_CAP_SECONDS if fallback is not None else self._timeout
        try:
            direct = url
            if platform == "tiktok" and self._resolve_tiktok is not None:
                direct = await self._tiktok_media(url)
            with _scratch(target) as scratch:
                timeout = min(cap, deadline - time.monotonic())
                return await self._attempt(direct, window, scratch, target, timeout)
        except ClipError as error:
            failed = error
        remaining = deadline - time.monotonic()
        if (
            fallback is None
            or remaining < MIN_FALLBACK_SECONDS
            or (platform == "youtube" and str(failed) not in BLOCKED_CAUSES)
        ):
            raise failed
        # Its own scratch: an abandoned direct thread can never write into this attempt.
        with _scratch(target) as scratch:
            async with fallback(platform, scratch) as extra:
                if extra is None:
                    raise failed
                return await self._attempt(url, window, scratch, target, remaining, extra)

    async def _tiktok_media(self, url: str) -> str:
        """yt-dlp gets 403 on TikTok pages from this host; the direct URL is never logged."""
        assert self._resolve_tiktok is not None
        try:
            return await self._resolve_tiktok(url)
        except TikWmError as error:
            raise ClipError(f"tikwm_{error.code}") from None
        except Exception as error:
            raise ClipError(type(error).__name__) from None

    async def _attempt(
        self,
        url: str,
        window: tuple[float, float] | None,
        scratch: Path,
        target: Path,
        timeout: float,
        extra: dict[str, Any] | None = None,
    ) -> Path:
        stop = threading.Event()

        def check(_status: object) -> None:
            if stop.is_set():
                raise _Stopped

        options: dict[str, Any] = {
            "format": FORMAT,
            "merge_output_format": "mp4",
            "outtmpl": str(scratch / "clip.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "noprogress": True,
            "logger": _Silent(),
            "no_warnings": True,
            "socket_timeout": 20,
            "proxy": "",  # direct, even when the environment sets HTTP(S)_PROXY
            "js_runtimes": {"bun": {}},  # YouTube JS challenges, as acquisition solves them
            "progress_hooks": [check],
            "postprocessor_hooks": [check],
            "ffmpeg_location": self._ffmpeg,
            **(extra or {}),
        }
        if window is not None:
            from yt_dlp.utils import download_range_func

            options["download_ranges"] = download_range_func(None, [window])
            options["force_keyframes_at_cuts"] = True
        work = asyncio.ensure_future(asyncio.to_thread(_run_yt_dlp, url, options))
        # A stopped download ends in `_Stopped`; that end is expected, so it is not logged.
        work.add_done_callback(lambda done: done.cancelled() or done.exception())
        try:
            await asyncio.wait_for(asyncio.shield(work), timeout)
        except BaseException as error:
            # yt-dlp cannot be cancelled: stop it at its next progress or postprocessor
            # hook and wait for the thread, so nothing writes while the scratch is removed.
            # ponytail: the stop lands at the next hook, bounded by the grace; a thread that
            # outlives it is abandoned, its scratch directory removed best-effort.
            stop.set()
            await asyncio.wait({work}, timeout=STOP_GRACE_SECONDS)
            if isinstance(error, Exception):
                raise ClipError(cause_of(error)) from None
            raise
        produced = scratch / "clip.mp4"
        if not produced.is_file() or produced.stat().st_size == 0:
            raise ClipError("no file")
        part = target.with_name(target.name + ".part")
        shutil.move(produced, part)
        os.replace(part, target)
        return target


@contextmanager
def _scratch(target: Path) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(
        prefix="thoth-footage-", dir=target.parent, ignore_cleanup_errors=True
    ) as scratch:
        yield Path(scratch)

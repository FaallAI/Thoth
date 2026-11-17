"""A video's preview proxy, built on first need and kept beside the asset (spec 2026-11-18).

Like a glance, a proxy lives under its own prefix (``previews/``), which the upload sweep never
lists, and an asset's bytes never change, so a built proxy is kept for good. A build runs in the
background of this process, one at a time; a failed one keeps nothing and is not tried again in
this process. The Player plays the original until the proxy exists; nothing ever fails for it.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from thoth_control_plane.infrastructure.preview_proxy_builder import build_preview_proxy

logger = logging.getLogger(__name__)

Builder = Callable[[str, str, str, Path], Awaitable[None]]


def proxy_location(project_id: str, asset_id: str) -> str:
    return f"previews/{project_id}/{asset_id}.v1.mp4"


class PreviewProxyService:
    def __init__(self, media, ffmpeg: str, *, build: Builder = build_preview_proxy) -> None:
        self._media = media
        self._ffmpeg = ffmpeg
        self._build = build
        self._slot = asyncio.Semaphore(1)  # ponytail: one ffmpeg per API process
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._failed: set[str] = set()

    async def ready(self, project_id: str, asset_id: str) -> bool:
        """Whether the proxy is kept; an unreachable store counts as not ready."""
        try:
            await asyncio.to_thread(self._media.size, proxy_location(project_id, asset_id))
        except Exception:
            return False
        return True

    def request(self, project_id: str, asset_id: str, location: str, media_type: str) -> None:
        """Start a build in the background unless one runs, failed, or is kept already."""
        key = proxy_location(project_id, asset_id)
        if key in self._failed or key in self._tasks:
            return
        task = asyncio.get_running_loop().create_task(self._make(key, location, media_type))
        self._tasks[key] = task
        task.add_done_callback(lambda _: self._tasks.pop(key, None))

    async def idle(self) -> None:
        """Wait for every build this process started (tests, shutdown)."""
        while self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def _make(self, key: str, location: str, media_type: str) -> None:
        async with self._slot:
            try:
                await asyncio.to_thread(self._media.size, key)
                return  # kept already, maybe by another process
            except Exception:
                pass
            try:
                source = await asyncio.to_thread(self._media.probe_source, location)
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / "proxy.mp4"
                    await self._build(self._ffmpeg, source, media_type, path)
                    await asyncio.to_thread(self._media.put_file, key, path)
            except Exception as error:
                self._failed.add(key)
                logger.warning("preview proxy failed for %s: %s", key, type(error).__name__)
                return
            logger.info("preview proxy kept at %s", key)

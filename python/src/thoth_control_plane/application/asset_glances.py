"""An asset's glance, built on first request and cached beside the asset (Tier 3b).

``EditorAssetService`` never opens an artifact; like the preview route, this service does, so it
stays apart. A glance lives under ``glance/``, which the upload sweep never lists. An asset's
bytes never change, so a built glance is kept for good; a failed build is never kept.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from thoth_control_plane.domain.asset_glance import AssetGlance
from thoth_control_plane.infrastructure.asset_glance_builder import (
    GlanceBuildFailed,
    GlanceToolMissing,
    build_glance,
)
from thoth_control_plane.infrastructure.media_store import (
    MediaLocatorInvalid,
    MediaStoreUnavailable,
    MediaUnavailable,
)

if TYPE_CHECKING:
    from thoth_control_plane.application.editor_assets import EditorAssetService
    from thoth_control_plane.domain.editor_assets import EditorAsset

logger = logging.getLogger(__name__)

#: ffmpeg runs at most this many glance builds at once in one process.
GLANCE_SLOTS = 2

Builder = Callable[[str, str, "EditorAsset"], Awaitable[AssetGlance]]


class GlanceUnavailable(Exception):
    """No glance now; ``code`` says why. The clip then draws as it always did."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def glance_location(project_id: str, asset_id: str) -> str:
    return f"glance/{project_id}/{asset_id}.v1.json"


class AssetGlanceService:
    def __init__(
        self,
        assets: EditorAssetService,
        media,
        ffmpeg: str,
        *,
        build: Builder = build_glance,
    ) -> None:
        self._assets = assets
        self._media = media
        self._ffmpeg = ffmpeg
        self._build = build
        self._slots = asyncio.Semaphore(GLANCE_SLOTS)

    async def glance(self, project_id: str, asset_id: str) -> AssetGlance:
        """The asset's glance; raises ``EditorAssetNotFound`` or ``GlanceUnavailable``."""
        record = await self._assets.get_ready_record(project_id, asset_id)
        location = glance_location(project_id, asset_id)
        cached = await asyncio.to_thread(self._read, location)
        if cached is not None:
            return cached
        async with self._slots:
            # A build that waited for a slot may find another request already made it.
            cached = await asyncio.to_thread(self._read, location)
            if cached is not None:
                return cached
            try:
                source = await asyncio.to_thread(self._media.probe_source, record.artifact_location)
                glance = await self._build(self._ffmpeg, source, record.asset)
            except GlanceToolMissing as error:
                logger.error("ffmpeg could not run for a glance")
                raise GlanceUnavailable("ffmpeg_unavailable") from error
            except GlanceBuildFailed as error:
                logger.warning("glance build failed for %s", asset_id)
                raise GlanceUnavailable("glance_failed") from error
            except (MediaUnavailable, MediaLocatorInvalid, MediaStoreUnavailable) as error:
                raise GlanceUnavailable("media_store_unavailable") from error
            try:
                await asyncio.to_thread(self._write, location, glance)
            except (MediaStoreUnavailable, MediaLocatorInvalid, OSError):
                # The glance is still good for this answer; the next request builds it again.
                logger.warning("glance for %s was built but not kept", asset_id)
            return glance

    def _read(self, location: str) -> AssetGlance | None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "glance.json"
            try:
                self._media.fetch(location, path)
            except (MediaUnavailable, MediaLocatorInvalid):
                return None
            except MediaStoreUnavailable as error:
                raise GlanceUnavailable("media_store_unavailable") from error
            try:
                return AssetGlance.model_validate_json(path.read_bytes())
            except ValidationError:
                logger.warning("a stored glance at %s did not decode; it is built again", location)
                return None

    def _write(self, location: str, glance: AssetGlance) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "glance.json"
            path.write_text(glance.model_dump_json(), encoding="utf-8")
            self._media.put_file(location, path)

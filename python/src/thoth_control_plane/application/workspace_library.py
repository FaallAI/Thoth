"""A workspace's own asset library: upload, import, delete, and copy into a draft.

Spec 2026-11-13. Items belong to one workspace and never reach another. Uploads pass the same
checks as a draft's uploads (`UPLOAD_TYPES`, signature, probe) and carry no licence gate: they
are the uploader's own files. Short audio becomes an SFX and is loudness-normalised, so a meme
stinger never drowns the narrator. A draft that uses an item gets its own copy, so deleting the
item from the library never breaks that draft.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import tempfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Any, Literal
from uuid import uuid4

from thoth_control_plane.application.editor_asset_ports import EditorAssetMediaInvalid
from thoth_control_plane.application.editor_asset_uploads import (
    UPLOAD_MAX_BYTES,
    UPLOAD_TYPES,
    MediaProbe,
    described_asset,
)
from thoth_control_plane.application.sfx_library import _loudnorm, _sha256
from thoth_control_plane.domain.editor_assets import CANVAS_FPS, EditorAsset
from thoth_control_plane.domain.workspace_assets import (
    NAME_MAX,
    LibraryKind,
    WorkspaceAsset,
    WorkspaceAssetRecord,
)

logger = logging.getLogger(__name__)

#: Audio up to this long is a sound effect; longer audio is backsound (spec 2026-11-13).
SFX_MAX_SECONDS = 15.0
_SUFFIX_TYPES = {upload.suffix: media_type for media_type, upload in UPLOAD_TYPES.items()}
_SUFFIX_TYPES[".jpeg"] = "image/jpeg"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class LibraryUnavailable(Exception):
    """The editor database or media storage is not configured or not answering."""


class LibraryItemNotFound(Exception):
    """No such item in this workspace; another workspace's item answers the same way."""


def library_kind(
    upload_kind: Literal["image", "video", "audio"], duration_seconds: float | None
) -> LibraryKind:
    if upload_kind == "image":
        return "image"
    if upload_kind == "video":
        return "clip"
    return "sfx" if (duration_seconds or 0.0) <= SFX_MAX_SECONDS else "backsound"


def display_name(file_name: str) -> str:
    """The name shown for an upload: its last path segment, without extension or controls."""
    base = PureWindowsPath(file_name.replace("/", "\\")).name
    stem = base.rsplit(".", 1)[0] if "." in base else base
    cleaned = _CONTROL.sub("", stem).strip()[:NAME_MAX].strip()
    return cleaned or "untitled"


async def _file_chunks(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as handle:
        while chunk := await asyncio.to_thread(handle.read, 1 << 20):
            yield chunk


class WorkspaceLibraryService:
    """One workspace's library; `artifacts` is None where only listing and copying run."""

    def __init__(
        self,
        repository: Any | None,
        artifacts: Any | None,
        probe: MediaProbe,
        media: Any | None,
        assets: Any | None,
        ffmpeg: Path,
        *,
        max_bytes: int = UPLOAD_MAX_BYTES,
    ) -> None:
        self._repository = repository
        self._artifacts = artifacts
        self._probe = probe
        self._media = media
        self._assets = assets
        self._ffmpeg = ffmpeg
        self._max_bytes = max_bytes

    def _require(self) -> Any:
        if self._repository is None or self._media is None:
            raise LibraryUnavailable()
        return self._repository

    async def list(self, workspace_id: str) -> list[WorkspaceAsset]:
        return await self._require().list(workspace_id)

    async def update(
        self,
        workspace_id: str,
        asset_id: str,
        *,
        name: str | None = None,
        labels: dict[str, object] | None = None,
        kind: LibraryKind | None = None,
    ) -> WorkspaceAsset:
        clean = None if name is None else display_name(name + ".x")
        updated = await self._require().update(
            workspace_id, asset_id, name=clean, labels=labels, kind=kind
        )
        if updated is None:
            raise LibraryItemNotFound()
        return updated

    async def upload(
        self,
        workspace_id: str,
        media_type: str,
        chunks: AsyncIterator[bytes],
        file_name: str,
        labels: dict[str, object] | None = None,
    ) -> WorkspaceAsset:
        upload_type = UPLOAD_TYPES.get(media_type)
        if upload_type is None:
            raise EditorAssetMediaInvalid("unsupported_media_type")
        repository = self._require()
        if self._artifacts is None:
            raise LibraryUnavailable()
        asset_id = f"lib_{uuid4().hex}"
        received = await self._artifacts.receive_upload(
            asset_id=asset_id, chunks=chunks, max_bytes=self._max_bytes
        )
        location: str | None = None
        try:
            if not upload_type.signature(received.head):
                raise EditorAssetMediaInvalid("media_type_mismatch")
            facts = described_asset(
                asset_id=f"asset_{asset_id.removeprefix('lib_')}",
                project_id=workspace_id,
                media_type=media_type,
                kind=upload_type.kind,
                checksum=received.checksum,
                report=await self._probe(received.path),
            )
            seconds = (
                None if facts.duration_in_frames is None else facts.duration_in_frames / CANVAS_FPS
            )
            kind = library_kind(upload_type.kind, seconds)
            with tempfile.TemporaryDirectory() as work:
                source, checksum, stored_type, suffix = (
                    received.path,
                    received.checksum,
                    media_type,
                    upload_type.suffix,
                )
                if kind == "sfx":
                    source = Path(work) / f"{asset_id}.mp3"
                    await asyncio.to_thread(_loudnorm, self._ffmpeg, received.path, source)
                    checksum, stored_type, suffix = _sha256(source), "audio/mpeg", ".mp3"
                location = f"library/{workspace_id}/{asset_id}{suffix}"
                await asyncio.to_thread(self._media.put_file, location, source)
            asset = WorkspaceAsset(
                asset_id=asset_id,
                workspace_id=workspace_id,
                kind=kind,
                name=display_name(file_name),
                labels=dict(labels or {}),
                media_type=stored_type,
                checksum=checksum,
                duration_seconds=seconds,
                width=facts.width,
                height=facts.height,
                has_audio=facts.has_audio,
                created_at=datetime.now(UTC),
            )
            kept = await repository.add(WorkspaceAssetRecord(asset=asset, location=location))
            if kept.asset.asset_id != asset_id:
                # The same file is already in this workspace: keep the one stored first.
                await asyncio.to_thread(self._media.delete, location)
            logger.info(
                "library upload workspace=%s asset=%s kind=%s new=%s",
                workspace_id,
                kept.asset.asset_id,
                kind,
                kept.asset.asset_id == asset_id,
            )
            return kept.asset
        except BaseException:
            if location is not None:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(self._media.delete, location)
            raise
        finally:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self._artifacts.discard, received.location)

    async def import_file(
        self, workspace_id: str, path: Path, labels: dict[str, object]
    ) -> WorkspaceAsset:
        media_type = _SUFFIX_TYPES.get(path.suffix.lower())
        if media_type is None:
            raise EditorAssetMediaInvalid("unsupported_media_type")
        return await self.upload(workspace_id, media_type, _file_chunks(path), path.name, labels)

    async def delete(self, workspace_id: str, asset_id: str) -> bool:
        location = await self._require().delete(workspace_id, asset_id)
        if location is None:
            return False
        try:
            await asyncio.to_thread(self._media.delete, location)
        except Exception:
            logger.warning("library delete left its object behind workspace=%s", workspace_id)
        logger.info("library delete workspace=%s asset=%s", workspace_id, asset_id)
        return True

    async def add_to_project(
        self, workspace_id: str, project_id: str, asset_id: str
    ) -> EditorAsset:
        record = await self._require().get(workspace_id, asset_id)
        if record is None:
            raise LibraryItemNotFound()
        if self._assets is None:
            raise LibraryUnavailable()
        upload_type = UPLOAD_TYPES[record.asset.media_type]
        return await self._assets.ensure_project_asset(
            project_id,
            location=record.location,
            checksum=record.asset.checksum,
            media_type=record.asset.media_type,
            kind=upload_type.kind,
            suffix=upload_type.suffix,
        )

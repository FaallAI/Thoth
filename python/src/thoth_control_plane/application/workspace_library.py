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
import json
import logging
import re
import tempfile
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Any, Literal
from uuid import uuid4

from thoth_control_plane.application.editor_asset_ports import (
    EditorAssetMediaInvalid,
    EditorAssetUploadTooLarge,
)
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


class LibraryKindRefused(Exception):
    """The kind does not fit the media: an image stays an image, a video a clip, and only
    short audio, which was loudness-normalised when it arrived, may be an SFX."""


def allowed_kinds(media_type: str, duration_seconds: float | None) -> set[LibraryKind]:
    family = UPLOAD_TYPES[media_type].kind if media_type in UPLOAD_TYPES else None
    if family == "image":
        return {"image"}
    if family == "video":
        return {"clip"}
    if family == "audio":
        short = (duration_seconds or 0.0) <= SFX_MAX_SECONDS
        return {"sfx", "backsound"} if short else {"backsound"}
    return set()


def library_kind(
    upload_kind: Literal["image", "video", "audio"], duration_seconds: float | None
) -> LibraryKind:
    if upload_kind == "image":
        return "image"
    if upload_kind == "video":
        return "clip"
    return "sfx" if (duration_seconds or 0.0) <= SFX_MAX_SECONDS else "backsound"


def clean_name(text: str) -> str:
    """A name as typed, without controls, trimmed to `NAME_MAX`; slashes and dots stay."""
    return _CONTROL.sub("", text).strip()[:NAME_MAX].strip() or "untitled"


def display_name(file_name: str) -> str:
    """The name shown for an upload: its last path segment, without extension or controls."""
    base = PureWindowsPath(file_name.replace("/", "\\")).name
    return clean_name(base.rsplit(".", 1)[0] if "." in base else base)


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

    async def _repo(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """One repository call; a database failure reads as the library being unavailable."""
        call = getattr(self._require(), method)
        try:
            return await call(*args, **kwargs)
        except Exception as error:
            logger.warning("library store unavailable: %s", type(error).__name__)
            raise LibraryUnavailable() from error

    async def list(self, workspace_id: str) -> list[WorkspaceAsset]:
        return await self._repo("list", workspace_id)

    async def stored(self, workspace_id: str, asset_id: str) -> tuple[WorkspaceAssetRecord, int]:
        """One item with its stored size, for streaming its media back to the page."""
        record = await self._repo("get", workspace_id, asset_id)
        if record is None:
            raise LibraryItemNotFound()
        try:
            size = (await asyncio.to_thread(self._media.stat, record.location)).size_bytes
        except Exception as error:
            raise LibraryUnavailable() from error
        return record, size

    def read(self, location: str, start: int, end: int | None) -> Iterator[bytes]:
        return self._media.open_range(location, start, end)

    async def update(
        self,
        workspace_id: str,
        asset_id: str,
        *,
        name: str | None = None,
        labels: dict[str, object] | None = None,
        kind: LibraryKind | None = None,
    ) -> WorkspaceAsset:
        clean = None if name is None else clean_name(name)
        if kind is not None:
            record = await self._repo("get", workspace_id, asset_id)
            if record is None:
                raise LibraryItemNotFound()
            if kind not in allowed_kinds(record.asset.media_type, record.asset.duration_seconds):
                raise LibraryKindRefused()
        updated = await self._repo(
            "update", workspace_id, asset_id, name=clean, labels=labels, kind=kind
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
        self._require()
        if self._artifacts is None:
            raise LibraryUnavailable()
        asset_id = f"lib_{uuid4().hex}"
        try:
            received = await self._artifacts.receive_upload(
                asset_id=asset_id, chunks=chunks, max_bytes=self._max_bytes
            )
        except EditorAssetUploadTooLarge:
            raise
        except Exception as error:
            raise LibraryUnavailable() from error
        location: str | None = None
        adding = False
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
            adding = True
            kept = await self._repo("add", WorkspaceAssetRecord(asset=asset, location=location))
            adding = False
            if kept.asset.asset_id != asset_id:
                # The same file is already in this workspace: keep the one stored first. A
                # leftover object only costs storage, so the upload still succeeds.
                try:
                    await asyncio.to_thread(self._media.delete, location)
                except Exception:
                    logger.warning("library dedupe left an object workspace=%s", workspace_id)
            logger.info(
                "library upload workspace=%s asset=%s kind=%s new=%s",
                workspace_id,
                kept.asset.asset_id,
                kind,
                kept.asset.asset_id == asset_id,
            )
            return kept.asset
        except BaseException as error:
            # Cancelled mid-add, the row may already be committed: keep its object, since a
            # leftover object only costs storage and a row without one is a broken item.
            committed_maybe = adding and not isinstance(error, Exception)
            if location is not None and not committed_maybe:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(self._media.delete, location)
            if isinstance(error, (EditorAssetMediaInvalid, LibraryUnavailable)) or not isinstance(
                error, Exception
            ):
                raise
            raise LibraryUnavailable() from error
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
        location = await self._repo("delete", workspace_id, asset_id)
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
        record = await self._repo("get", workspace_id, asset_id)
        if record is None:
            raise LibraryItemNotFound()
        if self._assets is None:
            raise LibraryUnavailable()
        upload_type = UPLOAD_TYPES[record.asset.media_type]
        try:
            return await self._assets.ensure_project_asset(
                project_id,
                location=record.location,
                checksum=record.asset.checksum,
                media_type=record.asset.media_type,
                kind=upload_type.kind,
                suffix=upload_type.suffix,
            )
        except Exception as error:
            logger.warning("library copy into a draft failed: %s", type(error).__name__)
            raise LibraryUnavailable() from error


@dataclass
class ImportReport:
    added: int = 0
    unchanged: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)


def _catalog_labels(catalog: Path | None) -> dict[str, dict[str, object]]:
    """Labels per file name from the bundled asset catalog, without its file and curve keys."""
    if catalog is None or not catalog.is_file():
        return {}
    rows = json.loads(catalog.read_text("utf-8")).get("assets", [])
    return {
        Path(str(row.get("file", ""))).name: {
            key: value for key, value in row.items() if key not in ("file", "env_curve")
        }
        for row in rows
    }


async def import_directory(
    service: WorkspaceLibraryService, workspace_id: str, directory: Path, catalog: Path | None
) -> ImportReport:
    """Load every file of one directory into a workspace's library; files already there stay."""
    labels = _catalog_labels(catalog)
    known = {item.asset_id for item in await service.list(workspace_id)}
    report = ImportReport()
    for path in sorted(item for item in directory.iterdir() if item.is_file()):
        try:
            asset = await service.import_file(workspace_id, path, labels.get(path.name, {}))
        except EditorAssetMediaInvalid as error:
            report.failed.append((path.name, error.code))
            continue
        except (EditorAssetUploadTooLarge, LibraryUnavailable) as error:
            report.failed.append((path.name, type(error).__name__))
            continue
        if asset.asset_id in known:
            report.unchanged += 1
        else:
            known.add(asset.asset_id)
            report.added += 1
    logger.info(
        "library import workspace=%s added=%d unchanged=%d failed=%d",
        workspace_id,
        report.added,
        report.unchanged,
        len(report.failed),
    )
    return report

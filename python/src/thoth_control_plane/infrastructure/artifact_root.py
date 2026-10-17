"""The one adapter that stores render and editor objects and composes local temporary paths.

Persistent objects live in the media store (spec 2026-10-17, render storage), keyed by the
same locators the database already holds::

    work/<render_job_id>/{bundle.json,output.mp4}     a job's bundle and its received output
    renders/<render_job_id>/{output.mp4,metadata.json,diagnostics.json}
    uploads/<project_id>/<asset_id>.<ext>

Only temporary files stay below the local root::

    temp/<render_job_id>/       outputs and records on their way into the store
    temp/uploads/<asset_id>.part

Identifiers are validated before they become path segments or keys, and every local target is
re-checked for canonical ancestry with no symlink, junction, or other reparse point in its
chain immediately before it is read, written, moved, or deleted.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import re
import shutil
import stat
from collections.abc import AsyncIterator, Iterator
from pathlib import Path, PurePosixPath
from uuid import uuid4

from thoth_control_plane.application.editor_asset_ports import (
    EditorAssetUploadTooLarge,
    ReceivedUpload,
)
from thoth_control_plane.application.render_job_ports import (
    ArtifactPathInvalid,
    ArtifactUnavailable,
    JobWorkspace,
    PublishedArtifact,
    ReceivedOutput,
    RenderOutputTooLarge,
    StagedAsset,
)
from thoth_control_plane.domain.render_jobs import RenderOutputFacts
from thoth_control_plane.infrastructure.media_store import (
    LocalMediaStore,
    MediaLocatorInvalid,
    MediaStore,
    MediaStoreUnavailable,
    MediaUnavailable,
)

#: Identical to the domain `OpaqueId`: one safe segment, never a path fragment.
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,127}$")
#: A source extension is only carried over when it is itself a safe segment.
_SUFFIX = re.compile(r"^\.[A-Za-z0-9]{1,8}$")
#: One segment of a stored asset locator: no dot-segment, separator, or colon.
_LOCATOR_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

#: Enough leading bytes to recognize every accepted media signature.
_HEAD_BYTES = 16
_OUTPUT_NAME = "output.mp4"
#: A bundle is one document revision and its staged names; far below this.
_MAX_BUNDLE_BYTES = 8 * 1024 * 1024


def _valid_identifier(value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.match(value):
        raise ArtifactPathInvalid()
    return value


def _is_link(path: Path) -> bool:
    """Report symlinks, junctions, and any other reparse point."""
    try:
        info = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _stored_sha256(checksum: str) -> str | None:
    return checksum.removeprefix("sha256:") if checksum.startswith("sha256:") else None


class LocalArtifactRoot:
    """Own every render and editor object, and every local path below one temporary root."""

    def __init__(self, root: Path, media: MediaStore | None = None) -> None:
        self._root = Path(root).resolve()
        self._media = media if media is not None else LocalMediaStore(self._root)

    # --- render jobs -----------------------------------------------------------

    def prepare(self, render_job_id: str) -> JobWorkspace:
        job = _valid_identifier(render_job_id)
        self._contained("temp", job).mkdir(parents=True, exist_ok=True)
        return JobWorkspace(render_job_id=job)

    def stage_asset(
        self,
        workspace: JobWorkspace,
        *,
        asset_id: str,
        location: str,
        expected_checksum: str,
        max_bytes: int,
    ) -> StagedAsset:
        """Verify one stored asset against its record and name it for the renderer.

        Nothing is copied: the renderer downloads the asset through the control plane and
        checks the same checksum again before it renders.
        """
        _valid_identifier(workspace.render_job_id)
        asset = _valid_identifier(asset_id)
        suffix = PurePosixPath(location).suffix
        suffix = suffix if _SUFFIX.match(suffix) else ""
        try:
            facts = self._media.stat(location)
        except (MediaUnavailable, MediaLocatorInvalid):
            raise ArtifactUnavailable() from None
        if facts.size_bytes > max_bytes or facts.sha256 != _stored_sha256(expected_checksum):
            raise ArtifactUnavailable()
        return StagedAsset(
            asset_id=asset,
            relative_name=f"{workspace.assets_name}/{asset}{suffix}",
            size_bytes=facts.size_bytes,
            checksum=expected_checksum,
        )

    def write_bundle(self, workspace: JobWorkspace, bundle_json: bytes) -> str:
        job = _valid_identifier(workspace.render_job_id)
        self._put_bytes(job, f"work/{job}/{workspace.bundle_name}", bundle_json)
        return workspace.bundle_name

    def read_bundle(self, render_job_id: str) -> bytes:
        job = _valid_identifier(render_job_id)
        location = f"work/{job}/{JobWorkspace(render_job_id=job).bundle_name}"
        try:
            if self._media.stat(location).size_bytes > _MAX_BUNDLE_BYTES:
                raise ArtifactUnavailable()
            return b"".join(self._media.open_range(location))
        except MediaUnavailable:
            raise ArtifactUnavailable() from None

    async def receive_output(
        self, render_job_id: str, chunks: AsyncIterator[bytes], *, max_bytes: int
    ) -> ReceivedOutput:
        """Stream one renderer upload to a local file, then store it under `work/<job>/`.

        A second upload for the same job replaces the first, so a renderer retry is safe.
        """
        job = _valid_identifier(render_job_id)
        directory = self._contained("temp", job)
        directory.mkdir(parents=True, exist_ok=True)
        # One partial per upload: a renderer retry racing its first attempt never shares it.
        partial = self._contained("temp", job, f"{_OUTPUT_NAME}.{uuid4().hex}.part")
        if _is_link(partial):
            raise ArtifactPathInvalid()
        digest = hashlib.sha256()
        written = 0
        try:
            with partial.open("wb") as writer:
                async for chunk in chunks:
                    written += len(chunk)
                    if written > max_bytes:
                        raise RenderOutputTooLarge()
                    digest.update(chunk)
                    await asyncio.to_thread(writer.write, chunk)
            await asyncio.to_thread(self._media.put_file, f"work/{job}/{_OUTPUT_NAME}", partial)
        finally:
            partial.unlink(missing_ok=True)
        return ReceivedOutput(size_bytes=written, checksum=f"sha256:{digest.hexdigest()}")

    def verify_temporary_output(self, render_job_id: str, expected: RenderOutputFacts) -> str:
        """The stored output's locator, when it is exactly the file the renderer reported."""
        job = _valid_identifier(render_job_id)
        location = f"work/{job}/{_OUTPUT_NAME}"
        try:
            facts = self._media.stat(location)
        except MediaUnavailable:
            raise ArtifactUnavailable() from None
        if facts.size_bytes != expected.size_bytes or facts.sha256 != _stored_sha256(
            expected.checksum
        ):
            raise ArtifactUnavailable()
        return location

    def publish(
        self,
        render_job_id: str,
        output: RenderOutputFacts,
        metadata_json: bytes,
        diagnostics_json: bytes,
    ) -> PublishedArtifact:
        job = _valid_identifier(render_job_id)
        source = self.verify_temporary_output(job, output)
        self._put_bytes(job, f"renders/{job}/metadata.json", metadata_json)
        self._put_bytes(job, f"renders/{job}/diagnostics.json", diagnostics_json)
        # Publication is the last step: one copy of the verified object.
        self._media.copy(source, f"renders/{job}/{_OUTPUT_NAME}")
        # The render is published; leftover work objects are only clutter, never a failure.
        with contextlib.suppress(MediaStoreUnavailable, MediaUnavailable):
            for location in self._media.list(f"work/{job}/"):
                self._media.delete(location)
        return PublishedArtifact(
            relative_path=f"renders/{job}/{_OUTPUT_NAME}",
            size_bytes=output.size_bytes,
            checksum=output.checksum,
        )

    def resolve_download(self, render_job_id: str, relative_path: str) -> str:
        job = _valid_identifier(render_job_id)
        if relative_path != f"renders/{job}/{_OUTPUT_NAME}":
            raise ArtifactPathInvalid()
        return relative_path

    def object_size(self, location: str) -> int:
        try:
            return self._media.size(location)
        except (MediaUnavailable, MediaLocatorInvalid):
            raise ArtifactUnavailable() from None

    def read_object(self, location: str, start: int, end: int | None) -> Iterator[bytes]:
        try:
            return self._media.open_range(location, start, end)
        except (MediaUnavailable, MediaLocatorInvalid):
            raise ArtifactUnavailable() from None

    def cleanup(self, render_job_id: str) -> None:
        """Delete this job's output and work objects, keeping its bounded safe records."""
        job = _valid_identifier(render_job_id)
        temporary = self._contained("temp", job)
        if _is_link(temporary):
            raise ArtifactPathInvalid()
        try:
            self._media.delete(f"renders/{job}/{_OUTPUT_NAME}")
            for location in self._media.list(f"work/{job}/"):
                self._media.delete(location)
        except MediaLocatorInvalid:
            raise ArtifactPathInvalid() from None
        if temporary.is_dir():
            shutil.rmtree(temporary, ignore_errors=True)

    def _put_bytes(self, job: str, location: str, data: bytes) -> None:
        """Store small bytes through a local staging file named after the object."""
        self._contained("temp", job).mkdir(parents=True, exist_ok=True)
        staging = self._contained("temp", job, f"{PurePosixPath(location).name}.part")
        if _is_link(staging):
            raise ArtifactPathInvalid()
        try:
            staging.write_bytes(data)
            self._media.put_file(location, staging)
        finally:
            staging.unlink(missing_ok=True)

    # --- editor uploads ----------------------------------------------------------

    async def receive_upload(
        self, *, asset_id: str, chunks: AsyncIterator[bytes], max_bytes: int
    ) -> ReceivedUpload:
        """Stream one upload into temporary storage, hashing it as it lands.

        The root must already exist: a missing mount is refused, never created.
        Any failure, including a client that disconnects, removes the partial file.
        """
        asset = _valid_identifier(asset_id)
        if _is_link(self._root) or not self._root.is_dir():
            raise ArtifactUnavailable()
        self._contained("temp", "uploads").mkdir(parents=True, exist_ok=True)
        partial = self._contained("temp", "uploads", f"{asset}.part")
        digest = hashlib.sha256()
        head = b""
        written = 0
        # Opened exclusively and outside the cleanup, so a clash never deletes another file.
        writer = partial.open("xb")
        try:
            with writer:
                async for chunk in chunks:
                    written += len(chunk)
                    if written > max_bytes:
                        raise EditorAssetUploadTooLarge()
                    if len(head) < _HEAD_BYTES:
                        head = (head + chunk)[:_HEAD_BYTES]
                    digest.update(chunk)
                    await asyncio.to_thread(writer.write, chunk)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        return ReceivedUpload(
            location=f"temp/uploads/{partial.name}",
            path=partial,
            size_bytes=written,
            checksum=f"sha256:{digest.hexdigest()}",
            head=head,
        )

    def publish_upload(self, received: ReceivedUpload, *, project_id: str, suffix: str) -> str:
        """Store one received upload at its project-scoped locator, then drop the local copy."""
        if not _LOCATOR_SEGMENT.match(project_id) or not _SUFFIX.match(suffix):
            raise ArtifactPathInvalid()
        source = self._contained(*received.location.split("/"))
        if _is_link(source) or not source.is_file():
            raise ArtifactUnavailable()
        name = f"{source.name.removesuffix('.part')}{suffix}"
        location = f"uploads/{project_id}/{name}"
        self._media.put_file(location, source)
        source.unlink(missing_ok=True)
        return location

    def discard(self, relative_location: str) -> None:
        """Remove one upload: a local temporary file, or a stored object; absent is fine."""
        segments = relative_location.split("/")
        if any(not _LOCATOR_SEGMENT.match(segment) for segment in segments):
            raise ArtifactPathInvalid()
        if segments[0] == "temp":
            target = self._contained(*segments)
            if _is_link(target):
                raise ArtifactPathInvalid()
            target.unlink(missing_ok=True)
            return
        try:
            self._media.delete(relative_location)
        except MediaLocatorInvalid:
            raise ArtifactPathInvalid() from None

    def _contained(self, *segments: str) -> Path:
        """Join validated segments and prove the result stays below the root."""
        candidate = self._root.joinpath(*segments)
        resolved = candidate.resolve()
        if resolved != self._root and not resolved.is_relative_to(self._root):
            raise ArtifactPathInvalid()
        current = self._root
        for segment in segments:
            current = current / segment
            if _is_link(current):
                raise ArtifactPathInvalid()
        return candidate

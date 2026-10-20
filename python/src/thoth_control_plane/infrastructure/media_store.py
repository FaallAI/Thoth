"""Workflow media storage (spec 2026-10-17): the port, its errors, and the local store.

A locator is the key: `reports/<id>/<kind>/<name>`, the same string reports, Temporal history,
and footage rows already hold. Calls are synchronous like `Reports`; async callers wrap them in
`asyncio.to_thread`.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

if TYPE_CHECKING:
    from thoth_control_plane.config import Settings

#: The same segment rule as `LocalArtifactRoot`: no dot-segment, separator, or colon.
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
#: Workflow media (`reports`), editor uploads, render inputs and outputs, and the volume archive.
_PREFIXES = frozenset({"reports", "uploads", "renders", "work", "archive"})
_CHUNK = 1024 * 1024


class MediaUnavailable(LookupError):
    """No object is stored at this locator."""


class MediaStoreUnavailable(RuntimeError):
    """The store could not be reached or refused the request."""


class MediaLocatorInvalid(ValueError):
    """The locator is not a safe media key."""


@dataclass(frozen=True)
class MediaStat:
    size_bytes: int
    sha256: str | None  # hex; None when the object carries no recorded digest


class MediaStore(Protocol):
    def put_file(self, location: str, path: Path) -> None: ...

    def fetch(self, location: str, destination: Path) -> None: ...

    def stat(self, location: str) -> MediaStat: ...

    def size(self, location: str) -> int: ...

    def delete(self, location: str) -> None: ...

    def list(self, prefix: str) -> list[str]: ...

    def open_range(
        self, location: str, start: int = 0, end: int | None = None
    ) -> Iterator[bytes]: ...

    def copy(self, source: str, destination: str) -> None: ...

    def check(self) -> None: ...


class MeteredMediaStore:
    """Records the bytes a scoped caller stores (spec 2026-10-20, 2.1); delegates the rest.

    Unscoped writes (the private renderer route, CLI imports) record nothing: a render's
    output is counted when the render completes.
    """

    def __init__(self, inner: MediaStore) -> None:
        self._inner = inner

    def put_file(self, location: str, path: Path) -> None:
        self._inner.put_file(location, path)
        from thoth_control_plane import metering

        metering.record_sync(
            "media_stored",
            location.split("/", 1)[0],
            path.stat().st_size,
            "byte",
            in_scope_only=True,
        )

    def fetch(self, location: str, destination: Path) -> None:
        self._inner.fetch(location, destination)

    def stat(self, location: str) -> MediaStat:
        return self._inner.stat(location)

    def size(self, location: str) -> int:
        return self._inner.size(location)

    def delete(self, location: str) -> None:
        self._inner.delete(location)

    def list(self, prefix: str) -> list[str]:
        return self._inner.list(prefix)

    def open_range(self, location: str, start: int = 0, end: int | None = None) -> Iterator[bytes]:
        return self._inner.open_range(location, start, end)

    def copy(self, source: str, destination: str) -> None:
        self._inner.copy(source, destination)

    def check(self) -> None:
        self._inner.check()


def checked_locator(location: str) -> str:
    """The locator itself, or `MediaLocatorInvalid`; runs before any key or path is built."""
    if not isinstance(location, str) or not 0 < len(location) <= 512:
        raise MediaLocatorInvalid("media_locator_invalid")
    segments = location.split("/")
    if (
        len(segments) < 2
        or segments[0] not in _PREFIXES
        or not all(_SEGMENT.fullmatch(segment) for segment in segments)
    ):
        raise MediaLocatorInvalid("media_locator_invalid")
    return location


def checked_prefix(prefix: str) -> str:
    """A listing prefix: a valid locator followed by one `/`."""
    if not prefix.endswith("/"):
        raise MediaLocatorInvalid("media_locator_invalid")
    checked_locator(prefix[:-1])
    return prefix


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        while chunk := reader.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    # A private partial: two writers of one locator (a retried upload) never share it.
    partial = destination.with_name(f"{destination.name}.{uuid4().hex}.part")
    try:
        shutil.copyfile(source, partial)
        os.replace(partial, destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


class LocalMediaStore:
    """Media below one directory: the artifact root when no S3 endpoint is configured."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def put_file(self, location: str, path: Path) -> None:
        _copy(path, self._path(location))

    def fetch(self, location: str, destination: Path) -> None:
        source = self._path(location)
        if not source.is_file():
            raise MediaUnavailable("media_unavailable")
        _copy(source, destination)

    def stat(self, location: str) -> MediaStat:
        path = self._path(location)
        if not path.is_file():
            raise MediaUnavailable("media_unavailable")
        return MediaStat(size_bytes=path.stat().st_size, sha256=sha256_file(path))

    def size(self, location: str) -> int:
        """The size alone: a request that only streams must not hash the object."""
        path = self._path(location)
        if not path.is_file():
            raise MediaUnavailable("media_unavailable")
        return path.stat().st_size

    def delete(self, location: str) -> None:
        self._path(location).unlink(missing_ok=True)

    def list(self, prefix: str) -> list[str]:
        base = self._path(checked_prefix(prefix)[:-1])
        if not base.is_dir():
            return []
        return sorted(
            path.relative_to(self._root).as_posix()
            for path in base.rglob("*")
            if path.is_file() and not path.is_symlink() and not path.name.endswith(".part")
        )

    def open_range(self, location: str, start: int = 0, end: int | None = None) -> Iterator[bytes]:
        path = self._path(location)
        if not path.is_file():
            raise MediaUnavailable("media_unavailable")
        return self._chunks(path, start, end)

    @staticmethod
    def _chunks(path: Path, start: int, end: int | None) -> Iterator[bytes]:
        remaining = None if end is None else max(0, end - start + 1)
        with path.open("rb") as reader:
            reader.seek(start)
            while remaining is None or remaining > 0:
                chunk = reader.read(_CHUNK if remaining is None else min(_CHUNK, remaining))
                if not chunk:
                    return
                if remaining is not None:
                    remaining -= len(chunk)
                yield chunk

    def copy(self, source: str, destination: str) -> None:
        origin = self._path(source)
        if not origin.is_file():
            raise MediaUnavailable("media_unavailable")
        _copy(origin, self._path(destination))

    def check(self) -> None:
        if not self._root.is_dir():
            raise MediaStoreUnavailable("media_root_missing")

    def _path(self, location: str) -> Path:
        """Join a checked locator below the root, refusing any link along the way."""
        candidate = self._root.joinpath(*checked_locator(location).split("/"))
        current = self._root
        for segment in location.split("/"):
            current = current / segment
            if current.is_symlink():
                raise MediaLocatorInvalid("media_locator_invalid")
        if not candidate.resolve().is_relative_to(self._root):
            raise MediaLocatorInvalid("media_locator_invalid")
        return candidate


def build_media_store(settings: Settings) -> MediaStore:
    """S3 when an endpoint is configured; otherwise the artifact root, as before."""
    if not settings.THOTH_MEDIA_S3_ENDPOINT:
        return LocalMediaStore(settings.THOTH_CONTROL_PLANE_ARTIFACT_ROOT)
    from thoth_control_plane.infrastructure.s3_media_store import S3MediaStore

    return S3MediaStore.from_settings(settings)

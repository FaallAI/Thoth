"""Moving the media already on the artifact volume into the store (spec 2026-10-17).

The import copies and verifies, never overwrites and never deletes. `remove_local_media` is the
separate, operator-gated step that deletes a local file once its object verified identical.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from thoth_control_plane.infrastructure.media_store import (
    LocalMediaStore,
    MediaLocatorInvalid,
    MediaStore,
    MediaUnavailable,
    checked_locator,
    sha256_file,
)


@dataclass(frozen=True)
class MediaImportCounts:
    imported: int
    present: int
    invalid: int
    mismatch: int


@dataclass(frozen=True)
class MediaRemovalCounts:
    removed: int
    kept: int


def _candidates(root: Path) -> Iterator[tuple[Path, str | None]]:
    """Each media file below `<root>/reports/` with its locator, or None when it is invalid.
    Links are never followed; report JSON is skipped (it lives in PostgreSQL)."""
    reports = root / "reports"
    if not reports.is_dir() or reports.is_symlink():
        return
    for directory, folders, files in os.walk(reports, followlinks=False):
        here = Path(directory)
        for name in sorted(folders):
            if (here / name).is_symlink():
                yield here / name, None
        folders[:] = sorted(name for name in folders if not (here / name).is_symlink())
        for name in sorted(files):
            path = here / name
            if name.endswith(".json") and not path.is_symlink():
                continue
            if path.is_symlink() or not path.is_file() or name.endswith(".part"):
                yield path, None
                continue
            try:
                yield path, checked_locator(path.relative_to(root).as_posix())
            except MediaLocatorInvalid:
                yield path, None


def _matches(store: MediaStore, location: str, size: int, digest: str) -> bool:
    """True when a fetched copy of the object has this size and sha256."""
    with tempfile.TemporaryDirectory(prefix="thoth-media-verify-") as scratch:
        copy = Path(scratch) / "object"
        store.fetch(location, copy)
        return copy.stat().st_size == size and sha256_file(copy) == digest


def import_media(root: Path, store: MediaStore) -> MediaImportCounts:
    """Copy each media file that is not stored yet. `MediaStoreUnavailable` propagates."""
    imported = present = invalid = mismatch = 0
    for path, location in _candidates(root):
        if location is None:
            invalid += 1
            continue
        try:
            size, digest = path.stat().st_size, sha256_file(path)
        except OSError:
            invalid += 1
            continue
        try:
            existing = store.stat(location)
        except MediaUnavailable:
            existing = None
        if existing is not None:
            same = existing.size_bytes == size and (
                existing.sha256 == digest
                if existing.sha256 is not None
                else _matches(store, location, size, digest)
            )
            if same:
                present += 1
            else:
                mismatch += 1
            continue
        store.put_file(location, path)
        if _matches(store, location, size, digest):
            imported += 1
        else:
            store.delete(location)
            mismatch += 1
    return MediaImportCounts(imported, present, invalid, mismatch)


def remove_local_media(root: Path, store: MediaStore) -> MediaRemovalCounts:
    """Delete each local media file whose object verifies identical; keep every other file."""
    if isinstance(store, LocalMediaStore) and store.root == root.resolve():
        raise ValueError("media_store_is_the_volume")
    removed = kept = 0
    for path, location in _candidates(root):
        if location is None:
            kept += 1
            continue
        try:
            size, digest = path.stat().st_size, sha256_file(path)
            verified = _matches(store, location, size, digest)
        except (OSError, MediaUnavailable):
            verified = False
        if not verified:
            kept += 1
            continue
        path.unlink()
        removed += 1
    reports = root / "reports"
    for directory, _, _ in sorted(os.walk(reports, followlinks=False), reverse=True):
        if Path(directory) != reports:
            with contextlib.suppress(OSError):
                Path(directory).rmdir()  # only an empty folder goes
    return MediaRemovalCounts(removed, kept)

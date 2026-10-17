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


def _candidates(root: Path, *, archive: bool = False) -> Iterator[tuple[Path, str | None]]:
    """Each file to move with its key, or None when it is invalid. Links are never followed.

    Media mode walks `<root>/reports/` and skips report JSON (it lives in PostgreSQL). Archive
    mode walks `reports/` and `legacy-scout/`, keeps the JSON, and keys every file under
    `archive/` (spec 2026-10-17, render storage).
    """
    for top in ("reports", "legacy-scout") if archive else ("reports",):
        base = root / top
        if not base.is_dir() or base.is_symlink():
            continue
        for directory, folders, files in os.walk(base, followlinks=False):
            here = Path(directory)
            for name in sorted(folders):
                if (here / name).is_symlink():
                    yield here / name, None
            folders[:] = sorted(name for name in folders if not (here / name).is_symlink())
            for name in sorted(files):
                path = here / name
                is_json = name.endswith(".json") and not path.is_symlink()
                if not archive and is_json:
                    continue  # report JSON lives in PostgreSQL
                if archive and top == "reports" and not is_json and not path.is_symlink():
                    continue  # media under reports/ moves through the media import
                if path.is_symlink() or not path.is_file() or name.endswith(".part"):
                    yield path, None
                    continue
                relative = path.relative_to(root).as_posix()
                try:
                    yield path, checked_locator(f"archive/{relative}" if archive else relative)
                except MediaLocatorInvalid:
                    yield path, None


def _matches(store: MediaStore, location: str, size: int, digest: str) -> bool:
    """True when a fetched copy of the object has this size and sha256."""
    with tempfile.TemporaryDirectory(prefix="thoth-media-verify-") as scratch:
        copy = Path(scratch) / "object"
        store.fetch(location, copy)
        return copy.stat().st_size == size and sha256_file(copy) == digest


def import_media(root: Path, store: MediaStore, *, archive: bool = False) -> MediaImportCounts:
    """Copy each media file that is not stored yet. `MediaStoreUnavailable` propagates."""
    imported = present = invalid = mismatch = 0
    for path, location in _candidates(root, archive=archive):
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


def remove_local_media(
    root: Path, store: MediaStore, *, archive: bool = False
) -> MediaRemovalCounts:
    """Delete each local media file whose object verifies identical; keep every other file."""
    volume = root.resolve()
    if isinstance(store, LocalMediaStore) and (
        store.root.is_relative_to(volume) or volume.is_relative_to(store.root)
    ):
        # Verifying a file against itself, or a copy inside the tree being removed, proves nothing.
        raise ValueError("media_store_is_the_volume")
    removed = kept = 0
    for path, location in _candidates(root, archive=archive):
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
    for top in ("reports", "legacy-scout") if archive else ("reports",):
        base = root / top
        for directory, _, _ in sorted(os.walk(base, followlinks=False), reverse=True):
            if Path(directory) != base:
                with contextlib.suppress(OSError):
                    Path(directory).rmdir()  # only an empty folder goes
    return MediaRemovalCounts(removed, kept)

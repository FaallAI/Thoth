"""Encrypted per-account browser profiles (spec 2026-10-13, section 3.2).

A profile keeps an account looking like one returning device: local storage and device ids
survive between leases. At rest it is a tar archive sealed with the vault key, one per engine
(a Chromium user data directory and a Firefox profile are different formats); it is unpacked
into a private directory only while the account is leased. Cookies still come from the vault.

An account deleted while its profile is unpacked must not get it back: the api deletes, the
worker seals, so `mark_deleted` leaves a tombstone on the shared volume that `seal` honours.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import io
import logging
import os
import shutil
import tarfile
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.accounts.policy import ENGINES
from thoth_control_plane.acquisition.accounts.vault import Vault, VaultError

if TYPE_CHECKING:
    from thoth_control_plane.infrastructure.source_account_store import AccountLease

logger = logging.getLogger(__name__)
PRUNED = ("Cache", "Code Cache", "GPUCache", "Service Worker/CacheStorage")
MAX_BYTES = 64 * 2**20


class AccountProfiles:
    def __init__(self, vault: Vault, root: Path, *, max_bytes: int = MAX_BYTES) -> None:
        self._vault, self._root, self._max = vault, root, max_bytes

    def _archive(self, account_id: str, engine: str) -> Path:
        if engine not in ENGINES:
            raise ValueError(f"unknown engine {engine!r}")
        return self._root / f"{account_id}.{engine}.profile"

    def unseal(self, account_id: str, engine: str = "patchright") -> Path:
        archive = self._archive(account_id, engine)
        directory = _private_directory()
        if archive.is_file():
            try:
                data = self._vault.open_bytes(archive.read_bytes())
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
                    tar.extractall(directory, filter="data")
            except (VaultError, tarfile.TarError, OSError, ValueError, EOFError):
                logger.warning("account profile unreadable; a fresh profile starts")
                self.discard(directory)
                directory = _private_directory()
        return directory

    def _tombstone(self, account_id: str) -> Path:
        return self._root / f"{account_id}.deleted"

    def seal(self, account_id: str, directory: Path, engine: str = "patchright") -> None:
        try:
            target = self._archive(account_id, engine)
            if self._tombstone(account_id).exists():
                return
            files = sorted(
                (
                    path
                    for path in directory.rglob("*")
                    if path.is_file() and not path.is_symlink() and not _pruned(path, directory)
                ),
                key=lambda path: path.stat().st_size,
            )
            total, kept = 0, []
            for path in files:  # smallest first, so the cap drops the largest files
                size = path.stat().st_size
                if total + size > self._max:
                    continue
                total += size
                kept.append(path)
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
                for path in kept:
                    tar.add(path, arcname=path.relative_to(directory).as_posix())
            self._root.mkdir(parents=True, exist_ok=True)
            partial = target.with_suffix(".part")
            partial.write_bytes(self._vault.seal_bytes(buffer.getvalue()))
            os.replace(partial, target)
            if self._tombstone(account_id).exists():  # deleted while this archive was written
                target.unlink(missing_ok=True)
        except OSError:
            logger.warning("account profile could not be saved; the next lease starts fresh")
        finally:
            self.discard(directory)

    @staticmethod
    def discard(directory: Path) -> None:
        shutil.rmtree(directory, ignore_errors=True)

    def delete(self, account_id: str) -> None:
        for engine in ENGINES:
            self._archive(account_id, engine).unlink(missing_ok=True)

    def mark_deleted(self, account_id: str) -> None:
        """The account is gone: no lease still open may write its profile back."""
        self._root.mkdir(parents=True, exist_ok=True)
        self._tombstone(account_id).touch()
        self.delete(account_id)


@contextlib.asynccontextmanager
async def leased_access(
    profiles: AccountProfiles | None, lease: AccountLease, *, engine: str | None = None
) -> AsyncIterator[SessionAccess]:
    """The lease's access with its engine's profile unpacked; sealed back on any exit."""
    access = lease.access if engine is None else dataclasses.replace(lease.access, engine=engine)
    if profiles is None:
        yield access
        return
    directory = await asyncio.to_thread(profiles.unseal, lease.account_id, access.engine)
    try:
        yield dataclasses.replace(access, profile_dir=directory)
    finally:
        await asyncio.to_thread(profiles.seal, lease.account_id, directory, access.engine)


def _private_directory() -> Path:
    directory = Path(tempfile.mkdtemp(prefix="thoth-profile-"))
    os.chmod(directory, 0o700)
    return directory


def _pruned(path: Path, root: Path) -> bool:
    relative = path.relative_to(root).as_posix()
    return any(f"/{name}/" in f"/{relative}" for name in PRUNED)

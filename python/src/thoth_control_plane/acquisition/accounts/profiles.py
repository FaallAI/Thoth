"""Encrypted per-account browser profiles (spec 2026-10-13, section 3.2).

A profile keeps an account looking like one returning device: local storage and device ids
survive between leases. At rest it is a tar archive sealed with the vault key, one per engine
(a Chromium user data directory and a Firefox profile are different formats); it is unpacked
into a private directory only while the account is leased. Cookies still come from the vault.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
import tarfile
import tempfile
from pathlib import Path

from thoth_control_plane.acquisition.accounts.policy import ENGINES
from thoth_control_plane.acquisition.accounts.vault import Vault, VaultError

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

    def seal(self, account_id: str, directory: Path, engine: str = "patchright") -> None:
        try:
            target = self._archive(account_id, engine)
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


def _private_directory() -> Path:
    directory = Path(tempfile.mkdtemp(prefix="thoth-profile-"))
    os.chmod(directory, 0o700)
    return directory


def _pruned(path: Path, root: Path) -> bool:
    relative = path.relative_to(root).as_posix()
    return any(f"/{name}/" in f"/{relative}" for name in PRUNED)

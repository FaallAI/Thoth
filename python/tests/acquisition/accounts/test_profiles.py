"""Encrypted per-account browser profiles (spec 2026-10-13, section 3.2)."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet

from thoth_control_plane.acquisition.accounts.profiles import AccountProfiles
from thoth_control_plane.acquisition.accounts.vault import Vault

ACCOUNT = "4f6c7d1e-0000-4000-8000-000000000001"


def _profiles(tmp_path: Path, **kwargs: Any) -> AccountProfiles:
    return AccountProfiles(Vault(Fernet.generate_key().decode()), tmp_path / "profiles", **kwargs)


def test_a_profile_round_trips_without_its_caches(tmp_path: Path) -> None:
    profiles = _profiles(tmp_path)
    directory = profiles.unseal(ACCOUNT)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    (directory / "Default").mkdir()
    (directory / "Default" / "Local Storage").write_text("device-id")
    (directory / "Default" / "Cache").mkdir()
    (directory / "Default" / "Cache" / "blob").write_bytes(b"x" * 1000)

    profiles.seal(ACCOUNT, directory)
    assert not directory.exists()
    archive = tmp_path / "profiles" / f"{ACCOUNT}.patchright.profile"
    assert b"device-id" not in archive.read_bytes()  # encrypted at rest

    again = profiles.unseal(ACCOUNT)
    assert (again / "Default" / "Local Storage").read_text() == "device-id"
    assert not (again / "Default" / "Cache").exists()


def test_each_engine_keeps_its_own_profile(tmp_path: Path) -> None:
    # A Chromium user data directory is never unpacked into Firefox (amendment 2026-10-14).
    profiles = _profiles(tmp_path)
    chromium = profiles.unseal(ACCOUNT, "patchright")
    (chromium / "Local State").write_text("chromium")
    profiles.seal(ACCOUNT, chromium, "patchright")

    firefox = profiles.unseal(ACCOUNT, "camoufox")
    assert list(firefox.iterdir()) == []
    (firefox / "prefs.js").write_text("firefox")
    profiles.seal(ACCOUNT, firefox, "camoufox")

    assert (profiles.unseal(ACCOUNT, "patchright") / "Local State").read_text() == "chromium"
    assert (profiles.unseal(ACCOUNT, "camoufox") / "prefs.js").read_text() == "firefox"


def test_a_truncated_or_foreign_profile_starts_fresh(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    profiles = _profiles(tmp_path)
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / f"{ACCOUNT}.patchright.profile").write_bytes(b"not a profile")

    with caplog.at_level("WARNING"):
        directory = profiles.unseal(ACCOUNT)

    assert list(directory.iterdir()) == []
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert "profile" in caplog.text


def test_an_oversized_profile_is_cut_to_the_cap(tmp_path: Path) -> None:
    profiles = _profiles(tmp_path, max_bytes=10_000)
    directory = profiles.unseal(ACCOUNT)
    (directory / "keep").write_text("small")
    (directory / "huge.bin").write_bytes(b"x" * 50_000)

    profiles.seal(ACCOUNT, directory)

    again = profiles.unseal(ACCOUNT)
    assert (again / "keep").exists() and not (again / "huge.bin").exists()


def test_delete_removes_the_archives_of_every_engine(tmp_path: Path) -> None:
    profiles = _profiles(tmp_path)
    profiles.seal(ACCOUNT, profiles.unseal(ACCOUNT, "patchright"), "patchright")
    profiles.seal(ACCOUNT, profiles.unseal(ACCOUNT, "camoufox"), "camoufox")
    other = "4f6c7d1e-0000-4000-8000-000000000002"
    profiles.seal(other, profiles.unseal(other))

    profiles.delete(ACCOUNT)

    assert sorted(path.name for path in (tmp_path / "profiles").iterdir()) == [
        f"{other}.patchright.profile"
    ]


def test_discard_removes_without_saving(tmp_path: Path) -> None:
    profiles = _profiles(tmp_path)
    directory = profiles.unseal(ACCOUNT)
    (directory / "state").write_text("x")

    profiles.discard(directory)

    assert not directory.exists()
    assert not (tmp_path / "profiles" / f"{ACCOUNT}.patchright.profile").exists()

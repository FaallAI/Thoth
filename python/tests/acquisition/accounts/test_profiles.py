"""Encrypted per-account browser profiles (spec 2026-10-13, section 3.2)."""

from __future__ import annotations

import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet

from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.accounts.cookies import parse_cookies
from thoth_control_plane.acquisition.accounts.profiles import AccountProfiles, leased_access
from thoth_control_plane.acquisition.accounts.vault import Vault
from thoth_control_plane.infrastructure.source_account_store import AccountLease

ACCOUNT = "4f6c7d1e-0000-4000-8000-000000000001"
NOW = datetime(2026, 10, 14, tzinfo=UTC)
COOKIES = parse_cookies(
    "instagram",
    "\t".join([".instagram.com", "TRUE", "/", "TRUE", "1893456000", "sessionid", "s"]) + "\n",
    now=NOW,
)


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


@pytest.mark.asyncio
async def test_a_failing_attempt_still_seals_and_removes_the_profile(tmp_path: Path) -> None:
    profiles = _profiles(tmp_path)
    lease = AccountLease(ACCOUNT, "instagram", SessionAccess(COOKIES), NOW)
    seen: list[Path] = []

    with pytest.raises(RuntimeError):
        async with leased_access(profiles, lease) as access:
            assert access.profile_dir is not None
            seen.append(access.profile_dir)
            (access.profile_dir / "state").write_text("kept")
            raise RuntimeError("acquisition crashed")

    assert not seen[0].exists()
    async with leased_access(profiles, lease) as again:
        assert again.profile_dir is not None
        assert (again.profile_dir / "state").read_text() == "kept"


@pytest.mark.asyncio
async def test_a_deleted_account_does_not_get_its_profile_back(tmp_path: Path) -> None:
    profiles = _profiles(tmp_path)
    lease = AccountLease(ACCOUNT, "instagram", SessionAccess(COOKIES), NOW)

    async with leased_access(profiles, lease) as access:
        assert access.profile_dir is not None
        (access.profile_dir / "state").write_text("x")
        profiles.delete(ACCOUNT)
        profiles.mark_deleted(ACCOUNT)  # the route calls this beside delete()

    assert list((tmp_path / "profiles").glob(f"{ACCOUNT}.*.profile")) == []


@pytest.mark.asyncio
async def test_the_lease_engine_picks_the_profile_and_can_be_overridden(tmp_path: Path) -> None:
    profiles = _profiles(tmp_path)
    lease = AccountLease(ACCOUNT, "instagram", SessionAccess(COOKIES, engine="camoufox"), NOW)

    async with leased_access(profiles, lease) as access:
        assert access.engine == "camoufox"
    # Acquisition's card crops stay on Patchright (spec 3.4), whatever the platform's engine.
    async with leased_access(profiles, lease, engine="patchright") as access:
        assert access.engine == "patchright"

    names = sorted(path.name for path in (tmp_path / "profiles").iterdir())
    assert names == [f"{ACCOUNT}.camoufox.profile", f"{ACCOUNT}.patchright.profile"]


@pytest.mark.asyncio
async def test_without_profiles_the_lease_access_is_unchanged() -> None:
    lease = AccountLease(ACCOUNT, "instagram", SessionAccess(COOKIES), NOW)

    async with leased_access(None, lease) as access:
        assert access is lease.access

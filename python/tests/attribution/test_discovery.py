"""Profile discovery honors the platform's access mode and leases a source account when needed."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import pytest

from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.accounts.cookies import parse_cookies
from thoth_control_plane.acquisition.models import (
    DiscoveredPhoto,
    DiscoveredVideo,
    DiscoveryDrops,
    DiscoveryReason,
    DiscoveryResult,
    ProfileDiscovery,
)
from thoth_control_plane.attribution.adapters.discovery import DiscoveryBlocked, ProfileDiscoverer
from thoth_control_plane.infrastructure.source_account_store import AccountLease

SOURCE = "vincentius.christ76"
VIDEO = DiscoveredVideo(
    post_id="7677137235434687752",
    owner_handle=SOURCE,
    canonical_url=f"https://www.tiktok.com/@{SOURCE}/video/7677137235434687752",
)
ACCESS = SessionAccess(
    parse_cookies(
        "tiktok",
        "\t".join([".tiktok.com", "TRUE", "/", "TRUE", "1893456000", "sessionid", "s"]) + "\n",
        now=datetime(2026, 10, 9, tzinfo=UTC),
    )
)


def _result(
    videos: list[DiscoveredVideo], reason: DiscoveryReason | None = None
) -> DiscoveryResult:
    return DiscoveryResult(
        kind="profile",
        videos=videos,
        pages=1,
        exhausted=True,
        drops=DiscoveryDrops(),
        reason=reason,
    )


class FakeDiscovery:
    """Answers by whether it was built with a session: anonymous and signed-in results."""

    def __init__(self, anonymous: DiscoveryResult, signed_in: DiscoveryResult) -> None:
        self.anonymous = anonymous
        self.signed_in = signed_in
        self.built_with: list[SessionAccess | None] = []

    def factory(self, access: SessionAccess | None, scratch: Path) -> Any:
        self.built_with.append(access)
        result = self.signed_in if access is not None else self.anonymous

        class _Discovery:
            async def discover(self, request: ProfileDiscovery) -> DiscoveryResult:
                assert (request.handle, request.limit) == (SOURCE, 30)
                return result

        return _Discovery()


class FakeLeases:
    def __init__(self, mode: str, available: bool = True) -> None:
        self._mode = mode
        self._available = available
        self.released: list[str | None] = []

    async def mode(self, platform: str) -> str:
        return self._mode

    async def lease(self, platform: str) -> AccountLease | None:
        if not self._available:
            return None
        return AccountLease("acc-1", "tiktok", ACCESS, datetime(2026, 10, 9, tzinfo=UTC))

    async def release(self, lease: AccountLease, outcome: str | None) -> None:
        self.released.append(outcome)


CAPTCHA = _result([], DiscoveryReason.CAPTCHA)


async def _discover(fake: FakeDiscovery, leases: FakeLeases | None) -> list[DiscoveredVideo]:
    discoverer = ProfileDiscoverer({"tiktok": fake.factory}, leases=leases)  # type: ignore[arg-type]
    return await discoverer.discover("tiktok", SOURCE)


@pytest.mark.asyncio
async def test_fallback_leases_an_account_after_a_captcha() -> None:
    fake = FakeDiscovery(CAPTCHA, _result([VIDEO]))
    leases = FakeLeases("fallback")

    assert await _discover(fake, leases) == [VIDEO]
    assert fake.built_with == [None, ACCESS]
    assert leases.released == ["success"]


def _videos(count: int) -> list[DiscoveredVideo]:
    ids = [str(7677137235434687000 + n) for n in range(count)]
    return [
        VIDEO.model_copy(
            update={
                "post_id": post_id,
                "canonical_url": f"https://www.tiktok.com/@{SOURCE}/video/{post_id}",
            }
        )
        for post_id in ids
    ]


@pytest.mark.asyncio
async def test_fallback_keeps_an_anonymous_success_without_an_account() -> None:
    fake = FakeDiscovery(_result(_videos(10)), _result([]))
    leases = FakeLeases("fallback")

    assert len(await _discover(fake, leases)) == 10
    assert (fake.built_with, leases.released) == ([None], [])


@pytest.mark.asyncio
async def test_fallback_leases_an_account_when_the_anonymous_listing_is_thin() -> None:
    # Operator, 2026-10-13: where signed out is weaker, use the login with its proxy.
    fake = FakeDiscovery(_result(_videos(5)), _result(_videos(30)))  # X signed out: ~5 posts
    leases = FakeLeases("fallback")

    assert len(await _discover(fake, leases)) == 30
    assert (fake.built_with, leases.released) == ([None, ACCESS], ["success"])


@pytest.mark.asyncio
async def test_a_thin_listing_without_an_account_is_still_returned() -> None:
    fake = FakeDiscovery(_result(_videos(5)), _result([]))

    assert len(await _discover(fake, FakeLeases("fallback", available=False))) == 5


@pytest.mark.asyncio
async def test_the_longer_listing_wins() -> None:
    fake = FakeDiscovery(_result(_videos(6)), _result(_videos(2)))
    leases = FakeLeases("fallback")

    assert len(await _discover(fake, leases)) == 6
    assert leases.released == ["success"]


@pytest.mark.asyncio
async def test_anonymous_mode_and_no_store_never_lease() -> None:
    fake = FakeDiscovery(CAPTCHA, _result([VIDEO]))
    leases = FakeLeases("anonymous")

    # A captcha is a failed discovery, not an empty profile.
    with pytest.raises(DiscoveryBlocked):
        await _discover(fake, leases)
    with pytest.raises(DiscoveryBlocked):
        await _discover(fake, None)
    assert (fake.built_with, leases.released) == ([None, None], [])
    assert await _discover(FakeDiscovery(_result([]), CAPTCHA), None) == []  # truly empty


@pytest.mark.asyncio
async def test_fallback_without_an_account_after_a_captcha_is_blocked() -> None:
    fake = FakeDiscovery(CAPTCHA, _result([VIDEO]))

    with pytest.raises(DiscoveryBlocked):
        await _discover(fake, FakeLeases("fallback", available=False))


@pytest.mark.asyncio
async def test_always_leases_first_and_runs_anonymously_without_an_account() -> None:
    fake = FakeDiscovery(_result([VIDEO]), _result([VIDEO]))
    leases = FakeLeases("always")
    assert await _discover(fake, leases) == [VIDEO]
    assert fake.built_with == [ACCESS]

    lonely = FakeDiscovery(_result([VIDEO]), _result([]))
    assert await _discover(lonely, FakeLeases("always", available=False)) == [VIDEO]
    assert lonely.built_with == [None]


@pytest.mark.asyncio
async def test_a_blocked_account_is_released_as_blocked() -> None:
    fake = FakeDiscovery(CAPTCHA, _result([], DiscoveryReason.BLOCKED))
    leases = FakeLeases("fallback")

    with pytest.raises(DiscoveryBlocked):
        await _discover(fake, leases)
    assert leases.released == ["blocked"]


@pytest.mark.asyncio
async def test_the_lease_is_released_when_discovery_raises() -> None:
    class Boom:
        def factory(self, access: SessionAccess | None, scratch: Path) -> Any:
            class _Discovery:
                async def discover(self, request: ProfileDiscovery) -> DiscoveryResult:
                    raise RuntimeError("browser died")

            return _Discovery()

    leases = FakeLeases("always")
    discoverer = ProfileDiscoverer({"tiktok": Boom().factory}, leases=leases)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError):
        await discoverer.discover("tiktok", SOURCE)
    assert leases.released == [None]


class _FailingSignedIn(FakeDiscovery):
    def factory(self, access: SessionAccess | None, scratch: Path) -> Any:
        if access is None:
            return super().factory(access, scratch)
        self.built_with.append(access)

        class _Discovery:
            async def discover(self, request: ProfileDiscovery) -> DiscoveryResult:
                raise RuntimeError("proxy down")

        return _Discovery()


@pytest.mark.asyncio
async def test_a_failing_signed_in_run_keeps_the_thin_anonymous_listing() -> None:
    # Review 2026-10-13: before the thin-listing rule these five videos were returned.
    fake = _FailingSignedIn(_result(_videos(5)), _result([]))
    leases = FakeLeases("fallback")

    assert len(await _discover(fake, leases)) == 5
    assert leases.released == [None]


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", [DiscoveryReason.CHALLENGE, DiscoveryReason.CAPTCHA])
async def test_a_challenge_cools_the_account(reason: DiscoveryReason) -> None:
    fake = FakeDiscovery(CAPTCHA, _result([], reason))
    leases = FakeLeases("fallback")

    with pytest.raises(DiscoveryBlocked):
        await _discover(fake, leases)
    assert leases.released == ["challenge"]


@pytest.mark.asyncio
async def test_store_leases_open_the_profile_and_seal_it_on_release(tmp_path: Path) -> None:
    from cryptography.fernet import Fernet
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from thoth_control_plane.acquisition.accounts.profiles import AccountProfiles
    from thoth_control_plane.acquisition.accounts.vault import Vault
    from thoth_control_plane.attribution.adapters.discovery import StoreLeases
    from thoth_control_plane.infrastructure.source_account_models import Base
    from thoth_control_plane.infrastructure.source_account_store import SourceAccountStore

    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    vault = Vault(Fernet.generate_key().decode())
    store = SourceAccountStore(engine, vault)
    store.add_account("tiktok", "a", ACCESS.cookies)
    leases = StoreLeases(store, AccountProfiles(vault, tmp_path / "profiles"))

    lease = await leases.lease("tiktok")
    assert lease is not None and lease.access.profile_dir is not None
    directory = lease.access.profile_dir
    await leases.release(lease, "success")

    assert not directory.exists()
    assert len(list((tmp_path / "profiles").iterdir())) == 1


@pytest.mark.asyncio
async def test_a_missing_tool_in_the_signed_in_run_is_never_swallowed() -> None:
    from thoth_control_plane.attribution.adapters.frames import ToolMissing

    leases = FakeLeases("fallback")

    def factory(access: SessionAccess | None, scratch: Path) -> Any:
        if access is None:
            return FakeDiscovery(_result(_videos(3)), _result([])).factory(None, scratch)
        raise ToolMissing("camoufox_missing")

    discoverer = ProfileDiscoverer({"tiktok": factory}, leases=leases)  # type: ignore[arg-type]
    with pytest.raises(ToolMissing):
        await discoverer.discover("tiktok", SOURCE)
    assert leases.released == [None]


@pytest.mark.asyncio
async def test_store_leases_never_hide_a_missing_tool() -> None:
    from thoth_control_plane.attribution.adapters.discovery import StoreLeases
    from thoth_control_plane.attribution.adapters.frames import ToolMissing

    class _Store:
        def lease(self, platform: str) -> None:
            raise ToolMissing("camoufox_missing")

    with pytest.raises(ToolMissing):
        await StoreLeases(_Store()).lease("tiktok")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_a_failed_seal_still_reports_the_outcome(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from thoth_control_plane.attribution.adapters.discovery import StoreLeases
    from thoth_control_plane.infrastructure.source_account_store import AccountLease

    class _Profiles:
        def unseal(self, account_id: str, engine: str) -> Path:
            return tmp_path

        def seal(self, account_id: str, directory: Path, engine: str) -> None:
            raise RuntimeError("tar failed")

    class _Store:
        reported: ClassVar[list[str | None]] = []

        def lease(self, platform: str) -> AccountLease:
            return AccountLease("a", "tiktok", ACCESS, datetime(2026, 10, 14, tzinfo=UTC))

        def report(self, account_id: str, outcome: str | None, leased_until: object) -> None:
            self.reported.append(outcome)

    leases = StoreLeases(_Store(), _Profiles())  # type: ignore[arg-type]
    lease = await leases.lease("tiktok")
    assert lease is not None

    with pytest.raises(RuntimeError):
        await leases.release(lease, "success")

    assert _Store.reported == ["success"]


@pytest.mark.asyncio
async def test_creator_listing_keeps_photos_and_the_page() -> None:
    photo = DiscoveredPhoto(
        post_id="1000000009",
        owner_handle=SOURCE,
        canonical_url=f"https://www.tiktok.com/@{SOURCE}/photo/1000000009",
        image_urls=["https://cdn.example/9.jpeg"],
    )
    result = _result(_videos(10)).model_copy(update={"photos": [photo], "page_png": b"page"})

    class _Discovery:
        async def discover(self, request: ProfileDiscovery) -> DiscoveryResult:
            assert (request.handle, request.limit) == (SOURCE, 24)
            return result

    discoverer = ProfileDiscoverer({"tiktok": lambda access, scratch: _Discovery()})
    listing = await discoverer.creator("tiktok", SOURCE, 24)
    assert (len(listing.videos), listing.photos, listing.page_png) == (10, [photo], b"page")

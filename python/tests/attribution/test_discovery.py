"""Profile discovery honors the platform's access mode and leases a source account when needed."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.accounts.cookies import parse_cookies
from thoth_control_plane.acquisition.models import (
    DiscoveredVideo,
    DiscoveryDrops,
    DiscoveryReason,
    DiscoveryResult,
    ProfileDiscovery,
)
from thoth_control_plane.attribution.adapters.discovery import ProfileDiscoverer
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


@pytest.mark.asyncio
async def test_fallback_keeps_an_anonymous_success_without_an_account() -> None:
    fake = FakeDiscovery(_result([VIDEO]), _result([]))
    leases = FakeLeases("fallback")

    assert await _discover(fake, leases) == [VIDEO]
    assert (fake.built_with, leases.released) == ([None], [])


@pytest.mark.asyncio
async def test_anonymous_mode_and_no_store_never_lease() -> None:
    fake = FakeDiscovery(CAPTCHA, _result([VIDEO]))
    leases = FakeLeases("anonymous")

    assert await _discover(fake, leases) == []
    assert await _discover(fake, None) == []
    assert (fake.built_with, leases.released) == ([None, None], [])


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
    fake = FakeDiscovery(CAPTCHA, CAPTCHA)
    leases = FakeLeases("fallback")

    assert await _discover(fake, leases) == []
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

"""The creator port over ProfileDiscoverer (spec 5c-2, G3): a failure is None, a tool raises."""

from __future__ import annotations

import pytest

from thoth_control_plane.attribution.adapters.discovery import CreatorListing, DiscoveryBlocked
from thoth_control_plane.attribution.adapters.frames import ToolMissing
from thoth_control_plane.footage.adapters.creator import CreatorListings


class Discoverer:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.calls: list[tuple[str, str, int]] = []

    async def creator(self, platform: str, handle: str, limit: int) -> CreatorListing:
        self.calls.append((platform, handle, limit))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_a_listing_passes_through() -> None:
    listing = CreatorListing(videos=[], photos=[])
    discoverer = Discoverer(listing)
    assert await CreatorListings(discoverer).listing_of("x", "nasa", 24) is listing
    assert discoverer.calls == [("x", "nasa", 24)]


@pytest.mark.asyncio
async def test_a_blocked_listing_is_none() -> None:
    assert (
        await CreatorListings(Discoverer(DiscoveryBlocked("captcha"))).listing_of("tiktok", "a", 24)
        is None
    )


@pytest.mark.asyncio
async def test_a_missing_tool_is_never_swallowed() -> None:
    with pytest.raises(ToolMissing):
        await CreatorListings(Discoverer(ToolMissing("yt-dlp"))).listing_of("youtube", "a", 24)

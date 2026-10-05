"""YouTube channel discovery over a fake yt-dlp client: no network."""

from __future__ import annotations

from typing import Any

import pytest

from thoth_control_plane.acquisition.models import (
    AcquisitionReason,
    DiscoveryReason,
    ProfileDiscovery,
)
from thoth_control_plane.acquisition.youtube_discovery import (
    DETAIL_SPACING_SECONDS,
    YouTubeChannelDiscovery,
)
from thoth_control_plane.acquisition.youtube_service import YtDlpError


def _vid(n: int) -> str:
    return f"video{n:06d}"


def _listing(*pairs: tuple[int, int]) -> dict[str, Any]:
    return {"entries": [{"id": _vid(n), "view_count": views} for n, views in pairs]}


def _detail(n: int, likes: int, views: int, day: int) -> dict[str, Any]:
    return {
        "id": _vid(n),
        "title": f"title {n}",
        "uploader_id": "@nasa",
        "channel_id": "UCnasa0000000000000000aa",
        "timestamp": 1_700_000_000 + day * 86_400,
        "view_count": views,
        "like_count": likes,
        "duration": 30 + n,
        "live_status": "not_live",
    }


class FakeClient:
    def __init__(
        self,
        listings: dict[str, Any],
        details: dict[str, Any] | None = None,
    ) -> None:
        self.listings, self.details = listings, details or {}
        self.calls: list[str] = []

    async def listing(self, url: str, limit: int) -> dict[str, Any]:
        self.calls.append(url)
        result = self.listings.get(url.rsplit("/", 1)[-1])
        if isinstance(result, AcquisitionReason):
            raise YtDlpError(result)
        return result if result is not None else {"entries": []}

    async def extract(self, url: str, *, comments: bool) -> dict[str, Any]:
        assert comments is False
        self.calls.append(url)
        result = self.details.get(url.rsplit("=", 1)[-1])
        if isinstance(result, AcquisitionReason):
            raise YtDlpError(result)
        return result if result is not None else {}


async def _discover(client: FakeClient, handle: str = "nasa", limit: int = 30, sleeps=None):
    async def sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    discovery = YouTubeChannelDiscovery(client, sleep=sleep)
    return await discovery.discover(ProfileDiscovery(handle=handle, limit=limit))


@pytest.mark.asyncio
async def test_the_most_viewed_are_detailed_and_ranked() -> None:
    client = FakeClient(
        {"videos": _listing((1, 100), (2, 900)), "shorts": _listing((3, 5_000))},
        {
            _vid(1): _detail(1, likes=50, views=100, day=3),
            _vid(2): _detail(2, likes=10, views=900, day=1),
            _vid(3): _detail(3, likes=900, views=5_000, day=2),
        },
    )
    sleeps: list[float] = []
    result = await _discover(client, sleeps=sleeps)
    assert [v.post_id for v in result.videos] == [_vid(3), _vid(1), _vid(2)]
    first = result.videos[0]
    assert str(first.canonical_url) == f"https://www.youtube.com/watch?v={_vid(3)}"
    assert (first.owner_handle, first.caption, first.duration_seconds) == ("nasa", "title 3", 33.0)
    assert first.engagement == {"play": 5_000, "like": 900}
    assert first.published_at == "2023-11-16T22:13:20Z"
    assert client.calls[:2] == [
        "https://www.youtube.com/@nasa/videos",
        "https://www.youtube.com/@nasa/shorts",
    ]
    assert sleeps == [DETAIL_SPACING_SECONDS] * 3
    assert (result.pages, result.exhausted, result.reason) == (1, False, None)


@pytest.mark.asyncio
async def test_a_channel_without_shorts_still_discovers() -> None:
    client = FakeClient(
        {"videos": _listing((1, 100)), "shorts": AcquisitionReason.REQUEST_BLOCKED},
        {_vid(1): _detail(1, likes=5, views=100, day=1)},
    )
    result = await _discover(client)
    assert ([v.post_id for v in result.videos], result.reason) == ([_vid(1)], None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (AcquisitionReason.REQUEST_BLOCKED, DiscoveryReason.BLOCKED),
        (AcquisitionReason.REQUEST_TIMEOUT, DiscoveryReason.TIMEOUT),
    ],
)
async def test_both_tabs_failing_is_the_failure_reason(
    error: AcquisitionReason, reason: DiscoveryReason
) -> None:
    result = await _discover(FakeClient({"videos": error, "shorts": error}))
    assert (result.videos, result.pages, result.reason) == ([], 0, reason)


@pytest.mark.asyncio
async def test_empty_tabs_are_no_data() -> None:
    result = await _discover(FakeClient({}))
    assert (result.videos, result.reason) == ([], DiscoveryReason.NO_DATA)


@pytest.mark.asyncio
async def test_a_detail_failure_returns_what_was_gathered() -> None:
    client = FakeClient(
        {"videos": _listing((1, 900), (2, 500), (3, 100))},
        {
            _vid(1): _detail(1, likes=5, views=900, day=1),
            _vid(2): AcquisitionReason.REQUEST_BLOCKED,
        },
    )
    result = await _discover(client)
    assert [v.post_id for v in result.videos] == [_vid(1)]
    assert result.reason is DiscoveryReason.BLOCKED
    assert f"https://www.youtube.com/watch?v={_vid(3)}" not in client.calls


@pytest.mark.asyncio
async def test_unreadable_details_are_invalid() -> None:
    client = FakeClient(
        {"videos": _listing((1, 900), (2, 500))},
        {_vid(1): {"id": "someoneelse"}, _vid(2): _detail(2, likes=1, views=500, day=1)},
    )
    result = await _discover(client)
    assert [v.post_id for v in result.videos] == [_vid(2)]
    assert result.drops.invalid == 1


@pytest.mark.asyncio
async def test_limit_is_respected() -> None:
    pairs = [(n, n * 100) for n in range(1, 6)]
    details = {_vid(n): _detail(n, likes=n, views=n * 100, day=n) for n in range(1, 6)}
    result = await _discover(FakeClient({"videos": _listing(*pairs)}, details), limit=2)
    assert [v.post_id for v in result.videos] == [_vid(5), _vid(4)]

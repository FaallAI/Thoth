"""Instagram profile discovery over a fake fetcher: no network."""

from __future__ import annotations

import json
from typing import Any

import pytest

from thoth_control_plane.acquisition.instagram_discovery import (
    TIMELINE_KEY,
    InstagramProfileDiscovery,
)
from thoth_control_plane.acquisition.models import (
    AcquisitionReason,
    DiscoveryReason,
    ProfileDiscovery,
)
from thoth_control_plane.acquisition.threads_service import RequestFetchError


def _node(n: int, media_type: object = 2, likes: int | None = None, **extra: Any):
    return {
        "pk": str(3_100_000_000_000_000_000 + n),
        "code": f"code_{n:03d}",
        "media_type": media_type,
        "user": {"username": "nasa"},
        "caption": {"text": f"post {n}"},
        "taken_at": 1_700_000_000 + n * 3_600,
        "like_count": n * 10 if likes is None else likes,
        "comment_count": n,
        **extra,
    }


def _page(nodes: list[object], username: str = "nasa") -> list[str]:
    user = {"username": username, TIMELINE_KEY: {"edges": [{"node": n} for n in nodes]}}
    return [json.dumps({"require": [{"data": {"xig_user_by_username": user}}]})]


class FakeFetcher:
    def __init__(self, texts: list[str] | None = None, error: AcquisitionReason | None = None):
        self.texts, self.error, self.urls = texts or [], error, []

    async def fetch(self, url: str) -> list[str]:
        self.urls.append(url)
        if self.error is not None:
            raise RequestFetchError(self.error)
        return self.texts


async def _discover(fetcher: FakeFetcher, handle: str = "nasa", limit: int = 30):
    discovery = InstagramProfileDiscovery(fetcher)
    return await discovery.discover(ProfileDiscovery(handle=handle, limit=limit))


@pytest.mark.asyncio
async def test_videos_only_sorted_by_likes() -> None:
    nodes = [
        _node(1, likes=5),
        _node(2, media_type=1),
        _node(3, media_type=8),
        _node(4, likes=50),
        _node(5, likes=20),
    ]
    fetcher = FakeFetcher(_page(nodes))
    result = await _discover(fetcher)
    assert [v.post_id for v in result.videos] == [
        "3100000000000000004",
        "3100000000000000005",
        "3100000000000000001",
    ]
    first = result.videos[0]
    assert str(first.canonical_url) == "https://www.instagram.com/p/code_004/"
    assert first.owner_handle == "nasa"
    assert first.caption == "post 4"
    assert first.engagement == {"like": 50, "comment": 4}
    assert first.duration_seconds is None
    assert first.hashtags == []
    assert (result.drops.photo_posts, result.drops.invalid) == (2, 0)
    assert (result.pages, result.exhausted, result.reason) == (1, False, None)
    assert fetcher.urls == ["https://www.instagram.com/nasa/"]


@pytest.mark.asyncio
async def test_limit_is_respected() -> None:
    result = await _discover(FakeFetcher(_page([_node(n) for n in range(1, 6)])), limit=2)
    assert [v.engagement["like"] for v in result.videos] == [50, 40]


@pytest.mark.asyncio
async def test_at_most_twelve_whatever_the_limit() -> None:
    result = await _discover(FakeFetcher(_page([_node(n) for n in range(1, 16)])), limit=30)
    assert len(result.videos) == 12


@pytest.mark.asyncio
async def test_malformed_nodes_count_as_invalid() -> None:
    nodes = [
        _node(1, code="bad code"),
        _node(2, media_type="2"),
        _node(3, media_type=True),
        "not a dict",
        _node(4, pk="abc"),
        _node(5),
    ]
    result = await _discover(FakeFetcher(_page(nodes)))
    assert [v.post_id for v in result.videos] == ["3100000000000000005"]
    assert result.drops.invalid == 5


@pytest.mark.asyncio
async def test_duplicate_posts_keep_the_first() -> None:
    result = await _discover(FakeFetcher(_page([_node(1, likes=5), _node(1, likes=99)])))
    assert [v.engagement["like"] for v in result.videos] == [5]
    assert result.drops.invalid == 0


@pytest.mark.asyncio
async def test_handle_match_is_case_insensitive() -> None:
    fetcher = FakeFetcher(_page([_node(1)]))
    result = await _discover(fetcher, handle="NASA")
    assert [v.owner_handle for v in result.videos] == ["nasa"]
    assert fetcher.urls == ["https://www.instagram.com/NASA/"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "texts",
    [
        [json.dumps({"require": [{"data": {"xig_user_by_username": {"username": "nasa"}}}]})],
        # No node anywhere spells the requested handle (grid nodes would carry it).
        _page([], username="someone_else"),
        [],
    ],
)
async def test_no_user_or_timeline_is_no_data(texts: list[str]) -> None:
    result = await _discover(FakeFetcher(texts))
    assert (result.videos, result.reason) == ([], DiscoveryReason.NO_DATA)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (AcquisitionReason.REQUEST_BLOCKED, DiscoveryReason.BLOCKED),
        (AcquisitionReason.REQUEST_TIMEOUT, DiscoveryReason.TIMEOUT),
    ],
)
async def test_fetch_failures_map_to_reasons(
    error: AcquisitionReason, reason: DiscoveryReason
) -> None:
    result = await _discover(FakeFetcher(error=error))
    assert (result.videos, result.pages, result.reason) == ([], 0, reason)


@pytest.mark.asyncio
async def test_require_login_is_blocked() -> None:
    texts = [json.dumps({"require_login": True, "status": "fail"})]
    result = await _discover(FakeFetcher(texts))
    assert result.reason is DiscoveryReason.BLOCKED

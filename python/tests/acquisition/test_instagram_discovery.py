"""Instagram profile discovery over a fake fetcher: no network."""

from __future__ import annotations

import json
from typing import Any

import pytest

from thoth_control_plane.acquisition.instagram_discovery import (
    DETAIL_SPACING_SECONDS,
    TIMELINE_KEY,
    InstagramProfileDiscovery,
    rank_videos,
)
from thoth_control_plane.acquisition.models import (
    AcquisitionReason,
    DiscoveredVideo,
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
    """The profile URL serves `texts`; a post URL serves its `details` entry or nothing."""

    def __init__(
        self,
        texts: list[str] | None = None,
        error: AcquisitionReason | None = None,
        details: dict[str, list[str] | AcquisitionReason] | None = None,
    ):
        self.texts, self.error, self.details, self.urls = texts or [], error, details or {}, []

    async def fetch(self, url: str) -> list[str]:
        self.urls.append(url)
        if "/p/" not in url:
            if self.error is not None:
                raise RequestFetchError(self.error)
            return self.texts
        detail = self.details.get(url, [])
        if isinstance(detail, AcquisitionReason):
            raise RequestFetchError(detail)
        return detail


async def _discover(fetcher: FakeFetcher, handle: str = "nasa", limit: int = 30, sleeps=None):
    async def sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    discovery = InstagramProfileDiscovery(fetcher, sleep=sleep)
    return await discovery.discover(ProfileDiscovery(handle=handle, limit=limit))


def _bare(n: int) -> dict[str, Any]:
    """A grid node as the anonymous grid serves it: no counts and no date."""
    node = _node(n)
    for key in ("like_count", "comment_count", "taken_at"):
        node.pop(key)
    return node


def _post_page(n: int, likes: int, taken_at: int) -> list[str]:
    post = {
        "code": f"code_{n:03d}",
        "pk": str(3_100_000_000_000_000_000 + n),
        "user": {"username": "nasa"},
        "like_count": likes,
        "comment_count": 3,
        "taken_at": taken_at,
    }
    return [json.dumps({"require": [{"xig_polaris_media": {"if_not_gated_logged_out": post}}]})]


def _url(n: int) -> str:
    return f"https://www.instagram.com/p/code_{n:03d}/"


def _video(n: int, **fields: Any) -> DiscoveredVideo:
    return DiscoveredVideo(
        post_id=str(3_100_000_000_000_000_000 + n),
        owner_handle="nasa",
        canonical_url=_url(n),
        **fields,
    )


@pytest.mark.asyncio
async def test_videos_only_ranked() -> None:
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
    assert fetcher.urls == ["https://www.instagram.com/nasa/", _url(4), _url(5), _url(1)]


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
    assert fetcher.urls[0] == "https://www.instagram.com/NASA/"


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


def test_rank_is_the_mean_of_like_view_and_recency_ranks() -> None:
    old_liked = _video(1, engagement={"like": 100}, published_at="2024-01-01T00:00:00Z")
    new_viewed = _video(
        2, engagement={"like": 10, "play": 5_000}, published_at="2024-03-01T00:00:00Z"
    )
    middle = _video(3, engagement={"like": 50, "play": 1_000}, published_at="2024-02-01T00:00:00Z")
    # like: 1, 0, .5; play: missing (lowest), 1, 0; date: 0, 1, .5 -> 1, 2, 1.
    ranked = rank_videos([old_liked, new_viewed, middle])
    assert [v.post_id for v in ranked] == [
        new_viewed.post_id,
        old_liked.post_id,  # ties keep the grid order
        middle.post_id,
    ]


def test_rank_without_any_signal_keeps_the_grid_order() -> None:
    videos = [_video(n, engagement={"like": 7}) for n in (3, 1, 2)]
    assert rank_videos(videos) == videos


@pytest.mark.asyncio
async def test_detail_pages_supply_the_signals_the_grid_lacks() -> None:
    details = {
        _url(1): _post_page(1, likes=900, taken_at=1_700_000_000),
        _url(2): _post_page(2, likes=100, taken_at=1_700_900_000),
        # _url(3) serves no post node: the video stays as the grid had it.
    }
    sleeps: list[float] = []
    fetcher = FakeFetcher(_page([_bare(1), _bare(2), _bare(3)]), details=details)
    result = await _discover(fetcher, sleeps=sleeps)
    assert [v.engagement for v in result.videos] == [
        {"like": 900, "comment": 3},
        {"like": 100, "comment": 3},
        {},
    ]
    assert result.videos[1].published_at == "2023-11-25T08:13:20Z"
    assert result.videos[2].published_at is None
    assert sleeps == [DETAIL_SPACING_SECONDS] * 3
    assert fetcher.urls[1:] == [_url(1), _url(2), _url(3)]
    assert result.reason is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (AcquisitionReason.REQUEST_BLOCKED, DiscoveryReason.BLOCKED),
        (AcquisitionReason.REQUEST_TIMEOUT, DiscoveryReason.TIMEOUT),
    ],
)
async def test_detail_failure_stops_and_returns_a_partial_result(
    error: AcquisitionReason, reason: DiscoveryReason
) -> None:
    details: dict[str, list[str] | AcquisitionReason] = {
        _url(1): _post_page(1, likes=5, taken_at=1_700_000_000),
        _url(2): error,
    }
    fetcher = FakeFetcher(_page([_bare(1), _bare(2), _bare(3)]), details=details)
    result = await _discover(fetcher)
    assert fetcher.urls[1:] == [_url(1), _url(2)]
    assert len(result.videos) == 3
    assert result.reason is reason
    assert result.videos[0].engagement == {"like": 5, "comment": 3}


@pytest.mark.asyncio
async def test_a_login_wall_on_a_detail_page_is_blocked() -> None:
    details: dict[str, list[str] | AcquisitionReason] = {
        _url(1): [json.dumps({"require_login": True, "status": "fail"})],
    }
    fetcher = FakeFetcher(_page([_bare(1), _bare(2)]), details=details)
    result = await _discover(fetcher)
    assert fetcher.urls[1:] == [_url(1)]
    assert len(result.videos) == 2
    assert result.reason is DiscoveryReason.BLOCKED

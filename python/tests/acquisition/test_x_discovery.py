"""X profile discovery over a fake fetcher: no network."""

from __future__ import annotations

import json
from typing import Any

import pytest

from thoth_control_plane.acquisition.models import (
    AcquisitionReason,
    DiscoveryReason,
    ProfileDiscovery,
)
from thoth_control_plane.acquisition.threads_service import RequestFetchError
from thoth_control_plane.acquisition.x_discovery import XProfileDiscovery


def _tweet(
    n: int,
    author: str = "nasa",
    video: bool = True,
    likes: int = 10,
    views: str = "100",
    **extra: Any,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "__typename": "Tweet",
        "rest_id": str(1_800_000_000_000_000_000 + n),
        "core": {"user_results": {"result": {"core": {"screen_name": author}}}},
        "details": {"full_text": f"post {n}", "created_at_ms": 1_700_000_000_000 + n * 3_600_000},
        "counts": {"favorite_count": likes, "reply_count": 1, "retweet_count": 2},
        "views": {"count": views},
    }
    if video:
        variants = [{"content_type": "video/mp4", "url": f"https://video.twimg.com/{n}.mp4"}]
        node["media_entities2"] = [{"type": "video", "video_info": {"variants": variants}}]
    node.update(extra)
    return node


def _page(*tweets: dict[str, Any]) -> str:
    timeline = [{"content": {"tweet": tweet}} for tweet in tweets]
    # Compact JSON is a subset of the seroval literals the decoder reads.
    root = json.dumps({"timeline": timeline}, separators=(",", ":"))
    return f'<script>($R=>$R[0].next({root}))($R["k"])</script>'


class FakeFetcher:
    def __init__(self, html: str = "", error: AcquisitionReason | None = None) -> None:
        self.html, self.error, self.urls = html, error, []

    async def page(self, url: str) -> str:
        self.urls.append(url)
        if self.error is not None:
            raise RequestFetchError(self.error)
        return self.html


async def _discover(fetcher: FakeFetcher, handle: str = "nasa", limit: int = 30):
    discovery = XProfileDiscovery(fetcher)
    return await discovery.discover(ProfileDiscovery(handle=handle, limit=limit))


def _id(n: int) -> str:
    return str(1_800_000_000_000_000_000 + n)


@pytest.mark.asyncio
async def test_own_videos_ranked_by_likes_views_and_recency() -> None:
    page = _page(
        _tweet(1, likes=500, views="9000"),
        _tweet(2, video=False),
        _tweet(3, likes=10, views="50"),
        _tweet(4, likes=200, views="4000"),
    )
    fetcher = FakeFetcher(page)
    result = await _discover(fetcher)
    assert [v.post_id for v in result.videos] == [_id(1), _id(4), _id(3)]
    first = result.videos[0]
    assert str(first.canonical_url) == f"https://x.com/nasa/status/{_id(1)}"
    assert first.owner_handle == "nasa"
    assert first.caption == "post 1"
    assert first.published_at == "2023-11-14T23:13:20Z"
    assert first.engagement == {"like": 500, "comment": 1, "share": 2, "play": 9000}
    assert (result.drops.photo_posts, result.drops.invalid) == (1, 0)
    assert (result.pages, result.exhausted, result.reason) == (1, False, None)
    assert fetcher.urls == ["https://x.com/nasa"]


@pytest.mark.asyncio
async def test_handle_case_reposts_and_other_authors() -> None:
    original = _tweet(5, author="someone_else")
    page = _page(
        _tweet(1, author="nasa"),
        _tweet(2, author="nasa", retweeted_status_results={"result": original}),
        _tweet(3, author="someone_else"),
    )
    result = await _discover(FakeFetcher(page), handle="NASA")
    assert [(v.post_id, v.owner_handle) for v in result.videos] == [(_id(1), "nasa")]
    assert result.drops.invalid == 3


@pytest.mark.asyncio
async def test_limit_is_respected() -> None:
    page = _page(*(_tweet(n, likes=n * 10) for n in range(1, 6)))
    result = await _discover(FakeFetcher(page), limit=2)
    assert [v.post_id for v in result.videos] == [_id(5), _id(4)]


@pytest.mark.asyncio
@pytest.mark.parametrize("html", ["", "<html></html>", "<script>($R=>$R[0].next({a:</script>"])
async def test_no_timeline_is_no_data(html: str) -> None:
    result = await _discover(FakeFetcher(html))
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
async def test_a_malformed_tweet_is_invalid() -> None:
    page = _page(_tweet(1, author="bad name"), _tweet(2, rest_id="abc"), _tweet(3))
    result = await _discover(FakeFetcher(page))
    assert [v.post_id for v in result.videos] == [_id(3)]
    assert result.drops.invalid == 2

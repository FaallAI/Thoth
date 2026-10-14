"""Keyword search for footage: TikTok and YouTube per query, X in one signed-in session."""

from __future__ import annotations

from typing import Any

import pytest

from thoth_control_plane.acquisition.models import (
    DiscoveredVideo,
    DiscoveryDrops,
    DiscoveryReason,
    DiscoveryResult,
    KeywordDiscovery,
)
from thoth_control_plane.attribution.adapters.discovery import ProfileDiscoverer
from thoth_control_plane.footage.adapters.search import PlatformSearch
from thoth_control_plane.footage.adapters.x_search import XSearchDiscovery, parse_search
from thoth_control_plane.footage.adapters.youtube import YouTubeSearchDiscovery


def _tweet(rest_id: str, *, video: bool = True, retweet: bool = False) -> dict[str, Any]:
    media = [
        {
            "type": "video",
            "video_info": {"duration_millis": 42_000, "aspect_ratio": [9, 16], "variants": []},
        }
    ]
    legacy: dict[str, Any] = {
        "full_text": f"banjir di kemang {rest_id} https://t.co/abc",
        "created_at": "Wed Oct 14 10:00:00 +0000 2026",
        "favorite_count": 12,
        "reply_count": 3,
        "retweet_count": 4,
        "lang": "in",
    }
    if video:
        legacy["extended_entities"] = {"media": media}
    if retweet:
        legacy["retweeted_status_result"] = {"result": {"__typename": "Tweet"}}
    return {
        "__typename": "Tweet",
        "rest_id": rest_id,
        "core": {"user_results": {"result": {"core": {"screen_name": "warga_kemang"}}}},
        "legacy": legacy,
        "views": {"count": "1500"},
    }


def _timeline(*tweets: dict[str, Any]) -> dict[str, Any]:
    entries = [
        {"content": {"itemContent": {"tweet_results": {"result": tweet}}}} for tweet in tweets
    ]
    return {
        "data": {
            "search_by_raw_query": {
                "search_timeline": {
                    "timeline": {
                        "instructions": [{"type": "TimelineAddEntries", "entries": entries}]
                    }
                }
            }
        }
    }


def test_parse_search_keeps_video_tweets_in_order() -> None:
    result = parse_search(
        [
            _timeline(
                _tweet("1000000001"),
                _tweet("1000000002", video=False),
                _tweet("1000000003", retweet=True),
                _tweet("1000000004"),
            )
        ],
        limit=8,
    )
    assert [v.post_id for v in result.videos] == ["1000000001", "1000000004"]
    first = result.videos[0]
    assert str(first.canonical_url) == "https://x.com/warga_kemang/status/1000000001"
    assert first.caption == "banjir di kemang 1000000001"
    assert first.duration_seconds == 42.0
    assert first.published_at == "2026-10-14T10:00:00Z"
    assert first.engagement == {"like": 12, "comment": 3, "share": 4, "play": 1500}
    assert result.drops == DiscoveryDrops(photo_posts=1, invalid=1)


def test_an_empty_timeline_is_an_answer_not_a_failure() -> None:
    result = parse_search([_timeline()], limit=8)
    assert result.videos == [] and result.reason is None and result.exhausted


class _Entry:
    def __init__(self, body: dict[str, Any], status: int = 200) -> None:
        self.status = status
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


class _Response:
    def __init__(self, captured: list[Any]) -> None:
        self.captured_xhr = captured
        self.status = 200


class _Session:
    """One browser session; each fetch answers with the next page's captured responses."""

    def __init__(self, pages: list[list[Any]], seen: list[str]) -> None:
        self._pages = list(pages)
        self._seen = seen
        self.closed = False

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *args: object) -> None:
        self.closed = True

    async def fetch(self, url: str, **kwargs: object) -> _Response:
        self._seen.append(url)
        return _Response(self._pages.pop(0) if self._pages else [])


def _x(pages: list[list[Any]], seen: list[str], sessions: list[_Session]) -> XSearchDiscovery:
    def factory(**kwargs: Any) -> _Session:
        assert kwargs["capture_xhr"] == r"/SearchTimeline"
        session = _Session(pages, seen)
        sessions.append(session)
        return session

    pauses: list[float] = []

    async def sleep(seconds: float) -> None:
        pauses.append(seconds)

    discovery = XSearchDiscovery(factory, sleep=sleep, pause=lambda: 7.0)
    discovery.pauses = pauses  # type: ignore[attr-defined]
    return discovery


async def test_one_session_searches_every_query_with_a_pause_between() -> None:
    seen: list[str] = []
    sessions: list[_Session] = []
    discovery = _x(
        [[_Entry(_timeline(_tweet("1000000001")))], [_Entry(_timeline())], []], seen, sessions
    )
    batch = await discovery.search_many(["banjir kemang", "topik sepi", "tanpa respons"], 8)
    assert len(sessions) == 1 and sessions[0].closed
    assert seen == [
        "https://x.com/search?q=banjir%20kemang&f=video&src=typed_query",
        "https://x.com/search?q=topik%20sepi&f=video&src=typed_query",
        "https://x.com/search?q=tanpa%20respons&f=video&src=typed_query",
    ]
    assert discovery.pauses == [7.0, 7.0]  # type: ignore[attr-defined]
    assert [v.post_id for v in batch.found["banjir kemang"]] == ["1000000001"]
    assert batch.found["topik sepi"] == []  # an empty answer is cached as empty
    assert "tanpa respons" not in batch.found  # nothing captured: unknown, never cached
    assert not batch.refused and not batch.unavailable


@pytest.mark.parametrize(
    "refusal", [_Entry({}, status=429), _Entry({"errors": [{"code": 88, "message": "Rate limit"}]})]
)
async def test_a_refusal_stops_the_remaining_queries(refusal: _Entry) -> None:
    seen: list[str] = []
    batch = await _x([[refusal], [_Entry(_timeline(_tweet("1000000001")))]], seen, []).search_many(
        ["pertama", "kedua"], 8
    )
    assert batch.refused and batch.found == {} and len(seen) == 1


async def test_a_browser_that_cannot_start_is_unavailable() -> None:
    def broken(**kwargs: Any) -> Any:
        raise RuntimeError("no browser")

    batch = await XSearchDiscovery(broken).search_many(["banjir"], 8)
    assert batch.unavailable and not batch.refused and batch.found == {}


class _Lease:
    account_id = "account-1"
    access = None
    leased_until = None


class _Leases:
    def __init__(self, free: bool = True) -> None:
        self.free = free
        self.leased: list[str] = []
        self.outcomes: list[object] = []

    async def mode(self, platform: str) -> str:
        return "fallback"

    async def lease(self, platform: str) -> _Lease | None:
        self.leased.append(platform)
        return _Lease() if self.free else None

    async def release(self, lease: object, outcome: object) -> None:
        self.outcomes.append(outcome)


class _XStub:
    def __init__(self, batch: Any) -> None:
        self.batch = batch
        self.calls: list[list[str]] = []

    async def search_many(self, queries: list[str], limit: int) -> Any:
        self.calls.append(list(queries))
        return self.batch


def _video(n: int) -> DiscoveredVideo:
    return DiscoveredVideo(
        post_id=f"100{n}", owner_handle="warga", canonical_url=f"https://x.com/warga/status/100{n}"
    )


def _platform_search(leases: _Leases, stub: _XStub) -> PlatformSearch:
    return PlatformSearch(
        ProfileDiscoverer({}, leases=leases),  # type: ignore[arg-type]
        leases,  # type: ignore[arg-type]
        x_search=lambda access: stub,
    )


async def test_x_takes_one_lease_for_every_query() -> None:
    from thoth_control_plane.footage.adapters.x_search import XSearchBatch

    leases = _Leases()
    stub = _XStub(XSearchBatch(found={"a": [_video(1)], "b": []}, refused=False, unavailable=False))
    batch = await _platform_search(leases, stub).search("x", ["a", "b", "bad\x00query"], 8)
    assert leases.leased == ["x"] and stub.calls == [["a", "b"]]  # the refused query never runs
    assert batch.found == {"a": [_video(1)], "b": []} and not batch.failed


@pytest.mark.parametrize(
    ("found", "refused", "outcome", "failed"),
    [
        ({"a": [_video(1)]}, False, "success", False),
        ({"a": []}, False, None, False),  # an empty search is an answer (ruling P3)
        ({}, True, "blocked", True),  # only a refusal cools the account down
    ],
)
async def test_only_a_refusal_cools_the_x_account_down(
    found: dict[str, list[DiscoveredVideo]], refused: bool, outcome: str | None, failed: bool
) -> None:
    from thoth_control_plane.footage.adapters.x_search import XSearchBatch

    leases = _Leases()
    stub = _XStub(XSearchBatch(found=found, refused=refused, unavailable=False))
    batch = await _platform_search(leases, stub).search("x", ["a"], 8)
    assert leases.outcomes == [outcome] and batch.failed is failed


async def test_no_free_x_account_means_no_signed_out_search() -> None:
    from thoth_control_plane.footage.adapters.x_search import XSearchBatch

    leases = _Leases(free=False)
    stub = _XStub(XSearchBatch(found={}, refused=False, unavailable=False))
    batch = await _platform_search(leases, stub).search("x", ["a"], 8)
    assert stub.calls == [] and batch.failed and batch.found == {}


async def test_tiktok_searches_each_query_and_keeps_what_it_found() -> None:
    calls: list[str] = []

    class Discovery:
        async def discover(self, request: KeywordDiscovery) -> DiscoveryResult:
            calls.append(request.query)
            if request.query == "boom":
                raise RuntimeError("browser died")
            return DiscoveryResult(
                kind="keyword", videos=[], pages=1, exhausted=True, drops=DiscoveryDrops()
            )

    leases = _Leases()
    search = PlatformSearch(
        ProfileDiscoverer({"tiktok": lambda access, scratch: Discovery()}, leases=None),
        leases,  # type: ignore[arg-type]
    )
    batch = await search.search("tiktok", ["a", "bad\x00query", "boom", "never"], 8)
    assert calls == ["a", "boom"]
    assert batch.found == {"a": []} and batch.failed


class _YtClient:
    def __init__(self) -> None:
        self.extracted: list[str] = []

    async def listing(self, url: str, limit: int) -> dict[str, Any]:
        assert url == "ytsearch8:banjir kemang" and limit == 8
        return {"entries": [{"id": f"vid{n:08d}", "view_count": n * 100} for n in range(1, 9)]}

    async def extract(self, url: str, *, comments: bool) -> dict[str, Any]:
        self.extracted.append(url)
        return {
            "id": url[-11:],
            "title": "banjir kemang",
            "duration": 50,
            "channel": "c",
            "uploader_id": "@kanal",
            "channel_id": "UC123",
            "view_count": 5,
            "like_count": 1,
        }


async def test_youtube_search_details_the_five_most_viewed() -> None:
    client = _YtClient()

    async def no_sleep(seconds: float) -> None:
        return None

    result = await YouTubeSearchDiscovery(client, sleep=no_sleep).discover(  # type: ignore[arg-type]
        KeywordDiscovery(query="banjir kemang", limit=8)
    )
    assert len(client.extracted) == 5
    assert client.extracted[0].endswith("vid00000008")
    assert result.kind == "keyword"
    assert len(result.videos) == 5


@pytest.mark.parametrize(
    ("videos", "reason", "leased"),
    [
        (3, None, []),  # a short search answer is complete: no lease (ruling P5)
        (0, DiscoveryReason.CAPTCHA, ["tiktok"]),  # a captcha still leases once under fallback
    ],
)
async def test_a_keyword_search_leases_only_on_a_block(
    videos: int, reason: DiscoveryReason | None, leased: list[str]
) -> None:
    class Discovery:
        async def discover(self, request: KeywordDiscovery) -> DiscoveryResult:
            return DiscoveryResult(
                kind="keyword",
                videos=[_video(n) for n in range(videos)],
                pages=1,
                exhausted=True,
                drops=DiscoveryDrops(),
                reason=reason,
            )

    leases = _Leases(free=False)
    search = PlatformSearch(
        ProfileDiscoverer({"tiktok": lambda access, scratch: Discovery()}, leases=leases),  # type: ignore[arg-type]
        leases,  # type: ignore[arg-type]
    )
    await search.search("tiktok", ["banjir"], 8)
    assert leases.leased == leased


def test_keyword_discovery_refuses_control_characters() -> None:
    # Task 8 relies on this: a query KeywordDiscovery refuses is skipped, not sent.
    with pytest.raises(ValueError):
        KeywordDiscovery(query="\x00", limit=8)

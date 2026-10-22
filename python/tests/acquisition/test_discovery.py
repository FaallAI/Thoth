import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from thoth_control_plane.acquisition import discovery as discovery_module
from thoth_control_plane.acquisition.browser import (
    FETCH_TIMEOUT_MS,
    FETCH_WAIT_MS,
    active_scrapling_session_count,
)
from thoth_control_plane.acquisition.cards import PROFILE_PAGE_JS
from thoth_control_plane.acquisition.discovery import (
    CAPTCHA_SELECTOR,
    EXPLORE_URL,
    PROFILE_GRID_ITEMS,
    PROFILE_HEADER,
    XHR_PATTERNS,
    ScraplingDiscoveryBrowser,
    _assemble,
    parse_discovery_page,
)
from thoth_control_plane.acquisition.models import (
    DiscoveryDrops,
    DiscoveryReason,
    KeywordDiscovery,
    ProfileDiscovery,
    TrendingDiscovery,
)


def _item(post_id: object = "1000000001", handle: str = "creator", **extra: object) -> dict:
    item = {
        "id": post_id,
        "desc": "a caption #cats",
        "createTime": 1709287200,
        "author": {"uniqueId": handle, "secUid": "MS4wLjABAAAA", "verified": False},
        "stats": {
            "playCount": 10,
            "diggCount": 5,
            "commentCount": 2,
            "shareCount": 1,
            "collectCount": 3,
        },
        "video": {"duration": 15},
        "challenges": [{"title": "cats"}],
    }
    item.update(extra)
    return item


def _list_body(items: list, has_more: object = True) -> bytes:
    return json.dumps({"statusCode": 0, "itemList": items, "hasMore": has_more}).encode()


def _search_body(entries: list, has_more: object = 1) -> bytes:
    return json.dumps({"status_code": 0, "data": entries, "has_more": has_more}).encode()


@pytest.mark.parametrize("kind", ["profile", "trending"])
def test_list_pages_reduce_to_validated_videos(kind: str) -> None:
    page = parse_discovery_page(kind, _list_body([_item()]))

    assert page.reason is None
    assert page.has_more is True
    assert page.drops == DiscoveryDrops()
    [video] = page.videos
    assert video.post_id == "1000000001"
    assert video.owner_handle == "creator"
    assert str(video.canonical_url) == "https://www.tiktok.com/@creator/video/1000000001"
    assert video.caption == "a caption #cats"
    assert video.published_at == "2024-03-01T10:00:00Z"
    assert video.duration_seconds == 15.0
    assert video.engagement == {"play": 10, "like": 5, "comment": 2, "share": 1, "collect": 3}
    assert video.hashtags == ["cats"]


def test_search_pages_keep_only_video_entries() -> None:
    body = _search_body(
        [
            {"type": 1, "item": _item("1000000001"), "common": {}},
            {"type": 4, "user_list": [{"uniqueId": "someone"}]},
            {"type": 1, "item": _item("1000000002"), "common": {}},
        ]
    )

    page = parse_discovery_page("keyword", body)

    assert [video.post_id for video in page.videos] == ["1000000001", "1000000002"]
    assert page.drops == DiscoveryDrops()
    assert page.has_more is True


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, True), (1, True), (False, False), (0, False), (None, False), ("true", False)],
)
def test_has_more_is_true_only_for_true_or_one(value: object, expected: bool) -> None:
    assert (
        parse_discovery_page("profile", _list_body([_item()], has_more=value)).has_more is expected
    )


def test_ads_photo_posts_and_invalid_items_are_dropped_and_counted() -> None:
    items = [
        _item("1000000001"),
        _item("1000000002", isAd=True),
        _item("1000000003", imagePost={"images": []}),
        _item(1000000004),
        _item("12"),
        _item("1000000006", author={}),
        # The model admits YouTube's string ids; TikTok ids stay numeric.
        _item("abcdefghijk"),
        "junk",
    ]

    page = parse_discovery_page("profile", _list_body(items))

    assert [video.post_id for video in page.videos] == ["1000000001"]
    assert page.drops == DiscoveryDrops(ads=1, photo_posts=1, invalid=5)


def test_an_ad_that_is_also_a_photo_post_counts_as_an_ad() -> None:
    page = parse_discovery_page("profile", _list_body([_item(isAd=True, imagePost={})]))

    assert page.drops == DiscoveryDrops(ads=1)


@pytest.mark.parametrize("body", [b"", b"<html></html>", b"[]", b"\xff\xfe"])
def test_empty_or_non_object_bodies_are_captcha(body: bytes) -> None:
    page = parse_discovery_page("keyword", body)

    assert page.reason is DiscoveryReason.CAPTCHA
    assert page.videos == []
    assert page.has_more is False


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("profile", {"statusCode": 10201, "itemList": [_item()], "hasMore": True}),
        ("keyword", {"status_code": 5, "data": [], "has_more": 1}),
    ],
)
def test_non_zero_status_is_blocked(kind: str, payload: dict) -> None:
    page = parse_discovery_page(kind, json.dumps(payload).encode())

    assert page.reason is DiscoveryReason.BLOCKED
    assert page.videos == []


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("profile", {"statusCode": "0", "itemList": [_item()], "hasMore": False}),
        ("keyword", {"status_code": "0", "data": [{"type": 1, "item": _item()}], "has_more": 0}),
    ],
)
def test_a_string_zero_status_is_ok(kind: str, payload: dict) -> None:
    page = parse_discovery_page(kind, json.dumps(payload).encode())

    assert page.reason is None
    assert len(page.videos) == 1


@pytest.mark.parametrize("status", [403, 429, 500, 302])
def test_a_non_2xx_response_is_blocked_whatever_its_body(status: int) -> None:
    for body in (_list_body([_item()]), b"<html>denied</html>"):
        page = parse_discovery_page("profile", body, status)

        assert page.reason is DiscoveryReason.BLOCKED
        assert page.videos == []


def test_canonical_url_is_rebuilt_never_taken_from_tiktok() -> None:
    item = _item(shareUrl="https://evil.example/@creator/video/1000000001")

    [video] = parse_discovery_page("profile", _list_body([item])).videos

    assert str(video.canonical_url) == "https://www.tiktok.com/@creator/video/1000000001"


def test_caption_is_truncated_and_a_non_string_desc_is_empty() -> None:
    items = [_item("1000000001", desc="x" * 10_050), _item("1000000002", desc=None)]

    long_caption, no_caption = parse_discovery_page("profile", _list_body(items)).videos

    assert len(long_caption.caption) == 10_000
    assert no_caption.caption == ""


@pytest.mark.parametrize("duration", [True, -1, float("nan"), float("inf"), "15"])
def test_invalid_duration_is_none_and_the_video_is_kept(duration: object) -> None:
    [video] = parse_discovery_page(
        "profile", _list_body([_item(video={"duration": duration})])
    ).videos

    assert video.duration_seconds is None


def test_bad_hashtags_are_dropped_and_the_video_is_kept() -> None:
    longest = "x" * 100
    challenges = [
        {"title": ""},
        {"title": longest + "x"},
        {"title": 5},
        "junk",
        {"title": "ok"},
        {"title": longest},
    ]

    [video] = parse_discovery_page("profile", _list_body([_item(challenges=challenges)])).videos

    assert video.hashtags == ["ok", longest]


def test_missing_stats_yield_empty_engagement() -> None:
    item = _item()
    del item["stats"]

    [video] = parse_discovery_page("trending", _list_body([item])).videos

    assert video.engagement == {}


API_URLS = {
    "profile": "https://www.tiktok.com/api/post/item_list/?aid=1988&count=16",
    "keyword": "https://www.tiktok.com/api/search/general/full/?aid=1988",
    "trending": "https://www.tiktok.com/api/explore/item_list/?aid=1988",
}
WARM_UP_ID = "1999999999"


def _body_for(kind: str, ids: list[str], has_more: bool = True) -> bytes:
    items = [_item(post_id) for post_id in ids]
    if kind == "keyword":
        return _search_body([{"type": 1, "item": item} for item in items], int(has_more))
    return _list_body(items, has_more)


def _pages(kind: str, count: int, per_page: int = 3, last_has_more: bool = True) -> list[bytes]:
    bodies = []
    for page in range(count):
        ids = [str(1_000_000_000 + page * per_page + index) for index in range(per_page)]
        bodies.append(_body_for(kind, ids, last_has_more or page < count - 1))
    return bodies


class FakeNetworkResponse:
    def __init__(self, url: str, body: bytes, fail: bool = False) -> None:
        self.url = url
        self._body = body
        self._fail = fail

    async def body(self) -> bytes:
        if self._fail:
            raise RuntimeError("Target closed")
        return self._body


class FakePage:
    """Emits one list response on load and one per scroll, like TikTok's infinite list."""

    def __init__(self, api_url: str, bodies: list[bytes], **flags: object) -> None:
        self.api_url = api_url
        self.pending = list(bodies)
        self.emitted: list[bytes] = []
        self.captcha = flags.get("captcha", False)
        self.body_error = flags.get("body_error", False)
        self.wheel_error = flags.get("wheel_error")
        self.hang = flags.get("hang", False)
        # The profile grid (spec 5c-2): with page_rect, grid items show and the page is cropped.
        self.page_rect = flags.get("page_rect", False)
        self.clips: list[dict] = []
        self.scrolls = 0
        self.handlers: list = []
        self.mouse = SimpleNamespace(wheel=self._wheel)

    def on(self, event: str, handler) -> None:
        assert event == "response"
        self.handlers.append(handler)

    def emit(self) -> None:
        if not self.pending:
            return
        body = self.pending.pop(0)
        self.emitted.append(body)
        for handler in self.handlers:
            # An unrelated response must be ignored by the pattern filter.
            handler(FakeNetworkResponse("https://www.tiktok.com/api/user/detail/", b"{}"))
            handler(FakeNetworkResponse(self.api_url, body, fail=bool(self.body_error)))

    async def _wheel(self, delta_x: int, delta_y: int) -> None:
        if self.wheel_error is not None:
            raise self.wheel_error
        if self.hang:
            await asyncio.Event().wait()
        self.scrolls += 1
        self.emit()

    async def wait_for_timeout(self, timeout: int) -> None:
        return None

    async def query_selector(self, selector: str) -> object | None:
        assert selector == CAPTCHA_SELECTOR
        return object() if self.captcha else None

    def locator(self, selector: str) -> SimpleNamespace:
        assert selector in (PROFILE_GRID_ITEMS, PROFILE_HEADER)

        async def count() -> int:
            return 6 if self.page_rect else 0

        async def bounding_box() -> dict:
            return {"x": 0, "y": 0, "width": 800, "height": 300}

        handle = SimpleNamespace(count=count, bounding_box=bounding_box)
        handle.first = handle
        return handle

    async def evaluate(self, script: str, arg: object = None) -> object:
        assert script == PROFILE_PAGE_JS
        return {"x": 0, "y": 0, "width": 800, "height": 900} if self.page_rect else None

    async def screenshot(self, **kwargs: object) -> bytes:
        self.clips.append(kwargs["clip"])
        self.scale = kwargs.get("scale")
        return b"page-png"


class FakeSession:
    def __init__(self, kind: str, bodies: list[bytes], **flags: object) -> None:
        self.page = FakePage(API_URLS[kind], bodies, **flags)
        self.css_captcha = flags.get("css_captcha", False)
        self.fetch_error = flags.get("fetch_error")
        self.enter_error = flags.get("enter_error")
        self.exit_error = flags.get("exit_error")
        self.status = flags.get("status", 200)
        self.factory_kwargs: dict = {}
        self.fetched: list[str] = []
        self.fetch_kwargs: list[dict] = []
        self.exited = False

    async def __aenter__(self) -> "FakeSession":
        if self.enter_error is not None:
            raise self.enter_error
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.exited = True
        if self.exit_error is not None:
            raise self.exit_error

    async def fetch(self, url: str, **kwargs: object) -> SimpleNamespace:
        self.fetched.append(url)
        self.fetch_kwargs.append(kwargs)
        if self.fetch_error is not None:
            raise self.fetch_error
        if "page_action" not in kwargs:
            warm_up = SimpleNamespace(
                url=API_URLS["keyword"], body=_body_for("keyword", [WARM_UP_ID])
            )
            return SimpleNamespace(captured_xhr=[warm_up], css=lambda selector: [])
        await kwargs["page_setup"](self.page)
        self.page.emit()
        await kwargs["page_action"](self.page)
        captured = [
            SimpleNamespace(url=self.page.api_url, status=self.status, body=body)
            for body in self.page.emitted
        ]
        rendered = ["captcha"] if self.css_captcha else []
        return SimpleNamespace(captured_xhr=captured, css=lambda selector: rendered)


def _browser(session: FakeSession) -> ScraplingDiscoveryBrowser:
    def factory(**kwargs: object) -> FakeSession:
        session.factory_kwargs = kwargs
        return session

    return ScraplingDiscoveryBrowser(session_factory=factory)


@pytest.mark.parametrize(
    ("request_model", "url"),
    [
        (ProfileDiscovery(handle="creator"), "https://www.tiktok.com/@creator"),
        (
            KeywordDiscovery(query="anak & kucing/2"),
            "https://www.tiktok.com/search?q=anak%20%26%20kucing%2F2",
        ),
        (
            KeywordDiscovery(query="kucing 🐱"),
            "https://www.tiktok.com/search?q=kucing%20%F0%9F%90%B1",
        ),
        (TrendingDiscovery(), "https://www.tiktok.com/explore"),
    ],
)
async def test_each_kind_opens_its_ordinary_page(request_model, url: str) -> None:
    session = FakeSession(request_model.kind, _pages(request_model.kind, 1, last_has_more=False))

    await _browser(session).discover(request_model)

    assert session.fetched[-1] == url


async def test_keyword_warms_up_on_explore_and_discards_that_visit() -> None:
    session = FakeSession("keyword", _pages("keyword", 1, last_has_more=False))

    result = await _browser(session).discover(KeywordDiscovery(query="cats"))

    assert session.fetched == [EXPLORE_URL, "https://www.tiktok.com/search?q=cats"]
    assert "page_action" not in session.fetch_kwargs[0]
    assert "page_setup" not in session.fetch_kwargs[0]
    assert WARM_UP_ID not in {video.post_id for video in result.videos}
    assert len(result.videos) == 3


@pytest.mark.parametrize("request_model", [ProfileDiscovery(handle="creator"), TrendingDiscovery()])
async def test_profile_and_trending_need_no_warm_up(request_model) -> None:
    session = FakeSession(request_model.kind, _pages(request_model.kind, 1, last_has_more=False))

    await _browser(session).discover(request_model)

    assert len(session.fetched) == 1


async def test_session_and_fetch_options_capture_only_the_list_api() -> None:
    session = FakeSession("profile", _pages("profile", 1, last_has_more=False))

    await _browser(session).discover(ProfileDiscovery(handle="creator"))

    assert session.factory_kwargs == {
        "headless": True,
        "max_pages": 1,
        "capture_xhr": XHR_PATTERNS["profile"],
    }
    options = {
        key: session.fetch_kwargs[0][key]
        for key in ("timeout", "network_idle", "disable_resources", "google_search", "wait")
    }
    assert options == {
        "timeout": FETCH_TIMEOUT_MS,
        "network_idle": True,
        "disable_resources": False,
        "google_search": False,
        "wait": FETCH_WAIT_MS,
    }
    assert session.exited is True
    assert active_scrapling_session_count() == 0


async def test_stops_scrolling_once_the_limit_is_reached() -> None:
    session = FakeSession("profile", _pages("profile", 5))

    result = await _browser(session).discover(ProfileDiscovery(handle="creator", limit=5))

    assert session.page.scrolls == 1
    assert result.pages == 2
    assert len(result.videos) == 5
    assert result.reason is None
    assert result.exhausted is False


async def test_stops_when_a_page_reports_no_more_results() -> None:
    session = FakeSession("trending", _pages("trending", 2, last_has_more=False))

    result = await _browser(session).discover(TrendingDiscovery(limit=100))

    assert session.page.scrolls == 1
    assert result.pages == 2
    assert len(result.videos) == 6
    assert result.exhausted is True
    assert result.reason is None


async def test_stops_after_two_scrolls_that_load_nothing() -> None:
    session = FakeSession("profile", _pages("profile", 1))

    result = await _browser(session).discover(ProfileDiscovery(handle="creator", limit=100))

    assert session.page.scrolls == 2
    assert result.pages == 1
    assert result.exhausted is False
    assert result.reason is None


async def test_stops_at_max_scrolls() -> None:
    session = FakeSession("profile", _pages("profile", 20))

    result = await _browser(session).discover(ProfileDiscovery(handle="creator", limit=100))

    assert session.page.scrolls == discovery_module.MAX_SCROLLS == 10
    assert result.pages == 11
    assert len(result.videos) == 33


async def test_attach_resets_stale_scroll_state_from_a_session_retry() -> None:
    """Scrapling re-runs page_setup/page_action on a fresh page when it retries a failed
    goto/load-state; a stale response left over from the failed attempt must never carry
    into the retry's tally (a closed page's body() raises there, which reads as done)."""
    scroll = discovery_module._Scroll(kind="profile", limit=100)
    failed_page = FakePage(
        API_URLS["profile"], _pages("profile", 1, last_has_more=False), body_error=True
    )
    await scroll.attach(failed_page)
    await discovery_module._paginate(failed_page, scroll)
    assert scroll.done is True  # the failed attempt's stale response looked like captcha

    retry_page = FakePage(API_URLS["profile"], _pages("profile", 1, last_has_more=False))
    await scroll.attach(retry_page)
    await discovery_module._paginate(retry_page, scroll)

    assert retry_page.scrolls == 1
    assert len(scroll.seen) == 3


async def test_attach_clears_a_captcha_flag_left_by_a_failed_attempt() -> None:
    scroll = discovery_module._Scroll(kind="profile", limit=100)
    failed_page = FakePage(API_URLS["profile"], _pages("profile", 1), captcha=True)
    await scroll.attach(failed_page)
    failed_page.emit()
    await discovery_module._paginate(failed_page, scroll)
    assert scroll.captcha is True

    retry_page = FakePage(API_URLS["profile"], _pages("profile", 1, last_has_more=False))
    await scroll.attach(retry_page)
    retry_page.emit()
    await discovery_module._paginate(retry_page, scroll)

    assert scroll.captcha is False
    assert scroll.stop == "done"


async def test_captcha_container_stops_with_a_partial_result() -> None:
    session = FakeSession("profile", _pages("profile", 3), captcha=True)

    result = await _browser(session).discover(ProfileDiscovery(handle="creator"))

    assert session.page.scrolls == 0
    assert result.reason is DiscoveryReason.CAPTCHA
    assert result.pages == 1
    assert len(result.videos) == 3


async def test_captcha_rendered_in_the_final_page_is_reported() -> None:
    session = FakeSession("profile", _pages("profile", 1, last_has_more=False), css_captcha=True)

    result = await _browser(session).discover(ProfileDiscovery(handle="creator"))

    assert result.reason is DiscoveryReason.CAPTCHA
    assert len(result.videos) == 3


async def test_scroll_deadline_bounds_a_hanging_scroll_with_a_partial_result(monkeypatch) -> None:
    monkeypatch.setattr(discovery_module, "SCROLL_DEADLINE_S", 0.05)
    session = FakeSession("profile", _pages("profile", 3), hang=True)

    # The outer bound only keeps a regression from hanging the suite.
    result = await asyncio.wait_for(
        _browser(session).discover(ProfileDiscovery(handle="creator")), 5
    )

    assert session.page.scrolls == 0
    assert result.reason is DiscoveryReason.TIMEOUT
    assert len(result.videos) == 3


@pytest.mark.parametrize("status", [403, 500])
async def test_a_non_2xx_captured_page_is_blocked(status: int) -> None:
    session = FakeSession("profile", _pages("profile", 1, last_has_more=False), status=status)

    result = await _browser(session).discover(ProfileDiscovery(handle="creator"))

    assert result.reason is DiscoveryReason.BLOCKED
    assert result.videos == []


async def test_an_empty_first_body_is_captcha_with_no_pages() -> None:
    session = FakeSession("keyword", [b"", *_pages("keyword", 2)])

    result = await _browser(session).discover(KeywordDiscovery(query="cats"))

    assert session.page.scrolls == 0
    assert result.reason is DiscoveryReason.CAPTCHA
    assert result.pages == 0
    assert result.videos == []


async def test_a_blocked_page_keeps_earlier_videos() -> None:
    blocked = json.dumps({"statusCode": 10201}).encode()
    session = FakeSession("profile", [*_pages("profile", 1), blocked])

    result = await _browser(session).discover(ProfileDiscovery(handle="creator"))

    assert session.page.scrolls == 1
    assert result.reason is DiscoveryReason.BLOCKED
    assert result.pages == 1
    assert len(result.videos) == 3


def test_assembly_ignores_pages_after_the_first_reason() -> None:
    blocked = json.dumps({"statusCode": 10201}).encode()
    first = _body_for("profile", ["1000000001"])
    later = _body_for("profile", ["1000000002"], has_more=False)

    pages = [parse_discovery_page("profile", body) for body in (first, blocked, later)]

    result = _assemble("profile", 100, pages, captcha=False, timed_out=False)

    assert [video.post_id for video in result.videos] == ["1000000001"]
    assert result.pages == 1
    assert result.reason is DiscoveryReason.BLOCKED
    assert result.exhausted is False


def test_assembly_deduplicates_first_seen_sums_drops_and_truncates() -> None:
    first = _list_body(
        [_item("1000000001", desc="first"), _item("1000000002"), _item("1000000009", isAd=True)]
    )
    second = _list_body(
        [_item("1000000001", desc="second"), _item("1000000003"), _item("1000000008", isAd=True)],
        has_more=False,
    )

    pages = [parse_discovery_page("profile", body) for body in (first, second)]

    result = _assemble("profile", 2, pages, captcha=False, timed_out=False)

    assert [video.post_id for video in result.videos] == ["1000000001", "1000000002"]
    assert result.videos[0].caption == "first"
    assert result.drops == DiscoveryDrops(ads=2)
    assert result.pages == 2
    assert result.exhausted is True


async def test_no_captured_response_is_no_data() -> None:
    session = FakeSession("trending", [])

    result = await _browser(session).discover(TrendingDiscovery())

    assert result.reason is DiscoveryReason.NO_DATA
    assert result.pages == 0


async def test_a_factory_failure_is_browser_unavailable() -> None:
    def broken_factory(**kwargs: object) -> None:
        raise ImportError("scrapling is not installed")

    result = await ScraplingDiscoveryBrowser(session_factory=broken_factory).discover(
        TrendingDiscovery()
    )

    assert result.reason is DiscoveryReason.BROWSER_UNAVAILABLE
    assert result.videos == []
    assert active_scrapling_session_count() == 0


async def test_a_browser_start_failure_is_browser_unavailable() -> None:
    session = FakeSession("trending", [], enter_error=RuntimeError("no browser binary"))

    result = await _browser(session).discover(TrendingDiscovery())

    assert result.reason is DiscoveryReason.BROWSER_UNAVAILABLE
    assert active_scrapling_session_count() == 0


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (TimeoutError("navigation"), DiscoveryReason.TIMEOUT),
        (RuntimeError("page crashed"), DiscoveryReason.BROWSER_UNAVAILABLE),
    ],
)
async def test_fetch_errors_are_classified_and_close_the_session(error, reason) -> None:
    session = FakeSession("profile", _pages("profile", 1), fetch_error=error)

    result = await _browser(session).discover(ProfileDiscovery(handle="creator"))

    assert result.reason is reason
    assert result.videos == []
    assert session.exited is True
    assert active_scrapling_session_count() == 0


async def test_a_failing_session_close_keeps_the_result_and_the_session_count() -> None:
    session = FakeSession(
        "profile", _pages("profile", 1, last_has_more=False), exit_error=RuntimeError("closed")
    )

    result = await _browser(session).discover(ProfileDiscovery(handle="creator"))

    assert result.reason is None
    assert len(result.videos) == 3
    assert session.exited is True
    assert active_scrapling_session_count() == 0


async def test_cancellation_propagates_and_still_closes_the_session() -> None:
    session = FakeSession("profile", _pages("profile", 1), fetch_error=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await _browser(session).discover(ProfileDiscovery(handle="creator"))

    assert session.exited is True
    assert active_scrapling_session_count() == 0


async def test_a_failing_scroll_keeps_what_was_captured() -> None:
    session = FakeSession("profile", _pages("profile", 3), wheel_error=RuntimeError("detached"))

    result = await _browser(session).discover(ProfileDiscovery(handle="creator"))

    assert result.pages == 1
    assert len(result.videos) == 3
    assert result.reason is None


async def test_a_failed_in_page_body_read_stops_scrolling_but_keeps_the_capture() -> None:
    session = FakeSession("profile", _pages("profile", 3), body_error=True)

    result = await _browser(session).discover(ProfileDiscovery(handle="creator"))

    assert session.page.scrolls == 0
    assert result.pages == 1
    assert len(result.videos) == 3
    assert result.reason is None


@pytest.mark.parametrize(
    ("flags", "patch", "limit", "stop"),
    [
        ({}, {}, 3, "limit"),
        ({"last_has_more": False}, {}, 100, "done"),
        ({"captcha": True}, {}, 100, "captcha"),
        ({"hang": True}, {"SCROLL_DEADLINE_S": 0.05}, 100, "deadline"),
        ({}, {}, 100, "idle"),
        ({}, {"MAX_SCROLLS": 1}, 100, "max_scrolls"),
        ({"wheel_error": RuntimeError("detached")}, {}, 100, "error:RuntimeError"),
    ],
)
async def test_the_scroll_stop_cause_is_logged(caplog, monkeypatch, flags, patch, limit, stop):
    for name, value in patch.items():
        monkeypatch.setattr(discovery_module, name, value)
    last_has_more = flags.pop("last_has_more", True)
    session = FakeSession("profile", _pages("profile", 2, last_has_more=last_has_more), **flags)
    caplog.set_level(logging.DEBUG, logger=discovery_module.__name__)

    await asyncio.wait_for(
        _browser(session).discover(ProfileDiscovery(handle="creator", limit=limit)), 5
    )

    messages = [record.getMessage() for record in caplog.records]
    assert any(message.endswith(f"stop={stop}") for message in messages)
    warned = [record for record in caplog.records if record.levelname == "WARNING"]
    if stop.startswith("error:"):
        assert [record.getMessage() for record in warned] == [
            "tiktok discovery scroll failed kind=profile error=RuntimeError"
        ]


async def test_logs_carry_counts_but_never_targets_or_content(caplog) -> None:
    session = FakeSession("keyword", _pages("keyword", 1), captcha=True)
    caplog.set_level(logging.INFO, logger=discovery_module.__name__)

    await _browser(session).discover(KeywordDiscovery(query="secretquery"))

    records = [record for record in caplog.records if record.name == discovery_module.__name__]
    assert [record.levelname for record in records] == ["INFO", "WARNING"]
    text = " ".join(record.getMessage() for record in records)
    for secret in ("secretquery", "creator", "a caption", "1000000000", WARM_UP_ID, "tiktok.com"):
        assert secret not in text


def test_importing_discovery_module_does_not_import_scrapling_or_patchright() -> None:
    probe = (
        "import sys;"
        "import thoth_control_plane.acquisition.discovery;"
        "assert 'scrapling' not in sys.modules;"
        "assert 'patchright' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


IMAGE = "https://p16-sign.tiktokcdn.com/obj/photo-1.jpeg"


def test_photo_posts_are_listed_with_their_images() -> None:
    images = {"images": [{"imageURL": {"urlList": [IMAGE, "https://p16.example/2.jpeg"]}}]}
    body = _list_body([_item(), _item("1000000003", imagePost=images)])
    page = parse_discovery_page("profile", body)
    assert [video.post_id for video in page.videos] == ["1000000001"]
    assert [photo.post_id for photo in page.photos] == ["1000000003"]
    photo = page.photos[0]
    assert str(photo.canonical_url) == "https://www.tiktok.com/@creator/photo/1000000003"
    assert [str(url) for url in photo.image_urls] == [IMAGE]
    assert photo.hashtags == ["cats"]
    assert page.drops.photo_posts == 1
    result = _assemble("profile", 30, [page, page], captcha=False, timed_out=False)
    assert [p.post_id for p in result.photos] == ["1000000003"]


def test_a_photo_post_without_images_is_only_counted() -> None:
    page = parse_discovery_page("profile", _list_body([_item("1000000003", imagePost={})]))
    assert page.photos == [] and page.drops.photo_posts == 1


@pytest.mark.asyncio
async def test_a_profile_listing_crops_the_profile_page_once_the_grid_shows() -> None:
    # Spec 5c-2, G2: TikTok's grid needs a login, so its page card comes from this visit.
    session = FakeSession("profile", [_list_body([_item()], has_more=False)], page_rect=True)
    browser = ScraplingDiscoveryBrowser(session_factory=lambda **kwargs: session)
    result = await browser.discover(ProfileDiscovery(handle="creator", limit=30))
    assert result.page_png == b"page-png"
    assert session.page.scale == "css"
    assert "page_png" not in result.model_dump()


@pytest.mark.asyncio
async def test_no_grid_means_no_profile_page() -> None:
    session = FakeSession("profile", [_list_body([_item()], has_more=False)])
    browser = ScraplingDiscoveryBrowser(session_factory=lambda **kwargs: session)
    result = await browser.discover(ProfileDiscovery(handle="creator", limit=30))
    assert result.page_png is None

"""The X request fetcher and card browser over injected fakes; no network, no Scrapling."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from tests.acquisition.fakes import FakeCardPage, card_session
from thoth_control_plane.acquisition import x_service
from thoth_control_plane.acquisition.browser import active_scrapling_session_count
from thoth_control_plane.acquisition.card_browser import COMMENT_ROW_ATTRIBUTE, CommentTarget
from thoth_control_plane.acquisition.models import AcquisitionReason
from thoth_control_plane.acquisition.x_service import (
    POST_CARD_SELECTOR,
    PROFILE_CARD_SELECTOR,
    TAG_REPLIES_JS,
    RequestFetchError,
    XHeadlessBrowser,
    XRequestFetcher,
)

POST_ID = "1800000000000000001"
POST = f"https://x.com/user_001/status/{POST_ID}"
PROFILE = "https://x.com/user_001"
C1 = "1800000000000000101"
BLOCKED, TIMEOUT = AcquisitionReason.REQUEST_BLOCKED, AcquisitionReason.REQUEST_TIMEOUT


def _response(status: int = 200, url: str = POST, body: bytes = b"{}"):
    return SimpleNamespace(status=status, url=url, body=body)


def _get(result: Any, seen: list[tuple[str, dict[str, Any]]] | None = None):
    async def get(url: str, **kwargs: Any):
        if seen is not None:
            seen.append((url, kwargs))
        if isinstance(result, Exception):
            raise result
        return result

    return get


@pytest.mark.asyncio
async def test_syndication_returns_the_json_of_the_named_tweet() -> None:
    seen: list[tuple[str, dict[str, Any]]] = []
    fetcher = XRequestFetcher(_get(_response(body=b'{"id_str": "1"}'), seen))
    assert await fetcher.syndication(POST_ID) == {"id_str": "1"}
    url, kwargs = seen[0]
    assert url == f"https://cdn.syndication.twimg.com/tweet-result?id={POST_ID}&token=0&lang=en"
    assert kwargs["impersonate"] == "chrome"


@pytest.mark.asyncio
async def test_syndication_404_is_missing_not_blocked() -> None:
    assert await XRequestFetcher(_get(_response(status=404))).syndication(POST_ID) is None


@pytest.mark.asyncio
async def test_a_non_json_syndication_body_is_missing() -> None:
    fetcher = XRequestFetcher(_get(_response(body=b"<html></html>")))
    assert await fetcher.syndication(POST_ID) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (_response(status=403), BLOCKED),
        (_response(status=429), BLOCKED),
        (_response(url="https://x.com/i/flow/login?redirect_after_login=%2F"), BLOCKED),
        (_response(url="https://x.com/account/access"), BLOCKED),
        (TimeoutError(), TIMEOUT),
        (RuntimeError("boom"), BLOCKED),
    ],
)
async def test_failures_are_classified(result: Any, reason: AcquisitionReason) -> None:
    fetcher = XRequestFetcher(_get(result))
    with pytest.raises(RequestFetchError) as caught:
        await fetcher.syndication(POST_ID)
    assert caught.value.reason is reason
    with pytest.raises(RequestFetchError) as caught:
        await fetcher.page(POST)
    assert caught.value.reason is reason


@pytest.mark.asyncio
async def test_a_page_404_is_blocked() -> None:
    with pytest.raises(RequestFetchError) as caught:
        await XRequestFetcher(_get(_response(status=404))).page(POST)
    assert caught.value.reason is BLOCKED


@pytest.mark.asyncio
async def test_page_returns_the_html_text() -> None:
    fetcher = XRequestFetcher(_get(_response(body="<p>é</p>".encode())))
    assert await fetcher.page(POST) == "<p>é</p>"


@pytest.mark.asyncio
async def test_a_handle_that_starts_with_login_is_not_a_login_wall() -> None:
    fetcher = XRequestFetcher(_get(_response(url="https://x.com/loginx")))
    assert await fetcher.page("https://x.com/loginx") == "{}"


TARGETS = [CommentTarget(C1, "fan_001", "a reply")]


@pytest.mark.asyncio
async def test_cards_use_the_x_layout_with_no_dialog() -> None:
    post_page, profile_page = FakeCardPage(POST, tagged=[C1]), FakeCardPage(PROFILE)
    session = card_session({POST: post_page, PROFILE: profile_page})
    browser = XHeadlessBrowser(lambda **kwargs: session)

    cards = await browser.cards(POST, PROFILE, want_post=True, targets=TARGETS)
    await browser.close()

    assert cards.post_png is not None
    assert list(cards.comment_pngs) == [C1]
    assert cards.profile_png is not None
    assert post_page.clicked == []
    # The post's own article: on a reply's page the parent tweet comes first.
    post_selector = f'article:has(a[href$="/status/{POST_ID}"])'
    assert POST_CARD_SELECTOR.format(post_id=POST_ID) == post_selector
    assert post_page.shots == [post_selector, f'[{COMMENT_ROW_ATTRIBUTE}="{C1}"]']
    assert post_page.evaluated == [
        (TAG_REPLIES_JS, [{"comment_id": C1, "author": "fan_001", "prefix": "a reply"}])
    ]
    assert profile_page.shots == [PROFILE_CARD_SELECTOR] == ["main > div:nth-child(4)"]
    assert session.exited == 1
    assert active_scrapling_session_count() == 0


@pytest.mark.asyncio
async def test_an_x_login_wall_is_a_problem_not_a_failure() -> None:
    wall = FakeCardPage("https://x.com/i/flow/login?redirect_after_login=x")
    session = card_session({POST: wall, PROFILE: FakeCardPage(PROFILE)})
    browser = XHeadlessBrowser(lambda **kwargs: session)
    cards = await browser.cards(POST, PROFILE, want_post=True, targets=TARGETS)
    await browser.close()
    assert (cards.post_png, cards.comment_pngs) == (None, {})
    assert cards.problems == ["headless_blocked"]
    assert cards.profile_png is not None


def test_the_selectors_are_read_when_the_layout_is_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(x_service, "PROFILE_CARD_SELECTOR", "main header")
    assert x_service.x_layout().profile_selector == "main header"

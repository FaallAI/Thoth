"""The X request fetcher and card browser over injected fakes; no network, no Scrapling."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from tests.acquisition.fakes import FakeCardPage, card_session
from thoth_control_plane.acquisition import x_service
from thoth_control_plane.acquisition.browser import active_scrapling_session_count
from thoth_control_plane.acquisition.card_browser import (
    COMMENT_ROW_ATTRIBUTE,
    MEDIA_BOX_JS,
    PROFILE_PAGE_JS,
    CommentTarget,
)
from thoth_control_plane.acquisition.models import AcquisitionReason
from thoth_control_plane.acquisition.x_service import (
    HIDE_OVERLAYS_JS,
    POST_CARD_SELECTOR,
    PROFILE_CARD_SELECTOR,
    TAG_PROFILE_JS,
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
        (
            _response(url="https://x.com/i/flow/login?redirect_after_login=%2F"),
            AcquisitionReason.LOGIN_WALL,
        ),
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


@pytest.mark.asyncio
async def test_a_handle_that_starts_with_login_is_not_a_login_wall() -> None:
    fetcher = XRequestFetcher(_get(_response(url="https://x.com/loginx")))
    assert await fetcher.syndication(POST_ID) == {}


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
    # The post card's media box is measured right after the crop (spec 5c-2, G1).
    assert post_page.evaluated == [
        (HIDE_OVERLAYS_JS, None),
        (MEDIA_BOX_JS, post_selector),
        (TAG_REPLIES_JS, [{"comment_id": C1, "author": "fan_001", "prefix": "a reply"}]),
    ]
    # The header is tagged by shape for this owner first, then cropped by the tag (G5).
    assert PROFILE_CARD_SELECTOR == '[data-thoth-profile-card="1"]'
    assert profile_page.shots == [PROFILE_CARD_SELECTOR]
    assert profile_page.evaluated == [
        (HIDE_OVERLAYS_JS, None),
        (f'({TAG_PROFILE_JS})("user_001")', None),
        (PROFILE_PAGE_JS, [{"x": 0, "y": 0, "width": 400, "height": 200}, "main article", 1]),
    ]
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


# Spec 2026-10-24 D3: X's own embed widget for meaningful replies the page did not show.
C2, C3, C4 = "1800000000000000102", "1800000000000000103", "1800000000000000104"


def _embed(comment_id: str) -> str:
    return x_service.EMBED_URL.format(comment_id=comment_id)


def _embed_page(comment_id: str, matches: bool = True) -> FakeCardPage:
    return FakeCardPage(_embed(comment_id), results={x_service.EMBED_MATCH_JS: matches})


def test_embed_candidates_are_substantive_replies_by_likes() -> None:
    from thoth_control_plane.acquisition.models import ReportComment

    def reply(comment_id: str, text: str, likes: int) -> ReportComment:
        return ReportComment(comment_id=comment_id, author="fan_001", text=text, likes=likes)

    candidates = x_service.embed_candidates(
        [
            reply(C1, "Kondisi udara di sana makin parah", 3),
            reply(C2, "wkwkwkwk", 50),
            reply(C3, "Semoga cepat turun hujan di Kalteng", 9),
        ]
    )
    assert [target.comment_id for target in candidates] == [C3, C1]


def test_the_embed_url_is_dark_and_hides_the_parent() -> None:
    url = _embed(C2)
    assert url.startswith("https://platform.twitter.com/embed/Tweet.html?id=")
    assert f"id={C2}" in url and "theme=dark" in url and "hideThread=true" in url


@pytest.mark.asyncio
async def test_uncarded_replies_get_an_embed_card_and_carded_ones_do_not() -> None:
    post_page = FakeCardPage(POST, tagged=[C1])
    pages = {POST: post_page, PROFILE: FakeCardPage(PROFILE), _embed(C2): _embed_page(C2)}
    session = card_session(pages)
    browser = XHeadlessBrowser(lambda **kwargs: session)
    embeds = [CommentTarget(C1, "fan_001", "a reply"), CommentTarget(C2, "fan_002", "b reply")]

    cards = await browser.cards(POST, PROFILE, want_post=True, targets=TARGETS, embeds=embeds)
    await browser.close()

    assert set(cards.comment_pngs) == {C1, C2}
    assert session.active.visits == [POST, PROFILE, _embed(C2)]
    assert pages[_embed(C2)].shots == ["article"]
    assert pages[_embed(C2)].evaluated == [(x_service.EMBED_MATCH_JS, [C2, "b reply"])]


@pytest.mark.asyncio
async def test_an_embed_of_another_post_is_never_a_card() -> None:
    pages = {POST: FakeCardPage(POST), PROFILE: FakeCardPage(PROFILE)}
    pages[_embed(C2)] = _embed_page(C2, matches=False)
    browser = XHeadlessBrowser(lambda **kwargs: card_session(pages))
    embeds = [CommentTarget(C2, "fan_002", "b reply")]

    cards = await browser.cards(POST, PROFILE, want_post=True, targets=[], embeds=embeds)
    await browser.close()

    assert cards.comment_pngs == {}
    assert pages[_embed(C2)].shots == []


@pytest.mark.asyncio
async def test_embeds_are_capped_and_a_failed_one_is_only_a_problem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(x_service, "MAX_EMBED_CARDS", 2)
    # C2's embed page is missing, so its visit fails; C3 and C4 are next in line.
    pages = {POST: FakeCardPage(POST), PROFILE: FakeCardPage(PROFILE)}
    pages |= {_embed(C3): _embed_page(C3), _embed(C4): _embed_page(C4)}
    session = card_session(pages)
    browser = XHeadlessBrowser(lambda **kwargs: session)
    embeds = [CommentTarget(c, "fan", f"{c} text") for c in (C2, C3, C4)]

    cards = await browser.cards(POST, PROFILE, want_post=True, targets=[], embeds=embeds)
    await browser.close()

    assert session.active.visits == [POST, PROFILE, _embed(C2), _embed(C3)]
    assert list(cards.comment_pngs) == [C3]
    assert cards.problems == ["headless_blocked"]
    assert active_scrapling_session_count() == 0


@pytest.mark.asyncio
async def test_embed_visits_wait_for_the_embed_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    monkeypatch.setattr(x_service, "EMBED_SPACING_SECONDS", 0.05)
    pages = {POST: FakeCardPage(POST), PROFILE: FakeCardPage(PROFILE)}
    pages |= {_embed(C2): _embed_page(C2), _embed(C3): _embed_page(C3)}
    browser = XHeadlessBrowser(lambda **kwargs: card_session(pages))
    embeds = [CommentTarget(c, "fan", f"{c} text") for c in (C2, C3)]

    started = time.perf_counter()
    await browser.cards(POST, PROFILE, want_post=True, targets=[], embeds=embeds)
    elapsed = time.perf_counter() - started
    await browser.close()

    assert elapsed >= 0.095  # one gap before each embed visit

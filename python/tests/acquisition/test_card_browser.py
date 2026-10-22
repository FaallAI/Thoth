"""The shared card browser over fake sessions: layout-driven crops; no network."""

from __future__ import annotations

import logging

import pytest

from tests.acquisition.fakes import FakeCardPage, FakeSession, card_session
from tests.acquisition.png_fixtures import make_png
from thoth_control_plane.acquisition.browser import active_scrapling_session_count
from thoth_control_plane.acquisition.card_browser import (
    COMMENT_ROW_ATTRIBUTE,
    MEDIA_BOX_JS,
    PROFILE_PAGE_JS,
    CardBrowser,
    CardLayout,
    Cards,
    CommentTarget,
    is_login_path,
    log_outcome,
    media_box,
    persist_cards,
)
from thoth_control_plane.acquisition.models import MediaBox, ReportComment

POST = "https://example.test/post/1"
PROFILE = "https://example.test/user_001"
C1 = "1800000000000000101"
LAYOUT = CardLayout(
    post_selector=".post", profile_selector=".profile", tag_js="TAG", login_paths=("/login",)
)
TARGETS = [CommentTarget(C1, "fan_001", "a reply")]


@pytest.mark.asyncio
async def test_cards_follow_the_layout() -> None:
    post_page, profile_page = FakeCardPage(POST, tagged=[C1, "99999"]), FakeCardPage(PROFILE)
    session = card_session({POST: post_page, PROFILE: profile_page})
    browser = CardBrowser(LAYOUT, lambda **kwargs: session)

    cards = await browser.cards(POST, PROFILE, want_post=True, targets=TARGETS)
    await browser.close()

    assert cards.post_png is not None
    assert list(cards.comment_pngs) == [C1]
    assert cards.profile_png is not None
    assert post_page.clicked == []
    assert post_page.shots == [".post", f'[{COMMENT_ROW_ATTRIBUTE}="{C1}"]']
    assert post_page.evaluated == [
        ("TAG", [{"comment_id": C1, "author": "fan_001", "prefix": "a reply"}])
    ]
    assert profile_page.shots == [".profile"]
    assert session.exited == 1
    assert active_scrapling_session_count() == 0


@pytest.mark.asyncio
async def test_a_layout_dialog_is_dismissed_on_both_pages() -> None:
    layout = CardLayout(".post", ".profile", "TAG", ("/login",), dismiss_selector=".close")
    post_page, profile_page = FakeCardPage(POST), FakeCardPage(PROFILE)
    session = card_session({POST: post_page, PROFILE: profile_page})
    browser = CardBrowser(layout, lambda **kwargs: session)
    await browser.cards(POST, PROFILE, want_post=True, targets=[])
    await browser.close()
    assert post_page.clicked == profile_page.clicked == [".close"]


@pytest.mark.asyncio
async def test_nothing_to_crop_on_the_post_skips_its_visit() -> None:
    session = card_session({PROFILE: FakeCardPage(PROFILE)})
    browser = CardBrowser(LAYOUT, lambda **kwargs: session)
    cards = await browser.cards(POST, PROFILE, want_post=False, targets=[])
    await browser.close()
    assert session.active.visits == [PROFILE]
    assert cards.profile_png is not None


@pytest.mark.asyncio
async def test_a_login_path_is_a_problem_not_a_failure() -> None:
    wall = FakeCardPage("https://example.test/login/next")
    browser = CardBrowser(LAYOUT, lambda **kwargs: card_session({POST: wall, PROFILE: wall}))
    cards = await browser.cards(POST, PROFILE, want_post=True, targets=TARGETS)
    await browser.close()
    assert cards.problems == ["headless_blocked", "headless_blocked"]
    assert (cards.post_png, cards.comment_pngs, cards.profile_png) == (None, {}, None)


@pytest.mark.asyncio
async def test_a_browser_that_cannot_start_yields_problems_only() -> None:
    session = FakeSession(enter_error=TimeoutError())
    browser = CardBrowser(LAYOUT, lambda **kwargs: session)
    cards = await browser.cards(POST, PROFILE, want_post=True, targets=TARGETS)
    await browser.close()
    assert cards.problems == ["headless_timeout", "headless_timeout"]
    assert active_scrapling_session_count() == 0


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://x.com/i/flow/login?redirect_after_login=%2F", True),
        ("https://x.com/i/flow/login", True),
        ("https://x.com/i/flow/loginx", False),
        ("https://x.com/user_001", False),
        ("not a url", False),
    ],
)
def test_is_login_path_matches_whole_segments(url: str, expected: bool) -> None:
    assert is_login_path(url, ("/i/flow/login",)) is expected


def test_log_outcome_names_the_platform_and_never_text(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    comment = ReportComment(comment_id=C1, author="fan_001", text="secret words")
    log_outcome(
        "x",
        "request",
        1,
        [comment],
        None,
        None,
        want_post=True,
        problems=["headless_timeout"],
        dropped=2,
    )
    assert "x acquisition finished method=request media=1 comments=1 comment_cards=0" in (
        caplog.text
    )
    assert "x cards missing missing=post,profile,comments=1 problems=headless_timeout" in (
        caplog.text
    )
    assert "x comments dropped count=2" in caplog.text
    assert "secret words" not in caplog.text
    assert "fan_001" not in caplog.text


def test_media_box_is_relative_to_the_card() -> None:
    box = media_box(
        {"x": 100, "y": 200, "width": 400, "height": 600},
        {"x": 120, "y": 350, "width": 360, "height": 300},
    )
    assert box == MediaBox(x=0.05, y=0.25, w=0.9, h=0.5)


def test_a_media_box_outside_the_card_is_dropped() -> None:
    card = {"x": 0, "y": 0, "width": 100, "height": 100}
    assert media_box(card, {"x": 50, "y": 50, "width": 100, "height": 100}) is None
    assert media_box(card, {"x": 10, "y": 10, "width": 0, "height": 50}) is None
    assert media_box(card, None) is None


@pytest.mark.asyncio
async def test_profile_page_and_post_media_follow_the_layout() -> None:
    layout = CardLayout(
        ".post", ".profile", "TAG", ("/login",), measure_media=True, page_items=".item"
    )
    boxes = {
        "card": {"x": 0, "y": 0, "width": 400, "height": 800},
        "media": {"x": 0, "y": 200, "width": 400, "height": 400},
    }
    rect = {"x": 0, "y": 0, "width": 600, "height": 900}
    post_page = FakeCardPage(POST, results={MEDIA_BOX_JS: boxes})
    profile_page = FakeCardPage(PROFILE, results={PROFILE_PAGE_JS: rect})
    session = card_session({POST: post_page, PROFILE: profile_page})
    browser = CardBrowser(layout, lambda **kwargs: session)

    cards = await browser.cards(POST, PROFILE, want_post=True, targets=[])
    await browser.close()

    assert cards.post_media_box == MediaBox(x=0.0, y=0.25, w=1.0, h=0.5)
    assert cards.profile_page_png is not None
    assert profile_page.clips == [rect]
    assert (PROFILE_PAGE_JS, [".profile", ".item", 2]) in profile_page.evaluated


@pytest.mark.asyncio
async def test_no_grid_items_means_no_profile_page() -> None:
    layout = CardLayout(".post", ".profile", "TAG", ("/login",), page_items=".item")
    profile_page = FakeCardPage(PROFILE, results={PROFILE_PAGE_JS: None})
    session = card_session({PROFILE: profile_page})
    browser = CardBrowser(layout, lambda **kwargs: session)
    cards = await browser.cards(POST, PROFILE, want_post=False, targets=[])
    await browser.close()
    assert cards.profile_page_png is None
    assert profile_page.clips == []


def test_persisted_cards_carry_the_media_box_and_profile_page(tmp_path) -> None:
    cards = Cards(
        post_png=make_png(400, 800),
        profile_png=make_png(400, 200),
        profile_page_png=make_png(400, 900),
        post_media_box=MediaBox(x=0.0, y=0.25, w=1.0, h=0.5),
    )
    saved = persist_cards(cards, [], "wf_cards_001", tmp_path)
    assert saved.post_card is not None and saved.post_card.media_box == cards.post_media_box
    assert saved.profile_page is not None
    assert str(saved.profile_page.location) == "reports/wf_cards_001/cards/profile-page.png"
    assert saved.profile_card is not None and saved.comments == []

"""The shared card browser over fake sessions: layout-driven crops; no network."""

from __future__ import annotations

import logging

import pytest

from tests.acquisition.fakes import FakeCardPage, FakeSession, card_session
from thoth_control_plane.acquisition.browser import active_scrapling_session_count
from thoth_control_plane.acquisition.card_browser import (
    COMMENT_ROW_ATTRIBUTE,
    CardBrowser,
    CardLayout,
    CommentTarget,
    is_login_path,
    log_outcome,
)
from thoth_control_plane.acquisition.models import ReportComment

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

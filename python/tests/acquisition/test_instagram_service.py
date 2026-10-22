"""Instagram fetcher, identity resolution, and headless cards over injected fakes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from tests.acquisition.png_fixtures import make_png
from thoth_control_plane.acquisition import instagram_service
from thoth_control_plane.acquisition.adapters.instagram import InstagramUrlError
from thoth_control_plane.acquisition.browser import (
    HeadlessBrowserError,
    active_scrapling_session_count,
)
from thoth_control_plane.acquisition.instagram_service import (
    COMMENT_ROW_ATTRIBUTE,
    DIALOG_CLOSE_SELECTOR,
    POST_CARD_SELECTOR,
    PROFILE_CARD_SELECTOR,
    PROFILE_PAGE_ITEMS,
    TAG_COMMENTS_JS,
    CommentTarget,
    InstagramHeadlessBrowser,
    InstagramRequestFetcher,
    RequestFetchError,
    comment_targets,
    resolve_instagram_identity,
)
from thoth_control_plane.acquisition.models import AcquisitionReason, ReportComment

POST = "https://www.instagram.com/p/code_001/"
PROFILE = "https://www.instagram.com/user_001/"
SHARE = "https://www.instagram.com/share/reel/tok_001/"
C1 = "18000000000000000001"


def _response(status: int = 200, url: str = POST):
    return SimpleNamespace(
        status=status, url=url, css=lambda selector: SimpleNamespace(getall=lambda: ["{}", ""])
    )


def _get(result: Any):
    async def get(url: str, **kwargs: Any):
        if isinstance(result, Exception):
            raise result
        return result

    return get


@pytest.mark.asyncio
async def test_request_fetcher_returns_script_texts() -> None:
    seen: dict[str, Any] = {}

    async def get(url: str, **kwargs: Any):
        seen.update(kwargs)
        return _response()

    assert await InstagramRequestFetcher(get).fetch(POST) == ["{}"]
    assert seen["impersonate"] == "chrome"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (_response(status=403), AcquisitionReason.REQUEST_BLOCKED),
        (_response(status=429), AcquisitionReason.REQUEST_BLOCKED),
        (
            _response(url="https://www.instagram.com/accounts/login/?next=%2Fp%2Fx%2F"),
            AcquisitionReason.LOGIN_WALL,
        ),
        (_response(url="https://www.instagram.com/challenge/"), AcquisitionReason.REQUEST_BLOCKED),
        (TimeoutError(), AcquisitionReason.REQUEST_TIMEOUT),
        (RuntimeError("boom"), AcquisitionReason.REQUEST_BLOCKED),
    ],
)
async def test_request_fetcher_classifies_failures(result: Any, reason: AcquisitionReason) -> None:
    with pytest.raises(RequestFetchError) as caught:
        await InstagramRequestFetcher(_get(result)).fetch(POST)
    assert caught.value.reason is reason


@pytest.mark.asyncio
async def test_a_handle_that_starts_with_login_is_not_a_login_wall() -> None:
    fetcher = InstagramRequestFetcher(_get(_response(url="https://www.instagram.com/loginx/")))
    assert await fetcher.fetch("https://www.instagram.com/loginx/") == ["{}"]


@pytest.mark.asyncio
async def test_landing_returns_the_final_url() -> None:
    landing = "https://www.instagram.com/reel/code_001/?igsh=x"
    assert await InstagramRequestFetcher(_get(_response(url=landing))).landing(SHARE) == landing


class _ShareRequest:
    def __init__(self, target: str) -> None:
        self.target, self.calls = target, []

    async def landing(self, share_url: str) -> str:
        self.calls.append(share_url)
        return self.target


class _ShareHeadless:
    def __init__(self, target: str) -> None:
        self.target, self.calls = target, []

    async def resolve(self, share_url: str) -> str:
        self.calls.append(share_url)
        return self.target


@pytest.mark.asyncio
async def test_a_post_url_is_its_own_identity() -> None:
    request, headless = _ShareRequest(POST), _ShareHeadless(POST)
    identity = await resolve_instagram_identity(POST + "?igsh=x", request, headless)
    assert identity.post_id == "code_001"
    assert request.calls == headless.calls == []


@pytest.mark.asyncio
async def test_a_share_link_resolves_through_the_request() -> None:
    request = _ShareRequest("https://www.instagram.com/reel/code_001/?igsh=x")
    headless = _ShareHeadless(POST)
    identity = await resolve_instagram_identity(SHARE + "?igsh=abc", request, headless)
    assert str(identity.canonical_url) == POST
    assert request.calls == [SHARE]
    assert headless.calls == []


@pytest.mark.asyncio
async def test_a_share_link_landing_off_a_post_is_invalid() -> None:
    with pytest.raises(InstagramUrlError):
        await resolve_instagram_identity(SHARE, _ShareRequest(PROFILE), _ShareHeadless(POST))


@pytest.mark.asyncio
async def test_headless_share_resolution_uses_the_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(instagram_service, "SHARE_RESOLUTION_METHOD", "headless")
    request, headless = _ShareRequest(PROFILE), _ShareHeadless(POST)
    identity = await resolve_instagram_identity(SHARE, request, headless)
    assert identity.post_id == "code_001"
    assert request.calls == []
    assert headless.calls == [SHARE]


def test_comment_targets_use_the_first_non_empty_line() -> None:
    comment = ReportComment(
        comment_id=C1,
        author="fan_001",
        text="  \n  a first line that is clearly longer than thirty chars\nsecond",
    )
    assert comment_targets([comment]) == [
        CommentTarget(C1, "fan_001", "a first line that is clearly l")
    ]


def test_the_tagging_script_sets_the_row_attribute() -> None:
    assert COMMENT_ROW_ATTRIBUTE in TAG_COMMENTS_JS


class _Locator:
    def __init__(self, page: _CardPage, selector: str) -> None:
        self.first, self._page, self._selector = self, page, selector

    async def click(self, timeout: int) -> None:
        self._page.clicked.append(self._selector)

    async def scroll_into_view_if_needed(self, timeout: int) -> None:
        return None

    async def screenshot(self, timeout: int) -> bytes:
        self._page.shots.append(self._selector)
        return make_png(400, 200)

    async def bounding_box(self) -> dict[str, float]:
        return {"x": 0, "y": 0, "width": 400, "height": 200}


class _CardPage:
    def __init__(self, url: str, tagged: list[str] | None = None) -> None:
        self.url, self.tagged = url, tagged or []
        self.clicked: list[str] = []
        self.shots: list[str] = []
        self.evaluated: list[object] = []

    def locator(self, selector: str) -> _Locator:
        return _Locator(self, selector)

    async def evaluate(self, script: str, arg: object) -> list[str]:
        self.evaluated.append(arg)
        return self.tagged


class _CardActive:
    def __init__(self, pages: dict[str, _CardPage]) -> None:
        self.pages, self.visits = pages, []

    async def fetch(self, url: str, **kwargs: Any):
        self.visits.append(url)
        page = self.pages[url]
        if kwargs.get("page_action") is not None:
            await kwargs["page_action"](page)
        return SimpleNamespace(
            url=page.url, css=lambda selector: SimpleNamespace(getall=lambda: ["{}", ""])
        )


class _Session:
    def __init__(self, active: Any = None, enter_error: Exception | None = None) -> None:
        self.active, self.enter_error, self.exited = active, enter_error, 0

    async def __aenter__(self):
        if self.enter_error is not None:
            raise self.enter_error
        return self.active

    async def __aexit__(self, *exc: object) -> None:
        self.exited += 1


def _browser(pages: dict[str, _CardPage]) -> tuple[InstagramHeadlessBrowser, _Session]:
    session = _Session(_CardActive(pages))
    return InstagramHeadlessBrowser(lambda **kwargs: session), session


TARGETS = [CommentTarget(C1, "fan_001", "first comment")]


@pytest.mark.asyncio
async def test_cards_crop_post_comments_and_profile_in_one_session() -> None:
    post_page = _CardPage(POST, tagged=[C1, "99999999"])
    profile_page = _CardPage(PROFILE)
    browser, session = _browser({POST: post_page, PROFILE: profile_page})

    cards = await browser.cards(POST, PROFILE, want_post=True, targets=TARGETS)
    await browser.close()

    assert cards.post_png is not None
    assert list(cards.comment_pngs) == [C1]
    assert cards.profile_png is not None
    assert cards.problems == []
    assert post_page.clicked == [DIALOG_CLOSE_SELECTOR]
    assert post_page.shots == [POST_CARD_SELECTOR, f'[{COMMENT_ROW_ATTRIBUTE}="{C1}"]']
    assert post_page.evaluated == [
        POST_CARD_SELECTOR,  # the media box, measured right after the crop (spec 5c-2)
        [{"comment_id": C1, "author": "fan_001", "prefix": "first comment"}],
    ]
    assert profile_page.shots == [PROFILE_CARD_SELECTOR]
    assert profile_page.evaluated == [
        [{"x": 0, "y": 0, "width": 400, "height": 200}, PROFILE_PAGE_ITEMS, 2]
    ]
    assert session.exited == 1
    assert active_scrapling_session_count() == 0


@pytest.mark.asyncio
async def test_video_post_crops_comments_but_not_the_post() -> None:
    post_page = _CardPage(POST, tagged=[C1])
    browser, _ = _browser({POST: post_page, PROFILE: _CardPage(PROFILE)})
    cards = await browser.cards(POST, PROFILE, want_post=False, targets=TARGETS)
    await browser.close()
    assert cards.post_png is None
    assert POST_CARD_SELECTOR not in post_page.shots
    assert list(cards.comment_pngs) == [C1]


@pytest.mark.asyncio
async def test_nothing_to_crop_on_the_post_skips_its_visit() -> None:
    browser, session = _browser({PROFILE: _CardPage(PROFILE)})
    cards = await browser.cards(POST, PROFILE, want_post=False, targets=[])
    await browser.close()
    assert session.active.visits == [PROFILE]
    assert cards.profile_png is not None


@pytest.mark.asyncio
async def test_a_login_wall_on_the_post_page_is_a_problem_not_a_failure() -> None:
    wall = _CardPage("https://www.instagram.com/accounts/login/?next=x")
    browser, _ = _browser({POST: wall, PROFILE: _CardPage(PROFILE)})
    cards = await browser.cards(POST, PROFILE, want_post=True, targets=TARGETS)
    await browser.close()
    assert cards.post_png is None
    assert cards.comment_pngs == {}
    assert cards.problems == ["headless_blocked"]
    assert cards.profile_png is not None


@pytest.mark.asyncio
async def test_a_browser_that_cannot_start_yields_problems_only() -> None:
    session = _Session(enter_error=TimeoutError())
    browser = InstagramHeadlessBrowser(lambda **kwargs: session)
    cards = await browser.cards(POST, PROFILE, want_post=True, targets=TARGETS)
    await browser.close()
    assert cards.problems == ["headless_timeout", "headless_timeout"]
    assert cards.post_png is cards.profile_png is None
    assert active_scrapling_session_count() == 0


@pytest.mark.asyncio
async def test_scripts_on_a_login_wall_is_blocked() -> None:
    browser, session = _browser({POST: _CardPage("https://www.instagram.com/accounts/login/")})
    with pytest.raises(HeadlessBrowserError) as caught:
        await browser.scripts(POST)
    await browser.close()
    assert caught.value.reason is AcquisitionReason.HEADLESS_BLOCKED
    assert session.exited == 1
    assert active_scrapling_session_count() == 0


@pytest.mark.asyncio
async def test_scripts_returns_the_page_json() -> None:
    browser, _ = _browser({POST: _CardPage(POST)})
    assert await browser.scripts(POST) == ["{}"]
    await browser.close()


class _SharePage:
    def __init__(self, landing: str) -> None:
        self.url, self._landing = SHARE, landing

    async def wait_for_url(self, predicate: Any, timeout: int) -> None:
        self.url = self._landing
        if not predicate(self.url):
            raise TimeoutError()


class _ShareActive:
    def __init__(self, landing: str) -> None:
        self.landing = landing

    async def fetch(self, url: str, **kwargs: Any):
        await kwargs["page_action"](_SharePage(self.landing))
        return SimpleNamespace(url=url)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("landing", "reason"),
    [
        ("https://www.instagram.com/reel/code_001/?igsh=x", None),
        ("https://www.instagram.com/accounts/login/?next=x", AcquisitionReason.HEADLESS_BLOCKED),
        (SHARE, AcquisitionReason.HEADLESS_INCOMPLETE),
    ],
)
async def test_headless_resolve(landing: str, reason: AcquisitionReason | None) -> None:
    session = _Session(_ShareActive(landing))
    browser = InstagramHeadlessBrowser(lambda **kwargs: session)
    try:
        if reason is None:
            assert await browser.resolve(SHARE) == landing
        else:
            with pytest.raises(HeadlessBrowserError) as caught:
                await browser.resolve(SHARE)
            assert caught.value.reason is reason
    finally:
        await browser.close()
    assert session.exited == 1
    assert active_scrapling_session_count() == 0

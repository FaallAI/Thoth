"""Threads acquisition over injected fakes: no network, no Scrapling."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any

import pytest

from tests.acquisition.png_fixtures import make_png
from thoth_control_plane.acquisition import threads_service
from thoth_control_plane.acquisition.browser import (
    HeadlessBrowserError,
    active_scrapling_session_count,
)
from thoth_control_plane.acquisition.materializer import MediaMaterializationError
from thoth_control_plane.acquisition.models import AcquisitionReason, MaterializedMedia
from thoth_control_plane.acquisition.threads_service import (
    POST_CARD_SELECTOR,
    RequestFetchError,
    ThreadsAcquirer,
    ThreadsHeadlessBrowser,
    ThreadsPage,
    ThreadsRequestFetcher,
)

URL = "https://www.threads.net/@user_001/post/code_001?xmt=abc"
WF = "wf_threads_001"


def _node(**extra: object) -> dict[str, object]:
    return {
        "code": "code_001",
        "user": {"username": "user_001"},
        "caption": {"text": "hello world"},
        "taken_at": 1_700_000_000,
        **extra,
    }


def _texts(node: dict[str, object]) -> list[str]:
    return [json.dumps({"data": {"thread_items": [{"post": node}]}})]


def _images(count: int) -> list[dict[str, object]]:
    return [
        {
            "image_versions2": {
                "candidates": [
                    {"url": f"https://img.example.test/{n}.jpg", "width": 9, "height": 9}
                ]
            }
        }
        for n in range(count)
    ]


class FakeRequest:
    def __init__(self, texts: list[str] | None = None, error: AcquisitionReason | None = None):
        self.texts, self.error, self.calls = texts or [], error, 0

    async def fetch(self, url: str) -> list[str]:
        self.calls += 1
        if self.error is not None:
            raise RequestFetchError(self.error)
        return self.texts


class FakeHeadless:
    def __init__(
        self,
        page: ThreadsPage | None = None,
        error: AcquisitionReason | None = None,
        landing: str | AcquisitionReason = "https://www.threads.com/@user_001/post/code_001?x=1",
    ):
        self.page, self.error, self.calls, self.closed = page, error, 0, 0
        self.landing, self.resolved = landing, []

    async def resolve(self, share_url: str) -> str:
        self.resolved.append(share_url)
        if isinstance(self.landing, AcquisitionReason):
            raise HeadlessBrowserError(self.landing)
        return self.landing

    async def fetch(self, url: str) -> ThreadsPage:
        self.calls += 1
        if self.error is not None:
            raise HeadlessBrowserError(self.error)
        assert self.page is not None
        return self.page

    async def close(self) -> None:
        self.closed += 1


class FakeMaterializer:
    def __init__(self, fail_at: int | None = None) -> None:
        self.fail_at = fail_at

    async def materialize(
        self, candidate, destination, relative_location, strategy, *, media_id="media_1", index=1
    ):
        if index == self.fail_at:
            raise MediaMaterializationError()
        video = candidate.kind == "video"
        suffix = ".mp4" if video else ".jpg"
        destination.with_suffix(suffix).parent.mkdir(parents=True, exist_ok=True)
        destination.with_suffix(suffix).write_bytes(b"x")
        return MaterializedMedia(
            media_id=media_id,
            kind=candidate.kind,
            index=index,
            location=relative_location.with_suffix(suffix),
            media_type="video/mp4" if video else "image/jpeg",
            bytes=20_000 if video else 5_000,
            checksum="sha256:" + "0" * 64,
            acquisition_strategy=strategy,
        )


def _card_page() -> ThreadsPage:
    return ThreadsPage(xhr_bodies=[], script_texts=[], card_png=make_png(400, 200))


async def _inspect(
    tmp_path: Path, request: FakeRequest, headless: FakeHeadless, materializer=None, url=URL
):
    acquirer = ThreadsAcquirer(request, headless, materializer or FakeMaterializer())
    return await acquirer.inspect(workflow_id=WF, source_url=url, artifact_root=tmp_path)


@pytest.mark.asyncio
async def test_text_only_post_gets_a_report_and_a_post_card(tmp_path: Path) -> None:
    headless = FakeHeadless(_card_page())
    result = await _inspect(tmp_path, FakeRequest(_texts(_node())), headless)

    report = result.report
    assert report is not None
    assert (report.schema_version, report.source.platform, report.media) == (3, "threads", [])
    assert str(report.source.canonical_url) == "https://www.threads.com/@user_001/post/code_001"
    assert report.post.text == "hello world"
    assert report.post_card is not None
    assert report.post_card.location == PurePosixPath(f"reports/{WF}/cards/post.png")
    assert (tmp_path / report.post_card.location).is_file()
    assert [a.strategy.value for a in report.outcome.attempts] == ["scrapling_request"]
    assert headless.closed >= 1


@pytest.mark.asyncio
async def test_video_post_skips_the_card_visit(tmp_path: Path) -> None:
    node = _node(video_versions=[{"url": "https://v.example.test/1.mp4"}])
    headless = FakeHeadless(_card_page())
    result = await _inspect(tmp_path, FakeRequest(_texts(node)), headless)

    assert result.report is not None
    assert [m.kind for m in result.report.media] == ["video"]
    assert result.report.post_card is None
    assert headless.calls == 0


@pytest.mark.asyncio
async def test_rejected_card_is_simply_absent(tmp_path: Path) -> None:
    page = ThreadsPage(xhr_bodies=[], script_texts=[], card_png=make_png(400, 200, flat=True))
    result = await _inspect(tmp_path, FakeRequest(_texts(_node())), FakeHeadless(page))
    assert result.report is not None
    assert result.report.post_card is None


@pytest.mark.asyncio
async def test_failed_card_visit_is_simply_absent(tmp_path: Path) -> None:
    headless = FakeHeadless(error=AcquisitionReason.HEADLESS_BLOCKED)
    result = await _inspect(tmp_path, FakeRequest(_texts(_node())), headless)
    assert result.report is not None
    assert result.report.post_card is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("request_", "code", "status"),
    [
        (FakeRequest(error=AcquisitionReason.REQUEST_BLOCKED), "request_blocked", "failed"),
        (FakeRequest(error=AcquisitionReason.REQUEST_TIMEOUT), "request_timeout", "failed"),
        (FakeRequest(["{}"]), "request_incomplete", "incomplete"),
    ],
)
async def test_request_failures_are_retryable_and_eligible(
    tmp_path: Path, request_: FakeRequest, code: str, status: str
) -> None:
    result = await _inspect(tmp_path, request_, FakeHeadless(_card_page()))
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == (code, True)
    assert [a.status.value for a in result.failure.attempts] == [status]


@pytest.mark.asyncio
async def test_whitespace_only_post_is_no_content(tmp_path: Path) -> None:
    node = _node(caption={"text": " \n\t "})
    result = await _inspect(tmp_path, FakeRequest(_texts(node)), FakeHeadless(_card_page()))
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("no_content", False)


@pytest.mark.asyncio
async def test_carousel_is_capped_at_twenty(tmp_path: Path) -> None:
    node = _node(carousel_media=_images(22))
    result = await _inspect(tmp_path, FakeRequest(_texts(node)), FakeHeadless(_card_page()))
    assert result.report is not None
    assert [m.index for m in result.report.media] == list(range(1, 21))
    assert result.report.media[19].location == PurePosixPath(
        f"reports/{WF}/media/threads-code_001-20.jpg"
    )


@pytest.mark.asyncio
async def test_mid_carousel_failure_leaves_no_orphans(tmp_path: Path) -> None:
    node = _node(carousel_media=_images(3))
    result = await _inspect(
        tmp_path, FakeRequest(_texts(node)), FakeHeadless(_card_page()), FakeMaterializer(fail_at=2)
    )
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("media_validation_failed", True)
    media_dir = tmp_path / "reports" / WF / "media"
    assert not media_dir.exists() or list(media_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_invalid_url_fails_before_any_fetch(tmp_path: Path) -> None:
    request, headless = FakeRequest(_texts(_node())), FakeHeadless(_card_page())
    result = await _inspect(tmp_path, request, headless, url="https://www.threads.com/@user_001")
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("invalid_source_url", False)
    assert (request.calls, headless.calls) == (0, 0)


SHARE = "https://www.threads.com/share/BAxyz12/?utm=x"


@pytest.mark.asyncio
async def test_share_link_resolves_to_its_post_before_any_fetch(tmp_path: Path) -> None:
    request, headless = FakeRequest(_texts(_node())), FakeHeadless(_card_page())
    result = await _inspect(tmp_path, request, headless, url=SHARE)
    assert result.report is not None
    assert headless.resolved == ["https://www.threads.com/share/BAxyz12/"]
    assert str(result.report.source.canonical_url) == (
        "https://www.threads.com/@user_001/post/code_001"
    )


@pytest.mark.asyncio
async def test_report_credits_the_post_author_not_the_url_owner(tmp_path: Path) -> None:
    request = FakeRequest(_texts(_node(user={"username": "real_author"})))
    result = await _inspect(tmp_path, request, FakeHeadless(_card_page()))
    assert result.report is not None
    assert result.report.post.owner_handle == "real_author"
    assert str(result.report.source.canonical_url) == (
        "https://www.threads.com/@real_author/post/code_001"
    )


@pytest.mark.asyncio
async def test_share_link_landing_off_a_post_is_invalid(tmp_path: Path) -> None:
    request = FakeRequest(_texts(_node()))
    headless = FakeHeadless(_card_page(), landing="https://www.threads.com/")
    result = await _inspect(tmp_path, request, headless, url=SHARE)
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("invalid_source_url", False)
    assert request.calls == 0


@pytest.mark.asyncio
async def test_share_link_resolution_failure_keeps_its_reason(tmp_path: Path) -> None:
    request = FakeRequest(_texts(_node()))
    headless = FakeHeadless(_card_page(), landing=AcquisitionReason.HEADLESS_BLOCKED)
    result = await _inspect(tmp_path, request, headless, url=SHARE)
    assert result.failure is not None
    assert result.failure.code == "headless_blocked"
    assert request.calls == 0
    assert headless.closed == 1


@pytest.mark.asyncio
async def test_headless_method_uses_one_visit_for_post_and_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(threads_service, "CONTENT_METHOD", "headless")
    page = ThreadsPage(xhr_bodies=[], script_texts=_texts(_node()), card_png=make_png(400, 200))
    request, headless = FakeRequest(), FakeHeadless(page)
    result = await _inspect(tmp_path, request, headless)

    assert result.report is not None
    assert result.report.post_card is not None
    assert [a.strategy.value for a in result.report.outcome.attempts] == ["scrapling_headless"]
    assert (request.calls, headless.calls) == (0, 1)


@pytest.mark.asyncio
async def test_headless_method_incomplete_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(threads_service, "CONTENT_METHOD", "headless")
    page = ThreadsPage(xhr_bodies=[{"data": {}}], script_texts=[], card_png=None)
    result = await _inspect(tmp_path, FakeRequest(), FakeHeadless(page))
    assert result.failure is not None
    assert result.failure.code == "headless_incomplete"


def _response(status: int = 200, url: str = "https://www.threads.com/@user_001/post/code_001"):
    return SimpleNamespace(
        status=status, url=url, css=lambda selector: SimpleNamespace(getall=lambda: ["{}", ""])
    )


@pytest.mark.asyncio
async def test_request_fetcher_returns_script_texts() -> None:
    seen: dict[str, Any] = {}

    async def get(url: str, **kwargs: Any):
        seen.update(kwargs)
        return _response()

    assert await ThreadsRequestFetcher(get).fetch(URL) == ["{}"]
    assert seen["impersonate"] == "chrome"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("get_result", "reason"),
    [
        (_response(status=403), AcquisitionReason.REQUEST_BLOCKED),
        (_response(url="https://www.threads.com/login?next=x"), AcquisitionReason.LOGIN_WALL),
        (TimeoutError(), AcquisitionReason.REQUEST_TIMEOUT),
        (RuntimeError("boom"), AcquisitionReason.REQUEST_BLOCKED),
    ],
)
async def test_request_fetcher_classifies_failures(
    get_result: Any, reason: AcquisitionReason
) -> None:
    async def get(url: str, **kwargs: Any):
        if isinstance(get_result, Exception):
            raise get_result
        return get_result

    with pytest.raises(RequestFetchError) as caught:
        await ThreadsRequestFetcher(get).fetch(URL)
    assert caught.value.reason is reason


class _Locator:
    def __init__(self, png: bytes) -> None:
        self.first, self._png = self, png

    async def scroll_into_view_if_needed(self, timeout: int) -> None:
        return None

    async def screenshot(self, timeout: int) -> bytes:
        return self._png


class _Page:
    def locator(self, selector: str) -> _Locator:
        assert selector == POST_CARD_SELECTOR
        return _Locator(make_png(400, 200))


class _Active:
    async def fetch(self, url: str, **kwargs: Any):
        await kwargs["page_action"](_Page())
        return SimpleNamespace(
            url=url,
            captured_xhr=[{"status": 200, "body": {"data": {}}}],
            css=lambda selector: SimpleNamespace(getall=lambda: ["{}"]),
        )


class _Session:
    def __init__(self, active: Any = None, enter_error: Exception | None = None) -> None:
        self.active, self.enter_error, self.exited = active or _Active(), enter_error, 0

    async def __aenter__(self):
        if self.enter_error is not None:
            raise self.enter_error
        return self.active

    async def __aexit__(self, *exc: object) -> None:
        self.exited += 1


@pytest.mark.asyncio
async def test_headless_browser_returns_page_and_releases_the_session() -> None:
    session = _Session()
    browser = ThreadsHeadlessBrowser(lambda **kwargs: session)
    page = await browser.fetch("https://www.threads.com/@user_001/post/code_001")
    await browser.close()

    assert page.script_texts == ["{}"]
    assert page.xhr_bodies == [{"data": {}}]
    assert page.card_png is not None
    assert session.exited == 1
    assert active_scrapling_session_count() == 0


@pytest.mark.asyncio
async def test_headless_browser_classifies_a_startup_timeout() -> None:
    browser = ThreadsHeadlessBrowser(lambda **kwargs: _Session(enter_error=TimeoutError()))
    with pytest.raises(HeadlessBrowserError) as caught:
        await browser.fetch("https://www.threads.com/@user_001/post/code_001")
    assert caught.value.reason is AcquisitionReason.HEADLESS_TIMEOUT
    assert active_scrapling_session_count() == 0


class _SharePage:
    def __init__(self, landing: str) -> None:
        self.url, self._landing = "https://www.threads.com/share/BAxyz12/", landing

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
async def test_headless_resolve_returns_the_landing_post_url() -> None:
    session = _Session(_ShareActive("https://www.threads.com/@user_001/post/code_001?x=1"))
    browser = ThreadsHeadlessBrowser(lambda **kwargs: session)
    landing = await browser.resolve("https://www.threads.com/share/BAxyz12/")
    assert landing == "https://www.threads.com/@user_001/post/code_001?x=1"
    assert session.exited == 1
    assert active_scrapling_session_count() == 0


@pytest.mark.asyncio
async def test_headless_resolve_on_a_login_wall_is_blocked() -> None:
    session = _Session(_ShareActive("https://www.threads.com/login?next=x"))
    browser = ThreadsHeadlessBrowser(lambda **kwargs: session)
    with pytest.raises(HeadlessBrowserError) as caught:
        await browser.resolve("https://www.threads.com/share/BAxyz12/")
    assert caught.value.reason is AcquisitionReason.HEADLESS_BLOCKED
    assert session.exited == 1
    assert active_scrapling_session_count() == 0


@pytest.mark.asyncio
async def test_headless_resolve_stuck_on_the_share_page_is_incomplete() -> None:
    session = _Session(_ShareActive("https://www.threads.com/share/BAxyz12/"))
    browser = ThreadsHeadlessBrowser(lambda **kwargs: session)
    with pytest.raises(HeadlessBrowserError) as caught:
        await browser.resolve("https://www.threads.com/share/BAxyz12/")
    assert caught.value.reason is AcquisitionReason.HEADLESS_INCOMPLETE
    assert active_scrapling_session_count() == 0

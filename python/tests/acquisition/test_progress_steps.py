"""Source-stage step emissions over the real seams and the existing fakes (phase 3, D3).

Each test wraps one representative flow in `progress.scoped` with a fake sink and asserts
the ordered `(code, n, total, params)` sequence the recorder receives.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.acquisition.fakes import FakeCardPage, card_session
from tests.acquisition.test_instagram_acquirer import _cards as _ig_cards
from tests.acquisition.test_instagram_acquirer import (
    _image as _ig_image,
)
from tests.acquisition.test_instagram_acquirer import (
    _node as _ig_node,
)
from tests.acquisition.test_instagram_acquirer import (
    _texts as _ig_texts,
)
from tests.acquisition.test_instagram_acquirer import (
    FakeHeadless as IgHeadless,
    FakeMaterializer as IgMaterializer,
    FakeRequest as IgRequest,
)
from tests.acquisition.test_service import (
    FakeBrowser as TikTokBrowser,
    FakeMaterializer as TikTokMaterializer,
    FakeResolver as TikTokResolver,
)
from tests.acquisition.test_service import complete_snapshot
from tests.acquisition.test_service import SOURCE_URL as TIKTOK_URL
from tests.acquisition.test_threads_service import _card_page as _threads_card_page
from tests.acquisition.test_threads_service import _images as _threads_images
from tests.acquisition.test_threads_service import _node as _threads_node
from tests.acquisition.test_threads_service import _texts as _threads_texts
from tests.acquisition.test_threads_service import (
    FakeHeadless as ThreadsHeadless,
    FakeMaterializer as ThreadsMaterializer,
    FakeRequest as ThreadsRequest,
)
from tests.acquisition.test_x_acquirer import FakeFx, FakeHeadless, FakeRequest
from tests.acquisition.test_youtube_acquirer import FakeClient, FakeHeadless as YtHeadless
from thoth_control_plane import progress
from thoth_control_plane.acquisition import card_browser, x_service
from thoth_control_plane.acquisition.card_browser import CardBrowser, CardLayout, CommentTarget
from thoth_control_plane.acquisition.instagram_service import (
    InstagramAcquirer,
    InstagramRequestFetcher,
)
from thoth_control_plane.acquisition.models import AcquisitionResult
from thoth_control_plane.acquisition.service import TikTokAcquisitionService
from thoth_control_plane.acquisition.threads_service import (
    ThreadsAcquirer,
    ThreadsRequestFetcher,
)
from thoth_control_plane.acquisition.x_service import (
    XAcquirer,
    XHeadlessBrowser,
    XRequestFetcher,
)
from thoth_control_plane.acquisition.youtube_service import YouTubeAcquirer
from thoth_control_plane.activities.source_investigation import (
    SourceInvestigationActivityInput,
    build_source_investigation_activity,
)
from thoth_control_plane.config import Settings
from thoth_control_plane.progress import StepRecord, StepScope

POST = "https://example.test/post/1"
PROFILE = "https://example.test/user_001"
LOGIN = "https://example.test/login"
C1, C2 = "1800000000000000101", "1800000000000000102"
LAYOUT = CardLayout(
    post_selector=".post", profile_selector=".profile", tag_js="TAG", login_paths=("/login",)
)
TARGETS = [CommentTarget(C1, "fan_001", "a reply")]
SOURCE_SCOPE = StepScope(workflow_id="wf_steps", stage="source", attempt=1)


class StepSink:
    def __init__(self) -> None:
        self.records: list[StepRecord] = []

    def append(self, scope: StepScope, record: StepRecord) -> None:
        self.records.append(record)


@pytest.fixture
def sink() -> StepSink:
    installed = StepSink()
    progress.install(installed)
    return installed


def sequence(sink: StepSink) -> list[tuple[str, int | None, int | None, dict | None]]:
    return [(r.code, r.n, r.total, r.params) for r in sink.records]


@pytest.fixture
def tiktok_report(tmp_path: Path):
    fixture = Path(__file__).resolve().parent.parent / "fixtures" / "tiktok"
    from thoth_control_plane.acquisition.models import SourceReport

    return SourceReport.model_validate_json(
        (fixture / "source_report_v3.json").read_text(encoding="utf-8")
    )


async def _successful_runner(tiktok_report: Any):
    async def run(workflow_id: str, source_url: str, artifact_root: Path) -> AcquisitionResult:
        del source_url
        media_path = artifact_root / f"reports/{workflow_id}/media/tiktok-1234567890.mp4"
        media_path.parent.mkdir(parents=True, exist_ok=True)
        media_path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 10_100)
        return AcquisitionResult(report=tiktok_report)

    return run


async def test_the_activity_reads_the_link_then_saves_the_report(
    tmp_path: Path, sink: StepSink, report_store, tiktok_report
) -> None:
    configured = build_source_investigation_activity(
        Settings(
            THOTH_CONTROL_PLANE_API_KEY="test-key",
            THOTH_CONTROL_PLANE_ARTIFACT_ROOT=tmp_path,
        ),
        runner=await _successful_runner(tiktok_report),
        reports=report_store,
    )
    with progress.scoped(SOURCE_SCOPE):
        result = await configured(
            SourceInvestigationActivityInput(
                workflow_id="wf_steps",
                request_snapshot_id="req_steps",
                canonical_source_url="https://www.tiktok.com/@creator/video/1234567890",
            )
        )
    assert result.report is not None
    assert sequence(sink) == [
        ("source.read_link", None, None, None),
        ("source.save_report", None, None, None),
    ]


async def test_the_card_pages_record_post_rows_gap_and_profile(sink: StepSink) -> None:
    pages = {POST: FakeCardPage(POST, tagged=[C1]), PROFILE: FakeCardPage(PROFILE)}
    browser = CardBrowser(LAYOUT, lambda **kwargs: card_session(pages))

    with progress.scoped(SOURCE_SCOPE):
        await browser.cards(POST, PROFILE, want_post=True, targets=TARGETS)
    await browser.close()

    assert sequence(sink) == [
        ("source.capture_post_card", None, None, None),
        ("source.capture_comment_cards", 1, 1, None),
        ("source.page_gap", None, None, None),
        ("source.capture_profile", None, None, None),
    ]
    gap = next(r for r in sink.records if r.code == "source.page_gap")
    assert gap.wait_until is not None and gap.kind == "wait"


async def test_a_covered_row_counts_and_warns(sink: StepSink) -> None:
    pages = {
        POST: FakeCardPage(POST, tagged=[C1, C2], results={card_browser.COVERED_JS: True}),
        PROFILE: FakeCardPage(PROFILE),
    }
    browser = CardBrowser(LAYOUT, lambda **kwargs: card_session(pages))

    with progress.scoped(SOURCE_SCOPE):
        cards = await browser.cards(
            POST, PROFILE, want_post=True, targets=[*TARGETS, CommentTarget(C2, "fan_002", "b")]
        )
    await browser.close()

    assert cards.comment_pngs == {}
    assert sequence(sink) == [
        ("source.capture_post_card", None, None, None),
        ("source.capture_comment_cards", 1, 2, None),
        ("source.capture_comment_cards", 2, 2, None),
        ("source.gate_covered", None, None, {"count": 2}),
        ("source.page_gap", None, None, None),
        ("source.capture_profile", None, None, None),
    ]


async def test_a_login_wall_on_either_card_page_warns(sink: StepSink) -> None:
    pages = {POST: FakeCardPage(LOGIN, tagged=[C1]), PROFILE: FakeCardPage(LOGIN)}
    browser = CardBrowser(LAYOUT, lambda **kwargs: card_session(pages))

    with progress.scoped(SOURCE_SCOPE):
        await browser.cards(POST, PROFILE, want_post=True, targets=TARGETS)
    await browser.close()

    assert sequence(sink) == [
        ("source.login_wall", None, None, None),
        ("source.page_gap", None, None, None),
        ("source.login_wall", None, None, None),
    ]


def _embed(url_of: dict[str, str]) -> str:
    return url_of["embed"]


async def test_the_x_embed_loop_gaps_and_counts_its_cards(sink: StepSink) -> None:
    embed = x_service.EMBED_URL.format(comment_id=C2)
    pages = {POST: FakeCardPage(POST, tagged=[C1]), PROFILE: FakeCardPage(PROFILE)}
    pages[embed] = FakeCardPage(embed, results={x_service.EMBED_MATCH_JS: True})
    browser = XHeadlessBrowser(lambda **kwargs: card_session(pages))

    with progress.scoped(SOURCE_SCOPE):
        cards = await browser.cards(
            POST,
            PROFILE,
            want_post=True,
            targets=TARGETS,
            embeds=[CommentTarget(C1, "fan_001", "a reply"), CommentTarget(C2, "fan_002", "b")],
        )
    await browser.close()

    assert set(cards.comment_pngs) == {C1, C2}
    assert sequence(sink) == [
        ("source.capture_post_card", None, None, None),
        ("source.capture_comment_cards", 1, 1, None),
        ("source.page_gap", None, None, None),
        ("source.capture_profile", None, None, None),
        ("source.page_gap", None, None, None),
        ("source.capture_embed_cards", 1, 1, None),
    ]


async def test_tiktok_fetches_the_post_then_downloads_its_media(
    sink: StepSink, tmp_path: Path
) -> None:
    service = TikTokAcquisitionService(
        TikTokBrowser(complete_snapshot()), TikTokResolver(), TikTokMaterializer()
    )
    with progress.scoped(SOURCE_SCOPE):
        result = await service.inspect(
            workflow_id="wf_steps", source_url=TIKTOK_URL, artifact_root=tmp_path
        )
    assert result.report is not None
    assert sequence(sink) == [
        ("source.fetch_post", None, None, {"platform": "tiktok"}),
        ("source.download_media", 1, 1, None),
    ]


async def test_threads_fetches_the_post_then_downloads_the_carousel(
    sink: StepSink, tmp_path: Path
) -> None:
    node = _threads_node(carousel_media=_threads_images(2))
    acquirer = ThreadsAcquirer(
        ThreadsRequest(_threads_texts(node)),
        ThreadsHeadless(_threads_card_page()),
        ThreadsMaterializer(),
    )
    with progress.scoped(SOURCE_SCOPE):
        result = await acquirer.inspect(
            workflow_id="wf_steps",
            source_url="https://www.threads.net/@user_001/post/code_001?xmt=abc",
            artifact_root=tmp_path,
        )
    assert result.report is not None
    assert sequence(sink) == [
        ("source.fetch_post", None, None, {"platform": "threads"}),
        ("source.download_media", 1, 2, None),
        ("source.download_media", 2, 2, None),
    ]


async def test_instagram_fetches_the_post_then_downloads_the_carousel(
    sink: StepSink, tmp_path: Path
) -> None:
    node = _ig_node(carousel_media=[_ig_image(1), _ig_image(2)])
    acquirer = InstagramAcquirer(IgRequest(_ig_texts(node)), IgHeadless(_ig_cards()), IgMaterializer())
    with progress.scoped(SOURCE_SCOPE):
        result = await acquirer.inspect(
            workflow_id="wf_steps",
            source_url="https://www.instagram.com/p/code_001/",
            artifact_root=tmp_path,
        )
    assert result.report is not None
    assert sequence(sink) == [
        ("source.fetch_post", None, None, {"platform": "instagram"}),
        ("source.download_media", 1, 2, None),
        ("source.download_media", 2, 2, None),
    ]


async def test_x_fetches_the_post_then_downloads_its_media(
    sink: StepSink, tmp_path: Path
) -> None:
    from tests.acquisition.fakes import FakeMaterializer

    acquirer = XAcquirer(FakeRequest(), FakeHeadless(), FakeMaterializer(), FakeFx())
    with progress.scoped(SOURCE_SCOPE):
        result = await acquirer.inspect(
            workflow_id="wf_steps",
            source_url="https://twitter.com/someone/status/1800000000000000001?s=20",
            artifact_root=tmp_path,
        )
    assert result.report is not None
    assert sequence(sink) == [
        ("source.fetch_post", None, None, {"platform": "x"}),
        ("source.download_media", 1, 1, None),
    ]


async def test_youtube_fetches_the_post_then_downloads_the_video(
    sink: StepSink, tmp_path: Path
) -> None:
    from tests.acquisition.fakes import FakeMaterializer

    acquirer = YouTubeAcquirer(FakeClient(), YtHeadless(), FakeMaterializer())
    with progress.scoped(SOURCE_SCOPE):
        result = await acquirer.inspect(
            workflow_id="wf_steps",
            source_url="https://youtu.be/abcDEF123_-?si=share",
            artifact_root=tmp_path,
        )
    assert result.report is not None
    assert sequence(sink) == [
        ("source.fetch_post", None, None, {"platform": "youtube"}),
        ("source.download_media", 1, 1, None),
    ]


async def test_a_login_wall_on_a_request_fetcher_warns(sink: StepSink) -> None:
    async def x_get(url: str, **kwargs: Any) -> Any:
        return SimpleNamespace(status=200, url="https://x.com/i/flow/login?x=1")

    async def threads_get(url: str, **kwargs: Any) -> Any:
        return SimpleNamespace(status=200, url="https://www.threads.net/login")

    async def instagram_get(url: str, **kwargs: Any) -> Any:
        return SimpleNamespace(status=200, url="https://www.instagram.com/accounts/login")

    with progress.scoped(SOURCE_SCOPE):
        with pytest.raises(Exception):
            await XRequestFetcher(x_get).syndication("1800000000000000001")
        with pytest.raises(Exception):
            await ThreadsRequestFetcher(threads_get).fetch("https://www.threads.net/@u/p/x/")
        with pytest.raises(Exception):
            await InstagramRequestFetcher(instagram_get).fetch("https://www.instagram.com/p/x/")
    assert sequence(sink) == [
        ("source.login_wall", None, None, None),
        ("source.login_wall", None, None, None),
        ("source.login_wall", None, None, None),
    ]

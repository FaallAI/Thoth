"""Instagram acquisition over injected fakes: no network, no Scrapling."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.acquisition.png_fixtures import make_png
from thoth_control_plane.acquisition import instagram_service
from thoth_control_plane.acquisition.browser import HeadlessBrowserError
from thoth_control_plane.acquisition.instagram_service import (
    InstagramAcquirer,
    InstagramCards,
    InstagramRequestFetcher,
    RequestFetchError,
)
from thoth_control_plane.acquisition.materializer import MediaMaterializationError
from thoth_control_plane.acquisition.models import (
    AcquisitionReason,
    AcquisitionStrategy,
    MaterializedMedia,
)

URL = "https://www.instagram.com/p/code_001/?igsh=abc"
CANONICAL = "https://www.instagram.com/p/code_001/"
SHARE_URL = "https://www.instagram.com/share/p/tok_001/"
WF = "wf_instagram_001"
C1, C2 = "18000000000000000001", "18000000000000000002"


def _image(n: int) -> dict[str, Any]:
    return {
        "image_versions2": {
            "candidates": [{"url": f"https://img.example.test/{n}.jpg", "width": 9, "height": 9}]
        }
    }


def _video(n: int) -> dict[str, Any]:
    return {
        "video_versions": [{"url": f"https://video.example.test/{n}.mp4", "width": 9, "height": 16}]
    }


def _node(**extra: Any) -> dict[str, Any]:
    return {
        "code": "code_001",
        "pk": "3000000000000000001",
        "user": {"username": "user_001"},
        "caption": {"text": "hello world"},
        "taken_at": 1_700_000_000,
        "like_count": 1_200,
        "comment_count": 2,
        **_image(0),
        **extra,
    }


def _comment(pk: str, text: str, author: str) -> dict[str, Any]:
    return {"pk": pk, "text": text, "comment_like_count": 3, "user": {"username": author}}


COMMENTS = (_comment(C1, "first comment here", "fan_001"), _comment(C2, "second", "fan_002"))


def _texts(node: dict[str, Any], comments: tuple[dict[str, Any], ...] = COMMENTS) -> list[str]:
    media = {
        "if_not_gated_logged_out": node,
        "comments_connection": {"edges": [{"node": c} for c in comments]},
    }
    return [json.dumps({"require": [{"data": {"xig_polaris_media": media}}]})]


class FakeRequest:
    def __init__(
        self,
        texts: list[str] | None = None,
        error: AcquisitionReason | None = None,
        landing: str | AcquisitionReason = CANONICAL,
    ) -> None:
        self.texts, self.error, self.landing_to, self.calls = texts or [], error, landing, 0
        self.landed: list[str] = []

    async def fetch(self, url: str) -> list[str]:
        self.calls += 1
        if self.error is not None:
            raise RequestFetchError(self.error)
        return self.texts

    async def landing(self, share_url: str) -> str:
        self.landed.append(share_url)
        if isinstance(self.landing_to, AcquisitionReason):
            raise RequestFetchError(self.landing_to)
        return self.landing_to


class FakeHeadless:
    def __init__(self, cards: InstagramCards | None = None, texts: list[str] | None = None):
        self.result, self.texts = cards or InstagramCards(), texts or []
        self.card_calls: list[dict[str, Any]] = []
        self.script_calls, self.closed = 0, 0

    async def scripts(self, url: str) -> list[str]:
        self.script_calls += 1
        return self.texts

    async def resolve(self, share_url: str) -> str:
        raise HeadlessBrowserError(AcquisitionReason.HEADLESS_INCOMPLETE)

    async def cards(self, post_url: str, profile_url: str, *, want_post: bool, targets: list):
        self.card_calls.append(
            {"post": post_url, "profile": profile_url, "want_post": want_post, "targets": targets}
        )
        return self.result

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


def _cards(**overrides: Any) -> InstagramCards:
    values = {
        "post_png": make_png(400, 200),
        "comment_pngs": {C1: make_png(400, 80)},
        "profile_png": make_png(400, 200),
    }
    return InstagramCards(**{**values, **overrides})


async def _inspect(tmp_path: Path, request, headless, materializer=None, url: str = URL):
    acquirer = InstagramAcquirer(request, headless, materializer or FakeMaterializer())
    return await acquirer.inspect(workflow_id=WF, source_url=url, artifact_root=tmp_path)


@pytest.mark.asyncio
async def test_image_post_report_carries_comments_and_cards(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    headless = FakeHeadless(_cards())
    result = await _inspect(tmp_path, FakeRequest(_texts(_node())), headless)

    report = result.report
    assert report is not None
    assert report.source.platform == "instagram"
    assert str(report.source.canonical_url) == CANONICAL
    assert report.post.owner_handle == "user_001"
    assert [item.kind for item in report.media] == ["image"]
    assert [c.comment_id for c in report.comments] == [C1, C2]
    assert str(report.comments[0].card.location).endswith(f"cards/comment-{C1}.png")
    assert report.comments[1].card is None
    assert str(report.post_card.location).endswith("cards/post.png")
    assert str(report.profile_card.location).endswith("cards/profile.png")
    assert (tmp_path / str(report.post_card.location)).is_file()
    assert report.outcome.attempts[0].strategy is AcquisitionStrategy.SCRAPLING_REQUEST
    call = headless.card_calls[0]
    assert (call["post"], call["profile"], call["want_post"]) == (
        CANONICAL,
        "https://www.instagram.com/user_001/",
        True,
    )
    assert [t.comment_id for t in call["targets"]] == [C1, C2]
    assert headless.closed == 1
    assert "instagram.com" not in caplog.text
    assert "hello world" not in caplog.text
    assert "user_001" not in caplog.text


@pytest.mark.asyncio
async def test_video_post_asks_for_its_post_card(tmp_path: Path) -> None:
    node = _node(media_type=2, **_video(0))
    headless = FakeHeadless(_cards(profile_page_png=make_png(400, 900)))
    result = await _inspect(tmp_path, FakeRequest(_texts(node)), headless)
    assert result.report is not None
    assert [item.kind for item in result.report.media] == ["video"]
    assert headless.card_calls[0]["want_post"] is True
    assert result.report.post_card is not None
    assert result.report.profile_page is not None


@pytest.mark.asyncio
async def test_carousel_with_a_video_asks_for_its_post_card(tmp_path: Path) -> None:
    node = _node(carousel_media=[_image(1), _video(2)])
    headless = FakeHeadless(_cards())
    result = await _inspect(tmp_path, FakeRequest(_texts(node)), headless)
    assert result.report is not None
    assert [item.kind for item in result.report.media] == ["image", "video"]
    assert headless.card_calls[0]["want_post"] is True


@pytest.mark.asyncio
async def test_a_flat_card_is_rejected_and_absent(tmp_path: Path) -> None:
    headless = FakeHeadless(_cards(post_png=make_png(400, 200, flat=True)))
    result = await _inspect(tmp_path, FakeRequest(_texts(_node())), headless)
    assert result.report is not None
    assert result.report.post_card is None
    assert result.report.profile_card is not None


@pytest.mark.asyncio
async def test_card_problems_still_give_a_report(tmp_path: Path) -> None:
    headless = FakeHeadless(InstagramCards(problems=["headless_timeout", "headless_timeout"]))
    result = await _inspect(tmp_path, FakeRequest(_texts(_node())), headless)
    report = result.report
    assert report is not None
    assert report.post_card is report.profile_card is None
    assert [c.card for c in report.comments] == [None, None]
    assert len(report.outcome.attempts) == 1


@pytest.mark.asyncio
async def test_a_blocked_request_is_retryable_and_skips_cards(tmp_path: Path) -> None:
    headless = FakeHeadless()
    result = await _inspect(
        tmp_path, FakeRequest(error=AcquisitionReason.REQUEST_BLOCKED), headless
    )
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("request_blocked", True)
    assert headless.card_calls == []
    assert headless.closed == 1


@pytest.mark.asyncio
async def test_require_login_is_request_blocked_with_a_login_wall_attempt(tmp_path: Path) -> None:
    texts = [json.dumps({"message": "x", "require_login": True, "status": "fail"})]
    result = await _inspect(tmp_path, FakeRequest(texts), FakeHeadless())
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("request_blocked", True)
    assert [a.reason for a in result.failure.attempts] == [AcquisitionReason.LOGIN_WALL]


@pytest.mark.asyncio
async def test_a_missing_post_node_is_request_incomplete(tmp_path: Path) -> None:
    result = await _inspect(tmp_path, FakeRequest(_texts(_node(code="other_01"))), FakeHeadless())
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("request_incomplete", True)


@pytest.mark.asyncio
async def test_missing_owner_is_request_incomplete(tmp_path: Path) -> None:
    result = await _inspect(tmp_path, FakeRequest(_texts(_node(user={}))), FakeHeadless())
    assert result.failure is not None
    assert result.failure.code == "request_incomplete"


@pytest.mark.asyncio
async def test_text_only_post_is_a_report_with_a_post_card(tmp_path: Path) -> None:
    node = _node(image_versions2=None)
    headless = FakeHeadless(_cards())
    result = await _inspect(tmp_path, FakeRequest(_texts(node)), headless)
    assert result.report is not None
    assert result.report.post.text == "hello world"
    assert result.report.media == []
    assert headless.card_calls[0]["want_post"] is True
    assert result.report.post_card is not None


@pytest.mark.asyncio
async def test_whitespace_only_post_without_media_is_no_content(tmp_path: Path) -> None:
    node = _node(caption={"text": "   "}, image_versions2=None)
    result = await _inspect(tmp_path, FakeRequest(_texts(node)), FakeHeadless())
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("no_content", False)


@pytest.mark.asyncio
async def test_an_invalid_url_fails_before_any_fetch(tmp_path: Path) -> None:
    request = FakeRequest(_texts(_node()))
    result = await _inspect(
        tmp_path, request, FakeHeadless(), url="https://www.instagram.com/user_001/"
    )
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("invalid_source_url", False)
    assert request.calls == 0


@pytest.mark.asyncio
async def test_share_link_landing_on_the_login_wall_is_request_blocked(tmp_path: Path) -> None:
    async def get(url: str, **kwargs: Any):
        return SimpleNamespace(
            status=200,
            url="https://www.instagram.com/accounts/login/?next=%2Fshare%2Fp%2Ftok_001%2F",
            css=lambda selector: SimpleNamespace(getall=lambda: []),
        )

    result = await _inspect(tmp_path, InstagramRequestFetcher(get), FakeHeadless(), url=SHARE_URL)
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("request_blocked", True)
    # The attempt names the login wall, so a leased account expires instead of cooling down.
    assert [a.reason for a in result.failure.attempts] == [AcquisitionReason.LOGIN_WALL]


@pytest.mark.asyncio
async def test_share_link_resolves_before_the_content_fetch(tmp_path: Path) -> None:
    request = FakeRequest(
        _texts(_node()), landing="https://www.instagram.com/reel/code_001/?igsh=x"
    )
    result = await _inspect(tmp_path, request, FakeHeadless(_cards()), url=SHARE_URL)
    assert result.report is not None
    assert request.landed == [SHARE_URL]
    assert str(result.report.source.canonical_url) == CANONICAL


@pytest.mark.asyncio
async def test_share_link_landing_off_a_post_is_invalid(tmp_path: Path) -> None:
    request = FakeRequest(landing="https://www.instagram.com/user_001/")
    result = await _inspect(tmp_path, request, FakeHeadless(), url=SHARE_URL)
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("invalid_source_url", False)
    assert request.calls == 0


@pytest.mark.asyncio
async def test_mid_carousel_failure_leaves_no_orphans_and_no_cards(tmp_path: Path) -> None:
    node = _node(carousel_media=[_image(1), _image(2), _image(3)])
    headless = FakeHeadless(_cards())
    result = await _inspect(
        tmp_path, FakeRequest(_texts(node)), headless, FakeMaterializer(fail_at=2)
    )
    assert result.failure is not None
    assert result.failure.code == "media_validation_failed"
    assert headless.card_calls == []
    media_dir = tmp_path / "reports" / WF / "media"
    assert not media_dir.exists() or list(media_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_headless_content_method_uses_the_browser_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(instagram_service, "CONTENT_METHOD", "headless")
    request = FakeRequest()
    headless = FakeHeadless(_cards(), texts=_texts(_node()))
    result = await _inspect(tmp_path, request, headless)
    assert result.report is not None
    assert request.calls == 0
    assert headless.script_calls == 1
    assert result.report.outcome.attempts[0].strategy is AcquisitionStrategy.SCRAPLING_HEADLESS


class _HangingHeadless(FakeHeadless):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()

    async def cards(self, *args: Any, **kwargs: Any):
        self.started.set()
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_cancellation_during_cards_still_closes_the_browser(tmp_path: Path) -> None:
    headless = _HangingHeadless()
    task = asyncio.create_task(_inspect(tmp_path, FakeRequest(_texts(_node())), headless))
    await headless.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert headless.closed == 1

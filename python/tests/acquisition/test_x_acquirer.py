"""X acquisition over injected fakes: no network, no Scrapling."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from tests.acquisition.fakes import FakeMaterializer
from tests.acquisition.png_fixtures import make_png
from thoth_control_plane.acquisition.card_browser import Cards
from thoth_control_plane.acquisition.models import (
    AcquisitionReason,
    AcquisitionStrategy,
    MediaBox,
)
from thoth_control_plane.acquisition.x_service import RequestFetchError, XAcquirer

POST_ID = "1800000000000000001"
URL = f"https://twitter.com/someone/status/{POST_ID}?s=20"
CANONICAL = f"https://x.com/user_001/status/{POST_ID}"
WF = "wf_x_001"
C1, C2 = "1800000000000000101", "1800000000000000102"


def _synd(**extra: Any) -> dict[str, Any]:
    return {
        "__typename": "Tweet",
        "id_str": POST_ID,
        "text": "hello world https://t.co/abc",
        "display_text_range": [0, 11],
        "created_at": "2024-05-01T12:34:56.000Z",
        "favorite_count": 1200,
        "conversation_count": 34,
        "user": {"screen_name": "user_001"},
        "mediaDetails": [{"type": "photo", "media_url_https": "https://pbs.twimg.com/media/a.jpg"}],
        **extra,
    }


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "x_fxembed"


def _status(**extra: Any) -> dict[str, Any]:
    return {
        "id": POST_ID,
        "text": "hello world",
        "author": {"screen_name": "user_001"},
        "likes": 3,
        "replies": 1,
        "reposts": 2,
        "views": 4500,
        **extra,
    }


def _reply(reply_id: str, author: str, text: str) -> dict[str, Any]:
    return {
        "id": reply_id,
        "text": text,
        "author": {"screen_name": author},
        "likes": 3,
        "replying_to": {"screen_name": "user_001", "status": POST_ID},
    }


REPLIES = [_reply(C1, "fan_001", "@user_001 first reply"), _reply(C2, "fan_002", "second")]
_STATUS = object()


class FakeRequest:
    def __init__(self, data: object = _STATUS, error: AcquisitionReason | None = None) -> None:
        self.data = _synd() if data is _STATUS else data
        self.error = error
        self.calls: list[tuple[str, str]] = []

    async def syndication(self, post_id: str) -> object:
        self.calls.append(("syndication", post_id))
        if self.error is not None:
            raise RequestFetchError(self.error)
        return self.data


class FakeFx:
    def __init__(
        self,
        status: object = _STATUS,
        replies: list[dict[str, Any]] | None = None,
        error: AcquisitionReason | None = None,
        replies_error: AcquisitionReason | None = None,
    ) -> None:
        self.data = _status() if status is _STATUS else status
        self.replies_error = replies_error
        self.reply_list = REPLIES if replies is None else replies
        self.error = error
        self.calls: list[tuple[str, str]] = []

    async def status(self, post_id: str) -> object:
        self.calls.append(("status", post_id))
        if self.error is not None:
            raise RequestFetchError(self.error)
        return self.data

    async def replies(self, post_id: str) -> list[dict[str, Any]]:
        self.calls.append(("replies", post_id))
        if self.replies_error is not None:
            raise RequestFetchError(self.replies_error)
        return self.reply_list


class FakeHeadless:
    def __init__(self, cards: Cards | None = None) -> None:
        self.result = cards or Cards()
        self.card_calls: list[dict[str, Any]] = []
        self.closed = 0

    async def cards(
        self, post_url: str, profile_url: str, *, want_post: bool, targets: list, embeds=None
    ):
        self.card_calls.append(
            {
                "post": post_url,
                "profile": profile_url,
                "want_post": want_post,
                "targets": targets,
                "embeds": embeds,
            }
        )
        return self.result

    async def close(self) -> None:
        self.closed += 1


def _cards(**overrides: Any) -> Cards:
    values = {
        "post_png": make_png(400, 200),
        "comment_pngs": {C1: make_png(400, 80)},
        "profile_png": make_png(400, 200),
    }
    return Cards(**{**values, **overrides})


async def _inspect(tmp_path: Path, request, headless, materializer=None, url: str = URL, fx=None):
    acquirer = XAcquirer(request, headless, materializer or FakeMaterializer(), fx or FakeFx())
    return await acquirer.inspect(workflow_id=WF, source_url=url, artifact_root=tmp_path)


@pytest.mark.asyncio
async def test_post_report_carries_media_replies_views_and_cards(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    request, headless = FakeRequest(), FakeHeadless(_cards())
    result = await _inspect(tmp_path, request, headless)

    report = result.report
    assert report is not None
    assert (report.source.platform, str(report.source.canonical_url)) == ("x", CANONICAL)
    assert report.post.owner_handle == "user_001"
    assert report.post.text == "hello world"
    assert report.post.engagement == {"like": 1200, "comment": 34, "share": 2, "play": 4500}
    assert [item.kind for item in report.media] == ["image"]
    assert [(c.comment_id, c.text) for c in report.comments] == [
        (C1, "first reply"),
        (C2, "second"),
    ]
    assert str(report.comments[0].card.location).endswith(f"cards/comment-{C1}.png")
    assert report.comments[1].card is None
    assert report.post_card is not None and report.profile_card is not None
    assert report.outcome.attempts[0].strategy is AcquisitionStrategy.SCRAPLING_REQUEST
    assert request.calls == [("syndication", POST_ID)]
    call = headless.card_calls[0]
    assert (call["post"], call["profile"], call["want_post"]) == (
        CANONICAL,
        "https://x.com/user_001",
        True,
    )
    # Embed candidates are the replies past the noise check, most liked first (spec D1/D3).
    assert [target.comment_id for target in call["embeds"]] == [C1, C2]
    assert [t.comment_id for t in call["targets"]] == [C1, C2]
    assert headless.closed == 1
    assert "x.com" not in caplog.text
    assert "hello world" not in caplog.text
    assert "user_001" not in caplog.text


@pytest.mark.asyncio
async def test_a_video_post_asks_for_its_post_card(tmp_path: Path) -> None:
    # Style A shows the post with its video playing inside (spec 5c-2, G1).
    variants = [{"type": "video/mp4", "src": "https://video.twimg.com/vid/1280x720/a.mp4"}]
    data = _synd(mediaDetails=[{"type": "video"}], video={"variants": variants})
    box = MediaBox(x=0.0, y=0.3, w=1.0, h=0.5)
    headless = FakeHeadless(_cards(post_media_box=box, profile_page_png=make_png(400, 900)))
    result = await _inspect(tmp_path, FakeRequest(data), headless)
    assert result.report is not None
    assert [item.kind for item in result.report.media] == ["video"]
    assert headless.card_calls[0]["want_post"] is True
    assert result.report.post_card is not None and result.report.post_card.media_box == box
    assert result.report.profile_page is not None


@pytest.mark.asyncio
async def test_an_fxembed_outage_falls_back_to_syndication_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    fx = FakeFx(error=AcquisitionReason.REQUEST_BLOCKED)
    result = await _inspect(tmp_path, FakeRequest(), FakeHeadless(_cards()), fx=fx)
    assert result.report is not None
    assert result.report.comments == []
    assert result.report.post.engagement == {"like": 1200, "comment": 34}
    assert "x fxembed enrichment unavailable reason=request_blocked" in caplog.text
    assert fx.calls == [("status", POST_ID)]


@pytest.mark.asyncio
async def test_a_replies_failure_keeps_the_videos_and_counters(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # Review: a failed conversation read must not throw away the status it follows.
    data = _synd(mediaDetails=[{"type": "video"}, {"type": "video"}])
    fx = FakeFx(
        _fixture_status("status_multi_video.json"), replies_error=AcquisitionReason.REQUEST_TIMEOUT
    )
    result = await _inspect(tmp_path, FakeRequest(data), FakeHeadless(_cards()), fx=fx)
    assert result.report is not None
    assert [item.kind for item in result.report.media] == ["video", "video"]
    assert "play" in result.report.post.engagement
    assert result.report.comments == []
    assert "x fxembed replies unavailable reason=request_timeout" in caplog.text


@pytest.mark.asyncio
async def test_a_missing_fxembed_status_still_yields_a_report(tmp_path: Path) -> None:
    fx = FakeFx(status=None, replies=[])
    result = await _inspect(tmp_path, FakeRequest(), FakeHeadless(_cards()), fx=fx)
    assert result.report is not None
    assert result.report.comments == []
    assert fx.calls == [("status", POST_ID)]


@pytest.mark.asyncio
async def test_a_long_tweet_takes_the_fxembed_text(tmp_path: Path) -> None:
    fx = FakeFx(_status(text="hello world and the rest"))
    request = FakeRequest(_synd(note_tweet={"id": "n1"}))
    result = await _inspect(tmp_path, request, FakeHeadless(_cards()), fx=fx)
    assert result.report is not None
    assert result.report.post.text == "hello world and the rest"


def _fixture_status(name: str) -> dict[str, Any]:
    status = json.loads((FIXTURES / name).read_text(encoding="utf-8"))["status"]
    return {**status, "id": POST_ID}


@pytest.mark.asyncio
async def test_a_multi_video_post_materializes_every_video_in_order(tmp_path: Path) -> None:
    data = _synd(mediaDetails=[{"type": "video"}, {"type": "video"}])
    fx = FakeFx(_fixture_status("status_multi_video.json"))
    result = await _inspect(tmp_path, FakeRequest(data), FakeHeadless(_cards()), fx=fx)
    assert result.report is not None
    assert [item.kind for item in result.report.media] == ["video", "video"]


@pytest.mark.asyncio
async def test_fxembed_videos_survive_a_syndication_listing_one_video(tmp_path: Path) -> None:
    variants = [{"type": "video/mp4", "src": "https://video.twimg.com/vid/1280x720/a.mp4"}]
    data = _synd(mediaDetails=[{"type": "video"}], video={"variants": variants})
    fx = FakeFx(_fixture_status("status_multi_video.json"))
    result = await _inspect(tmp_path, FakeRequest(data), FakeHeadless(_cards()), fx=fx)
    assert result.report is not None
    assert [item.kind for item in result.report.media] == ["video", "video"]


@pytest.mark.asyncio
async def test_a_deleted_tweet_is_request_incomplete(tmp_path: Path) -> None:
    # The fetcher maps a 404 or a non-JSON body to None.
    request, headless = FakeRequest(data=None), FakeHeadless()
    result = await _inspect(tmp_path, request, headless)
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("request_incomplete", True)
    assert len(result.failure.attempts) == 1
    assert request.calls == [("syndication", POST_ID)]
    assert headless.card_calls == []
    assert headless.closed == 1


@pytest.mark.asyncio
async def test_a_tombstone_is_request_incomplete(tmp_path: Path) -> None:
    request = FakeRequest({"__typename": "TweetTombstone"})
    result = await _inspect(tmp_path, request, FakeHeadless())
    assert result.failure is not None
    assert result.failure.code == "request_incomplete"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason", [AcquisitionReason.REQUEST_BLOCKED, AcquisitionReason.REQUEST_TIMEOUT]
)
async def test_syndication_failures_are_retryable(
    tmp_path: Path, reason: AcquisitionReason
) -> None:
    request = FakeRequest(error=reason)
    result = await _inspect(tmp_path, request, FakeHeadless())
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == (reason.value, True)
    assert request.calls == [("syndication", POST_ID)]


@pytest.mark.asyncio
async def test_no_text_and_no_media_is_no_content(tmp_path: Path) -> None:
    data = _synd(text="   ", display_text_range=[0, 3], mediaDetails=[])
    fx = FakeFx(status=None, replies=[])
    result = await _inspect(tmp_path, FakeRequest(data), FakeHeadless(), fx=fx)
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("no_content", False)


@pytest.mark.asyncio
async def test_an_invalid_url_fails_before_any_fetch(tmp_path: Path) -> None:
    request = FakeRequest()
    result = await _inspect(tmp_path, request, FakeHeadless(), url="https://x.com/user_001")
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("invalid_source_url", False)
    assert request.calls == []


@pytest.mark.asyncio
async def test_a_media_failure_skips_cards_and_leaves_no_orphans(tmp_path: Path) -> None:
    photos = [
        {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/a.jpg"},
        {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/b.jpg"},
    ]
    headless = FakeHeadless(_cards())
    result = await _inspect(
        tmp_path, FakeRequest(_synd(mediaDetails=photos)), headless, FakeMaterializer(fail_at=2)
    )
    assert result.failure is not None
    assert result.failure.code == "media_validation_failed"
    assert headless.card_calls == []
    media_dir = tmp_path / "reports" / WF / "media"
    assert not media_dir.exists() or list(media_dir.iterdir()) == []


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
    task = asyncio.create_task(_inspect(tmp_path, FakeRequest(), headless))
    await headless.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert headless.closed == 1

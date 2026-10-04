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
from thoth_control_plane.acquisition.models import AcquisitionReason, AcquisitionStrategy
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


def _tweet(rest_id: str, author: str, text: str, reply_to: str | None) -> dict[str, Any]:
    node: dict[str, Any] = {
        "__typename": "Tweet",
        "rest_id": rest_id,
        "core": {"user_results": {"result": {"core": {"screen_name": author}}}},
        "details": {"full_text": text, "created_at_ms": 1_714_566_896_000},
        "counts": {"favorite_count": 3, "reply_count": 1, "retweet_count": 2},
        "views": {"count": "4500"},
    }
    if reply_to is not None:
        node["reply_to_results"] = {"rest_id": reply_to}
    return node


def _page(*tweets: dict[str, Any]) -> str:
    # Compact JSON is a subset of the seroval literals the decoder reads.
    root = json.dumps({"entries": list(tweets)}, separators=(",", ":"))
    return f'<script>($R=>$R[0].next({root}))($R["k"])</script>'


PAGE = _page(
    _tweet(POST_ID, "user_001", "hello world", None),
    _tweet(C1, "fan_001", "@user_001 first reply", POST_ID),
    _tweet(C2, "fan_002", "second", POST_ID),
)


_SYND = object()


class FakeRequest:
    def __init__(
        self,
        data: object = _SYND,
        page: str = PAGE,
        error: AcquisitionReason | None = None,
        page_error: AcquisitionReason | None = None,
    ) -> None:
        self.data = _synd() if data is _SYND else data
        self.page_html, self.error, self.page_error = page, error, page_error
        self.calls: list[tuple[str, str]] = []

    async def syndication(self, post_id: str) -> object:
        self.calls.append(("syndication", post_id))
        if self.error is not None:
            raise RequestFetchError(self.error)
        return self.data

    async def page(self, url: str) -> str:
        self.calls.append(("page", url))
        if self.page_error is not None:
            raise RequestFetchError(self.page_error)
        return self.page_html


class FakeHeadless:
    def __init__(self, cards: Cards | None = None) -> None:
        self.result = cards or Cards()
        self.card_calls: list[dict[str, Any]] = []
        self.closed = 0

    async def cards(self, post_url: str, profile_url: str, *, want_post: bool, targets: list):
        self.card_calls.append(
            {"post": post_url, "profile": profile_url, "want_post": want_post, "targets": targets}
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


async def _inspect(tmp_path: Path, request, headless, materializer=None, url: str = URL):
    acquirer = XAcquirer(request, headless, materializer or FakeMaterializer())
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
    assert request.calls == [("syndication", POST_ID), ("page", CANONICAL)]
    call = headless.card_calls[0]
    assert (call["post"], call["profile"], call["want_post"]) == (
        CANONICAL,
        "https://x.com/user_001",
        True,
    )
    assert [t.comment_id for t in call["targets"]] == [C1, C2]
    assert headless.closed == 1
    assert "x.com" not in caplog.text
    assert "hello world" not in caplog.text
    assert "user_001" not in caplog.text


@pytest.mark.asyncio
async def test_a_video_post_asks_for_no_post_card(tmp_path: Path) -> None:
    variants = [{"type": "video/mp4", "src": "https://video.twimg.com/vid/1280x720/a.mp4"}]
    data = _synd(mediaDetails=[{"type": "video"}], video={"variants": variants})
    headless = FakeHeadless(_cards(post_png=None))
    result = await _inspect(tmp_path, FakeRequest(data), headless)
    assert result.report is not None
    assert [item.kind for item in result.report.media] == ["video"]
    assert headless.card_calls[0]["want_post"] is False


@pytest.mark.asyncio
async def test_a_failed_page_still_yields_a_report(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    request = FakeRequest(page_error=AcquisitionReason.REQUEST_BLOCKED)
    result = await _inspect(tmp_path, request, FakeHeadless(_cards()))
    assert result.report is not None
    assert result.report.comments == []
    assert result.report.post.engagement == {"like": 1200, "comment": 34}
    assert "x page enrichment unavailable reason=request_blocked" in caplog.text


@pytest.mark.asyncio
async def test_an_unreadable_page_still_yields_a_report(tmp_path: Path) -> None:
    request = FakeRequest(page="<html><script>($R=>$R[0].next({a:</script></html>")
    result = await _inspect(tmp_path, request, FakeHeadless(_cards()))
    assert result.report is not None
    assert result.report.comments == []


@pytest.mark.asyncio
async def test_a_long_tweet_takes_the_page_text(tmp_path: Path) -> None:
    note = {"note_tweet_results": {"result": {"text": "hello world and the rest"}}}
    post = {**_tweet(POST_ID, "user_001", "hello world", None), "note_tweet": note}
    request = FakeRequest(_synd(note_tweet={"id": "n1"}), page=_page(post))
    result = await _inspect(tmp_path, request, FakeHeadless(_cards()))
    assert result.report is not None
    assert result.report.post.text == "hello world and the rest"


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
    result = await _inspect(tmp_path, FakeRequest(data, page=""), FakeHeadless())
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

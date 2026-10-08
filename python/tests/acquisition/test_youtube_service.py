"""The yt-dlp client and the YouTube card browser over injected fakes; no network."""

from __future__ import annotations

import asyncio
import gc
import logging
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from tests.acquisition.fakes import FakeCardPage, card_session
from thoth_control_plane.acquisition import youtube_service
from thoth_control_plane.acquisition.adapters.youtube import MAX_DOWNLOAD_BYTES, FormatChoice
from thoth_control_plane.acquisition.browser import active_scrapling_session_count
from thoth_control_plane.acquisition.card_browser import COMMENT_ROW_ATTRIBUTE, CommentTarget
from thoth_control_plane.acquisition.materializer import MediaMaterializationError
from thoth_control_plane.acquisition.models import AcquisitionReason
from thoth_control_plane.acquisition.youtube_service import (
    PROFILE_CARD_SELECTOR,
    TAG_COMMENTS_JS,
    YouTubeHeadlessBrowser,
    YtDlpClient,
    YtDlpError,
    classify,
)

URL = "https://www.youtube.com/watch?v=abcDEF123_-"
CHANNEL = "https://www.youtube.com/channel/UCuser001abcdefghijklmno"
CHOICE = FormatChoice(video_format="137", audio_format="140", short_side=1080, estimated_bytes=1)


class FakeYdl:
    """Records the options it was built with; returns or raises what it was given."""

    def __init__(self, options: dict[str, Any], result: Any, on_download=None) -> None:
        self.options, self.result, self.on_download = options, result, on_download

    def __enter__(self) -> FakeYdl:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def extract_info(self, url: str, download: bool) -> Any:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def download(self, urls: list[str]) -> int:
        if isinstance(self.result, Exception):
            raise self.result
        if self.on_download is not None:
            self.on_download(self.options)
        return 0


def _client(result: Any, seen: list[dict[str, Any]], on_download=None) -> YtDlpClient:
    def factory(options: dict[str, Any]) -> FakeYdl:
        seen.append(options)
        return FakeYdl(options, result, on_download)

    return YtDlpClient(factory)


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("ERROR: Sign in to confirm you're not a bot", AcquisitionReason.REQUEST_BLOCKED),
        ("ERROR: Sign in to confirm your age", AcquisitionReason.REQUEST_BLOCKED),
        (
            "ERROR: Private video. Sign in if you've been granted access",
            AcquisitionReason.REQUEST_INCOMPLETE,
        ),
        ("ERROR: Video unavailable", AcquisitionReason.REQUEST_INCOMPLETE),
        (
            "ERROR: This video has been removed by the uploader",
            AcquisitionReason.REQUEST_INCOMPLETE,
        ),
        ("ERROR: Read timed out", AcquisitionReason.REQUEST_TIMEOUT),
        ("ERROR: Requested format is not available", AcquisitionReason.REQUEST_BLOCKED),
        ("something new", AcquisitionReason.REQUEST_BLOCKED),
    ],
)
def test_classify_maps_message_classes(message: str, reason: AcquisitionReason) -> None:
    assert classify(RuntimeError(message)) is reason


def test_a_stale_extractor_warns_without_the_message(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    classify(RuntimeError("nsig extraction failed for https://www.youtube.com/watch?v=x"))
    assert "yt-dlp needs an update" in caplog.text
    assert "youtube.com" not in caplog.text


def test_a_timeout_error_is_a_timeout() -> None:
    assert classify(TimeoutError()) is AcquisitionReason.REQUEST_TIMEOUT


@pytest.mark.asyncio
async def test_extract_asks_for_first_page_comments_with_bun() -> None:
    seen: list[dict[str, Any]] = []
    info = await _client({"id": "x"}, seen).extract(URL, comments=True)
    assert info == {"id": "x"}
    options = seen[0]
    assert options["getcomments"] is True
    # The watch page renders top comments; yt-dlp's default order is newest first.
    assert options["extractor_args"] == {
        "youtube": {"max_comments": ["50", "50", "0", "0"], "comment_sort": ["top"]}
    }
    assert options["js_runtimes"] == {"bun": {}}
    assert options["skip_download"] is True
    assert options["quiet"] is True


@pytest.mark.asyncio
async def test_extract_without_comments_skips_them() -> None:
    seen: list[dict[str, Any]] = []
    await _client({"id": "x"}, seen).extract(URL, comments=False)
    assert "getcomments" not in seen[0]


@pytest.mark.asyncio
async def test_extract_failures_become_reasons() -> None:
    with pytest.raises(YtDlpError) as caught:
        await _client(RuntimeError("Video unavailable"), []).extract(URL, comments=True)
    assert caught.value.reason is AcquisitionReason.REQUEST_INCOMPLETE
    with pytest.raises(YtDlpError) as caught:
        await _client(["not", "a", "dict"], []).extract(URL, comments=True)
    assert caught.value.reason is AcquisitionReason.REQUEST_INCOMPLETE


@pytest.mark.asyncio
async def test_extract_has_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(youtube_service, "EXTRACT_TIMEOUT_SECONDS", 0.05)

    class Slow(FakeYdl):
        def extract_info(self, url: str, download: bool) -> Any:
            time.sleep(0.5)
            return {}

    client = YtDlpClient(lambda options: Slow(options, None))
    with pytest.raises(YtDlpError) as caught:
        await client.extract(URL, comments=False)
    assert caught.value.reason is AcquisitionReason.REQUEST_TIMEOUT


@pytest.mark.asyncio
async def test_download_merges_the_chosen_pair_into_mp4(tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []

    def write(options: dict[str, Any]) -> None:
        (tmp_path / "merged.mp4").write_bytes(b"x")

    merged = await _client(None, seen, write).download(URL, CHOICE, tmp_path)
    assert merged == tmp_path / "merged.mp4"
    options = seen[0]
    assert options["format"] == "137+140"
    assert options["merge_output_format"] == "mp4"
    assert options["outtmpl"] == {"default": str(tmp_path / "merged.%(ext)s")}
    # A bitrate estimate can be far off; yt-dlp stops a format over the cap itself.
    assert options["max_filesize"] == MAX_DOWNLOAD_BYTES


@pytest.mark.asyncio
async def test_a_failed_or_empty_download_is_a_media_failure(tmp_path: Path) -> None:
    with pytest.raises(MediaMaterializationError):
        await _client(RuntimeError("HTTP Error 403"), []).download(URL, CHOICE, tmp_path)
    with pytest.raises(MediaMaterializationError):
        await _client(None, []).download(URL, CHOICE, tmp_path)


C1 = "UgzComment001"
TARGETS = [CommentTarget(C1, "fan_001", "first comment")]


@pytest.mark.asyncio
async def test_cards_crop_comments_and_the_channel_header_never_a_post() -> None:
    post_page, channel_page = FakeCardPage(URL, tagged=[C1]), FakeCardPage(CHANNEL)
    session = card_session({URL: post_page, CHANNEL: channel_page})
    browser = YouTubeHeadlessBrowser(lambda **kwargs: session)

    cards = await browser.cards(URL, CHANNEL, want_post=False, targets=TARGETS)
    await browser.close()

    assert cards.post_png is None
    assert list(cards.comment_pngs) == [C1]
    assert cards.profile_png is not None
    assert post_page.shots == [f'[{COMMENT_ROW_ATTRIBUTE}="{C1}"]']
    assert post_page.evaluated == [
        (TAG_COMMENTS_JS, [{"comment_id": C1, "author": "fan_001", "prefix": "first comment"}])
    ]
    assert channel_page.shots == [PROFILE_CARD_SELECTOR] == ["#page-header"]
    assert post_page.clicked == channel_page.clicked == []
    assert session.exited == 1
    assert active_scrapling_session_count() == 0


class _EndlessYdl(FakeYdl):
    """A download that runs until a progress hook stops it; `running` is set while it runs."""

    running = threading.Event()

    def download(self, urls: list[str]) -> int:
        self.running.set()
        try:
            for _ in range(300):
                for hook in self.options.get("progress_hooks", []):
                    hook({"status": "downloading"})
                time.sleep(0.01)
        finally:
            self.running.clear()
        return 0


@pytest.mark.asyncio
async def test_a_timed_out_download_is_stopped_before_it_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(youtube_service, "DOWNLOAD_TIMEOUT_SECONDS", 0.05)
    client = YtDlpClient(lambda options: _EndlessYdl(options, None))
    with pytest.raises(MediaMaterializationError):
        await client.download(URL, CHOICE, tmp_path)
    # Nothing still writes into the work directory the caller is about to remove.
    assert not _EndlessYdl.running.is_set()
    gc.collect()
    assert [r for r in caplog.records if r.name == "asyncio"] == []


@pytest.mark.asyncio
async def test_a_cancelled_download_is_stopped_before_the_cancellation_returns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    client = YtDlpClient(lambda options: _EndlessYdl(options, None))
    task = asyncio.create_task(client.download(URL, CHOICE, tmp_path))
    while not _EndlessYdl.running.is_set() and not task.done():
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not _EndlessYdl.running.is_set()
    gc.collect()
    assert [r for r in caplog.records if r.name == "asyncio"] == []


def test_extract_and_download_fit_inside_the_activity_budget() -> None:
    # `inspect_source_candidates` runs under a 5-minute start-to-close timeout; the cards and
    # the adoption need what is left, so yt-dlp's own timeouts must fire first.
    budget = youtube_service.EXTRACT_TIMEOUT_SECONDS + youtube_service.DOWNLOAD_TIMEOUT_SECONDS
    assert budget <= 240


def test_a_sign_in_demand_with_cookies_is_a_login_wall() -> None:
    error = RuntimeError("ERROR: Sign in to confirm you're not a bot")
    assert classify(error) is AcquisitionReason.REQUEST_BLOCKED
    assert classify(error, signed_in=True) is AcquisitionReason.LOGIN_WALL
    assert classify(RuntimeError("Video unavailable"), signed_in=True) is (
        AcquisitionReason.REQUEST_INCOMPLETE
    )


@pytest.mark.asyncio
async def test_a_signed_in_client_reports_a_login_wall() -> None:
    client = YtDlpClient(
        lambda options: FakeYdl(options, RuntimeError("Sign in to confirm your age")),
        signed_in=True,
    )
    with pytest.raises(YtDlpError) as caught:
        await client.extract(URL, comments=True)
    assert caught.value.reason is AcquisitionReason.LOGIN_WALL

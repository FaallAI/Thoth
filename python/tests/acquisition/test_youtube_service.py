"""The yt-dlp client and the YouTube card browser over injected fakes; no network."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import pytest

from tests.acquisition.fakes import FakeCardPage, card_session
from thoth_control_plane.acquisition import youtube_service
from thoth_control_plane.acquisition.adapters.youtube import FormatChoice
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
    assert options["extractor_args"] == {"youtube": {"max_comments": ["50", "50", "0", "0"]}}
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

"""YouTube acquisition over injected fakes: no network, no yt-dlp, no Scrapling."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import pytest

from tests.acquisition.fakes import FakeMaterializer
from tests.acquisition.png_fixtures import make_png
from thoth_control_plane.acquisition.card_browser import Cards
from thoth_control_plane.acquisition.materializer import MediaMaterializationError
from thoth_control_plane.acquisition.models import AcquisitionReason, AcquisitionStrategy
from thoth_control_plane.acquisition.youtube_service import YouTubeAcquirer, YtDlpError

VIDEO_ID = "abcDEF123_-"
URL = f"https://youtu.be/{VIDEO_ID}?si=share"
CANONICAL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
CHANNEL = "https://www.youtube.com/channel/UCuser001abcdefghijklmno"
WF = "wf_youtube_001"
C1, C2 = "UgzComment001", "UgzComment002"
MB = 1024 * 1024


def _info(**extra: Any) -> dict[str, Any]:
    return {
        "id": VIDEO_ID,
        "title": "secret title",
        "description": "secret description",
        "uploader_id": "@user_001",
        "channel_id": "UCuser001abcdefghijklmno",
        "timestamp": 1_714_566_896,
        "view_count": 4_500,
        "like_count": 120,
        "comment_count": 34,
        "duration": 600,
        "live_status": "not_live",
        "comments": [
            {"id": C1, "parent": "root", "author": "@fan_001", "text": "first", "like_count": 3},
            {"id": C2, "parent": "root", "author": "@fan_002", "text": "second", "like_count": 1},
        ],
        "formats": [
            {
                "format_id": "137",
                "protocol": "https",
                "url": "https://media.example.test/137",
                "ext": "mp4",
                "vcodec": "avc1",
                "acodec": "none",
                "width": 1920,
                "height": 1080,
                "filesize": 100 * MB,
            },
            {
                "format_id": "140",
                "protocol": "https",
                "url": "https://media.example.test/140",
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "mp4a",
                "filesize": 10 * MB,
            },
        ],
        **extra,
    }


class FakeClient:
    def __init__(
        self,
        info: Any = None,
        error: AcquisitionReason | None = None,
        download_error: bool = False,
    ) -> None:
        self.info = _info() if info is None else info
        self.error, self.download_error = error, download_error
        self.calls: list[tuple[str, Any]] = []

    async def extract(self, url: str, *, comments: bool) -> dict[str, Any]:
        self.calls.append(("extract", (url, comments)))
        if self.error is not None:
            raise YtDlpError(self.error)
        return self.info

    async def download(self, url: str, choice, directory: Path) -> Path:
        self.calls.append(("download", (url, choice.video_format, choice.audio_format)))
        (directory / "merged.f137.mp4").write_bytes(b"part")
        if self.download_error:
            raise MediaMaterializationError()
        merged = directory / "merged.mp4"
        merged.write_bytes(b"x")
        return merged


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


def _cards() -> Cards:
    return Cards(comment_pngs={C1: make_png(400, 80)}, profile_png=make_png(400, 200))


async def _inspect(tmp_path: Path, client, headless, materializer=None, url: str = URL):
    acquirer = YouTubeAcquirer(client, headless, materializer or FakeMaterializer())
    return await acquirer.inspect(workflow_id=WF, source_url=url, artifact_root=tmp_path)


def _work_dirs(tmp_path: Path) -> list[Path]:
    media = tmp_path / "reports" / WF / "media"
    return [p for p in media.iterdir() if p.name.endswith(".download")] if media.exists() else []


@pytest.mark.asyncio
async def test_a_video_report_carries_the_merged_mp4_comments_and_cards(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    client, headless = FakeClient(), FakeHeadless(_cards())
    result = await _inspect(tmp_path, client, headless)

    report = result.report
    assert report is not None
    assert (report.source.platform, str(report.source.canonical_url)) == ("youtube", CANONICAL)
    assert report.post.owner_handle == "user_001"
    assert report.post.engagement == {"play": 4_500, "like": 120, "comment": 34}
    assert [(m.kind, m.media_type) for m in report.media] == [("video", "video/mp4")]
    assert str(report.media[0].location).endswith(f"media/youtube-{VIDEO_ID}-1.mp4")
    assert report.media[0].acquisition_strategy is AcquisitionStrategy.YT_DLP
    assert report.media[0].duration_seconds == 600.0
    assert [c.comment_id for c in report.comments] == [C1, C2]
    assert str(report.comments[0].card.location).endswith(f"cards/comment-{C1}.png")
    assert report.comments[1].card is None
    assert report.post_card is None
    assert report.profile_card is not None
    assert report.outcome.attempts[0].strategy is AcquisitionStrategy.YT_DLP
    assert client.calls == [
        ("extract", (CANONICAL, True)),
        ("download", (CANONICAL, "137", "140")),
    ]
    call = headless.card_calls[0]
    assert (call["post"], call["profile"], call["want_post"]) == (CANONICAL, CHANNEL, False)
    assert [t.comment_id for t in call["targets"]] == [C1, C2]
    assert _work_dirs(tmp_path) == []
    assert headless.closed == 1
    for secret in ("youtube.com", "youtu.be", "secret title", "user_001", "fan_001"):
        assert secret not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    [
        AcquisitionReason.REQUEST_BLOCKED,
        AcquisitionReason.REQUEST_TIMEOUT,
        AcquisitionReason.REQUEST_INCOMPLETE,
    ],
)
async def test_extract_failures_are_retryable_and_skip_the_rest(
    tmp_path: Path, reason: AcquisitionReason
) -> None:
    client, headless = FakeClient(error=reason), FakeHeadless()
    result = await _inspect(tmp_path, client, headless)
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == (reason.value, True)
    assert len(result.failure.attempts) == 1
    assert [name for name, _ in client.calls] == ["extract"]
    assert headless.card_calls == []
    assert headless.closed == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "info",
    [
        _info(id="otherVideo1"),
        _info(live_status="is_live"),
        _info(live_status="is_upcoming"),
        _info(uploader_id="bad handle", channel_id=None),
    ],
)
async def test_another_video_a_live_stream_or_no_owner_is_request_incomplete(
    tmp_path: Path, info: dict[str, Any]
) -> None:
    client = FakeClient(info=info)
    result = await _inspect(tmp_path, client, FakeHeadless())
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("request_incomplete", True)
    assert [name for name, _ in client.calls] == ["extract"]


@pytest.mark.asyncio
async def test_no_fitting_format_is_a_media_failure_without_a_download(tmp_path: Path) -> None:
    client, headless = FakeClient(info=_info(formats=[])), FakeHeadless()
    result = await _inspect(tmp_path, client, headless)
    assert result.failure is not None
    assert result.failure.code == "media_validation_failed"
    assert [name for name, _ in client.calls] == ["extract"]
    assert headless.card_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("client", "materializer"),
    [
        (FakeClient(download_error=True), FakeMaterializer()),
        (FakeClient(), FakeMaterializer(fail_adopt=True)),
    ],
)
async def test_a_failed_download_or_adopt_leaves_nothing_behind(
    tmp_path: Path, client: FakeClient, materializer: FakeMaterializer
) -> None:
    headless = FakeHeadless()
    result = await _inspect(tmp_path, client, headless, materializer)
    assert result.failure is not None
    assert result.failure.code == "media_validation_failed"
    assert _work_dirs(tmp_path) == []
    media = tmp_path / "reports" / WF / "media"
    assert not media.exists() or list(media.iterdir()) == []
    assert headless.card_calls == []


@pytest.mark.asyncio
async def test_an_invalid_url_fails_before_any_extraction(tmp_path: Path) -> None:
    client = FakeClient()
    result = await _inspect(
        tmp_path, client, FakeHeadless(), url="https://www.youtube.com/@someone"
    )
    assert result.failure is not None
    assert (result.failure.code, result.failure.retryable) == ("invalid_source_url", False)
    assert client.calls == []


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
    task = asyncio.create_task(_inspect(tmp_path, FakeClient(), headless))
    await headless.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert headless.closed == 1


class _RecordingClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.directories: list[Path] = []

    async def download(self, url: str, choice, directory: Path) -> Path:
        self.directories.append(directory)
        return await super().download(url, choice, directory)


@pytest.mark.asyncio
async def test_each_attempt_downloads_into_its_own_work_directory(tmp_path: Path) -> None:
    # A retry must never share a directory with an earlier attempt's leftover download.
    client = _RecordingClient()
    for _ in range(2):
        await _inspect(tmp_path, client, FakeHeadless())
    first, second = client.directories
    assert first != second and first.parent == second.parent
    assert _work_dirs(tmp_path) == []

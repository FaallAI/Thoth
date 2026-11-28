from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.acquisition.adapters.tikwm import TikWmError
from thoth_control_plane.acquisition.youtube_service import _Silent
from thoth_control_plane.attribution.ports import AttributionError, Frame
from thoth_control_plane.footage.adapters import downloader as downloader_module
from thoth_control_plane.footage.adapters.downloader import ClipError, YtDlpClipDownloader
from thoth_control_plane.footage.adapters.vision import (
    FOOTAGE_PROMPT,
    AgnoFootageJudge,
    FootageAnswer,
)


def test_the_prompt_names_the_visual_and_the_stage4_classes() -> None:
    assert "{visual}" in FOOTAGE_PROMPT
    assert "commentary" in FOOTAGE_PROMPT and "reaction" in FOOTAGE_PROMPT


async def test_the_judge_asks_with_the_visual(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_run(self: Any, schema: Any, prompt: str, frames: Any) -> FootageAnswer:
        seen.update(schema=schema, prompt=prompt, frames=len(frames))
        return FootageAnswer(kind="footage", shows_object="yes", description="A flooded street.")

    monkeypatch.setattr(AgnoFootageJudge, "_run", fake_run)
    frames = [Frame(second=float(n), jpeg=b"x") for n in range(5)]
    answer = await AgnoFootageJudge("k", "m").judge(frames, "a flooded street")
    assert answer.kind == "footage"
    assert seen["schema"] is FootageAnswer and seen["frames"] == 3
    assert "a flooded street" in seen["prompt"]


async def test_a_failed_download_is_a_clip_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(url: str, options: dict[str, Any]) -> None:
        raise RuntimeError("network")

    monkeypatch.setattr(downloader_module, "_run_yt_dlp", boom)
    with pytest.raises(ClipError):
        await YtDlpClipDownloader("ffmpeg").download(
            "https://www.tiktok.com/@a/video/7400000000000000001", (4.0, 24.0), tmp_path / "c.mp4"
        )
    assert list(tmp_path.iterdir()) == []


async def test_a_window_reaches_yt_dlp_and_the_file_lands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake(url: str, options: dict[str, Any]) -> None:
        seen.update(options)
        Path(options["outtmpl"].replace("%(ext)s", "mp4")).write_bytes(b"\x00" * 64)

    monkeypatch.setattr(downloader_module, "_run_yt_dlp", fake)
    target = tmp_path / "c.mp4"
    assert (
        await YtDlpClipDownloader("ffmpeg").download("https://youtu.be/x", (4.0, 24.0), target)
        == target
    )
    assert target.read_bytes() == b"\x00" * 64
    assert seen["proxy"] == "" and seen["noprogress"] is True
    assert isinstance(seen["logger"], _Silent)
    assert seen["force_keyframes_at_cuts"] is True and "download_ranges" in seen
    assert not any(p.name.endswith(".part") for p in tmp_path.iterdir())

    seen.clear()
    await YtDlpClipDownloader("ffmpeg").download("https://youtu.be/y", None, tmp_path / "d.mp4")
    assert "download_ranges" not in seen


async def test_a_judge_failure_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing(self: Any, schema: Any, prompt: str, frames: Any) -> FootageAnswer:
        raise AttributionError("vision_unavailable")

    monkeypatch.setattr(AgnoFootageJudge, "_run", failing)
    with pytest.raises(AttributionError) as raised:
        await AgnoFootageJudge("k", "m").judge([Frame(second=1.0, jpeg=b"x")], "a street")
    assert raised.value.code == "vision_unavailable"


async def test_a_timed_out_download_stops_before_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = {"stopped": False}

    def fake(url: str, options: dict[str, Any]) -> None:
        scratch = Path(options["outtmpl"]).parent
        try:
            while True:
                (scratch / "clip.f137.mp4").write_bytes(b"\x00")
                for hook in options["progress_hooks"]:
                    hook({})
                time.sleep(0.01)
        except BaseException:
            state["stopped"] = True
            raise

    monkeypatch.setattr(downloader_module, "_run_yt_dlp", fake)
    with pytest.raises(ClipError):
        await YtDlpClipDownloader("ffmpeg", timeout=0.05).download(
            "https://youtu.be/x", (4.0, 24.0), tmp_path / "c.mp4"
        )
    assert state["stopped"] is True
    assert list(tmp_path.iterdir()) == []


async def test_only_the_merged_clip_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(url: str, options: dict[str, Any]) -> None:
        Path(options["outtmpl"].replace("%(ext)s", "f137.mp4")).write_bytes(b"\x00" * 64)

    monkeypatch.setattr(downloader_module, "_run_yt_dlp", fake)
    with pytest.raises(ClipError):
        await YtDlpClipDownloader("ffmpeg").download("https://youtu.be/x", None, tmp_path / "c.mp4")
    assert list(tmp_path.iterdir()) == []


async def test_a_download_that_ignores_the_stop_is_abandoned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()

    def stuck(url: str, options: dict[str, Any]) -> None:
        release.wait(30)

    monkeypatch.setattr(downloader_module, "_run_yt_dlp", stuck)
    monkeypatch.setattr(downloader_module, "STOP_GRACE_SECONDS", 0.05)
    try:
        with pytest.raises(ClipError):
            await asyncio.wait_for(
                YtDlpClipDownloader("ffmpeg", timeout=0.05).download(
                    "https://youtu.be/x", None, tmp_path / "c.mp4"
                ),
                5,
            )
    finally:
        release.set()


async def test_the_person_prompt_adds_the_exception_only_for_a_person(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []

    async def fake_run(self: Any, schema: Any, prompt: str, frames: Any) -> FootageAnswer:
        prompts.append(prompt)
        return FootageAnswer(kind="footage", shows_object="yes", description="")

    monkeypatch.setattr(AgnoFootageJudge, "_run", fake_run)
    frames = [Frame(second=1.0, jpeg=b"x")]
    judge = AgnoFootageJudge("k", "m")
    await judge.judge(frames, "a speaker")
    await judge.judge(frames, "a speaker", person=True)
    assert prompts[0] == FOOTAGE_PROMPT.format(visual="a speaker")
    assert "talking to the camera" in prompts[0] and "commentary" in prompts[0]
    assert prompts[1] != prompts[0] and "a speaker" in prompts[1]
    assert "themself" in prompts[1]
    assert "talking to the camera" not in prompts[1]  # the person rule replaces that sentence


def test_the_kind_field_description_does_not_define_commentary() -> None:
    description = FootageAnswer.model_json_schema()["properties"]["kind"]["description"]
    assert "talking" not in description and "head" not in description


async def test_a_tiktok_url_is_resolved_and_the_direct_url_downloaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}
    asked: list[str] = []

    def fake(url: str, options: dict[str, Any]) -> None:
        seen.update(options, url=url)
        Path(options["outtmpl"].replace("%(ext)s", "mp4")).write_bytes(b"\x00" * 64)

    async def resolve(url: str) -> str:
        asked.append(url)
        return "https://cdn.example/direct.mp4"

    monkeypatch.setattr(downloader_module, "_run_yt_dlp", fake)
    page = "https://www.tiktok.com/@a/video/7400000000000000001"
    await YtDlpClipDownloader("ffmpeg", resolve_tiktok=resolve).download(
        page, (4.0, 24.0), tmp_path / "c.mp4"
    )
    assert asked == [page] and seen["url"] == "https://cdn.example/direct.mp4"
    assert "download_ranges" in seen and seen["proxy"] == ""


async def test_a_failing_tiktok_resolver_is_a_clip_error(tmp_path: Path) -> None:
    async def resolve(url: str) -> str:
        raise RuntimeError("cdn_unavailable")

    with pytest.raises(ClipError):
        await YtDlpClipDownloader("ffmpeg", resolve_tiktok=resolve).download(
            "https://vm.tiktok.com/abc/", None, tmp_path / "c.mp4"
        )
    assert list(tmp_path.iterdir()) == []


async def test_a_youtube_url_skips_the_tiktok_resolver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake(url: str, options: dict[str, Any]) -> None:
        seen["url"] = url
        Path(options["outtmpl"].replace("%(ext)s", "mp4")).write_bytes(b"\x00" * 8)

    async def resolve(url: str) -> str:
        raise AssertionError("not for youtube")

    monkeypatch.setattr(downloader_module, "_run_yt_dlp", fake)
    await YtDlpClipDownloader("ffmpeg", resolve_tiktok=resolve).download(
        "https://youtu.be/x", None, tmp_path / "c.mp4"
    )
    assert seen["url"] == "https://youtu.be/x"


async def test_the_scene_question_is_asked_only_with_a_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # spec 10.5 and 10.12
    seen: list[tuple[str, list[Frame]]] = []

    async def fake_run(self: Any, schema: Any, prompt: str, frames: Any) -> FootageAnswer:
        seen.append((prompt, list(frames)))
        return FootageAnswer(kind="footage", shows_object="yes", same_event="yes")

    monkeypatch.setattr(AgnoFootageJudge, "_run", fake_run)
    frames = [Frame(second=float(n), jpeg=b"x") for n in range(5)]
    main = Frame(second=0.0, jpeg=b"main")
    judge = AgnoFootageJudge("k", "m")
    await judge.judge(frames, "a street")
    answer = await judge.judge(frames, "a street", reference=main)
    assert "same_event" not in seen[0][0] and len(seen[0][1]) == 3
    assert "same_event" in seen[1][0] and "first image" in seen[1][0]
    assert seen[1][1][0] is main and len(seen[1][1]) == 4
    assert answer.same_event == "yes"
    assert FootageAnswer(kind="footage", shows_object="no").same_event is None  # not asked


@pytest.mark.parametrize(
    ("message", "cause"),
    [
        ("ERROR: [youtube] x: Sign in to confirm you're not a bot. Use --cookies", "bot_check"),
        ("ERROR: unable to download video data: HTTP Error 403: Forbidden", "http_403"),
        ("ERROR: HTTP Error 429: Too Many Requests", "http_429"),
        ("ERROR: something else https://www.youtube.com/watch?v=x", "DownloadError"),
    ],
)
async def test_a_download_error_names_its_cause_without_the_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, message: str, cause: str
) -> None:  # spec 10.8 and 10.12: a YouTube bot check shows in the causes
    from yt_dlp.utils import DownloadError

    def boom(url: str, options: dict[str, Any]) -> None:
        raise DownloadError(message)

    monkeypatch.setattr(downloader_module, "_run_yt_dlp", boom)
    with pytest.raises(ClipError) as raised:
        await YtDlpClipDownloader("ffmpeg").download(
            "https://www.youtube.com/watch?v=x", (4.0, 24.0), tmp_path / "c.mp4"
        )
    assert str(raised.value) == cause


async def test_an_answer_without_the_asked_scene_is_unusable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # final review, minor 12: a missing answer never passes as "no"
    from thoth_control_plane.attribution.ports import AttributionError

    async def fake_run(self: Any, schema: Any, prompt: str, frames: Any) -> FootageAnswer:
        return FootageAnswer(kind="footage", shows_object="yes")

    monkeypatch.setattr(AgnoFootageJudge, "_run", fake_run)
    frames = [Frame(second=1.0, jpeg=b"x")]
    judge = AgnoFootageJudge("k", "m")
    assert (await judge.judge(frames, "a street")).same_event is None
    with pytest.raises(AttributionError, match="vision_unavailable"):
        await judge.judge(frames, "a street", reference=Frame(second=0.0, jpeg=b"m"))


# Footage sourcing v2 (spec 2026-11-27, 3.2 and 5.1): bun for YouTube's JS, TikWm codes kept,
# and one leased retry only after the direct download fails.

TIKTOK = "https://www.tiktok.com/@podmuses/video/7400000000000000001"


def _writes(url: str, options: dict[str, Any]) -> None:
    Path(options["outtmpl"].replace("%(ext)s", "mp4")).write_bytes(b"\x00" * 64)


class Session:
    """A fake leased session: yields its options and records how the attempt ended."""

    def __init__(self, extra: dict[str, Any] | None = None, *, lease: bool = True) -> None:
        self.extra = extra or {"proxy": "http://leased", "cookiefile": "c.txt"}
        self.lease = lease
        self.calls: list[tuple[str, Path]] = []
        self.ended: list[str] = []

    def __call__(self, platform: str, scratch: Path) -> Any:
        @asynccontextmanager
        async def session() -> Any:
            self.calls.append((platform, scratch))
            try:
                yield self.extra if self.lease else None
                self.ended.append("ok")
            except ClipError as error:
                self.ended.append(str(error))
                raise

        return session()


async def test_direct_downloads_solve_youtube_js_with_bun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake(url: str, options: dict[str, Any]) -> None:
        seen.update(options)
        _writes(url, options)

    monkeypatch.setattr(downloader_module, "_run_yt_dlp", fake)
    await YtDlpClipDownloader("ffmpeg", fallback_session=Session()).download(
        "https://www.youtube.com/watch?v=x", (4.0, 12.0), tmp_path / "c.mp4"
    )
    assert seen["js_runtimes"] == {"bun": {}}
    assert seen["proxy"] == ""


@pytest.mark.parametrize("code", ["cdn_rate_limited", "cdn_unavailable"])
async def test_a_tikwm_failure_keeps_its_code(tmp_path: Path, code: str) -> None:
    async def resolve(url: str) -> str:
        raise TikWmError(code)  # type: ignore[arg-type]

    with pytest.raises(ClipError) as raised:
        await YtDlpClipDownloader("ffmpeg", resolve_tiktok=resolve).download(
            TIKTOK, None, tmp_path / "c.mp4"
        )
    assert str(raised.value) == f"tikwm_{code}"
    assert "tiktok.com" not in str(raised.value)


async def test_a_failed_tikwm_falls_back_to_a_leased_download_of_the_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def resolve(url: str) -> str:
        raise TikWmError("cdn_rate_limited")

    runs: list[tuple[str, dict[str, Any]]] = []

    def fake(url: str, options: dict[str, Any]) -> None:
        runs.append((url, options))
        _writes(url, options)

    monkeypatch.setattr(downloader_module, "_run_yt_dlp", fake)
    session = Session()
    target = tmp_path / "c.mp4"
    downloader = YtDlpClipDownloader("ffmpeg", resolve_tiktok=resolve, fallback_session=session)
    assert await downloader.download(TIKTOK, None, target) == target
    ((url, options),) = runs
    assert url == TIKTOK
    assert options["proxy"] == "http://leased" and options["cookiefile"] == "c.txt"
    assert options["js_runtimes"] == {"bun": {}}
    ((platform, scratch),) = session.calls
    assert platform == "tiktok" and Path(options["outtmpl"]).parent == scratch
    assert session.ended == ["ok"]


async def test_a_failed_cdn_download_falls_back_in_its_own_scratch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def resolve(url: str) -> str:
        return "https://cdn.example/v.mp4"

    runs: list[tuple[str, dict[str, Any]]] = []

    def fake(url: str, options: dict[str, Any]) -> None:
        runs.append((url, dict(options)))
        if options["proxy"] == "":
            raise RuntimeError("connection reset")
        _writes(url, options)

    monkeypatch.setattr(downloader_module, "_run_yt_dlp", fake)
    session = Session()
    downloader = YtDlpClipDownloader("ffmpeg", resolve_tiktok=resolve, fallback_session=session)
    await downloader.download(TIKTOK, (2.0, 10.0), tmp_path / "c.mp4")
    (direct_url, direct), (fallback_url, fallback) = runs
    assert direct_url == "https://cdn.example/v.mp4" and fallback_url == TIKTOK
    assert Path(direct["outtmpl"]).parent != Path(fallback["outtmpl"]).parent
    assert "download_ranges" in fallback


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=abc",
        "https://youtu.be/abc",
        "https://m.youtube.com/watch?v=abc",
    ],
)
@pytest.mark.parametrize(
    "message",
    ["Sign in to confirm you are not a bot", "HTTP Error 403: Forbidden", "HTTP Error 429"],
)
async def test_a_blocked_youtube_download_retries_leased(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, url: str, message: str
) -> None:
    def fake(link: str, options: dict[str, Any]) -> None:
        if options["proxy"] == "":
            raise RuntimeError(message)
        _writes(link, options)

    monkeypatch.setattr(downloader_module, "_run_yt_dlp", fake)
    session = Session()
    await YtDlpClipDownloader("ffmpeg", fallback_session=session).download(
        url, (40.0, 48.0), tmp_path / "c.mp4"
    )
    assert [platform for platform, _ in session.calls] == ["youtube"]


@pytest.mark.parametrize("failure", ["network", "nothing"])
async def test_other_youtube_failures_do_not_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    def fake(url: str, options: dict[str, Any]) -> None:
        if failure == "network":
            raise RuntimeError("connection reset")

    monkeypatch.setattr(downloader_module, "_run_yt_dlp", fake)
    session = Session()
    with pytest.raises(ClipError) as raised:
        await YtDlpClipDownloader("ffmpeg", fallback_session=session).download(
            "https://youtu.be/abc", None, tmp_path / "c.mp4"
        )
    assert str(raised.value) == ("RuntimeError" if failure == "network" else "no file")
    assert session.calls == []


async def test_a_failed_leased_retry_reports_its_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake(url: str, options: dict[str, Any]) -> None:
        raise RuntimeError("HTTP Error 429: Too Many Requests")

    monkeypatch.setattr(downloader_module, "_run_yt_dlp", fake)
    session = Session()
    with pytest.raises(ClipError) as raised:
        await YtDlpClipDownloader("ffmpeg", fallback_session=session).download(
            "https://youtu.be/abc", None, tmp_path / "c.mp4"
        )
    assert str(raised.value) == "http_429"
    assert session.ended == ["http_429"]


async def test_no_lease_keeps_the_direct_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake(url: str, options: dict[str, Any]) -> None:
        raise RuntimeError("HTTP Error 403: Forbidden")

    monkeypatch.setattr(downloader_module, "_run_yt_dlp", fake)
    session = Session(lease=False)
    with pytest.raises(ClipError) as raised:
        await YtDlpClipDownloader("ffmpeg", fallback_session=session).download(
            "https://youtu.be/abc", None, tmp_path / "c.mp4"
        )
    assert str(raised.value) == "http_403"
    assert len(session.calls) == 1


async def test_a_leased_retry_is_logged_without_the_url(  # final review
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fake(url: str, options: dict[str, Any]) -> None:
        if options["proxy"] == "":
            raise RuntimeError("HTTP Error 403: Forbidden")
        _writes(url, options)

    monkeypatch.setattr(downloader_module, "_run_yt_dlp", fake)
    with caplog.at_level(logging.INFO, logger=downloader_module.__name__):
        await YtDlpClipDownloader("ffmpeg", fallback_session=Session()).download(
            "https://youtu.be/abc", None, tmp_path / "c.mp4"
        )
    assert "footage download fallback platform=youtube cause=http_403" in caplog.text
    assert "youtu.be" not in caplog.text


def _hangs_when_direct(url: str, options: dict[str, Any]) -> None:
    if options["proxy"] != "":
        _writes(url, options)
        return
    while True:  # a direct download that only ends when the downloader stops it
        for hook in options["progress_hooks"]:
            hook({})
        time.sleep(0.01)


async def test_the_direct_attempt_leaves_time_for_the_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(downloader_module, "_run_yt_dlp", _hangs_when_direct)
    monkeypatch.setattr(downloader_module, "DIRECT_FALLBACK_CAP_SECONDS", 0.1)
    monkeypatch.setattr(downloader_module, "MIN_FALLBACK_SECONDS", 1.0)
    monkeypatch.setattr(downloader_module, "BLOCKED_CAUSES", frozenset({"TimeoutError"}))
    session = Session()
    target = tmp_path / "c.mp4"
    started = time.monotonic()
    await asyncio.wait_for(
        YtDlpClipDownloader("ffmpeg", timeout=30.0, fallback_session=session).download(
            "https://youtu.be/abc", None, target
        ),
        10,
    )
    assert time.monotonic() - started < 5
    assert target.is_file() and session.ended == ["ok"]


async def test_too_little_time_left_skips_the_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(downloader_module, "_run_yt_dlp", _hangs_when_direct)
    monkeypatch.setattr(downloader_module, "BLOCKED_CAUSES", frozenset({"TimeoutError"}))
    session = Session()
    with pytest.raises(ClipError) as raised:
        await YtDlpClipDownloader("ffmpeg", timeout=0.2, fallback_session=session).download(
            "https://youtu.be/abc", None, tmp_path / "c.mp4"
        )
    assert str(raised.value) == "TimeoutError"
    assert session.calls == []


class Leases:
    def __init__(self, mode: str = "fallback", lease: object | None = None) -> None:
        self._mode = mode
        self._lease = lease
        self.leased: list[str] = []
        self.released: list[tuple[object, str | None]] = []

    async def mode(self, platform: str) -> str:
        return self._mode

    async def lease(self, platform: str) -> object | None:
        self.leased.append(platform)
        return self._lease

    async def release(self, lease: object, outcome: str | None) -> None:
        self.released.append((lease, outcome))


class Access:
    def yt_dlp_options(self, directory: Path) -> dict[str, Any]:
        return {"proxy": "http://leased", "cookiefile": str(directory / "cookies.txt")}


class Lease:
    access = Access()


async def test_the_production_session_honors_an_anonymous_policy(tmp_path: Path) -> None:
    leases = Leases(mode="anonymous", lease=Lease())
    async with _download_fallback_session(leases)("tiktok", tmp_path) as extra:
        assert extra is None
    assert leases.leased == [] and leases.released == []


async def test_the_production_session_without_an_account_yields_nothing(tmp_path: Path) -> None:
    leases = Leases(lease=None)
    async with _download_fallback_session(leases)("youtube", tmp_path) as extra:
        assert extra is None
    assert leases.leased == ["youtube"] and leases.released == []


@pytest.mark.parametrize(
    ("raised", "outcome"),
    [
        (None, "success"),
        (ClipError("http_429"), "rate_limited"),
        (ClipError("bot_check"), "blocked"),
        (ClipError("http_403"), "blocked"),
        (ClipError("TimeoutError"), None),
        (ClipError("no file"), None),
        (asyncio.CancelledError(), None),
    ],
)
async def test_the_production_session_reports_the_outcome(
    tmp_path: Path, raised: BaseException | None, outcome: str | None
) -> None:
    lease = Lease()
    leases = Leases(lease=lease)
    session = _download_fallback_session(leases)("youtube", tmp_path)
    if raised is None:
        async with session as extra:
            assert extra == {"proxy": "http://leased", "cookiefile": str(tmp_path / "cookies.txt")}
    else:
        with pytest.raises(type(raised)):
            async with session:
                raise raised
    assert leases.released == [(lease, outcome)]


def _download_fallback_session(leases: Leases) -> Any:
    from thoth_control_plane.activities.footage import _download_fallback_session as build

    return build(leases)  # type: ignore[arg-type]

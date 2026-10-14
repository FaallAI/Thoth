from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any

import pytest

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

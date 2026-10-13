"""ffmpeg frames at a second, ffprobe durations, and RapidOCR box geometry."""

from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

import pytest

from thoth_control_plane.attribution.ports import Frame

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def _require_module(name: str) -> None:
    # Operator, 2026-10-11/13: a required tool missing is a failure, never a skip.
    import importlib.util

    if importlib.util.find_spec(name) is None:
        pytest.fail(f"{name} is required for this test and is not installed")


def _require(binary: str | None, name: str) -> str:
    # Operator, 2026-10-11: a missing ffmpeg is an error, never a skip.
    if binary is None:
        pytest.fail(f"{name} is required for this test and is not installed")
    return binary


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            _require(FFMPEG, "ffmpeg"),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=4:size=1080x1920:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    return video


@pytest.mark.asyncio
async def test_frame_at_returns_one_jpeg_at_the_requested_width(clip: Path) -> None:
    from PIL import Image

    from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource

    frame = await FfmpegFrameSource(_require(FFMPEG, "ffmpeg")).frame_at(clip, 2.0, width=720)

    assert frame.second == 2.0
    with Image.open(io.BytesIO(frame.jpeg)) as image:
        assert image.size == (720, 1280)


@pytest.mark.asyncio
async def test_frame_at_past_the_end_raises_frame_error(clip: Path) -> None:
    from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource, FrameError

    with pytest.raises(FrameError):
        await FfmpegFrameSource(_require(FFMPEG, "ffmpeg")).frame_at(clip, 99.0, width=720)


@pytest.mark.asyncio
async def test_frame_at_without_ffmpeg_raises_tool_missing(clip: Path) -> None:
    from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource, ToolMissing

    with pytest.raises(ToolMissing) as raised:
        await FfmpegFrameSource("/nonexistent/ffmpeg").frame_at(clip, 1.0, width=720)
    assert raised.value.code == "ffmpeg_missing"


@pytest.mark.asyncio
async def test_ffprobe_reads_the_duration(clip: Path) -> None:
    from thoth_control_plane.attribution.adapters.frames import FfprobeDuration

    duration = await FfprobeDuration(_require(FFPROBE, "ffprobe")).duration(clip)

    assert duration == pytest.approx(4.0, abs=0.05)


@pytest.mark.asyncio
async def test_ffprobe_failures_are_told_apart(tmp_path: Path) -> None:
    from thoth_control_plane.attribution.adapters.frames import (
        DurationError,
        FfprobeDuration,
        ToolMissing,
    )

    with pytest.raises(ToolMissing) as raised:
        await FfprobeDuration("/nonexistent/ffprobe").duration(tmp_path / "x.mp4")
    assert raised.value.code == "ffprobe_missing"
    with pytest.raises(DurationError):
        await FfprobeDuration(_require(FFPROBE, "ffprobe")).duration(tmp_path / "missing.mp4")


@pytest.mark.asyncio
async def test_rapidocr_boxes_carry_left_and_right() -> None:
    _require_module("rapidocr")
    from PIL import Image, ImageDraw, ImageFont

    from thoth_control_plane.attribution.adapters.ocr import RapidOcrReader

    image = Image.new("RGB", (720, 1280), "white")
    ImageDraw.Draw(image).text(
        (400, 600), "KABAR TERKINI", fill="black", font=ImageFont.load_default(size=40)
    )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)

    boxes = await RapidOcrReader(angle=False).read(Frame(0.0, buffer.getvalue()))

    found = [box for box in boxes if "TERKINI" in box.text]
    assert found, [box.text for box in boxes]
    assert 0.5 < found[0].left < found[0].right <= 1.0
    assert 0.4 < found[0].top < found[0].bottom < 0.55

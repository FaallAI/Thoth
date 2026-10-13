"""The local adapters: ffmpeg frames, ORB frame matching, and RapidOCR text."""

from __future__ import annotations

import asyncio
import io
import logging
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from thoth_control_plane.attribution.ports import Frame

FFMPEG = shutil.which("ffmpeg")


def _require_module(name: str) -> None:
    # Operator, 2026-10-11/13: a required tool missing is a failure, never a skip.
    import importlib.util

    if importlib.util.find_spec(name) is None:
        pytest.fail(f"{name} is required for this test and is not installed")


@pytest.fixture
def ffmpeg() -> str:
    # Operator, 2026-10-11: a missing ffmpeg is an error, never a skip.
    if FFMPEG is None:
        pytest.fail("ffmpeg is required for this test and is not installed")
    return FFMPEG


def _jpeg(image: object, quality: int = 90) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)  # type: ignore[attr-defined]
    return buffer.getvalue()


def _scene(seed: int) -> object:
    """A synthetic frame with corners and edges, the detail ORB keys on."""
    from PIL import Image, ImageDraw

    rng = random.Random(seed)
    image = Image.new("RGB", (360, 640), (rng.randrange(60), rng.randrange(60), rng.randrange(60)))
    draw = ImageDraw.Draw(image)
    for _ in range(60):
        x, y = rng.randrange(340), rng.randrange(620)
        w, h = rng.randrange(10, 80), rng.randrange(10, 80)
        colour = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
        if rng.random() < 0.5:
            draw.rectangle((x, y, x + w, y + h), fill=colour)
        else:
            draw.ellipse((x, y, x + w, y + h), outline=colour, width=3)
    return image


def _reaction(original: object, seed: int) -> object:
    """A reaction frame: the original shrunk into the top panel above an unrelated scene."""
    canvas = _scene(seed)
    canvas.paste(original.resize((216, 384)), (72, 20))  # type: ignore[attr-defined]
    return canvas


def test_matcher_finds_nothing_in_flat_frames() -> None:
    _require_module("cv2")
    from PIL import Image

    from thoth_control_plane.attribution.adapters.visual import OrbMatcher

    black = Frame(0.0, _jpeg(Image.new("RGB", (360, 640), "black")))
    matcher = OrbMatcher(step=1)

    async def run() -> object:
        return await matcher.prepare([black, black])

    assert not asyncio.run(run())


def test_matcher_finds_the_original_shrunk_into_a_reaction_panel() -> None:
    _require_module("cv2")
    from thoth_control_plane.attribution.adapters.visual import OrbMatcher

    original = [_scene(seed) for seed in (1, 2, 3)]
    repost = [
        Frame(float(n), _jpeg(_reaction(frame, 100 + n), quality=70))
        for n, frame in enumerate(original)
    ]
    candidate = [Frame(float(n), _jpeg(frame)) for n, frame in enumerate(original)]
    unrelated = [Frame(float(n), _jpeg(_scene(200 + n))) for n in range(3)]
    matcher = OrbMatcher(step=1)

    async def run() -> tuple[list[int], list[int]]:
        prepared = await matcher.prepare(repost)
        found = await matcher.compare(prepared, await matcher.prepare(candidate))
        other = await matcher.compare(prepared, await matcher.prepare(unrelated))
        return found, other

    found, other = asyncio.run(run())
    assert len(found) == 3 and min(found) >= 25, found
    assert max(other) < 25, other


def test_matcher_finds_a_zoomed_repost_over_a_busy_background() -> None:
    # Real frames, 2026-10-11: instagram DeRDs6DCX07 zooms into DeLTY7YtLl4 under a headline
    # band. The crowd and stage lights took every keypoint of a 600-feature budget (0 inliers).
    _require_module("cv2")
    from thoth_control_plane.attribution.adapters.visual import OrbMatcher

    frames = Path(__file__).parents[1] / "fixtures" / "attribution" / "frames"
    repost = [Frame(4.0, (frames / "plank_repost.jpg").read_bytes())]
    original = [Frame(14.0, (frames / "plank_original.jpg").read_bytes())]
    matcher = OrbMatcher(step=1)

    async def run() -> list[int]:
        return await matcher.compare(await matcher.prepare(repost), await matcher.prepare(original))

    found = asyncio.run(run())
    assert found and found[0] >= 40, found


@pytest.mark.asyncio
async def test_ffmpeg_samples_frames_by_second(tmp_path: Path, ffmpeg: str) -> None:
    from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource

    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=3:size=320x240:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    source = FfmpegFrameSource(ffmpeg)

    frames = await source.frames(video, fps=1.0)
    assert [frame.second for frame in frames][:3] == [0.0, 1.0, 2.0]
    assert all(frame.jpeg.startswith(b"\xff\xd8") for frame in frames)
    assert all(frame.second < 2 for frame in await source.frames(video, fps=1.0, seconds=1.0))


@pytest.mark.asyncio
async def test_ffmpeg_failure_raises_a_frame_error(tmp_path: Path, ffmpeg: str) -> None:
    from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource, FrameError

    source = FfmpegFrameSource(ffmpeg)
    with pytest.raises(FrameError):
        await source.frames(tmp_path / "missing.mp4", fps=1.0)


@pytest.mark.asyncio
async def test_rapidocr_reads_a_handle_with_its_vertical_position() -> None:
    _require_module("rapidocr")
    from PIL import Image, ImageDraw, ImageFont

    from thoth_control_plane.attribution.adapters.ocr import RapidOcrReader

    image = Image.new("RGB", (720, 1280), "white")
    ImageDraw.Draw(image).text(
        (60, 1000), "@vincentius.christ76", fill="black", font=ImageFont.load_default(size=56)
    )

    boxes = await RapidOcrReader().read(Frame(0.0, _jpeg(image)))

    found = [box for box in boxes if "christ76" in box.text.replace(" ", "")]
    assert found, [box.text for box in boxes]
    assert 0.7 < found[0].top < found[0].bottom < 0.9
    # RapidOCR logs model loads at INFO and every empty frame at WARNING: worker noise.
    assert logging.getLogger("RapidOCR").level >= logging.ERROR


@pytest.mark.asyncio
async def test_scene_detector_finds_the_cut_between_two_shots(ffmpeg: str, tmp_path: Path) -> None:
    from thoth_control_plane.attribution.adapters.frames import FfmpegSceneDetector

    video = tmp_path / "two.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=s=320x240:d=2:r=25",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x240:d=2:r=25",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )

    cuts = await FfmpegSceneDetector(ffmpeg).cuts(video)

    assert len(cuts) == 1 and 1.9 <= cuts[0] <= 2.1, cuts


@pytest.mark.asyncio
async def test_scene_detector_without_ffmpeg_is_tool_missing(tmp_path: Path) -> None:
    from thoth_control_plane.attribution.adapters.frames import FfmpegSceneDetector, ToolMissing

    with pytest.raises(ToolMissing) as raised:
        await FfmpegSceneDetector("/nonexistent/ffmpeg").cuts(tmp_path / "x.mp4")
    assert raised.value.code == "ffmpeg_missing"


@pytest.mark.asyncio
async def test_frames_without_ffmpeg_is_tool_missing(tmp_path: Path) -> None:
    from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource, ToolMissing

    with pytest.raises(ToolMissing) as raised:
        await FfmpegFrameSource("/nonexistent/ffmpeg").frames(tmp_path / "x.mp4", fps=1.0)
    assert raised.value.code == "ffmpeg_missing"


@pytest.mark.asyncio
async def test_scene_detection_reads_only_the_opening_span(
    ffmpeg: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Review 2026-10-13: a full-length scan of a long video timed out and failed the workflow.
    from thoth_control_plane.attribution.adapters import frames
    from thoth_control_plane.attribution.adapters.frames import FfmpegSceneDetector

    video = tmp_path / "two.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=s=320x240:d=2:r=25",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x240:d=2:r=25",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    monkeypatch.setattr(frames, "SCENE_SECONDS", 1.5)

    assert await FfmpegSceneDetector(ffmpeg).cuts(video) == []


@pytest.mark.asyncio
async def test_rapidocr_missing_at_run_time_is_tool_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    from PIL import Image

    from thoth_control_plane.attribution.adapters.frames import ToolMissing
    from thoth_control_plane.attribution.adapters.ocr import RapidOcrReader

    monkeypatch.setitem(sys.modules, "rapidocr", None)
    frame = Frame(0.0, _jpeg(Image.new("RGB", (64, 64), "white")))

    with pytest.raises(ToolMissing) as raised:
        await RapidOcrReader().read(frame)
    assert raised.value.code == "rapidocr_missing"


@pytest.mark.asyncio
async def test_opencv_missing_at_run_time_is_tool_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from PIL import Image

    from thoth_control_plane.attribution.adapters.frames import ToolMissing
    from thoth_control_plane.attribution.adapters.visual import OrbMatcher

    monkeypatch.setitem(sys.modules, "cv2", None)
    frame = Frame(0.0, _jpeg(Image.new("RGB", (64, 64), "white")))

    with pytest.raises(ToolMissing) as raised:
        await OrbMatcher().prepare([frame])
    assert raised.value.code == "opencv_missing"

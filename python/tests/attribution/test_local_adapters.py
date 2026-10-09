"""The local adapters: ffmpeg frames, perceptual hashes, and RapidOCR text."""

from __future__ import annotations

import asyncio
import io
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from thoth_control_plane.attribution.ports import Frame

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not installed")


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
    pytest.importorskip("cv2")
    from PIL import Image

    from thoth_control_plane.attribution.adapters.visual import OrbMatcher

    black = Frame(0.0, _jpeg(Image.new("RGB", (360, 640), "black")))
    matcher = OrbMatcher(step=1)

    async def run() -> object:
        return await matcher.prepare([black, black])

    assert not asyncio.run(run())


def test_matcher_finds_the_original_shrunk_into_a_reaction_panel() -> None:
    pytest.importorskip("cv2")
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


@needs_ffmpeg
@pytest.mark.asyncio
async def test_ffmpeg_samples_frames_by_second(tmp_path: Path) -> None:
    from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource

    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            FFMPEG,
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
    source = FfmpegFrameSource(FFMPEG)  # type: ignore[arg-type]

    frames = await source.frames(video, fps=1.0)
    assert [frame.second for frame in frames][:3] == [0.0, 1.0, 2.0]
    assert all(frame.jpeg.startswith(b"\xff\xd8") for frame in frames)
    assert all(frame.second < 2 for frame in await source.frames(video, fps=1.0, seconds=1.0))


@needs_ffmpeg
@pytest.mark.asyncio
async def test_ffmpeg_failure_raises_a_frame_error(tmp_path: Path) -> None:
    from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource, FrameError

    source = FfmpegFrameSource(FFMPEG)  # type: ignore[arg-type]
    with pytest.raises(FrameError):
        await source.frames(tmp_path / "missing.mp4", fps=1.0)


@pytest.mark.asyncio
async def test_rapidocr_reads_a_handle_with_its_vertical_position() -> None:
    pytest.importorskip("rapidocr")
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

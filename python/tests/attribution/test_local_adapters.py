"""The local adapters: ffmpeg frames, perceptual hashes, and RapidOCR text."""

from __future__ import annotations

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


def _noise(seed: int) -> object:
    from PIL import Image

    rng = random.Random(seed)
    small = Image.new("L", (36, 64))
    small.putdata([rng.randrange(256) for _ in range(36 * 64)])
    return small.resize((360, 640)).convert("RGB")


def test_hasher_ignores_flat_frames() -> None:
    pytest.importorskip("imagehash")
    from PIL import Image

    from thoth_control_plane.attribution.adapters.frames import ImageHasher

    black = Frame(0.0, _jpeg(Image.new("RGB", (360, 640), "black")))
    assert ImageHasher().hash(black) is None


def test_hasher_matches_a_reencoded_frame_with_a_new_credit_bar() -> None:
    pytest.importorskip("imagehash")
    from PIL import ImageDraw

    from thoth_control_plane.attribution.adapters.frames import ImageHasher
    from thoth_control_plane.attribution.matching import distance

    original = _noise(1)
    repost = original.copy()  # type: ignore[attr-defined]
    ImageDraw.Draw(repost).rectangle((0, 0, 360, 90), fill="white")
    hasher = ImageHasher()
    first = hasher.hash(Frame(0.0, _jpeg(original)))
    reposted = hasher.hash(Frame(0.0, _jpeg(repost, quality=60)))
    other = hasher.hash(Frame(0.0, _jpeg(_noise(2))))

    assert first is not None and reposted is not None and other is not None
    assert distance(first, reposted) <= 10 < distance(first, other)


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

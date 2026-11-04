"""The headline region tracker (ffmpeg + OpenCV) and the caption judge (vision over OpenRouter)."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
import respx

from thoth_control_plane.assembly.subtitles import OcrBox
from thoth_control_plane.attribution.ports import Frame

FFMPEG = shutil.which("ffmpeg")
# A 720x1280 grey clip; three outlined bars (a headline) leave the top band at 3.2 s.
BARS = ",".join(
    f"drawbox=x=72:y={256 + 40 * n}:w=576:h=28:color=white:t=4:enable='lt(t,3.2)'" for n in range(3)
)
HEADLINE = OcrBox("headline", 0.08, 0.19, 0.92, 0.31)


def _require_module(name: str) -> None:
    # Operator, 2026-10-11/13: a required tool missing is a failure, never a skip.
    import importlib.util

    if importlib.util.find_spec(name) is None:
        pytest.fail(f"{name} is required for this test and is not installed")


def _require_cv2() -> None:
    # OpenCV is required for assembly now: missing it is an error, never a skip.
    try:
        import cv2  # noqa: F401
    except ImportError:
        pytest.fail("OpenCV (cv2) is required for this test and is not installed")


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    # Operator, 2026-10-11: a missing ffmpeg is an error, never a skip.
    if FFMPEG is None:
        pytest.fail("ffmpeg is required for this test and is not installed")
    video = tmp_path / "headline.mp4"
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=gray:s=720x1280:d=6:r=25",
            "-vf",
            BARS,
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    return video


@pytest.mark.asyncio
async def test_tracker_finds_the_frame_the_headline_leaves(clip: Path) -> None:
    _require_cv2()
    from thoth_control_plane.assembly.adapters.region import FfmpegRegionTracker

    gone = await FfmpegRegionTracker(FFMPEG).first_absent(clip, HEADLINE, 1.0, 5.0)  # type: ignore[arg-type]

    assert gone is not None and 3.1 <= gone <= 3.4, gone


@pytest.mark.asyncio
async def test_tracker_answers_none_when_the_headline_stays(clip: Path) -> None:
    _require_cv2()
    from thoth_control_plane.assembly.adapters.region import FfmpegRegionTracker

    assert await FfmpegRegionTracker(FFMPEG).first_absent(clip, HEADLINE, 0.5, 3.0) is None  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_tracker_without_ffmpeg_raises_tool_missing(clip: Path) -> None:
    _require_cv2()
    from thoth_control_plane.assembly.adapters.region import FfmpegRegionTracker
    from thoth_control_plane.attribution.adapters.frames import ToolMissing

    with pytest.raises(ToolMissing) as raised:
        await FfmpegRegionTracker("/nonexistent/ffmpeg").first_absent(clip, HEADLINE, 1.0, 5.0)
    assert raised.value.code == "ffmpeg_missing"


def _completion(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "c1",
            "object": "chat.completion",
            "created": 0,
            "model": "m",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


def _jpeg() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "gray").save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.mark.asyncio
@respx.mock
async def test_judge_answers_yes_no_and_none() -> None:
    _require_module("openai")
    from thoth_control_plane.assembly.adapters.captions import (
        OPENROUTER_BASE_URL,
        AgnoCaptionJudge,
    )

    route = respx.post(f"{OPENROUTER_BASE_URL}/chat/completions")
    judge = AgnoCaptionJudge("synthetic-key", "qwen/qwen3-vl-30b-a3b-instruct")
    frames = [Frame(1.0, _jpeg())]

    route.mock(return_value=_completion(json.dumps({"speech_captions": True})))
    assert await judge.speech_captions(frames) is True
    assert "data:image/jpeg;base64" in route.calls.last.request.content.decode()
    route.mock(return_value=_completion(json.dumps({"speech_captions": False})))
    assert await judge.speech_captions(frames) is False
    route.mock(return_value=httpx.Response(500, json={"error": "down"}))
    assert await judge.speech_captions(frames) is None


# --- One decode pass (operator, 2026-11-03) ---


@pytest.fixture
def moving(tmp_path: Path) -> Path:
    if FFMPEG is None:
        pytest.fail("ffmpeg is required for this test and is not installed")
    video = tmp_path / "moving.mp4"
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=1080x1920:d=4:r=30",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    return video


def _picture(frame: Frame):  # type: ignore[no-untyped-def]
    from PIL import Image

    return Image.open(io.BytesIO(frame.jpeg)).convert("L")


@pytest.mark.asyncio
async def test_a_decode_pass_gives_the_frames_ffmpeg_extracts(moving: Path) -> None:
    _require_module("av")
    from PIL import ImageChops, ImageStat

    from thoth_control_plane.assembly.adapters.decoder import PyAvFrameDecoder
    from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource

    seconds = [0.5, 1.0, 1.0625, 2.75, 3.5]

    decoded = await PyAvFrameDecoder().decode(moving, seconds, width=720)

    alone = FfmpegFrameSource(FFMPEG)  # type: ignore[arg-type]
    for second in seconds:
        frame = await alone.frame_at(moving, second, width=720)
        assert decoded[second].second == second
        difference = ImageChops.difference(_picture(decoded[second]), _picture(frame))
        assert _picture(decoded[second]).size == (720, 1280)
        assert ImageStat.Stat(difference).mean[0] < 3, second


@pytest.mark.asyncio
async def test_a_decode_pass_crops_to_the_band_and_stops_at_the_end(moving: Path) -> None:
    _require_module("av")
    from PIL import ImageChops, ImageStat

    from thoth_control_plane.assembly.adapters.decoder import PyAvFrameDecoder

    decoder = PyAvFrameDecoder()
    decoded = await decoder.decode(moving, [1.0, 9.0], width=720, top=0.8, bottom=0.9)
    whole = await decoder.decode(moving, [1.0], width=720)

    assert set(decoded) == {1.0}
    assert _picture(decoded[1.0]).size == (720, 128)
    band = _picture(whole[1.0]).crop((0, 1024, 720, 1152))
    assert ImageStat.Stat(ImageChops.difference(_picture(decoded[1.0]), band)).mean[0] < 3


@pytest.mark.asyncio
async def test_a_rotated_video_is_left_to_ffmpeg(moving: Path, tmp_path: Path) -> None:
    # ffmpeg turns such a video upright; a decode pass would read it on its side.
    _require_module("av")
    from thoth_control_plane.assembly.adapters.decoder import PyAvFrameDecoder

    rotated = tmp_path / "rotated.mp4"
    subprocess.run(
        [  # type: ignore[list-item]
            FFMPEG,
            "-v",
            "error",
            "-display_rotation",
            "90",
            "-i",
            str(moving),
            "-c",
            "copy",
            str(rotated),
        ],
        check=True,
    )

    assert await PyAvFrameDecoder().decode(rotated, [1.0], width=720) == {}


def _text_page() -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (720, 200), "white")
    ImageDraw.Draw(image).text(
        (120, 70), "KABAR TERKINI", fill="black", font=ImageFont.load_default(size=40)
    )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_a_band_read_answers_in_the_coordinates_of_the_whole_frame() -> None:
    _require_module("rapidocr")
    from thoth_control_plane.attribution.adapters.ocr import RapidOcrReader

    boxes = await RapidOcrReader(angle=False).read_band(Frame(0.0, _text_page()), 0.5, 0.7)

    found = [box for box in boxes if "TERKINI" in box.text]
    assert found, [box.text for box in boxes]
    assert 0.5 < found[0].top < found[0].bottom < 0.7
    assert 0.1 < found[0].left < found[0].right < 0.9


def test_a_band_is_not_scaled_up_and_keeps_two_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    # The detector scales a short side up to 736 by default, so a crop read slower than the frame.
    _require_module("rapidocr")
    import rapidocr

    from thoth_control_plane.attribution.adapters.ocr import RapidOcrReader

    built: list[dict[str, object]] = []
    monkeypatch.setattr(rapidocr, "RapidOCR", lambda params=None: built.append(params or {}))

    RapidOcrReader()._get_band()

    assert built == [
        {
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            "Det.limit_type": "max",
            "Det.limit_side_len": 736,
        }
    ]


@pytest.mark.asyncio
async def test_a_decode_pass_lands_on_the_same_frame_as_ffmpeg(tmp_path: Path) -> None:
    _require_module("av")
    from thoth_control_plane.assembly.adapters.decoder import PyAvFrameDecoder
    from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource

    if FFMPEG is None:
        pytest.fail("ffmpeg is required for this test and is not installed")
    # A white bar two pixels further on in every frame: its place says which frame this is.
    video = tmp_path / "counting.mp4"
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x180:d=4:r=30",
            "-vf",
            "geq=lum='if(between(X,N*2,N*2+1),235,16)':cb=128:cr=128",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "1",
            str(video),
        ],
        check=True,
    )
    seconds = [0.5, 1.0, 1.0625, 1.53125, 2.75, 3.5]

    decoded = await PyAvFrameDecoder().decode(video, seconds, width=320)

    def bar(frame: Frame) -> int:
        row = _picture(frame).crop((0, 90, 320, 91))
        return max(range(320), key=lambda x: row.getpixel((x, 0)))

    alone = FfmpegFrameSource(FFMPEG)
    for second in seconds:
        assert abs(bar(decoded[second]) - bar(await alone.frame_at(video, second, width=320))) <= 1


@pytest.mark.asyncio
async def test_a_decode_pass_keeps_the_brightness_of_saturated_colours(tmp_path: Path) -> None:
    # Through RGB these clip: the picture OCR reads came out up to 4.6 levels darker.
    _require_module("av")
    from PIL import ImageStat

    from thoth_control_plane.assembly.adapters.decoder import PyAvFrameDecoder
    from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource

    if FFMPEG is None:
        pytest.fail("ffmpeg is required for this test and is not installed")
    video = tmp_path / "saturated.mp4"
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x180:d=1:r=30",
            "-vf",
            "geq=lum=60:cb=250:cr=250",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "1",
            str(video),
        ],
        check=True,
    )

    decoded = await PyAvFrameDecoder().decode(video, [0.5], width=320)
    alone = await FfmpegFrameSource(FFMPEG).frame_at(video, 0.5, width=320)

    gap = ImageStat.Stat(_picture(decoded[0.5])).mean[0] - ImageStat.Stat(_picture(alone)).mean[0]
    assert abs(gap) < 1

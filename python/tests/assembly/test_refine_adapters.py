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

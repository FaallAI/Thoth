"""The calibration capture records exactly what production classifies, recovery included."""

from __future__ import annotations

import asyncio
from pathlib import Path

from tests.assembly.capture_ocr import record_ocr
from thoth_control_plane.attribution.adapters.frames import FrameError
from thoth_control_plane.attribution.matching import TextBox
from thoth_control_plane.attribution.ports import Frame


class Frames:
    """The video stream ends before the container: the last sample has no frame (Instagram)."""

    async def frame_at(self, video: Path, second: float, *, width: int) -> Frame:
        if second > 38.9:
            raise FrameError("ffmpeg_failed")
        return Frame(second, b"jpeg")


class Probe:
    async def duration(self, video: Path) -> float:
        raise AssertionError("the duration is given")


class Text:
    async def read(self, frame: Frame) -> list[TextBox]:
        return [TextBox("kata", 0.712345678, 0.787654321, 0.123456789, 0.876543219)]


def test_capture_recovers_frames_and_keeps_exact_geometry() -> None:
    case = asyncio.run(
        record_ocr(
            Path("v.mp4"), 39.077, frames=Frames(), probe=Probe(), text=Text(), max_frames=12
        )
    )

    assert len(case["frames"]) == 12
    assert case["frames"][-1]["t"] < 38.9  # recovered, as production does
    assert case["frames"][0]["boxes"] == [
        ["kata", 0.123456789, 0.712345678, 0.876543219, 0.787654321]
    ]
    assert case["duration"] == 39.077
    assert case["captured"]["outcome"] == case["ocr"].outcome

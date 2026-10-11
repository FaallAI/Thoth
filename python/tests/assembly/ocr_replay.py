"""Replay a recorded calibration case through `analyze_main_ocr` with recorded answers."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from thoth_control_plane.assembly.models import MainOcr
from thoth_control_plane.assembly.ocr import analyze_main_ocr
from thoth_control_plane.attribution.adapters.frames import FrameError
from thoth_control_plane.attribution.matching import TextBox
from thoth_control_plane.attribution.ports import Frame

NOW = datetime(2026, 10, 12, tzinfo=UTC)


class _Frames:
    """Only the recorded seconds decode, so frame recovery takes the recorded path again."""

    def __init__(self, seconds: set[float]) -> None:
        self._seconds = seconds

    async def frame_at(self, video: Path, second: float, *, width: int) -> Frame:
        match = next((s for s in self._seconds if abs(s - second) < 1e-6), None)
        if match is None:
            raise FrameError("not_recorded")
        return Frame(match, f"{match}".encode())


class _Text:
    def __init__(self, frames: list[dict[str, Any]]) -> None:
        self._boxes = {frame["t"]: frame["boxes"] for frame in frames}

    async def read(self, frame: Frame) -> list[TextBox]:
        boxes = self._boxes[float(frame.jpeg.decode())]
        return [TextBox(text, y0, y1, x0, x1) for text, x0, y0, x1, y1 in boxes]


class _Probe:
    async def duration(self, video: Path) -> float:
        raise AssertionError("the recorded duration is used")


class _Answer:
    def __init__(self, tracker: float | None, vision: bool | None) -> None:
        self._tracker, self._vision = tracker, vision

    async def first_absent(self, *args: object) -> float | None:
        return self._tracker

    async def speech_captions(self, frames: object) -> bool | None:
        return self._vision


def replay(case: dict[str, Any]) -> MainOcr:
    answers = _Answer(case.get("tracker"), case.get("vision"))
    return asyncio.run(
        analyze_main_ocr(
            Path("recorded.mp4"),
            case["duration"],
            frames=_Frames({frame["t"] for frame in case["frames"]}),
            probe=_Probe(),
            text=_Text(case["frames"]),
            max_frames=12,
            now=NOW,
            trim_allowed=case.get("trim_allowed", True),
            tracker=answers,
            judge=answers,
        )
    )

"""A title card the source opens on: where it ends, read offline (operator, 2026-11-08)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from thoth_control_plane.assembly.intro_card import intro_card_end
from thoth_control_plane.attribution.adapters.frames import FrameError
from thoth_control_plane.attribution.matching import TextBox
from thoth_control_plane.attribution.ports import Frame

VIDEO = Path("main.mp4")
# The ROCKY GERUNG source's card, as RapidOCR read it at 0 s (2026-11-07): lines top to bottom.
CARD = [
    TextBox("TOBAT ROCKY.", 0.106, 0.144, 0.25, 0.75),
    TextBox("UDAH TUA...!!!", 0.16, 0.203, 0.3, 0.7),
    TextBox("Penjilat nasional", 0.512, 0.563, 0.1, 0.6),
    TextBox("SOSIAL EKSPERIMEN", 0.745, 0.805, 0.1, 0.9),
    TextBox("ROCKY GERUNG", 0.806, 0.878, 0.15, 0.85),
    TextBox("(Wantimpres)", 0.947, 0.977, 0.02, 0.2),
]
CAPTION = TextBox("bung", 0.84, 0.894, 0.42, 0.58)


class Frames:
    def __init__(self, broken: set[float] = frozenset()) -> None:
        self.broken, self.calls = broken, []

    async def frame_at(self, video: Path, second: float, *, width: int) -> Frame:
        self.calls.append(second)
        if second in self.broken:
            raise FrameError("frame_extract")
        return Frame(second, f"{second}".encode())


class Reader:
    def __init__(self, boxes_at: Callable[[float], list[TextBox]]) -> None:
        self.boxes_at = boxes_at

    async def read(self, frame: Frame) -> list[TextBox]:
        return self.boxes_at(float(frame.jpeg.decode()))


def end(boxes_at: Callable[[float], list[TextBox]], frames: Frames | None = None) -> float | None:
    return asyncio.run(intro_card_end(VIDEO, frames or Frames(), Reader(boxes_at)))


def test_a_title_card_ends_where_its_lines_go() -> None:
    found = end(lambda second: CARD if second < 0.4 else [CAPTION])

    assert found is not None and 0.375 < found <= 0.5


def test_a_video_that_opens_on_its_scene_has_no_card() -> None:
    assert end(lambda second: [CAPTION]) is None


def test_text_that_stays_is_an_overlay_not_a_card() -> None:
    assert end(lambda second: CARD) is None


def test_a_card_that_only_fills_the_top_is_not_taken_for_one() -> None:
    # A headline band over the action is no title card: cutting it would lose the action.
    top = [TextBox(f"line {i}", 0.05 + i * 0.05, 0.09 + i * 0.05, 0.1, 0.9) for i in range(6)]

    assert end(lambda second: top if second < 0.4 else []) is None


def test_an_unreadable_first_frame_cuts_nothing() -> None:
    assert end(lambda second: CARD if second < 0.4 else [], Frames(broken={0.0})) is None


def test_an_unreadable_frame_while_looking_cuts_nothing() -> None:
    assert end(lambda second: CARD if second < 0.4 else [], Frames(broken={0.5})) is None

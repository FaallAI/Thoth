"""A title card the source opens on (operator, 2026-11-08): a narrated draft starts after it.

The ROCKY GERUNG source opened on its own cover, lines of text from top to bottom, for about
0.4 s, and the narration's heading sat over it on the video's first frame. A card is text that
fills the frame top and bottom on the first frame and is gone within the first moments; text
that stays is an overlay, and a band of lines only at the top is a headline over the action.
Local RapidOCR only. Any doubt or failed read answers None, and nothing is cut.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path

from thoth_control_plane.assembly.ocr import _read_at
from thoth_control_plane.assembly.ports import FrameSampler, TextReader
from thoth_control_plane.assembly.subtitles import OcrBox, OcrFrame, norm_text

CARD_MIN_LINES = 5
TOP, BOTTOM = 1 / 3, 2 / 3  # a card's lines reach both thirds
LOOK_SECONDS = 1.5  # past this the text is part of the video, not a cover before it
STEP = 0.25
ROUNDS = 2  # the 0.25 s gap narrows to 1/16 s
GONE_SHARE = 0.3  # fewer of the card's lines than this, on their spots: the card is gone
SPOT = 0.05
SAME_TEXT = 0.8


def _middle(box: OcrBox) -> tuple[float, float]:
    return (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2


def _is_card(frame: OcrFrame) -> bool:
    lines = [box for box in frame.boxes if norm_text(box.text)]
    middles = [_middle(box)[1] for box in lines]
    return (
        len(lines) >= CARD_MIN_LINES
        and any(y < TOP for y in middles)
        and any(y > BOTTOM for y in middles)
    )


def _still_there(line: OcrBox, frame: OcrFrame) -> bool:
    x, y = _middle(line)
    text = norm_text(line.text)
    return any(
        abs(_middle(box)[0] - x) <= SPOT
        and abs(_middle(box)[1] - y) <= SPOT
        and SequenceMatcher(None, text, norm_text(box.text)).ratio() >= SAME_TEXT
        for box in frame.boxes
    )


def _gone(card: OcrFrame, frame: OcrFrame) -> bool:
    lines = [box for box in card.boxes if norm_text(box.text)]
    kept = sum(1 for line in lines if _still_there(line, frame))
    return kept < GONE_SHARE * len(lines)


async def intro_card_end(video: Path, frames: FrameSampler, text: TextReader) -> float | None:
    """The second the opening title card ends, at most 1/16 s after it; None without one."""
    card, _ = await _read_at(frames, video, text, 0.0, None)
    if card.error or not _is_card(card):
        return None
    inside, outside = 0.0, None
    second = STEP
    while second <= LOOK_SECONDS + 1e-9:
        row, _ = await _read_at(frames, video, text, second, second - 0.001)
        if row.error:
            return None
        if _gone(card, row):
            outside = second
            break
        inside = second
        second = round(second + STEP, 6)
    if outside is None:
        return None
    for _ in range(ROUNDS):
        middle = round((inside + outside) / 2, 6)
        row, _ = await _read_at(frames, video, text, middle, middle - 0.001)
        if row.error:
            return outside
        if _gone(card, row):
            outside = middle
        else:
            inside = middle
    return outside

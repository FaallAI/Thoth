"""Visual signals that need no model: frame-hash matching and burned-in speech detection.

A repost is a cut of the original's footage, so most of its frames reappear in the original.
Frames are compared as an unordered bag of 64-bit perceptual hashes, in the manner of Meta's
vPDQ. Hashing itself lives in `adapters/frames.py`; this module only compares numbers.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

LOWER_BAND = 0.55


@dataclass(frozen=True)
class FrameHash:
    second: float
    value: int


@dataclass(frozen=True)
class TextBox:
    """One OCR line; `top` and `bottom` are fractions of the frame height."""

    text: str
    top: float
    bottom: float


def distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def match_share(
    repost: Sequence[FrameHash], candidate: Sequence[FrameHash], max_distance: int
) -> float | None:
    """The share of the repost's frames found in the candidate; None when a side has none."""
    if not repost or not candidate:
        return None
    # ponytail: O(n*m) comparisons, a few thousand for short clips; index by hash band if long
    hits = sum(
        1
        for frame in repost
        if any(distance(frame.value, other.value) <= max_distance for other in candidate)
    )
    return hits / len(repost)


def looks_like_burned_in_speech(
    frames: Sequence[Sequence[TextBox]], *, min_share: float = 0.6, min_distinct: int = 3
) -> bool:
    """Changing text in the lower part of most frames: the captions of a reaction upload.

    A lower-third (a name, a credit bar) repeats one string, so it is not speech, and a
    headline at the top is not in the lower band.
    """
    if not frames:
        return False
    lines = [
        " ".join(box.text for box in boxes if (box.top + box.bottom) / 2 >= LOWER_BAND).strip()
        for boxes in frames
    ]
    spoken = [line.lower() for line in lines if line]
    return len(spoken) / len(frames) >= min_share and len(set(spoken)) >= min_distinct

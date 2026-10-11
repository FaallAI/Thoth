"""Visual signals that need no model: match summaries and burned-in speech detection.

A repost reuses the original's footage, often transformed: cut, zoomed, framed by overlays, or
shrunk into a panel of a reaction video. The matcher (`adapters/visual.py`, ORB features with a
RANSAC homography) reports, for each sampled repost frame, the most geometrically consistent
feature matches it found in any candidate frame; this module only reads those numbers.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

LOWER_BAND = 0.55


@dataclass(frozen=True)
class TextBox:
    """One OCR line; `top`/`bottom` are fractions of the height, `left`/`right` of the width."""

    text: str
    top: float
    bottom: float
    left: float = 0.0
    right: float = 1.0


def summarize_matches(inliers: Sequence[int], *, min_inliers: int) -> tuple[int, int] | None:
    """(repost frames holding the candidate, best inlier count); None when nothing compared."""
    if not inliers:
        return None
    return sum(1 for count in inliers if count >= min_inliers), max(inliers)


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

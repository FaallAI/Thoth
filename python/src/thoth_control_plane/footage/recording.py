"""One copy of a recording (footage library spec 2026-11-15, 9.4 and 9.9). Pure decisions over
ORB inlier counts; the features come from the attribution `OrbMatcher`.

Matching frames alone cannot tell a copy from another moment on the same set: two moments of one
podcast matched 9 of 9 frames (spike, 2026-11-16). A copy is the same moment, so its best matches
sit on one time offset, and stand far above the rest of their row.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from thoth_control_plane.attribution.matching import TextBox

MIN_INLIERS = 25
MIN_FRAMES = 3
ALIGNED_SHARE = 0.6
OFFSET_SLACK = 1
MIN_PEAK = 3.0
RECORDING_WIDTH = 480
MAIN_STEP_SECONDS = 2.0
UNKNOWN_DATE = "9999"
CLEAN_SHARE = 0.15  # spec 10.6: the one same-event clip


def triggered(best: Sequence[int]) -> bool:
    """Stage 1: any frame matches well enough to look closer."""
    return any(count >= MIN_INLIERS for count in best)


def is_copy(matrix: Sequence[Sequence[int]]) -> bool:
    """Stage 2 over a 1 fps inlier matrix (rows: the candidate's frames): at least 3 matched
    frames, 60% of them on one time offset (+-1 s), and best matches 3x their row's median."""
    rows = [(index, row) for index, row in enumerate(matrix) if row and max(row) >= MIN_INLIERS]
    if len(rows) < MIN_FRAMES:
        return False
    offsets = [list(row).index(max(row)) - index for index, row in rows]
    aligned = max(sum(1 for o in offsets if abs(o - mode) <= OFFSET_SLACK) for mode in offsets)
    if aligned < ALIGNED_SHARE * len(rows):
        return False
    peaks = [max(row) / max(1.0, statistics.median(row)) for _, row in rows]
    return statistics.median(peaks) >= MIN_PEAK


def text_share(frames: Sequence[Sequence[TextBox]]) -> float:
    """The mean share of a frame that OCR text boxes cover: watermarks, captions, header bars."""
    if not frames:
        return 0.0
    shares = [
        min(1.0, sum((b.bottom - b.top) * (b.right - b.left) for b in boxes)) for boxes in frames
    ]
    return sum(shares) / len(shares)


@dataclass(frozen=True)
class CopyFacts:
    url: str
    original: bool  # an own account's clip or a traced original
    share: float  # text_share over its vision frames
    published_at: str | None


def keep_first(a: CopyFacts, b: CopyFacts) -> bool:
    """Whether copy `a` stays over copy `b` (operator, item 63): an original, then the cleaner,
    then the earlier published; a tie keeps `a`."""

    def rank(copy: CopyFacts) -> tuple[bool, float, str]:
        return (not copy.original, copy.share, copy.published_at or UNKNOWN_DATE)

    return rank(a) <= rank(b)


def clean_original(facts: CopyFacts) -> bool:
    """An original with little on-screen text: the only same-event clip a run keeps (10.6)."""
    return facts.original and facts.share <= CLEAN_SHARE

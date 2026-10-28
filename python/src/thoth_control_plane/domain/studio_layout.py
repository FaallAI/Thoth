"""Where Studio places cards and slides (spec 2026-10-21 5c-1, section 3).

Every layout number lives here so the operator's evaluation tunes one module. Times are
seconds of the main scene; positions are the editor's canvas fractions.
"""

from __future__ import annotations

from collections.abc import Sequence

from thoth_control_plane.domain.edit_document_v2 import ClipBlurRegion, Position
from thoth_control_plane.domain.studio_imports import SourceBlurRegion

#: Indonesian readers read 150-200 words a minute at 6.09 characters a word: 15-20 a second.
READING_CPS = 15.0
#: Time to notice a card and find its text before reading starts.
ORIENTATION_SECONDS = 1.0
READING_MIN = 2.5
#: The longest a single text event stays up (Netflix timed text guide).
READING_MAX = 7.0
#: The reaction beat starts at this share of the main scene (legacy render; to be evaluated).
BEAT_START = 0.40
#: The beat ends this long before the main scene does.
BEAT_TAIL = 0.3
CARD_GAP = 0.5
MAX_COMMENT_CARDS = 3
PROFILE_AT = 3.0
PROFILE_SECONDS = 3.0
#: The shortest a clamped profile card lasts, and how far before the scene end it may start.
PROFILE_MIN = 0.5
#: Cards stay inside x 120-960 of a 1080-wide canvas, the strictest platform safe area.
CARD_WIDTH = 0.76
#: Cards sit high, clear of the bottom UI and of the original video's own subtitles.
CARD_CENTER_Y = 0.26
#: The platform's header covers the top 10 % and its buttons the bottom 18 % (spec 2026-10-27, 9).
SAFE_TOP = 0.10
SAFE_BOTTOM = 0.18
SLIDE_SECONDS = 3.0


def reading_seconds(text: str) -> float:
    """How long a comment card stays up: its characters at the reading rate, plus orientation."""
    return min(READING_MAX, max(READING_MIN, len(text) / READING_CPS + ORIENTATION_SECONDS))


def post_card_slot(scene_seconds: float, reading: float) -> tuple[float, float]:
    """(start, duration) of the post card: it opens the video for its reading time (spec 5c-2)."""
    return 0.0, min(reading, scene_seconds)


def profile_slot(scene_seconds: float, *, not_before: float = 0.0) -> tuple[float, float]:
    """(start, duration) of the profile card, after `not_before` (the post card, spec 5c-2) and
    clamped inside a short main scene."""
    start = max(0.0, min(max(PROFILE_AT, not_before), scene_seconds - PROFILE_MIN))
    return start, max(PROFILE_MIN, min(PROFILE_SECONDS, scene_seconds - start))


def reaction_beat(
    scene_seconds: float, reading: Sequence[float], *, not_before: float = 0.0
) -> list[tuple[float, float] | None]:
    """One (start, duration) per comment card in rank order, or None when it is not placed.

    Cards are packed in order with CARD_GAP between them; the first that does not fit ends
    the beat, and none is ever shortened. Leftover time is shared evenly before, between
    and after them, so they spread across the beat. `not_before` keeps the beat clear of
    the profile card, which a short main would otherwise overlap in the same slot.
    """
    start, end = max(BEAT_START * scene_seconds, not_before), scene_seconds - BEAT_TAIL
    placed: list[float] = []
    cursor = start
    for seconds in reading[:MAX_COMMENT_CARDS]:
        if cursor + seconds > end:
            break
        placed.append(seconds)
        cursor += seconds + CARD_GAP
    spare = end - start - sum(placed) - CARD_GAP * max(0, len(placed) - 1)
    extra = spare / (len(placed) + 1) if placed else 0.0
    slots: list[tuple[float, float] | None] = []
    for index, seconds in enumerate(placed):
        at = start + extra * (index + 1) + sum(placed[:index]) + CARD_GAP * index
        slots.append((at, seconds))
    return slots + [None] * (len(reading) - len(placed))


def card_position(
    image_width: int | None, image_height: int | None, canvas: tuple[int, int]
) -> Position:
    """A `fit = "contain"` card drawn CARD_WIDTH of the canvas wide, centred on CARD_CENTER_Y.

    A card too tall for the card line moves down just enough to start below the platform's
    header; one taller than the safe band keeps that top edge (Story's Top preset agrees).
    """
    canvas_width, canvas_height = canvas
    drawn = (
        canvas_width
        if not image_width or not image_height
        else min(canvas_width, canvas_height * image_width / image_height)
    )
    scale = CARD_WIDTH * canvas_width / drawn
    shown = (
        min(1.0, (canvas_width / canvas_height) / (image_width / image_height))
        if image_width and image_height
        else 1.0
    ) * scale
    centre = max(CARD_CENTER_Y, SAFE_TOP + shown / 2)
    return Position(x=0.0, y=centre - 0.5, scale=scale)


def clip_regions(
    regions: Sequence[SourceBlurRegion], fps: float, trim_frames: int
) -> list[ClipBlurRegion]:
    """Detected regions in source frames for a clip that starts `trim_frames` into its source.

    A window that ends at or before the trim is dropped; one that starts before it is
    clamped to it. A region without a window covers the whole clip.
    """
    kept: list[ClipBlurRegion] = []
    for region in regions:
        # OCR allows a hair past the frame edge; the editor does not.
        box = {
            "x": region.x,
            "y": region.y,
            "w": min(region.w, 1.0 - region.x),
            "h": min(region.h, 1.0 - region.y),
        }
        if region.start is None or region.end is None:
            kept.append(ClipBlurRegion(**box))
            continue
        start, end = round(region.start * fps), round(region.end * fps)
        if end <= trim_frames or end <= start:
            continue
        kept.append(ClipBlurRegion(**box, from_frame=max(start, trim_frames), to_frame=end))
    return kept

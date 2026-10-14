"""Pure helpers for the clip checks: the download window, vision sample times, and dHash."""

from __future__ import annotations

from collections.abc import Sequence

WINDOW_SECONDS = 20.0
WHOLE_UP_TO = 30.0
UNKNOWN_WINDOW = (0.0, 30.0)
LEAD_SHARE = 0.1
MIN_LEAD = 3.0
VISION_SHARES = (0.2, 0.5, 0.8)
HASH_SIZE = 8
DUPLICATE_DISTANCE = 10


def clip_window(duration: float | None) -> tuple[float, float] | None:
    """The span to download, or None for the whole clip (spec amendment 1)."""
    if duration is None:
        return UNKNOWN_WINDOW
    if duration <= WHOLE_UP_TO:
        return None
    start = min(max(MIN_LEAD, LEAD_SHARE * duration), duration - WINDOW_SECONDS)
    start = round(start, 3)
    return start, round(start + WINDOW_SECONDS, 3)


def vision_seconds(trim_start: float, duration: float) -> list[float]:
    span = max(duration - trim_start, 0.0)
    return [round(trim_start + span * share, 3) for share in VISION_SHARES]


def dhash(jpeg: bytes) -> int:
    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError("not an image")
    small = cv2.resize(image, (HASH_SIZE + 1, HASH_SIZE), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def is_duplicate(
    hashes: Sequence[int], others: Sequence[Sequence[int]], distance: int = DUPLICATE_DISTANCE
) -> bool:
    """Duplicate when at least half the frames sit within `distance` bits of a frame of one
    other clip (the main or an admitted clip)."""
    if not hashes:
        return False
    for other in others:
        close = sum(1 for h in hashes if any((h ^ o).bit_count() <= distance for o in other))
        if close * 2 >= len(hashes) and other:
            return True
    return False

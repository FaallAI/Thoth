"""Corrections applied after Scout's verdict (spec amendment, operator, 2026-10-12).

Scout's classifier stays a faithful port; real videos showed four ways its verdict hurts a
render (`docs/research/2026-10-12-stage5a-ocr-trim-research.md`):

- an added band that never leaves was blurred *and muted*: it is an overlay, keep the audio;
- signage and LED walls read as captions muted an original: text cut by the frame edge, or
  constant text over part of the video, is scene text;
- captions that survive these rules are confirmed by one vision call before the audio goes;
- a trim belongs only to a main that may be a repost, and its boundary is measured, not the
  midpoint of a sampling gap (the measuring happens in `ocr.py` through a port).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from thoth_control_plane.assembly.subtitles import (
    COVER_MAX,
    OcrBox,
    OcrFrame,
    Region,
    Verdict,
    _area,
    _group,
    _iou,
    _similarity,
    norm_text,
)

EDGE = 0.005  # a box this close to the frame edge is cut by it
EDGE_SHARE = 1 / 3  # this share of edge-cut boxes makes a window scene text
CONSTANT = 0.8  # "the same text" despite OCR noise; distinct captions share less
OVERLAY_COVERAGE = 0.8  # share of usable samples a constant window must cover to be an overlay
INSIDE = 0.01  # tolerance for a box to sit inside a blur region (envelopes are padded)
SLACK = 1e-6


@dataclass(frozen=True)
class Windows:
    captions: tuple[Region, ...] = ()
    overlays: tuple[Region, ...] = ()
    dropped: tuple[Region, ...] = ()


def region_boxes(frames: Sequence[OcrFrame], region: Region) -> list[tuple[OcrFrame, list[OcrBox]]]:
    """The usable frames inside the region's time window, each with the boxes inside it."""
    rows = []
    for frame in frames:
        if frame.error or not region.start - SLACK <= frame.t <= region.end + SLACK:
            continue
        rows.append(
            (
                frame,
                [
                    box
                    for box in frame.boxes
                    if box.x0 >= region.x - INSIDE
                    and box.x1 <= region.x + region.w + INSIDE
                    and box.y0 >= region.y - INSIDE
                    and box.y1 <= region.y + region.h + INSIDE
                ],
            )
        )
    return rows


def _joined(boxes: list[OcrBox]) -> str:
    return norm_text(" ".join(box.text for box in sorted(boxes, key=lambda b: (b.y0, b.x0))))


def sort_windows(frames: Sequence[OcrFrame], verdict: Verdict) -> Windows:
    # Coverage counts only the rendered samples: the trimmed intro is never shown.
    usable = sum(1 for f in frames if not f.error and f.t >= verdict.trim_start - SLACK) or 1
    captions, overlays, dropped = [], [], []
    for region in verdict.subtitle_blur:
        rows = [(frame, boxes) for frame, boxes in region_boxes(frames, region) if boxes]
        boxes = [box for _, row in rows for box in row]
        if not boxes:
            captions.append(region)  # nothing to judge by; the vision call decides
            continue
        cut = sum(1 for box in boxes if box.x0 <= EDGE or box.x1 >= 1 - EDGE)
        if cut >= EDGE_SHARE * len(boxes):
            dropped.append(region)
            continue
        texts = [_joined(row) for _, row in rows]
        constant = len(texts) >= 2 and all(_similarity(texts[0], t) >= CONSTANT for t in texts)
        if constant:
            (overlays if len(rows) / usable >= OVERLAY_COVERAGE else dropped).append(region)
        else:
            captions.append(region)
    return Windows(tuple(captions), tuple(overlays), tuple(dropped))


def headline_span(
    frames: Sequence[OcrFrame], verdict: Verdict
) -> tuple[OcrBox, float, float] | None:
    """The headline a trim removes: its envelope, the last sample holding it, the first not.

    The classifier puts the trim at the midpoint of those two samples; the lines that left are
    the headline-sized boxes of the earlier one with no match in the later. Like Scout's anchor,
    a line must hold in at least two intro samples, and only the band around the widest line
    counts: a box seen once elsewhere would widen the region into moving footage.
    """
    if verdict.trim_start <= 0:
        return None
    usable = sorted((frame for frame in frames if not frame.error), key=lambda f: f.t)
    before = [frame for frame in usable if frame.t < verdict.trim_start]
    after = [frame for frame in usable if frame.t > verdict.trim_start]
    if not before or not after:
        return None
    present, absent = before[-1], after[0]

    def same(box: OcrBox, other: OcrBox) -> bool:
        return _similarity(box.text, other.text) >= 0.5 and _iou(box, other) >= 0.45

    intro = [frame for frame in usable if frame.t <= COVER_MAX]
    left = [
        box
        for box in present.boxes
        if _area(box) >= 0.015
        and box.x1 - box.x0 >= 0.45
        and not any(same(box, other) for other in absent.boxes)
        and sum(1 for frame in intro if any(same(box, other) for other in frame.boxes)) >= 2
    ]
    if not left:
        return None
    widest = max(left, key=lambda box: box.x1 - box.x0)
    left = next(group for group in _group(left) if widest in group)
    envelope = OcrBox(
        " ".join(box.text for box in left),
        min(box.x0 for box in left),
        min(box.y0 for box in left),
        max(box.x1 for box in left),
        max(box.y1 for box in left),
    )
    return envelope, present.t, absent.t


def without_trim(verdict: Verdict) -> Verdict:
    """An original keeps its intro: no trim, windows begin at 0, a cover verdict becomes clean."""
    outcome = "clean" if verdict.outcome == "cover" else verdict.outcome
    return replace(retrim(verdict, 0.0), outcome=outcome)


def retrim(verdict: Verdict, trim: float) -> Verdict:
    """Move the trim; a window that began at the old trim begins at the new one."""
    old = verdict.trim_start
    regions = tuple(
        replace(region, start=trim) if abs(region.start - old) <= SLACK else region
        for region in verdict.subtitle_blur
    )
    return replace(verdict, trim_start=trim, subtitle_blur=regions)


def settle(verdict: Verdict, windows: Windows, confirmed: bool | None) -> Verdict:
    """The final verdict: captions only if the judge did not reject them; overlays keep audio."""
    captions = windows.captions if confirmed is not False else ()
    kept = set(captions) | set(windows.overlays)
    blur = tuple(region for region in verdict.subtitle_blur if region in kept)
    if captions:
        return Verdict("subtitle", verdict.trim_start, True, blur)
    if windows.overlays:
        return Verdict("overlay", verdict.trim_start, False, blur)
    if verdict.trim_start > 0:
        return Verdict("cover", verdict.trim_start, False, ())
    return Verdict("clean", 0.0, False, ())

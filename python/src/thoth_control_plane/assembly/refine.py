"""Corrections applied after Scout's verdict (spec amendment, operator, 2026-10-12).

Scout's classifier stays a faithful port; real videos showed four ways its verdict hurts a
render (`docs/research/2026-10-12-stage5a-ocr-trim-research.md`):

- an added band that never leaves was blurred *and muted*: it is an overlay, keep the audio;
- signage and LED walls read as captions muted an original: text cut by the frame edge, or
  constant text over part of the video, is scene text;
- captions that survive these rules are confirmed by one vision call before the audio goes;
- a trim belongs only to a main that may be a repost, and its boundary is measured, not the
  midpoint of a sampling gap (the measuring happens in `ocr.py` through a port);
- a blur outlasted its text, because one sample stood for seconds of video: captions are read
  again every half second and each window opens and closes with its text (operator, 2026-11-02);
- half a second still showed a word: each edge is then read out of its gap (operator, 2026-11-03).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace

from thoth_control_plane.assembly.subtitles import (
    COVER_MAX,
    OcrBox,
    OcrFrame,
    Region,
    Verdict,
    _area,
    _envelope,
    _group,
    _iou,
    _lower_third,
    _median,
    _plausible_subtitle,
    _similarity,
    editorial_labels,
    norm_text,
)

EDGE = 0.005  # a box this close to the frame edge is cut by it
EDGE_SHARE = 1 / 3  # this share of edge-cut boxes makes a window scene text
CONSTANT = 0.8  # "the same text" despite OCR noise; distinct captions share less
OVERLAY_COVERAGE = 0.8  # share of usable samples a constant window must cover to be an overlay
INSIDE = 0.01  # tolerance for a box to sit inside a blur region (envelopes are padded)
SLACK = 1e-6
FOLLOW_STEP = 0.5
# ponytail: a video past 3 minutes is read thinner to bound the OCR time; its windows are looser.
FOLLOW_MAX_FRAMES = 360
FOLLOW_MIN_READS = 4  # fewer reads on one spot are scene text passing by
TRACK_Y = 0.012  # a caption line keeps its height on the frame...
TRACK_X = 0.05  # ...and its centre or left edge...
TRACK_HEIGHT = 0.4  # ...and its letter size, as a share of the first read
WORD_HEIGHT = 2.0  # the next word's box against this one's: letters below the line make it taller
CAPTION_WIDTH = 0.18  # the sampled rule's narrowest box, here for a track's median read
SAME_TEXT = 0.6  # a misread of the same words; sentences of a caption share less
# ponytail: a caption line that says one sentence for 60% of its reads passes for a sign. Three
# videos put captions at 50% or less and signs at more; judge new misses against this share.
CONSTANT_SHARE = 0.6
MOVED_SHARE = 0.5  # this share of reads also seen on another spot makes a track text in the shot
ANOTHER_SPOT = 0.1  # nearer, it is the same line with a taller read: not another spot


@dataclass(frozen=True)
class Windows:
    captions: tuple[Region, ...] = ()
    overlays: tuple[Region, ...] = ()
    dropped: tuple[Region, ...] = ()


@dataclass(frozen=True)
class EdgeGap:
    """Two neighbouring reads around a window's edge: one holds its text, one does not."""

    reference: OcrBox
    outside: float
    inside: float


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


def follow_seconds(trim_start: float, duration: float) -> list[float]:
    """The seconds to read a caption video at: every half second that gets rendered."""
    step = max(FOLLOW_STEP, (duration - trim_start) / FOLLOW_MAX_FRAMES)
    seconds = (round(i * step, 6) for i in range(1, math.ceil(duration / step)))
    return [second for second in seconds if second >= trim_start - SLACK]


def _on_line(first: OcrBox, box: OcrBox) -> bool:
    return abs((box.y0 + box.y1) - (first.y0 + first.y1)) / 2 <= TRACK_Y and (
        abs((box.x0 + box.x1) - (first.x0 + first.x1)) / 2 <= TRACK_X
        or abs(box.x0 - first.x0) <= TRACK_X
    )


def _on_track(first: OcrBox, box: OcrBox) -> bool:
    height = first.y1 - first.y0
    return _on_line(first, box) and abs((box.y1 - box.y0) - height) <= TRACK_HEIGHT * height


def _same_words(a: str, b: str) -> bool:
    """One text despite the reader: misread, or only part of it read."""
    return bool(a and b) and (_similarity(a, b) >= SAME_TEXT or a in b or b in a)


def _changes(track: list[tuple[int, OcrBox]]) -> bool:
    """Captions say something new; a watermark or a sign says one thing, however it is read."""
    texts = [norm_text(box.text) for _, box in track]
    usual = Counter(texts).most_common(1)[0][0]
    alike = sum(1 for text in texts if _same_words(usual, text))
    return (
        len(track) >= FOLLOW_MIN_READS
        and _median([box.x1 - box.x0 for _, box in track]) >= CAPTION_WIDTH
        and alike / len(track) < CONSTANT_SHARE
    )


def _moves(track: list[tuple[int, OcrBox]], tracks: list[list[tuple[int, OcrBox]]]) -> bool:
    """A camera carries a sign across the frame; a caption's words stay on their own spot."""
    here = track[0][1]
    elsewhere = {
        norm_text(box.text)
        for other in tracks
        if other is not track
        for _, box in other
        if abs(box.y0 + box.y1 - here.y0 - here.y1) / 2 > ANOTHER_SPOT
        or abs(box.x0 + box.x1 - here.x0 - here.x1) / 2 > ANOTHER_SPOT
    }
    seen = sum(
        1
        for _, box in track
        if any(_similarity(norm_text(box.text), text) >= SAME_TEXT for text in elsewhere)
    )
    return seen / len(track) >= MOVED_SHARE


def follow_captions(
    frames: Sequence[OcrFrame], trim_start: float, duration: float
) -> tuple[Region, ...]:
    """The windows of changing text on one spot of the frame, over every rendered frame.

    Each run of frames holding the text is one window, closing halfway to the first frame
    without it. The sampled windows do not narrow this down: twelve samples can miss the
    caption band altogether. Signs, shirts and an editorial chyron are not followed.
    """
    rows = sorted(
        (frame for frame in frames if not frame.error and frame.t >= trim_start - SLACK),
        key=lambda frame: frame.t,
    )
    labels = editorial_labels(rows)
    tracks: list[list[tuple[int, OcrBox]]] = []
    for index, frame in enumerate(rows):
        for box in frame.boxes:
            if (
                box.x0 <= EDGE
                or box.x1 >= 1 - EDGE
                or not _plausible_subtitle(box)
                or _lower_third(box, index, rows, labels)
            ):
                continue
            track = next((t for t in tracks if _on_track(t[0][1], box)), None)
            if track is None:
                tracks.append([(index, box)])
            else:
                track.append((index, box))

    regions: list[Region] = []
    for track in tracks:
        if not _changes(track) or _moves(track, tracks):
            continue
        runs: list[list[tuple[int, OcrBox]]] = []
        for read in track:
            if runs and read[0] <= runs[-1][-1][0] + 1:
                runs[-1].append(read)
            else:
                runs.append([read])
        for run in runs:
            first, last = run[0][0], run[-1][0]
            start = (rows[first - 1].t + rows[first].t) / 2 if first > 0 else trim_start
            end = (rows[last].t + rows[last + 1].t) / 2 if last + 1 < len(rows) else duration
            box = _envelope([box for _, box in run])
            regions.append(Region(box.x0, box.y0, box.x1 - box.x0, box.y1 - box.y0, start, end))
    return tuple(sorted(regions, key=lambda region: (region.start, region.y)))


def holds_caption(reference: OcrBox, frame: OcrFrame) -> bool:
    """Any words on the line of `reference`: a caption changes its words, not its line."""
    height = reference.y1 - reference.y0
    return any(
        box.x0 > EDGE
        and box.x1 < 1 - EDGE
        and _plausible_subtitle(box)
        and _on_line(reference, box)
        and height / WORD_HEIGHT <= box.y1 - box.y0 <= height * WORD_HEIGHT
        for box in frame.boxes
    )


def edge_seconds(gap: EdgeGap, rounds: int) -> set[float]:
    """Every second that halving this gap `rounds` times can ask for."""
    spans, seconds = [(gap.outside, gap.inside)], set()
    for _ in range(rounds):
        halves = []
        for one, other in spans:
            middle = round((one + other) / 2, 6)
            seconds.add(middle)
            halves += [(one, middle), (middle, other)]
        spans = halves
    return seconds


def edge_gaps(
    frames: Sequence[OcrFrame], region: Region, trim_start: float
) -> tuple[EdgeGap | None, EdgeGap | None]:
    """Where a window opens and closes. None: it starts at the trim, ends with the video, or
    the read beside the edge holds nothing to look for."""
    rows = sorted(
        (frame for frame in frames if not frame.error and frame.t >= trim_start - SLACK),
        key=lambda frame: frame.t,
    )

    def gap(edge: float, opening: bool) -> EdgeGap | None:
        before = [frame for frame in rows if frame.t < edge - SLACK]
        after = [frame for frame in rows if frame.t > edge + SLACK]
        if opening and not before and after and after[0] is rows[0] and edge <= trim_start + SLACK:
            # Nothing is read before the first read (0.5 s), so a window seen there opened at
            # the trim unread: the trim's own frame is the far side (edoc_3a20bf9f, 2026-11-05).
            inside, outside_t = rows[0], trim_start
        elif not before or not after:
            return None
        else:
            inside, outside = (after[0], before[-1]) if opening else (before[-1], after[0])
            outside_t = outside.t
        boxes = region_boxes([inside], replace(region, start=inside.t, end=inside.t))[0][1]
        # The window's middle is its line: text in the shot can reach into the window too.
        middle = region.y + region.h / 2
        reference = min(
            (box for box in boxes if _plausible_subtitle(box)),
            key=lambda box: abs((box.y0 + box.y1) / 2 - middle),
            default=None,
        )
        return EdgeGap(reference, outside_t, inside.t) if reference else None

    return gap(region.start, True), gap(region.end, False)


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

"""Speech captions and intro headlines from OCR boxes: a pure port of Scout's classifier.

Port of `classifyOcrFrames` and `buildSampleTimes` in `scout/lib/subtitle_vision.ts`; the
parity fixture in `tests/fixtures/assembly/classifier_parity.json` holds Scout's own answers.
Headline removal (`trim_start`) and subtitle censorship (blur windows, muted audio) are
independent: a clip can keep a positive trim_start and still carry later blur windows. An
editorial lower-third (a changing chyron anchored by a stable "LIVE NEWS" badge) is kept.
All geometry is normalized to 0..1.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

COVER_MAX = 5.0
# Above this share of the frame a persistent box is furniture worth reasoning about (a headline,
# a caption); below it, it is a watermark or a station badge that every frame carries.
STABLE_SMALL_AREA = 0.02
EDITORIAL_LABEL = re.compile(
    r"^(breaking news|live(?: news)?|exclusive|news(?: update)?|sports|weather|headlines?)$"
)
Outcome = Literal["clean", "cover", "subtitle"]


@dataclass(frozen=True)
class OcrBox:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class OcrFrame:
    t: float
    boxes: tuple[OcrBox, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class Region:
    x: float
    y: float
    w: float
    h: float
    start: float
    end: float


@dataclass(frozen=True)
class Verdict:
    outcome: Outcome
    trim_start: float
    mute_audio: bool
    subtitle_blur: tuple[Region, ...]


CLEAN = Verdict("clean", 0.0, False, ())


def build_sample_times(duration: float, max_frames: int = 12) -> list[float]:
    """The intro densely (headlines live there), the rest spread evenly to the end."""
    limit = max(1, math.floor(max_frames))
    if not math.isfinite(duration) or duration <= 0.5:
        return [0.0]
    intro = [float(t) for t in (0.5, 1, 2, 3, 4, 5) if t < duration][:limit]
    if len(intro) >= limit or duration <= 5:
        return intro
    remaining = limit - len(intro)
    safe_end = max(5.0, duration - min(0.1, duration / 100))
    tail = [round(5 + (safe_end - 5) * ((i + 1) / remaining), 6) for i in range(remaining)]
    return sorted(set(intro) | set(tail))[:limit]


def norm_text(text: str) -> str:
    """Lowercase; every run of characters that is not a letter or a digit becomes one space."""
    kept = "".join(c if unicodedata.category(c)[0] in "LN" else " " for c in text.lower())
    return " ".join(kept.split())


def _area(box: OcrBox) -> float:
    return max(0.0, box.x1 - box.x0) * max(0.0, box.y1 - box.y0)


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) >> 1
    return ordered[mid] if len(ordered) % 2 == 1 else (ordered[mid - 1] + ordered[mid]) / 2


def _plausible_subtitle(box: OcrBox) -> bool:
    # One-glyph captions are valid in CJK; digits alone are not caption evidence. A near
    # full-frame OCR box is noise.
    text = norm_text(box.text)
    digits_only = all(unicodedata.category(c)[0] == "N" or c.isspace() for c in text)
    return (
        bool(text) and not digits_only and not (box.x1 - box.x0 >= 0.9 and box.y1 - box.y0 >= 0.85)
    )


def _iou(a: OcrBox, b: OcrBox) -> float:
    inter = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0)) * max(
        0.0, min(a.y1, b.y1) - max(a.y0, b.y0)
    )
    union = _area(a) + _area(b) - inter
    return inter / union if union > 0 else 0.0


def _v_overlap(a: OcrBox, b: OcrBox) -> float:
    overlap = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    return overlap / max(0.000001, min(a.y1 - a.y0, b.y1 - b.y0))


def _h_overlap(a: OcrBox, b: OcrBox) -> float:
    overlap = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    return overlap / max(0.000001, min(a.x1 - a.x0, b.x1 - b.x0))


def _gap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, max(a0, b0) - min(a1, b1))


def _linked(a: OcrBox, b: OcrBox) -> bool:
    return (_v_overlap(a, b) >= 0.5 and _gap(a.x0, a.x1, b.x0, b.x1) <= 0.08) or (
        _h_overlap(a, b) >= 0.3 and _gap(a.y0, a.y1, b.y0, b.y1) <= 0.07
    )


def _group(boxes: Sequence[OcrBox]) -> list[list[OcrBox]]:
    groups: list[list[OcrBox]] = []
    for box in boxes:
        connected = [i for i, group in enumerate(groups) if any(_linked(box, o) for o in group)]
        if not connected:
            groups.append([box])
            continue
        target = groups[connected[0]]
        target.append(box)
        for i in reversed(connected[1:]):
            target.extend(groups[i])
            del groups[i]
    return groups


def _multiline(boxes: Sequence[OcrBox]) -> bool:
    return any(
        i != j and _gap(a.y0, a.y1, b.y0, b.y1) <= 0.07 and _h_overlap(a, b) >= 0.3
        for i, a in enumerate(boxes)
        for j, b in enumerate(boxes)
    )


def _editorial(text: str) -> bool:
    return EDITORIAL_LABEL.match(norm_text(text)) is not None


def _lower_third(
    box: OcrBox, index: int, frames: Sequence[OcrFrame], labels: Sequence[OcrBox]
) -> bool:
    if box.y0 < 0.65 or box.x0 > 0.3:
        return False
    # A changing left-aligned caption is ambiguous alone: it is an editorial lower-third only
    # when a separate persistent label anchors the same band.
    center = (box.y0 + box.y1) / 2
    anchored = any(
        norm_text(label.text) != norm_text(box.text)
        and abs((label.y0 + label.y1) / 2 - center) <= 0.12
        and label.x0 < box.x0 - 0.03
        and _iou(label, box) < 0.2
        for label in labels
    )
    if not anchored:
        return False
    track = [
        (i, other)
        for i, frame in enumerate(frames)
        for other in frame.boxes
        if _v_overlap(box, other) >= 0.5 and abs(other.x0 - box.x0) <= 0.04
    ]
    if len({i for i, _ in track}) < 2:
        return False
    lefts = [other.x0 for _, other in track]
    return max(lefts) - min(lefts) <= 0.035 and any(
        i != index and norm_text(other.text) != norm_text(box.text) for i, other in track
    )


def _similarity(a: str, b: str) -> float:
    aa, bb = norm_text(a), norm_text(b)
    if not aa or not bb:
        return 0.0
    if aa == bb:
        return 1.0
    tokens_a, tokens_b = set(aa.split(" ")), set(bb.split(" "))
    union = len(tokens_a | tokens_b)
    token_score = len(tokens_a & tokens_b) / union if union else 0.0
    bigrams_a = {aa[i : i + 2] for i in range(len(aa) - 1)}
    bigrams_b = {bb[i : i + 2] for i in range(len(bb) - 1)}
    total = len(bigrams_a) + len(bigrams_b)
    dice = 2 * len(bigrams_a & bigrams_b) / total if total else 0.0
    return max(token_score, dice)


def _envelope(boxes: Sequence[OcrBox]) -> OcrBox:
    return OcrBox(
        " ".join(box.text for box in boxes),
        max(0.0, min(box.x0 for box in boxes) - 0.02),
        max(0.0, min(box.y0 for box in boxes) - 0.015),
        min(1.0, max(box.x1 for box in boxes) + 0.02),
        min(1.0, max(box.y1 for box in boxes) + 0.015),
    )


def _union(a: OcrBox, b: OcrBox) -> OcrBox:
    return OcrBox(
        f"{a.text} {b.text}".strip(),
        min(a.x0, b.x0),
        min(a.y0, b.y0),
        max(a.x1, b.x1),
        max(a.y1, b.y1),
    )


@dataclass
class _Window:
    frame_index: int
    start: float
    end: float
    region: OcrBox


def classify_ocr_frames(frames: Sequence[OcrFrame], duration: float) -> Verdict:
    # A failed sample is unknown, not clean: it must not read as a headline disappearing.
    ordered = sorted((frame for frame in frames if not frame.error), key=lambda frame: frame.t)
    if not ordered:
        return CLEAN
    stable = max(2, math.ceil(len(ordered) * 0.6))

    def same(a: OcrBox, b: OcrBox) -> bool:
        return norm_text(a.text) == norm_text(b.text) and _iou(a, b) >= 0.6

    every = [box for frame in ordered for box in frame.boxes]
    labels: list[OcrBox] = []
    for index, candidate in enumerate(every):
        if (
            not _editorial(candidate.text)
            or candidate.y0 < 0.65
            or _area(candidate) >= STABLE_SMALL_AREA
        ):
            continue
        held = sum(
            1
            for frame in ordered
            if any(_editorial(b.text) and same(b, candidate) for b in frame.boxes)
        )
        first = next((i for i, box in enumerate(every) if same(box, candidate)), -1)
        if held >= stable and first == index:
            labels.append(candidate)

    # A banner on the 2% cutoff jitters across it sample to sample; judge it by its median area
    # so all its samples are kept or dropped together (an 89 s video once lost 47 s to this).
    def stable_small(candidate: OcrBox) -> bool:
        areas = []
        for frame in ordered:
            match = next((box for box in frame.boxes if same(box, candidate)), None)
            if match is not None:
                areas.append(_area(match))
        return len(areas) >= stable and _median(areas) < STABLE_SMALL_AREA

    filtered = [
        replace(frame, boxes=tuple(box for box in frame.boxes if not stable_small(box)))
        for frame in ordered
    ]

    def headline_match(anchor: OcrBox, box: OcrBox) -> bool:
        return _similarity(anchor.text, box.text) >= 0.5 and _iou(anchor, box) >= 0.45

    trim_start = 0.0
    for index, frame in enumerate(filtered):
        if frame.t > COVER_MAX:
            break
        # Headlines often arrive one thin line at a time: wide, but only ~1.5-2% of the frame.
        for anchor in (b for b in frame.boxes if _area(b) >= 0.015 and b.x1 - b.x0 >= 0.45):
            matching = []
            for i in range(index, len(filtered)):
                if filtered[i].t > COVER_MAX:
                    break
                if any(headline_match(anchor, box) for box in filtered[i].boxes):
                    matching.append(i)
            if len(matching) < 2:
                continue
            last = matching[-1]
            absent = next(
                (
                    i
                    for i in range(last + 1, len(filtered))
                    if not any(headline_match(anchor, box) for box in filtered[i].boxes)
                ),
                -1,
            )
            if absent > last:
                trim_start = max(trim_start, (filtered[last].t + filtered[absent].t) / 2)

    raw = [
        replace(
            frame,
            boxes=tuple(
                box
                for box in frame.boxes
                if box.x1 - box.x0 >= 0.18 and box.y1 - box.y0 >= 0.025 and _plausible_subtitle(box)
            )
            if frame.t + 1e-9 >= trim_start
            else (),
        )
        for frame in filtered
    ]
    candidates = [
        replace(
            frame,
            boxes=tuple(box for box in frame.boxes if not _lower_third(box, index, raw, labels)),
        )
        for index, frame in enumerate(raw)
    ]
    multiline = [_multiline(frame.boxes) for frame in candidates]
    selected: list[list[OcrBox]] = []
    for index, frame in enumerate(candidates):
        keep = []
        for box in frame.boxes:
            changes = any(
                other_index != index
                and any(
                    _v_overlap(box, o) >= 0.5 and norm_text(box.text) != norm_text(o.text)
                    for o in other.boxes
                )
                for other_index, other in enumerate(candidates)
            )
            stacked = multiline[index] and any(
                other_index != index
                and multiline[other_index]
                and any(_v_overlap(box, o) >= 0.5 for o in other.boxes)
                for other_index, other in enumerate(candidates)
            )
            if changes or stacked:
                keep.append(box)
        selected.append(keep)

    windows: list[_Window] = []
    for i, boxes in enumerate(selected):
        if not boxes:
            continue
        start = (filtered[i - 1].t + filtered[i].t) / 2 if i > 0 else 0.0
        end = (filtered[i].t + filtered[i + 1].t) / 2 if i + 1 < len(filtered) else duration
        for group in _group(boxes):
            windows.append(_Window(i, max(trim_start, start), min(duration, end), _envelope(group)))

    merged: list[_Window] = []
    consumed: set[int] = set()
    current = -1
    for window in windows:
        if window.frame_index != current:
            consumed = set()
            current = window.frame_index
        match: _Window | None = None
        best = -1.0
        for candidate in merged:
            if id(candidate) in consumed or window.start > candidate.end + 1e-6:
                continue
            vertical = _v_overlap(candidate.region, window.region)
            horizontal = _h_overlap(candidate.region, window.region)
            iou = _iou(candidate.region, window.region)
            if iou < 0.6 and (vertical < 0.5 or horizontal < 0.5):
                continue
            score = max(iou, min(vertical, horizontal))
            if score > best:
                match, best = candidate, score
        if match is not None:
            match.end = max(match.end, window.end)
            match.region = _union(match.region, window.region)
            consumed.add(id(match))
        else:
            created = _Window(window.frame_index, window.start, window.end, window.region)
            merged.append(created)
            consumed.add(id(created))

    blur = tuple(
        Region(
            w.region.x0,
            w.region.y0,
            w.region.x1 - w.region.x0,
            w.region.y1 - w.region.y0,
            w.start,
            w.end,
        )
        for w in merged
    )
    if blur:
        return Verdict("subtitle", trim_start, True, blur)
    if trim_start > 0:
        return Verdict("cover", trim_start, False, ())
    return CLEAN

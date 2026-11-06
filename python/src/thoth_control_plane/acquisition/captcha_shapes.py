"""The local, deterministic solver for TikTok's 3D shapes captcha: the same-shape pair.

Segmentation follows the free spike validated on the one real sample (2026-11-06,
``tests/acquisition/fixtures/shapes_sample.jpg``): the objects are saturated pastels on a
near-white ground, so a saturation mask drops the background and the soft shadows, a hue
split separates overlapping objects of different colours, and connected components with a
minimum area become the candidates. Every pair is scored by the distance between the masks
normalised to a fixed square (aspect kept), taking the better of the plain and mirrored
overlap, and the best pair must beat the runner-up by :data:`PAIR_RATIO` or the solver
refuses rather than click a guess. A refusal does not spare a leased account's cooldown —
an unanswered modal ends as `challenge` like a miss — so the caller asks for a fresh image.
One real image proves feasibility, not accuracy.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any

import cv2
import numpy

#: Objects are saturated pastels; the ground and the soft shadows are near-grey.
SAT_MIN = 45
#: Hue histogram bin, in OpenCV hue degrees (0..179). A group spans the bin around a peak.
HUE_BIN = 10
#: A hue peak must hold at least this share of the saturated pixels to be a colour group.
MIN_GROUP_SHARE = 0.05
MIN_OBJECT_AREA = 300
#: Fewer candidates than this and nothing can be distinguished from anything.
MIN_OBJECTS = 3
#: The refusal margin: the best pair must beat the runner-up both relatively (by this
#: ratio) and absolutely (by PAIR_GAP, the floor under rasterization noise: two identical
#: shapes translated differ by well under it, two merely similar shapes by more).
PAIR_RATIO = 0.7
PAIR_GAP = 0.05
#: Masks are compared at this square size, aspect kept, so shape — not scale — decides.
NORM = 64
#: The vision fallback's set-of-marks picture marks at most this many candidates.
MAX_MARKS = 12


@dataclass(frozen=True)
class Component:
    """One segmented candidate: its box and centroid in image pixels, and its own mask."""

    box: tuple[int, int, int, int]
    centroid: tuple[float, float]
    area: int
    mask: Any


@dataclass
class ShapesResult:
    """The solver's answer: two image-pixel points, or None when it refuses."""

    points: tuple[tuple[float, float], tuple[float, float]] | None
    objects: list[Component]


def _hue_centers(values: numpy.ndarray) -> list[float]:
    """Hue group centres as the histogram's own local maxima, near peaks merged.

    The number of colour groups comes from the image, not a fixed k: every local maximum
    of the raw histogram holding enough pixels is one group (the histogram is read raw —
    smoothing would let a strong colour's shoulder swamp a neighbouring weaker peak), and
    maxima within two bins are one colour, a single pastel spreading across bins.
    """
    if not len(values):
        return []
    bins = 180 // HUE_BIN
    hist, _ = numpy.histogram(values, bins=bins, range=(0.0, 180.0))

    def local_mass(index: int) -> int:
        return int(hist[(index - 1) % bins] + hist[index] + hist[(index + 1) % bins])

    peaks = [
        index
        for index in range(bins)
        if hist[index] >= hist[(index - 1) % bins]
        and hist[index] > hist[(index + 1) % bins]
        and local_mass(index) >= MIN_GROUP_SHARE * len(values)
    ]
    kept: list[int] = []
    for index in sorted(peaks, key=lambda i: -hist[i]):
        if all(min(abs(index - other), bins - abs(index - other)) > 2 for other in kept):
            kept.append(index)
    centers = []
    for index in sorted(kept):
        near = numpy.abs((values - index * HUE_BIN + 90) % 180 - 90) <= 1.5 * HUE_BIN
        centers.append(float(values[near].mean()))
    return centers


def objects_in(image: Any) -> list[Component]:
    """The image's candidates: saturation mask, hue groups from the image, components."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = (hsv[:, :, 1] > SAT_MIN).astype(numpy.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, numpy.ones((3, 3), numpy.uint8))
    hue = hsv[:, :, 0].astype(int)
    objects: list[Component] = []
    for center in _hue_centers(hue[mask > 0].astype(numpy.float32)):
        near = numpy.abs((hue - round(center) + 90) % 180 - 90) <= HUE_BIN
        group = ((mask > 0) & near).astype(numpy.uint8) * 255
        group = cv2.morphologyEx(group, cv2.MORPH_CLOSE, numpy.ones((5, 5), numpy.uint8))
        count, labels, stats, cents = cv2.connectedComponentsWithStats(group)
        for index in range(1, count):
            x, y, w, h, area = stats[index]
            if area < MIN_OBJECT_AREA:
                continue
            objects.append(
                Component(
                    (int(x), int(y), int(w), int(h)),
                    (float(cents[index][0]), float(cents[index][1])),
                    int(area),
                    (labels[y : y + h, x : x + w] == index).astype(numpy.uint8) * 255,
                )
            )
    return objects


def _norm_mask(mask: Any, flip: bool = False) -> numpy.ndarray:
    """The mask scaled into an NORM square, aspect kept by padding, as a boolean array."""
    height, width = mask.shape
    scale = NORM / max(height, width)
    resized = cv2.resize(
        mask,
        (max(1, int(width * scale)), max(1, int(height * scale))),
        interpolation=cv2.INTER_NEAREST,
    )
    if flip:
        resized = cv2.flip(resized, 1)
    out = numpy.zeros((NORM, NORM), numpy.uint8)
    out[: resized.shape[0], : resized.shape[1]] = resized
    return out > 0


def mask_distance(a: Component, b: Component) -> float:
    """How unlike two shapes are: 1 minus the best of plain and mirrored IoU distance.

    Scaling to NORM makes the distance about shape, not size; the mirrored variant answers
    the pair TikTok renders flipped.
    """
    best = 1.0
    for flip in (False, True):
        p, q = _norm_mask(a.mask, flip=flip), _norm_mask(b.mask)
        best = min(best, 1.0 - (p & q).sum() / max(1, (p | q).sum()))
    return float(best)


# ponytail: known ceilings of the mask-IoU pair — same-colour overlap merges into one
# component, a strong 3D rotation or a mirrored pose defeats the normalised masks, and
# partial occlusion eats the overlap; upgrade path: DINOv2 features (RESEARCH.md) or the
# vision fallback behind this solver.
def same_shape_pair(image: Any) -> ShapesResult:
    """The two same-shape objects' centroids in image pixels, or a refusal (points None).

    Refuses unless at least MIN_OBJECTS candidates were segmented and the best pair beats
    the runner-up twice — best < PAIR_RATIO x second and second - best >= PAIR_GAP, so a
    tie between two equally plausible pairs refuses — unless RapidOCR reads the same single
    character off exactly two crops, a backup vote that fires only on the margin's refusal
    (it reads nothing off the pastel 3D renders of the one real sample, so it helps flatter
    renders).
    """
    objects = objects_in(image)
    points: tuple[tuple[float, float], tuple[float, float]] | None = None
    if len(objects) >= MIN_OBJECTS:
        ranked = sorted(
            (mask_distance(objects[i], objects[j]), i, j)
            for i, j in itertools.combinations(range(len(objects)), 2)
        )
        best, second = ranked[0], ranked[1]
        if best[0] < PAIR_RATIO * second[0] and second[0] - best[0] >= PAIR_GAP:
            points = (objects[best[1]].centroid, objects[best[2]].centroid)
        else:
            pair = _ocr_pair(image, objects)
            if pair is not None:
                points = (pair[0].centroid, pair[1].centroid)
    return ShapesResult(points, objects)


_OCR: Any = None


def _ocr_pair(image: Any, objects: list[Component]) -> tuple[Component, Component] | None:
    """The backup vote: exactly two crops that read the same single character.

    Best effort and quiet: a missing RapidOCR, a read that raises, or an ambiguous tally
    (more than one same-character pair) all abstain. Not one call leaves this machine.
    """
    global _OCR
    try:
        if _OCR is None:
            from rapidocr import RapidOCR

            _OCR = RapidOCR()
        texts = []
        for component in objects:
            x, y, w, h = component.box
            crop = image[max(0, y - 6) : y + h + 6, max(0, x - 6) : x + w + 6]
            reads = _OCR(crop)
            singles = [
                str(box[1]).strip()
                for box in (getattr(reads, "boxes", None) or [])
                if len(str(box[1]).strip()) == 1
            ]
            texts.append(singles[0] if singles else None)
        pairs = [
            (objects[i], objects[j])
            for i, j in itertools.combinations(range(len(objects)), 2)
            if texts[i] is not None and texts[i] == texts[j]
        ]
        return pairs[0] if len(pairs) == 1 else None
    except Exception:
        return None


def marked_image(image: Any, objects: list[Component]) -> bytes:
    """The vision fallback's set-of-marks picture: numbered red boxes over the candidates.

    The vision model is asked for numbers, never raw coordinates, so the marks are what it
    sees and what the click then aims at (the chosen boxes' centres).
    """
    marked = image.copy()
    for number, component in enumerate(objects[:MAX_MARKS], start=1):
        x, y, w, h = component.box
        cv2.rectangle(marked, (x - 4, y - 4), (x + w + 4, y + h + 4), (0, 0, 255), 2)
        cv2.putText(
            marked,
            str(number),
            (x - 4, y - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (0, 0, 255),
            2,
        )
    ok, encoded = cv2.imencode(".png", marked)
    return encoded.tobytes() if ok else b""

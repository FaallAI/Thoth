"""Shots from scene cuts, the frames the vision call sees, and the label of each shot.

The cover call used to see only the first three seconds, so a reaction that opens on the clip
it shows looked like a plain repost (research 2026-10-13). Frames now come from the cover and
the middle of the longest shots.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from thoth_control_plane.attribution.ports import Frame

MAX_VISION_FRAMES = 6
MIN_SHOT = 1.0
COVER_SECONDS = (0.0, 1.0)


@dataclass(frozen=True)
class Shot:
    start: float
    end: float
    shows: str = "other"


def shots(cuts: Sequence[float], end: float) -> list[Shot]:
    """The shots between cuts; one shorter than `MIN_SHOT` joins the shot before it."""
    bounds = [0.0, *sorted(cut for cut in cuts if 0.0 < cut < end), end]
    merged: list[Shot] = []
    for start, stop in zip(bounds, bounds[1:], strict=False):
        if merged and stop - start < MIN_SHOT:
            merged[-1] = Shot(merged[-1].start, stop)
        else:
            merged.append(Shot(start, stop))
    return merged


def vision_frames(frames: Sequence[Frame], cut: Sequence[Shot]) -> list[Frame]:
    """The cover seconds, then the frame nearest the middle of each shot, longest first."""
    if not frames:
        return []
    chosen = {frame.second: frame for frame in frames if frame.second in COVER_SECONDS}
    for shot in sorted(cut, key=lambda s: s.end - s.start, reverse=True):
        if len(chosen) >= MAX_VISION_FRAMES:
            break
        middle = (shot.start + shot.end) / 2
        nearest = min(frames, key=lambda frame: abs(frame.second - middle))
        chosen.setdefault(nearest.second, nearest)
    return [chosen[second] for second in sorted(chosen)][:MAX_VISION_FRAMES]


def label(cut: Sequence[Shot], sent: Sequence[Frame], shows: Sequence[str]) -> list[Shot]:
    """Each shot takes the label of the last sent frame inside it.

    A list of the wrong length labels nothing: models drop items, and a shifted list would
    give a shot another shot's label.
    """
    if len(shows) != len(sent):
        return [replace(shot, shows="other") for shot in cut]
    labelled = []
    for shot in cut:
        inside = [s for f, s in zip(sent, shows, strict=True) if shot.start <= f.second < shot.end]
        labelled.append(replace(shot, shows=inside[-1] if inside else "other"))
    return labelled

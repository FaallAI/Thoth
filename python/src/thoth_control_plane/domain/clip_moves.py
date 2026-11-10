"""Clip moves: keyframed scale and place, and how edits keep them in place (spec 2026-11-09, 3.1).

Frames are timeline frames relative to the clip's start. The composition's `moves.ts` follows the
same rules; `packages/remotion-composition/src/move_cases.json` holds the cases both run.
"""

from __future__ import annotations

from itertools import pairwise

from thoth_control_plane.domain.edit_document_v2 import (
    Ease,
    EditDocumentV2,
    MoveKeyframe,
    TimelineVideoClip,
)

Value = tuple[float, float, float]


def ease(kind: Ease, t: float) -> float:
    """How far along a segment the value is at its fraction `t`."""
    if kind == "linear":
        return t
    if kind == "ease_out":
        return 1 - (1 - t) ** 2
    if kind == "ease_in_out":
        return 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2
    return 0.0


def _value(keyframe: MoveKeyframe) -> Value:
    return (keyframe.scale, keyframe.x, keyframe.y)


def _segment(moves: list[MoveKeyframe], frame: float) -> MoveKeyframe:
    """The keyframe whose segment holds `frame`: the last at or before it, else the first."""
    before = [move for move in moves if move.frame <= frame]
    return before[-1] if before else moves[0]


def move_at(moves: list[MoveKeyframe], frame: float) -> Value:
    """(scale, x, y) at a frame; no moves is the clip's own placement."""
    if not moves:
        return (1.0, 0.0, 0.0)
    if frame <= moves[0].frame:
        return _value(moves[0])
    if frame >= moves[-1].frame:
        return _value(moves[-1])
    for start, end in pairwise(moves):
        if start.frame <= frame < end.frame:
            t = ease(start.ease, (frame - start.frame) / (end.frame - start.frame))
            (s0, x0, y0), (s1, x1, y1) = _value(start), _value(end)
            return (s0 + (s1 - s0) * t, x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
    return _value(moves[-1])


def _at(moves: list[MoveKeyframe], frame: int, ease_of: Ease) -> MoveKeyframe:
    scale, x, y = move_at(moves, frame)
    return MoveKeyframe(frame=0, scale=scale, x=x, y=y, ease=ease_of)


def shift_moves(moves: list[MoveKeyframe], delta: int) -> list[MoveKeyframe]:
    """The clip's start moved by `delta` frames; the picture at the new start stays as it was."""
    if not moves:
        return []
    kept = [
        move.model_copy(update={"frame": move.frame - delta})
        for move in moves
        if move.frame >= delta
    ]
    dropped = [move for move in moves if move.frame < delta]
    if dropped and (not kept or kept[0].frame != 0):
        kept.insert(0, _at(moves, delta, dropped[-1].ease))
    return kept


def split_moves(
    moves: list[MoveKeyframe], at: int
) -> tuple[list[MoveKeyframe], list[MoveKeyframe]]:
    """Each part keeps its own keyframes; the cut holds the value it had there."""
    if not moves:
        return [], []
    left = [move.model_copy() for move in moves if move.frame < at]
    if not left:
        left = [_at(moves, 0, moves[0].ease)]
    elif len(left) < len(moves) and left[-1].frame != at - 1:
        end = _at(moves, at - 1, _segment(moves, at - 1).ease)
        left.append(end.model_copy(update={"frame": at - 1}))
    return left, shift_moves(moves, at)


def stretch_moves(moves: list[MoveKeyframe], old: int, new: int) -> list[MoveKeyframe]:
    """A clip retimed from `old` to `new` frames: its moves stretch with it."""
    if not moves or old <= 0 or old == new:
        return [move.model_copy() for move in moves]
    stretched: list[MoveKeyframe] = []
    for move in moves:
        frame = min(move.frame * new // old, new - 1)
        if not stretched or frame > stretched[-1].frame:
            stretched.append(move.model_copy(update={"frame": frame}))
    return stretched


def fit_move_list(moves: list[MoveKeyframe], duration: int) -> list[MoveKeyframe]:
    """Moves past a clip's end are dropped; its last frame holds the value it had there."""
    if not moves or moves[-1].frame < duration:
        return moves
    kept = [move for move in moves if move.frame < duration]
    if not kept or kept[-1].frame != duration - 1:
        end = _at(moves, duration - 1, _segment(moves, duration - 1).ease)
        kept.append(end.model_copy(update={"frame": duration - 1}))
    return kept


def fit_moves(document: EditDocumentV2) -> None:
    """Keep every clip's moves inside it after an edit that shortened it."""
    for clip in document.clips:
        if isinstance(clip, TimelineVideoClip) and clip.moves:
            clip.moves = fit_move_list(clip.moves, clip.duration_in_frames)

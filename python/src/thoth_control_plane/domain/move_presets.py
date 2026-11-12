"""The camera move presets, as Studio offers them (`move_presets.ts`), for style templates.

Spec 2026-11-10. The same JSON cases run here and in the dashboard, so a style and a click give the
same keyframes. Punch in needs a playhead, so styles do not use it.
"""

from __future__ import annotations

from typing import Literal

from thoth_control_plane.domain.edit_document_v2 import Ease, MoveKeyframe

MovePreset = Literal["none", "push_in", "pan_across", "scroll_down", "pull_out"]


def _key(frame: int, scale: float, ease: Ease, x: float = 0.0, y: float = 0.0) -> MoveKeyframe:
    return MoveKeyframe(frame=frame, scale=scale, x=x, y=y, ease=ease)


def move_preset(kind: MovePreset, duration: int, fps: float) -> list[MoveKeyframe]:
    """A preset's keyframes for a clip `duration` frames long; a one-frame clip holds the first."""
    del fps  # the playhead-free presets span the clip whatever its rate
    last = max(0, duration - 1)
    moves: list[MoveKeyframe]
    if kind == "push_in":
        moves = [_key(0, 1, "linear"), _key(last, 1.12, "linear")]
    elif kind == "pan_across":
        moves = [_key(0, 1.15, "linear", 0.06), _key(last, 1.15, "linear", -0.06)]
    elif kind == "scroll_down":
        moves = [_key(0, 1.6, "ease_in_out", 0, 0.3), _key(last, 1.6, "ease_in_out", 0, -0.3)]
    elif kind == "pull_out":
        moves = [_key(0, 1.2, "ease_out"), _key(last, 1, "ease_out")]
    else:
        return []
    return moves if last > 0 else moves[:1]

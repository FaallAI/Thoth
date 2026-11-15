"""The planner's deterministic assigner (spec 2026-11-13, 5.5 and 5.7). Pure.

A plan says which shots and card suit each phrase; this turns that into frames. The main video
keeps running underneath on the beats it plays under, a soundbite jump-cuts it, footage rides
over it on the b-roll with its credit, and a card sits on top. No shot is used twice in a draft.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from thoth_control_plane.domain.narration import BeatId
from thoth_control_plane.domain.planner import DraftPlan, PlanPhrase, PlanShot

#: A model pick must last at least this share of its phrase window (a soundbite need not).
MIN_SHARE_OF_WINDOW = 0.5


@dataclass(frozen=True)
class PlannedShot:
    from_frame: int
    duration: int
    asset_id: str
    source_from_frame: int
    layer: Literal["main", "broll"]
    #: Past the source's last frame, hold it.
    hold: bool
    #: The footage source's @account, shown over the shot.
    credit: str | None


@dataclass(frozen=True)
class PlannedCard:
    from_frame: int
    duration: int
    asset_id: str
    item_id: str
    #: No base under it: the card fills the screen instead of sitting on top.
    full: bool


@dataclass(frozen=True)
class BeatAssignment:
    beat: BeatId
    shots: list[PlannedShot]
    cards: list[PlannedCard]
    phrase_starts: list[int]


def pick_bases(
    phrases: Sequence[PlanPhrase],
    shots: Mapping[str, PlanShot],
    windows_seconds: Sequence[float],
    used: set[str],
) -> list[str | None]:
    """Per phrase, the base shot to show, or None for the main-video fallback. A soundbite takes
    its first unused shot whatever its length; a model pick needs half its window. `used` is
    shared by the caller across the whole draft, so a shot never repeats."""
    picks: list[str | None] = []
    for phrase, window in zip(phrases, windows_seconds, strict=True):
        chosen = None
        for shot_id in phrase.base:
            shot = shots.get(shot_id)
            if shot is None or shot_id in used:
                continue
            long_enough = shot.end_seconds - shot.start_seconds >= MIN_SHARE_OF_WINDOW * window
            if phrase.soundbite or long_enough:
                chosen = shot_id
                break
        if chosen is not None:
            used.add(chosen)
        picks.append(chosen)
    return picks


def assign_beat(
    beat: BeatId,
    phrases: Sequence[PlanPhrase],
    windows: Sequence[tuple[int, int]],
    plan: DraftPlan,
    fps: float,
    main_asset: str | None,
    main_from_frame: int,
    background: bool,
    used: set[str],
    source_frames: Mapping[str, int],
) -> BeatAssignment:
    """The beat's shots and cards in timeline frames. `main_from_frame` is the main video's
    source frame at the beat's start; `background` says the main video plays under this beat."""
    shots = {shot.shot_id: shot for shot in plan.shots}
    cards = {card.card_id: card for card in plan.cards}
    lengths = [(end - start) / fps for start, end in windows]
    picks = pick_bases(phrases, shots, lengths, used)
    placed: list[PlannedShot] = []
    placed_cards: list[PlannedCard] = []
    main_at = main_from_frame

    def frames_of(asset_id: str) -> float:
        return source_frames.get(asset_id, math.inf)

    def main(start: int, length: int, source_from: int, asset_id: str) -> None:
        placed.append(
            PlannedShot(
                from_frame=start,
                duration=length,
                asset_id=asset_id,
                source_from_frame=source_from,
                layer="main",
                hold=source_from + length > frames_of(asset_id),
                credit=None,
            )
        )

    for phrase, pick, (start, end) in zip(phrases, picks, windows, strict=True):
        length = end - start
        shot = shots.get(pick) if pick is not None else None
        if shot is not None and shot.source == "main":
            source_from = round(shot.start_seconds * fps)
            main(start, length, source_from, shot.asset_id)
            main_at = source_from + length
        else:
            if background and main_asset is not None:
                main(start, length, main_at, main_asset)
                main_at += length
            if shot is not None:
                source_from = round(shot.start_seconds * fps)
                own = max(1, round((shot.end_seconds - shot.start_seconds) * fps))
                # Over the main video a short shot ends at its own end; alone it plays on.
                duration = min(length, own) if background and main_asset is not None else length
                placed.append(
                    PlannedShot(
                        from_frame=start,
                        duration=duration,
                        asset_id=shot.asset_id,
                        source_from_frame=source_from,
                        layer="broll",
                        hold=source_from + duration > frames_of(shot.asset_id),
                        credit=shot.handle,
                    )
                )
        card = cards.get(phrase.overlay) if phrase.overlay else None
        if card is not None:
            placed_cards.append(
                PlannedCard(
                    from_frame=start,
                    duration=length,
                    asset_id=card.asset_id,
                    item_id=card.item_id,
                    full=not phrase.base,
                )
            )
    return BeatAssignment(
        beat=beat,
        shots=placed,
        cards=placed_cards,
        phrase_starts=[start for start, _ in windows],
    )

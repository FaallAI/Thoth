"""A style's cut rhythm: where a beat's shots fall and what each one shows (spec 2026-11-10, 4).

One function serves the three places a style cuts: applying it (no timing yet), the cut preview
(timing estimated from the script) and the narration write (the voice's real timing). It needs no
understanding of the content; picking a shot for what is said is the planner's work.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from thoth_control_plane.domain.style_templates import CutRules


@dataclass(frozen=True)
class ShotSource:
    asset_id: str
    kind: Literal["video", "image"]
    #: Where the material's own clip started in its source.
    source_from_frame: int
    #: The asset's whole length in frames; None for a still.
    source_frames: int | None
    item_id: str | None = None


@dataclass(frozen=True)
class Shot:
    from_frame: int
    duration: int
    #: None is a card-line slot.
    source: ShotSource | None
    source_from_frame: int = 0


def _boundaries(
    start: int, end: int, rules: CutRules, fps: float, sentence_ends: Sequence[int]
) -> list[int]:
    """The frames the shots start at, `start` first."""
    longest = max(1, round(rules.max_shot_seconds * fps))
    shortest = min(longest, max(1, round(rules.min_shot_seconds * fps)))
    length = end - start
    ends = sorted(e for e in sentence_ends if start < e < end) if rules.cut_on_sentences else []
    if not ends:
        count = max(1, math.ceil(length / longest))
        # A remainder shorter than a shot's minimum is shared out rather than cut on its own.
        if count > 1 and length - (count - 1) * longest < shortest:
            count -= 1
        cuts = [start + round(index * length / count) for index in range(count)]
    else:
        cuts = [start]
        position = start
        while end - position > longest:
            fitting = [e for e in ends if position + shortest <= e <= position + longest]
            position = fitting[-1] if fitting else position + longest
            cuts.append(position)
    # A tail shorter than a shot's minimum joins the shot before it.
    while len(cuts) > 1 and end - cuts[-1] < shortest:
        cuts.pop()
    return cuts


def _with_cards(
    start: int,
    end: int,
    rules: CutRules,
    fps: float,
    sentence_ends: Sequence[int],
    slots: int,
    frames: int,
) -> list[tuple[int, int, bool]]:
    """(from, duration, is_card): the fact shots over the beat less its cards, a card after every
    second fact shot (never after the last), later shots moved on by the cards before them."""
    shortest = max(1, round(rules.min_shot_seconds * fps))
    cards = slots
    while True:
        facts_end = end - cards * frames
        if cards and facts_end - start < shortest:
            cards -= 1
            continue
        cuts = _boundaries(start, facts_end, rules, fps, sentence_ends)
        room = (len(cuts) - 1) // 2
        if room >= cards:
            break
        cards = room
    laid: list[tuple[int, int, bool]] = []
    shift = 0
    bounds = [*cuts[1:], facts_end]
    for index, (begin, stop) in enumerate(zip(cuts, bounds, strict=True)):
        laid.append((begin + shift, stop - begin, False))
        if index % 2 == 1 and shift < cards * frames and index < len(cuts) - 1:
            laid.append((stop + shift, frames, True))
            shift += frames
    return laid


def plan_shots(
    start: int,
    end: int,
    sources: Sequence[ShotSource],
    rules: CutRules,
    fps: float,
    sentence_ends: Sequence[int] = (),
    card_slots: int = 0,
    card_frames: int = 0,
) -> list[Shot]:
    """The shots covering frames [start, end) of a beat, each from one source or a card slot."""
    if end <= start or not sources:
        return []
    if card_slots > 0 and card_frames > 0 and rules.card_between_facts:
        laid = _with_cards(start, end, rules, fps, sentence_ends, card_slots, card_frames)
    else:
        cuts = _boundaries(start, end, rules, fps, sentence_ends)
        stops = [*cuts[1:], end]
        laid = [(begin, stop - begin, False) for begin, stop in zip(cuts, stops, strict=True)]

    cursor = {index: source.source_from_frame for index, source in enumerate(sources)}
    turn = 0
    shots: list[Shot] = []

    def left(index: int) -> float:
        source = sources[index]
        if source.source_frames is None:
            return math.inf
        return source.source_frames - cursor[index]

    for begin, duration, card in laid:
        if card:
            shots.append(Shot(from_frame=begin, duration=duration, source=None))
            continue
        position, remaining = begin, duration
        while remaining > 0:
            order = [(turn + offset) % len(sources) for offset in range(len(sources))]
            chosen = next((index for index in order if left(index) >= remaining), None)
            if chosen is None:
                # Every movie has run out: start them again, then take what the longest can give.
                for index, source in enumerate(sources):
                    cursor[index] = source.source_from_frame
                chosen = max(order, key=left)
            take = int(min(remaining, left(chosen)))
            if take <= 0:
                break
            source = sources[chosen]
            shots.append(
                Shot(
                    from_frame=position,
                    duration=take,
                    source=source,
                    source_from_frame=cursor[chosen] if source.source_frames is not None else 0,
                )
            )
            if source.source_frames is not None:
                cursor[chosen] += take
            if rules.cycle_materials:
                turn = (chosen + 1) % len(sources)
            position += take
            remaining -= take
    return shots

"""Planner stage 1 (spec 2026-11-13): what each narration phrase shows.

A plan is data: the draft's candidate shots and cards, and per voiced beat its phrases with the
picks (a base of video shots, an optional card overlay). Everything here is pure; the shots,
the model call and the store live in `assembly/`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import Literal

from pydantic import Field

from thoth_control_plane.domain.models import StrictModel
from thoth_control_plane.domain.narration import BeatId
from thoth_control_plane.voice.ports import WordTiming

#: A phrase is at least this long before punctuation or the cap may close it (spec 5.1).
MIN_PHRASE_SECONDS = 0.9
#: A phrase closes before the next word would take it past this (spec 5.1).
MAX_PHRASE_SECONDS = 2.4
_CLOSES = re.compile(r"[,.?!;:]$")


class PlanShot(StrictModel):
    shot_id: str
    asset_id: str
    source: Literal["main", "footage"]
    start_seconds: float
    end_seconds: float
    #: What the main video says during the shot (spec 4: a sentence covering >= 1 s or half).
    said: str = ""
    #: The footage source's @account, for its credit.
    handle: str | None = None


class PlanCard(StrictModel):
    card_id: str
    asset_id: str
    item_id: str
    kind: Literal["post_card", "comment_card"]


class PlanPhrase(StrictModel):
    phrase_id: str
    #: Inclusive word indices in the beat's voice.
    first_word: int
    last_word: int
    text: str
    base: list[str] = Field(default_factory=list)
    overlay: str | None = None
    #: The base is the main video saying the phrase (spec 5.3), not a model pick.
    soundbite: bool = False
    why: str = ""


class BeatPlan(StrictModel):
    beat: BeatId
    #: The beat's words, timing aside: a re-voice with the same words reuses the picks.
    words_key: str
    phrases: list[PlanPhrase] = Field(default_factory=list)


class DraftPlan(StrictModel):
    version: int = 1
    #: The model that answered; None when no model answered (soundbites only, or reused).
    model: str | None = None
    shots: list[PlanShot] = Field(default_factory=list)
    cards: list[PlanCard] = Field(default_factory=list)
    beats: list[BeatPlan] = Field(default_factory=list)


def split_phrases(words: Sequence[WordTiming]) -> list[tuple[int, int]]:
    """Inclusive word ranges: closed at punctuation or before ~2.4 s, never under 0.9 s."""
    ranges: list[tuple[int, int]] = []
    first = 0
    for index, word in enumerate(words):
        span = word.end_seconds - words[first].start_seconds
        following = words[index + 1] if index + 1 < len(words) else None
        stop = bool(_CLOSES.search(word.text)) and span >= MIN_PHRASE_SECONDS
        too_long = (
            following is not None
            and following.end_seconds - words[first].start_seconds > MAX_PHRASE_SECONDS
            and span >= MIN_PHRASE_SECONDS
            and not _CLOSES.search(following.text)
        )
        if stop or too_long or following is None:
            ranges.append((first, index))
            first = index + 1
    if len(ranges) > 1:
        a, b = ranges[-1]
        if words[b].end_seconds - words[a].start_seconds < MIN_PHRASE_SECONDS:
            ranges.pop()
            ranges[-1] = (ranges[-1][0], b)
    return ranges


def words_key(words: Sequence[WordTiming]) -> str:
    return hashlib.sha256("\n".join(word.text for word in words).encode()).hexdigest()


def reuse_picks(
    stored: BeatPlan, ranges: Sequence[tuple[int, int]], words: Sequence[WordTiming]
) -> list[PlanPhrase]:
    """The new phrases, each with the picks of the stored phrase covering most of its words."""
    out = []
    for number, (first, last) in enumerate(ranges, start=1):
        best = max(
            stored.phrases,
            key=lambda p: min(last, p.last_word) - max(first, p.first_word),
            default=None,
        )
        overlap = best is not None and min(last, best.last_word) >= max(first, best.first_word)
        out.append(
            PlanPhrase(
                phrase_id=f"P{number}",
                first_word=first,
                last_word=last,
                text=" ".join(word.text for word in words[first : last + 1]),
                base=list(best.base) if overlap and best else [],
                overlay=best.overlay if overlap and best else None,
                soundbite=bool(overlap and best and best.soundbite),
                why=best.why if overlap and best else "",
            )
        )
    return out

"""Moments inside a long video, found by its auto-captions: where a card person is said
(footage library spec 2026-11-15, 4.4). Pure functions; the fetch is an adapter."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from thoth_control_plane.footage.gates import norm

INTRO_SECONDS = 30.0  # a channel's intro and recap
APART_SECONDS = 60.0
LEAD_SECONDS = 1.0
SECTION_SECONDS = 8.0
MAX_MOMENTS = 3


@dataclass(frozen=True)
class CaptionLine:
    start: float
    text: str


class CaptionPort(Protocol):
    async def captions(self, url: str, language: str) -> bytes | None: ...


def parse_json3(data: bytes) -> list[CaptionLine]:
    """YouTube's json3 captions as lines; anything unreadable gives none."""
    try:
        events = json.loads(data)["events"]
    except (ValueError, KeyError, TypeError):
        return []
    lines: list[CaptionLine] = []
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict) or "tStartMs" not in event:
            continue
        segments = event.get("segs") or []
        if not isinstance(segments, list):
            continue
        text = "".join(str(s.get("utf8", "")) for s in segments if isinstance(s, dict)).strip()
        try:
            start = float(event["tStartMs"]) / 1000
        except (TypeError, ValueError):
            continue
        if text:
            lines.append(CaptionLine(start, text))
    return lines


def _says(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def pick_moments(
    lines: Sequence[CaptionLine],
    names: Sequence[str],
    terms: Sequence[str],
    limit: int = MAX_MOMENTS,
) -> list[float]:
    """Up to `limit` line starts that name a card person: 2 per name, 1 per term, best first
    (earlier on ties), past the intro, at least a minute apart; returned in time order."""
    scored: list[tuple[int, float]] = []
    for line in lines:
        if line.start < INTRO_SECONDS:
            continue
        said = norm(line.text)
        named = sum(_says(said, name) for name in names)
        if not named:
            continue
        scored.append((2 * named + sum(_says(said, term) for term in terms), line.start))
    kept: list[float] = []
    for _, start in sorted(scored, key=lambda item: (-item[0], item[1])):
        if all(abs(start - other) >= APART_SECONDS for other in kept):
            kept.append(start)
            if len(kept) == limit:
                break
    return sorted(kept)


def section(moment: float) -> tuple[float, float]:
    start = round(max(0.0, moment - LEAD_SECONDS), 3)
    return start, round(start + SECTION_SECONDS, 3)

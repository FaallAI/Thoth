"""Moments inside a long video, found by its auto-captions: where the story is discussed
(footage library spec 2026-11-15, 4.4 and 9.3). Pure functions; the fetch is an adapter."""

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
WINDOW_SECONDS = 60.0
MIN_SCORE = 4
MIN_WORDS = 2
SAID_CHARS = 1500
LAST_LINE_SECONDS = 3.0


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


@dataclass(frozen=True)
class Discussion:
    """A moment where the story is discussed, and the caption lines around it (`said`, as
    TranscriptSegment dumps in source-video seconds)."""

    moment: float
    said: list[dict[str, float | str]]


def _count(text: str, phrases: Sequence[str]) -> int:
    return sum(_says(text, phrase) for phrase in phrases)


def pick_discussions(
    lines: Sequence[CaptionLine],
    subject: Sequence[str],
    others: Sequence[str],
    words: Sequence[str],
    limit: int = MAX_MOMENTS,
) -> list[Discussion]:
    """Up to `limit` 60 s windows where the story is discussed (spec 2026-11-15, 9.3): 2 per line
    naming the subject, 1 per line naming another person, 1 per distinct word said; a window
    needs a score of 4 and 2 distinct words, so a name alone is never a discussion."""
    said = [norm(line.text) for line in lines]
    windows: list[tuple[int, float, int, int]] = []  # (score, start, first, last) line indexes
    for first, line in enumerate(lines):
        if line.start < INTRO_SECONDS:
            continue
        last = first
        while last + 1 < len(lines) and lines[last + 1].start < line.start + WINDOW_SECONDS:
            last += 1
        inside = said[first : last + 1]
        distinct = {word for word in words if any(_says(text, word) for text in inside)}
        named = sum(2 * bool(_count(t, subject)) + bool(_count(t, others)) for t in inside)
        score = named + len(distinct)
        if score >= MIN_SCORE and len(distinct) >= MIN_WORDS:
            windows.append((score, line.start, first, last))

    def moment(first: int, last: int) -> float:
        weights = {
            i: 2 * bool(_count(said[i], subject))
            + bool(_count(said[i], others))
            + _count(said[i], words)
            for i in range(first, last + 1)
        }
        return lines[max(weights, key=lambda i: (weights[i], -i))].start

    # Windows and their moments both stay a minute apart: two windows a minute apart can still
    # pick lines seconds apart, which would be the same footage twice (final review, 8).
    kept: list[tuple[float, float, int, int]] = []
    for _, start, first, last in sorted(windows, key=lambda w: (-w[0], w[1])):
        at = moment(first, last)
        if all(
            abs(start - other) >= WINDOW_SECONDS and abs(at - shown) >= APART_SECONDS
            for other, shown, _, _ in kept
        ):
            kept.append((start, at, first, last))
            if len(kept) == limit:
                break
    return [Discussion(at, _segments(lines, first, last)) for _, at, first, last in sorted(kept)]


def _segments(lines: Sequence[CaptionLine], first: int, last: int) -> list[dict[str, float | str]]:
    segments: list[dict[str, float | str]] = []
    used = 0
    for index in range(first, last + 1):
        line = lines[index]
        used += len(line.text) + 1
        if used > SAID_CHARS:
            break
        end = lines[index + 1].start if index + 1 < len(lines) else line.start + LAST_LINE_SECONDS
        segments.append(
            {"text": line.text, "start_seconds": line.start, "end_seconds": max(end, line.start)}
        )
    return segments


def section(moment: float) -> tuple[float, float]:
    start = round(max(0.0, moment - LEAD_SECONDS), 3)
    return start, round(start + SECTION_SECONDS, 3)

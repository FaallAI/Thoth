"""Moments inside a long video, found by its auto-captions: where the story is discussed
(footage library spec 2026-11-15, 4.4 and 9.3). Its chapters and Most Replayed heatmap, from the
same metadata, lift and place them, and cut a ceremony with no captions (spec 2026-11-27, 5.2).
Pure functions; the fetch is an adapter."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from thoth_control_plane.footage.gates import mentions, norm

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
CHAPTER_BOOST = 2
HEAT_PEAK = 0.7  # yt-dlp's heatmap values run 0..1; a peak is a most-replayed moment
CHAPTER_OFFSET = 5.0  # past a chapter's title card


@dataclass(frozen=True)
class CaptionLine:
    start: float
    text: str


@dataclass(frozen=True)
class Chapter:
    start: float
    end: float
    title: str


@dataclass(frozen=True)
class HeatPoint:
    start: float
    end: float
    value: float


@dataclass(frozen=True)
class LongVideoHints:
    """What one metadata call says about a long video: its captions, chapters and heatmap."""

    captions: bytes | None = None
    chapters: list[Chapter] = field(default_factory=list)
    heatmap: list[HeatPoint] = field(default_factory=list)


class CaptionPort(Protocol):
    async def captions(self, url: str, language: str) -> bytes | None: ...


def _span(item: object) -> tuple[float, float, dict[str, object]] | None:
    if not isinstance(item, dict):
        return None
    try:
        start, end = float(item["start_time"]), float(item["end_time"])
    except (KeyError, TypeError, ValueError):
        return None
    return (start, end, item) if end > start else None


def parse_chapters(raw: object) -> list[Chapter]:
    """yt-dlp's `chapters`; malformed items are skipped."""
    chapters: list[Chapter] = []
    for span in map(_span, raw if isinstance(raw, list) else []):
        title = span[2].get("title") if span else None
        if span and isinstance(title, str) and title.strip():
            chapters.append(Chapter(span[0], span[1], title.strip()))
    return chapters


def parse_heatmap(raw: object) -> list[HeatPoint]:
    """yt-dlp's `heatmap` (Most Replayed); malformed items are skipped."""
    points: list[HeatPoint] = []
    for span in map(_span, raw if isinstance(raw, list) else []):
        value = span[2].get("value") if span else None
        if span and isinstance(value, int | float):
            points.append(HeatPoint(span[0], span[1], float(value)))
    return points


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


def _names(text: str, names: Sequence[str]) -> int:
    return sum(mentions(text, name) for name in names)


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
    *,
    chapters: Sequence[Chapter] = (),
    heatmap: Sequence[HeatPoint] = (),
) -> list[Discussion]:
    """Up to `limit` 60 s windows where the story is discussed (spec 2026-11-15, 9.3): 2 per line
    naming the subject, 1 per line naming another person, 1 per distinct word said; a window
    needs a score of 4 and 2 distinct words, so a name alone is never a discussion. A chapter on
    the story adds 2 to the windows it holds, and a replay peak weighs a line up. With no
    window, the chapters on the story are the moments (spec 2026-11-27, 5.2)."""
    said = [norm(line.text) for line in lines]
    titles = [(chapter, norm(chapter.title)) for chapter in chapters]
    on_story = [
        chapter
        for chapter, title in titles
        if _names(title, subject) or _names(title, others) or _count(title, words)
    ]
    peaks = [point for point in heatmap if point.value >= HEAT_PEAK]
    windows: list[tuple[int, float, int, int]] = []  # (score, start, first, last) line indexes
    for first, line in enumerate(lines):
        if line.start < INTRO_SECONDS:
            continue
        last = first
        while last + 1 < len(lines) and lines[last + 1].start < line.start + WINDOW_SECONDS:
            last += 1
        inside = said[first : last + 1]
        distinct = {word for word in words if any(_says(text, word) for text in inside)}
        named = sum(2 * bool(_names(t, subject)) + bool(_names(t, others)) for t in inside)
        end = line.start + WINDOW_SECONDS
        boost = CHAPTER_BOOST * any(c.start < end and c.end > line.start for c in on_story)
        score = named + len(distinct) + boost
        # Spec 10.12, revision 2: with a subject, a window must name them.
        if subject and not any(_names(t, subject) for t in inside):
            continue
        if score >= MIN_SCORE and len(distinct) >= MIN_WORDS:
            windows.append((score, line.start, first, last))

    def moment(first: int, last: int) -> float:
        weights = {
            i: 2 * bool(_names(said[i], subject))
            + bool(_names(said[i], others))
            + _count(said[i], words)
            + any(p.start <= lines[i].start < p.end for p in peaks)
            for i in range(first, last + 1)
        }
        return lines[max(weights, key=lambda i: (weights[i], -i))].start

    if not windows:
        return _chapter_moments(titles, subject, others, words, heatmap, limit)

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


def _chapter_moments(
    titles: Sequence[tuple[Chapter, str]],
    subject: Sequence[str],
    others: Sequence[str],
    words: Sequence[str],
    heatmap: Sequence[HeatPoint],
    limit: int,
) -> list[Discussion]:
    """Chapters whose title is on the story, scored like a caption line (2 or more; with a
    subject, the title must name them), each cut where its section stays inside the chapter and
    past the intro: at its strongest replay peak, else just past its title card."""
    scored: list[tuple[int, float, float]] = []  # (score, chapter start, moment)
    for chapter, title in titles:
        low = max(chapter.start + LEAD_SECONDS, INTRO_SECONDS)
        high = chapter.end - (SECTION_SECONDS - LEAD_SECONDS)
        if high < low or (subject and not _names(title, subject)):
            continue
        score = (
            2 * bool(_names(title, subject)) + bool(_names(title, others)) + _count(title, words)
        )
        if score < 2:
            continue
        inside = [p for p in heatmap if p.start < high and p.end > low]
        if inside:
            peak = max(inside, key=lambda p: p.value)
            at = min(max((peak.start + peak.end) / 2, low), high)
        else:
            at = min(low + CHAPTER_OFFSET, high)
        scored.append((score, chapter.start, at))
    kept: list[float] = []
    for _, _, at in sorted(scored, key=lambda s: (-s[0], s[1])):
        if all(abs(at - other) >= APART_SECONDS for other in kept):
            kept.append(at)
            if len(kept) == limit:
                break
    return [Discussion(round(at, 1), []) for at in sorted(kept)]


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

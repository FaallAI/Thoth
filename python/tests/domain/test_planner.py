"""Planner stage 1 (spec 2026-11-13): phrases, plan reuse, speech per shot, soundbites."""

from __future__ import annotations

from thoth_control_plane.domain.planner import (
    BeatPlan,
    PlanPhrase,
    reuse_picks,
    split_phrases,
    words_key,
)
from thoth_control_plane.voice.ports import WordTiming


def w(text: str, start: float, end: float) -> WordTiming:
    return WordTiming(text=text, start_seconds=start, end_seconds=end)


def test_split_cuts_at_punctuation_once_long_enough() -> None:
    words = [
        w("Rocky", 0.0, 0.4),
        w("Gerung", 0.4, 0.9),
        w("kena", 0.9, 1.1),
        w("semprot!", 1.1, 1.6),
        w("Ada", 1.7, 1.9),
        w("yang", 1.9, 2.1),
        w("teriak", 2.1, 2.6),
        w("tobat,", 2.6, 3.0),
    ]
    assert split_phrases(words) == [(0, 3), (4, 7)]


def test_split_caps_a_phrase_near_2_4_seconds() -> None:
    words = [w(f"kata{i}", i * 0.5, i * 0.5 + 0.45) for i in range(10)]
    ranges = split_phrases(words)
    assert all(words[b].end_seconds - words[a].start_seconds <= 2.4 + 0.5 for a, b in ranges)
    assert len(ranges) >= 2
    assert ranges[0][0] == 0 and ranges[-1][1] == 9
    assert all(b + 1 == c for (_, b), (c, _) in zip(ranges, ranges[1:], strict=False))


def test_split_folds_a_short_tail_into_the_phrase_before() -> None:
    words = [w("Bung", 0.0, 0.5), w("Rocky", 0.5, 1.0), w("Gerung,", 1.0, 1.6), w("nih.", 1.7, 2.0)]
    assert split_phrases(words) == [(0, 3)]


def test_split_of_no_words_is_empty() -> None:
    assert split_phrases([]) == []


def test_words_key_ignores_timing() -> None:
    assert words_key([w("a", 0, 1), w("b", 1, 2)]) == words_key([w("a", 0, 2), w("b", 2, 3)])
    assert words_key([w("a", 0, 1)]) != words_key([w("b", 0, 1)])


def test_reuse_maps_picks_by_word_overlap() -> None:
    stored = BeatPlan(
        beat="main",
        words_key="k",
        phrases=[
            PlanPhrase(phrase_id="P1", first_word=0, last_word=3, text="", base=["S4"]),
            PlanPhrase(phrase_id="P2", first_word=4, last_word=7, text="", overlay="C2"),
        ],
    )
    words = [w(str(i), i, i + 1) for i in range(8)]
    out = reuse_picks(stored, [(0, 2), (3, 7)], words)
    assert [p.base for p in out] == [["S4"], []]
    assert [p.overlay for p in out] == [None, "C2"]
    assert [(p.first_word, p.last_word) for p in out] == [(0, 2), (3, 7)]
    assert [p.text for p in out] == ["0 1 2", "3 4 5 6 7"]

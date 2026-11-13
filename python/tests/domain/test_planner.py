"""Planner stage 1 (spec 2026-11-13): phrases, plan reuse, speech per shot, soundbites."""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

from thoth_control_plane.domain.narration import TranscriptSegment
from thoth_control_plane.domain.planner import (
    BeatPlan,
    PlanPhrase,
    PlanShot,
    reuse_picks,
    shot_speech,
    soundbite,
    split_phrases,
    words_key,
)
from thoth_control_plane.voice.ports import WordTiming

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "planner"


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
    assert all(b + 1 == c for (_, b), (c, _) in pairwise(ranges))


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


SEGS = [
    TranscriptSegment(text="A", start_seconds=0.9, end_seconds=20.4),
    TranscriptSegment(text="B", start_seconds=20.4, end_seconds=32.1),
]


def test_a_sliver_at_a_cut_is_not_the_shots_speech() -> None:
    assert shot_speech(SEGS, 17.9, 20.9) == "A"
    assert shot_speech(SEGS, 20.9, 23.9) == "B"
    assert shot_speech(SEGS, 19.0, 22.0) == "A B"
    assert shot_speech(SEGS, 40.0, 41.0) == ""


def _main(shot_id: str, said: str, start: float = 0.0) -> PlanShot:
    return PlanShot(
        shot_id=shot_id,
        asset_id="m",
        source="main",
        start_seconds=start,
        end_seconds=start + 1,
        said=said,
    )


def test_soundbite_needs_two_content_words_and_half_overlap() -> None:
    shots = [_main("S25", "Penjilat nasional.", 0.0), _main("S3", "Tobat, TG!", 1.0)]
    assert soundbite("penjilat nasional.", shots) == ["S25"]
    assert soundbite("nah.", shots) == []
    assert soundbite("sampai ada yang menyebutnya sebagai", shots) == []


def test_soundbite_returns_every_best_shot_in_time_order() -> None:
    shots = [_main("S26", "Penjilat nasional.", 5.0), _main("S25", "Penjilat nasional.", 4.0)]
    assert soundbite("penjilat nasional", shots) == ["S25", "S26"]


def fixture_soundbite_score() -> tuple[int, int]:
    """(fired, hit): phrases a soundbite fires on, and those hitting the operator's blind pick."""
    fired = hit = 0
    for path in sorted(FIXTURES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        shots = [
            PlanShot(
                shot_id=s["shot"],
                asset_id=s["asset_id"],
                source=s["source"],
                start_seconds=s["start"],
                end_seconds=s["end"],
                said=s["said"],
            )
            for s in data["shots"]
            if s["source"] == "main"
        ]
        for phrase in data["phrases"]:
            picked = soundbite(phrase["text"], shots)
            if picked:
                fired += 1
                hit += bool(set(picked) & set(data["blind"][phrase["id"]]["own"]))
    return fired, hit


def test_soundbite_hits_the_operators_blind_pick_on_the_fixtures() -> None:
    fired, hit = fixture_soundbite_score()
    assert fired >= 12 and hit >= 12, (fired, hit)

"""Planner stage 1: the deterministic assigner (spec 2026-11-13, 5.5 and 5.7)."""

from __future__ import annotations

import json
from pathlib import Path

from thoth_control_plane.domain.planner import DraftPlan, PlanCard, PlanPhrase, PlanShot, soundbite
from thoth_control_plane.domain.planner_assign import assign_beat, pick_bases

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "planner"
FPS = 30.0


def shot(
    shot_id: str, asset: str, source: str, start: float, end: float, handle: str | None = None
):
    return PlanShot(
        shot_id=shot_id,
        asset_id=asset,
        source=source,  # type: ignore[arg-type]
        start_seconds=start,
        end_seconds=end,
        handle=handle,
    )


SHOT_LIST = [
    shot("S1", "main_asset", "main", 0.0, 3.0),
    shot("S2", "main_asset", "main", 3.0, 6.0),
    shot("S7", "main_asset", "main", 20.0, 21.0),
    shot("S8", "main_asset", "main", 21.0, 21.4),
    shot("S40", "f1", "footage", 2.0, 5.0, "@kompascomreport"),
    shot("S41", "f2", "footage", 0.0, 0.5, "@metropolitan.id"),
]
SHOTS = {s.shot_id: s for s in SHOT_LIST}
PLAN = DraftPlan(
    shots=SHOT_LIST,
    cards=[PlanCard(card_id="C2", asset_id="card2", item_id="comment_002", kind="comment_card")],
)
SRC = {"main_asset": 9000, "f1": 300, "f2": 20}


def ph(base: list[str] | None = None, overlay: str | None = None, soundbite: bool = False):
    return PlanPhrase(
        phrase_id="P1",
        first_word=0,
        last_word=1,
        text="",
        base=base or [],
        overlay=overlay,
        soundbite=soundbite,
    )


def test_no_shot_repeats_across_the_draft() -> None:
    used: set[str] = set()
    first = pick_bases([ph(base=["S1"])], SHOTS, [1.5], used)
    second = pick_bases([ph(base=["S1", "S2"])], SHOTS, [1.5], used)
    assert first == ["S1"] and second == ["S2"]


def test_a_shot_shorter_than_half_its_window_is_passed_over() -> None:
    assert pick_bases([ph(base=["S8", "S1"])], SHOTS, [2.0], set()) == ["S1"]


def test_a_soundbite_is_taken_even_when_shorter_than_half_its_window() -> None:
    assert pick_bases([ph(base=["S8"], soundbite=True)], SHOTS, [9.0], set()) == ["S8"]


def test_nothing_fits_falls_back_to_the_main_video() -> None:
    a = assign_beat("main", [ph()], [(0, 45)], PLAN, FPS, "main_asset", 300, True, set(), SRC)
    assert [(s.layer, s.asset_id, s.source_from_frame, s.duration) for s in a.shots] == [
        ("main", "main_asset", 300, 45)
    ]
    assert a.cards == [] and a.phrase_starts == [0]


def test_a_soundbite_jump_cuts_the_main_video() -> None:
    a = assign_beat(
        "main", [ph(base=["S2"], soundbite=True), ph()], [(0, 45), (45, 90)], PLAN, FPS,
        "main_asset", 300, True, set(), SRC,
    )  # fmt: skip
    assert [(s.layer, s.source_from_frame) for s in a.shots] == [("main", 90), ("main", 135)]


def test_footage_base_rides_over_the_running_main_video_with_a_credit() -> None:
    a = assign_beat(
        "main", [ph(base=["S40"])], [(0, 45)], PLAN, FPS, "main_asset", 300, True, set(), SRC
    )
    assert {s.layer for s in a.shots} == {"main", "broll"}
    broll = next(s for s in a.shots if s.layer == "broll")
    assert (broll.asset_id, broll.source_from_frame, broll.credit) == ("f1", 60, "@kompascomreport")
    main = next(s for s in a.shots if s.layer == "main")
    assert (main.source_from_frame, main.duration, main.credit) == (300, 45, None)


def test_a_short_footage_shot_ends_at_its_own_end_over_the_main_video() -> None:
    a = assign_beat(
        "main", [ph(base=["S41"], soundbite=True)], [(0, 90)], PLAN, FPS, "main_asset", 0, True,
        set(), SRC,
    )  # fmt: skip
    broll = next(s for s in a.shots if s.layer == "broll")
    assert broll.duration == 15 and not broll.hold


def test_a_short_footage_shot_holds_inside_its_source_on_the_footage_beat() -> None:  # Focus 5
    a = assign_beat(
        "footage", [ph(base=["S41"], soundbite=True)], [(0, 90)], PLAN, FPS, None, 0, False,
        set(), SRC,
    )  # fmt: skip
    broll = next(s for s in a.shots if s.layer == "broll")
    assert broll.hold and broll.source_from_frame < 20 and broll.duration == 90


def test_nothing_fits_on_the_footage_beat_leaves_the_window_to_the_rhythm() -> None:
    a = assign_beat("footage", [ph()], [(0, 45)], PLAN, FPS, None, 0, False, set(), SRC)
    assert a.shots == [] and a.phrase_starts == [0]


def test_card_with_no_base_fills_the_screen() -> None:
    a = assign_beat(
        "reactions", [ph(overlay="C2")], [(0, 45)], PLAN, FPS, "main_asset", 0, True, set(), SRC
    )
    assert [(c.asset_id, c.item_id, c.full, c.from_frame, c.duration) for c in a.cards] == [
        ("card2", "comment_002", True, 0, 45)
    ]
    assert {s.layer for s in a.shots} == {"main"}


def test_card_over_a_base_is_an_overlay() -> None:
    a = assign_beat(
        "reactions", [ph(base=["S1"], overlay="C2")], [(0, 45)], PLAN, FPS, "main_asset", 0, True,
        set(), SRC,
    )  # fmt: skip
    assert [c.full for c in a.cards] == [False]


def fixture_blind_first_shot_score() -> float:
    """The middle counting (spec 4): blind picks only, the first base shot, a main-video fallback
    counted fine where the operator picked no shot."""
    right = total = 0
    for path in sorted(FIXTURES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        shots = {
            s["shot"]: PlanShot(
                shot_id=s["shot"],
                asset_id=s["asset_id"],
                source=s["source"],
                start_seconds=s["start"],
                end_seconds=s["end"],
                said=s["said"],
            )
            for s in data["shots"]
        }
        mains = [s for s in shots.values() if s.source == "main"]
        phrases, windows = [], []
        for p in data["phrases"]:
            heard = soundbite(p["text"], mains)
            answer = data["answer_v3"].get(p["id"], {"base": []})
            phrases.append(
                PlanPhrase(
                    phrase_id=p["id"],
                    first_word=0,
                    last_word=0,
                    text=p["text"],
                    base=heard or answer["base"],
                    soundbite=bool(heard),
                )
            )
            windows.append(p["end"] - p["start"])
        picks = pick_bases(phrases, shots, windows, set())
        for p, pick in zip(data["phrases"], picks, strict=True):
            own = {x for x in data["blind"][p["id"]]["own"] if not x.startswith("C")}
            total += 1
            right += (pick in own) if own else (pick is None or shots[pick].source == "main")
    return right / total


def test_the_trial_answers_keep_the_blind_first_shot_score() -> None:
    score = fixture_blind_first_shot_score()
    print(f"blind first-shot score on the trial fixtures: {score:.2f}")
    assert score >= 0.60, score

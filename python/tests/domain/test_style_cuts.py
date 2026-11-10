"""A style's cut rhythm: where a beat's shots fall and what each shows (spec 2026-11-10, 4)."""

from __future__ import annotations

from thoth_control_plane.domain.style_cuts import ShotSource, plan_shots
from thoth_control_plane.domain.style_templates import CutRules

FPS = 30
IMAGE = ShotSource(asset_id="asset_photo", kind="image", source_from_frame=0, source_frames=None)
LONG = ShotSource(asset_id="asset_long", kind="video", source_from_frame=0, source_frames=3000)


def rules(max_seconds: float, **changes: object) -> CutRules:
    return CutRules(max_shot_seconds=max_seconds, **changes)  # type: ignore[arg-type]


def test_shots_never_exceed_max() -> None:
    shots = plan_shots(0, 330, [LONG], rules(5.0), FPS)
    assert all(shot.duration <= 150 for shot in shots)
    assert sum(shot.duration for shot in shots) == 330


def test_cuts_snap_to_sentence_ends() -> None:
    shots = plan_shots(0, 260, [LONG], rules(5.0), FPS, sentence_ends=[100, 200])
    assert [shot.from_frame for shot in shots] == [0, 100, 200]


def test_a_beat_shorter_than_one_shot_gets_one_shot() -> None:
    shots = plan_shots(0, 20, [LONG], rules(5.0), FPS)
    assert [(shot.from_frame, shot.duration) for shot in shots] == [(0, 20)]


def test_a_short_tail_merges() -> None:
    shots = plan_shots(0, 155, [LONG], rules(5.0), FPS)
    assert [(shot.from_frame, shot.duration) for shot in shots] == [(0, 155)]


def test_materials_cycle_and_a_short_movie_hands_over() -> None:
    short = ShotSource(asset_id="asset_short", kind="video", source_from_frame=0, source_frames=40)
    shots = plan_shots(0, 200, [short, IMAGE], rules(3.0), FPS)
    assert all(shot.source is not None for shot in shots)
    for shot in shots:
        if shot.source == short:
            assert shot.source_from_frame + shot.duration <= 40
    assert sum(shot.duration for shot in shots) == 200


def test_materials_take_turns() -> None:
    shots = plan_shots(0, 360, [LONG, IMAGE], rules(3.0), FPS)
    assert [shot.source for shot in shots[:4]] == [LONG, IMAGE, LONG, IMAGE]


def test_a_movie_resumes_where_its_last_shot_stopped() -> None:
    shots = plan_shots(0, 180, [LONG], rules(3.0), FPS)
    assert [shot.source_from_frame for shot in shots] == [0, 90]


def test_cards_sit_between_facts() -> None:
    shots = plan_shots(
        0,
        600,
        [LONG, IMAGE],
        rules(3.0, card_between_facts=True),
        FPS,
        card_slots=2,
        card_frames=60,
    )
    sources = [shot.source for shot in shots]
    assert sources[2] is None and sources[5] is None
    assert sources.count(None) == 2
    assert sum(shot.duration for shot in shots) == 600


def test_no_sources_gives_no_shots() -> None:
    assert plan_shots(0, 100, [], rules(3.0), FPS) == []

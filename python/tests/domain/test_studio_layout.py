"""Layout rules for cards, slides and the reaction beat (spec 2026-10-21 5c-1, section 3)."""

from __future__ import annotations

import pytest

from thoth_control_plane.domain.studio_imports import SourceBlurRegion
from thoth_control_plane.domain.studio_layout import (
    card_position,
    clip_regions,
    profile_slot,
    reaction_beat,
    reading_seconds,
)

CANVAS = (1080, 1920)


def test_reading_time_follows_fifteen_characters_a_second() -> None:
    assert reading_seconds("a" * 39) == pytest.approx(3.6)
    assert reading_seconds("a" * 84) == pytest.approx(6.6)
    assert reading_seconds("a" * 155) == pytest.approx(7.0)
    assert reading_seconds("") == pytest.approx(2.5)


def test_reading_time_counts_code_points() -> None:
    assert reading_seconds("🔥" * 30) == pytest.approx(3.0)


def test_a_short_main_places_few_cards_and_never_shortens_one() -> None:
    reading = [3.6, 3.6, 3.6]
    slots = reaction_beat(11.2, reading)
    placed = [(slot, seconds) for slot, seconds in zip(slots, reading, strict=True) if slot]
    assert 1 <= len(placed) <= 2
    for (start, duration), seconds in placed:
        assert duration == pytest.approx(seconds)
        assert start + duration <= 11.2 - 0.3 + 1e-9


def test_a_typical_main_places_three_spread_cards() -> None:
    slots = reaction_beat(46.5, [3.6, 4.0, 6.6, 3.0])
    assert slots[3] is None
    placed = [slot for slot in slots[:3] if slot is not None]
    assert len(placed) == 3
    assert placed[0][0] > 0.4 * 46.5
    gaps = [placed[k + 1][0] - (placed[k][0] + placed[k][1]) for k in range(2)]
    assert gaps[0] == pytest.approx(gaps[1])
    assert gaps[0] >= 0.5
    assert placed[2][0] + placed[2][1] <= 46.5 - 0.3 + 1e-9


def test_a_card_that_does_not_fit_stops_the_beat() -> None:
    assert reaction_beat(12.0, [7.0, 2.5]) == [None, None]


def test_a_three_second_main_places_no_card() -> None:
    assert reaction_beat(3.0, [2.5]) == [None]


def test_profile_slot_clamps_inside_a_short_scene() -> None:
    assert profile_slot(46.5) == pytest.approx((3.0, 3.0))
    assert profile_slot(3.0) == pytest.approx((2.5, 0.5))
    assert profile_slot(1.0) == pytest.approx((0.5, 0.5))


def _drawn(width: int | None, height: int | None) -> tuple[float, float]:
    """The drawn card width and its vertical centre, in canvas pixels."""
    position = card_position(width, height, CANVAS)
    canvas_w, canvas_h = CANVAS
    contain_w = canvas_w if not width or not height else min(canvas_w, canvas_h * width / height)
    return contain_w * position.scale, canvas_h / 2 + position.y * canvas_h


def test_card_position_is_centred_at_the_card_line() -> None:
    width, centre = _drawn(768, 198)
    assert width == pytest.approx(0.76 * 1080, abs=1)
    assert centre == pytest.approx(0.26 * 1920, abs=1)
    assert card_position(768, 198, CANVAS).x == 0
    assert card_position(None, None, CANVAS).scale == pytest.approx(0.76)


def test_the_beat_waits_for_the_profile_card() -> None:
    # An 11 s main would start its beat at 4.48 s, under the profile card (3-6 s).
    [slot] = reaction_beat(11.2, [2.5], not_before=6.5)
    assert slot is not None
    assert slot[0] >= 6.5


def test_clip_regions_drop_and_clamp_at_the_trim() -> None:
    band = {"x": 0.1, "y": 0.65, "w": 0.8, "h": 0.09}
    regions = [
        SourceBlurRegion(**band, start=1.0, end=1.5),
        SourceBlurRegion(**band, start=1.5, end=3.0),
        SourceBlurRegion(**band),
    ]
    converted = clip_regions(regions, fps=30.0, trim_frames=60)
    assert [(r.from_frame, r.to_frame) for r in converted] == [(60, 90), (None, None)]
    assert (converted[0].x, converted[0].h) == (0.1, 0.09)

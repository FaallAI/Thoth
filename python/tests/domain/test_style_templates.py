"""Style templates: Style A and Style B as data (spec 2026-11-10)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from thoth_control_plane.domain.narration import BEAT_ORDER
from thoth_control_plane.domain.style_templates import BUILT_IN_STYLES, StyleTemplate


def test_both_built_in_styles_cover_every_beat() -> None:
    for style in BUILT_IN_STYLES.values():
        assert set(style.beats) == set(BEAT_ORDER)


def test_style_a_values() -> None:
    a = BUILT_IN_STYLES["style_a"]
    assert a.captions.style == "boxed"
    assert (a.cuts.min_shot_seconds, a.cuts.max_shot_seconds) == (1.5, 4.0)  # spec 2026-11-17
    assert a.narration.card_lines is False
    assert a.beats["hook"].heading_place == "title_top"
    assert a.beats["main"].background == "blur_fill"
    assert a.beats["evidence"].highlight and a.beats["evidence"].arrow
    assert a.beats["footage"].background == "blur_fill"


def test_style_b_values() -> None:
    b = BUILT_IN_STYLES["style_b"]
    assert b.captions.style == "kinetic"
    assert b.cuts.max_shot_seconds == 2.4 and b.cuts.min_shot_seconds == 0.9
    assert b.cuts.card_between_facts is True
    assert b.narration.card_lines is True
    assert b.beats["main"].dim == 0.45


def test_style_b_is_still_and_planned() -> None:
    # Planner stage 1 (spec 2026-11-13, 5.6): phrase-start cuts, a still camera, revision 2.
    b = BUILT_IN_STYLES["style_b"]
    assert b.revision == 2 and b.cuts.planned
    assert {look.move for look in b.beats.values()} == {"none"}
    assert {look.fit for look in b.beats.values()} == {"cover"}


def test_a_template_missing_a_beat_is_refused() -> None:
    body = BUILT_IN_STYLES["style_a"].model_dump()
    del body["beats"]["outro"]
    with pytest.raises(ValidationError):
        StyleTemplate.model_validate(body)


def test_starters_are_written() -> None:
    a = BUILT_IN_STYLES["style_a"].narration.starter
    b = BUILT_IN_STYLES["style_b"].narration.starter
    assert "Hook" in a and "Call-To-Value" in a
    assert "metafora" in b.lower() and "reaksi" in b.lower()


def test_every_built_in_style_is_planned() -> None:  # spec 2026-11-17, goal 1
    assert all(style.cuts.planned for style in BUILT_IN_STYLES.values())
    assert BUILT_IN_STYLES["style_a"].revision == 2


def test_a_stored_template_without_planned_is_planned() -> None:
    body = BUILT_IN_STYLES["style_a"].model_dump()
    del body["cuts"]["planned"]
    assert StyleTemplate.model_validate(body).cuts.planned is True

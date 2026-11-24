"""Style templates: Style A and Style B as data (spec 2026-11-10)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from thoth_control_plane.domain.narration import BEAT_ORDER
from thoth_control_plane.domain.style_templates import (
    BUILT_IN_STYLES,
    DEFAULT_DELIVERY,
    NarrationRules,
    StyleTemplate,
)


def test_both_built_in_styles_cover_every_beat() -> None:
    for style in BUILT_IN_STYLES.values():
        assert set(style.beats) == set(BEAT_ORDER)


def test_style_a_values() -> None:
    a = BUILT_IN_STYLES["style_a"]
    assert a.captions.style == "boxed"
    # Operator, 2026-11-17 (item 88): Style B's b-roll rhythm for Style A too.
    assert (a.cuts.min_shot_seconds, a.cuts.max_shot_seconds) == (0.9, 2.4)
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
    assert BUILT_IN_STYLES["style_a"].revision == 3


def test_a_stored_template_without_planned_is_planned() -> None:
    body = BUILT_IN_STYLES["style_a"].model_dump()
    del body["cuts"]["planned"]
    assert StyleTemplate.model_validate(body).cuts.planned is True


def test_no_built_in_style_caps_the_half_phrase_rule() -> None:
    # Item 86 capped Style A's slow phrases; at Style B's rhythm (item 88) half a phrase is at
    # most 1.2 s, so the cap stays available to a style but no built-in one sets it.
    assert all(s.cuts.pick_cap_seconds is None for s in BUILT_IN_STYLES.values())


def test_built_in_styles_define_distinct_delivery_profiles() -> None:
    """Stressed delivery (spec 2026-11-24, 5.2): Style A expressive, Style B calm."""
    a = BUILT_IN_STYLES["style_a"].narration.delivery
    assert (a.stability, a.max_tags_per_beat) == (0.45, 3)
    assert a.tags == ("curious", "amused", "excited", "surprised", "emphatically", "whispers")
    b = BUILT_IN_STYLES["style_b"].narration.delivery
    assert (b.stability, b.max_tags_per_beat) == (0.50, 2)
    assert b.tags == ("seriously", "intrigued", "emphatically", "thoughtful")
    assert "amused" not in b.tags


def test_narration_rules_decodes_without_delivery_field() -> None:
    assert NarrationRules(starter="x").delivery == DEFAULT_DELIVERY
    assert DEFAULT_DELIVERY.stability == 0.48
    assert DEFAULT_DELIVERY.tags == ("curious", "emphatically", "intrigued", "seriously")
    assert DEFAULT_DELIVERY.max_tags_per_beat == 3


def test_a_stored_template_with_its_delivery_reads_back() -> None:
    """A template is stored as JSON, where the delivery tags come back as a list."""
    for style in BUILT_IN_STYLES.values():
        stored = json.loads(style.model_dump_json())
        assert StyleTemplate.model_validate(stored) == style

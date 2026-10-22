"""The creator relevance rules (spec 5c-2, G3a): pure, no I/O."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from thoth_control_plane.footage.creator import (
    CLOSE_CAP,
    CLOSE_DAYS,
    WEAK_BODY,
    body_length,
    closest,
    creator_query,
    enriched_text,
    verdict,
)


def test_the_constants_the_spec_pins() -> None:
    assert (WEAK_BODY, CLOSE_DAYS, CLOSE_CAP) == (15, 7, 3)


def test_creator_query_names_the_handle() -> None:
    assert creator_query("dominan.news") == "creator:@dominan.news"


def test_hashtags_read_as_words() -> None:
    assert enriched_text("", ["BBMLangka", "banjir_bali2026"]) == "BBM Langka banjir bali 2026"
    assert enriched_text("Antrean SPBU", ["viral"]) == "Antrean SPBU viral"


def test_body_length_ignores_tags_and_mentions() -> None:
    assert body_length("#fyp #viral @someone ") == 0
    assert body_length("Antrean panjang #bbm") == len("Antrean panjang")


def test_weak_caption_is_undecided_not_rejected() -> None:
    assert verdict(0.10, "#fyp #viral @someone", 0.36) == "undecided"
    assert verdict(0.10, "Liburan ke pantai bersama keluarga", 0.36) == "reject"
    assert verdict(0.40, "", 0.36) == "pass"
    assert verdict(0.36, "anything at all here", 0.36) == "pass"


def test_closest_keeps_three_within_seven_days_nearest_first() -> None:
    main = datetime(2026, 10, 10, tzinfo=UTC)
    posts = [main + timedelta(days=d) for d in (-8, -1, 2, 3, 6, 0.5)]
    kept, dropped = closest(posts, lambda p: p, main)
    assert kept == [main + timedelta(days=0.5), main - timedelta(days=1), main + timedelta(days=2)]
    assert dropped == [main - timedelta(days=8), main + timedelta(days=3), main + timedelta(days=6)]


def test_a_post_without_a_date_is_dropped() -> None:
    main = datetime(2026, 10, 10, tzinfo=UTC)
    kept, dropped = closest(["dated", "undated"], lambda p: main if p == "dated" else None, main)
    assert (kept, dropped) == (["dated"], ["undated"])


def test_no_main_date_keeps_no_undecided() -> None:
    kept, dropped = closest([1, 2], lambda p: None, None)
    assert (kept, dropped) == ([], [1, 2])

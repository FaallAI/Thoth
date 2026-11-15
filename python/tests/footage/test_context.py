"""The context card (footage library spec 2026-11-15, 4.1) and its matching (4.2-4.3)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tests.assembly.support import report as support_report
from thoth_control_plane.acquisition.models import ReportComment
from thoth_control_plane.footage.context import (
    CARD_PROMPT,
    REFINE_PROMPT,
    CardPerson,
    ContextCard,
    card_material,
    card_names,
    context_objects,
    context_reason,
    in_window,
    subject_names,
)

CARDS = Path(__file__).resolve().parents[1] / "fixtures" / "footage" / "context"


def card(name: str) -> ContextCard:
    return ContextCard.model_validate_json((CARDS / f"{name}.json").read_text(encoding="utf-8"))


def test_the_spike_cards_decode() -> None:
    mutant = card("mutant_card")
    assert [p.name for p in mutant.people] == ["Mutant", "Denny Sumargo"]
    assert "Densu" in mutant.people[1].aliases
    for name in ("rocky_card", "persib_card", "erio_card"):
        assert card(name).people


def test_nulls_and_junk_become_empty() -> None:
    empty = ContextCard.model_validate({"people": None, "queries": "x", "event": None})
    assert empty == ContextCard()
    assert ContextCard.model_validate({"model": "m", "people": [{"name": "A", "aliases": None}]})


def test_card_material_takes_the_top_comments_by_likes() -> None:
    main = support_report(
        url="https://www.tiktok.com/@akun/video/7499999999999999999",
        owner="akun",
        text="Mutant pengen diundang podcast Densu",
        media="none",
    )
    comments = [
        ReportComment(comment_id=f"77{n:017d}", author="u", text=f"komen {n}", likes=n)
        for n in range(30)
    ]
    main = main.model_copy(update={"comments": comments})
    material = json.loads(card_material(main, [{"name": "Mutant"}], "halo " * 1000))
    assert len(material["comments"]) == 25
    assert material["comments"][0] == {"text": "komen 29", "likes": 29}
    assert material["caption"] == "Mutant pengen diundang podcast Densu"
    assert material["figures"] == [{"name": "Mutant"}]
    assert len(material["transcript"]) == 1500


def _candidates() -> list[dict[str, object]]:
    return json.loads((CARDS / "mutant_candidates.json").read_text(encoding="utf-8"))


def test_short_and_marked_aliases_are_dropped() -> None:
    rocky = ContextCard(people=[CardPerson(name="Bung Rocky", aliases=["TG", "Rocky?"])])
    assert card_names(rocky) == ["bung rocky", "rocky"]


def test_a_name_matches_whole_words_only() -> None:
    sandy = ContextCard(people=[CardPerson(name="Sandy")])
    assert context_reason("Sandyakala di Bandung", sandy) == "story"
    assert context_reason("Sandy Walsh cetak gol", sandy) is None


def test_the_mutant_candidates_pass_on_the_card() -> None:
    mutant = card("mutant_card")
    mutant.people[0].aliases.append("Saiful")
    by_caption = {str(c["caption"]): c for c in _candidates()}
    for start in (
        "SAIFUL BUKAN MUTAN",
        "Momen Saeful temui Denny Sumargo di acara Urban Sneaker Society",
        "Detik-detik Pria Mengamuk di Depan Denny Sumargo hingga Tendang Kursi",
    ):
        matches = [text for text in by_caption if text.startswith(start)]
        assert matches, start
        assert context_reason(matches[0], mutant) is None, start
    sneakers = [str(c["caption"]) for c in _candidates() if c["query"] == "sneakers"]
    assert len(sneakers) == 13
    assert all(context_reason(text, mutant) == "story" for text in sneakers)


def test_an_unknown_time_stays_in_the_window() -> None:
    now = datetime(2026, 11, 14, tzinfo=UTC)
    main = "2026-11-10T11:16:32Z"
    assert in_window(None, main, now)
    assert not in_window("2026-10-01T00:00:00Z", main, now)
    assert in_window("2026-11-12T00:00:00Z", main, now)
    assert not in_window("2026-11-15T00:00:00Z", main, now)


def test_context_objects_mark_person_queries() -> None:
    mutant = card("mutant_card")
    person, place = context_objects(
        mutant, ["Mutant USS Denny Sumargo", "Urban Sneaker Society 2026 viral"]
    )
    assert person.person and person.visual.startswith("Mutant in person")
    assert person.query == "Mutant USS Denny Sumargo"
    assert not place.person and place.visual


def test_english_filler_words_are_not_event_terms() -> None:  # final review, Important 3
    rocky, mutant = card("rocky_card"), card("mutant_card")
    assert context_reason("The best street food and the night market", rocky) == "story"
    assert context_reason("Podcast terbaru di Jakarta bareng komika", mutant) == "story"
    assert context_reason("the sneaker drop event this weekend", mutant) == "story"
    assert context_reason("Keseruan Urban Sneaker Society hari kedua", mutant) is None


def test_spoken_words_are_single_lowercase_words() -> None:  # spec 9.2
    card = ContextCard.model_validate(
        {
            "spoken": [
                "Pedang",
                "marah",
                None,
                {"x": 1},
                "dua kata",
                "marah",
                *[f"w{i}" for i in range(20)],
            ]
        }
    )
    assert card.spoken[:2] == ["pedang", "marah"]
    assert "dua kata" not in card.spoken
    assert len(card.spoken) == 12


def test_an_old_card_decodes_without_spoken() -> None:
    assert ContextCard.model_validate({"event": "x"}).spoken == []


def test_subject_names_are_the_first_persons() -> None:
    card = ContextCard.model_validate(
        {"people": [{"name": "Mutant", "aliases": ["Saiful", "Ipul"]}, {"name": "Denny Sumargo"}]}
    )
    assert subject_names(card) == ["mutant", "saiful", "ipul"]  # longest first, stable
    assert subject_names(ContextCard()) == []


def test_the_prompts_ask_for_the_subject_first_and_spoken_words() -> None:
    assert '"spoken"' in CARD_PROMPT
    assert "people[0]" in CARD_PROMPT
    assert "only in comments" in CARD_PROMPT
    assert "people[0]" in REFINE_PROMPT

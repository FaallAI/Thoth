"""The context card (footage library spec 2026-11-15, 4.1) and its matching (4.2-4.3)."""

from __future__ import annotations

import json
from pathlib import Path

from tests.assembly.support import report as support_report
from thoth_control_plane.acquisition.models import ReportComment
from thoth_control_plane.footage.context import ContextCard, card_material

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

"""The Mutant run (wf_4c7961fc…, stage1 2026-11-14) replayed under the context gate, and the
production wiring of the context path (footage library spec 2026-11-15, section 5)."""

from __future__ import annotations

import json
from pathlib import Path

from thoth_control_plane.footage.context import ContextCard, context_reason

CONTEXT = Path(__file__).resolve().parents[1] / "fixtures" / "footage" / "context"


def test_the_mutant_run_replays_under_the_context_gate() -> None:
    card = ContextCard.model_validate_json((CONTEXT / "mutant_card.json").read_text("utf-8"))
    card.people[0].aliases.append("Saiful")
    rows = json.loads((CONTEXT / "mutant_candidates.json").read_text("utf-8"))
    passed = {
        r["caption"]
        for r in rows
        if context_reason(f"{r['caption']} {r['owner_handle']}", card) is None
    }
    for start in (
        "SAIFUL BUKAN MUTAN",
        "Momen Saeful temui Denny Sumargo",
        "Detik-detik Pria Mengamuk di Depan Denny Sumargo",
    ):
        assert any(text.startswith(start) for text in passed), start
    sneakers = [r for r in rows if r["query"] == "sneakers"]
    assert len(sneakers) == 13
    assert not any(r["caption"] in passed for r in sneakers)
    travel = [r for r in rows if r["query"] == "creator:@jnrksn" and "Bali" in r["caption"]]
    assert travel and not any(r["caption"] in passed for r in travel)


def test_production_wiring_builds_the_context_ports(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from thoth_control_plane.activities.footage import context_ports
    from thoth_control_plane.footage.adapters.captions import YtDlpCaptionFetcher
    from thoth_control_plane.footage.adapters.context_model import OpenRouterCardModel
    from thoth_control_plane.infrastructure.media_store import LocalMediaStore

    settings = SimpleNamespace(
        THOTH_FOOTAGE_CARD_MODEL="google/gemini-3.1-flash-lite",
        THOTH_FOOTAGE_QUERY_MODEL="deepseek/deepseek-v4-flash-0731",
    )
    ports = context_ports(settings, "key", LocalMediaStore(tmp_path))  # type: ignore[arg-type]
    assert isinstance(ports["card"], OpenRouterCardModel)
    assert ports["card"]._models == [
        "google/gemini-3.1-flash-lite",
        "deepseek/deepseek-v4-flash-0731",
    ]
    assert isinstance(ports["captions_text"], YtDlpCaptionFetcher)
    assert callable(ports["library_media"])

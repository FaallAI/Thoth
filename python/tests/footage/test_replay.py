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
    ):
        assert any(text.startswith(start) for text in passed), start
    # A news recap naming only Denny Sumargo is off the story (spec 10.12, revision 1).
    assert not any(text.startswith("Detik-detik Pria Mengamuk") for text in passed)
    sneakers = [r for r in rows if r["query"] == "sneakers"]
    assert len(sneakers) == 13
    assert not any(r["caption"] in passed for r in sneakers)
    travel = [r for r in rows if r["query"] == "creator:@jnrksn" and "Bali" in r["caption"]]
    assert travel and not any(r["caption"] in passed for r in travel)


# Run wf_18344b47 (stage1 2026-11-26): Ernest Prakasa's monologue on FFI 2026. Under the old
# English card every caption below was rejected "story"; the commentary card admits them.
FFI_ON_STORY = (
    "Dalam euforia para pemenang Piala Citra FFI 2026",
    "Sejumlah Sineas Gunakan Panggung FFI 2026",
    "Respons Fadli Zon seusai Dikritik",
    "Direktur film,musik, Dan seni kementerian kebudayaan,Irini Dewi Wanti",
    "Produser film Para Perasuk, Siera Tamihardja",
    "Malam puncak Festival Film Indonesia (FFI) 2026",
    "Malam penganugerahan Piala Citra",
    "Menang Piala Citra! Produser Film Para Perasuk",
    "Sentilan Keras Siera Tamihardja untuk Fadli Zon",
)
FFI_OFF_STORY = (
    "Kekuatan Musik Indonesia",  # Irini Dewi Wanti on music, August 2026
    "TERNYATA LAURA BASUKI",
    "COACH JUSTIN",
    "JUS TALK #603",  # "FFI" alone
    "Gara-gara Warisan",
    "Penjelasan Ending",
)


def test_the_ffi_commentary_run_replays_under_the_commentary_card() -> None:
    card = ContextCard.model_validate_json((CONTEXT / "ffi_card.json").read_text("utf-8"))
    assert card.main_kind == "commentary"
    rows = json.loads((CONTEXT / "ffi_candidates.json").read_text("utf-8"))

    def verdicts(part: str) -> list[bool]:
        found = [r for r in rows if part in r["caption"]]
        assert found, part
        return [context_reason(f"{r['caption']} {r['owner_handle']}", card) is None for r in found]

    assert [s for s in FFI_ON_STORY if not all(verdicts(s))] == []
    assert [s for s in FFI_OFF_STORY if any(verdicts(s))] == []


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

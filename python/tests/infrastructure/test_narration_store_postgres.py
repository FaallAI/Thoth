"""Narrations, narration presets and the SFX library on the migrated schema (migration 0027)."""

from __future__ import annotations

import asyncio

import pytest

from tests.postgres_support import DATABASE_URL, empty_tables, needs_postgres, reset_schema
from thoth_control_plane.domain.narration import (
    NarrationInProgress,
    NarrationPreset,
    NarrationPresetConflict,
    NarrationScript,
    ScriptBeat,
    VoiceEstimate,
)
from thoth_control_plane.infrastructure.narration_store import NarrationStore

pytestmark = needs_postgres


@pytest.fixture(scope="module")
def migrated() -> None:
    reset_schema()


@pytest.fixture
def store(migrated: None) -> NarrationStore:
    empty_tables()
    return NarrationStore(DATABASE_URL)


def run(awaitable):  # type: ignore[no-untyped-def]
    return asyncio.run(awaitable)


def test_a_draft_holds_one_unfinished_narration_at_a_time(store: NarrationStore) -> None:
    run(store.start("project_a", "edoc_1", "narration/edoc_1/1", NarrationPreset()))
    with pytest.raises(NarrationInProgress):
        run(store.start("project_a", "edoc_1", "narration/edoc_1/2", NarrationPreset()))

    run(store.set_status("edoc_1", "failed", failure_code="voice_not_configured"))
    again = run(store.start("project_a", "edoc_1", "narration/edoc_1/2", NarrationPreset()))
    assert (again.status, again.workflow_id, again.failure_code) == (
        "transcribing",
        "narration/edoc_1/2",
        None,
    )


def test_a_narration_is_invisible_to_another_project(store: NarrationStore) -> None:
    run(store.start("project_a", "edoc_1", "narration/edoc_1/1", NarrationPreset()))
    assert run(store.get("project_b", "edoc_1")) is None
    assert run(store.get("project_a", "edoc_1")) is not None


def test_the_script_estimate_and_stale_beats_round_trip(store: NarrationStore) -> None:
    run(store.start("project_a", "edoc_1", "narration/edoc_1/1", NarrationPreset()))
    script = NarrationScript(beats=[ScriptBeat(beat="main", text="Halo")], sfx_cues=[])
    estimate = VoiceEstimate(characters=4, provider="elevenlabs", voice_id="v", usd=None)
    run(store.set_script("edoc_1", script, estimate, {"main": ["Budi"]}))
    run(store.mark_stale("edoc_1", "main"))
    run(store.mark_stale("edoc_1", "main"))

    state = run(store.get("project_a", "edoc_1"))
    assert state.status == "awaiting_approval"
    assert (state.script, state.estimate, state.unsupported) == (
        script,
        estimate,
        {"main": ["Budi"]},
    )
    assert state.stale_beats == ["main"]
    run(store.clear_stale("edoc_1", "main"))
    assert run(store.get("project_a", "edoc_1")).stale_beats == []


def test_a_preset_defaults_then_saves_with_its_revision(store: NarrationStore) -> None:
    first = run(store.get_preset("project_a"))
    assert (first.preset, first.revision) == (NarrationPreset(), 0)

    saved = run(store.save_preset("project_a", NarrationPreset(target_seconds=30), 0))
    assert (saved.preset.target_seconds, saved.revision) == (30, 1)
    with pytest.raises(NarrationPresetConflict):
        run(store.save_preset("project_a", NarrationPreset(), 0))


def test_a_claim_moves_the_status_once(store: NarrationStore) -> None:
    run(store.start("project_a", "edoc_1", "narration/edoc_1/1", NarrationPreset()))
    run(store.set_status("edoc_1", "awaiting_approval"))

    assert run(store.claim("edoc_1", {"awaiting_approval"}, "voicing")) is True
    assert run(store.claim("edoc_1", {"awaiting_approval"}, "voicing")) is False
    assert run(store.get("project_a", "edoc_1")).status == "voicing"


# Style templates, final review (2026-11-10): a style's undo brings the earlier narration back.
def _completed(store: NarrationStore, workflow_id: str, text: str) -> None:
    run(store.start("project_001", "edoc_1", workflow_id, NarrationPreset()))
    run(
        store.set_script(
            "edoc_1",
            NarrationScript.model_validate(
                {"beats": [{"beat": "main", "text": text}], "sfx_cues": []}
            ),
            VoiceEstimate(characters=4, provider="elevenlabs", voice_id="v", usd=None),
            {},
        )
    )
    run(store.set_status("edoc_1", "completed"))


def test_a_restart_keeps_the_completed_narration_to_restore(store: NarrationStore) -> None:
    _completed(store, "narration/edoc_1/1", "Narasi lama.")
    run(store.start("project_001", "edoc_1", "narration/edoc_1/2", NarrationPreset()))
    assert run(store.restore_previous("edoc_1")) is True
    state = run(store.get("project_001", "edoc_1"))
    assert state is not None
    assert (state.status, state.workflow_id) == ("completed", "narration/edoc_1/1")
    assert state.script is not None and state.script.beats[0].text == "Narasi lama."
    assert run(store.restore_previous("edoc_1")) is False


def test_a_cancelled_workflow_cannot_close_a_restored_narration(store: NarrationStore) -> None:
    _completed(store, "narration/edoc_1/1", "Narasi lama.")
    run(store.start("project_001", "edoc_1", "narration/edoc_1/2", NarrationPreset()))
    run(store.restore_previous("edoc_1"))
    run(store.close("edoc_1", "narration/edoc_1/2", "cancelled"))
    state = run(store.get("project_001", "edoc_1"))
    assert state is not None and state.status == "completed"
    run(store.close("edoc_1", "narration/edoc_1/1", "failed", failure_code="narration_failed"))
    assert run(store.get("project_001", "edoc_1")).status == "failed"


def test_a_scripts_title_card_is_kept_until_the_next_narration(store: NarrationStore) -> None:
    # Deferred minor (2026-11-10): the cut preview reads the title card the script step found.
    run(store.start("project_001", "edoc_1", "narration/edoc_1/1", NarrationPreset()))
    run(
        store.set_script(
            "edoc_1",
            NarrationScript.model_validate(
                {"beats": [{"beat": "main", "text": "Satu."}], "sfx_cues": []}
            ),
            VoiceEstimate(characters=5, provider="elevenlabs", voice_id="v", usd=None),
            {},
            intro_frames=27,
        )
    )
    assert run(store.get_intro_frames("edoc_1")) == 27
    run(store.set_status("edoc_1", "completed"))
    run(store.start("project_001", "edoc_1", "narration/edoc_1/2", NarrationPreset()))
    assert run(store.get_intro_frames("edoc_1")) is None

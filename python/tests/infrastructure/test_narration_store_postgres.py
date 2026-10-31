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
    SfxEntry,
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


def test_an_sfx_upsert_is_idempotent_by_checksum(store: NarrationStore) -> None:
    entry = SfxEntry(
        sfx_id="whoosh",
        file_name="whoosh.mp3",
        location="sfx/abc.mp3",
        checksum="sha256:abc",
        duration_seconds=1.2,
        labels={"licence": "CC0-1.0"},
    )
    assert run(store.upsert_sfx(entry)) is True
    assert run(store.upsert_sfx(entry)) is False
    assert run(store.list_sfx()) == [entry]


def test_a_claim_moves_the_status_once(store: NarrationStore) -> None:
    run(store.start("project_a", "edoc_1", "narration/edoc_1/1", NarrationPreset()))
    run(store.set_status("edoc_1", "awaiting_approval"))

    assert run(store.claim("edoc_1", {"awaiting_approval"}, "voicing")) is True
    assert run(store.claim("edoc_1", {"awaiting_approval"}, "voicing")) is False
    assert run(store.get("project_a", "edoc_1")).status == "voicing"


def test_a_changed_file_replaces_its_library_entry(store: NarrationStore) -> None:
    first = SfxEntry(
        sfx_id="whoosh",
        file_name="whoosh.mp3",
        location="sfx/a.mp3",
        checksum="sha256:" + "a" * 64,
        duration_seconds=1.0,
        labels={"licence": "CC0-1.0"},
    )
    changed = first.model_copy(update={"location": "sfx/b.mp3", "checksum": "sha256:" + "b" * 64})
    assert run(store.upsert_sfx(first)) is True
    assert run(store.upsert_sfx(changed)) is True
    assert run(store.list_sfx()) == [changed]

"""The narration routes: start, read, decide, edit a beat, re-voice, the preset, the SFX library,
and the editing lock (Task 9)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.api.open_projects import OPEN_PROJECTS
from tests.api.test_edit_documents import MemoryEditDocumentRepository
from tests.domain.edit_document_v2_fixtures import document_with_every_clip_kind
from thoth_control_plane.api import create_app
from thoth_control_plane.application.narrations import NarrationService
from thoth_control_plane.config import Settings
from thoth_control_plane.domain.edit_document_v2 import EditDocumentV2
from thoth_control_plane.domain.narration import (
    ACTIVE_STATUSES,
    NarrationInProgress,
    NarrationPreset,
    NarrationPresetConflict,
    NarrationScript,
    NarrationState,
    ScriptBeat,
    SfxEntry,
    StoredPreset,
    VoiceEstimate,
)

pytestmark = pytest.mark.asyncio
AUTH = {"Authorization": "Bearer test-key"}
DOC = "/api/v1/projects/project_001/edit-documents/edoc_abc123"


class Store:
    def __init__(self) -> None:
        self.state: NarrationState | None = None
        self.preset = StoredPreset(preset=NarrationPreset(), revision=0)

    async def get(self, project_id: str, document_id: str) -> NarrationState | None:
        return self.state if project_id == "project_001" else None

    async def start(
        self, project_id: str, document_id: str, workflow_id: str, preset: Any
    ) -> NarrationState:
        if self.state is not None and self.state.status in ACTIVE_STATUSES:
            raise NarrationInProgress()
        self.state = NarrationState(
            document_id=document_id, workflow_id=workflow_id, status="transcribing"
        )
        return self.state

    async def set_status(
        self, document_id: str, status: str, *, failure_code: str | None = None
    ) -> None:
        assert self.state is not None
        self.state = self.state.model_copy(update={"status": status, "failure_code": failure_code})

    async def claim(self, document_id: str, expected: set[str], status: str) -> bool:
        if self.state is None or self.state.status not in expected:
            return False
        self.state = self.state.model_copy(update={"status": status})
        return True

    async def set_beat_text(self, document_id: str, beat: str, text: str) -> NarrationScript:
        assert self.state is not None and self.state.script is not None
        script = NarrationScript(
            beats=[
                ScriptBeat(beat=b.beat, text=text if b.beat == beat else b.text)
                for b in self.state.script.beats
            ]
        )
        self.state = self.state.model_copy(update={"script": script, "stale_beats": [beat]})
        return script

    async def get_preset(self, project_id: str) -> StoredPreset:
        return self.preset

    async def save_preset(
        self, project_id: str, preset: NarrationPreset, base_revision: int
    ) -> StoredPreset:
        if base_revision != self.preset.revision:
            raise NarrationPresetConflict()
        self.preset = StoredPreset(preset=preset, revision=base_revision + 1)
        return self.preset

    async def list_sfx(self) -> list[SfxEntry]:
        return [
            SfxEntry(
                sfx_id="whoosh",
                file_name="whoosh.mp3",
                location="sfx/secret-key.mp3",
                checksum="sha256:" + "a" * 64,
                duration_seconds=1.0,
                labels={"licence": "CC0-1.0"},
            )
        ]


class Gateway:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.decisions: list[Any] = []
        self.revoiced: list[str] = []
        self.cancelled: list[str] = []
        self.gone = False
        self.start_fails = False

    async def start(self, workflow_id: str, step: Any) -> None:
        if self.start_fails:
            from thoth_control_plane.application.narrations import NarrationUnavailable

            raise NarrationUnavailable()
        self.started.append(workflow_id)

    async def decide(self, workflow_id: str, decision: Any) -> None:
        self.decisions.append(decision)

    async def revoice(self, step: Any) -> None:
        self.revoiced.append(step.beat)

    async def cancel(self, workflow_id: str) -> None:
        if self.gone:
            from thoth_control_plane.application.narrations import NarrationUnavailable

            raise NarrationUnavailable()
        self.cancelled.append(workflow_id)


class Preferences:
    def __init__(self, configured: bool = True) -> None:
        self.configured = configured

    async def get_preference(self, project_id: str, stage_id: str) -> object | None:
        return object() if self.configured and stage_id == "narration_script" else None


def build(
    store: Store, gateway: Gateway, *, run: str | None = "wf_run_1", configured: bool = True
) -> httpx.AsyncClient:
    repository = MemoryEditDocumentRepository()
    repository.documents[("project_001", "edoc_abc123")] = EditDocumentV2.model_validate(
        document_with_every_clip_kind()
    )
    app = create_app(
        Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"),
        None,
        repository,
        project_store=OPEN_PROJECTS,
    )

    async def source_run(project_id: str, document_id: str) -> str | None:
        return run

    app.state.narration_service = NarrationService(
        store=store,
        documents=app.state.edit_document_service,
        source_run=source_run,
        preferences=Preferences(configured),
        gateway=gateway,
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def code(response: httpx.Response) -> Any:
    detail = response.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else detail


async def test_starting_a_narration_runs_one_workflow_and_refuses_a_second() -> None:
    store, gateway = Store(), Gateway()
    async with build(store, gateway) as api:
        first = await api.post(f"{DOC}/narration", headers=AUTH)
        second = await api.post(f"{DOC}/narration", headers=AUTH)

    assert first.status_code == 202 and first.json()["status"] == "transcribing"
    assert gateway.started == ["narration/edoc_abc123/1"]
    assert (second.status_code, code(second)) == (409, "narration_in_progress")


@pytest.mark.parametrize(
    ("run", "configured", "expected"),
    [(None, True, "narration_not_available"), ("wf_run_1", False, "prompt_not_configured")],
)
async def test_a_draft_that_cannot_be_narrated_spends_nothing(
    run: str | None, configured: bool, expected: str
) -> None:
    store, gateway = Store(), Gateway()
    async with build(store, gateway, run=run, configured=configured) as api:
        response = await api.post(f"{DOC}/narration", headers=AUTH)

    assert (response.status_code, code(response)) == (409, expected)
    assert gateway.started == [] and store.state is None


async def test_the_estimate_shows_while_the_script_awaits_approval_and_one_decision_is_sent() -> (
    None
):
    store, gateway = Store(), Gateway()
    script = NarrationScript(beats=[ScriptBeat(beat="main", text="Halo")])
    store.state = NarrationState(
        document_id="edoc_abc123",
        workflow_id="narration/edoc_abc123/1",
        status="awaiting_approval",
        script=script,
        estimate=VoiceEstimate(characters=4, provider="elevenlabs", voice_id="v"),
    )
    async with build(store, gateway) as api:
        read = await api.get(f"{DOC}/narration", headers=AUTH)
        decided = await api.post(
            f"{DOC}/narration/decision", json={"decision": "approve"}, headers=AUTH
        )
        store.state = store.state.model_copy(update={"status": "voicing"})
        late = await api.post(
            f"{DOC}/narration/decision", json={"decision": "approve"}, headers=AUTH
        )

    assert read.json()["estimate"]["characters"] == 4
    assert decided.status_code == 202 and len(gateway.decisions) == 1
    assert (late.status_code, code(late)) == (409, "narration_not_awaiting_approval")


async def test_a_completed_beat_can_be_edited_and_then_re_voiced() -> None:
    store, gateway = Store(), Gateway()
    store.state = NarrationState(
        document_id="edoc_abc123",
        workflow_id="narration/edoc_abc123/1",
        status="completed",
        script=NarrationScript(beats=[ScriptBeat(beat="main", text="Halo")]),
    )
    async with build(store, gateway) as api:
        early = await api.post(f"{DOC}/narration/beats/main/revoice", headers=AUTH)
        edited = await api.put(
            f"{DOC}/narration/beats/main", json={"text": "Halo semua"}, headers=AUTH
        )
        revoiced = await api.post(f"{DOC}/narration/beats/main/revoice", headers=AUTH)

    assert (early.status_code, code(early)) == (409, "beat_not_stale")
    assert edited.status_code == 200 and edited.json()["beats"][0]["text"] == "Halo semua"
    assert revoiced.status_code == 202 and gateway.revoiced == ["main"]


async def test_the_draft_is_locked_while_the_narration_runs() -> None:
    store, gateway = Store(), Gateway()
    store.state = NarrationState(
        document_id="edoc_abc123", workflow_id="narration/edoc_abc123/1", status="voicing"
    )
    patch = {
        "base_revision": 1,
        "operations": [
            {
                "kind": "replace_text",
                "operation_id": "op_1",
                "clip_id": "clip_001",
                "field": "heading",
                "value": "Baru",
            }
        ],
    }
    async with build(store, gateway) as api:
        locked = await api.patch(DOC, json=patch, headers=AUTH)
        store.state = store.state.model_copy(update={"status": "completed"})
        open_again = await api.patch(DOC, json=patch, headers=AUTH)

    assert (locked.status_code, code(locked)) == (409, "narration_in_progress")
    assert open_again.status_code == 200


async def test_another_projects_narration_is_not_found() -> None:
    store, gateway = Store(), Gateway()
    store.state = NarrationState(document_id="edoc_abc123", workflow_id="w", status="completed")
    async with build(store, gateway) as api:
        response = await api.get(
            "/api/v1/projects/project_999/edit-documents/edoc_abc123/narration", headers=AUTH
        )
    assert response.status_code in {403, 404}


async def test_the_preset_saves_with_its_revision_and_the_sfx_library_hides_locations() -> None:
    store, gateway = Store(), Gateway()
    async with build(store, gateway) as api:
        read = await api.get("/api/v1/projects/project_001/narration-preset", headers=AUTH)
        saved = await api.put(
            "/api/v1/projects/project_001/narration-preset",
            json={"base_revision": 0, "preset": {**read.json()["preset"], "target_seconds": 30}},
            headers=AUTH,
        )
        stale = await api.put(
            "/api/v1/projects/project_001/narration-preset",
            json={"base_revision": 0, "preset": read.json()["preset"]},
            headers=AUTH,
        )
        sfx = await api.get("/api/v1/sfx", headers=AUTH)

    assert read.json()["revision"] == 0 and saved.json()["revision"] == 1
    assert (stale.status_code, code(stale)) == (409, "narration_preset_conflict")
    assert sfx.json() == [
        {
            "sfx_id": "whoosh",
            "file_name": "whoosh.mp3",
            "duration_seconds": 1.0,
            "labels": {"licence": "CC0-1.0"},
        }
    ]


# --- Final review fixes (C1, I2, I4, re-graded minor 2) ---


async def test_a_workflow_that_never_starts_leaves_the_draft_editable() -> None:
    store, gateway = Store(), Gateway()
    gateway.start_fails = True
    async with build(store, gateway) as api:
        response = await api.post(f"{DOC}/narration", headers=AUTH)

    assert (response.status_code, code(response)) == (503, "narration_unavailable")
    assert store.state is not None and (store.state.status, store.state.failure_code) == (
        "failed",
        "narration_unavailable",
    )


async def test_cancel_signals_a_running_narration_or_closes_one_whose_workflow_is_gone() -> None:
    store, gateway = Store(), Gateway()
    store.state = NarrationState(
        document_id="edoc_abc123", workflow_id="narration/edoc_abc123/1", status="awaiting_approval"
    )
    async with build(store, gateway) as api:
        first = await api.post(f"{DOC}/narration/cancel", headers=AUTH)
        gateway.gone = True
        second = await api.post(f"{DOC}/narration/cancel", headers=AUTH)
        closed = store.state.status
        store.state = store.state.model_copy(update={"status": "completed"})
        idle = await api.post(f"{DOC}/narration/cancel", headers=AUTH)

    assert first.status_code == 202 and gateway.cancelled == ["narration/edoc_abc123/1"]
    assert second.status_code == 202 and closed == "cancelled"
    assert (idle.status_code, code(idle)) == (409, "narration_not_active")


async def test_a_decision_is_taken_once_and_the_answer_shows_the_next_step() -> None:
    store, gateway = Store(), Gateway()
    store.state = NarrationState(
        document_id="edoc_abc123", workflow_id="narration/edoc_abc123/1", status="awaiting_approval"
    )
    async with build(store, gateway) as api:
        rejected = await api.post(
            f"{DOC}/narration/decision", json={"decision": "reject"}, headers=AUTH
        )
        again = await api.post(
            f"{DOC}/narration/decision", json={"decision": "approve"}, headers=AUTH
        )

    assert rejected.json()["status"] == "scripting"
    assert (again.status_code, code(again)) == (409, "narration_not_awaiting_approval")
    assert len(gateway.decisions) == 1


async def test_a_re_voice_runs_once_and_locks_the_draft_while_it_runs() -> None:
    store, gateway = Store(), Gateway()
    store.state = NarrationState(
        document_id="edoc_abc123",
        workflow_id="narration/edoc_abc123/1",
        status="completed",
        stale_beats=["main"],
        script=NarrationScript(beats=[ScriptBeat(beat="main", text="Halo")]),
    )
    async with build(store, gateway) as api:
        first = await api.post(f"{DOC}/narration/beats/main/revoice", headers=AUTH)
        second = await api.post(f"{DOC}/narration/beats/main/revoice", headers=AUTH)

    assert first.status_code == 202 and first.json()["status"] == "voicing"
    assert (second.status_code, code(second)) == (409, "beat_not_stale")
    assert gateway.revoiced == ["main"]


# --- Deferred minors fixed before push ---


async def test_a_draft_that_already_has_a_narration_is_not_narrated_again() -> None:
    store, gateway = Store(), Gateway()
    store.state = NarrationState(
        document_id="edoc_abc123", workflow_id="narration/edoc_abc123/1", status="completed"
    )
    async with build(store, gateway) as api:
        response = await api.post(f"{DOC}/narration", headers=AUTH)
    assert (response.status_code, code(response)) == (409, "narration_exists")
    assert gateway.started == []


async def test_a_line_cannot_be_edited_while_its_voice_is_being_made() -> None:
    store, gateway = Store(), Gateway()
    store.state = NarrationState(
        document_id="edoc_abc123",
        workflow_id="narration/edoc_abc123/1",
        status="voicing",
        script=NarrationScript(beats=[ScriptBeat(beat="main", text="Halo")]),
    )
    async with build(store, gateway) as api:
        response = await api.put(f"{DOC}/narration/beats/main", json={"text": "Baru"}, headers=AUTH)
    assert (response.status_code, code(response)) == (409, "narration_not_completed")


async def test_store_outages_answer_unavailable_not_a_missing_run() -> None:
    from thoth_control_plane.application.edit_documents import EditorUnavailable

    store, gateway = Store(), Gateway()
    client = build(store, gateway)
    service = client._transport.app.state.narration_service  # type: ignore[attr-defined]

    async def down(project_id: str, document_id: str) -> str | None:
        raise EditorUnavailable()

    service._source_run = down
    async with client as api:
        response = await api.post(f"{DOC}/narration", headers=AUTH)
    assert (response.status_code, code(response)) == (503, "narration_unavailable")

    class BrokenPreferences:
        async def get_preference(self, project_id: str, stage_id: str) -> object:
            raise RuntimeError("prompt store down")

    async def present(project_id: str, document_id: str) -> str | None:
        return "wf_run_1"

    service._source_run = present
    service._preferences = BrokenPreferences()
    async with build(store, gateway) as api2:
        api2._transport.app.state.narration_service = service  # type: ignore[attr-defined]
        response = await api2.post(f"{DOC}/narration", headers=AUTH)
    assert (response.status_code, code(response)) == (503, "narration_unavailable")


async def test_resolving_an_import_item_waits_for_the_narration() -> None:
    store, gateway = Store(), Gateway()
    store.state = NarrationState(
        document_id="edoc_abc123", workflow_id="narration/edoc_abc123/1", status="writing"
    )
    async with build(store, gateway) as api:
        response = await api.post(
            "/api/v1/projects/project_001/studio-imports/documents/edoc_abc123/items/main/resolve",
            json={"base_revision": 1, "decision": {"kind": "exclude"}},
            headers=AUTH,
        )
    assert (response.status_code, code(response)) == (409, "narration_in_progress")


async def test_a_library_sfx_can_be_added_to_the_draft_project() -> None:
    from thoth_control_plane.domain.editor_assets import EditorAsset

    store, gateway = Store(), Gateway()
    client = build(store, gateway)
    service = client._transport.app.state.narration_service  # type: ignore[attr-defined]
    added: list[tuple[str, str]] = []

    class Assets:
        async def ensure_project_asset(self, project_id: str, entry: SfxEntry) -> EditorAsset:
            added.append((project_id, entry.sfx_id))
            return EditorAsset(
                asset_id="asset_sfx",
                project_id=project_id,
                kind="audio",
                media_type="audio/mpeg",
                validation_state="ready",
                checksum=entry.checksum,
                has_audio=True,
                duration_in_frames=30,
            )

    service._sfx_assets = Assets()
    async with client as api:
        response = await api.post("/api/v1/projects/project_001/sfx/whoosh/asset", headers=AUTH)
        missing = await api.post("/api/v1/projects/project_001/sfx/airhorn/asset", headers=AUTH)
    assert response.status_code == 200 and response.json()["asset_id"] == "asset_sfx"
    assert added == [("project_001", "whoosh")] and missing.status_code == 404

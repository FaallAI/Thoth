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

    async def start(self, workflow_id: str, step: Any) -> None:
        self.started.append(workflow_id)

    async def decide(self, workflow_id: str, decision: Any) -> None:
        self.decisions.append(decision)

    async def revoice(self, step: Any) -> None:
        self.revoiced.append(step.beat)


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

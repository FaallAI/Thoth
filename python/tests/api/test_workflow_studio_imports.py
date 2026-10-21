"""The workflow-to-Studio routes: read-only inspection, the import, replay, and each refusal."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.api.open_projects import OPEN_PROJECTS
from tests.api.test_edit_documents import MemoryEditDocumentRepository
from tests.application.test_workflow_studio_imports import (
    WF,
    AttachingImports,
    MemoryAssets,
    MemoryReports,
    MemoryRuns,
    Probe,
    content_set_bytes,
    seed_media,
    stored_run,
)
from thoth_control_plane.api import create_app
from thoth_control_plane.assembly.studio import workflow_source_key
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure.media_store import build_media_store

AUTH = {"Authorization": "Bearer test-key"}
PATH = f"/api/v1/projects/project_001/workflows/{WF}/studio-import"
DEFAULT = object()


def client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    runs: MemoryRuns | None = None,
    reports: Any = DEFAULT,
) -> httpx.AsyncClient:
    probe = Probe()

    async def probe_media(_ffprobe: str, source: Any) -> dict[str, Any]:
        return await probe(source)

    monkeypatch.setattr("thoth_control_plane.api.app.probe_media", probe_media)
    (tmp_path / "root").mkdir(exist_ok=True)
    settings = Settings(
        THOTH_CONTROL_PLANE_API_KEY="test-key", THOTH_CONTROL_PLANE_ARTIFACT_ROOT=tmp_path / "root"
    )
    seed_media(build_media_store(settings), tmp_path)
    app = create_app(
        settings,
        None,
        MemoryEditDocumentRepository(),
        editor_asset_repository=MemoryAssets(),
        studio_import_repository=AttachingImports(),
        project_store=OPEN_PROJECTS,
        workflow_run_store=runs or MemoryRuns(stored_run()),
        report_store=MemoryReports(content_set_bytes()) if reports is DEFAULT else reports,
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def code_of(response: httpx.Response) -> str | None:
    detail = response.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else None


async def test_inspection_is_read_only_and_then_lists_the_draft(tmp_path, monkeypatch) -> None:
    runs = MemoryRuns(stored_run())
    async with client(tmp_path, monkeypatch, runs=runs) as api:
        found = await api.get(PATH, headers=AUTH)
        assert found.status_code == 200
        digest = hashlib.sha256(content_set_bytes()).hexdigest()
        assert found.json()["source_key"] == workflow_source_key(WF, digest)
        assert found.json()["drafts"] == []
        assert runs.get(WF).project_id is None

        opened = await api.post(PATH, headers={**AUTH, "Idempotency-Key": "open-1"})
        listed = await api.get(PATH, headers=AUTH)

    assert [draft["document_id"] for draft in listed.json()["drafts"]] == [
        opened.json()["draft"]["document_id"]
    ]


async def test_open_assigns_the_run_imports_and_replays(tmp_path, monkeypatch) -> None:
    runs = MemoryRuns(stored_run())
    async with client(tmp_path, monkeypatch, runs=runs) as api:
        headers = {**AUTH, "Idempotency-Key": "open-1"}
        opened = await api.post(PATH, headers=headers)
        replay = await api.post(PATH, headers=headers)

    assert opened.status_code == 201
    assert [(i["item_id"], i["outcome"]) for i in opened.json()["items"]] == [
        ("main_000", "copied"),
        ("footage_000", "copied"),
        ("footage_001", "copied"),
    ]
    assert runs.get(WF).project_id == "project_001"
    assert replay.status_code == 201
    assert replay.json()["draft"]["document_id"] == opened.json()["draft"]["document_id"]
    assert {i["outcome"] for i in replay.json()["items"]} == {"decided"}
    assert "reports/" not in opened.text and "uploads/" not in opened.text


CASES: list[tuple[Callable[[], Any], Callable[[], Any], int, str | None]] = [
    (lambda: MemoryRuns(), lambda: MemoryReports(content_set_bytes()), 404, None),
    (lambda: MemoryRuns(stored_run(actor_id="ws_other")), lambda: DEFAULT, 404, None),
    (
        lambda: MemoryRuns(stored_run(project_id="project_002")),
        lambda: DEFAULT,
        409,
        "workflow_in_other_project",
    ),
    (lambda: None, lambda: MemoryReports(None), 409, "content_set_unavailable"),
    (lambda: None, lambda: MemoryReports(b"{}"), 409, "content_set_invalid"),
    (lambda: None, lambda: None, 503, None),
]


@pytest.mark.parametrize(("runs", "reports", "status", "code"), CASES)
async def test_every_refusal_has_its_status_and_code(
    tmp_path, monkeypatch, runs, reports, status, code
) -> None:
    async with client(tmp_path, monkeypatch, runs=runs(), reports=reports()) as api:
        answers = [
            await api.get(PATH, headers=AUTH),
            await api.post(PATH, headers={**AUTH, "Idempotency-Key": "k-1"}),
        ]
    for answer in answers:
        assert (answer.status_code, code_of(answer)) == (status, code)


async def test_the_idempotency_key_is_required_and_checked(tmp_path, monkeypatch) -> None:
    async with client(tmp_path, monkeypatch) as api:
        missing = await api.post(PATH, headers=AUTH)
        unsafe = await api.post(PATH, headers={**AUTH, "Idempotency-Key": "not a key"})
    assert missing.status_code == 422
    assert (unsafe.status_code, code_of(unsafe)) == (422, "invalid_idempotency_key")
    assert "not a key" not in unsafe.text


async def test_the_routes_need_a_caller(tmp_path, monkeypatch) -> None:
    async with client(tmp_path, monkeypatch) as api:
        assert (await api.get(PATH)).status_code == 403
        assert (await api.post(PATH, headers={"Idempotency-Key": "k-1"})).status_code == 403

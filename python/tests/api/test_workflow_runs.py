"""Workflow runs per project: start, list, settle, move, and the expired-history fallback."""

import json
from datetime import UTC, datetime

import httpx
import pytest
import pytest_asyncio

from tests.sqlite_support import sqlite_engine
from thoth_control_plane.api import create_app
from thoth_control_plane.application import WorkflowNotReady
from thoth_control_plane.application.ports import RunClosed, RunExpired
from thoth_control_plane.config import Settings
from thoth_control_plane.domain import WorkflowSummary
from thoth_control_plane.infrastructure import run_models  # noqa: F401
from thoth_control_plane.infrastructure.project_store import ProjectStore
from thoth_control_plane.infrastructure.report_store import ReportStore
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.workflow_run_store import (
    StoredRun,
    WorkflowRunStore,
    WorkflowRunsUnavailable,
)

AUTH = {"Authorization": "Bearer test-key"}
REQUEST = {
    "source": {"url": "https://www.tiktok.com/@a/video/1", "intent": "identify_original"},
    "style": {"preset_id": "news-vertical"},
    "output": {"format": "vertical_video", "language": "id"},
    "review": {"require_publish_approval": True},
}
T_OLD = datetime(2026, 9, 1, tzinfo=UTC)


def old_run(workflow_id: str, project_id: str | None, *, expired: bool) -> StoredRun:
    return StoredRun(
        workflow_id=workflow_id,
        project_id=project_id,
        actor_type="user",
        actor_id="owner",
        display_url="https://x.test/v",
        platform="tiktok",
        status="unknown",
        history_expired=expired,
        summary=None,
        created_at=T_OLD,
        updated_at=T_OLD,
    )


@pytest.fixture
def stores():
    engine = sqlite_engine()
    Base.metadata.create_all(engine)
    return ProjectStore(engine), WorkflowRunStore(engine), ReportStore(engine)


def app_for(gateway, stores, settings: Settings | None = None):
    projects, runs, reports = stores
    return create_app(
        settings or Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"),
        gateway,
        project_store=projects,
        workflow_run_store=runs,
        report_store=reports,
    )


@pytest_asyncio.fixture
async def api(gateway, stores):
    transport = httpx.ASGITransport(app=app_for(gateway, stores))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def start(api, project_id: str, key: str = "k1"):
    return await api.post(
        f"/api/v1/projects/{project_id}/workflows",
        json=REQUEST,
        headers={**AUTH, "Idempotency-Key": key},
    )


@pytest.mark.asyncio
async def test_a_project_start_is_listed_under_its_project(api, stores) -> None:
    project = stores[0].create("News", "ws_bootstrap")
    assert (await start(api, project.project_id)).status_code == 202
    response = await api.get(f"/api/v1/projects/{project.project_id}/workflows", headers=AUTH)
    page = response.json()
    assert [r["workflow_id"] for r in page["items"]] == ["wf_001"]
    assert page["next_cursor"] is None


@pytest.mark.asyncio
async def test_an_unknown_project_never_starts(api, gateway) -> None:
    response = await start(api, "missing")
    assert response.status_code == 404
    assert response.json() == {"detail": "project_not_found"}
    assert gateway.workflows == {}


@pytest.mark.asyncio
async def test_the_legacy_start_is_unassigned_and_can_be_moved(api, stores) -> None:
    await api.post("/api/v1/workflows", json=REQUEST, headers={**AUTH, "Idempotency-Key": "k"})
    loose = (await api.get("/api/v1/workflows?unassigned=true", headers=AUTH)).json()["items"]
    assert [r["workflow_id"] for r in loose] == ["wf_001"]
    project = stores[0].create("News", "ws_bootstrap")
    moved = await api.patch(
        "/api/v1/workflows/wf_001", json={"project_id": project.project_id}, headers=AUTH
    )
    assert moved.status_code == 200
    assert moved.json()["project_id"] == project.project_id
    refused = await api.get("/api/v1/workflows?unassigned=false", headers=AUTH)
    assert refused.status_code == 422
    nowhere = await api.patch(
        "/api/v1/workflows/wf_001", json={"project_id": "missing"}, headers=AUTH
    )
    assert nowhere.status_code == 404


@pytest.mark.asyncio
async def test_a_retried_start_after_a_row_failure_lands_the_row(
    api, stores, gateway, monkeypatch
) -> None:
    project = stores[0].create("News", "ws_bootstrap")
    runs = stores[1]
    original = runs.record_start
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise WorkflowRunsUnavailable("workflow_runs_unavailable")
        return original(*args, **kwargs)

    monkeypatch.setattr(runs, "record_start", flaky)
    first = await start(api, project.project_id, "same")
    assert first.status_code == 503
    assert first.json() == {"detail": "workflow_runs_unavailable"}
    assert (await start(api, project.project_id, "same")).status_code == 202
    assert runs.get("wf_001") is not None
    assert list(gateway.workflows) == ["wf_001"]


@pytest.mark.asyncio
async def test_listing_settles_closed_and_expired_runs(api, stores, gateway) -> None:
    project = stores[0].create("News", "ws_bootstrap")
    await start(api, project.project_id)
    gateway.settlements["wf_001"] = RunClosed(None, "cancelled")
    listing = f"/api/v1/projects/{project.project_id}/workflows"
    item = (await api.get(listing, headers=AUTH)).json()["items"][0]
    assert item["status"] == "cancelled"
    stores[1].insert_missing(old_run("wf_old", project.project_id, expired=False))
    stores[2].put("reports/wf_old/source-report.json", "source_report", b"{}")
    gateway.settlements["wf_old"] = RunExpired()
    items = (await api.get(listing, headers=AUTH)).json()["items"]
    old = next(i for i in items if i["workflow_id"] == "wf_old")
    assert old["history_expired"] is True
    assert old["status"] == "unknown"
    assert old["artifact_count"] == 1


@pytest.mark.asyncio
async def test_a_temporal_outage_still_lists_the_stored_rows(api, stores, gateway) -> None:
    project = stores[0].create("News", "ws_bootstrap")
    await start(api, project.project_id)
    gateway.settle_error = WorkflowNotReady()
    response = await api.get(f"/api/v1/projects/{project.project_id}/workflows", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["items"][0]["status"] == "queued"


@pytest.mark.asyncio
async def test_an_expired_workflow_detail_answers_from_the_store(api, stores) -> None:
    stores[1].insert_missing(old_run("wf_old", None, expired=True))
    stores[2].put("reports/wf_old/source-report.json", "source_report", b"{}")
    body = (await api.get("/api/v1/workflows/wf_old", headers=AUTH)).json()
    assert body["history_expired"] is True
    assert body["status"] == "succeeded"
    assert [a["artifact_id"] for a in body["artifacts"]] == ["source_report"]
    report = await api.get("/api/v1/workflows/wf_old/artifacts/source_report", headers=AUTH)
    assert report.status_code == 200
    assert report.content == b"{}"


@pytest.mark.asyncio
async def test_listing_a_missing_project_is_404(api) -> None:
    response = await api.get("/api/v1/projects/missing/workflows", headers=AUTH)
    assert response.status_code == 404


def summary_with(artifacts: list[dict]) -> WorkflowSummary:
    return WorkflowSummary.model_validate_json(
        json.dumps(
            {
                "workflow_id": "wf_001",
                "status": "succeeded",
                "created_at": T_OLD.isoformat(),
                "updated_at": T_OLD.isoformat(),
                "source": {"display_url": "https://x.test/v", "platform": "tiktok"},
                "stages": [],
                "artifacts": artifacts,
            }
        )
    )


CLIP = {
    "artifact_id": "clip",
    "kind": "footage",
    "label": "Clip",
    "media_type": "video/mp4",
    "location": "reports/wf_001/footage/clip.mp4",
}
GONE = {**CLIP, "artifact_id": "gone", "location": "reports/wf_001/footage/gone.mp4"}


@pytest.mark.asyncio
async def test_media_artifacts_stream_from_the_store_with_ranges(gateway, stores, tmp_path) -> None:
    from thoth_control_plane.infrastructure.media_store import LocalMediaStore

    # The object lives only in the store, never under the (unmounted) artifact root.
    settings = Settings(
        THOTH_CONTROL_PLANE_API_KEY="test-key",
        THOTH_CONTROL_PLANE_ARTIFACT_ROOT=str(tmp_path / "artifact-root"),
    )
    clip = tmp_path / "store" / "reports" / "wf_001" / "footage" / "clip.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"0123456789")
    gateway.workflows["wf_001"] = summary_with([CLIP, GONE])
    app = app_for(gateway, stores, settings)
    app.state.media_store = LocalMediaStore(tmp_path / "store")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        whole = await client.get("/api/v1/workflows/wf_001/artifacts/clip", headers=AUTH)
        part = await client.get(
            "/api/v1/workflows/wf_001/artifacts/clip", headers={**AUTH, "Range": "bytes=2-4"}
        )
        missing = await client.get("/api/v1/workflows/wf_001/artifacts/gone", headers=AUTH)
    assert whole.status_code == 200
    assert whole.content == b"0123456789"
    assert 'filename="clip.mp4"' in whole.headers["content-disposition"]
    assert part.status_code == 206
    assert part.content == b"234"
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_a_media_store_outage_answers_503(gateway, stores, monkeypatch) -> None:
    from thoth_control_plane.infrastructure.media_store import MediaStoreUnavailable

    app = app_for(gateway, stores)

    def down(location):
        raise MediaStoreUnavailable("media_store_unavailable")

    monkeypatch.setattr(app.state.media_store, "size", down)
    gateway.workflows["wf_001"] = summary_with([CLIP])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/workflows/wf_001/artifacts/clip", headers=AUTH)
    assert response.status_code == 503


async def test_any_settle_failure_still_lists_the_stored_rows(api, stores, gateway) -> None:
    project = stores[0].create("News", "ws_bootstrap")
    await start(api, project.project_id)
    gateway.settle_error = RuntimeError("history payload no longer decodes")
    response = await api.get(f"/api/v1/projects/{project.project_id}/workflows", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["items"][0]["status"] == "queued"


async def test_a_slow_settle_is_bounded(api, stores, gateway, monkeypatch) -> None:
    import asyncio
    import time

    from thoth_control_plane.application import workflow_runs

    project = stores[0].create("News", "ws_bootstrap")
    await start(api, project.project_id)

    async def stalled(workflow_id):
        await asyncio.sleep(5)

    monkeypatch.setattr(gateway, "settle", stalled)
    monkeypatch.setattr(workflow_runs, "SETTLE_TIMEOUT_SECONDS", 0.05)
    began = time.monotonic()
    response = await api.get(f"/api/v1/projects/{project.project_id}/workflows", headers=AUTH)
    assert response.status_code == 200
    assert time.monotonic() - began < 2


async def test_a_malformed_cursor_is_a_client_error(api, stores) -> None:
    project = stores[0].create("News", "ws_bootstrap")
    response = await api.get(
        f"/api/v1/projects/{project.project_id}/workflows?cursor=not-a-cursor", headers=AUTH
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_cursor"}


async def test_an_expired_detail_keeps_a_known_status(api, stores) -> None:
    from dataclasses import replace

    failed = replace(old_run("wf_failed", None, expired=True), status="failed")
    stores[1].insert_missing(failed)
    stores[2].put("reports/wf_failed/source-report.json", "source_report", b"{}")
    body = (await api.get("/api/v1/workflows/wf_failed", headers=AUTH)).json()
    assert body["status"] == "failed"
    assert body["history_expired"] is True

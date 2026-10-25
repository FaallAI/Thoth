"""The steps endpoint over HTTP, and current_step inside the workflow detail (spec G3, D6)."""

import pytest
import pytest_asyncio
import httpx

from tests.sqlite_support import sqlite_engine
from thoth_control_plane.api import create_app
from thoth_control_plane.config import Settings
from thoth_control_plane.domain.models import StageSummary, WorkflowSummary
from thoth_control_plane.infrastructure import step_models  # noqa: F401  (registers the table)
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.step_store import StepStore
from thoth_control_plane.progress import StepRecord, StepScope

AUTH = {"Authorization": "Bearer test-key"}
REQUEST = {
    "source": {"url": "https://www.tiktok.com/@a/video/1", "intent": "identify_original"},
    "style": {"preset_id": "news-vertical"},
    "output": {"format": "vertical_video", "language": "id"},
    "review": {"require_publish_approval": True},
}


@pytest.fixture
def stores():
    engine = sqlite_engine()
    Base.metadata.create_all(engine)
    from thoth_control_plane.infrastructure import run_models  # noqa: F401  (workflow_runs rows)
    from thoth_control_plane.infrastructure.project_store import ProjectStore
    from thoth_control_plane.infrastructure.report_store import ReportStore
    from thoth_control_plane.infrastructure.workflow_run_store import WorkflowRunStore

    return ProjectStore(engine), WorkflowRunStore(engine), ReportStore(engine), StepStore(engine)


@pytest_asyncio.fixture
async def api(gateway, stores):
    projects, runs, reports, steps = stores
    app = create_app(
        Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"),
        gateway,
        project_store=projects,
        workflow_run_store=runs,
        report_store=reports,
        step_store=steps,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def record(code: str, *, kind: str = "info", n: int | None = None, total: int | None = None):
    from datetime import UTC, datetime

    return StepRecord(
        at=datetime(2026, 10, 25, 12, 0, tzinfo=UTC),
        kind=kind,
        code=code,
        n=n,
        total=total,
        params={"count": 2},
    )


@pytest.mark.asyncio
async def test_the_steps_page_serves_the_run_in_order(api, stores) -> None:
    assert (
        await api.post(
            "/api/v1/workflows", json=REQUEST, headers={**AUTH, "Idempotency-Key": "k1"}
        )
    ).status_code == 202
    steps = stores[3]
    steps.append(StepScope("wf_001", "source", 1), record("source.read_link"))
    steps.append(StepScope("wf_001", "source", 1), record("source.download_media", kind="progress", n=1, total=4))

    response = await api.get("/api/v1/workflows/wf_001/steps", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert [step["code"] for step in body["steps"]] == ["source.read_link", "source.download_media"]
    assert body["steps"][1]["n"] == 1 and body["steps"][1]["params"] == {"count": 2}
    assert body["steps"][0]["seq"] < body["steps"][1]["seq"]

    after = body["steps"][0]["seq"]
    tail = await api.get(f"/api/v1/workflows/wf_001/steps?after={after}", headers=AUTH)
    assert [step["code"] for step in tail.json()["steps"]] == ["source.download_media"]


@pytest.mark.asyncio
async def test_a_run_without_steps_or_a_unknown_run(api) -> None:
    assert (
        await api.post(
            "/api/v1/workflows", json=REQUEST, headers={**AUTH, "Idempotency-Key": "k2"}
        )
    ).status_code == 202
    empty = await api.get("/api/v1/workflows/wf_001/steps", headers=AUTH)
    assert empty.status_code == 200 and empty.json() == {"steps": []}
    missing = await api.get("/api/v1/workflows/wf_none/steps", headers=AUTH)
    assert missing.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["after=-1", "limit=0", "limit=501"])
async def test_out_of_bounds_queries_are_refused(api, query: str) -> None:
    assert (
        await api.get(f"/api/v1/workflows/wf_001/steps?{query}", headers=AUTH)
    ).status_code == 422


@pytest.mark.asyncio
async def test_without_a_step_store_the_page_degrades_to_empty(gateway, stores) -> None:
    projects, runs, reports, _ = stores
    app = create_app(
        Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"),
        gateway,
        project_store=projects,
        workflow_run_store=runs,
        report_store=reports,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        started = await client.post(
            "/api/v1/workflows", json=REQUEST, headers={**AUTH, "Idempotency-Key": "k3"}
        )
        assert started.status_code == 202
        response = await client.get("/api/v1/workflows/wf_001/steps", headers=AUTH)
        assert response.status_code == 200 and response.json() == {"steps": []}


@pytest.mark.asyncio
async def test_the_detail_fills_current_step_of_a_running_stage(api, gateway, stores) -> None:
    started = await api.post(
        "/api/v1/workflows", json=REQUEST, headers={**AUTH, "Idempotency-Key": "k4"}
    )
    assert started.status_code == 202
    from datetime import UTC, datetime

    now = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    gateway.workflows["wf_001"] = WorkflowSummary(
        workflow_id="wf_001",
        status="running",
        created_at=now,
        updated_at=now,
        source={"display_url": "https://x.test/v", "platform": "tiktok"},
        stages=[
            StageSummary(id="source", label="Source", status="running"),
            StageSummary(id="approval", label="Approval", status="waiting"),
        ],
    )
    steps = stores[3]
    steps.append(StepScope("wf_001", "source", 1), record("source.download_media", kind="progress", n=3, total=9))

    detail = await api.get("/api/v1/workflows/wf_001", headers=AUTH)
    assert detail.status_code == 200
    by_id = {stage["id"]: stage for stage in detail.json()["stages"]}
    assert by_id["source"]["current_step"]["code"] == "source.download_media"
    assert by_id["approval"]["current_step"] is None

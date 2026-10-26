"""Run lists across projects, with filters and what each row shows (restyle spec §6, B1-B2)."""

import json
from datetime import UTC, datetime

import httpx
import pytest
import pytest_asyncio

from tests.sqlite_support import sqlite_engine
from thoth_control_plane.api import create_app
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure import run_models, step_models  # noqa: F401  (tables)
from thoth_control_plane.infrastructure.project_store import ProjectStore
from thoth_control_plane.infrastructure.report_store import ReportStore
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.step_store import StepStore
from thoth_control_plane.infrastructure.workflow_run_store import StoredRun, WorkflowRunStore
from thoth_control_plane.progress import StepRecord, StepScope

AUTH = {"Authorization": "Bearer test-key"}


@pytest.fixture
def stores():
    engine = sqlite_engine()
    Base.metadata.create_all(engine)
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


def seed(
    stores,
    workflow_id: str,
    *,
    project_id: str | None = None,
    platform: str = "tiktok",
    url: str = "https://www.tiktok.com/@a/video/1",
    status: str = "succeeded",
    minute: int = 0,
) -> None:
    """A stored row for the API key's actor; the fake gateway gives every start one ID."""
    at = datetime(2026, 10, 26, 8, minute, tzinfo=UTC)
    stores[1].insert_missing(
        StoredRun(
            workflow_id=workflow_id,
            project_id=project_id,
            actor_type="user",
            actor_id="owner",
            display_url=url,
            platform=platform,
            status=status,
            history_expired=False,
            summary=None,
            created_at=at,
            updated_at=at,
        )
    )


async def ids(api, path: str) -> list[str]:
    response = await api.get(path, headers=AUTH)
    assert response.status_code == 200, response.text
    return [r["workflow_id"] for r in response.json()["items"]]


@pytest.mark.asyncio
async def test_without_unassigned_the_list_spans_every_project(api, stores) -> None:
    projects = stores[0]
    news = projects.create("News", "ws_bootstrap")
    haze = projects.create("Haze", "ws_bootstrap")
    seed(stores, "wf_a", project_id=news.project_id, minute=1)
    seed(stores, "wf_b", project_id=haze.project_id, minute=2)
    seed(stores, "wf_c", minute=3)

    assert await ids(api, "/api/v1/workflows") == ["wf_c", "wf_b", "wf_a"]
    assert await ids(api, "/api/v1/workflows?unassigned=true") == ["wf_c"]
    assert (await api.get("/api/v1/workflows?unassigned=false", headers=AUTH)).status_code == 422


@pytest.mark.asyncio
async def test_a_row_carries_its_title_owner_card_and_current_step(api, stores) -> None:
    _, _, reports, steps = stores
    seed(stores, "wf_live", status="running")
    reports.put(
        "reports/wf_live/source-report.json",
        "source_report",
        json.dumps(
            {
                "schema_version": 3,
                "post": {"text": "Haze closes schools\nmore", "owner_handle": "kalteng"},
                "post_card": {"location": "reports/wf_live/cards/post.png"},
            }
        ).encode(),
    )
    steps.append(
        StepScope("wf_live", "source", 1),
        StepRecord(
            at=datetime(2026, 10, 26, 8, 1, tzinfo=UTC),
            kind="info",
            code="source.fetch_post",
            n=None,
            total=None,
            params={"platform": "tiktok"},
        ),
    )

    [row] = (await api.get("/api/v1/workflows", headers=AUTH)).json()["items"]

    assert row["title"] == "Haze closes schools"
    assert row["owner_handle"] == "kalteng"
    assert row["has_post_card"] is True
    assert row["stages"] == []
    assert row["current_step"]["code"] == "source.fetch_post"


@pytest.mark.asyncio
async def test_a_finished_row_shows_no_current_step(api, stores) -> None:
    seed(stores, "wf_done")
    stores[3].append(
        StepScope("wf_done", "source", 1),
        StepRecord(
            at=datetime(2026, 10, 26, 8, 1, tzinfo=UTC),
            kind="info",
            code="source.save_report",
            n=None,
            total=None,
            params=None,
        ),
    )

    [row] = (await api.get("/api/v1/workflows", headers=AUTH)).json()["items"]

    assert row["current_step"] is None and row["title"] is None


@pytest.mark.asyncio
async def test_filters_narrow_both_lists(api, stores) -> None:
    project = stores[0].create("News", "ws_bootstrap")
    seed(stores, "wf_tt", project_id=project.project_id, minute=1)
    seed(
        stores,
        "wf_x",
        project_id=project.project_id,
        platform="x",
        url="https://x.com/someone/status/1234567890",
        status="failed",
        minute=2,
    )
    seed(stores, "wf_loose", status="cancelled", minute=3)

    base = f"/api/v1/projects/{project.project_id}/workflows"
    assert await ids(api, f"{base}?platform=x") == ["wf_x"]
    assert await ids(api, "/api/v1/workflows?q=TIKTOK.com") == ["wf_loose", "wf_tt"]
    assert await ids(api, f"{base}?status=succeeded&status=failed") == ["wf_x", "wf_tt"]
    assert await ids(api, "/api/v1/workflows?status=cancelled") == ["wf_loose"]
    assert (await api.get(f"{base}?status=nonsense", headers=AUTH)).status_code == 422
    assert (await api.get(f"/api/v1/workflows?q={'x' * 101}", headers=AUTH)).status_code == 422
    assert (await api.get(f"{base}?platform=Bad Name", headers=AUTH)).status_code == 422


@pytest.mark.asyncio
async def test_inbox_items_carry_the_post_title(api, stores) -> None:
    seed(stores, "wf_wait", status="awaiting_approval")
    stores[2].put(
        "reports/wf_wait/source-report.json",
        "source_report",
        json.dumps(
            {"schema_version": 3, "post": {"text": "Firefighters dig peat trenches"}}
        ).encode(),
    )

    inbox = (await api.get("/api/v1/inbox", headers=AUTH)).json()

    assert [item["title"] for item in inbox["approvals"]] == ["Firefighters dig peat trenches"]

"""Run lists across projects, filters and list-row details on a disposable PostgreSQL
(restyle spec §6, B1-B2): the LIKE escaping and the grouped step query are Postgres facts."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest

from thoth_control_plane.domain import Actor, WorkflowSummary
from thoth_control_plane.infrastructure.report_store import ReportStore
from thoth_control_plane.infrastructure.step_store import StepStore
from thoth_control_plane.infrastructure.workflow_run_store import WorkflowRunStore
from thoth_control_plane.operations.editor_migrations import apply_editor_migrations
from thoth_control_plane.progress import StepRecord, StepScope

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations" / "editor"
DATABASE_URL = os.environ.get("THOTH_TEST_EDITOR_DATABASE_URL", "")
OWNER = Actor(actor_id="owner", actor_type="user")
T0 = datetime(2026, 10, 26, 8, tzinfo=UTC)

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="THOTH_TEST_EDITOR_DATABASE_URL points at a disposable Postgres"
)


@pytest.fixture
def stores() -> tuple[WorkflowRunStore, ReportStore, StepStore]:
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    with psycopg.connect(DATABASE_URL) as connection:
        for project in ("p_news", "p_haze"):
            connection.execute(
                "INSERT INTO projects (project_id, name, workspace_id) "
                "VALUES (%s, %s, 'ws_bootstrap')",
                (project, project),
            )
    return (
        WorkflowRunStore.connect(DATABASE_URL),
        ReportStore.connect(DATABASE_URL),
        StepStore.connect(DATABASE_URL),
    )


def start(runs: WorkflowRunStore, workflow_id: str, project_id: str | None, **source) -> None:
    summary = WorkflowSummary.model_validate_json(
        json.dumps(
            {
                "workflow_id": workflow_id,
                "status": "running",
                "created_at": T0.isoformat(),
                "updated_at": T0.isoformat(),
                "source": {
                    "display_url": source.get("url", "https://www.tiktok.com/@a/video/1"),
                    "platform": source.get("platform", "tiktok"),
                },
                "stages": [],
            }
        )
    )
    runs.record_start(summary, project_id=project_id, actor=OWNER)


def report(reports: ReportStore, workflow_id: str, text: str) -> None:
    reports.put(
        f"reports/{workflow_id}/source-report.json",
        "source_report",
        json.dumps({"schema_version": 3, "post": {"text": text, "owner_handle": "a"}}).encode(),
    )


def test_every_project_filters_and_literal_text(stores) -> None:
    runs, reports, _ = stores
    start(runs, "wf_news", "p_news")
    start(runs, "wf_haze", "p_haze", platform="x", url="https://x.com/a/status/1")
    start(runs, "wf_loose", None)
    runs.settle("wf_loose", status="succeeded", summary=None, history_expired=False)
    report(reports, "wf_news", "Haze 50% worse_than ever")
    runs.fill_listing(["wf_news", "wf_haze", "wf_loose"])

    def ids(**filters) -> set[str]:
        page, _ = runs.page(
            project_id=None, unassigned=False, actor=OWNER, cursor=None, limit=50, **filters
        )
        return {run.workflow_id for run in page}

    assert ids() == {"wf_news", "wf_haze", "wf_loose"}
    assert ids(statuses=["running"]) == {"wf_news", "wf_haze"}
    assert ids(platform="x") == {"wf_haze"}
    assert ids(text="haze 50%") == {"wf_news"}
    assert ids(text="worse_than") == {"wf_news"}
    assert ids(text="worseXthan") == set()  # "_" is literal, not any character
    assert ids(text="5%0") == set()  # "%" is literal, not any run of characters
    assert ids(text="X.COM/A") == {"wf_haze"}
    stored = runs.get("wf_news")
    assert stored is not None and stored.title == "Haze 50% worse_than ever"


def test_latest_steps_group_per_run(stores) -> None:
    _, _, steps = stores
    at = datetime(2026, 10, 26, 8, 1, tzinfo=UTC)
    for workflow_id, code in (
        ("wf_a", "source.read_link"),
        ("wf_a", "source.fetch_post"),
        ("wf_b", "source.read_link"),
    ):
        steps.append(
            StepScope(workflow_id, "source", 1),
            StepRecord(at=at, kind="info", code=code, n=None, total=None, params=None),
        )

    latest = steps.latest(["wf_a", "wf_b"])

    assert {key: step.code for key, step in latest.items()} == {
        "wf_a": "source.fetch_post",
        "wf_b": "source.read_link",
    }

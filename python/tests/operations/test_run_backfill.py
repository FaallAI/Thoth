"""Backfill one run row per workflow that already has a source report."""

import json

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from thoth_control_plane.infrastructure import run_models  # noqa: F401
from thoth_control_plane.infrastructure.report_store import ReportStore
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.workflow_run_store import WorkflowRunStore
from thoth_control_plane.operations.run_backfill import backfill_runs

GOOD = "wf_" + "a" * 24
NO_SOURCE = "wf_" + "b" * 24


def report(url: str, platform: str = "tiktok") -> bytes:
    return json.dumps({"source": {"canonical_url": url, "platform": platform}}).encode()


def test_backfill_inserts_once_strips_queries_and_counts_invalid() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    reports, runs = ReportStore(engine), WorkflowRunStore(engine)
    reports.put(
        f"reports/{GOOD}/source-report.json", "source_report", report("https://x.test/v/1?sig=s#f")
    )
    reports.put(f"reports/{NO_SOURCE}/source-report.json", "source_report", b'{"source": {}}')
    # A folder that is not a workflow ID (a test or candidate folder) is skipped, not counted.
    reports.put("reports/wf_test/source-report.json", "source_report", report("https://x.test/2"))

    assert backfill_runs(runs) == (1, 0, 1)
    stored = runs.get(GOOD)
    assert stored is not None
    assert stored.display_url == "https://x.test/v/1"
    assert stored.status == "unknown"
    assert stored.project_id is None
    assert (stored.actor_type, stored.actor_id) == ("user", "owner")
    assert runs.get("wf_test") is None

    assert backfill_runs(runs) == (0, 1, 1)


def test_a_known_start_time_replaces_the_report_import_time() -> None:
    from datetime import UTC, datetime

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    reports, runs = ReportStore(engine), WorkflowRunStore(engine)
    reports.put(f"reports/{GOOD}/source-report.json", "source_report", report("https://x.test/v/1"))
    started = datetime(2026, 9, 25, 13, 8, tzinfo=UTC)
    assert backfill_runs(runs, start_times={GOOD: started}) == (1, 0, 0)
    stored = runs.get(GOOD)
    assert stored is not None
    assert stored.created_at == started
    assert stored.updated_at == started


async def test_temporal_start_times_skip_workflows_temporal_no_longer_holds() -> None:
    from datetime import UTC, datetime

    from temporalio.service import RPCError, RPCStatusCode

    from thoth_control_plane.operations.run_backfill import temporal_start_times

    started = datetime(2026, 9, 25, tzinfo=UTC)

    class Handle:
        def __init__(self, workflow_id):
            self.workflow_id = workflow_id

        async def describe(self):
            if self.workflow_id == "wf_gone":
                raise RPCError("gone", RPCStatusCode.NOT_FOUND, b"")
            return type("Description", (), {"start_time": started})()

    class Client:
        def get_workflow_handle(self, workflow_id):
            return Handle(workflow_id)

    assert await temporal_start_times(Client(), ["wf_live", "wf_gone"]) == {"wf_live": started}


def test_only_workflows_without_a_row_need_a_start_time() -> None:
    from thoth_control_plane.operations.run_backfill import workflows_needing_rows

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    reports, runs = ReportStore(engine), WorkflowRunStore(engine)
    reports.put(f"reports/{GOOD}/source-report.json", "source_report", report("https://x.test/1"))
    reports.put(
        f"reports/{NO_SOURCE}/source-report.json", "source_report", report("https://x.test/2")
    )
    reports.put("reports/wf_test/source-report.json", "source_report", report("https://x.test/3"))
    assert workflows_needing_rows(runs) == [GOOD, NO_SOURCE]
    backfill_runs(runs)
    assert workflows_needing_rows(runs) == []

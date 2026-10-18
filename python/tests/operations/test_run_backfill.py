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

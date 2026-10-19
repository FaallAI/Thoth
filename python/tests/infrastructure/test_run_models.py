"""The projects and workflow_runs ORM tables round-trip on SQLite."""

from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from thoth_control_plane.infrastructure.run_models import ProjectRow, WorkflowRunRow
from thoth_control_plane.infrastructure.source_account_models import Base

NOW = datetime(2026, 10, 18, 8, tzinfo=UTC)


def test_a_run_belongs_to_a_project_and_keeps_its_summary() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            ProjectRow(
                project_id="p1",
                name="News",
                created_at=NOW,
                updated_at=NOW,
                workspace_id="ws_bootstrap",
            )
        )
        session.add(
            WorkflowRunRow(
                workflow_id="wf_001",
                project_id="p1",
                actor_type="user",
                actor_id="owner",
                display_url="https://example.test/post",
                platform="example",
                status="queued",
                history_expired=False,
                summary={"workflow_id": "wf_001"},
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()
        row = session.scalar(select(WorkflowRunRow))
    assert row is not None
    assert row.project_id == "p1"
    assert row.summary == {"workflow_id": "wf_001"}
    assert row.created_at == NOW

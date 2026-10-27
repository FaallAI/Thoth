"""The Studio documents list names the run each draft was opened from (restyle spec §7, B9)."""

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import text

from tests.sqlite_support import sqlite_engine
from thoth_control_plane.api import create_app
from thoth_control_plane.config import Settings
from thoth_control_plane.domain.edit_document_list import (
    EditDocumentListItem,
    EditDocumentListPage,
)
from thoth_control_plane.infrastructure import run_models  # noqa: F401  (tables)
from thoth_control_plane.infrastructure.project_store import ProjectStore
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.workflow_run_store import StoredRun, WorkflowRunStore

AUTH = {"Authorization": "Bearer test-key"}
AT = datetime(2026, 10, 27, 8, tzinfo=UTC)


class Listing:
    """A document repository that only lists: one draft per source run named here."""

    def __init__(self, sources: dict[str, str | None]) -> None:
        self.sources = sources

    async def list_documents(self, *, project_id: str, limit: int, cursor: str | None):
        items = [
            EditDocumentListItem(
                document_id=document_id,
                revision=2,
                updated_at=AT,
                label="Kabut asap",
                imported=source is not None,
                state="rendering",
                render_percent=62,
                source_workflow_id=source,
            )
            for document_id, source in self.sources.items()
        ]
        return EditDocumentListPage(items=items, next_cursor=None)


def run(workflow_id: str, project_id: str | None, **fields) -> StoredRun:
    return StoredRun(
        workflow_id=workflow_id,
        project_id=project_id,
        actor_type="user",
        actor_id="someone_else",
        display_url="https://x.com/namelesid/status/1",
        platform="x",
        status="succeeded",
        history_expired=False,
        summary=None,
        created_at=AT,
        updated_at=AT,
        **fields,
    )


@pytest.mark.asyncio
async def test_each_draft_carries_its_source_runs_platform_title_owner_and_card(gateway) -> None:
    engine = sqlite_engine()
    Base.metadata.create_all(engine)
    projects, runs = ProjectStore(engine), WorkflowRunStore(engine)
    haze = projects.create("Haze", "ws_bootstrap").project_id
    other = projects.create("Other", "ws_bootstrap").project_id
    runs.insert_missing(run("wf_haze", haze))
    runs.insert_missing(run("wf_other", other))
    with engine.begin() as connection:
        # What the run list reads once from each source report (restyle B2).
        connection.execute(
            text(
                "UPDATE workflow_runs SET title = 'Kabut asap Kalteng', owner_handle = 'namelesid',"
                " post_card_location = 'reports/wf_haze/cards/post.png'"
                " WHERE workflow_id = 'wf_haze'"
            )
        )
        connection.execute(
            text("UPDATE workflow_runs SET title = 'Elsewhere' WHERE workflow_id = 'wf_other'")
        )
    listing = Listing(
        {"edoc_a": "wf_haze", "edoc_b": "wf_other", "edoc_c": "wf_gone", "edoc_d": None}
    )
    app = create_app(
        Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"),
        gateway,
        listing,
        project_store=projects,
        workflow_run_store=runs,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/projects/{haze}/edit-documents", headers=AUTH)

    assert response.status_code == 200, response.text
    items = {item["document_id"]: item for item in response.json()["items"]}
    source = ("source_platform", "source_title", "source_owner_handle", "source_has_post_card")
    # The run lives in this project: any member sees where its draft came from.
    assert [items["edoc_a"][key] for key in source] == [
        "x",
        "Kabut asap Kalteng",
        "namelesid",
        True,
    ]
    assert (items["edoc_a"]["state"], items["edoc_a"]["render_percent"]) == ("rendering", 62)
    # A run in another project, a run that is gone, and no run at all show no source.
    for document_id in ("edoc_b", "edoc_c", "edoc_d"):
        assert [items[document_id][key] for key in source] == [None, None, None, False]

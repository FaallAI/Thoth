"""Opening a workflow in Studio on a disposable PostgreSQL: the real report row, draft,
attach and asset tables, with a local media store and a fake probe."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

from tests.application.test_workflow_studio_imports import (
    ACTOR,
    WF,
    Probe,
    content_set_bytes,
    seed_media,
    stored_run,
)
from thoth_control_plane.application.studio_imports import StudioImportService
from thoth_control_plane.application.workflow_studio_imports import (
    WorkflowStudioImportService,
    content_set_location,
)
from thoth_control_plane.infrastructure.editor_asset_repository import (
    PostgresEditorAssetRepository,
)
from thoth_control_plane.infrastructure.media_store import LocalMediaStore
from thoth_control_plane.infrastructure.project_store import ProjectStore
from thoth_control_plane.infrastructure.report_store import ReportStore
from thoth_control_plane.infrastructure.studio_import_repository import (
    PostgresStudioImportRepository,
)
from thoth_control_plane.infrastructure.workflow_run_store import WorkflowRunStore
from thoth_control_plane.operations.editor_migrations import apply_editor_migrations

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations" / "editor"
DATABASE_URL = os.environ.get("THOTH_TEST_EDITOR_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="THOTH_TEST_EDITOR_DATABASE_URL points at a disposable Postgres"
)


@pytest.fixture
def database() -> str:
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    return DATABASE_URL


async def test_a_workflow_opens_in_studio_on_the_real_tables(database: str, tmp_path: Path) -> None:
    project = ProjectStore.connect(database).create("Studio", "ws_bootstrap").project_id
    reports = ReportStore.connect(database)
    reports.put(content_set_location(WF), "content_set", content_set_bytes())
    runs = WorkflowRunStore.connect(database)
    runs.insert_missing(stored_run())
    media = LocalMediaStore(tmp_path / "store")
    seed_media(media, tmp_path)
    assets = PostgresEditorAssetRepository(database)
    imports = StudioImportService(PostgresStudioImportRepository(database))
    service = WorkflowStudioImportService(
        runs=runs, reports=reports, media=media, assets=assets, imports=imports, probe=Probe()
    )

    opened = await service.open(project, WF, ACTOR, "open-1")

    assert {(item.item_id, item.outcome) for item in opened.items} == {
        ("main_000", "copied"),
        ("footage_000", "copied"),
        ("footage_001", "copied"),
    }
    inventory = await imports.get_inventory(project, opened.draft.document_id)
    attached = {i.item_id: i.asset_id for i in inventory.items if i.disposition == "attached"}
    assert set(attached) == {"main_000", "footage_000", "footage_001"}
    record = await assets.get_ready_record(project_id=project, asset_id=attached["main_000"])
    assert record is not None and record.provenance == "workflow_import"
    assert record.artifact_location == f"uploads/{project}/{attached['main_000']}.mp4"
    assert runs.get(WF).project_id == project

    second = await service.open(project, WF, ACTOR, "open-2")

    assert {item.outcome for item in second.items} == {"reused"}
    with psycopg.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM editor_assets").fetchone() == (3,)

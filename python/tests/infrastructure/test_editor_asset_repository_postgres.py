"""Project-scoped editor assets on the migrated PostgreSQL schema (ORM spec 2026-10-26)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.postgres_support import DATABASE_URL, empty_tables, needs_postgres, reset_schema
from thoth_control_plane.application.editor_asset_ports import EditorAssetPersistenceError
from thoth_control_plane.domain.editor_assets import EditorAsset, EditorAssetRecord
from thoth_control_plane.infrastructure.editor_asset_repository import (
    PostgresEditorAssetRepository,
)
from thoth_control_plane.infrastructure.editor_database import editor_sessions
from thoth_control_plane.infrastructure.editor_models import EditorAssetRow

START = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
CHECKSUM = "sha256:" + "a" * 64


@pytest.fixture(scope="module")
def migrated() -> None:
    reset_schema()


@pytest.fixture
def assets(migrated: None) -> PostgresEditorAssetRepository:
    empty_tables()
    return PostgresEditorAssetRepository(DATABASE_URL)


def seed(
    asset_id: str,
    *,
    project_id: str = "project_001",
    minutes: int = 0,
    state: str = "ready",
    kind: str = "video",
    checksum: str | None = CHECKSUM,
) -> None:
    with editor_sessions(DATABASE_URL).begin() as session:
        session.add(
            EditorAssetRow(
                project_id=project_id,
                asset_id=asset_id,
                kind=kind,
                media_type="audio/mpeg" if kind == "audio" else "video/mp4",
                artifact_location=f"{project_id}/{asset_id}.bin",
                duration_in_frames=900,
                width=None if kind == "audio" else 1080,
                height=None if kind == "audio" else 1920,
                fps=30.0,
                has_audio=True,
                validation_state=state,
                checksum=checksum,
                provenance="operator_upload",
                created_at=START + timedelta(minutes=minutes),
            )
        )


@needs_postgres
async def test_a_listing_is_project_scoped_ready_only_newest_first_and_locator_free(
    assets: PostgresEditorAssetRepository,
) -> None:
    seed("asset_old", minutes=0)
    seed("asset_new", minutes=5)
    seed("asset_pending", minutes=9, state="pending")
    seed("asset_elsewhere", project_id="project_002", minutes=7)

    page = await assets.list_ready(project_id="project_001", limit=10, cursor=None)

    assert [asset.asset_id for asset in page.assets] == ["asset_new", "asset_old"]
    assert page.next_cursor is None
    assert "artifact_location" not in EditorAsset.model_fields


@needs_postgres
async def test_a_cursor_replays_the_listing_as_a_keyset(
    assets: PostgresEditorAssetRepository,
) -> None:
    for minute in range(3):
        seed(f"asset_{minute}", minutes=minute)

    first = await assets.list_ready(project_id="project_001", limit=2, cursor=None)
    second = await assets.list_ready(project_id="project_001", limit=2, cursor=first.next_cursor)

    assert [asset.asset_id for asset in first.assets] == ["asset_2", "asset_1"]
    assert first.next_cursor is not None
    assert [asset.asset_id for asset in second.assets] == ["asset_0"]
    assert second.next_cursor is None


@needs_postgres
async def test_the_page_size_is_clamped_to_at_least_one(
    assets: PostgresEditorAssetRepository,
) -> None:
    seed("asset_a", minutes=0)
    seed("asset_b", minutes=1)

    page = await assets.list_ready(project_id="project_001", limit=0, cursor=None)

    assert [asset.asset_id for asset in page.assets] == ["asset_b"]
    assert page.next_cursor is not None


@needs_postgres
async def test_a_malformed_cursor_is_the_safe_error(
    assets: PostgresEditorAssetRepository,
) -> None:
    with pytest.raises(EditorAssetPersistenceError, match=r"^editor asset unavailable$"):
        await assets.list_ready(project_id="project_001", limit=10, cursor="not-a-cursor")


@needs_postgres
async def test_a_project_without_assets_lists_an_empty_page(
    assets: PostgresEditorAssetRepository,
) -> None:
    page = await assets.list_ready(project_id="project_002", limit=10, cursor=None)

    assert page.assets == ()
    assert page.next_cursor is None


@needs_postgres
async def test_a_record_carries_the_server_only_locator_for_its_own_project(
    assets: PostgresEditorAssetRepository,
) -> None:
    seed("asset_main")
    seed("asset_pending", state="pending")

    record = await assets.get_ready_record(project_id="project_001", asset_id="asset_main")

    assert record is not None
    assert record.artifact_location == "project_001/asset_main.bin"
    assert record.provenance == "operator_upload"
    assert await assets.get_ready_record(project_id="project_999", asset_id="asset_main") is None
    assert await assets.get_ready_record(project_id="project_001", asset_id="asset_none") is None
    pending = await assets.get_ready_record(project_id="project_001", asset_id="asset_pending")
    assert pending is None


@needs_postgres
async def test_a_batch_answers_in_the_callers_order_and_skips_what_is_missing(
    assets: PostgresEditorAssetRepository,
) -> None:
    seed("asset_main")
    seed("asset_music", kind="audio")
    seed("asset_other", project_id="project_002")

    records = await assets.get_ready_records(
        project_id="project_001",
        asset_ids=("asset_music", "asset_none", "asset_other", "asset_main"),
    )

    assert [record.asset.asset_id for record in records] == ["asset_music", "asset_main"]
    assert await assets.get_ready_records(project_id="project_001", asset_ids=()) == ()


@needs_postgres
async def test_registration_writes_one_row_and_a_duplicate_is_the_safe_error(
    assets: PostgresEditorAssetRepository,
) -> None:
    record = EditorAssetRecord(
        asset=EditorAsset(
            asset_id="asset_upload",
            project_id="project_001",
            kind="video",
            media_type="video/mp4",
            duration_in_frames=300,
            width=1080,
            height=1920,
            fps=30.0,
            has_audio=False,
            validation_state="ready",
            checksum=CHECKSUM,
        ),
        artifact_location="project_001/asset_upload.mp4",
        provenance="operator_upload",
    )

    await assets.register_ready(record)

    stored = await assets.get_ready_record(project_id="project_001", asset_id="asset_upload")
    assert stored == record
    with pytest.raises(EditorAssetPersistenceError, match=r"^editor asset unavailable$"):
        await assets.register_ready(record)


@needs_postgres
async def test_a_checksum_finds_the_oldest_ready_asset_of_the_project(
    assets: PostgresEditorAssetRepository,
) -> None:
    seed("asset_second", minutes=5)
    seed("asset_first", minutes=1)
    seed("asset_elsewhere", project_id="project_002", minutes=0)

    found = await assets.find_ready_by_checksum(project_id="project_001", checksum=CHECKSUM)
    missing = await assets.find_ready_by_checksum(
        project_id="project_001", checksum="sha256:" + "b" * 64
    )

    assert found is not None and found.asset.asset_id == "asset_first"
    assert missing is None


@needs_postgres
async def test_registered_locations_span_every_project(
    assets: PostgresEditorAssetRepository,
) -> None:
    seed("asset_one")
    seed("asset_two", project_id="project_002")

    found = await assets.registered_locations(
        ["project_001/asset_one.bin", "project_002/asset_two.bin", "project_003/none.bin"]
    )

    assert found == {"project_001/asset_one.bin", "project_002/asset_two.bin"}


async def test_an_unreachable_database_never_leaks_its_address() -> None:
    repository = PostgresEditorAssetRepository("postgresql://user:secret@127.0.0.1:1/editor")

    with pytest.raises(EditorAssetPersistenceError) as raised:
        await repository.list_ready(project_id="project_001", limit=10, cursor=None)

    assert str(raised.value) == "editor asset unavailable"
    assert "secret" not in repr(raised.value.args)

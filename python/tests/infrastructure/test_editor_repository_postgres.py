"""Immutable Creator Studio revisions on the migrated PostgreSQL schema (ORM spec 2026-10-26)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import func, select

from tests.postgres_support import DATABASE_URL, empty_tables, needs_postgres, reset_schema
from thoth_control_plane.application.ports import (
    EditDocumentRevisionConflict,
    EditDocumentUpgradeConflict,
)
from thoth_control_plane.domain.edit_document_operations import EditDocumentPatch
from thoth_control_plane.domain.edit_document_upgrade import upgrade_edit_document_v1
from thoth_control_plane.domain.edit_document_v2 import EditDocumentV2
from thoth_control_plane.domain.edit_documents import EditDocumentV1
from thoth_control_plane.infrastructure.editor_database import editor_sessions
from thoth_control_plane.infrastructure.editor_models import (
    EditDocumentRevisionRow,
    EditDocumentUpgradeIdempotencyRow,
    EditorAssetRow,
)
from thoth_control_plane.infrastructure.editor_repository import (
    EditDocumentConflict,
    EditDocumentPersistenceError,
    PostgresEditDocumentRepository,
)

PROJECT = "project_001"
DOCUMENT = "edoc_abc123"


@pytest.fixture(scope="module")
def migrated() -> None:
    reset_schema()


@pytest.fixture
def documents(migrated: None) -> PostgresEditDocumentRepository:
    empty_tables()
    return PostgresEditDocumentRepository(DATABASE_URL)


def document(document_id: str = DOCUMENT, project_id: str = PROJECT) -> EditDocumentV1:
    return EditDocumentV1.model_validate(
        {
            "schema_version": 1,
            "document_id": document_id,
            "project_id": project_id,
            "revision": 1,
            "template": {"template_id": "vertical_text_story", "version": 1},
            "canvas": {"width": 1080, "height": 1920, "fps": 30, "duration_in_frames": 150},
            "scenes": [
                {
                    "scene_id": "scene_001",
                    "role": "title",
                    "start_frame": 0,
                    "duration_in_frames": 150,
                    "clip_ids": ["clip_001"],
                }
            ],
            "tracks": [{"track_id": "track_visual", "kind": "visual", "clip_ids": ["clip_001"]}],
            "clips": [
                {
                    "kind": "text",
                    "clip_id": "clip_001",
                    "scene_id": "scene_001",
                    "track_id": "track_visual",
                    "start_frame": 0,
                    "duration_in_frames": 150,
                    "heading": "Title",
                    "body": "",
                    "style_slot": "title",
                    "ownership": "ai_managed",
                }
            ],
        }
    )


def timeline_document() -> EditDocumentV2:
    return upgrade_edit_document_v1(document())


def retitle(value: str, operation_id: str = "op_001") -> list[Any]:
    return EditDocumentPatch.model_validate(
        {
            "base_revision": 1,
            "operations": [
                {
                    "kind": "replace_text",
                    "operation_id": operation_id,
                    "clip_id": "clip_001",
                    "field": "heading",
                    "value": value,
                }
            ],
        }
    ).operations


def add_clip_patch() -> list[Any]:
    return EditDocumentPatch.model_validate(
        {
            "base_revision": 1,
            "operations": [
                {
                    "kind": "add_clip_from_asset",
                    "operation_id": "op_1",
                    "clip_id": "clip_b_roll",
                    "track_id": "track_b_roll",
                    "asset_id": "asset_main",
                    "from_frame": 0,
                    "duration_in_frames": 60,
                }
            ],
        }
    ).operations


def seed_asset(project_id: str = PROJECT, state: str = "ready") -> None:
    with editor_sessions(DATABASE_URL).begin() as session:
        session.add(
            EditorAssetRow(
                project_id=project_id,
                asset_id="asset_main",
                kind="video",
                media_type="video/mp4",
                artifact_location=f"{project_id}/asset_main.mp4",
                duration_in_frames=900,
                width=1080,
                height=1920,
                fps=30.0,
                has_audio=True,
                validation_state=state,
                checksum="sha256:" + "a" * 64,
                provenance="operator_upload",
            )
        )


def revisions() -> int:
    with editor_sessions(DATABASE_URL)() as session:
        return session.scalar(select(func.count()).select_from(EditDocumentRevisionRow)) or 0


@needs_postgres
async def test_a_revision_reads_back_as_the_latest_and_by_number(
    documents: PostgresEditDocumentRepository,
) -> None:
    await documents.insert_revision(document())

    assert await documents.get_latest(project_id=PROJECT, document_id=DOCUMENT) == document()
    exact = await documents.get_revision(project_id=PROJECT, document_id=DOCUMENT, revision=1)
    assert exact == document()
    assert (
        await documents.get_revision(project_id=PROJECT, document_id=DOCUMENT, revision=7) is None
    )
    assert (
        await documents.get_revision(project_id="project_999", document_id=DOCUMENT, revision=1)
        is None
    )
    assert await documents.get_latest(project_id="project_999", document_id=DOCUMENT) is None


@needs_postgres
async def test_an_existing_revision_cannot_be_overwritten(
    documents: PostgresEditDocumentRepository,
) -> None:
    await documents.insert_revision(document())

    with pytest.raises(EditDocumentConflict, match=r"^edit document revision already exists$"):
        await documents.insert_revision(document())


@needs_postgres
async def test_operations_append_the_next_revision(
    documents: PostgresEditDocumentRepository,
) -> None:
    await documents.insert_revision(document())

    result = await documents.apply_operations(PROJECT, DOCUMENT, 1, retitle("Revised title"))

    assert result.revision == 2
    assert result.clips[0].heading == "Revised title"
    assert result.clips[0].ownership == "user_edited"
    assert await documents.get_latest(project_id=PROJECT, document_id=DOCUMENT) == result


@needs_postgres
async def test_a_stale_save_conflicts_with_the_latest_document(
    documents: PostgresEditDocumentRepository,
) -> None:
    await documents.insert_revision(document())
    current = await documents.apply_operations(PROJECT, DOCUMENT, 1, retitle("Second"))

    with pytest.raises(EditDocumentRevisionConflict) as error:
        await documents.apply_operations(PROJECT, DOCUMENT, 1, [])

    assert error.value.latest == current
    assert revisions() == 2


@needs_postgres
async def test_concurrent_saves_on_one_base_land_exactly_once(
    documents: PostgresEditDocumentRepository,
) -> None:
    await documents.insert_revision(document())

    outcomes = await asyncio.gather(
        documents.apply_operations(PROJECT, DOCUMENT, 1, retitle("First title", "op_001")),
        documents.apply_operations(PROJECT, DOCUMENT, 1, retitle("Second title", "op_002")),
        return_exceptions=True,
    )

    saved = [outcome for outcome in outcomes if not isinstance(outcome, BaseException)]
    refused = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
    assert len(saved) == 1 and len(refused) == 1
    assert isinstance(refused[0], EditDocumentRevisionConflict)
    assert refused[0].latest.revision == 2
    assert refused[0].latest.clips[0].heading == saved[0].clips[0].heading
    assert revisions() == 2


@needs_postgres
async def test_an_unreadable_stored_document_is_the_safe_error(
    documents: PostgresEditDocumentRepository,
) -> None:
    with editor_sessions(DATABASE_URL).begin() as session:
        session.add(
            EditDocumentRevisionRow(
                project_id=PROJECT,
                document_id=DOCUMENT,
                revision=1,
                document_json={"revision": "invalid"},
            )
        )

    with pytest.raises(
        EditDocumentPersistenceError, match=r"^edit document persistence unavailable$"
    ):
        await documents.apply_operations(PROJECT, DOCUMENT, 1, [])


@needs_postgres
async def test_operations_on_a_missing_document_are_the_safe_error(
    documents: PostgresEditDocumentRepository,
) -> None:
    with pytest.raises(EditDocumentPersistenceError):
        await documents.apply_operations(PROJECT, DOCUMENT, 1, [])


@needs_postgres
async def test_an_asset_resolves_only_when_this_project_has_it_ready(
    documents: PostgresEditDocumentRepository,
) -> None:
    await documents.insert_revision(timeline_document())
    with pytest.raises(EditDocumentPersistenceError):
        await documents.apply_operations(PROJECT, DOCUMENT, 1, add_clip_patch())
    seed_asset(state="pending")
    with pytest.raises(EditDocumentPersistenceError):
        await documents.apply_operations(PROJECT, DOCUMENT, 1, add_clip_patch())
    assert revisions() == 1

    with editor_sessions(DATABASE_URL).begin() as session:
        row = session.get(EditorAssetRow, (PROJECT, "asset_main"))
        assert row is not None
        row.validation_state = "ready"
    result = await documents.apply_operations(PROJECT, DOCUMENT, 1, add_clip_patch())

    assert [ref.asset_id for ref in result.asset_refs] == ["asset_main"]
    assert result.revision == 2
    # Only the safe projection enters the document: never the artifact locator.
    assert "asset_main.mp4" not in result.model_dump_json()


@needs_postgres
async def test_an_upgrade_appends_one_version_two_revision_and_records_the_key(
    documents: PostgresEditDocumentRepository,
) -> None:
    await documents.insert_revision(document())

    result = await documents.upgrade_to_timeline(
        project_id=PROJECT, document_id=DOCUMENT, base_revision=1, idempotency_key="key_001"
    )

    assert (result.schema_version, result.revision) == (2, 2)
    with editor_sessions(DATABASE_URL)() as session:
        recorded = session.get(EditDocumentUpgradeIdempotencyRow, (PROJECT, "key_001"))
    assert recorded is not None
    assert (recorded.document_id, recorded.result_revision) == (DOCUMENT, 2)
    assert len(recorded.payload_hash) == 64
    assert set(recorded.payload_hash) <= set("0123456789abcdef")


@needs_postgres
async def test_an_upgrade_replay_returns_the_recorded_revision_without_writing(
    documents: PostgresEditDocumentRepository,
) -> None:
    await documents.insert_revision(document())
    first = await documents.upgrade_to_timeline(
        project_id=PROJECT, document_id=DOCUMENT, base_revision=1, idempotency_key="key_001"
    )

    replayed = await documents.upgrade_to_timeline(
        project_id=PROJECT, document_id=DOCUMENT, base_revision=1, idempotency_key="key_001"
    )

    assert replayed == first
    assert revisions() == 2


@needs_postgres
async def test_an_upgrade_key_replayed_with_another_payload_conflicts(
    documents: PostgresEditDocumentRepository,
) -> None:
    await documents.insert_revision(document())
    await documents.upgrade_to_timeline(
        project_id=PROJECT, document_id=DOCUMENT, base_revision=1, idempotency_key="key_001"
    )

    with pytest.raises(EditDocumentUpgradeConflict):
        await documents.upgrade_to_timeline(
            project_id=PROJECT, document_id=DOCUMENT, base_revision=2, idempotency_key="key_001"
        )
    assert revisions() == 2


@needs_postgres
async def test_an_upgrade_conflicts_when_the_base_revision_moved(
    documents: PostgresEditDocumentRepository,
) -> None:
    await documents.insert_revision(document())
    await documents.apply_operations(PROJECT, DOCUMENT, 1, retitle("Moved"))

    with pytest.raises(EditDocumentRevisionConflict) as conflict:
        await documents.upgrade_to_timeline(
            project_id=PROJECT, document_id=DOCUMENT, base_revision=1, idempotency_key="key_001"
        )
    assert conflict.value.latest.revision == 2
    assert revisions() == 2


@needs_postgres
async def test_an_upgrade_conflicts_when_the_document_is_already_version_two(
    documents: PostgresEditDocumentRepository,
) -> None:
    await documents.insert_revision(timeline_document())

    with pytest.raises(EditDocumentUpgradeConflict):
        await documents.upgrade_to_timeline(
            project_id=PROJECT, document_id=DOCUMENT, base_revision=1, idempotency_key="key_001"
        )
    assert revisions() == 1


@needs_postgres
async def test_a_listing_shows_each_documents_newest_revision_newest_first(
    documents: PostgresEditDocumentRepository,
) -> None:
    await documents.insert_revision(document("edoc_old"))
    await documents.insert_revision(document("edoc_new"))
    await documents.apply_operations(PROJECT, "edoc_old", 1, retitle("Edited later"))
    await documents.insert_revision(document("edoc_elsewhere", project_id="project_other"))

    first = await documents.list_documents(project_id=PROJECT, limit=1, cursor=None)
    second = await documents.list_documents(project_id=PROJECT, limit=1, cursor=first.next_cursor)

    assert [(item.document_id, item.revision) for item in first.items] == [("edoc_old", 2)]
    assert first.next_cursor is not None
    assert [(item.document_id, item.revision) for item in second.items] == [("edoc_new", 1)]
    assert second.next_cursor is None
    assert not first.items[0].imported


async def test_an_unreachable_store_is_the_safe_error_without_its_address() -> None:
    unreachable = PostgresEditDocumentRepository("postgresql://user:secret@127.0.0.1:1/editor")

    for attempt in (
        unreachable.get_latest(project_id=PROJECT, document_id=DOCUMENT),
        unreachable.get_revision(project_id=PROJECT, document_id=DOCUMENT, revision=1),
        unreachable.apply_operations(PROJECT, DOCUMENT, 1, []),
    ):
        with pytest.raises(EditDocumentPersistenceError) as failure:
            await attempt
        assert str(failure.value) == "edit document persistence unavailable"
        assert "secret" not in repr(failure.value.args)


def test_conflict_errors_are_safe() -> None:
    assert str(EditDocumentConflict()) == "edit document revision already exists"
    assert str(EditDocumentRevisionConflict(document())) == "edit document revision conflict"

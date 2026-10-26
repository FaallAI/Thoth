"""Studio drafts and import decisions on the migrated PostgreSQL schema (ORM spec 2026-10-26)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import func, select

from tests.domain.test_studio_imports import projection_payload
from tests.postgres_support import DATABASE_URL, empty_tables, needs_postgres, reset_schema
from thoth_control_plane.application.edit_documents import EditDocumentNotFound
from thoth_control_plane.application.ports import (
    EditDocumentRevisionConflict,
    StudioImportConflict,
    StudioImportDecisionRejected,
    StudioImportItemNotFound,
    StudioImportItemResolved,
)
from thoth_control_plane.application.studio_imports import build_studio_draft
from thoth_control_plane.domain.edit_document_v2 import EditDocumentV2
from thoth_control_plane.domain.studio_imports import (
    AttachImportAsset,
    ExcludeImportItem,
    StudioSourceProjection,
    inventory,
    source_key,
)
from thoth_control_plane.infrastructure import studio_import_repository
from thoth_control_plane.infrastructure.editor_database import editor_sessions
from thoth_control_plane.infrastructure.editor_models import (
    EditDocumentRevisionRow,
    EditorAssetRow,
    StudioImportDecisionRow,
    StudioImportDraftRow,
)
from thoth_control_plane.infrastructure.editor_repository import EditDocumentPersistenceError
from thoth_control_plane.infrastructure.studio_import_repository import (
    PostgresStudioImportRepository,
)

PROJECT = "project_001"
DOCUMENT = "edoc_first"
PROJECTION = StudioSourceProjection.model_validate(projection_payload())
KEY = source_key(PROJECTION)
DRAFT = build_studio_draft(PROJECT, DOCUMENT, PROJECTION)
INVENTORY = inventory(PROJECTION)


@pytest.fixture(scope="module")
def migrated() -> None:
    reset_schema()


@pytest.fixture
def imports(migrated: None) -> PostgresStudioImportRepository:
    empty_tables()
    return PostgresStudioImportRepository(DATABASE_URL)


async def create(
    imports: PostgresStudioImportRepository,
    *,
    key: str = KEY,
    idempotency_key: str = "open-1",
    document: EditDocumentV2 = DRAFT,
) -> Any:
    return await imports.create_draft(
        project_id=document.project_id,
        source_key=key,
        idempotency_key=idempotency_key,
        document=document,
        inventory=INVENTORY,
    )


async def resolve(
    imports: PostgresStudioImportRepository, item_id: str, decision: Any, base_revision: int = 1
) -> Any:
    return await imports.resolve_item(
        project_id=PROJECT,
        document_id=DOCUMENT,
        item_id=item_id,
        base_revision=base_revision,
        decision=decision,
    )


def seed_asset(
    asset_id: str = "asset_clip",
    kind: str = "video",
    duration: int | None = 60,
    *,
    project_id: str = PROJECT,
    state: str = "ready",
) -> None:
    audio = kind == "audio"
    with editor_sessions(DATABASE_URL).begin() as session:
        session.add(
            EditorAssetRow(
                project_id=project_id,
                asset_id=asset_id,
                kind=kind,
                media_type={"video": "video/mp4", "image": "image/png"}.get(kind, "audio/mpeg"),
                artifact_location=f"{project_id}/{asset_id}.bin",
                duration_in_frames=duration,
                width=None if audio else 1080,
                height=None if audio else 1920,
                fps=30.0,
                has_audio=kind != "image",
                validation_state=state,
                checksum=None,
                provenance="operator_upload",
            )
        )


def attach(asset_id: str = "asset_clip") -> AttachImportAsset:
    return AttachImportAsset(kind="attach_asset", asset_id=asset_id)


def saved(revision: int = 2, document_id: str = DOCUMENT) -> dict[str, Any]:
    with editor_sessions(DATABASE_URL)() as session:
        row = session.get(EditDocumentRevisionRow, (document_id, revision))
    assert row is not None
    return row.document_json


def count(table: type) -> int:
    with editor_sessions(DATABASE_URL)() as session:
        return session.scalar(select(func.count()).select_from(table)) or 0


def scene_of(document: dict[str, Any], scene_id: str) -> dict[str, Any]:
    return next(scene for scene in document["scenes"] if scene["scene_id"] == scene_id)


def clip_of(document: dict[str, Any], clip_id: str) -> dict[str, Any]:
    return next(clip for clip in document["clips"] if clip["clip_id"] == clip_id)


@needs_postgres
async def test_a_draft_writes_its_first_revision_and_manifest_together(
    imports: PostgresStudioImportRepository,
) -> None:
    draft = await create(imports)

    assert (draft.document_id, draft.source_key, draft.revision) == (DOCUMENT, KEY, 1)
    assert draft.created_at.tzinfo is not None
    assert (count(EditDocumentRevisionRow), count(StudioImportDraftRow)) == (1, 1)
    persisted = str(saved(1))
    with editor_sessions(DATABASE_URL)() as session:
        persisted += str(session.scalar(select(StudioImportDraftRow.inventory)))
    assert "example.com" not in persisted
    assert "source_url" not in persisted


@needs_postgres
async def test_a_replayed_key_returns_the_draft_at_its_latest_revision_without_writing(
    imports: PostgresStudioImportRepository,
) -> None:
    await create(imports)
    await resolve(imports, "unsupported_000", ExcludeImportItem(kind="exclude"))

    replayed = await create(imports)

    assert (replayed.document_id, replayed.revision) == (DOCUMENT, 2)
    assert (count(EditDocumentRevisionRow), count(StudioImportDraftRow)) == (2, 1)


@needs_postgres
async def test_a_key_reused_for_another_source_is_a_conflict(
    imports: PostgresStudioImportRepository,
) -> None:
    await create(imports)

    with pytest.raises(StudioImportConflict):
        await create(imports, key="f" * 64)
    assert count(EditDocumentRevisionRow) == 1


@needs_postgres
async def test_a_refused_manifest_rolls_back_its_revision(
    imports: PostgresStudioImportRepository,
) -> None:
    # The draft table refuses this key shape, after the revision was already written.
    with pytest.raises(EditDocumentPersistenceError) as raised:
        await create(imports, idempotency_key="not a key!")

    assert "postgresql" not in str(raised.value)
    assert count(EditDocumentRevisionRow) == 0


@needs_postgres
async def test_listing_is_project_scoped_bounded_and_newest_first(
    imports: PostgresStudioImportRepository,
) -> None:
    await create(
        imports,
        idempotency_key="open-a",
        document=build_studio_draft(PROJECT, "edoc_a", PROJECTION),
    )
    await create(
        imports,
        idempotency_key="open-b",
        document=build_studio_draft(PROJECT, "edoc_b", PROJECTION),
    )
    await create(
        imports,
        idempotency_key="open-c",
        document=build_studio_draft(PROJECT, "edoc_c", PROJECTION),
    )
    await create(
        imports,
        idempotency_key="open-x",
        document=build_studio_draft("project_other", "edoc_x", PROJECTION),
    )

    drafts = await imports.list_drafts(project_id=PROJECT, source_key=KEY, limit=2)

    assert [(draft.document_id, draft.revision) for draft in drafts] == [
        ("edoc_c", 1),
        ("edoc_b", 1),
    ]


@needs_postgres
async def test_the_manifest_reads_with_decisions_and_the_latest_revision(
    imports: PostgresStudioImportRepository,
) -> None:
    await create(imports)
    await resolve(imports, "unsupported_000", ExcludeImportItem(kind="exclude"))

    result = await imports.get_inventory(project_id=PROJECT, document_id=DOCUMENT)

    assert result is not None
    assert (result.document_id, result.source_key, result.revision) == (DOCUMENT, KEY, 2)
    dispositions = {entry.item_id: entry.disposition for entry in result.items}
    assert dispositions["unsupported_000"] == "excluded"
    assert dispositions["main_000"] == "unresolved"
    assert await imports.get_inventory(project_id=PROJECT, document_id="edoc_none") is None


@needs_postgres
async def test_an_exclusion_records_its_decision_with_a_new_revision(
    imports: PostgresStudioImportRepository,
) -> None:
    await create(imports)

    result = await resolve(imports, "unsupported_000", ExcludeImportItem(kind="exclude"))

    assert result.revision == 2
    decided = {entry.item_id: entry.disposition for entry in result.items}
    assert decided["unsupported_000"] == "excluded"
    with editor_sessions(DATABASE_URL)() as session:
        decision = session.scalar(select(StudioImportDecisionRow))
    assert decision is not None
    assert (
        decision.item_id,
        decision.revision,
        decision.disposition,
        decision.asset_id,
        decision.reason,
    ) == ("unsupported_000", 2, "excluded", None, None)


@needs_postgres
async def test_a_stale_revision_is_a_conflict_with_the_latest_document(
    imports: PostgresStudioImportRepository,
) -> None:
    await create(imports)
    await resolve(imports, "unsupported_000", ExcludeImportItem(kind="exclude"))

    with pytest.raises(EditDocumentRevisionConflict) as raised:
        await resolve(imports, "footage_000", ExcludeImportItem(kind="exclude"))

    assert raised.value.latest.revision == 2
    assert count(StudioImportDecisionRow) == 1


@needs_postgres
async def test_an_item_is_decided_once(imports: PostgresStudioImportRepository) -> None:
    await create(imports)
    await resolve(imports, "unsupported_000", ExcludeImportItem(kind="exclude"))

    with pytest.raises(StudioImportItemResolved):
        await resolve(imports, "unsupported_000", ExcludeImportItem(kind="exclude"), 2)
    assert count(StudioImportDecisionRow) == 1


@needs_postgres
async def test_an_unknown_item_or_draft_is_not_found(
    imports: PostgresStudioImportRepository,
) -> None:
    with pytest.raises(EditDocumentNotFound):
        await resolve(imports, "main_000", ExcludeImportItem(kind="exclude"))
    await create(imports)
    with pytest.raises(StudioImportItemNotFound):
        await resolve(imports, "footage_999", ExcludeImportItem(kind="exclude"))


@needs_postgres
async def test_an_unsupported_field_cannot_be_attached(
    imports: PostgresStudioImportRepository,
) -> None:
    await create(imports)
    seed_asset("asset_001")

    with pytest.raises(StudioImportDecisionRejected) as raised:
        await resolve(imports, "unsupported_000", attach("asset_001"))
    assert raised.value.code == "item_not_attachable"
    assert count(StudioImportDecisionRow) == 0


@needs_postgres
async def test_attach_places_the_media_clip_in_its_scene_with_the_decision(
    imports: PostgresStudioImportRepository,
) -> None:
    await create(imports)
    seed_asset()

    result = await resolve(imports, "footage_001", attach())

    entry = next(item for item in result.items if item.item_id == "footage_001")
    assert (entry.disposition, entry.asset_id, result.revision) == ("attached", "asset_clip", 2)
    document = saved()
    scene = scene_of(document, "scene_003")
    clip = clip_of(document, "clip_footage_001")
    assert (clip["kind"], clip["track_id"], clip["scene_id"], clip["asset_id"]) == (
        "video",
        "track_b_roll",
        "scene_003",
        "asset_clip",
    )
    assert (clip["from_frame"], clip["duration_in_frames"]) == (
        scene["start_frame"],
        min(60, scene["duration_in_frames"]),
    )
    assert [ref["asset_id"] for ref in document["asset_refs"]] == ["asset_clip"]
    with editor_sessions(DATABASE_URL)() as session:
        decision = session.scalar(select(StudioImportDecisionRow))
    assert decision is not None
    assert (decision.item_id, decision.revision, decision.disposition, decision.asset_id) == (
        "footage_001",
        2,
        "attached",
        "asset_clip",
    )


@needs_postgres
async def test_the_main_item_starts_at_its_trim_on_the_main_video_track(
    imports: PostgresStudioImportRepository,
) -> None:
    await create(imports)
    seed_asset(duration=900)

    await resolve(imports, "main_000", attach())

    document = saved()
    clip = clip_of(document, "clip_main_000")
    assert (clip["track_id"], clip["scene_id"]) == ("track_main_video", "scene_001")
    # The source skips its first 1.5 s: 45 frames at 30 fps, leaving 855 to play.
    assert (clip["source_from_frame"], clip["duration_in_frames"]) == (45, 855)
    assert scene_of(document, "scene_001")["duration_in_frames"] == 855
    assert scene_of(document, "scene_002")["start_frame"] == 855


@needs_postgres
async def test_a_footage_scene_takes_the_length_of_its_source(
    imports: PostgresStudioImportRepository,
) -> None:
    await create(imports)
    seed_asset(duration=240)

    await resolve(imports, "footage_001", attach())

    document = saved()
    scene = scene_of(document, "scene_003")
    clip = clip_of(document, "clip_footage_001")
    assert (clip["source_from_frame"], clip["duration_in_frames"]) == (0, 240)
    assert scene["duration_in_frames"] == 240
    assert scene_of(document, "scene_004")["start_frame"] == scene["start_frame"] + 240


@needs_postgres
async def test_main_footage_stays_within_the_main_scene(
    imports: PostgresStudioImportRepository,
) -> None:
    await create(imports)
    seed_asset(duration=900)

    await resolve(imports, "main_footage_000", attach())

    document = saved()
    scene = scene_of(document, "scene_001")
    clip = clip_of(document, "clip_main_footage_000")
    assert scene["duration_in_frames"] == DRAFT.scenes[0].duration_in_frames
    assert (clip["track_id"], clip["duration_in_frames"]) == (
        "track_b_roll",
        scene["duration_in_frames"],
    )


@needs_postgres
@pytest.mark.parametrize(
    ("item_id", "duration", "code"),
    [
        ("main_000", 45, "trim_exceeds_asset"),
        ("main_000", None, "asset_duration_unknown"),
        ("footage_001", None, "asset_duration_unknown"),
    ],
)
async def test_a_source_range_the_asset_cannot_hold_leaves_the_item_unresolved(
    imports: PostgresStudioImportRepository, item_id: str, duration: int | None, code: str
) -> None:
    await create(imports)
    seed_asset(duration=duration)

    with pytest.raises(StudioImportDecisionRejected) as raised:
        await resolve(imports, item_id, attach())

    assert raised.value.code == code
    assert (count(EditDocumentRevisionRow), count(StudioImportDecisionRow)) == (1, 0)


@needs_postgres
async def test_an_image_item_takes_a_still_for_the_whole_scene(
    imports: PostgresStudioImportRepository,
) -> None:
    await create(imports)
    seed_asset("asset_still", "image", None)

    await resolve(imports, "comment_000", attach("asset_still"))

    document = saved()
    clip = clip_of(document, "clip_comment_000")
    assert clip["duration_in_frames"] == scene_of(document, "scene_006")["duration_in_frames"]


@needs_postgres
async def test_attach_refuses_an_asset_that_is_not_ready_in_this_project(
    imports: PostgresStudioImportRepository,
) -> None:
    await create(imports)
    seed_asset("asset_elsewhere", project_id="project_other")
    seed_asset("asset_pending", state="pending")

    for asset_id in ("asset_elsewhere", "asset_pending", "asset_none"):
        with pytest.raises(StudioImportDecisionRejected) as raised:
            await resolve(imports, "footage_001", attach(asset_id))
        assert raised.value.code == "asset_unavailable"
    assert (count(EditDocumentRevisionRow), count(StudioImportDecisionRow)) == (1, 0)


@needs_postgres
async def test_attach_refuses_an_asset_of_another_media_kind(
    imports: PostgresStudioImportRepository,
) -> None:
    await create(imports)
    seed_asset("asset_voice", "audio", 60)

    with pytest.raises(StudioImportDecisionRejected) as raised:
        await resolve(imports, "footage_001", attach("asset_voice"))

    assert raised.value.code == "asset_kind_mismatch"
    assert count(EditDocumentRevisionRow) == 1


@needs_postgres
async def test_attach_refuses_a_document_that_cannot_take_the_clip(
    imports: PostgresStudioImportRepository,
) -> None:
    locked = DRAFT.model_dump(mode="json")
    for track in locked["tracks"]:
        track["locked"] = track["locked"] or track["track_id"] == "track_b_roll"
    await create(imports, document=EditDocumentV2.model_validate(locked))
    seed_asset()

    with pytest.raises(StudioImportDecisionRejected) as raised:
        await resolve(imports, "footage_001", attach())

    assert raised.value.code == "attach_rejected"
    assert count(EditDocumentRevisionRow) == 1


@needs_postgres
async def test_an_attached_item_cannot_be_resolved_again(
    imports: PostgresStudioImportRepository,
) -> None:
    await create(imports)
    seed_asset()
    seed_asset("asset_other")
    await resolve(imports, "footage_001", attach())

    with pytest.raises(StudioImportItemResolved):
        await resolve(imports, "footage_001", attach("asset_other"), 2)
    assert count(StudioImportDecisionRow) == 1


@needs_postgres
async def test_attach_at_a_stale_revision_is_a_conflict(
    imports: PostgresStudioImportRepository,
) -> None:
    await create(imports)
    seed_asset()
    await resolve(imports, "unsupported_000", ExcludeImportItem(kind="exclude"))

    with pytest.raises(EditDocumentRevisionConflict) as raised:
        await resolve(imports, "footage_001", attach())

    assert raised.value.latest.revision == 2
    assert count(EditDocumentRevisionRow) == 2


@needs_postgres
async def test_a_refused_decision_rolls_back_the_attached_clip(
    imports: PostgresStudioImportRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    await create(imports)
    seed_asset()

    def refused_decision(**fields: Any) -> StudioImportDecisionRow:
        # A disposition the decision table refuses, after the revision was written.
        return StudioImportDecisionRow(**{**fields, "disposition": "bogus"})

    monkeypatch.setattr(studio_import_repository, "StudioImportDecisionRow", refused_decision)

    with pytest.raises(EditDocumentPersistenceError) as raised:
        await resolve(imports, "footage_001", attach())

    assert "postgresql" not in str(raised.value)
    assert (count(EditDocumentRevisionRow), count(StudioImportDecisionRow)) == (1, 0)


@needs_postgres
async def test_a_not_placed_exclusion_reads_back_with_its_reason(
    imports: PostgresStudioImportRepository,
) -> None:
    await create(imports)

    await resolve(imports, "footage_000", ExcludeImportItem(kind="exclude", reason="not_placed"))

    result = await imports.get_inventory(project_id=PROJECT, document_id=DOCUMENT)
    assert result is not None
    entry = {entry.item_id: entry for entry in result.items}["footage_000"]
    assert entry.disposition == "excluded"
    assert entry.reason == "Not placed: no room in the reaction beat"

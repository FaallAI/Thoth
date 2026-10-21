"""PostgreSQL persistence for Studio drafts, their source inventory, and item decisions."""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter

from thoth_control_plane.application.edit_documents import EditDocumentNotFound
from thoth_control_plane.application.ports import (
    EditDocumentRevisionConflict,
    StudioImportConflict,
    StudioImportDecisionRejected,
    StudioImportItemNotFound,
    StudioImportItemResolved,
)
from thoth_control_plane.domain.edit_document_operations import (
    EditDocumentOperation,
    SetSceneDuration,
    apply_edit_operations,
)
from thoth_control_plane.domain.edit_document_v2 import EditDocument, EditDocumentV2
from thoth_control_plane.domain.studio_imports import (
    NOT_PLACED,
    OVERLAY_ROLES,
    AttachImportAsset,
    ExcludeImportItem,
    StudioDraft,
    StudioImportInventory,
    StudioImportItem,
)
from thoth_control_plane.domain.studio_layout import (
    CARD_GAP,
    READING_MIN,
    SLIDE_SECONDS,
    card_position,
    clip_regions,
    profile_slot,
    reaction_beat,
)
from thoth_control_plane.domain.timeline_operations import AddClipFromAsset
from thoth_control_plane.infrastructure.editor_repository import (
    DOCUMENT_ADAPTER,
    EditDocumentPersistenceError,
    PostgresEditDocumentRepository,
)

INVENTORY_ADAPTER: TypeAdapter[list[StudioImportItem]] = TypeAdapter(list[StudioImportItem])
TYPED = (
    EditDocumentNotFound,
    EditDocumentRevisionConflict,
    StudioImportConflict,
    StudioImportDecisionRejected,
    StudioImportItemNotFound,
    StudioImportItemResolved,
)

# Every draft query reports the document's latest revision, never the first one.
_DRAFT_COLUMNS = """
    d.document_id, d.source_key, d.created_at,
    (SELECT max(r.revision) FROM edit_document_revisions r
     WHERE r.project_id = d.project_id AND r.document_id = d.document_id)
"""


def _draft(row: Any) -> StudioDraft:
    return StudioDraft(document_id=row[0], source_key=row[1], created_at=row[2], revision=row[3])


class PostgresStudioImportRepository:
    """Open one short-lived async connection per operation; rows are never updated."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    async def create_draft(
        self,
        *,
        project_id: str,
        source_key: str,
        idempotency_key: str,
        document: EditDocumentV2,
        inventory: list[StudioImportItem],
    ) -> StudioDraft:
        try:
            connection = await AsyncConnection.connect(self._database_url)
            async with connection:
                cursor = connection.cursor()
                await cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                    (project_id, f"studio-import:{idempotency_key}"),
                )
                await cursor.execute(
                    f"""
                    SELECT {_DRAFT_COLUMNS}
                    FROM studio_import_drafts d
                    WHERE d.project_id = %s AND d.idempotency_key = %s
                    """,
                    (project_id, idempotency_key),
                )
                recorded = await cursor.fetchone()
                if recorded is not None:
                    if recorded[1] != source_key:
                        raise StudioImportConflict()
                    return _draft(recorded)

                await PostgresEditDocumentRepository._insert_revision(cursor, document)
                await cursor.execute(
                    """
                    INSERT INTO studio_import_drafts
                        (project_id, document_id, first_revision, source_key, idempotency_key,
                         inventory)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING created_at
                    """,
                    (
                        project_id,
                        document.document_id,
                        document.revision,
                        source_key,
                        idempotency_key,
                        Jsonb([entry.model_dump(mode="json") for entry in inventory]),
                    ),
                )
                created = await cursor.fetchone()
                if created is None:
                    raise EditDocumentPersistenceError()
                return StudioDraft(
                    document_id=document.document_id,
                    source_key=source_key,
                    revision=document.revision,
                    created_at=created[0],
                )
        except TYPED:
            raise
        except EditDocumentPersistenceError:
            raise
        except Exception as error:
            raise EditDocumentPersistenceError() from error

    async def list_drafts(
        self, *, project_id: str, source_key: str, limit: int
    ) -> list[StudioDraft]:
        try:
            connection = await AsyncConnection.connect(self._database_url)
            async with connection:
                cursor = connection.cursor()
                await cursor.execute(
                    f"""
                    SELECT {_DRAFT_COLUMNS}
                    FROM studio_import_drafts d
                    WHERE d.project_id = %s AND d.source_key = %s
                    ORDER BY d.created_at DESC, d.document_id DESC
                    LIMIT %s
                    """,
                    (project_id, source_key, limit),
                )
                return [_draft(row) for row in await cursor.fetchall()]
        except Exception as error:
            raise EditDocumentPersistenceError() from error

    async def get_inventory(
        self, *, project_id: str, document_id: str
    ) -> StudioImportInventory | None:
        try:
            connection = await AsyncConnection.connect(self._database_url)
            async with connection:
                return await self._inventory(connection.cursor(), project_id, document_id)
        except Exception as error:
            raise EditDocumentPersistenceError() from error

    async def resolve_item(
        self,
        *,
        project_id: str,
        document_id: str,
        item_id: str,
        base_revision: int,
        decision: ExcludeImportItem | AttachImportAsset,
    ) -> StudioImportInventory:
        try:
            connection = await AsyncConnection.connect(self._database_url)
            async with connection:
                cursor = connection.cursor()
                # The editor's own lock: no patch can land between the check and the insert.
                await cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                    (project_id, document_id),
                )
                current = await self._inventory(cursor, project_id, document_id)
                if current is None:
                    raise EditDocumentNotFound()
                entry = next((item for item in current.items if item.item_id == item_id), None)
                if entry is None:
                    raise StudioImportItemNotFound()
                if entry.disposition != "unresolved":
                    raise StudioImportItemResolved()
                asset_id = decision.asset_id if isinstance(decision, AttachImportAsset) else None
                reason = decision.reason if isinstance(decision, ExcludeImportItem) else None
                disposition = "excluded" if asset_id is None else "attached"
                if asset_id and (entry.media_kind == "none" or entry.scene_id is None):
                    raise StudioImportDecisionRejected("item_not_attachable")

                await cursor.execute(
                    """
                    SELECT document_json
                    FROM edit_document_revisions
                    WHERE project_id = %s AND document_id = %s
                    ORDER BY revision DESC LIMIT 1
                    FOR UPDATE
                    """,
                    (project_id, document_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise EditDocumentPersistenceError()
                latest = DOCUMENT_ADAPTER.validate_python(row[0])
                if latest.revision != base_revision:
                    raise EditDocumentRevisionConflict(latest)
                # Excluding changes no content; the new revision records when it was decided.
                updated = (
                    latest
                    if asset_id is None
                    else await self._attached(cursor, latest, entry, asset_id, current)
                )
                result = DOCUMENT_ADAPTER.validate_python(
                    {**updated.model_dump(mode="json"), "revision": latest.revision + 1}
                )
                await PostgresEditDocumentRepository._insert_revision(cursor, result)
                await cursor.execute(
                    """
                    INSERT INTO studio_import_decisions
                        (project_id, document_id, item_id, revision, disposition, asset_id, reason)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        project_id,
                        document_id,
                        item_id,
                        result.revision,
                        disposition,
                        asset_id,
                        reason,
                    ),
                )
                return current.model_copy(
                    update={
                        "revision": result.revision,
                        "items": [
                            item.model_copy(
                                update={
                                    "disposition": disposition,
                                    "asset_id": asset_id,
                                    **({"reason": NOT_PLACED} if reason == "not_placed" else {}),
                                }
                            )
                            if item.item_id == item_id
                            else item
                            for item in current.items
                        ],
                    }
                )
        except TYPED:
            raise
        except EditDocumentPersistenceError:
            raise
        except Exception as error:
            raise EditDocumentPersistenceError() from error

    @staticmethod
    async def _attached(
        cursor: Any,
        latest: EditDocument,
        entry: StudioImportItem,
        asset_id: str,
        current: StudioImportInventory,
    ) -> EditDocument:
        """``latest`` with the item's ready asset placed in its scene.

        The main item fills the main video track; every other item is b-roll over its scene.
        A video plays from its trim to its end and its scene takes that length; main footage
        stays within the main scene, and a still fills its scene.
        """
        asset = (
            await PostgresEditDocumentRepository.ready_assets(cursor, latest.project_id, [asset_id])
        ).get(asset_id)
        if asset is None:
            raise StudioImportDecisionRejected("asset_unavailable")
        if asset.kind != entry.media_kind:
            raise StudioImportDecisionRejected("asset_kind_mismatch")
        scene = next((scene for scene in latest.scenes if scene.scene_id == entry.scene_id), None)
        if scene is None:
            raise StudioImportDecisionRejected("item_not_attachable")
        if entry.role in OVERLAY_ROLES:
            return _overlay(latest, entry, asset, scene, current)
        slides = sum(1 for item in current.items if item.role == "slide")
        operations: list[EditDocumentOperation] = []
        source_from = 0
        duration = scene.duration_in_frames
        if entry.media_kind == "video":
            # Asset lengths are on the canvas clock, so the trim converts at the same rate.
            if asset.duration_in_frames is None:
                raise StudioImportDecisionRejected("asset_duration_unknown")
            source_from = round((entry.trim_start_seconds or 0) * latest.canvas.fps)
            if source_from >= asset.duration_in_frames:
                raise StudioImportDecisionRejected("trim_exceeds_asset")
            duration = asset.duration_in_frames - source_from
            if entry.role == "main_footage":
                duration = min(duration, scene.duration_in_frames)
            elif duration != scene.duration_in_frames:
                operations.append(
                    SetSceneDuration(
                        kind="set_scene_duration",
                        operation_id=f"fit_{entry.item_id}",
                        scene_id=scene.scene_id,
                        duration_in_frames=duration,
                    )
                )
        elif entry.role == "main" and slides:
            # A carousel: the first image, then each slide, SLIDE_SECONDS apiece (spec 5c-1, 3.3).
            duration = round(SLIDE_SECONDS * latest.canvas.fps)
            operations.append(
                SetSceneDuration(
                    kind="set_scene_duration",
                    operation_id=f"fit_{entry.item_id}",
                    scene_id=scene.scene_id,
                    duration_in_frames=duration * (1 + slides),
                )
            )
        operations.append(
            AddClipFromAsset(
                kind="add_clip_from_asset",
                operation_id=f"attach_{entry.item_id}",
                clip_id=f"clip_{entry.item_id}",
                track_id="track_main_video" if entry.role == "main" else "track_b_roll",
                asset_id=asset_id,
                # Resizing a scene never moves its own start.
                from_frame=scene.start_frame,
                duration_in_frames=duration,
                source_from_frame=source_from,
                scene_id=scene.scene_id,
            )
        )
        try:
            document = apply_edit_operations(latest, operations, resolved_assets={asset_id: asset})
        except ValueError as error:
            raise StudioImportDecisionRejected("attach_rejected") from error
        if entry.role == "main" and slides:
            # Every image of a carousel is letterboxed alike, so the framing never jumps.
            _clip(document, f"clip_{entry.item_id}").fit = "contain"
        if entry.blur_regions:
            # Stored and switched off until narration replaces the speech (spec 5c-1, 6).
            clip = _clip(document, f"clip_{entry.item_id}")
            clip.blur_regions = clip_regions(entry.blur_regions, latest.canvas.fps, source_from)
        return document

    @staticmethod
    async def _inventory(
        cursor: Any, project_id: str, document_id: str
    ) -> StudioImportInventory | None:
        await cursor.execute(
            """
            SELECT d.source_key, d.inventory,
                (SELECT max(r.revision) FROM edit_document_revisions r
                 WHERE r.project_id = d.project_id AND r.document_id = d.document_id)
            FROM studio_import_drafts d
            WHERE d.project_id = %s AND d.document_id = %s
            """,
            (project_id, document_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        await cursor.execute(
            """
            SELECT item_id, disposition, asset_id, reason
            FROM studio_import_decisions
            WHERE project_id = %s AND document_id = %s
            """,
            (project_id, document_id),
        )
        decided = {
            item_id: (disposition, asset_id, reason)
            for item_id, disposition, asset_id, reason in await cursor.fetchall()
        }
        items = [
            item.model_copy(
                update={
                    "disposition": decided[item.item_id][0],
                    "asset_id": decided[item.item_id][1],
                    **({"reason": NOT_PLACED} if decided[item.item_id][2] == "not_placed" else {}),
                }
            )
            if item.item_id in decided
            else item
            for item in INVENTORY_ADAPTER.validate_python(row[1])
        ]
        return StudioImportInventory(
            document_id=document_id, source_key=row[0], revision=row[2], items=items
        )


def _clip(document: EditDocument, clip_id: str) -> Any:
    return next(clip for clip in document.clips if clip.clip_id == clip_id)


def _overlay(
    latest: EditDocument,
    entry: StudioImportItem,
    asset: Any,
    scene: Any,
    current: StudioImportInventory,
) -> EditDocument:
    """A slide, the profile card or a comment card placed over the main scene (spec 5c-1, 7).

    The main scene's length decides every slot, so nothing is placed before the main is.
    """
    main = next((item for item in current.items if item.item_id == "main_000"), None)
    if main is None or main.disposition != "attached":
        raise StudioImportDecisionRejected("main_not_attached")
    canvas = latest.canvas
    seconds = scene.duration_in_frames / canvas.fps
    position = card_position(asset.width, asset.height, (canvas.width, canvas.height))
    track = "track_b_roll"
    if entry.role == "slide":
        track, position = "track_main_video", None
        at, length = (entry.order + 1) * SLIDE_SECONDS, SLIDE_SECONDS
    elif entry.role == "profile_card":
        at, length = profile_slot(seconds)
    else:
        cards = sorted(
            (item for item in current.items if item.role == "comment_card"),
            key=lambda item: item.order or 0,
        )
        has_profile = any(item.role == "profile_card" for item in current.items)
        not_before = sum(profile_slot(seconds)) + CARD_GAP if has_profile else 0.0
        reading = [item.reading_seconds or READING_MIN for item in cards]
        slot = reaction_beat(seconds, reading, not_before=not_before)[entry.order or 0]
        if slot is None:
            raise StudioImportDecisionRejected("no_room_in_reaction_beat")
        at, length = slot
    clip_id = f"clip_{entry.item_id}"
    operation = AddClipFromAsset(
        kind="add_clip_from_asset",
        operation_id=f"attach_{entry.item_id}",
        clip_id=clip_id,
        track_id=track,
        asset_id=asset.asset_id,
        from_frame=scene.start_frame + round(at * canvas.fps),
        duration_in_frames=max(1, round(length * canvas.fps)),
        source_from_frame=0,
        scene_id=scene.scene_id,
    )
    try:
        document = apply_edit_operations(
            latest, [operation], resolved_assets={asset.asset_id: asset}
        )
    except ValueError as error:
        raise StudioImportDecisionRejected("attach_rejected") from error
    clip = _clip(document, clip_id)
    clip.fit = "contain"
    clip.position = position
    return document

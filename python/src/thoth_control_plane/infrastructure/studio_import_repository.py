"""PostgreSQL persistence for Studio drafts, their source inventory, and item decisions.

SQLAlchemy ORM on the shared editor pool (ORM spec 2026-10-26); async callers reach the
synchronous session through `asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
    STILL_ROLES,
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
    post_card_slot,
    profile_slot,
    reaction_beat,
)
from thoth_control_plane.domain.timeline_operations import AddClipFromAsset
from thoth_control_plane.infrastructure.editor_database import advisory_xact_lock, editor_sessions
from thoth_control_plane.infrastructure.editor_models import (
    EditDocumentRevisionRow,
    StudioImportDecisionRow,
    StudioImportDraftRow,
)
from thoth_control_plane.infrastructure.editor_repository import (
    DOCUMENT_ADAPTER,
    EditDocumentPersistenceError,
    PostgresEditDocumentRepository,
    latest_revision_for_update,
)

T = TypeVar("T")

INVENTORY_ADAPTER: TypeAdapter[list[StudioImportItem]] = TypeAdapter(list[StudioImportItem])
TYPED = (
    EditDocumentNotFound,
    EditDocumentRevisionConflict,
    StudioImportConflict,
    StudioImportDecisionRejected,
    StudioImportItemNotFound,
    StudioImportItemResolved,
)


def _latest_revision():  # type: ignore[no-untyped-def]
    """Every draft query reports the document's latest revision, never the first one."""
    return (
        select(func.max(EditDocumentRevisionRow.revision))
        .where(
            EditDocumentRevisionRow.project_id == StudioImportDraftRow.project_id,
            EditDocumentRevisionRow.document_id == StudioImportDraftRow.document_id,
        )
        .correlate(StudioImportDraftRow)
        .scalar_subquery()
    )


def _drafts():  # type: ignore[no-untyped-def]
    return select(
        StudioImportDraftRow.document_id,
        StudioImportDraftRow.source_key,
        StudioImportDraftRow.created_at,
        _latest_revision(),
    )


def _draft(row: Any) -> StudioDraft:
    return StudioDraft(document_id=row[0], source_key=row[1], created_at=row[2], revision=row[3])


class PostgresStudioImportRepository:
    """One short transaction per operation, on the shared editor pool; rows are never updated."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    async def _run(self, work: Callable[[Session], T]) -> T:
        """Run `work(session)` in one transaction. Typed outcomes pass through; any other
        failure is the safe persistence error."""

        def unit() -> T:
            with editor_sessions(self._database_url).begin() as session:
                return work(session)

        try:
            return await asyncio.to_thread(unit)
        except (*TYPED, EditDocumentPersistenceError):
            raise
        except Exception as error:
            raise EditDocumentPersistenceError() from error

    async def create_draft(
        self,
        *,
        project_id: str,
        source_key: str,
        idempotency_key: str,
        document: EditDocumentV2,
        inventory: list[StudioImportItem],
        source_workflow_id: str | None = None,
    ) -> StudioDraft:
        def write(session: Session) -> StudioDraft:
            advisory_xact_lock(session, project_id, f"studio-import:{idempotency_key}")
            recorded = session.execute(
                _drafts().where(
                    StudioImportDraftRow.project_id == project_id,
                    StudioImportDraftRow.idempotency_key == idempotency_key,
                )
            ).first()
            if recorded is not None:
                if recorded[1] != source_key:
                    raise StudioImportConflict()
                return _draft(recorded)

            PostgresEditDocumentRepository._insert_revision(session, document)
            # The draft references its first revision, so the revision goes first.
            session.flush()
            draft = StudioImportDraftRow(
                project_id=project_id,
                document_id=document.document_id,
                first_revision=document.revision,
                source_key=source_key,
                idempotency_key=idempotency_key,
                inventory=[entry.model_dump(mode="json") for entry in inventory],
                source_workflow_id=source_workflow_id,
            )
            session.add(draft)
            session.flush()
            # The database stamps `created_at`, as the psycopg INSERT ... RETURNING did.
            session.refresh(draft, ["created_at"])
            return StudioDraft(
                document_id=document.document_id,
                source_key=source_key,
                revision=document.revision,
                created_at=draft.created_at,
            )

        return await self._run(write)

    async def list_drafts(
        self, *, project_id: str, source_key: str, limit: int
    ) -> list[StudioDraft]:
        def read(session: Session) -> list[StudioDraft]:
            rows = session.execute(
                _drafts()
                .where(
                    StudioImportDraftRow.project_id == project_id,
                    StudioImportDraftRow.source_key == source_key,
                )
                .order_by(
                    StudioImportDraftRow.created_at.desc(), StudioImportDraftRow.document_id.desc()
                )
                .limit(limit)
            ).all()
            return [_draft(row) for row in rows]

        return await self._run(read)

    async def get_inventory(
        self, *, project_id: str, document_id: str
    ) -> StudioImportInventory | None:
        return await self._run(lambda session: self._inventory(session, project_id, document_id))

    async def resolve_item(
        self,
        *,
        project_id: str,
        document_id: str,
        item_id: str,
        base_revision: int,
        decision: ExcludeImportItem | AttachImportAsset,
    ) -> StudioImportInventory:
        def write(session: Session) -> StudioImportInventory:
            # The editor's own lock: no patch can land between the check and the insert.
            advisory_xact_lock(session, project_id, document_id)
            current = self._inventory(session, project_id, document_id)
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

            latest = latest_revision_for_update(session, project_id, document_id)
            if latest is None:
                raise EditDocumentPersistenceError()
            if latest.revision != base_revision:
                raise EditDocumentRevisionConflict(latest)
            # Excluding changes no content; the new revision records when it was decided.
            updated = (
                latest
                if asset_id is None
                else self._attached(session, latest, entry, asset_id, current)
            )
            result = DOCUMENT_ADAPTER.validate_python(
                {**updated.model_dump(mode="json"), "revision": latest.revision + 1}
            )
            PostgresEditDocumentRepository._insert_revision(session, result)
            # The decision references the new revision, so the revision goes first.
            session.flush()
            session.add(
                StudioImportDecisionRow(
                    project_id=project_id,
                    document_id=document_id,
                    item_id=item_id,
                    revision=result.revision,
                    disposition=disposition,
                    asset_id=asset_id,
                    reason=reason,
                )
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

        return await self._run(write)

    @staticmethod
    def _attached(
        session: Session,
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
        asset = PostgresEditDocumentRepository.ready_assets(
            session, latest.project_id, [asset_id]
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
        elif entry.role in STILL_ROLES:
            # The profile page and each creator photo hold SLIDE_SECONDS (spec 5c-2, G5).
            duration = round(SLIDE_SECONDS * latest.canvas.fps)
            if duration != scene.duration_in_frames:
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
                source_role=entry.role,
            )
        )
        try:
            document = apply_edit_operations(latest, operations, resolved_assets={asset_id: asset})
        except ValueError as error:
            raise StudioImportDecisionRejected("attach_rejected") from error
        if (entry.role == "main" and slides) or entry.role in STILL_ROLES:
            # Every image of a carousel is letterboxed alike, so the framing never jumps; a
            # profile page or a photo is shown whole.
            _clip(document, f"clip_{entry.item_id}").fit = "contain"
        if entry.blur_regions:
            # Stored and switched off until narration replaces the speech (spec 5c-1, 6).
            clip = _clip(document, f"clip_{entry.item_id}")
            clip.blur_regions = clip_regions(entry.blur_regions, latest.canvas.fps, source_from)
        return document

    @staticmethod
    def _inventory(
        session: Session, project_id: str, document_id: str
    ) -> StudioImportInventory | None:
        row = session.execute(
            select(
                StudioImportDraftRow.source_key,
                StudioImportDraftRow.inventory,
                _latest_revision(),
            ).where(
                StudioImportDraftRow.project_id == project_id,
                StudioImportDraftRow.document_id == document_id,
            )
        ).first()
        if row is None:
            return None
        decided = {
            decision.item_id: (decision.disposition, decision.asset_id, decision.reason)
            for decision in session.scalars(
                select(StudioImportDecisionRow).where(
                    StudioImportDecisionRow.project_id == project_id,
                    StudioImportDecisionRow.document_id == document_id,
                )
            )
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
    # The post opens the video for its reading time, then who posted it (spec 5c-2, G5).
    post = next((item for item in current.items if item.role == "post_card"), None)
    after_post = (
        sum(post_card_slot(seconds, post.reading_seconds or READING_MIN)) + CARD_GAP
        if post is not None
        else 0.0
    )
    if entry.role == "slide":
        track, position = "track_main_video", None
        at, length = (entry.order + 1) * SLIDE_SECONDS, SLIDE_SECONDS
    elif entry.role == "post_card":
        at, length = post_card_slot(seconds, entry.reading_seconds or READING_MIN)
    elif entry.role == "profile_card":
        at, length = profile_slot(seconds, not_before=after_post)
    else:
        cards = sorted(
            (item for item in current.items if item.role == "comment_card"),
            key=lambda item: item.order or 0,
        )
        has_profile = any(item.role == "profile_card" for item in current.items)
        not_before = (
            sum(profile_slot(seconds, not_before=after_post)) + CARD_GAP
            if has_profile
            else after_post
        )
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
        fit="contain",
        position=position,
        source_role=entry.role,
    )
    try:
        return apply_edit_operations(latest, [operation], resolved_assets={asset.asset_id: asset})
    except ValueError as error:
        raise StudioImportDecisionRejected("attach_rejected") from error

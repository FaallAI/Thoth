"""PostgreSQL persistence for immutable Creator Studio document revisions.

SQLAlchemy ORM on the shared editor pool (ORM spec 2026-10-26); async callers reach the
synchronous session through `asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from typing import TypeVar

from pydantic import TypeAdapter
from sqlalchemy import exists, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from thoth_control_plane.application.ports import (
    EditDocumentRevisionConflict,
    EditDocumentUpgradeConflict,
)
from thoth_control_plane.domain.cursors import decode_cursor, encode_cursor
from thoth_control_plane.domain.edit_document_list import (
    EditDocumentListItem,
    EditDocumentListPage,
    document_label,
)
from thoth_control_plane.domain.edit_document_operations import (
    EditDocumentOperation,
    apply_edit_operations,
)
from thoth_control_plane.domain.edit_document_upgrade import upgrade_edit_document_v1
from thoth_control_plane.domain.edit_document_v2 import AssetRef, EditDocument, EditDocumentV2
from thoth_control_plane.domain.edit_documents import EditDocumentV1
from thoth_control_plane.domain.timeline_operations import AddClipFromAsset
from thoth_control_plane.infrastructure.editor_database import advisory_xact_lock, editor_sessions
from thoth_control_plane.infrastructure.editor_models import (
    EditDocumentRevisionRow,
    EditDocumentUpgradeIdempotencyRow,
    EditorAssetRow,
    StudioImportDraftRow,
)

T = TypeVar("T")

DOCUMENT_ADAPTER: TypeAdapter[EditDocument] = TypeAdapter(EditDocument)

LIST_LIMIT_MAX = 50

#: PostgreSQL's unique_violation: the revision already exists.
_UNIQUE_VIOLATION = "23505"


def _upgrade_payload_hash(project_id: str, document_id: str, base_revision: int) -> str:
    """Hash the canonical upgrade request so no raw request is ever retained."""
    canonical = f"{project_id}|{document_id}|{base_revision}".encode()
    return hashlib.sha256(canonical).hexdigest()


class EditDocumentConflict(Exception):
    """A revision already exists and cannot be overwritten."""

    def __init__(self) -> None:
        super().__init__("edit document revision already exists")


class EditDocumentPersistenceError(Exception):
    """The editor store is unavailable without leaking connection details."""

    def __init__(self) -> None:
        super().__init__("edit document persistence unavailable")


def latest_revision_for_update(
    session: Session, project_id: str, document_id: str
) -> EditDocument | None:
    """The document's newest revision, row-locked for the rest of the transaction."""
    row = session.scalar(
        select(EditDocumentRevisionRow)
        .where(
            EditDocumentRevisionRow.project_id == project_id,
            EditDocumentRevisionRow.document_id == document_id,
        )
        .order_by(EditDocumentRevisionRow.revision.desc())
        .limit(1)
        .with_for_update()
    )
    return None if row is None else DOCUMENT_ADAPTER.validate_python(row.document_json)


class PostgresEditDocumentRepository:
    """One short transaction per immutable repository operation, on the shared editor pool."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    async def _run(
        self,
        work: Callable[[Session], T],
        passthrough: tuple[type[Exception], ...] = (),
    ) -> T:
        """Run `work(session)` in one transaction. Typed outcomes pass through; any other
        failure is the safe persistence error."""

        def unit() -> T:
            with editor_sessions(self._database_url).begin() as session:
                return work(session)

        try:
            return await asyncio.to_thread(unit)
        except (*passthrough, EditDocumentPersistenceError):
            raise
        except Exception as error:
            raise EditDocumentPersistenceError() from error

    async def insert_revision(self, document: EditDocument) -> None:
        def write(session: Session) -> None:
            self._insert_revision(session, document)
            session.flush()

        try:
            await self._run(write)
        except EditDocumentPersistenceError as error:
            cause = error.__cause__
            if (
                isinstance(cause, IntegrityError)
                and getattr(cause.orig, "sqlstate", None) == _UNIQUE_VIOLATION
            ):
                raise EditDocumentConflict() from cause
            raise

    async def get_latest(self, *, project_id: str, document_id: str) -> EditDocument | None:
        def read(session: Session) -> EditDocument | None:
            document_json = session.scalar(
                select(EditDocumentRevisionRow.document_json)
                .where(
                    EditDocumentRevisionRow.project_id == project_id,
                    EditDocumentRevisionRow.document_id == document_id,
                )
                .order_by(EditDocumentRevisionRow.revision.desc())
                .limit(1)
            )
            return (
                None if document_json is None else DOCUMENT_ADAPTER.validate_python(document_json)
            )

        return await self._run(read)

    async def list_documents(
        self, *, project_id: str, limit: int, cursor: str | None
    ) -> EditDocumentListPage:
        clamped = max(1, min(int(limit), LIST_LIMIT_MAX))
        # A bad cursor is the client's error (InvalidCursor -> 422), never a persistence failure.
        keyset = decode_cursor(cursor) if cursor else None

        def read(session: Session) -> EditDocumentListPage:
            # The newest revision of each document in one project, newest first, by keyset.
            revision = EditDocumentRevisionRow
            latest = (
                select(
                    revision.document_id,
                    revision.revision,
                    revision.created_at,
                    revision.document_json,
                )
                .where(revision.project_id == project_id)
                .distinct(revision.document_id)
                .order_by(revision.document_id, revision.revision.desc())
                .cte("latest")
            )
            imported = (
                exists()
                .where(
                    StudioImportDraftRow.project_id == project_id,
                    StudioImportDraftRow.document_id == latest.c.document_id,
                )
                .label("imported")
            )
            query = select(
                latest.c.document_id,
                latest.c.revision,
                latest.c.created_at,
                latest.c.document_json,
                imported,
            )
            if keyset:
                query = query.where(
                    tuple_(latest.c.created_at, latest.c.document_id) < tuple_(*keyset)
                )
            rows = session.execute(
                query.order_by(latest.c.created_at.desc(), latest.c.document_id.desc()).limit(
                    clamped + 1
                )
            ).all()
            page = rows[:clamped]
            items = [
                EditDocumentListItem(
                    document_id=document_id,
                    revision=number,
                    updated_at=created_at,
                    label=document_label(document_json),
                    imported=was_imported,
                )
                for document_id, number, created_at, document_json, was_imported in page
            ]
            next_cursor = encode_cursor(page[-1][2], page[-1][0]) if len(rows) > clamped else None
            return EditDocumentListPage(items=items, next_cursor=next_cursor)

        return await self._run(read)

    async def get_revision(
        self, *, project_id: str, document_id: str, revision: int
    ) -> EditDocument | None:
        def read(session: Session) -> EditDocument | None:
            row = session.get(EditDocumentRevisionRow, (document_id, revision))
            if row is None or row.project_id != project_id:
                return None
            return DOCUMENT_ADAPTER.validate_python(row.document_json)

        return await self._run(read)

    async def apply_operations(
        self,
        project_id: str,
        document_id: str,
        base_revision: int,
        operations: list[EditDocumentOperation],
    ) -> EditDocument:
        def write(session: Session) -> EditDocument:
            advisory_xact_lock(session, project_id, document_id)
            latest = latest_revision_for_update(session, project_id, document_id)
            if latest is None:
                raise EditDocumentPersistenceError()
            if latest.revision != base_revision:
                raise EditDocumentRevisionConflict(latest)
            resolved = self._resolve_assets(session, project_id, operations)
            updated = apply_edit_operations(latest, operations, resolved_assets=resolved)
            result = DOCUMENT_ADAPTER.validate_python(
                {**updated.model_dump(mode="json"), "revision": latest.revision + 1}
            )
            self._insert_revision(session, result)
            return result

        return await self._run(write, (EditDocumentRevisionConflict,))

    async def upgrade_to_timeline(
        self,
        *,
        project_id: str,
        document_id: str,
        base_revision: int,
        idempotency_key: str,
    ) -> EditDocument:
        """Append exactly one version 2 revision, replaying a recorded key safely."""
        payload_hash = _upgrade_payload_hash(project_id, document_id, base_revision)

        def write(session: Session) -> EditDocument:
            advisory_xact_lock(session, project_id, document_id)
            recorded = session.scalar(
                select(EditDocumentUpgradeIdempotencyRow)
                .where(
                    EditDocumentUpgradeIdempotencyRow.project_id == project_id,
                    EditDocumentUpgradeIdempotencyRow.idempotency_key == idempotency_key,
                )
                .with_for_update()
            )
            if recorded is not None:
                if recorded.payload_hash != payload_hash:
                    raise EditDocumentUpgradeConflict()
                return self._revision(session, project_id, document_id, recorded.result_revision)

            latest = latest_revision_for_update(session, project_id, document_id)
            if latest is None:
                raise EditDocumentPersistenceError()
            if not isinstance(latest, EditDocumentV1):
                raise EditDocumentUpgradeConflict()
            if latest.revision != base_revision:
                raise EditDocumentRevisionConflict(latest)

            upgraded = upgrade_edit_document_v1(latest)
            result = EditDocumentV2.model_validate(
                {**upgraded.model_dump(mode="json"), "revision": latest.revision + 1}
            )
            self._insert_revision(session, result)
            # The idempotency row references the revision row, so the revision goes first.
            session.flush()
            session.add(
                EditDocumentUpgradeIdempotencyRow(
                    project_id=project_id,
                    idempotency_key=idempotency_key,
                    payload_hash=payload_hash,
                    document_id=document_id,
                    result_revision=result.revision,
                )
            )
            return result

        return await self._run(write, (EditDocumentRevisionConflict, EditDocumentUpgradeConflict))

    @staticmethod
    def _insert_revision(session: Session, document: EditDocument) -> None:
        session.add(
            EditDocumentRevisionRow(
                project_id=document.project_id,
                document_id=document.document_id,
                revision=document.revision,
                document_json=document.model_dump(mode="json"),
            )
        )

    @staticmethod
    def _revision(
        session: Session, project_id: str, document_id: str, revision: int
    ) -> EditDocument:
        row = session.get(EditDocumentRevisionRow, (document_id, revision))
        if row is None or row.project_id != project_id:
            raise EditDocumentPersistenceError()
        return DOCUMENT_ADAPTER.validate_python(row.document_json)

    @staticmethod
    def _resolve_assets(
        session: Session, project_id: str, operations: list[EditDocumentOperation]
    ) -> dict[str, AssetRef]:
        """Resolve every referenced asset inside the caller's transaction.

        Only assets that are both owned by ``project_id`` and ``ready`` come
        back, and only as safe projections: the operation engine never sees an
        artifact locator, so a locator cannot enter a persisted document.
        """
        asset_ids = sorted(
            {
                operation.asset_id
                for operation in operations
                if isinstance(operation, AddClipFromAsset)
            }
        )
        return PostgresEditDocumentRepository.ready_assets(session, project_id, asset_ids)

    @staticmethod
    def ready_assets(
        session: Session, project_id: str, asset_ids: list[str]
    ) -> dict[str, AssetRef]:
        """The safe projection of each listed asset this project owns and has ready.

        The artifact locator is never selected here, so it cannot reach a persisted document.
        """
        if not asset_ids:
            return {}
        asset = EditorAssetRow
        rows = session.execute(
            select(
                asset.asset_id,
                asset.kind,
                asset.duration_in_frames,
                asset.width,
                asset.height,
                asset.fps,
                asset.has_audio,
                asset.checksum,
            ).where(
                asset.project_id == project_id,
                asset.validation_state == "ready",
                asset.asset_id.in_(asset_ids),
            )
        ).all()
        return {
            row.asset_id: AssetRef(
                asset_id=row.asset_id,
                project_id=project_id,
                kind=row.kind,
                duration_in_frames=row.duration_in_frames,
                width=row.width,
                height=row.height,
                fps=row.fps,
                has_audio=row.has_audio,
                validation_state="ready",
                checksum=row.checksum,
            )
            for row in rows
        }

"""PostgreSQL persistence for append-only, revision-bound Studio review events.

Every write runs in one short-lived transaction that first takes the same
per-document advisory lock as editor saves, so a review can never attach to a
revision that a concurrent save is superseding. Rows are only ever inserted and
read: a newer saved revision leaves earlier comments and decisions historical.

SQLAlchemy ORM on the shared editor pool (ORM spec 2026-10-26); async callers reach the
synchronous session through `asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any, TypeVar

from pydantic import TypeAdapter
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from thoth_control_plane.application.studio_review_ports import (
    InvalidStudioReviewPage,
    StudioReviewDocumentNotFound,
    StudioReviewFrameOutOfRange,
    StudioReviewIdempotencyConflict,
    StudioReviewNotEligible,
    StudioReviewPersistenceError,
    StudioReviewRevisionConflict,
)
from thoth_control_plane.domain.edit_document_v2 import EditDocument
from thoth_control_plane.domain.models import ActorSnapshot
from thoth_control_plane.domain.studio_review import (
    PAGE_LIMIT,
    CreateComment,
    CreateDecision,
    ReviewComment,
    ReviewCommentPage,
    ReviewDecision,
    ReviewDecisionPage,
    review_blocking_issues,
)
from thoth_control_plane.infrastructure.editor_database import advisory_xact_lock, editor_sessions
from thoth_control_plane.infrastructure.editor_models import (
    EditDocumentRevisionRow,
    StudioReviewEventRow,
)

T = TypeVar("T")

DOCUMENT_ADAPTER: TypeAdapter[EditDocument] = TypeAdapter(EditDocument)

_CURSOR_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
_EVENT_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,127}$")

#: Typed outcomes the application maps to fixed safe codes; never redacted.
_PASSTHROUGH = (
    StudioReviewDocumentNotFound,
    StudioReviewFrameOutOfRange,
    StudioReviewIdempotencyConflict,
    StudioReviewNotEligible,
    StudioReviewRevisionConflict,
)


def _request_hash(kind: str, request: CreateComment | CreateDecision, actor: ActorSnapshot) -> str:
    """Hash the kind, the complete request, and the author so no raw body is compared."""
    canonical = json.dumps(
        {"kind": kind, "request": request.model_dump(mode="json"), "actor": actor.actor_id},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _row_to_event(row: StudioReviewEventRow) -> ReviewComment | ReviewDecision:
    common = {
        "project_id": row.project_id,
        "document_id": row.document_id,
        "document_revision": row.revision,
        "actor": ActorSnapshot(
            actor_id=row.actor_id, actor_type=row.actor_type, display_name=row.actor_display_name
        ),
        "created_at": row.created_at,
    }
    if row.event_kind == "comment":
        return ReviewComment(
            comment_id=row.event_id, text=row.comment_text, frame=row.frame, **common
        )
    return ReviewDecision(
        decision_id=row.event_id, decision=row.decision, reason=row.reason, **common
    )


def _encode_cursor(created_at: datetime, event_id: str) -> str:
    raw = f"{created_at.isoformat()}|{event_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _page_bounds(limit: int, cursor: str | None) -> tuple[int, tuple[datetime, str] | None]:
    """Accept only an in-range limit and a cursor this server issued."""
    if not 1 <= limit <= PAGE_LIMIT:
        raise InvalidStudioReviewPage()
    if cursor is None:
        return limit, None
    if not _CURSOR_PATTERN.match(cursor):
        raise InvalidStudioReviewPage()
    try:
        decoded = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("utf-8")
        stamp, separator, event_id = decoded.partition("|")
        created_at = datetime.fromisoformat(stamp)
    except (ValueError, UnicodeDecodeError) as error:
        raise InvalidStudioReviewPage() from error
    if not separator or not _EVENT_ID_PATTERN.match(event_id) or created_at.tzinfo is None:
        raise InvalidStudioReviewPage()
    return limit, (created_at, event_id)


class PostgresStudioReviewRepository:
    """One short transaction per review operation, on the shared editor pool."""

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
        except (*_PASSTHROUGH, StudioReviewPersistenceError):
            raise
        except Exception as error:
            raise StudioReviewPersistenceError() from error

    async def create_comment(
        self,
        *,
        project_id: str,
        document_id: str,
        request: CreateComment,
        actor: ActorSnapshot,
    ) -> ReviewComment:
        event = await self._append(project_id, document_id, "comment", request, actor)
        assert isinstance(event, ReviewComment)
        return event

    async def create_decision(
        self,
        *,
        project_id: str,
        document_id: str,
        request: CreateDecision,
        actor: ActorSnapshot,
    ) -> ReviewDecision:
        event = await self._append(project_id, document_id, "decision", request, actor)
        assert isinstance(event, ReviewDecision)
        return event

    async def list_comments(
        self, *, project_id: str, document_id: str, limit: int, cursor: str | None
    ) -> ReviewCommentPage:
        events, next_cursor = await self._list(project_id, document_id, "comment", limit, cursor)
        return ReviewCommentPage(comments=events, next_cursor=next_cursor)

    async def list_decisions(
        self, *, project_id: str, document_id: str, limit: int, cursor: str | None
    ) -> ReviewDecisionPage:
        events, next_cursor = await self._list(project_id, document_id, "decision", limit, cursor)
        return ReviewDecisionPage(decisions=events, next_cursor=next_cursor)

    async def _append(
        self,
        project_id: str,
        document_id: str,
        kind: str,
        request: CreateComment | CreateDecision,
        actor: ActorSnapshot,
    ) -> ReviewComment | ReviewDecision:
        request_hash = _request_hash(kind, request, actor)

        def write(session: Session) -> ReviewComment | ReviewDecision:
            advisory_xact_lock(session, project_id, document_id)
            # Replay wins over staleness: an identical retry of a request that
            # already landed returns that record even after a newer save.
            recorded = session.scalar(
                select(StudioReviewEventRow).where(
                    StudioReviewEventRow.project_id == project_id,
                    StudioReviewEventRow.document_id == document_id,
                    StudioReviewEventRow.operation_id == request.operation_id,
                )
            )
            if recorded is not None:
                if recorded.request_hash != request_hash:
                    raise StudioReviewIdempotencyConflict()
                return _row_to_event(recorded)

            latest = session.scalar(
                select(EditDocumentRevisionRow)
                .where(
                    EditDocumentRevisionRow.project_id == project_id,
                    EditDocumentRevisionRow.document_id == document_id,
                )
                .order_by(EditDocumentRevisionRow.revision.desc())
                .limit(1)
                .with_for_update()
            )
            if latest is None:
                raise StudioReviewDocumentNotFound()
            if latest.revision != request.base_revision:
                raise StudioReviewRevisionConflict(latest_revision=latest.revision)
            document = DOCUMENT_ADAPTER.validate_python(latest.document_json)
            self._check_eligible(document, request)

            comment = isinstance(request, CreateComment)
            row = StudioReviewEventRow(
                event_id=f"review_{uuid.uuid4().hex}",
                project_id=project_id,
                document_id=document_id,
                revision=request.base_revision,
                operation_id=request.operation_id,
                request_hash=request_hash,
                event_kind=kind,
                actor_id=actor.actor_id,
                actor_type=actor.actor_type,
                actor_display_name=actor.display_name,
                comment_text=request.text if comment else None,
                frame=request.frame if comment else None,
                decision=None if comment else request.decision,
                reason=None if comment else request.reason,
            )
            session.add(row)
            session.flush()
            # The database stamps `created_at`, as the psycopg INSERT ... RETURNING did.
            session.refresh(row, ["created_at"])
            return _row_to_event(row)

        return await self._run(write)

    @staticmethod
    def _check_eligible(document: EditDocument, request: CreateComment | CreateDecision) -> None:
        if isinstance(request, CreateComment):
            if request.frame is not None and request.frame >= document.canvas.duration_in_frames:
                raise StudioReviewFrameOutOfRange()
            return
        if request.decision == "approved":
            issues = review_blocking_issues(document)
            if issues:
                raise StudioReviewNotEligible(issues)

    async def _list(
        self, project_id: str, document_id: str, kind: str, limit: int, cursor: str | None
    ) -> tuple[tuple[Any, ...], str | None]:
        bounded, keyset = _page_bounds(limit, cursor)

        def read(session: Session) -> tuple[tuple[Any, ...], str | None]:
            # Comments read oldest-first, decisions newest-first; the project and
            # document predicates always apply, so a cursor can only move a keyset.
            key = tuple_(StudioReviewEventRow.created_at, StudioReviewEventRow.event_id)
            query = select(StudioReviewEventRow).where(
                StudioReviewEventRow.project_id == project_id,
                StudioReviewEventRow.document_id == document_id,
                StudioReviewEventRow.event_kind == kind,
            )
            if kind == "comment":
                order = (StudioReviewEventRow.created_at, StudioReviewEventRow.event_id)
                if keyset is not None:
                    query = query.where(key > tuple_(*keyset))
            else:
                order = (
                    StudioReviewEventRow.created_at.desc(),
                    StudioReviewEventRow.event_id.desc(),
                )
                if keyset is not None:
                    query = query.where(key < tuple_(*keyset))
            rows = session.scalars(query.order_by(*order).limit(bounded + 1)).all()
            events = tuple(_row_to_event(row) for row in rows[:bounded])
            last = rows[bounded - 1] if len(rows) > bounded else None
            return events, None if last is None else _encode_cursor(last.created_at, last.event_id)

        return await self._run(read)

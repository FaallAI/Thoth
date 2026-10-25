"""PostgreSQL persistence for the one active render slot and its history.

Every mutation runs inside one short-lived transaction. Creation serializes on a
single advisory lock so the idempotency record and the active slot are decided
together, and the database keeps the same invariant independently through the
partial unique index on active rows. Lifecycle changes re-read the row `FOR
UPDATE` and hand it to the pure domain transition, so a duplicate, late, or
superseded callback can never win a race against a terminal state.

SQLAlchemy ORM on the shared editor pool (ORM spec 2026-10-26); async callers reach the
synchronous session through `asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
import base64
import re
from collections.abc import Callable
from datetime import datetime
from typing import TypeVar

from sqlalchemy import Select, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from thoth_control_plane.application.render_job_ports import (
    InvalidRenderCursor,
    RenderBusy,
    RenderIdempotencyConflict,
    RenderJobNotFound,
    RenderPersistenceError,
)
from thoth_control_plane.domain.render_jobs import (
    InvalidRenderEvent,
    InvalidRenderTransition,
    RenderJob,
    RenderJobEvent,
    RenderJobPage,
    apply_render_event,
    mark_cancel_requested,
)
from thoth_control_plane.infrastructure.editor_database import advisory_xact_lock, editor_sessions
from thoth_control_plane.infrastructure.editor_models import RenderJobIdempotencyRow, RenderJobRow

T = TypeVar("T")

ACTIVE_STATUSES = ("preparing", "rendering", "finalizing")

#: One installation-wide lock namespace: creation is the only serialized path.
RENDER_LOCK_NAMESPACE = "render-jobs"
RENDER_LOCK_KEY = 1

#: The largest history page any caller may ask for, matching `RenderJobPage`.
MAX_PAGE_SIZE = 50

#: PostgreSQL's unique_violation: the active-slot index refused a second active job.
_UNIQUE_VIOLATION = "23505"

_CURSOR_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
_JOB_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,127}$")

#: Typed outcomes the application maps to fixed safe codes; never redacted.
_PASSTHROUGH = (
    RenderBusy,
    RenderIdempotencyConflict,
    RenderJobNotFound,
    InvalidRenderCursor,
    InvalidRenderTransition,
    InvalidRenderEvent,
)

#: Every column a lifecycle change may move; identity and creation facts never change.
_MUTABLE = (
    "status",
    "progress_percent",
    "last_event_sequence",
    "started_at",
    "finished_at",
    "cancel_requested_at",
    "artifacts_cleaned_at",
    "failure_code",
    "output_relative_path",
)


def _job(row: RenderJobRow) -> RenderJob:
    """Rebuild one job, taking output facts from the provenance record."""
    provenance = row.provenance
    return RenderJob.model_validate(
        {
            "render_job_id": row.render_job_id,
            "project_id": row.project_id,
            "document_id": row.document_id,
            "document_revision": row.document_revision,
            "dispatch_id": row.dispatch_id,
            "template_id": row.template_id,
            "template_version": row.template_version,
            "preset_id": row.preset_id,
            "renderer_version": row.renderer_version,
            "status": row.status,
            "progress_percent": row.progress_percent,
            "last_event_sequence": row.last_event_sequence,
            "retry_of_job_id": row.retry_of_job_id,
            "created_by": row.created_by,
            "created_at": row.created_at,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "cancel_requested_at": row.cancel_requested_at,
            "artifacts_cleaned_at": row.artifacts_cleaned_at,
            "failure_code": row.failure_code,
            "output_relative_path": row.output_relative_path,
            "output": provenance.get("output"),
            "provenance": provenance,
        }
    )


def _store(row: RenderJobRow, job: RenderJob) -> None:
    """Write a job's mutable state and its output facts onto its row."""
    for field in _MUTABLE:
        setattr(row, field, getattr(job, field))
    output = job.output
    row.output_media_type = None if output is None else output.media_type
    row.output_size_bytes = None if output is None else output.size_bytes
    row.output_checksum = None if output is None else output.checksum
    row.provenance = job.provenance.model_dump(mode="json")


def _encode_cursor(job: RenderJob) -> str:
    raw = f"{job.created_at.isoformat()}|{job.render_job_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    """Accept only a cursor this server issued, so no filter is caller-authored."""
    if not _CURSOR_PATTERN.match(cursor):
        raise InvalidRenderCursor()
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise InvalidRenderCursor() from error
    stamp, separator, render_job_id = decoded.partition("|")
    if not separator or not _JOB_ID_PATTERN.match(render_job_id):
        raise InvalidRenderCursor()
    try:
        created_at = datetime.fromisoformat(stamp)
    except ValueError as error:
        raise InvalidRenderCursor() from error
    if created_at.tzinfo is None:
        raise InvalidRenderCursor()
    return created_at, render_job_id


def _active() -> Select[tuple[RenderJobRow]]:
    return select(RenderJobRow).where(RenderJobRow.status.in_(ACTIVE_STATUSES))


def _require_row(
    session: Session,
    *,
    render_job_id: str,
    project_id: str | None = None,
    lock: bool = False,
) -> RenderJobRow:
    query = select(RenderJobRow).where(RenderJobRow.render_job_id == render_job_id)
    if project_id is not None:
        query = query.where(RenderJobRow.project_id == project_id)
    if lock:
        query = query.with_for_update()
    row = session.scalar(query)
    if row is None:
        raise RenderJobNotFound()
    return row


class PostgresRenderJobRepository:
    """One short transaction per render-job operation, on the shared editor pool."""

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
        except _PASSTHROUGH:
            raise
        except Exception as error:
            raise RenderPersistenceError() from error

    async def reserve(
        self, job: RenderJob, *, idempotency_key: str, payload_hash: str
    ) -> RenderJob:
        def write(session: Session) -> RenderJob:
            advisory_xact_lock(session, RENDER_LOCK_NAMESPACE, RENDER_LOCK_KEY)
            # Replay wins over the slot: an identical retry of a request that
            # already created the active job must return that same job.
            recorded = session.scalar(
                select(RenderJobIdempotencyRow)
                .where(
                    RenderJobIdempotencyRow.project_id == job.project_id,
                    RenderJobIdempotencyRow.idempotency_key == idempotency_key,
                )
                .with_for_update()
            )
            if recorded is not None:
                if recorded.payload_hash != payload_hash:
                    raise RenderIdempotencyConflict()
                return _job(_require_row(session, render_job_id=recorded.render_job_id))

            active = session.scalar(_active().with_for_update())
            if active is not None:
                raise RenderBusy(
                    active_render_job_id=active.render_job_id,
                    active_project_id=active.project_id,
                )

            row = RenderJobRow(
                render_job_id=job.render_job_id,
                project_id=job.project_id,
                document_id=job.document_id,
                document_revision=job.document_revision,
                dispatch_id=job.dispatch_id,
                template_id=job.template_id,
                template_version=job.template_version,
                preset_id=job.preset_id,
                renderer_version=job.renderer_version,
                retry_of_job_id=job.retry_of_job_id,
                created_by=job.created_by,
                created_at=job.created_at,
            )
            _store(row, job)
            session.add(row)
            # The idempotency record references the job, so the job goes first.
            session.flush()
            session.add(
                RenderJobIdempotencyRow(
                    project_id=job.project_id,
                    idempotency_key=idempotency_key,
                    payload_hash=payload_hash,
                    render_job_id=job.render_job_id,
                )
            )
            session.flush()
            return job

        try:
            return await self._run(write)
        except RenderPersistenceError as error:
            cause = error.__cause__
            if (
                isinstance(cause, IntegrityError)
                and getattr(cause.orig, "sqlstate", None) == _UNIQUE_VIOLATION
            ):
                # The partial unique index is the authority even if the read above raced.
                raise RenderBusy() from cause
            raise

    async def find_replay(
        self, *, project_id: str, idempotency_key: str, payload_hash: str
    ) -> RenderJob | None:
        def read(session: Session) -> RenderJob | None:
            recorded = session.get(RenderJobIdempotencyRow, (project_id, idempotency_key))
            if recorded is None:
                return None
            if recorded.payload_hash != payload_hash:
                raise RenderIdempotencyConflict()
            return _job(_require_row(session, render_job_id=recorded.render_job_id))

        return await self._run(read)

    async def get_active(self) -> RenderJob | None:
        def read(session: Session) -> RenderJob | None:
            row = session.scalar(_active().limit(1))
            return None if row is None else _job(row)

        return await self._run(read)

    async def get(self, *, project_id: str, render_job_id: str) -> RenderJob | None:
        def read(session: Session) -> RenderJob | None:
            row = session.get(RenderJobRow, render_job_id)
            return None if row is None or row.project_id != project_id else _job(row)

        return await self._run(read)

    async def get_internal(self, *, render_job_id: str) -> RenderJob | None:
        def read(session: Session) -> RenderJob | None:
            row = session.get(RenderJobRow, render_job_id)
            return None if row is None else _job(row)

        return await self._run(read)

    async def list(self, *, project_id: str, limit: int, cursor: str | None) -> RenderJobPage:
        bounded = max(1, min(int(limit), MAX_PAGE_SIZE))
        keyset = None if cursor is None else _decode_cursor(cursor)

        def read(session: Session) -> list[RenderJobRow]:
            query = select(RenderJobRow).where(RenderJobRow.project_id == project_id)
            if keyset is not None:
                query = query.where(
                    tuple_(RenderJobRow.created_at, RenderJobRow.render_job_id) < tuple_(*keyset)
                )
            return list(
                session.scalars(
                    query.order_by(
                        RenderJobRow.created_at.desc(), RenderJobRow.render_job_id.desc()
                    ).limit(bounded + 1)
                )
            )

        rows = await self._run(read)
        jobs = tuple(_job(row) for row in rows[:bounded])
        next_cursor = _encode_cursor(jobs[-1]) if len(rows) > bounded and jobs else None
        return RenderJobPage(jobs=jobs, next_cursor=next_cursor)

    async def apply_event(
        self, *, render_job_id: str, event: RenderJobEvent, now: datetime
    ) -> RenderJob:
        def write(session: Session) -> RenderJob:
            row = _require_row(session, render_job_id=render_job_id, lock=True)
            current = _job(row)
            updated = apply_render_event(current, event, now)
            if updated != current:
                _store(row, updated)
            return updated

        return await self._run(write)

    async def mark_cancel_requested(
        self, *, project_id: str, render_job_id: str, now: datetime
    ) -> tuple[RenderJob, bool]:
        def write(session: Session) -> tuple[RenderJob, bool]:
            row = _require_row(
                session, render_job_id=render_job_id, project_id=project_id, lock=True
            )
            current = _job(row)
            updated = mark_cancel_requested(current, now)
            if updated == current:
                return current, False
            _store(row, updated)
            return updated, True

        return await self._run(write)

    async def mark_cleaned(
        self, *, project_id: str, render_job_id: str, now: datetime
    ) -> RenderJob:
        def write(session: Session) -> RenderJob:
            row = _require_row(
                session, render_job_id=render_job_id, project_id=project_id, lock=True
            )
            current = _job(row)
            if current.finished_at is None:
                raise InvalidRenderTransition("an active render job cannot be cleaned up")
            if current.artifacts_cleaned_at is not None:
                return current
            # The audit row and its safe provenance stay; only files go away.
            updated = current.model_copy(update={"artifacts_cleaned_at": now})
            _store(row, updated)
            return updated

        return await self._run(write)

    async def list_expired_active(self, *, deadline: datetime, limit: int) -> tuple[RenderJob, ...]:
        def read(session: Session) -> tuple[RenderJob, ...]:
            rows = session.scalars(
                _active()
                .where(RenderJobRow.created_at < deadline)
                .order_by(RenderJobRow.created_at.asc())
                .limit(max(1, min(int(limit), MAX_PAGE_SIZE)))
            )
            return tuple(_job(row) for row in rows)

        return await self._run(read)

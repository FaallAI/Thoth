"""Workflow runs in PostgreSQL (editor migration 0012).

A row is written when a workflow starts and settled when it is read. Synchronous like the report
store; callers wrap calls in `asyncio.to_thread`. A database error is `WorkflowRunsUnavailable`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, create_engine, func, or_, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from thoth_control_plane.application.ports import WorkflowRunsUnavailable
from thoth_control_plane.domain import Actor, ArtifactRef, WorkflowSummary
from thoth_control_plane.domain.cursors import decode_cursor, encode_cursor
from thoth_control_plane.domain.workflow_runs import StoredRun
from thoth_control_plane.infrastructure.report_models import WorkflowReportRow
from thoth_control_plane.infrastructure.run_models import WorkflowRunRow

logger = logging.getLogger(__name__)

_REPORT_LABELS = {
    "source_report": "Source investigation report",
    "original_source_report": "Original source report",
    "source_attribution": "Source attribution",
    "content_set": "Content set",
}


def _aware(moment: datetime) -> datetime:
    """SQLite aggregates return naive UTC; Postgres returns aware."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _summary(value: dict[str, Any] | None) -> WorkflowSummary | None:
    # StrictModel takes timestamps and enums from their JSON forms only through JSON validation.
    return None if value is None else WorkflowSummary.model_validate_json(json.dumps(value))


def _stored(row: WorkflowRunRow) -> StoredRun:
    return StoredRun(
        workflow_id=row.workflow_id,
        project_id=row.project_id,
        actor_type=row.actor_type,
        actor_id=row.actor_id,
        display_url=row.display_url,
        platform=row.platform,
        status=row.status,
        history_expired=row.history_expired,
        summary=_summary(row.summary),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class WorkflowRunStore:
    def __init__(
        self, engine: Engine, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        self._clock = clock

    @classmethod
    def connect(cls, database_url: str) -> WorkflowRunStore:
        url = make_url(database_url).set(drivername="postgresql+psycopg")
        return cls(
            create_engine(
                url,
                pool_pre_ping=True,
                pool_size=2,
                max_overflow=2,
                hide_parameters=True,
                connect_args={"connect_timeout": 10},
            )
        )

    @staticmethod
    def _unavailable(error: Exception) -> WorkflowRunsUnavailable:
        logger.warning("workflow run store failed: %s", type(error).__name__)
        return WorkflowRunsUnavailable("workflow_runs_unavailable")

    def record_start(
        self, summary: WorkflowSummary, *, project_id: str | None, actor: Actor
    ) -> None:
        """Upsert by workflow ID; a retried start never moves the run to another project."""
        now = self._clock()
        try:
            with self._sessions.begin() as session:
                row = session.get(WorkflowRunRow, summary.workflow_id)
                if row is None:
                    session.add(
                        WorkflowRunRow(
                            workflow_id=summary.workflow_id,
                            project_id=project_id,
                            actor_type=actor.actor_type,
                            actor_id=actor.actor_id,
                            display_url=str(summary.source.display_url),
                            platform=summary.source.platform,
                            status=summary.status.value,
                            history_expired=False,
                            summary=summary.model_dump(mode="json"),
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    return
                row.status = summary.status.value
                row.summary = summary.model_dump(mode="json")
                row.updated_at = now
        except SQLAlchemyError as error:
            raise self._unavailable(error) from None

    def page(
        self,
        *,
        project_id: str | None,
        unassigned: bool,
        actor: Actor,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[StoredRun], str | None]:
        query = select(WorkflowRunRow).where(
            WorkflowRunRow.actor_type == actor.actor_type,
            WorkflowRunRow.actor_id == actor.actor_id,
            WorkflowRunRow.project_id.is_(None)
            if unassigned
            else WorkflowRunRow.project_id == project_id,
        )
        if cursor:
            created_at, workflow_id = decode_cursor(cursor)
            query = query.where(
                or_(
                    WorkflowRunRow.created_at < created_at,
                    and_(
                        WorkflowRunRow.created_at == created_at,
                        WorkflowRunRow.workflow_id < workflow_id,
                    ),
                )
            )
        query = query.order_by(
            WorkflowRunRow.created_at.desc(), WorkflowRunRow.workflow_id.desc()
        ).limit(limit + 1)
        try:
            with self._sessions() as session:
                rows = [_stored(row) for row in session.scalars(query).all()]
        except SQLAlchemyError as error:
            raise self._unavailable(error) from None
        page = rows[:limit]
        next_cursor = (
            encode_cursor(page[-1].created_at, page[-1].workflow_id) if len(rows) > limit else None
        )
        return page, next_cursor

    def get(self, workflow_id: str) -> StoredRun | None:
        try:
            with self._sessions() as session:
                row = session.get(WorkflowRunRow, workflow_id)
        except SQLAlchemyError as error:
            raise self._unavailable(error) from None
        return None if row is None else _stored(row)

    def settle(
        self,
        workflow_id: str,
        *,
        status: str,
        summary: WorkflowSummary | None,
        history_expired: bool,
    ) -> None:
        try:
            with self._sessions.begin() as session:
                row = session.get(WorkflowRunRow, workflow_id)
                if row is None:
                    return
                stored = summary.model_dump(mode="json") if summary is not None else row.summary
                if (row.status, row.history_expired, row.summary) == (
                    status,
                    history_expired,
                    stored,
                ):
                    return  # a re-read of the same state writes nothing
                row.status = status
                row.history_expired = history_expired
                row.summary = stored
                # The run's own time, not the moment someone looked at it.
                row.updated_at = summary.updated_at if summary is not None else self._clock()
        except SQLAlchemyError as error:
            raise self._unavailable(error) from None

    def assign(self, workflow_id: str, project_id: str) -> StoredRun | None:
        try:
            with self._sessions.begin() as session:
                row = session.get(WorkflowRunRow, workflow_id)
                if row is None:
                    return None
                row.project_id = project_id
                row.updated_at = self._clock()
                return _stored(row)
        except SQLAlchemyError as error:
            raise self._unavailable(error) from None

    def insert_missing(self, run: StoredRun) -> bool:
        """Backfill only: insert when absent, never overwrite."""
        try:
            with self._sessions.begin() as session:
                if session.get(WorkflowRunRow, run.workflow_id) is not None:
                    return False
                session.add(
                    WorkflowRunRow(
                        workflow_id=run.workflow_id,
                        project_id=run.project_id,
                        actor_type=run.actor_type,
                        actor_id=run.actor_id,
                        display_url=run.display_url,
                        platform=run.platform,
                        status=run.status,
                        history_expired=run.history_expired,
                        summary=None
                        if run.summary is None
                        else run.summary.model_dump(mode="json"),
                        created_at=run.created_at,
                        updated_at=run.updated_at,
                    )
                )
                return True
        except SQLAlchemyError as error:
            raise self._unavailable(error) from None

    def report_artifacts(self, workflow_id: str) -> list[ArtifactRef]:
        """The run's JSON reports as artifacts, for a summary Temporal no longer holds."""
        try:
            with self._sessions() as session:
                rows = session.scalars(
                    select(WorkflowReportRow)
                    .where(WorkflowReportRow.workflow_id == workflow_id)
                    .order_by(WorkflowReportRow.location)
                ).all()
        except SQLAlchemyError as error:
            raise self._unavailable(error) from None
        return [
            ArtifactRef(
                artifact_id=row.kind,
                kind=row.kind,
                label=_REPORT_LABELS.get(row.kind, row.kind),
                media_type="application/json",
                location=row.location,
                checksum=f"sha256:{row.sha256}",
                size_bytes=row.size_bytes,
            )
            for row in rows
        ]

    def source_report_rows(self) -> list[tuple[str, str, datetime]]:
        """(workflow_id, source report text, earliest report time) for the backfill."""
        earliest = (
            select(
                WorkflowReportRow.workflow_id,
                func.min(WorkflowReportRow.created_at).label("first_seen"),
            )
            .group_by(WorkflowReportRow.workflow_id)
            .subquery()
        )
        query = (
            select(WorkflowReportRow.workflow_id, WorkflowReportRow.content, earliest.c.first_seen)
            .join(earliest, earliest.c.workflow_id == WorkflowReportRow.workflow_id)
            .where(WorkflowReportRow.kind == "source_report")
            .order_by(WorkflowReportRow.workflow_id)
        )
        try:
            with self._sessions() as session:
                rows = session.execute(query).all()
        except SQLAlchemyError as error:
            raise self._unavailable(error) from None
        return [(workflow_id, content, _aware(first)) for workflow_id, content, first in rows]


__all__ = ["StoredRun", "WorkflowRunStore", "WorkflowRunsUnavailable"]

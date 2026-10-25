"""Project-scoped PostgreSQL persistence for Prompt Lab revisions and bindings.

SQLAlchemy ORM on the shared editor pool (ORM spec 2026-10-26); async callers reach the
synchronous session through `asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from thoth_control_plane.application.ports import (
    PromptBindingNotFound,
    PromptBindingRevisionConflict,
    PromptTemplateNotFound,
    PromptTemplateRevisionConflict,
)
from thoth_control_plane.domain.prompts import (
    ProjectPromptBinding,
    PromptStageId,
    PromptTemplateRevision,
    SaveProjectPromptBindingRequest,
)
from thoth_control_plane.infrastructure.editor_database import advisory_xact_lock, editor_sessions
from thoth_control_plane.infrastructure.editor_models import (
    ProjectPromptBindingRow,
    PromptTemplateRevisionRow,
)

T = TypeVar("T")

TEMPLATE_ROW_KEYS = ("project_id", "template_id", "revision", "stage_id", "language", "body")
BINDING_ROW_KEYS = (
    "project_id",
    "stage_id",
    "template_id",
    "template_revision",
    "project_override",
    "revision",
)

#: Typed outcomes the application maps to fixed safe codes; never redacted.
_PASSTHROUGH = (
    PromptTemplateRevisionConflict,
    PromptTemplateNotFound,
    PromptBindingRevisionConflict,
    PromptBindingNotFound,
)


class PromptLabPersistenceError(Exception):
    """The prompt lab store is unavailable without leaking connection details."""

    def __init__(self) -> None:
        super().__init__("prompt lab persistence unavailable")


def _template(row: PromptTemplateRevisionRow) -> PromptTemplateRevision:
    return PromptTemplateRevision.model_validate(
        {key: getattr(row, key) for key in TEMPLATE_ROW_KEYS}
    )


def _binding(row: ProjectPromptBindingRow) -> ProjectPromptBinding:
    return ProjectPromptBinding.model_validate({key: getattr(row, key) for key in BINDING_ROW_KEYS})


class PostgresPromptLabRepository:
    """One short project-scoped transaction per operation, on the shared editor pool."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    async def _run(self, work: Callable[[Session], T]) -> T:
        def unit() -> T:
            with editor_sessions(self._database_url).begin() as session:
                return work(session)

        try:
            return await asyncio.to_thread(unit)
        except _PASSTHROUGH:
            raise
        except Exception as error:
            raise PromptLabPersistenceError() from error

    async def list_template_heads(
        self, *, project_id: str, stage_id: PromptStageId
    ) -> list[PromptTemplateRevision]:
        def read(session: Session) -> list[PromptTemplateRevision]:
            rows = session.scalars(
                select(PromptTemplateRevisionRow)
                .where(
                    PromptTemplateRevisionRow.project_id == project_id,
                    PromptTemplateRevisionRow.stage_id == stage_id,
                )
                .distinct(PromptTemplateRevisionRow.template_id)
                .order_by(
                    PromptTemplateRevisionRow.template_id,
                    PromptTemplateRevisionRow.revision.desc(),
                )
            )
            return [_template(row) for row in rows]

        return await self._run(read)

    async def get_template_revision(
        self, *, project_id: str, template_id: str, revision: int
    ) -> PromptTemplateRevision | None:
        def read(session: Session) -> PromptTemplateRevision | None:
            row = session.get(PromptTemplateRevisionRow, (project_id, template_id, revision))
            return _template(row) if row else None

        return await self._run(read)

    async def save_template(
        self,
        *,
        project_id: str,
        template_id: str,
        base_revision: int | None,
        stage_id: PromptStageId,
        language: str,
        body: str,
    ) -> PromptTemplateRevision:
        def write(session: Session) -> PromptTemplateRevision:
            advisory_xact_lock(session, project_id, template_id)
            row = session.scalar(
                select(PromptTemplateRevisionRow)
                .where(
                    PromptTemplateRevisionRow.project_id == project_id,
                    PromptTemplateRevisionRow.template_id == template_id,
                )
                .order_by(PromptTemplateRevisionRow.revision.desc())
                .limit(1)
                .with_for_update()
            )
            latest = _template(row) if row else None
            if base_revision is None:
                if latest is not None:
                    raise PromptTemplateRevisionConflict(latest)
                next_revision = 1
            else:
                if latest is None:
                    raise PromptTemplateNotFound()
                if latest.revision != base_revision:
                    raise PromptTemplateRevisionConflict(latest)
                next_revision = latest.revision + 1
            saved = PromptTemplateRevision.model_validate(
                {
                    "project_id": project_id,
                    "template_id": template_id,
                    "revision": next_revision,
                    "stage_id": stage_id,
                    "language": language,
                    "body": body,
                }
            )
            session.add(
                PromptTemplateRevisionRow(
                    project_id=saved.project_id,
                    template_id=saved.template_id,
                    revision=saved.revision,
                    stage_id=saved.stage_id,
                    language=saved.language,
                    body=saved.body,
                )
            )
            return saved

        return await self._run(write)

    async def get_binding(
        self, *, project_id: str, stage_id: PromptStageId
    ) -> ProjectPromptBinding | None:
        def read(session: Session) -> ProjectPromptBinding | None:
            row = session.get(ProjectPromptBindingRow, (project_id, stage_id))
            return _binding(row) if row else None

        return await self._run(read)

    async def save_binding(
        self,
        *,
        project_id: str,
        stage_id: PromptStageId,
        request: SaveProjectPromptBindingRequest,
    ) -> ProjectPromptBinding:
        def write(session: Session) -> ProjectPromptBinding:
            advisory_xact_lock(session, project_id, stage_id)
            row = session.scalar(
                select(ProjectPromptBindingRow)
                .where(
                    ProjectPromptBindingRow.project_id == project_id,
                    ProjectPromptBindingRow.stage_id == stage_id,
                )
                .with_for_update()
            )
            latest = _binding(row) if row else None
            if request.base_revision is None:
                if latest is not None:
                    raise PromptBindingRevisionConflict(latest)
                next_revision = 1
            else:
                if latest is None:
                    raise PromptBindingNotFound()
                if latest.revision != request.base_revision:
                    raise PromptBindingRevisionConflict(latest)
                next_revision = latest.revision + 1
            if row is None:
                session.add(
                    ProjectPromptBindingRow(
                        project_id=project_id,
                        stage_id=stage_id,
                        template_id=request.template_id,
                        template_revision=request.template_revision,
                        project_override=request.project_override,
                        revision=next_revision,
                    )
                )
            else:
                row.template_id = request.template_id
                row.template_revision = request.template_revision
                row.project_override = request.project_override
                row.revision = next_revision
                row.updated_at = func.current_timestamp()
            # Surface a constraint failure (an unknown template revision) inside this unit.
            session.flush()
            return ProjectPromptBinding.model_validate(
                {
                    "project_id": project_id,
                    "stage_id": stage_id,
                    "template_id": request.template_id,
                    "template_revision": request.template_revision,
                    "project_override": request.project_override,
                    "revision": next_revision,
                }
            )

        return await self._run(write)

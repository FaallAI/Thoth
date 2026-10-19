"""Projects in PostgreSQL (editor migration 0012).

Synchronous like the report store; callers wrap calls in `asyncio.to_thread`. A database error is
`ProjectStoreUnavailable`, never an absent project.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID
from thoth_control_plane.domain.projects import Project
from thoth_control_plane.infrastructure.run_models import ProjectRow

logger = logging.getLogger(__name__)


class ProjectStoreUnavailable(RuntimeError):
    """The database could not be reached or refused the statement."""


def _project(row: ProjectRow) -> Project:
    return Project(
        project_id=row.project_id,
        name=row.name,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _unavailable(error: Exception) -> ProjectStoreUnavailable:
    logger.warning("project store failed: %s", type(error).__name__)
    return ProjectStoreUnavailable("project_store_unavailable")


class ProjectStore:
    def __init__(
        self, engine: Engine, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        self._clock = clock

    @classmethod
    def connect(cls, database_url: str) -> ProjectStore:
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

    def list(self, workspace_id: str) -> list[Project]:
        try:
            with self._sessions() as session:
                rows = session.scalars(
                    select(ProjectRow)
                    .where(ProjectRow.workspace_id == workspace_id)
                    .order_by(ProjectRow.updated_at.desc(), ProjectRow.project_id.desc())
                ).all()
        except SQLAlchemyError as error:
            raise _unavailable(error) from None
        return [_project(row) for row in rows]

    def get(self, project_id: str, workspace_id: str) -> Project | None:
        """The project, or None when it is missing or belongs to another workspace."""
        try:
            with self._sessions() as session:
                row = session.get(ProjectRow, project_id)
        except SQLAlchemyError as error:
            raise _unavailable(error) from None
        return None if row is None or row.workspace_id != workspace_id else _project(row)

    def create(self, name: str, workspace_id: str) -> Project:
        now = self._clock()
        row = ProjectRow(
            project_id=str(uuid4()),
            name=name.strip(),
            created_at=now,
            updated_at=now,
            workspace_id=workspace_id,
        )
        try:
            with self._sessions.begin() as session:
                session.add(row)
        except SQLAlchemyError as error:
            raise _unavailable(error) from None
        return _project(row)

    def insert_missing(self, project: Project) -> bool:
        """Import only: insert with the given ID into the bootstrap workspace, never overwrite."""
        try:
            with self._sessions.begin() as session:
                if session.get(ProjectRow, project.project_id) is not None:
                    return False
                session.add(ProjectRow(**project.model_dump(), workspace_id=BOOTSTRAP_WORKSPACE_ID))
                return True
        except SQLAlchemyError as error:
            raise _unavailable(error) from None

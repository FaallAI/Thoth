"""Workflow steps in PostgreSQL (editor migration 0019).

Synchronous like the other stores; async callers use `asyncio.to_thread`. The recorder's
sink protocol is `append(scope, record)`, so the worker installs this store directly.
"""

from __future__ import annotations

from sqlalchemy import and_, create_engine, func, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker

from thoth_control_plane.domain.models import WorkflowStep
from thoth_control_plane.infrastructure.step_models import WorkflowStepRow
from thoth_control_plane.progress import StepRecord, StepScope


class StepStore:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    @classmethod
    def connect(cls, database_url: str) -> StepStore:
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

    def append(self, scope: StepScope, record: StepRecord) -> None:
        with self._sessions.begin() as session:
            session.add(
                WorkflowStepRow(
                    workflow_id=scope.workflow_id,
                    attempt=scope.attempt,
                    stage=scope.stage,
                    at=record.at,
                    kind=record.kind,
                    code=record.code,
                    n=record.n,
                    total=record.total,
                    wait_until=record.wait_until,
                    params=record.params,
                )
            )

    def page(self, workflow_id: str, after: int, limit: int) -> list[WorkflowStep]:
        with self._sessions() as session:
            rows = session.scalars(
                select(WorkflowStepRow)
                .where(WorkflowStepRow.workflow_id == workflow_id, WorkflowStepRow.seq > after)
                .order_by(WorkflowStepRow.seq)
                .limit(limit)
            )
            return [_step(row) for row in rows]

    def current_steps(self, workflow_id: str) -> dict[str, WorkflowStep]:
        """For each stage, the latest step of that stage's highest attempt.

        The database picks one row per stage, so a poll reads a handful of rows however
        many steps the run recorded.
        """
        step = WorkflowStepRow
        top = (
            select(step.stage, func.max(step.attempt).label("attempt"))
            .where(step.workflow_id == workflow_id)
            .group_by(step.stage)
            .subquery()
        )
        latest = (
            select(func.max(step.seq))
            .join(top, and_(step.stage == top.c.stage, step.attempt == top.c.attempt))
            .where(step.workflow_id == workflow_id)
            .group_by(step.stage)
        )
        with self._sessions() as session:
            rows = session.scalars(select(step).where(step.seq.in_(latest)))
            return {row.stage: _step(row) for row in rows}


def _step(row: WorkflowStepRow) -> WorkflowStep:
    return WorkflowStep(
        seq=row.seq,
        stage=row.stage,
        attempt=row.attempt,
        at=row.at,
        kind=row.kind,
        code=row.code,
        n=row.n,
        total=row.total,
        wait_until=row.wait_until,
        params=row.params,
    )

"""Usage events, workspace quotas and unit prices in PostgreSQL (editor migration 0015).

Synchronous like the other stores; async callers use `asyncio.to_thread`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker

from thoth_control_plane.acquisition.accounts.cookies import PLATFORMS
from thoth_control_plane.acquisition.accounts.policy import DEFAULT_WORKSPACE_DAILY_LEASES
from thoth_control_plane.auth.models import actor_workspace_id
from thoth_control_plane.infrastructure.run_models import ProjectRow, WorkflowRunRow
from thoth_control_plane.infrastructure.usage_models import (
    UnitPriceRow,
    UsageEventRow,
    WorkspaceQuotaRow,
)
from thoth_control_plane.metering import KINDS, UNITS, UsageRecord


@dataclass(frozen=True)
class UsageTotal:
    kind: str
    key: str
    unit: str
    quantity: float
    events: int


@dataclass(frozen=True)
class UnitPrice:
    kind: str
    key: str
    unit: str
    usd_per_unit: float


def day_start(moment: datetime) -> datetime:
    return datetime.combine(moment.date(), datetime.min.time(), tzinfo=UTC)


class UsageStore:
    def __init__(
        self, engine: Engine, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        self._clock = clock

    @classmethod
    def connect(cls, database_url: str) -> UsageStore:
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

    def record(self, event: UsageRecord) -> None:
        with self._sessions.begin() as session:
            session.add(
                UsageEventRow(
                    event_id=f"use_{uuid.uuid4().hex}",
                    workspace_id=event.workspace_id,
                    workflow_id=event.workflow_id,
                    project_id=event.project_id,
                    kind=event.kind,
                    key=event.key,
                    quantity=event.quantity,
                    unit=event.unit,
                    occurred_at=self._clock(),
                )
            )

    def workspace_of_workflow(self, workflow_id: str) -> str | None:
        with self._sessions() as session:
            actor = session.scalar(
                select(WorkflowRunRow.actor_id).where(WorkflowRunRow.workflow_id == workflow_id)
            )
        return None if actor is None else actor_workspace_id(actor)

    def workspace_of_project(self, project_id: str) -> str | None:
        with self._sessions() as session:
            return session.scalar(
                select(ProjectRow.workspace_id).where(ProjectRow.project_id == project_id)
            )

    def _grouped(self, start: datetime, end: datetime, workspace_id: str | None) -> list[Any]:
        query = select(
            UsageEventRow.workspace_id,
            UsageEventRow.kind,
            UsageEventRow.key,
            UsageEventRow.unit,
            func.sum(UsageEventRow.quantity),
            func.count(),
        ).where(UsageEventRow.occurred_at >= start, UsageEventRow.occurred_at < end)
        if workspace_id is not None:
            query = query.where(UsageEventRow.workspace_id == workspace_id)
        query = query.group_by(
            UsageEventRow.workspace_id, UsageEventRow.kind, UsageEventRow.key, UsageEventRow.unit
        ).order_by(UsageEventRow.workspace_id, UsageEventRow.kind, UsageEventRow.key)
        with self._sessions() as session:
            return list(session.execute(query).all())

    def totals(self, workspace_id: str, start: datetime, end: datetime) -> list[UsageTotal]:
        return [
            UsageTotal(kind, key, unit, float(quantity), int(events))
            for _ws, kind, key, unit, quantity, events in self._grouped(start, end, workspace_id)
        ]

    def totals_by_workspace(self, start: datetime, end: datetime) -> dict[str, list[UsageTotal]]:
        found: dict[str, list[UsageTotal]] = {}
        for workspace, kind, key, unit, quantity, events in self._grouped(start, end, None):
            found.setdefault(workspace, []).append(
                UsageTotal(kind, key, unit, float(quantity), int(events))
            )
        return found

    def leases_today(self, workspace_id: str) -> dict[str, int]:
        start = day_start(self._clock())
        return {
            total.key: total.events
            for total in self.totals(workspace_id, start, start + timedelta(days=1))
            if total.kind == "account_lease"
        }

    def quotas(self, workspace_id: str) -> dict[str, int]:
        with self._sessions() as session:
            overrides = {
                row.platform: row.daily_leases
                for row in session.scalars(
                    select(WorkspaceQuotaRow).where(WorkspaceQuotaRow.workspace_id == workspace_id)
                )
            }
        return {
            platform: overrides.get(platform, DEFAULT_WORKSPACE_DAILY_LEASES.get(platform, 0))
            for platform in PLATFORMS
        }

    def set_quota(self, workspace_id: str, platform: str, daily_leases: int) -> None:
        if platform not in PLATFORMS or daily_leases < 0:
            raise ValueError("invalid_quota")
        with self._sessions.begin() as session:
            row = session.get(WorkspaceQuotaRow, (workspace_id, platform))
            if row is None:
                row = WorkspaceQuotaRow(workspace_id=workspace_id, platform=platform)
                session.add(row)
            row.daily_leases, row.updated_at = daily_leases, self._clock()

    def clear_quota(self, workspace_id: str, platform: str) -> None:
        with self._sessions.begin() as session:
            session.execute(
                delete(WorkspaceQuotaRow).where(
                    WorkspaceQuotaRow.workspace_id == workspace_id,
                    WorkspaceQuotaRow.platform == platform,
                )
            )

    def prices(self) -> list[UnitPrice]:
        with self._sessions() as session:
            rows = session.scalars(
                select(UnitPriceRow).order_by(
                    UnitPriceRow.kind, UnitPriceRow.key, UnitPriceRow.unit
                )
            )
            return [UnitPrice(r.kind, r.key, r.unit, r.usd_per_unit) for r in rows]

    def set_price(self, kind: str, key: str, unit: str, usd_per_unit: float) -> UnitPrice:
        if kind not in KINDS or unit not in UNITS or not key or usd_per_unit < 0:
            raise ValueError("invalid_price")
        with self._sessions.begin() as session:
            row = session.get(UnitPriceRow, (kind, key, unit))
            if row is None:
                row = UnitPriceRow(kind=kind, key=key, unit=unit)
                session.add(row)
            row.usd_per_unit, row.updated_at = usd_per_unit, self._clock()
        return UnitPrice(kind, key, unit, usd_per_unit)

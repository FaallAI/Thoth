"""Plans, subscriptions, invoices and the allowance ledger in PostgreSQL (editor migration 0016).

Synchronous like the other stores; async callers use `asyncio.to_thread`. A database error is
`BillingUnavailable`.
"""

from __future__ import annotations

import contextlib
import re
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID
from thoth_control_plane.billing import (
    FREE_PLAN_ID,
    AllowanceView,
    BillingUnavailable,
    InvalidPlan,
    PlanLimitReached,
    PlanView,
    SubscriptionView,
    UnknownPlan,
)
from thoth_control_plane.infrastructure.billing_models import (
    AllowanceUseRow,
    PlanRow,
    SubscriptionRow,
)

PLAN_ID = re.compile(r"^[a-z0-9-]{1,32}$")


def _plan(row: PlanRow) -> PlanView:
    return PlanView(
        row.plan_id,
        row.name,
        row.price_idr,
        row.workflows_per_period,
        row.videos_per_period,
        row.period_days,
        row.active,
    )


class BillingStore:
    def __init__(
        self, engine: Engine, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        self._clock = clock

    @classmethod
    def connect(cls, database_url: str) -> BillingStore:
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

    # --- plans ---------------------------------------------------------------------------

    def plans(self, active_only: bool = False) -> list[PlanView]:
        query = select(PlanRow).order_by(PlanRow.price_idr, PlanRow.plan_id)
        if active_only:
            query = query.where(PlanRow.active.is_(True))
        with self._session() as session:
            return [_plan(row) for row in session.scalars(query)]

    def plan(self, plan_id: str) -> PlanView | None:
        with self._session() as session:
            row = session.get(PlanRow, plan_id)
            return None if row is None else _plan(row)

    def set_plan(
        self,
        plan_id: str,
        *,
        name: str,
        price_idr: int,
        workflows: int,
        videos: int,
        period_days: int,
        active: bool,
    ) -> PlanView:
        if (
            not PLAN_ID.fullmatch(plan_id)
            or not 1 <= len(name.strip()) <= 60
            or min(price_idr, workflows, videos) < 0
            or not 1 <= period_days <= 366
            or (plan_id == FREE_PLAN_ID and not active)
        ):
            raise InvalidPlan("invalid_plan")
        with self._session(write=True) as session:
            row = session.get(PlanRow, plan_id)
            if row is None:
                row = PlanRow(plan_id=plan_id)
                session.add(row)
            row.name, row.price_idr = name.strip(), price_idr
            row.workflows_per_period, row.videos_per_period = workflows, videos
            row.period_days, row.active, row.updated_at = period_days, active, self._clock()
            return _plan(row)

    # --- subscriptions -------------------------------------------------------------------

    def subscription(self, workspace_id: str) -> SubscriptionView:
        self._ensure(workspace_id)
        with self._session(write=True) as session:
            row = self._current(session, workspace_id, lock=False)
            return SubscriptionView(row.workspace_id, row.plan_id, row.period_start, row.period_end)

    def grant(self, workspace_id: str, plan_id: str, days: int) -> SubscriptionView:
        """An operator grant: `days` of `plan_id` starting now, with no payment."""
        self._ensure(workspace_id)
        with self._session(write=True) as session:
            if session.get(PlanRow, plan_id) is None:
                raise UnknownPlan(plan_id)
            row = self._current(session, workspace_id, lock=True)
            now = self._clock()
            row.plan_id, row.period_start = plan_id, now
            row.period_end, row.updated_at = now + timedelta(days=days), now
            return SubscriptionView(row.workspace_id, row.plan_id, row.period_start, row.period_end)

    # --- the allowance -------------------------------------------------------------------

    def consume(self, workspace_id: str, kind: str, ref: str) -> bool:
        """Admit one unit of `kind`, or raise `PlanLimitReached`; True when newly taken."""
        if workspace_id == BOOTSTRAP_WORKSPACE_ID:
            return False
        self._ensure(workspace_id)
        with self._session(write=True) as session:
            sub = self._current(session, workspace_id, lock=True)
            existing = session.scalar(
                select(AllowanceUseRow).where(
                    AllowanceUseRow.workspace_id == workspace_id,
                    AllowanceUseRow.kind == kind,
                    AllowanceUseRow.ref == ref,
                )
            )
            if existing is not None and existing.released_at is None:
                return False
            plan = session.get(PlanRow, sub.plan_id)
            assert plan is not None
            allowance = plan.workflows_per_period if kind == "workflow" else plan.videos_per_period
            used = self._used(session, workspace_id, kind, sub.period_start)
            if used >= allowance:
                raise PlanLimitReached(kind, used, allowance, sub.period_end)
            now = self._clock()
            if existing is not None:
                existing.released_at, existing.created_at = None, now
            else:
                session.add(
                    AllowanceUseRow(
                        use_id=f"use_{uuid.uuid4().hex}",
                        workspace_id=workspace_id,
                        kind=kind,
                        ref=ref,
                        created_at=now,
                    )
                )
            return True

    def release(self, workspace_id: str, kind: str, ref: str) -> None:
        with self._session(write=True) as session:
            row = session.scalar(
                select(AllowanceUseRow).where(
                    AllowanceUseRow.workspace_id == workspace_id,
                    AllowanceUseRow.kind == kind,
                    AllowanceUseRow.ref == ref,
                    AllowanceUseRow.released_at.is_(None),
                )
            )
            if row is not None:
                row.released_at = self._clock()

    def allowance(self, workspace_id: str) -> AllowanceView:
        if workspace_id == BOOTSTRAP_WORKSPACE_ID:
            return AllowanceView(workspace_id, True, None, None, None, 0, None, 0, None)
        self._ensure(workspace_id)
        with self._session(write=True) as session:
            sub = self._current(session, workspace_id, lock=False)
            row = session.get(PlanRow, sub.plan_id)
            assert row is not None
            plan = _plan(row)
            return AllowanceView(
                workspace_id,
                False,
                plan,
                sub.period_start,
                sub.period_end,
                self._used(session, workspace_id, "workflow", sub.period_start),
                plan.workflows_per_period,
                self._used(session, workspace_id, "video", sub.period_start),
                plan.videos_per_period,
            )

    # --- internals -----------------------------------------------------------------------

    @contextlib.contextmanager
    def _session(self, write: bool = False) -> Iterator[Session]:
        """A session (a transaction when writing) whose database errors are unavailability."""
        try:
            if write:
                with self._sessions.begin() as session:
                    yield session
            else:
                with self._sessions() as session:
                    yield session
        except SQLAlchemyError as error:
            raise BillingUnavailable("billing_unavailable") from error

    def _ensure(self, workspace_id: str) -> None:
        """Create the lazy free row; a racing creator's row is just as good."""
        try:
            with self._sessions.begin() as session:
                if session.get(SubscriptionRow, workspace_id) is not None:
                    return
                free = session.get(PlanRow, FREE_PLAN_ID)
                if free is None:
                    raise BillingUnavailable("free_plan_missing")
                now = self._clock()
                session.add(
                    SubscriptionRow(
                        workspace_id=workspace_id,
                        plan_id=FREE_PLAN_ID,
                        period_start=now,
                        period_end=now + timedelta(days=free.period_days),
                        updated_at=now,
                    )
                )
        except IntegrityError:
            return
        except SQLAlchemyError as error:
            raise BillingUnavailable("billing_unavailable") from error

    def _current(self, session: Session, workspace_id: str, *, lock: bool) -> SubscriptionRow:
        """The subscription, rolled forward past `period_end` (spec 1.2)."""
        row = session.get(
            SubscriptionRow, workspace_id, with_for_update={"key_share": True} if lock else None
        )
        assert row is not None  # _ensure ran first
        now = self._clock()
        if now >= row.period_end:
            free = session.get(PlanRow, FREE_PLAN_ID)
            assert free is not None
            row.plan_id, row.period_start = FREE_PLAN_ID, now
            row.period_end, row.updated_at = now + timedelta(days=free.period_days), now
        return row

    @staticmethod
    def _used(session: Session, workspace_id: str, kind: str, since: datetime) -> int:
        return int(
            session.scalar(
                select(func.count())
                .select_from(AllowanceUseRow)
                .where(
                    AllowanceUseRow.workspace_id == workspace_id,
                    AllowanceUseRow.kind == kind,
                    AllowanceUseRow.released_at.is_(None),
                    AllowanceUseRow.created_at >= since,
                )
            )
            or 0
        )

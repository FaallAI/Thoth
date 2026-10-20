"""SQLAlchemy ORM mapping of the billing tables (editor migration 0016)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from thoth_control_plane.infrastructure import account_models  # noqa: F401  (workspaces FK)
from thoth_control_plane.infrastructure.source_account_models import Base, UtcDateTime


class PlanRow(Base):
    __tablename__ = "plans"

    plan_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    price_idr: Mapped[int] = mapped_column(BigInteger)
    workflows_per_period: Mapped[int] = mapped_column(Integer)
    videos_per_period: Mapped[int] = mapped_column(Integer)
    period_days: Mapped[int] = mapped_column(Integer, default=30)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)


class SubscriptionRow(Base):
    __tablename__ = "subscriptions"

    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.workspace_id"), primary_key=True
    )
    plan_id: Mapped[str] = mapped_column(String, ForeignKey("plans.plan_id"))
    period_start: Mapped[datetime] = mapped_column(UtcDateTime)
    period_end: Mapped[datetime] = mapped_column(UtcDateTime)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)


class InvoiceRow(Base):
    __tablename__ = "invoices"

    invoice_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.workspace_id"))
    plan_id: Mapped[str] = mapped_column(String, ForeignKey("plans.plan_id"))
    amount_idr: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String)
    provider_invoice_id: Mapped[str | None] = mapped_column(String, nullable=True)
    invoice_url: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    paid_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class AllowanceUseRow(Base):
    __tablename__ = "allowance_uses"
    __table_args__ = (UniqueConstraint("workspace_id", "kind", "ref"),)

    use_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.workspace_id"))
    kind: Mapped[str] = mapped_column(String)
    ref: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    released_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

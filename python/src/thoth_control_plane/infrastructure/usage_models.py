"""SQLAlchemy ORM mapping of the metering tables (editor migration 0015)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from thoth_control_plane.infrastructure import account_models  # noqa: F401  (workspaces FK)
from thoth_control_plane.infrastructure.source_account_models import Base, UtcDateTime


class UsageEventRow(Base):
    __tablename__ = "usage_events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.workspace_id"))
    workflow_id: Mapped[str | None] = mapped_column(String, nullable=True)
    project_id: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String)
    key: Mapped[str] = mapped_column(String)
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String)
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime)


class WorkspaceQuotaRow(Base):
    __tablename__ = "workspace_quotas"

    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.workspace_id"), primary_key=True
    )
    platform: Mapped[str] = mapped_column(String, primary_key=True)
    daily_leases: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)


class UnitPriceRow(Base):
    __tablename__ = "unit_prices"

    kind: Mapped[str] = mapped_column(String, primary_key=True)
    key: Mapped[str] = mapped_column(String, primary_key=True)
    unit: Mapped[str] = mapped_column(String, primary_key=True)
    usd_per_unit: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)

"""SQLAlchemy ORM mapping of the workflow steps table (editor migration 0019)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from thoth_control_plane.infrastructure.source_account_models import Base, UtcDateTime


class WorkflowStepRow(Base):
    __tablename__ = "workflow_steps"

    # SQLite only autoincrements an INTEGER primary key, so the variant keeps the SQLite
    # fixtures inserting while Postgres keeps the BIGSERIAL of migration 0019.
    seq: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    # No ORM foreign key: the row may be written before `workflow_runs` has one (spec section 4).
    workflow_id: Mapped[str] = mapped_column(String)
    attempt: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String)
    at: Mapped[datetime] = mapped_column(UtcDateTime)
    kind: Mapped[str] = mapped_column(String)
    code: Mapped[str] = mapped_column(String)
    n: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wait_until: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    params: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

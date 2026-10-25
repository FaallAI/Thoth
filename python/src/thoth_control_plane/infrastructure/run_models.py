"""SQLAlchemy ORM mapping of the projects and workflow_runs tables (editor migration 0012)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from thoth_control_plane.infrastructure.source_account_models import Base, UtcDateTime


class ProjectRow(Base):
    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)
    #: No ORM foreign key and no default: the 0014 constraint is the authority, and a row must
    #: never fall into the bootstrap workspace silently. (SQLite fixtures that build only the
    #: run tables have no `workspaces` table to point at.)
    workspace_id: Mapped[str] = mapped_column(String)


class WorkflowRunRow(Base):
    __tablename__ = "workflow_runs"

    workflow_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("projects.project_id"), nullable=True
    )
    actor_type: Mapped[str] = mapped_column(String)
    actor_id: Mapped[str] = mapped_column(String)
    display_url: Mapped[str] = mapped_column(String)
    platform: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    history_expired: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)
    # Editor migration 0020: set once by an explicit acknowledge, never by opening a run.
    acknowledged_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

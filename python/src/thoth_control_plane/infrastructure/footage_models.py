"""SQLAlchemy ORM mapping of the footage tables (editor migration 0010)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from thoth_control_plane.infrastructure.source_account_models import Base, UtcDateTime


class FootageSearchRow(Base):
    __tablename__ = "footage_searches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    platform: Mapped[str] = mapped_column(String)
    query: Mapped[str] = mapped_column(String)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(UtcDateTime)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)


class FootageRunRow(Base):
    __tablename__ = "footage_runs"

    workflow_id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String)
    footage_status: Mapped[str | None] = mapped_column(String, nullable=True)
    objects: Mapped[list[dict[str, str]]] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # The TikTok profile page card the creator listing cropped (migration 0018, spec 5c-2).
    profile_page: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Migration 0033 (footage library): the run's context card, None on the object path.
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class FootageCandidateRow(Base):
    __tablename__ = "footage_candidates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[str] = mapped_column(
        String, ForeignKey("footage_runs.workflow_id", ondelete="CASCADE")
    )
    url: Mapped[str] = mapped_column(String)
    platform: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    media_kind: Mapped[str] = mapped_column(String, default="video")
    query: Mapped[str] = mapped_column(String)
    visual: Mapped[str] = mapped_column(String)
    owner_handle: Mapped[str] = mapped_column(String)
    caption: Mapped[str] = mapped_column(String, default="")
    published_at: Mapped[str | None] = mapped_column(String, nullable=True)
    engagement: Mapped[dict[str, int]] = mapped_column(JSON)
    source_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    story_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    kind: Mapped[str | None] = mapped_column(String, nullable=True)
    shows_object: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    media_location: Mapped[str | None] = mapped_column(String, nullable=True)
    media_checksum: Mapped[str | None] = mapped_column(String, nullable=True)
    media_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    clip_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    clip_start: Mapped[float | None] = mapped_column(Float, nullable=True)
    ocr: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)


class FootageLibraryRow(Base):
    """One kept clip in a workspace's footage library (migration 0033). The workspace foreign
    key lives in the SQL only, like `projects.workspace_id`."""

    __tablename__ = "footage_library"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String)
    platform: Mapped[str] = mapped_column(String)
    owner_handle: Mapped[str] = mapped_column(String, default="")
    published_at: Mapped[str | None] = mapped_column(String, nullable=True)
    section_start: Mapped[float] = mapped_column(Float, default=0.0)
    section_end: Mapped[float | None] = mapped_column(Float, nullable=True)
    media_location: Mapped[str] = mapped_column(String)
    media_checksum: Mapped[str] = mapped_column(String)
    hashes: Mapped[list[int]] = mapped_column(JSON, default=list)
    names: Mapped[list[str]] = mapped_column(JSON, default=list)
    event: Mapped[str] = mapped_column(String, default="")
    first_workflow_id: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)

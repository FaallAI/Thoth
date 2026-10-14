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


class FootageCandidateRow(Base):
    __tablename__ = "footage_candidates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[str] = mapped_column(
        String, ForeignKey("footage_runs.workflow_id", ondelete="CASCADE")
    )
    url: Mapped[str] = mapped_column(String)
    platform: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
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

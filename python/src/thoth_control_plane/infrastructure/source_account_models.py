"""SQLAlchemy ORM mapping of the source-account tables (editor migration 0008)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    TypeDecorator,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class UtcDateTime(TypeDecorator[datetime]):
    """Aware UTC in Python; `timestamptz` on Postgres, naive UTC on SQLite (tests)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        value = value.astimezone(UTC)
        return value if dialect.name == "postgresql" else value.replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class SourceAccountPolicyRow(Base):
    __tablename__ = "source_account_policies"

    platform: Mapped[str] = mapped_column(String, primary_key=True)
    mode: Mapped[str] = mapped_column(String)
    min_spacing_seconds: Mapped[int] = mapped_column(Integer, default=60)
    # NULL means the platform default; 0 means unlimited (editor migration 0009).
    daily_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engine: Mapped[str] = mapped_column(String, default="patchright")
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)


class SourceProxyRow(Base):
    __tablename__ = "source_proxies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    scheme: Mapped[str] = mapped_column(String)
    display: Mapped[str] = mapped_column(String)
    fingerprint: Mapped[str] = mapped_column(String, unique=True)
    proxy_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class SourceAccountRow(Base):
    __tablename__ = "source_accounts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    platform: Mapped[str] = mapped_column(String)
    label: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    cooldown_level: Mapped[int] = mapped_column(SmallInteger, default=0)
    cooldown_until: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    leased_until: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    cookies_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    cookie_names: Mapped[list[str]] = mapped_column(JSON)
    cookies_earliest_expiry: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    proxy_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("source_proxies.id", ondelete="RESTRICT"), unique=True, nullable=True
    )
    locale: Mapped[str] = mapped_column(String, default="id-ID")
    timezone: Mapped[str] = mapped_column(String, default="Asia/Jakarta")
    fingerprint_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)


class SourceAccountUsageRow(Base):
    """Leases per account per UTC day, for the daily budget (editor migration 0009)."""

    __tablename__ = "source_account_usage"

    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("source_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    uses: Mapped[int] = mapped_column(Integer, default=0)

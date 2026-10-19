"""SQLAlchemy ORM mapping of the accounts tables (editor migration 0013)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from thoth_control_plane.infrastructure.source_account_models import Base, UtcDateTime


class WorkspaceRow(Base):
    __tablename__ = "workspaces"

    workspace_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class UserRow(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True)
    display_name: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    disabled_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class UserIdentityRow(Base):
    __tablename__ = "user_identities"

    provider: Mapped[str] = mapped_column(String, primary_key=True)
    subject: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.user_id"))
    email_at_sign_in: Mapped[str] = mapped_column(String)
    last_sign_in_at: Mapped[datetime] = mapped_column(UtcDateTime)


class MemberRow(Base):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.workspace_id"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.user_id"), primary_key=True)
    role: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class SessionRow(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.user_id"))
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.workspace_id"))
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class DeviceRow(Base):
    __tablename__ = "trusted_devices"

    device_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.user_id"))
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class ChallengeRow(Base):
    __tablename__ = "email_challenges"

    challenge_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.user_id"))
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    code_hmac: Mapped[str] = mapped_column(String)
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class TokenRow(Base):
    __tablename__ = "access_tokens"

    token_id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_kind: Mapped[str] = mapped_column(String)
    owner_id: Mapped[str] = mapped_column(String)
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.workspace_id"))
    name: Mapped[str] = mapped_column(String)
    prefix: Mapped[str] = mapped_column(String)
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    scope: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    parent_token_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("access_tokens.token_id"), nullable=True
    )


class AuthEventRow(Base):
    __tablename__ = "auth_events"

    # BIGSERIAL on Postgres; SQLite only autoincrements an INTEGER primary key.
    event_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    at: Mapped[datetime] = mapped_column(UtcDateTime)
    kind: Mapped[str] = mapped_column(String)
    outcome: Mapped[str] = mapped_column(String)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    token_id: Mapped[str | None] = mapped_column(String, nullable=True)
    detail_code: Mapped[str | None] = mapped_column(String, nullable=True)

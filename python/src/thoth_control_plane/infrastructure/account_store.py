"""Accounts in PostgreSQL (editor migration 0013).

Synchronous like the project store; callers wrap calls in `asyncio.to_thread`. A database error is
`AccountStoreUnavailable`, never an absent account.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID, VerifiedIdentity
from thoth_control_plane.infrastructure.account_models import (
    MemberRow,
    UserIdentityRow,
    UserRow,
    WorkspaceRow,
)

logger = logging.getLogger(__name__)


class AccountStoreUnavailable(RuntimeError):
    """The database could not be reached or refused the statement."""


@dataclass(frozen=True)
class AccountUser:
    user_id: str
    email: str
    display_name: str
    workspace_id: str
    role: str
    disabled: bool


def _unavailable(error: Exception) -> AccountStoreUnavailable:
    logger.warning("account store failed: %s", type(error).__name__)
    return AccountStoreUnavailable("account_store_unavailable")


class AccountStore:
    def __init__(
        self, engine: Engine, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._engine = engine
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        self._clock = clock

    @classmethod
    def connect(cls, database_url: str) -> AccountStore:
        url = make_url(database_url).set(drivername="postgresql+psycopg")
        return cls(
            create_engine(
                url,
                pool_pre_ping=True,
                pool_size=2,
                max_overflow=4,
                hide_parameters=True,
                connect_args={"connect_timeout": 10},
            )
        )

    # --- users, identities, workspaces ----------------------------------------------------

    def upsert_identity(self, identity: VerifiedIdentity) -> AccountUser:
        """The user behind a verified identity: linked by (provider, subject), else by email."""
        now = self._clock()
        try:
            with self._sessions.begin() as session:
                link = session.get(UserIdentityRow, (identity.provider, identity.subject))
                user = (
                    session.get(UserRow, link.user_id)
                    if link is not None
                    else session.scalar(select(UserRow).where(UserRow.email == identity.email))
                )
                if user is None:
                    user = self._new_user(session, identity.email, identity.display_name, now)
                if link is None:
                    session.add(
                        UserIdentityRow(
                            provider=identity.provider,
                            subject=identity.subject,
                            user_id=user.user_id,
                            email_at_sign_in=identity.email,
                            last_sign_in_at=now,
                        )
                    )
                else:
                    link.email_at_sign_in = identity.email
                    link.last_sign_in_at = now
                return self._account(session, user)
        except SQLAlchemyError as error:
            raise _unavailable(error) from None

    def ensure_user(self, email: str, display_name: str) -> AccountUser:
        """The user with this email, created when missing (the bootstrap CLI)."""
        now = self._clock()
        try:
            with self._sessions.begin() as session:
                user = session.scalar(select(UserRow).where(UserRow.email == email))
                if user is None:
                    user = self._new_user(session, email, display_name, now)
                return self._account(session, user)
        except SQLAlchemyError as error:
            raise _unavailable(error) from None

    def account(self, user_id: str) -> AccountUser | None:
        try:
            with self._sessions() as session:
                user = session.get(UserRow, user_id)
                return None if user is None else self._account(session, user)
        except SQLAlchemyError as error:
            raise _unavailable(error) from None

    def _new_user(self, session: Session, email: str, name: str, now: datetime) -> UserRow:
        user = UserRow(
            user_id=f"usr_{uuid4().hex}",
            email=email,
            display_name=(name or email)[:200],
            created_at=now,
        )
        session.add(user)
        session.flush()
        # ponytail: two first sign-ins racing may both own the bootstrap; harmless until
        # sub-project 2 scopes data by workspace.
        taken = session.scalar(
            select(func.count())
            .select_from(MemberRow)
            .where(MemberRow.workspace_id == BOOTSTRAP_WORKSPACE_ID)
        )
        workspace_id = BOOTSTRAP_WORKSPACE_ID
        if taken:
            workspace_id = f"ws_{uuid4().hex}"
            session.add(
                WorkspaceRow(
                    workspace_id=workspace_id,
                    name=f"{user.display_name}'s workspace"[:120],
                    created_at=now,
                )
            )
        session.add(
            MemberRow(workspace_id=workspace_id, user_id=user.user_id, role="owner", created_at=now)
        )
        session.flush()
        return user

    @staticmethod
    def _account(session: Session, user: UserRow) -> AccountUser:
        member = session.scalars(
            select(MemberRow)
            .where(MemberRow.user_id == user.user_id)
            .order_by(MemberRow.created_at, MemberRow.workspace_id)
        ).first()
        return AccountUser(
            user_id=user.user_id,
            email=user.email,
            display_name=user.display_name,
            workspace_id=member.workspace_id if member else BOOTSTRAP_WORKSPACE_ID,
            role=member.role if member else "member",
            disabled=user.disabled_at is not None,
        )

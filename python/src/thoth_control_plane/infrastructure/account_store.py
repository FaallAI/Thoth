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

from sqlalchemy import create_engine, delete, func, select, update
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID, VerifiedIdentity
from thoth_control_plane.infrastructure.account_models import (
    AuthEventRow,
    ChallengeRow,
    DeviceRow,
    MemberRow,
    SessionRow,
    TokenRow,
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


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    user_id: str
    workspace_id: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class ChallengeRecord:
    challenge_id: str
    user_id: str
    code_hmac: str
    attempts: int
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class TokenRecord:
    token_id: str
    owner_kind: str
    owner_id: str
    workspace_id: str
    name: str
    prefix: str
    scope: str
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    parent_token_id: str | None = None


def _unavailable(error: Exception) -> AccountStoreUnavailable:
    logger.warning("account store failed: %s", type(error).__name__)
    return AccountStoreUnavailable("account_store_unavailable")


def _session(row: SessionRow) -> SessionRecord:
    return SessionRecord(
        row.session_id,
        row.user_id,
        row.workspace_id,
        row.created_at,
        row.last_seen_at,
        row.expires_at,
    )


def _token(row: TokenRow) -> TokenRecord:
    return TokenRecord(
        row.token_id,
        row.owner_kind,
        row.owner_id,
        row.workspace_id,
        row.name,
        row.prefix,
        row.scope,
        row.created_at,
        row.expires_at,
        row.last_used_at,
        row.parent_token_id,
    )


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

    # --- sessions --------------------------------------------------------------------------

    def create_session(
        self, user_id: str, workspace_id: str, token_hash: str, expires_at: datetime
    ) -> SessionRecord:
        now = self._clock()
        row = SessionRow(
            session_id=f"ses_{uuid4().hex}",
            user_id=user_id,
            workspace_id=workspace_id,
            token_hash=token_hash,
            created_at=now,
            last_seen_at=now,
            expires_at=expires_at,
        )
        self._write(lambda session: session.add(row))
        return _session(row)

    def live_session(self, token_hash: str) -> SessionRecord | None:
        row = self._one(
            select(SessionRow).where(
                SessionRow.token_hash == token_hash,
                SessionRow.revoked_at.is_(None),
                SessionRow.expires_at > self._clock(),
            )
        )
        return None if row is None else _session(row)

    def extend_session(self, session_id: str, expires_at: datetime, seen_at: datetime) -> None:
        self._execute(
            update(SessionRow)
            .where(SessionRow.session_id == session_id)
            .values(expires_at=expires_at, last_seen_at=seen_at)
        )

    def revoke_session(self, token_hash: str) -> None:
        self._execute(
            update(SessionRow)
            .where(SessionRow.token_hash == token_hash, SessionRow.revoked_at.is_(None))
            .values(revoked_at=self._clock())
        )

    # --- trusted browsers ------------------------------------------------------------------

    def trust_device(self, user_id: str, token_hash: str, expires_at: datetime) -> None:
        row = DeviceRow(
            device_id=f"dev_{uuid4().hex}",
            user_id=user_id,
            token_hash=token_hash,
            created_at=self._clock(),
            expires_at=expires_at,
        )
        self._write(lambda session: session.add(row))

    def is_trusted(self, user_id: str, token_hash: str) -> bool:
        return (
            self._one(
                select(DeviceRow).where(
                    DeviceRow.token_hash == token_hash,
                    DeviceRow.user_id == user_id,
                    DeviceRow.revoked_at.is_(None),
                    DeviceRow.expires_at > self._clock(),
                )
            )
            is not None
        )

    def forget_device(self, token_hash: str) -> None:
        self._execute(
            update(DeviceRow)
            .where(DeviceRow.token_hash == token_hash, DeviceRow.revoked_at.is_(None))
            .values(revoked_at=self._clock())
        )

    # --- email challenges ------------------------------------------------------------------

    def create_challenge(
        self,
        challenge_id: str,
        user_id: str,
        token_hash: str,
        code_hmac: str,
        expires_at: datetime,
    ) -> None:
        row = ChallengeRow(
            challenge_id=challenge_id,
            user_id=user_id,
            token_hash=token_hash,
            code_hmac=code_hmac,
            attempts=0,
            created_at=self._clock(),
            expires_at=expires_at,
        )
        self._write(lambda session: session.add(row))

    def live_challenge(self, token_hash: str) -> ChallengeRecord | None:
        row = self._one(
            select(ChallengeRow).where(
                ChallengeRow.token_hash == token_hash,
                ChallengeRow.consumed_at.is_(None),
                ChallengeRow.expires_at > self._clock(),
            )
        )
        if row is None:
            return None
        return ChallengeRecord(
            row.challenge_id,
            row.user_id,
            row.code_hmac,
            row.attempts,
            row.created_at,
            row.expires_at,
        )

    def claim_attempt(self, token_hash: str) -> ChallengeRecord | None:
        """Count one guess before it is checked, atomically; None once 5 were counted, or used."""
        try:
            with self._sessions.begin() as session:
                row = session.execute(
                    update(ChallengeRow)
                    .where(
                        ChallengeRow.token_hash == token_hash,
                        ChallengeRow.consumed_at.is_(None),
                        ChallengeRow.expires_at > self._clock(),
                        ChallengeRow.attempts < 5,
                    )
                    .values(attempts=ChallengeRow.attempts + 1)
                    .returning(
                        ChallengeRow.challenge_id,
                        ChallengeRow.user_id,
                        ChallengeRow.code_hmac,
                        ChallengeRow.attempts,
                        ChallengeRow.created_at,
                        ChallengeRow.expires_at,
                    )
                ).first()
        except SQLAlchemyError as error:
            raise _unavailable(error) from None
        return None if row is None else ChallengeRecord(*row)

    def consume_challenge(self, challenge_id: str) -> bool:
        try:
            with self._sessions.begin() as session:
                result = session.execute(
                    update(ChallengeRow)
                    .where(
                        ChallengeRow.challenge_id == challenge_id,
                        ChallengeRow.consumed_at.is_(None),
                    )
                    .values(consumed_at=self._clock())
                )
                return result.rowcount == 1
        except SQLAlchemyError as error:
            raise _unavailable(error) from None

    def discard_challenge(self, challenge_id: str) -> None:
        """Forget a challenge whose code never left, so it counts toward no limit."""
        self._execute(delete(ChallengeRow).where(ChallengeRow.challenge_id == challenge_id))

    def challenge_times(self, user_id: str, since: datetime) -> list[datetime]:
        try:
            with self._sessions() as session:
                return list(
                    session.scalars(
                        select(ChallengeRow.created_at)
                        .where(ChallengeRow.user_id == user_id, ChallengeRow.created_at >= since)
                        .order_by(ChallengeRow.created_at)
                    )
                )
        except SQLAlchemyError as error:
            raise _unavailable(error) from None

    # --- developer tokens ------------------------------------------------------------------

    def create_token(self, record: TokenRecord, token_hash: str, limit: int | None = None) -> bool:
        """Insert a token; with a limit, refuse (False) when the owner already holds that many.

        The owner's row is locked first, so parallel creates cannot both pass the count.
        """
        row = TokenRow(
            token_id=record.token_id,
            owner_kind=record.owner_kind,
            owner_id=record.owner_id,
            workspace_id=record.workspace_id,
            name=record.name,
            prefix=record.prefix,
            token_hash=token_hash,
            scope=record.scope,
            created_at=record.created_at,
            expires_at=record.expires_at,
            parent_token_id=record.parent_token_id,
        )
        try:
            with self._sessions.begin() as session:
                if limit is not None:
                    owner = UserRow if record.owner_kind == "user" else WorkspaceRow
                    session.get(owner, record.owner_id, with_for_update=True)
                    held = session.scalar(
                        select(func.count())
                        .select_from(TokenRow)
                        .where(
                            TokenRow.owner_kind == record.owner_kind,
                            TokenRow.owner_id == record.owner_id,
                            TokenRow.revoked_at.is_(None),
                            TokenRow.expires_at > self._clock(),
                        )
                    )
                    if (held or 0) >= limit:
                        return False
                session.add(row)
                return True
        except SQLAlchemyError as error:
            raise _unavailable(error) from None

    def token(self, token_id: str) -> TokenRecord | None:
        """One token in any state (revoked or expired included), or None."""
        row = self._one(select(TokenRow).where(TokenRow.token_id == token_id))
        return None if row is None else _token(row)

    def live_token(self, token_hash: str) -> TokenRecord | None:
        row = self._one(
            select(TokenRow).where(
                TokenRow.token_hash == token_hash,
                TokenRow.revoked_at.is_(None),
                TokenRow.expires_at > self._clock(),
            )
        )
        return None if row is None else _token(row)

    def list_tokens(self, owner_kind: str, owner_id: str) -> list[TokenRecord]:
        """Tokens that are not revoked, newest first; expired ones stay listed until revoked."""
        try:
            with self._sessions() as session:
                rows = session.scalars(
                    select(TokenRow)
                    .where(
                        TokenRow.owner_kind == owner_kind,
                        TokenRow.owner_id == owner_id,
                        TokenRow.revoked_at.is_(None),
                    )
                    .order_by(TokenRow.created_at.desc(), TokenRow.token_id.desc())
                ).all()
        except SQLAlchemyError as error:
            raise _unavailable(error) from None
        return [_token(row) for row in rows]

    def active_token_count(self, owner_kind: str, owner_id: str) -> int:
        try:
            with self._sessions() as session:
                return int(
                    session.scalar(
                        select(func.count())
                        .select_from(TokenRow)
                        .where(
                            TokenRow.owner_kind == owner_kind,
                            TokenRow.owner_id == owner_id,
                            TokenRow.revoked_at.is_(None),
                            TokenRow.expires_at > self._clock(),
                        )
                    )
                    or 0
                )
        except SQLAlchemyError as error:
            raise _unavailable(error) from None

    def revoke_token(self, token_id: str, owner_kind: str, owner_id: str) -> bool:
        """Revoke one of the owner's tokens and, transitively, every token it minted."""
        now = self._clock()
        try:
            with self._sessions.begin() as session:
                result = session.execute(
                    update(TokenRow)
                    .where(
                        TokenRow.token_id == token_id,
                        TokenRow.owner_kind == owner_kind,
                        TokenRow.owner_id == owner_id,
                        TokenRow.revoked_at.is_(None),
                    )
                    .values(revoked_at=now)
                )
                if result.rowcount != 1:
                    return False
                frontier = [token_id]
                while frontier:
                    frontier = list(
                        session.scalars(
                            update(TokenRow)
                            .where(
                                TokenRow.parent_token_id.in_(frontier),
                                TokenRow.revoked_at.is_(None),
                            )
                            .values(revoked_at=now)
                            .returning(TokenRow.token_id)
                        )
                    )
                return True
        except SQLAlchemyError as error:
            raise _unavailable(error) from None

    def touch_token(self, token_id: str, at: datetime) -> None:
        self._execute(update(TokenRow).where(TokenRow.token_id == token_id).values(last_used_at=at))

    # --- events ----------------------------------------------------------------------------

    def record_event(
        self,
        kind: str,
        outcome: str,
        *,
        user_id: str | None = None,
        token_id: str | None = None,
        detail_code: str | None = None,
    ) -> None:
        row = AuthEventRow(
            at=self._clock(),
            kind=kind,
            outcome=outcome,
            user_id=user_id,
            token_id=token_id,
            detail_code=detail_code,
        )
        self._write(lambda session: session.add(row))

    # --- plumbing --------------------------------------------------------------------------

    def _write(self, action: Callable[[Session], object]) -> None:
        try:
            with self._sessions.begin() as session:
                action(session)
        except SQLAlchemyError as error:
            raise _unavailable(error) from None

    def _execute(self, statement: object) -> None:
        self._write(lambda session: session.execute(statement))

    def _one(self, statement: object):
        try:
            with self._sessions() as session:
                return session.scalars(statement).first()
        except SQLAlchemyError as error:
            raise _unavailable(error) from None

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

"""Sign-in rules: email codes, sessions, trusted browsers and developer tokens (spec 2-3).

Every store call runs off the event loop. A store failure is `AuthUnavailable`; an audit row
that cannot be written is logged and never blocks a sign-in.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from thoth_control_plane.auth.mailer import Mailer, MailNotSent
from thoth_control_plane.auth.models import (
    ALL_SCOPES,
    SCOPE_SETS,
    CreatedToken,
    CreateToken,
    MeView,
    Principal,
    SignInRefused,
    TokenView,
    VerifiedIdentity,
)
from thoth_control_plane.auth.secrets import (
    TOKEN_PREFIX,
    code_hmac,
    new_code,
    random_token,
    same,
    token_hash,
)
from thoth_control_plane.infrastructure.account_store import (
    AccountStore,
    AccountStoreUnavailable,
    AccountUser,
    TokenRecord,
)

logger = logging.getLogger(__name__)

SESSION_IDLE = timedelta(hours=12)
SESSION_MAX = timedelta(days=7)
DEVICE_TTL = timedelta(days=30)
CODE_TTL = timedelta(minutes=10)
CODE_ATTEMPTS = 5
RESEND_AFTER = timedelta(seconds=60)
DAILY_CODES = 10
TOKEN_LIMIT = 20
TOUCH_EVERY = timedelta(minutes=1)
CODE_SUBJECT = "Your Thoth sign-in code"


@dataclass(frozen=True)
class SignedIn:
    session_token: str
    session_expires_at: datetime
    device_token: str | None


@dataclass(frozen=True)
class CodeSent:
    challenge_token: str


class _Coded(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CodeRejected(_Coded):
    """`wrong_code`, `expired` or `too_many_attempts`."""


class CodeLimited(_Coded):
    """`resend_too_soon` or `daily_limit`."""


class CodeNotSent(Exception):
    pass


class AuthUnavailable(Exception):
    pass


class UserRequired(Exception):
    pass


class TokenLimitReached(Exception):
    pass


class ScopeTooBroad(Exception):
    pass


def token_view(record: TokenRecord) -> TokenView:
    return TokenView(
        token_id=record.token_id,
        owner_kind=record.owner_kind,  # type: ignore[arg-type]
        name=record.name,
        prefix=record.prefix,
        scope=record.scope,  # type: ignore[arg-type]
        created_at=record.created_at,
        expires_at=record.expires_at,
        last_used_at=record.last_used_at,
    )


class SignInService:
    def __init__(
        self,
        store: AccountStore,
        mailer: Mailer | None,
        secret: str | None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._mailer = mailer
        self._secret = secret
        self._clock = clock

    async def _run(self, function: Callable[..., Any], *args: Any) -> Any:
        try:
            return await asyncio.to_thread(function, *args)
        except AccountStoreUnavailable as error:
            raise AuthUnavailable() from error

    async def _event(self, kind: str, outcome: str, **fields: str | None) -> None:
        try:
            await asyncio.to_thread(self._store.record_event, kind, outcome, **fields)
        except AccountStoreUnavailable:
            logger.warning("auth event %s was not recorded", kind)

    # --- signing in ------------------------------------------------------------------------

    async def begin(
        self,
        identity: VerifiedIdentity,
        device_token: str | None,
        previous_session: str | None = None,
    ) -> SignedIn | CodeSent:
        if self._secret is None or self._mailer is None:
            raise SignInRefused("not_configured")
        account: AccountUser = await self._run(self._store.upsert_identity, identity)
        if account.disabled:
            await self._event(
                "sign_in", "refused", user_id=account.user_id, detail_code="not_allowed"
            )
            raise SignInRefused("not_allowed")
        if device_token and await self._run(
            self._store.is_trusted, account.user_id, token_hash(device_token)
        ):
            if previous_session:  # a new sign-in never keeps the old session alive
                await self._run(self._store.revoke_session, token_hash(previous_session))
            return await self._start(account, trust_device=False)
        try:
            # The cooldown also applies here, so repeated (even forced) sign-ins cannot burn
            # the daily code limit in a burst.
            return await self._send_code(account, enforce_cooldown=True)
        except CodeLimited as limited:
            code = "too_soon" if limited.code == "resend_too_soon" else "too_many_codes"
            raise SignInRefused(code) from None

    async def verify(
        self,
        challenge_token: str,
        code: str,
        *,
        trust_device: bool,
        previous_session: str | None,
    ) -> SignedIn:
        # Every guess claims one of the five attempts atomically before it is checked, so racing
        # requests cannot get more than five codes evaluated.
        hashed = token_hash(challenge_token)
        record = await self._run(self._store.claim_attempt, hashed)
        if record is None:
            live = await self._run(self._store.live_challenge, hashed)
            raise CodeRejected("too_many_attempts" if live is not None else "expired")
        expected = code_hmac(self._secret or "", record.challenge_id, code.strip())
        if not same(record.code_hmac, expected):
            if record.attempts >= CODE_ATTEMPTS:
                await self._run(self._store.consume_challenge, record.challenge_id)
                await self._event(
                    "email_code", "refused", user_id=record.user_id, detail_code="too_many_attempts"
                )
                raise CodeRejected("too_many_attempts")
            raise CodeRejected("wrong_code")
        if not await self._run(self._store.consume_challenge, record.challenge_id):
            raise CodeRejected("expired")  # a concurrent verification won
        account = await self._run(self._store.account, record.user_id)
        if account is None or account.disabled:
            raise SignInRefused("not_allowed")
        if previous_session:
            await self._run(self._store.revoke_session, token_hash(previous_session))
        return await self._start(account, trust_device=trust_device)

    async def resend(self, challenge_token: str) -> CodeSent:
        if self._secret is None or self._mailer is None:
            raise SignInRefused("not_configured")
        record = await self._run(self._store.live_challenge, token_hash(challenge_token))
        if record is None:
            raise CodeRejected("expired")
        account = await self._run(self._store.account, record.user_id)
        if account is None or account.disabled:
            raise SignInRefused("not_allowed")
        sent = await self._send_code(account, enforce_cooldown=True)
        await self._run(self._store.consume_challenge, record.challenge_id)
        return sent

    async def logout(
        self, session_token: str | None, device_token: str | None, *, forget_device: bool
    ) -> None:
        if session_token:
            await self._run(self._store.revoke_session, token_hash(session_token))
        if forget_device and device_token:
            await self._run(self._store.forget_device, token_hash(device_token))

    # --- who is calling --------------------------------------------------------------------

    async def authenticate_session(self, session_token: str) -> Principal | None:
        record = await self._run(self._store.live_session, token_hash(session_token))
        if record is None:
            return None
        account = await self._run(self._store.account, record.user_id)
        if account is None or account.disabled:
            return None
        now = self._clock()
        if now - record.last_seen_at >= TOUCH_EVERY:
            expires = min(now + SESSION_IDLE, record.created_at + SESSION_MAX)
            await self._run(self._store.extend_session, record.session_id, expires, now)
        return Principal(account.user_id, record.workspace_id, ALL_SCOPES, "session", account.email)

    async def authenticate_token(self, text: str) -> Principal | None:
        if not text.startswith(TOKEN_PREFIX):
            return None
        record = await self._run(self._store.live_token, token_hash(text))
        if record is None:
            return None
        user_id = email = None
        if record.owner_kind == "user":
            account = await self._run(self._store.account, record.owner_id)
            if account is None or account.disabled:
                return None
            user_id, email = account.user_id, account.email
        now = self._clock()
        if record.last_used_at is None or now - record.last_used_at >= TOUCH_EVERY:
            await self._run(self._store.touch_token, record.token_id, now)
        return Principal(
            user_id, record.workspace_id, SCOPE_SETS[record.scope], "token", email, record.token_id
        )

    async def describe(self, principal: Principal) -> MeView:
        name = None
        if principal.user_id is not None:
            account = await self._run(self._store.account, principal.user_id)
            name = account.display_name if account else None
        return MeView(
            user_id=principal.user_id,
            email=principal.email,
            display_name=name,
            workspace_id=principal.workspace_id,
            scopes=sorted(principal.scopes),  # type: ignore[arg-type]
        )

    async def note_service_key(self) -> None:
        await self._event("service_key", "ok")

    # --- developer tokens ------------------------------------------------------------------

    async def create_token(self, principal: Principal, request: CreateToken) -> CreatedToken:
        if principal.user_id is None:
            raise UserRequired()
        if not SCOPE_SETS[request.scope] <= principal.scopes:
            raise ScopeTooBroad()
        return await self._issue(
            "user",
            principal.user_id,
            principal.workspace_id,
            request,
            principal.user_id,
            principal.token_id,
        )

    async def create_workspace_token(
        self, principal: Principal, request: CreateToken
    ) -> CreatedToken:
        """External developer tokens. The route refuses this until the operator enables them."""
        if principal.user_id is None:
            raise UserRequired()
        account = await self._run(self._store.account, principal.user_id)
        if (
            account is None
            or account.role not in ("owner", "admin")
            or not SCOPE_SETS[request.scope] <= principal.scopes
        ):
            raise ScopeTooBroad()
        return await self._issue(
            "workspace",
            principal.workspace_id,
            principal.workspace_id,
            request,
            principal.user_id,
            principal.token_id,
        )

    async def list_tokens(self, principal: Principal) -> list[TokenView]:
        if principal.user_id is None:
            raise UserRequired()
        records = await self._run(self._store.list_tokens, "user", principal.user_id)
        return [token_view(record) for record in records]

    async def revoke_token(self, principal: Principal, token_id: str) -> bool:
        if principal.user_id is None:
            raise UserRequired()
        revoked = await self._run(self._store.revoke_token, token_id, "user", principal.user_id)
        if revoked:
            await self._event("token_revoked", "ok", user_id=principal.user_id, token_id=token_id)
        return revoked

    # --- internals -------------------------------------------------------------------------

    async def _issue(
        self,
        owner_kind: str,
        owner_id: str,
        workspace_id: str,
        request: CreateToken,
        actor_user_id: str,
        parent_token_id: str | None = None,
    ) -> CreatedToken:
        secret = random_token(TOKEN_PREFIX)
        now = self._clock()
        expires_at = now + timedelta(days=request.days)
        if parent_token_id is not None:
            # A token minted by a token never outlives it, and revoking it revokes this one.
            parent = await self._run(self._store.token, parent_token_id)
            if parent is not None:
                expires_at = min(expires_at, parent.expires_at)
        record = TokenRecord(
            token_id=f"tok_{uuid4().hex}",
            owner_kind=owner_kind,
            owner_id=owner_id,
            workspace_id=workspace_id,
            name=request.name.strip(),
            prefix=secret[: len(TOKEN_PREFIX) + 6],
            scope=request.scope,
            created_at=now,
            expires_at=expires_at,
            last_used_at=None,
            parent_token_id=parent_token_id,
        )
        if not await self._run(self._store.create_token, record, token_hash(secret), TOKEN_LIMIT):
            raise TokenLimitReached()
        await self._event("token_created", "ok", user_id=actor_user_id, token_id=record.token_id)
        return CreatedToken(token=token_view(record), secret=secret)

    async def _start(self, account: AccountUser, *, trust_device: bool) -> SignedIn:
        now = self._clock()
        session_token = random_token()
        expires = now + SESSION_IDLE
        await self._run(
            self._store.create_session,
            account.user_id,
            account.workspace_id,
            token_hash(session_token),
            expires,
        )
        device = None
        if trust_device:
            device = random_token()
            await self._run(
                self._store.trust_device, account.user_id, token_hash(device), now + DEVICE_TTL
            )
        await self._event("sign_in", "ok", user_id=account.user_id)
        return SignedIn(session_token, expires, device)

    async def _send_code(self, account: AccountUser, *, enforce_cooldown: bool) -> CodeSent:
        assert self._mailer is not None and self._secret is not None  # begin() checked both
        now = self._clock()
        times = await self._run(
            self._store.challenge_times, account.user_id, now - timedelta(days=1)
        )
        if len(times) >= DAILY_CODES:
            raise CodeLimited("daily_limit")
        if enforce_cooldown and times and now - times[-1] < RESEND_AFTER:
            raise CodeLimited("resend_too_soon")
        challenge_id = f"chl_{uuid4().hex}"
        code = new_code()
        challenge = random_token()
        await self._run(
            self._store.create_challenge,
            challenge_id,
            account.user_id,
            token_hash(challenge),
            code_hmac(self._secret, challenge_id, code),
            now + CODE_TTL,
        )
        body = (
            f"Your Thoth sign-in code is {code}.\n\n"
            "It expires in 10 minutes. If you did not try to sign in, ignore this email.\n"
        )
        try:
            await self._mailer.send(account.email, CODE_SUBJECT, body)
        except MailNotSent:
            # Nothing reached the user: no cooldown and no daily count for this attempt.
            await self._run(self._store.discard_challenge, challenge_id)
            await self._event(
                "email_code", "failed", user_id=account.user_id, detail_code="code_not_sent"
            )
            raise CodeNotSent() from None
        await self._event("email_code", "ok", user_id=account.user_id)
        return CodeSent(challenge)

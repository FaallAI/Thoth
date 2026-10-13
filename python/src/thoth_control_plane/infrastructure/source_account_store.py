"""Source accounts, their per-platform policy, and the proxy pool, on SQLAlchemy ORM.

Synchronous: async callers run it in a worker thread. Cookie sets and proxy URLs are sealed
by the vault before they reach a row and opened only to build a `SessionAccess`. Errors are
`SourceAccountError` codes; none carries a secret.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from sqlalchemy import and_, create_engine, or_, select, true
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from thoth_control_plane.acquisition.accounts import fingerprints
from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.accounts.cookies import PLATFORMS, CookieSet, Platform
from thoth_control_plane.acquisition.accounts.policy import (
    DEFAULT_DAILY_BUDGETS,
    DEFAULT_MODE,
    DEFAULT_SPACING_SECONDS,
    DEFAULT_SPACING_SECONDS_BY_PLATFORM,
    ENGINES,
    LEASE,
    Health,
    Mode,
    Outcome,
    after,
)
from thoth_control_plane.acquisition.accounts.proxies import ProxyImport
from thoth_control_plane.acquisition.accounts.vault import Vault, VaultError
from thoth_control_plane.infrastructure.source_account_models import (
    SourceAccountPolicyRow,
    SourceAccountRow,
    SourceAccountUsageRow,
    SourceProxyRow,
)

UNSET: Final = object()
# A lease skips at most this many undecryptable accounts before giving up for this call.
MAX_LEASE_ATTEMPTS = 5


class SourceAccountError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PolicyView:
    platform: Platform
    mode: Mode
    min_spacing_seconds: int
    daily_budget: int = 0  # effective: the platform default when the row leaves it unset
    engine: str = "patchright"


@dataclass(frozen=True)
class AccountView:
    id: str
    platform: Platform
    label: str
    status: str
    cooldown_until: datetime | None
    last_used_at: datetime | None
    last_outcome: str | None
    success_count: int
    failure_count: int
    cookie_names: tuple[str, ...]
    cookies_earliest_expiry: datetime | None
    proxy_id: str | None
    proxy_display: str | None
    created_at: datetime
    updated_at: datetime
    locale: str = "id-ID"
    timezone: str = "Asia/Jakarta"
    fingerprint_set: bool = False
    uses_today: int = 0


@dataclass(frozen=True)
class ProxyView:
    id: str
    scheme: str
    display: str
    account_platform: str | None
    account_label: str | None


@dataclass(frozen=True)
class ProxyImportResult:
    added: int
    duplicates: int
    invalid_lines: tuple[int, ...]


@dataclass(frozen=True)
class AccountLease:
    account_id: str
    platform: Platform
    access: SessionAccess
    # Identifies this lease: a report carrying another one is stale.
    leased_until: datetime


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError):
        raise SourceAccountError("not_found") from None


class SourceAccountStore:
    def __init__(
        self,
        engine: Engine,
        vault: Vault,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        self._vault = vault
        self._clock = clock

    @classmethod
    def connect(cls, database_url: str, vault: Vault) -> SourceAccountStore:
        url = make_url(database_url).set(drivername="postgresql+psycopg")
        return cls(create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2), vault)

    # Policies

    def policies(self) -> list[PolicyView]:
        with self._sessions() as session:
            rows = {row.platform: row for row in session.scalars(select(SourceAccountPolicyRow))}
        return [self._policy_view(platform, rows.get(platform)) for platform in PLATFORMS]

    def policy(self, platform: Platform) -> PolicyView:
        with self._sessions() as session:
            return self._policy_view(platform, session.get(SourceAccountPolicyRow, platform))

    def set_policy(
        self,
        platform: Platform,
        mode: Mode,
        min_spacing_seconds: int,
        daily_budget: int | None = None,
        engine: str = "patchright",
    ) -> PolicyView:
        if engine not in ENGINES:
            raise ValueError(f"unknown engine {engine!r}")
        with self._sessions.begin() as session:
            row = session.get(SourceAccountPolicyRow, platform)
            if row is None:
                row = SourceAccountPolicyRow(platform=platform)
                session.add(row)
            row.mode, row.min_spacing_seconds = mode, min_spacing_seconds
            row.daily_budget, row.engine = daily_budget, engine
            row.updated_at = self._clock()
        return self._policy_view(platform, row)

    @staticmethod
    def _policy_view(platform: Platform, row: SourceAccountPolicyRow | None) -> PolicyView:
        budget = DEFAULT_DAILY_BUDGETS.get(platform, 0)
        if row is None:
            spacing = DEFAULT_SPACING_SECONDS_BY_PLATFORM.get(platform, DEFAULT_SPACING_SECONDS)
            return PolicyView(platform, DEFAULT_MODE, spacing, budget)
        return PolicyView(
            platform,
            row.mode,  # type: ignore[arg-type]
            row.min_spacing_seconds,
            budget if row.daily_budget is None else row.daily_budget,
            row.engine or "patchright",
        )

    # Accounts

    def accounts(self) -> list[AccountView]:
        with self._sessions() as session:
            rows = session.scalars(
                select(SourceAccountRow).order_by(SourceAccountRow.platform, SourceAccountRow.label)
            ).all()
            return [self._account_view(session, row) for row in rows]

    def account(self, account_id: str) -> AccountView:
        with self._sessions() as session:
            return self._account_view(session, self._row(session, account_id))

    def add_account(
        self, platform: Platform, label: str, cookies: CookieSet, proxy_id: str | None = None
    ) -> AccountView:
        now = self._clock()
        with self._sessions.begin() as session:
            self._require_free_label(session, platform, label)
            row = SourceAccountRow(
                id=uuid.uuid4(),
                platform=platform,
                label=label,
                status="healthy",
                cooldown_level=0,
                success_count=0,
                failure_count=0,
                created_at=now,
                updated_at=now,
            )
            self._set_cookies(row, cookies)
            row.proxy_id = self._free_proxy(session, proxy_id, None)
            session.add(row)
            session.flush()
            return self._account_view(session, row)

    def replace_cookies(self, account_id: str, cookies: CookieSet) -> AccountView:
        with self._sessions.begin() as session:
            row = self._row(session, account_id)
            if cookies.platform != row.platform:
                raise SourceAccountError("platform_mismatch")
            self._set_cookies(row, cookies)
            if row.status != "disabled":
                row.status = "healthy"
            row.cooldown_level, row.cooldown_until = 0, None
            # A lease taken on the old cookies ends here; its report must not judge the new ones.
            row.leased_until = None
            row.updated_at = self._clock()
            return self._account_view(session, row)

    def update_account(
        self,
        account_id: str,
        *,
        label: Any = UNSET,
        proxy_id: Any = UNSET,
        disabled: bool | None = None,
        locale: str | None = None,
        timezone: str | None = None,
        reset_fingerprint: bool = False,
    ) -> AccountView:
        with self._sessions.begin() as session:
            row = self._row(session, account_id)
            if label is not UNSET and label != row.label:
                self._require_free_label(session, row.platform, label)
                row.label = label
            if proxy_id is not UNSET:
                row.proxy_id = self._free_proxy(session, proxy_id, row.id)
            if disabled is True:
                row.status = "disabled"
            elif disabled is False and row.status == "disabled":
                row.status, row.cooldown_level, row.cooldown_until = "healthy", 0, None
            if locale is not None:
                row.locale = locale
            if timezone is not None:
                row.timezone = timezone
            if reset_fingerprint:  # the route also deletes the profiles: a new device
                row.fingerprint_ciphertext = None
            row.updated_at = self._clock()
            session.flush()
            return self._account_view(session, row)

    def delete_account(self, account_id: str) -> None:
        with self._sessions.begin() as session:
            session.delete(self._row(session, account_id))

    def record_check(self, account_id: str, valid: bool) -> AccountView:
        """A manual session check: valid makes the account healthy, invalid expires it."""
        with self._sessions.begin() as session:
            row = self._row(session, account_id)
            if row.status != "disabled":
                row.status = "healthy" if valid else "expired"
                if valid:
                    row.cooldown_level, row.cooldown_until = 0, None
            row.last_outcome = "success" if valid else "login_wall"
            row.updated_at = self._clock()
            return self._account_view(session, row)

    def access(self, account_id: str) -> SessionAccess:
        """The account's session, for a manual check; an unreadable one is expired."""
        with self._sessions.begin() as session:
            row = self._row(session, account_id)
            try:
                return self._open(session, row)
            except VaultError:
                row.status, row.last_outcome = "expired", "undecryptable"
        raise SourceAccountError("undecryptable")

    # Rotation

    def lease(self, platform: Platform, engine: str | None = None) -> AccountLease | None:
        """The least recently used eligible account, held for `LEASE`; None when none is.

        `engine` defaults to the platform's; acquisition asks for Patchright (spec 3.4).
        """
        for _ in range(MAX_LEASE_ATTEMPTS):
            now = self._clock()
            policy = self.policy(platform)
            spacing = timedelta(seconds=policy.min_spacing_seconds)
            today = now.date()
            # Spec 2026-10-13, 3.3: an account that used its daily budget waits for tomorrow.
            within_budget = (
                ~SourceAccountRow.id.in_(
                    select(SourceAccountUsageRow.account_id).where(
                        SourceAccountUsageRow.day == today,
                        SourceAccountUsageRow.uses >= policy.daily_budget,
                    )
                )
                if policy.daily_budget > 0
                else true()
            )
            with self._sessions.begin() as session:
                row = session.scalars(
                    select(SourceAccountRow)
                    .where(
                        SourceAccountRow.platform == platform,
                        within_budget,
                        or_(
                            SourceAccountRow.status == "healthy",
                            and_(
                                SourceAccountRow.status == "cooldown",
                                SourceAccountRow.cooldown_until <= now,
                            ),
                        ),
                        or_(
                            SourceAccountRow.leased_until.is_(None),
                            SourceAccountRow.leased_until <= now,
                        ),
                        or_(
                            SourceAccountRow.last_used_at.is_(None),
                            SourceAccountRow.last_used_at <= now - spacing,
                        ),
                    )
                    .order_by(SourceAccountRow.last_used_at.asc().nulls_first())
                    .limit(1)
                    .with_for_update(skip_locked=True)
                ).first()
                if row is None:
                    return None
                try:
                    access = self._open(session, row, engine or policy.engine)
                except VaultError:
                    row.status, row.last_outcome, row.updated_at = "expired", "undecryptable", now
                    continue
                row.leased_until, row.last_used_at = now + LEASE, now
                usage = session.get(SourceAccountUsageRow, (row.id, today))
                if usage is None:
                    session.add(SourceAccountUsageRow(account_id=row.id, day=today, uses=1))
                else:
                    usage.uses += 1
                return AccountLease(str(row.id), platform, access, row.leased_until)
        return None

    def report(
        self, account_id: str, outcome: Outcome | None, leased_until: datetime | None = None
    ) -> None:
        """Release a lease; `outcome` None releases it without touching the account's health.

        With `leased_until`, a lease that is no longer the account's (expired and re-leased,
        or ended by a re-import) is ignored.
        """
        now = self._clock()
        with self._sessions.begin() as session:
            row = session.get(SourceAccountRow, _uuid(account_id))
            if row is None:
                return
            if leased_until is not None and row.leased_until != leased_until:
                return
            row.leased_until = None
            if outcome is not None:
                health = after(
                    Health(
                        status=row.status,  # type: ignore[arg-type]
                        cooldown_level=row.cooldown_level,
                        cooldown_until=row.cooldown_until,
                        success_count=row.success_count,
                        failure_count=row.failure_count,
                    ),
                    outcome,
                    now,
                )
                row.status, row.cooldown_level = health.status, health.cooldown_level
                row.cooldown_until = health.cooldown_until
                row.success_count, row.failure_count = health.success_count, health.failure_count
                row.last_outcome = outcome
            row.updated_at = now

    # Proxies

    def proxies(self) -> list[ProxyView]:
        with self._sessions() as session:
            holders = {
                row.proxy_id: row
                for row in session.scalars(
                    select(SourceAccountRow).where(SourceAccountRow.proxy_id.is_not(None))
                )
            }
            rows = session.scalars(select(SourceProxyRow).order_by(SourceProxyRow.created_at))
            return [
                ProxyView(
                    id=str(row.id),
                    scheme=row.scheme,
                    display=row.display,
                    account_platform=holders[row.id].platform if row.id in holders else None,
                    account_label=holders[row.id].label if row.id in holders else None,
                )
                for row in rows
            ]

    def import_proxies(self, parsed: ProxyImport) -> ProxyImportResult:
        added = duplicates = 0
        now = self._clock()
        with self._sessions.begin() as session:
            for entry in parsed.entries:
                fingerprint = self._vault.fingerprint(entry.url)
                exists = session.scalars(
                    select(SourceProxyRow.id).where(SourceProxyRow.fingerprint == fingerprint)
                ).first()
                if exists is not None:
                    duplicates += 1
                    continue
                session.add(
                    SourceProxyRow(
                        id=uuid.uuid4(),
                        scheme=entry.scheme,
                        display=entry.display,
                        fingerprint=fingerprint,
                        proxy_ciphertext=self._vault.seal(entry.url),
                        created_at=now,
                    )
                )
                added += 1
        return ProxyImportResult(added, duplicates, parsed.invalid_lines)

    def delete_proxy(self, proxy_id: str) -> None:
        with self._sessions.begin() as session:
            row = session.get(SourceProxyRow, _uuid(proxy_id))
            if row is None:
                raise SourceAccountError("not_found")
            if self._holder(session, row.id) is not None:
                raise SourceAccountError("proxy_in_use")
            session.delete(row)

    # Helpers

    def _row(self, session: Session, account_id: str) -> SourceAccountRow:
        row = session.get(SourceAccountRow, _uuid(account_id))
        if row is None:
            raise SourceAccountError("not_found")
        return row

    @staticmethod
    def _holder(session: Session, proxy_id: uuid.UUID) -> SourceAccountRow | None:
        return session.scalars(
            select(SourceAccountRow).where(SourceAccountRow.proxy_id == proxy_id)
        ).first()

    def _require_free_label(self, session: Session, platform: str, label: str) -> None:
        taken = session.scalars(
            select(SourceAccountRow.id).where(
                SourceAccountRow.platform == platform, SourceAccountRow.label == label
            )
        ).first()
        if taken is not None:
            raise SourceAccountError("label_taken")

    def _free_proxy(
        self, session: Session, proxy_id: str | None, owner: uuid.UUID | None
    ) -> uuid.UUID | None:
        if proxy_id is None:
            return None
        key = _uuid(proxy_id)
        if session.get(SourceProxyRow, key) is None:
            raise SourceAccountError("proxy_not_found")
        holder = self._holder(session, key)
        if holder is not None and holder.id != owner:
            raise SourceAccountError("proxy_in_use")
        return key

    def _set_cookies(self, row: SourceAccountRow, cookies: CookieSet) -> None:
        row.cookies_ciphertext = self._vault.seal(cookies.to_json())
        row.cookie_names = cookies.names()
        row.cookies_earliest_expiry = cookies.earliest_expiry()

    def _open(
        self, session: Session, row: SourceAccountRow, engine: str = "patchright"
    ) -> SessionAccess:
        cookies = CookieSet.from_json(
            row.platform,  # type: ignore[arg-type]
            self._vault.open(row.cookies_ciphertext),
        )
        proxy = None
        if row.proxy_id is not None:
            proxy_row = session.get(SourceProxyRow, row.proxy_id)
            proxy = self._vault.open(proxy_row.proxy_ciphertext) if proxy_row else None
        # Spec 3.4 (amended 2026-10-14): only Camoufox gets a fingerprint, made on first use.
        fingerprint = None
        if engine == "camoufox":
            if row.fingerprint_ciphertext is None:
                fingerprint = fingerprints.new_fingerprint()
                row.fingerprint_ciphertext = self._vault.seal(json.dumps(fingerprint))
            else:
                fingerprint = json.loads(self._vault.open(row.fingerprint_ciphertext))
        return SessionAccess(
            cookies,
            proxy,
            locale=row.locale or "id-ID",
            timezone=row.timezone or "Asia/Jakarta",
            fingerprint=fingerprint,
            engine=engine,
        )

    def _account_view(self, session: Session, row: SourceAccountRow) -> AccountView:
        proxy = session.get(SourceProxyRow, row.proxy_id) if row.proxy_id else None
        usage = session.get(SourceAccountUsageRow, (row.id, self._clock().date()))
        return AccountView(
            id=str(row.id),
            platform=row.platform,  # type: ignore[arg-type]
            label=row.label,
            status=row.status,
            cooldown_until=row.cooldown_until,
            last_used_at=row.last_used_at,
            last_outcome=row.last_outcome,
            success_count=row.success_count,
            failure_count=row.failure_count,
            cookie_names=tuple(row.cookie_names),
            cookies_earliest_expiry=row.cookies_earliest_expiry,
            proxy_id=str(row.proxy_id) if row.proxy_id else None,
            proxy_display=proxy.display if proxy else None,
            created_at=row.created_at,
            updated_at=row.updated_at,
            locale=row.locale or "id-ID",
            timezone=row.timezone or "Asia/Jakarta",
            fingerprint_set=row.fingerprint_ciphertext is not None,
            uses_today=usage.uses if usage is not None else 0,
        )

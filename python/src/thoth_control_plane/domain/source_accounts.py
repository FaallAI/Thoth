"""Public shapes of the source-account API: safe fields only, never a cookie or a proxy URL."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from thoth_control_plane.acquisition.accounts.cookies import MAX_IMPORT_BYTES
from thoth_control_plane.acquisition.accounts.policy import MAX_SPACING_SECONDS
from thoth_control_plane.acquisition.accounts.proxies import MAX_PROXY_BYTES
from thoth_control_plane.domain.models import StrictModel

SourcePlatform = Literal["tiktok", "threads", "instagram", "x", "youtube"]
AccessMode = Literal["anonymous", "fallback", "always"]
AccountStatus = Literal["healthy", "cooldown", "expired", "disabled"]
AccountOutcome = Literal[
    "success", "blocked", "challenge", "rate_limited", "login_wall", "undecryptable"
]
AccountLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
CookieText = Annotated[str, Field(min_length=1, max_length=MAX_IMPORT_BYTES)]
ProxyText = Annotated[str, Field(min_length=1, max_length=MAX_PROXY_BYTES)]
OpaqueUuid = Annotated[str, Field(pattern=r"^[0-9a-f-]{36}$")]


class SourceAccount(StrictModel):
    id: str
    platform: SourcePlatform
    label: str
    status: AccountStatus
    cooldown_until: datetime | None
    last_used_at: datetime | None
    last_outcome: AccountOutcome | None
    success_count: int
    failure_count: int
    cookie_names: list[str]
    cookies_earliest_expiry: datetime | None
    proxy_id: str | None
    proxy_display: str | None
    created_at: datetime
    updated_at: datetime


class StatusCounts(StrictModel):
    healthy: int = 0
    cooldown: int = 0
    expired: int = 0
    disabled: int = 0


class PlatformAccounts(StrictModel):
    platform: SourcePlatform
    mode: AccessMode
    min_spacing_seconds: int
    counts: StatusCounts
    accounts: list[SourceAccount]


class SourceAccountsOverview(StrictModel):
    available: bool
    platforms: list[PlatformAccounts]


class AccessPolicyUpdate(StrictModel):
    mode: AccessMode
    min_spacing_seconds: Annotated[int, Field(ge=0, le=MAX_SPACING_SECONDS)]


class CookieValidationRequest(StrictModel):
    platform: SourcePlatform
    cookies: CookieText


class CookieValidation(StrictModel):
    valid: bool
    count: int
    names: list[str]
    earliest_expiry: datetime | None
    error: Literal["invalid_cookie_file", "all_cookies_expired", "missing_required_cookie"] | None
    missing: list[str]


class SourceAccountCreate(StrictModel):
    platform: SourcePlatform
    label: AccountLabel
    cookies: CookieText
    proxy_id: OpaqueUuid | None = None


class CookieReimport(StrictModel):
    cookies: CookieText


class SourceAccountUpdate(StrictModel):
    """Omit a field to keep it; `proxy_id: null` removes the proxy."""

    label: AccountLabel | None = None
    proxy_id: OpaqueUuid | None = None
    disabled: bool | None = None


class SourceProxy(StrictModel):
    id: str
    scheme: Literal["http", "https", "socks5"]
    display: str
    account_platform: SourcePlatform | None
    account_label: str | None


class ProxyImportRequest(StrictModel):
    text: ProxyText


class ProxyImportSummary(StrictModel):
    added: int
    duplicates: int
    invalid_lines: list[int]


class SessionCheckResult(StrictModel):
    result: Literal["valid", "expired", "inconclusive"]
    account: SourceAccount

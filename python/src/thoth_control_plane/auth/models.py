"""Who is calling, what a provider vouched for, and the account API models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from thoth_control_plane.domain.models import StrictModel

Scope = Literal["read", "write", "admin"]
SCOPE_SETS: dict[str, frozenset[str]] = {
    "read": frozenset({"read"}),
    "write": frozenset({"read", "write"}),
    "admin": frozenset({"read", "write", "admin"}),
}
ALL_SCOPES = SCOPE_SETS["admin"]
BOOTSTRAP_WORKSPACE_ID = "ws_bootstrap"
SignInErrorCode = Literal[
    "unverified_email", "not_allowed", "provider_error", "not_configured", "too_many_codes"
]


@dataclass(frozen=True)
class Principal:
    """An authenticated caller; `user_id` is None for the service key and workspace tokens."""

    user_id: str | None
    workspace_id: str
    scopes: frozenset[str]
    via: Literal["session", "token", "service"]
    email: str | None = None


@dataclass(frozen=True)
class VerifiedIdentity:
    provider: Literal["google", "github"]
    subject: str
    email: str  # lower-case and verified by the provider
    display_name: str


class SignInRefused(Exception):
    def __init__(self, code: SignInErrorCode) -> None:
        super().__init__(code)
        self.code = code


class MeView(StrictModel):
    user_id: str | None
    email: str | None
    display_name: str | None
    workspace_id: str
    scopes: list[Scope]


class TokenView(StrictModel):
    token_id: str
    owner_kind: Literal["user", "workspace"]
    name: str
    prefix: str
    scope: Scope
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None


class CreateToken(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    scope: Scope = "write"
    days: Annotated[int, Field(ge=1, le=365)] = 90


class CreatedToken(StrictModel):
    token: TokenView
    secret: str  # shown once; never stored

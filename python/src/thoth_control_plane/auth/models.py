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
#: The single data actor every record had before workspaces; it stays the bootstrap's actor.
LEGACY_ACTOR_ID = "owner"


def data_actor_id(workspace_id: str) -> str:
    """The data actor that owns a workspace's records (spec 1.1)."""
    return LEGACY_ACTOR_ID if workspace_id == BOOTSTRAP_WORKSPACE_ID else workspace_id


def actor_workspace_id(actor_id: str) -> str:
    """The workspace a data actor belongs to: the inverse of `data_actor_id`."""
    return BOOTSTRAP_WORKSPACE_ID if actor_id == LEGACY_ACTOR_ID else actor_id


SignInErrorCode = Literal[
    "unverified_email",
    "not_allowed",
    "provider_error",
    "not_configured",
    "too_many_codes",
    "too_soon",
]


@dataclass(frozen=True)
class Principal:
    """An authenticated caller; `user_id` is None for the service key and workspace tokens."""

    user_id: str | None
    workspace_id: str
    scopes: frozenset[str]
    via: Literal["session", "token", "service"]
    email: str | None = None
    token_id: str | None = None  # the developer token used, when via == "token"
    # the caller's role in workspace_id; None for the service key and workspace tokens
    role: str | None = None


def is_platform_admin(principal: Principal) -> bool:
    """The service key, or an owner/admin of the bootstrap workspace (spec 1.3)."""
    if principal.via == "service":
        return True
    return (
        principal.user_id is not None
        and principal.workspace_id == BOOTSTRAP_WORKSPACE_ID
        and principal.role in ("owner", "admin")
    )


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


class WorkspaceView(StrictModel):
    workspace_id: str
    name: str
    role: str | None


#: The dashboard's languages (restyle spec D1); None until the user chooses one.
Locale = Literal["en", "id"]


class MeView(StrictModel):
    user_id: str | None
    email: str | None
    display_name: str | None
    workspace_id: str
    scopes: list[Scope]
    workspace: WorkspaceView
    platform_admin: bool
    locale: Locale | None = None


class MeUpdate(StrictModel):
    locale: Locale


def accountless_me(principal: Principal) -> MeView:
    """`/me` on a server without the account store: the principal alone, nothing looked up."""
    return MeView(
        user_id=principal.user_id,
        email=principal.email,
        display_name=None,
        workspace_id=principal.workspace_id,
        scopes=sorted(principal.scopes),  # type: ignore[arg-type]
        workspace=WorkspaceView(
            workspace_id=principal.workspace_id,
            name=principal.workspace_id,
            role=principal.role,
        ),
        platform_admin=is_platform_admin(principal),
    )


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

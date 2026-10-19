"""Shared authenticated API dependencies.

A caller is a session cookie, a developer token, or the legacy service key (spec 3.5-3.6). Every
principal still acts on the shared `owner` data until sub-project 2 scopes data by workspace.
"""

from __future__ import annotations

import asyncio
import time
from hmac import compare_digest
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from thoth_control_plane.auth.models import (
    ALL_SCOPES,
    BOOTSTRAP_WORKSPACE_ID,
    Principal,
    data_actor_id,
    is_platform_admin,
)
from thoth_control_plane.auth.service import AuthUnavailable
from thoth_control_plane.domain import Actor

SESSION_COOKIE = "thoth_session"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
#: The legacy service key's use is recorded at most this often per API process.
SERVICE_KEY_NOTE_SECONDS = 60.0


def _forbidden(detail: str = "Not authorized") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


async def _note_service_key(request: Request) -> None:
    state = request.app.state
    now = time.monotonic()
    last = getattr(state, "service_key_noted_at", None)
    if last is not None and now - last < SERVICE_KEY_NOTE_SECONDS:
        return
    state.service_key_noted_at = now
    sign_in = getattr(state, "sign_in", None)
    if sign_in is not None:
        await sign_in.note_service_key()


async def resolve_principal(request: Request, authorization: str | None) -> Principal | None:
    """The caller, or None. A present Authorization header never falls back to the cookie."""
    settings = request.app.state.settings
    sign_in = getattr(request.app.state, "sign_in", None)
    try:
        if authorization is not None:
            scheme, _, credential = authorization.partition(" ")
            if scheme.lower() != "bearer" or not credential:
                return None
            expected = settings.THOTH_CONTROL_PLANE_API_KEY.get_secret_value()
            if compare_digest(credential.encode("utf-8"), expected.encode("utf-8")):
                await _note_service_key(request)
                return Principal(None, BOOTSTRAP_WORKSPACE_ID, ALL_SCOPES, "service")
            return None if sign_in is None else await sign_in.authenticate_token(credential)
        cookie = request.cookies.get(SESSION_COOKIE)
        if cookie and sign_in is not None:
            return await sign_in.authenticate_session(cookie)
    except AuthUnavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "auth_unavailable") from None
    return None


async def current_principal(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> Principal:
    principal = await resolve_principal(request, authorization)
    if principal is None:
        raise _forbidden()
    return principal


def require_write(request: Request, principal: Principal) -> None:
    """Unsafe methods need the write scope; a cookie also needs the site's own Origin."""
    if request.method in SAFE_METHODS:
        return
    if "write" not in principal.scopes:
        raise _forbidden("insufficient_scope")
    site = request.app.state.settings.THOTH_SITE_ORIGIN
    if principal.via == "session" and request.headers.get("origin") != site:
        raise _forbidden("cross_site_request")


async def current_actor(
    request: Request, principal: Annotated[Principal, Depends(current_principal)]
) -> Actor:
    """The caller's workspace as the data actor (spec 1.1), and the project guard (spec 1.2).

    Every route with `{project_id}` in its path depends on this, so the project must be in the
    caller's workspace; a foreign project answers exactly like a missing one. The email is kept
    for audit.
    """
    require_write(request, principal)
    project_id = request.path_params.get("project_id")
    if project_id is not None:
        await _require_project(request, project_id, principal.workspace_id)
    display = principal.email[:200] if principal.email else None
    return Actor(
        actor_id=data_actor_id(principal.workspace_id), actor_type="user", display_name=display
    )


async def _require_project(request: Request, project_id: str, workspace_id: str) -> None:
    from thoth_control_plane.infrastructure.project_store import ProjectStoreUnavailable

    store = request.app.state.project_store
    if store is None:
        raise ProjectStoreUnavailable("project_store_unavailable")
    if await asyncio.to_thread(store.get, project_id, workspace_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project_not_found")


async def platform_actor(
    request: Request, principal: Annotated[Principal, Depends(current_principal)]
) -> Actor:
    """Platform resources (source accounts, proxies): platform admins with the admin scope."""
    if not is_platform_admin(principal) or "admin" not in principal.scopes:
        raise _forbidden()
    return await current_actor(request, principal)


def internal_renderer(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> None:
    """Authenticate the private renderer, which shares no credential with a creator.

    An installation without a configured renderer has no internal credential at
    all, so every private route stays closed instead of falling back to another
    secret.
    """
    configured = request.app.state.settings.THOTH_RENDERER_INTERNAL_CREDENTIAL
    scheme, _, credential = authorization.partition(" ") if authorization else ("", "", "")
    expected = configured.get_secret_value() if configured is not None else ""
    if (
        not expected
        or scheme.lower() != "bearer"
        or not credential
        or not compare_digest(credential, expected)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

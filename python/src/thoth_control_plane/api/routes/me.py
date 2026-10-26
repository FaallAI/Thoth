"""The caller's account and developer tokens (spec 3.3)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from thoth_control_plane.api.dependencies import current_principal, require_write
from thoth_control_plane.auth.models import (
    CreatedToken,
    CreateToken,
    MeUpdate,
    MeView,
    Principal,
    TokenView,
    accountless_me,
)
from thoth_control_plane.auth.service import (
    AuthUnavailable,
    ScopeTooBroad,
    SignInService,
    TokenLimitReached,
    UserRequired,
)

router = APIRouter(tags=["account"])
Caller = Annotated[Principal, Depends(current_principal)]


def _service(request: Request) -> SignInService:
    service = request.app.state.sign_in
    if service is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "accounts_unavailable")
    return service


def _account_caller(request: Request, principal: Principal) -> SignInService:
    """Token management needs a user: a session, or a personal token with the admin scope."""
    require_write(request, principal)
    if principal.user_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "user_required")
    if principal.via == "token" and "admin" not in principal.scopes:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_scope")
    return _service(request)


async def _issue(call) -> CreatedToken:
    try:
        return await call
    except UserRequired:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "user_required") from None
    except ScopeTooBroad:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_scope") from None
    except TokenLimitReached:
        raise HTTPException(status.HTTP_409_CONFLICT, "token_limit") from None
    except AuthUnavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "auth_unavailable") from None


@router.get("/me", response_model=MeView)
async def me(request: Request, principal: Caller) -> MeView:
    service = request.app.state.sign_in
    if service is None:
        return accountless_me(principal)
    return await service.describe(principal)


@router.patch("/me", response_model=MeView)
async def update_me(body: MeUpdate, request: Request, principal: Caller) -> MeView:
    """Save the caller's own preferences: today, the dashboard language."""
    require_write(request, principal)
    try:
        return await _service(request).set_locale(principal, body.locale)
    except UserRequired:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "user_required") from None
    except AuthUnavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "auth_unavailable") from None


@router.get("/me/tokens", response_model=list[TokenView])
async def list_tokens(request: Request, principal: Caller) -> list[TokenView]:
    return await _account_caller(request, principal).list_tokens(principal)


@router.post("/me/tokens", response_model=CreatedToken, status_code=status.HTTP_201_CREATED)
async def create_token(body: CreateToken, request: Request, principal: Caller) -> CreatedToken:
    return await _issue(_account_caller(request, principal).create_token(principal, body))


@router.delete("/me/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(token_id: str, request: Request, principal: Caller) -> Response:
    if not await _account_caller(request, principal).revoke_token(principal, token_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "token_not_found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/workspace/tokens", response_model=CreatedToken, status_code=status.HTTP_201_CREATED)
async def create_workspace_token(
    body: CreateToken, request: Request, principal: Caller
) -> CreatedToken:
    if not request.app.state.settings.THOTH_AUTH_WORKSPACE_TOKENS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "workspace_tokens_disabled")
    return await _issue(_account_caller(request, principal).create_workspace_token(principal, body))

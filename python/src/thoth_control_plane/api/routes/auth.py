"""Sign-in with Google or GitHub, then an emailed code (spec section 2). Not in OpenAPI.

Every refusal returns to /login with a fixed code; no provider or server text reaches the page.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Header, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import Field

from thoth_control_plane.api.dependencies import SESSION_COOKIE, resolve_principal
from thoth_control_plane.auth.models import MeView, SignInRefused
from thoth_control_plane.auth.providers import PROVIDER_FAILURES
from thoth_control_plane.auth.service import (
    DEVICE_TTL,
    SESSION_MAX,
    AuthUnavailable,
    CodeLimited,
    CodeNotSent,
    CodeRejected,
    SignedIn,
)
from thoth_control_plane.domain.models import StrictModel

router = APIRouter(prefix="/auth", include_in_schema=False)

DEVICE_COOKIE = "thoth_device"
CHALLENGE_COOKIE = "thoth_challenge"
NEXT_KEY = "thoth_next"
DEFAULT_NEXT = "/workflows"


class VerifyBody(StrictModel):
    code: Annotated[str, Field(min_length=6, max_length=12)]
    trust_device: bool = True
    next: Annotated[str, Field(max_length=2048)] | None = None


class LogoutBody(StrictModel):
    forget_device: bool = False


def safe_next(value: str | None) -> str:
    """Only a same-site absolute path; anything else becomes the Workflows page.

    A browser's URL parser drops tab, CR and LF, so "/\t/evil.test" would become "//evil.test":
    any control character or space refuses the value outright.
    """
    if (
        not value
        or not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or any(ord(character) <= 0x20 or ord(character) == 0x7F for character in value)
    ):
        return DEFAULT_NEXT
    return value


def _to_login(code: str) -> RedirectResponse:
    return RedirectResponse(f"/login?error={code}", status_code=status.HTTP_303_SEE_OTHER)


def _same_site(request: Request) -> bool:
    return request.headers.get("origin") == request.app.state.settings.THOTH_SITE_ORIGIN


def _detail(code: str, status_code: int) -> JSONResponse:
    return JSONResponse({"detail": code}, status_code=status_code)


def _set_cookie(
    response: Response, request: Request, name: str, value: str, *, max_age: int, path: str
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path=path,
        httponly=True,
        samesite="lax",
        secure=request.app.state.settings.cookie_secure,
    )


def _signed_in(response: Response, request: Request, done: SignedIn) -> None:
    _set_cookie(
        response,
        request,
        SESSION_COOKIE,
        done.session_token,
        max_age=int(SESSION_MAX.total_seconds()),
        path="/",
    )
    if done.device_token is not None:
        _set_cookie(
            response,
            request,
            DEVICE_COOKIE,
            done.device_token,
            max_age=int(DEVICE_TTL.total_seconds()),
            path="/auth",
        )


@router.get("/providers")
async def providers(request: Request) -> dict[str, list[str]]:
    return {"providers": sorted(request.app.state.auth_providers)}


@router.get("/login/{provider}")
async def login(provider: str, request: Request, next: str | None = None) -> Response:
    found = request.app.state.auth_providers.get(provider)
    if found is None or request.app.state.sign_in is None:
        return _to_login("not_configured")
    request.session[NEXT_KEY] = safe_next(next)
    origin = request.app.state.settings.THOTH_SITE_ORIGIN.rstrip("/")
    try:
        return await found.redirect(request, f"{origin}/auth/callback/{provider}")
    except PROVIDER_FAILURES:  # e.g. Google's metadata endpoint is unreachable
        return _to_login("provider_error")


@router.get("/callback/{provider}")
async def callback(provider: str, request: Request) -> Response:
    found = request.app.state.auth_providers.get(provider)
    sign_in = request.app.state.sign_in
    target = safe_next(request.session.pop(NEXT_KEY, None) if "session" in request.scope else None)
    if found is None or sign_in is None:
        return _to_login("not_configured")
    try:
        identity = await found.identity(request)
        step = await sign_in.begin(identity, request.cookies.get(DEVICE_COOKIE))
    except SignInRefused as refused:
        return _to_login(refused.code)
    except CodeNotSent:
        return _to_login("code_not_sent")
    except AuthUnavailable:
        return _to_login("unavailable")
    if isinstance(step, SignedIn):
        response = RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
        _signed_in(response, request, step)
        return response
    response = RedirectResponse(
        f"/login/verify?next={quote(target, safe='/')}", status_code=status.HTTP_303_SEE_OTHER
    )
    _set_cookie(
        response, request, CHALLENGE_COOKIE, step.challenge_token, max_age=600, path="/auth"
    )
    return response


@router.post("/verify")
async def verify(body: VerifyBody, request: Request) -> Response:
    if not _same_site(request):
        return _detail("cross_site_request", 403)
    sign_in = request.app.state.sign_in
    challenge = request.cookies.get(CHALLENGE_COOKIE)
    if sign_in is None:
        return _detail("not_configured", 503)
    if not challenge:
        return _detail("expired", 400)
    try:
        done = await sign_in.verify(
            challenge,
            body.code,
            trust_device=body.trust_device,
            previous_session=request.cookies.get(SESSION_COOKIE),
        )
    except CodeRejected as rejected:
        return _detail(rejected.code, 400)
    except SignInRefused as refused:
        return _detail(refused.code, 403)
    except AuthUnavailable:
        return _detail("unavailable", 503)
    response = JSONResponse({"next": safe_next(body.next)})
    _signed_in(response, request, done)
    response.delete_cookie(CHALLENGE_COOKIE, path="/auth")
    return response


@router.post("/resend")
async def resend(request: Request) -> Response:
    if not _same_site(request):
        return _detail("cross_site_request", 403)
    sign_in = request.app.state.sign_in
    challenge = request.cookies.get(CHALLENGE_COOKIE)
    if sign_in is None or not challenge:
        return _detail("expired", 400)
    try:
        sent = await sign_in.resend(challenge)
    except CodeRejected as rejected:
        return _detail(rejected.code, 400)
    except CodeLimited as limited:
        return _detail(limited.code, 429)
    except CodeNotSent:
        return _detail("code_not_sent", 503)
    except SignInRefused as refused:
        return _detail(refused.code, 403)
    except AuthUnavailable:
        return _detail("unavailable", 503)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _set_cookie(
        response, request, CHALLENGE_COOKIE, sent.challenge_token, max_age=600, path="/auth"
    )
    return response


@router.post("/logout")
async def logout(body: LogoutBody, request: Request) -> Response:
    if not _same_site(request):
        return _detail("cross_site_request", 403)
    sign_in = request.app.state.sign_in
    if sign_in is not None:
        try:
            await sign_in.logout(
                request.cookies.get(SESSION_COOKIE),
                request.cookies.get(DEVICE_COOKIE),
                forget_device=body.forget_device,
            )
        except AuthUnavailable:
            return _detail("unavailable", 503)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path="/")
    if body.forget_device:
        response.delete_cookie(DEVICE_COOKIE, path="/auth")
    return response


@router.get("/me", response_model=MeView)
async def me(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> Response | MeView:
    principal = await resolve_principal(request, authorization)
    if principal is None:
        return _detail("signed_out", 401)
    sign_in = request.app.state.sign_in
    if sign_in is None:
        return MeView(
            user_id=None,
            email=None,
            display_name=None,
            workspace_id=principal.workspace_id,
            scopes=sorted(principal.scopes),
        )  # type: ignore[arg-type]
    return await sign_in.describe(principal)

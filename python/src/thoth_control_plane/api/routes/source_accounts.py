"""Authenticated routes for source accounts, their access policy, and the proxy pool.

The store is synchronous, so every call runs in a worker thread. Responses carry safe fields
only; a request body (cookies, proxy credentials) is never logged or echoed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from thoth_control_plane.acquisition.accounts.cookies import (
    PLATFORMS,
    CookieImportError,
    parse_cookies,
    summarize,
)
from thoth_control_plane.acquisition.accounts.proxies import ProxyImportError, parse_proxy_list
from thoth_control_plane.acquisition.accounts.session_check import check_session
from thoth_control_plane.api.dependencies import current_actor
from thoth_control_plane.domain import Actor
from thoth_control_plane.domain.source_accounts import (
    AccessPolicyUpdate,
    CookieReimport,
    CookieValidation,
    CookieValidationRequest,
    PlatformAccounts,
    ProxyImportRequest,
    ProxyImportSummary,
    SessionCheckResult,
    SourceAccount,
    SourceAccountCreate,
    SourceAccountsOverview,
    SourceAccountUpdate,
    SourcePlatform,
    SourceProxy,
    StatusCounts,
)
from thoth_control_plane.infrastructure.source_account_store import (
    UNSET,
    AccountView,
    SourceAccountError,
    SourceAccountStore,
)

router = APIRouter()
logger = logging.getLogger(__name__)
T = TypeVar("T")
_ERROR_STATUS = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "proxy_not_found": status.HTTP_404_NOT_FOUND,
    "label_taken": status.HTTP_409_CONFLICT,
    "proxy_in_use": status.HTTP_409_CONFLICT,
    "undecryptable": status.HTTP_409_CONFLICT,
    "platform_mismatch": status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def get_source_account_store(request: Request) -> SourceAccountStore | None:
    return request.app.state.source_account_store


def get_session_checker(request: Request) -> Callable[..., Any]:
    return getattr(request.app.state, "session_checker", check_session)


Store = Annotated[SourceAccountStore | None, Depends(get_source_account_store)]
Authorized = Annotated[Actor, Depends(current_actor)]


def _error(status_code: int, code: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, **extra})


def _require(store: SourceAccountStore | None) -> SourceAccountStore:
    if store is None:
        raise _error(status.HTTP_503_SERVICE_UNAVAILABLE, "source_accounts_unavailable")
    return store


async def _call(function: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    try:
        return await asyncio.to_thread(function, *args, **kwargs)
    except SourceAccountError as error:
        raise _error(_ERROR_STATUS.get(error.code, status.HTTP_409_CONFLICT), error.code) from None


def _account(view: AccountView) -> SourceAccount:
    return SourceAccount(
        id=view.id,
        platform=view.platform,
        label=view.label,
        status=view.status,  # type: ignore[arg-type]
        cooldown_until=view.cooldown_until,
        last_used_at=view.last_used_at,
        last_outcome=view.last_outcome,  # type: ignore[arg-type]
        success_count=view.success_count,
        failure_count=view.failure_count,
        cookie_names=list(view.cookie_names),
        cookies_earliest_expiry=view.cookies_earliest_expiry,
        proxy_id=view.proxy_id,
        proxy_display=view.proxy_display,
        created_at=view.created_at,
        updated_at=view.updated_at,
    )


def _cookies(platform: SourcePlatform, text: str):
    try:
        return parse_cookies(platform, text, now=datetime.now(UTC))
    except CookieImportError as error:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, error.code, missing=list(error.missing)
        ) from None


@router.get("/source-accounts", response_model=SourceAccountsOverview)
async def list_source_accounts(_: Authorized, store: Store) -> SourceAccountsOverview:
    if store is None:
        return SourceAccountsOverview(
            available=False,
            platforms=[
                PlatformAccounts(
                    platform=platform,
                    mode="fallback",
                    min_spacing_seconds=60,
                    counts=StatusCounts(),
                    accounts=[],
                )
                for platform in PLATFORMS
            ],
        )
    policies = await _call(store.policies)
    accounts = [_account(view) for view in await _call(store.accounts)]
    platforms = []
    for policy in policies:
        mine = [account for account in accounts if account.platform == policy.platform]
        counts = StatusCounts()
        for account in mine:
            setattr(counts, account.status, getattr(counts, account.status) + 1)
        platforms.append(
            PlatformAccounts(
                platform=policy.platform,
                mode=policy.mode,
                min_spacing_seconds=policy.min_spacing_seconds,
                counts=counts,
                accounts=mine,
            )
        )
    return SourceAccountsOverview(available=True, platforms=platforms)


@router.put("/source-accounts/policies/{platform}", response_model=AccessPolicyUpdate)
async def update_access_policy(
    platform: SourcePlatform, payload: AccessPolicyUpdate, _: Authorized, store: Store
) -> AccessPolicyUpdate:
    view = await _call(
        _require(store).set_policy, platform, payload.mode, payload.min_spacing_seconds
    )
    return AccessPolicyUpdate(mode=view.mode, min_spacing_seconds=view.min_spacing_seconds)


@router.post("/source-accounts/validate", response_model=CookieValidation)
async def validate_cookies(payload: CookieValidationRequest, _: Authorized) -> CookieValidation:
    """A dry run of an import: the safe summary; nothing is stored."""
    summary = summarize(payload.platform, payload.cookies, now=datetime.now(UTC))
    return CookieValidation(
        valid=summary.error is None,
        count=summary.count,
        names=list(summary.names),
        earliest_expiry=summary.earliest_expiry,
        error=summary.error,
        missing=list(summary.missing),
    )


@router.post("/source-accounts", response_model=SourceAccount, status_code=status.HTTP_201_CREATED)
async def create_source_account(
    payload: SourceAccountCreate, _: Authorized, store: Store
) -> SourceAccount:
    store = _require(store)
    cookies = _cookies(payload.platform, payload.cookies)
    view = await _call(
        store.add_account, payload.platform, payload.label, cookies, payload.proxy_id
    )
    return _account(view)


@router.put("/source-accounts/{account_id}/cookies", response_model=SourceAccount)
async def reimport_cookies(
    account_id: str, payload: CookieReimport, _: Authorized, store: Store
) -> SourceAccount:
    store = _require(store)
    current = await _call(store.account, account_id)
    cookies = _cookies(current.platform, payload.cookies)
    return _account(await _call(store.replace_cookies, account_id, cookies))


@router.patch("/source-accounts/{account_id}", response_model=SourceAccount)
async def update_source_account(
    account_id: str, payload: SourceAccountUpdate, _: Authorized, store: Store
) -> SourceAccount:
    store = _require(store)
    given = payload.model_fields_set
    view = await _call(
        store.update_account,
        account_id,
        label=payload.label if "label" in given and payload.label is not None else UNSET,
        proxy_id=payload.proxy_id if "proxy_id" in given else UNSET,
        disabled=payload.disabled,
    )
    return _account(view)


@router.delete("/source-accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source_account(account_id: str, _: Authorized, store: Store) -> Response:
    await _call(_require(store).delete_account, account_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/source-proxies", response_model=list[SourceProxy])
async def list_source_proxies(_: Authorized, store: Store) -> list[SourceProxy]:
    views = await _call(_require(store).proxies)
    return [
        SourceProxy(
            id=view.id,
            scheme=view.scheme,  # type: ignore[arg-type]
            display=view.display,
            account_platform=view.account_platform,  # type: ignore[arg-type]
            account_label=view.account_label,
        )
        for view in views
    ]


@router.post("/source-proxies/import", response_model=ProxyImportSummary)
async def import_source_proxies(
    payload: ProxyImportRequest, _: Authorized, store: Store
) -> ProxyImportSummary:
    store = _require(store)
    try:
        parsed = parse_proxy_list(payload.text)
    except ProxyImportError as error:
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, error.code) from None
    result = await _call(store.import_proxies, parsed)
    return ProxyImportSummary(
        added=result.added, duplicates=result.duplicates, invalid_lines=list(result.invalid_lines)
    )


@router.delete("/source-proxies/{proxy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source_proxy(proxy_id: str, _: Authorized, store: Store) -> Response:
    await _call(_require(store).delete_proxy, proxy_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/source-accounts/{account_id}/test", response_model=SessionCheckResult)
async def test_source_account(
    account_id: str,
    _: Authorized,
    store: Store,
    checker: Annotated[Callable[..., Any], Depends(get_session_checker)],
) -> SessionCheckResult:
    """One live request with the account's session; only an operator's press sends it."""
    store = _require(store)
    view = await _call(store.account, account_id)
    access = await _call(store.access, account_id)
    verdict = await checker(view.platform, access)
    if verdict != "inconclusive":
        view = await _call(store.record_check, account_id, verdict == "valid")
    logger.info("source account session check platform=%s result=%s", view.platform, verdict)
    return SessionCheckResult(result=verdict, account=_account(view))

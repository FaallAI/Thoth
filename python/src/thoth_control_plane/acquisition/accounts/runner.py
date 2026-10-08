"""Acquisition with source accounts: the platform's mode decides when a session is used.

- `anonymous`: never.
- `always`: lease an account; run anonymously and say so when none is available.
- `fallback`: run anonymously; when that is blocked or meets a login wall, lease one account
  and run once more with it.

The leased account is always released, with the outcome its acquisition earned. An account
store that fails never fails acquisition: it runs anonymously and a `warn` says why. Logs and
results carry enums only, never an account, a label, or a proxy.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.accounts.policy import Outcome
from thoth_control_plane.acquisition.models import AccountUse, AcquisitionReason, AcquisitionResult
from thoth_control_plane.acquisition.platforms import platform_of
from thoth_control_plane.infrastructure.source_account_store import (
    AccountLease,
    SourceAccountStore,
)

logger = logging.getLogger(__name__)

Acquire = Callable[[str, str, Path, SessionAccess | None], Awaitable[AcquisitionResult]]
Runner = Callable[[str, str, Path], Awaitable[AcquisitionResult]]
BLOCKED_CODES = frozenset({"request_blocked", "headless_blocked"})


def account_outcome(result: AcquisitionResult) -> Outcome | None:
    """What `result` says about the session; None leaves the account's health alone."""
    if result.failure is None:
        return "success"
    if AcquisitionReason.LOGIN_WALL in {attempt.reason for attempt in result.failure.attempts}:
        return "login_wall"
    if result.failure.code == "cdn_rate_limited":
        return "rate_limited"
    if result.failure.code in BLOCKED_CODES:
        return "blocked"
    return None


async def _lease(store: SourceAccountStore, platform: str) -> AccountLease | None:
    try:
        return await asyncio.to_thread(store.lease, platform)  # type: ignore[arg-type]
    except Exception:
        logger.warning("source account lease unavailable; acquisition runs anonymously")
        return None


async def _release(store: SourceAccountStore, lease: AccountLease, outcome: Outcome | None) -> None:
    try:
        await asyncio.to_thread(store.report, lease.account_id, outcome)
    except Exception:
        logger.warning("source account release failed; its lease expires on its own")


def account_runner(store: SourceAccountStore | None, acquire: Acquire) -> Runner:
    async def run(workflow_id: str, source_url: str, artifact_root: Path) -> AcquisitionResult:
        async def attempt(access: SessionAccess | None) -> AcquisitionResult:
            return await acquire(workflow_id, source_url, artifact_root, access)

        platform = platform_of(source_url)
        if store is None or platform is None:
            return await attempt(None)
        try:
            mode = (await asyncio.to_thread(store.policy, platform)).mode  # type: ignore[arg-type]
        except Exception:
            logger.warning("source account policy unavailable; acquisition runs anonymously")
            return await attempt(None)
        if mode == "anonymous":
            return await attempt(None)
        anonymous: AcquisitionResult | None = None
        if mode == "fallback":
            anonymous = await attempt(None)
            if account_outcome(anonymous) not in ("blocked", "login_wall"):
                return anonymous
        lease = await _lease(store, platform)
        if lease is None:
            result = anonymous if anonymous is not None else await attempt(None)
            logger.info("no source account available platform=%s mode=%s", platform, mode)
            return result.model_copy(
                update={"account": AccountUse(used=False, no_account_available=True)}
            )
        outcome: Outcome | None = None
        try:
            result = await attempt(lease.access)
            outcome = account_outcome(result)
        finally:
            await _release(store, lease, outcome)
        logger.info("source account used platform=%s outcome=%s", platform, outcome or "none")
        return result.model_copy(update={"account": AccountUse(used=True, outcome=outcome)})

    return run

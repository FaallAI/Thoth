"""A manual session check: one request to a page only a signed-in session can open.

Run only when the operator presses "Test session"; never by acquisition and never by the
suite. The verdict is `valid`, `expired`, or `inconclusive` (timeout, block, or an answer the
check cannot read). Nothing about the response leaves this module but the verdict.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.card_browser import is_login_path

Verdict = Literal["valid", "expired", "inconclusive"]
TIMEOUT_SECONDS = 20.0
CHECK_OPTIONS: dict[str, Any] = {
    "impersonate": "chrome",
    "stealthy_headers": True,
    "follow_redirects": "safe",
    "timeout": 15,
    "retries": 0,
}


@dataclass(frozen=True)
class SessionCheck:
    url: str
    # Where a signed-out request ends up, or is redirected to.
    signed_out_paths: tuple[str, ...] = ()
    signed_out_hosts: tuple[str, ...] = ()
    # For a JSON check: the keys whose value is present only for a signed-in session.
    signed_in_json: tuple[str, ...] = ()


CHECKS: dict[str, SessionCheck] = {
    "tiktok": SessionCheck(
        url="https://www.tiktok.com/passport/web/account/info/",
        signed_in_json=("data", "username"),
    ),
    "threads": SessionCheck(
        url="https://www.threads.com/settings/account",
        signed_out_paths=("/login",),
    ),
    "instagram": SessionCheck(
        url="https://www.instagram.com/accounts/edit/",
        signed_out_paths=("/accounts/login", "/login"),
    ),
    "x": SessionCheck(
        url="https://x.com/settings/account",
        signed_out_paths=("/i/flow/login", "/login", "/i/jf/onboarding"),
    ),
    "youtube": SessionCheck(
        url="https://www.youtube.com/account",
        signed_out_paths=("/signin", "/ServiceLogin"),
        signed_out_hosts=("accounts.google.com",),
    ),
}


def _signed_out(check: SessionCheck, url: object) -> bool:
    if not url:
        return False
    host = (urlsplit(str(url)).hostname or "").lower()
    return host in check.signed_out_hosts or is_login_path(url, check.signed_out_paths)


def judge(check: SessionCheck, response: Any) -> Verdict:
    """The verdict for one response; reads its status, URL, redirect, and body only."""
    status = getattr(response, "status", None)
    headers = getattr(response, "headers", None) or {}
    location = headers.get("location") or headers.get("Location")
    if _signed_out(check, getattr(response, "url", None)) or _signed_out(check, location):
        return "expired"
    if status != 200:
        return "inconclusive"
    if not check.signed_in_json:
        return "valid"
    body = getattr(response, "body", b"")
    try:
        node: Any = json.loads(body.decode("utf-8") if isinstance(body, bytes) else str(body))
    except (ValueError, UnicodeDecodeError):
        return "inconclusive"
    for key in check.signed_in_json:
        node = node.get(key) if isinstance(node, dict) else None
    return "valid" if node else "expired"


async def _scrapling_get(url: str, **kwargs: Any) -> Any:
    from scrapling.fetchers import AsyncFetcher

    return await AsyncFetcher.get(url, **kwargs)


async def check_session(
    platform: str,
    access: SessionAccess,
    get: Callable[..., Awaitable[Any]] | None = None,
) -> Verdict:
    check = CHECKS[platform]
    try:
        response = await asyncio.wait_for(
            (get or _scrapling_get)(check.url, **CHECK_OPTIONS, **access.request_kwargs()),
            TIMEOUT_SECONDS,
        )
    except Exception:
        return "inconclusive"
    return judge(check, response)

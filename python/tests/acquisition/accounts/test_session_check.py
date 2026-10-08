"""The manual session check over synthetic responses; no network."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from thoth_control_plane.acquisition.accounts import session_check
from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.accounts.cookies import parse_cookies
from thoth_control_plane.acquisition.accounts.session_check import CHECKS, check_session, judge

ACCESS = SessionAccess(
    parse_cookies(
        "instagram",
        "\t".join([".instagram.com", "TRUE", "/", "TRUE", "1893456000", "sessionid", "s"]) + "\n",
        now=datetime(2026, 10, 8, tzinfo=UTC),
    ),
    "http://u:p@1.2.3.4:8080",
)


def _response(url: str, status: int = 200, body: object = b"", location: str | None = None):
    headers = {"location": location} if location else {}
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    return SimpleNamespace(url=url, status=status, body=data, headers=headers)


@pytest.mark.parametrize(
    ("platform", "response", "verdict"),
    [
        ("instagram", _response("https://www.instagram.com/accounts/edit/"), "valid"),
        (
            "instagram",
            _response("https://www.instagram.com/accounts/login/?next=/accounts/edit/"),
            "expired",
        ),
        ("instagram", _response("https://www.instagram.com/accounts/edit/", 429), "inconclusive"),
        ("threads", _response("https://www.threads.com/settings/account"), "valid"),
        ("threads", _response("https://www.threads.com/login?next=x"), "expired"),
        ("x", _response("https://x.com/settings/account"), "valid"),
        ("x", _response("https://x.com/i/flow/login?redirect_after_login=x"), "expired"),
        (
            "tiktok",
            _response(
                "https://www.tiktok.com/passport/web/account/info/",
                body={"data": {"username": "u"}},
            ),
            "valid",
        ),
        (
            "tiktok",
            _response(
                "https://www.tiktok.com/passport/web/account/info/", body={"data": {"captcha": ""}}
            ),
            "expired",
        ),
        (
            "tiktok",
            _response("https://www.tiktok.com/passport/web/account/info/", body=b"<html>"),
            "inconclusive",
        ),
        ("youtube", _response("https://www.youtube.com/account"), "valid"),
        (
            "youtube",
            _response(
                "https://www.youtube.com/account",
                status=303,
                location="https://accounts.google.com/ServiceLogin?service=youtube",
            ),
            "expired",
        ),
    ],
)
def test_each_platform_reads_its_signed_in_page(platform: str, response: Any, verdict: str) -> None:
    assert judge(CHECKS[platform], response) == verdict


@pytest.mark.asyncio
async def test_the_check_sends_the_sessions_cookies_and_proxy() -> None:
    seen: dict[str, Any] = {}

    async def get(url: str, **kwargs: Any):
        seen.update(url=url, **kwargs)
        return _response("https://www.instagram.com/accounts/edit/")

    assert await check_session("instagram", ACCESS, get) == "valid"
    assert seen["url"] == "https://www.instagram.com/accounts/edit/"
    assert (seen["cookies"], seen["proxy"]) == ({"sessionid": "s"}, "http://u:p@1.2.3.4:8080")
    assert seen["impersonate"] == "chrome"


@pytest.mark.asyncio
async def test_a_failure_or_a_slow_answer_is_inconclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(url: str, **kwargs: Any):
        raise RuntimeError("proxy refused")

    assert await check_session("instagram", ACCESS, broken) == "inconclusive"
    monkeypatch.setattr(session_check, "TIMEOUT_SECONDS", 0.01)

    async def slow(url: str, **kwargs: Any):
        await asyncio.sleep(1)

    assert await check_session("instagram", ACCESS, slow) == "inconclusive"


def test_every_platform_has_a_check() -> None:
    assert set(CHECKS) == {"tiktok", "threads", "instagram", "x", "youtube"}

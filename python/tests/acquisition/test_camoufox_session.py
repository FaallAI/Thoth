"""Camoufox as a Scrapling-shaped session for signed-in discovery (spec 2026-10-13, 3.4)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from thoth_control_plane.acquisition.camoufox_session import CamoufoxSession

FIREFOX = {"navigator": {"userAgent": "Mozilla/5.0 (X11; Linux x86_64; rv:150.0) Firefox/150.0"}}


class _Page:
    def __init__(self) -> None:
        self.url = "about:blank"

    async def goto(self, url: str, timeout: int) -> SimpleNamespace:
        self.url = url
        return SimpleNamespace(status=200)

    async def content(self) -> str:
        return "<html>reels</html>"


class _Context:
    def __init__(self) -> None:
        self.cookies: list[dict[str, Any]] = []
        self.page = _Page()
        self.closed = False

    async def add_cookies(self, cookies: list[dict[str, Any]]) -> None:
        self.cookies += cookies

    async def new_page(self) -> _Page:
        return self.page


class _Camoufox:
    seen: ClassVar[dict[str, Any]] = {}
    context: ClassVar[_Context] = _Context()

    def __init__(self, **kwargs: Any) -> None:
        _Camoufox.seen = kwargs
        _Camoufox.context = _Context()

    async def __aenter__(self) -> _Context:
        return _Camoufox.context

    async def __aexit__(self, *exc: object) -> None:
        _Camoufox.context.closed = True


@pytest.mark.asyncio
async def test_a_page_runs_setup_and_action_in_the_accounts_persistent_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import thoth_control_plane.acquisition.camoufox_session as module

    monkeypatch.setattr(module, "_camoufox", lambda: _Camoufox)
    steps: list[str] = []

    async def setup(page: Any) -> None:
        steps.append("setup")

    async def action(page: Any) -> Any:
        steps.append("action")
        return page

    cookies = [{"name": "sessionid", "value": "s", "domain": ".instagram.com", "path": "/"}]
    async with CamoufoxSession(
        headless=True,
        max_pages=1,
        cookies=cookies,
        proxy={"server": "http://1.2.3.4:8080", "username": "u", "password": "p"},
        user_data_dir=str(tmp_path),
        locale="id-ID",
        timezone_id="Asia/Jakarta",
        fingerprint=FIREFOX,
    ) as session:
        result = await session.fetch(
            "https://www.instagram.com/x/reels/", page_setup=setup, page_action=action
        )

    assert steps == ["setup", "action"]
    assert (result.status, result.url) == (200, "https://www.instagram.com/x/reels/")
    assert result.body == b"<html>reels</html>"
    seen = _Camoufox.seen
    assert (seen["persistent_context"], seen["user_data_dir"]) == (True, str(tmp_path))
    assert (seen["locale"], seen["config"]) == ("id-ID", {"timezone": "Asia/Jakarta"})
    assert seen["fingerprint"] == FIREFOX and seen["proxy"]["username"] == "u"
    assert seen["geoip"] is False  # the account's own timezone, never an IP lookup
    assert "max_pages" not in seen  # a Scrapling-only option
    assert _Camoufox.context.cookies == cookies and _Camoufox.context.closed


@pytest.mark.asyncio
async def test_without_camoufox_the_session_is_tool_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from thoth_control_plane.attribution.adapters.frames import ToolMissing

    monkeypatch.setitem(sys.modules, "camoufox", None)
    monkeypatch.setitem(sys.modules, "camoufox.async_api", None)

    with pytest.raises(ToolMissing) as raised:
        async with CamoufoxSession(headless=True):
            pass
    assert raised.value.code == "camoufox_missing"


@pytest.mark.asyncio
async def test_a_proxy_without_credentials_reaches_camoufox_as_a_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import thoth_control_plane.acquisition.camoufox_session as module

    monkeypatch.setattr(module, "_camoufox", lambda: _Camoufox)

    async with CamoufoxSession(headless=True, proxy="socks5://10.0.0.1:1080"):
        pass

    assert _Camoufox.seen["proxy"] == {"server": "socks5://10.0.0.1:1080"}

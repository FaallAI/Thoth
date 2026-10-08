"""One leased session: the decrypted cookies and proxy, shaped for each access path."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from thoth_control_plane.acquisition.accounts.cookies import CookieSet

COOKIE_FILE_NAME = "cookies.txt"


def _browser_proxy(proxy: str) -> str | dict[str, str]:
    """Playwright reads URL credentials raw, so a proxy with credentials goes decoded."""
    parts = urlsplit(proxy)
    if parts.username is None:
        return proxy
    host = parts.hostname or ""
    shown = f"[{host}]" if ":" in host else host
    return {
        "server": f"{parts.scheme}://{shown}:{parts.port}",
        "username": unquote(parts.username),
        "password": unquote(parts.password or ""),
    }


@dataclass(frozen=True)
class SessionAccess:
    cookies: CookieSet
    proxy: str | None = None

    def __repr__(self) -> str:
        # The cookies and the proxy are secrets; a repr must never print them.
        return f"SessionAccess(platform={self.cookies.platform!r})"

    def browser_kwargs(self) -> dict[str, Any]:
        """Extra `AsyncStealthySession` arguments: the cookies, and the proxy if any."""
        kwargs: dict[str, Any] = {"cookies": self.cookies.to_playwright()}
        if self.proxy:
            kwargs["proxy"] = _browser_proxy(self.proxy)
        return kwargs

    def request_kwargs(self) -> dict[str, Any]:
        """Extra `AsyncFetcher.get` arguments: the cookies, and the proxy if any."""
        kwargs: dict[str, Any] = {"cookies": self.cookies.to_request()}
        if self.proxy:
            kwargs["proxy"] = self.proxy
        return kwargs

    def yt_dlp_options(self, directory: Path) -> dict[str, Any]:
        """yt-dlp options; writes the cookie file (mode 0600) into `directory`.

        The caller owns `directory` and removes it once yt-dlp is done.
        """
        path = directory / COOKIE_FILE_NAME
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(self.cookies.to_netscape())
        options: dict[str, Any] = {"cookiefile": str(path)}
        if self.proxy:
            options["proxy"] = self.proxy
        return options

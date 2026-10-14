"""One leased session: the decrypted cookies and proxy, shaped for each access path."""

from __future__ import annotations

import os
from dataclasses import KW_ONLY, dataclass, field
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
    _: KW_ONLY
    # Spec 2026-10-13, 3.2 and 3.4: the account's own device, kept between leases.
    profile_dir: Path | None = None
    locale: str = "id-ID"
    timezone: str = "Asia/Jakarta"
    fingerprint: dict[str, Any] | None = field(default=None, hash=False)  # Camoufox's only
    engine: str = "patchright"

    def __repr__(self) -> str:
        # The cookies, proxy, profile, and fingerprint are secrets; a repr never prints them.
        return f"SessionAccess(platform={self.cookies.platform!r})"

    def browser_kwargs(self) -> dict[str, Any]:
        """Extra browser-session arguments: cookies, proxy, profile, locale, and timezone.

        Only Camoufox gets the fingerprint, a Firefox one. Patchright keeps Scrapling's user
        agent, which already matches the driven Chromium and the host OS (amendment 2026-10-14).
        """
        kwargs: dict[str, Any] = {
            "cookies": self.cookies.to_playwright(),
            "locale": self.locale,
            "timezone_id": self.timezone,
        }
        if self.proxy:
            kwargs["proxy"] = _browser_proxy(self.proxy)
            # Chromium's WebRTC otherwise reaches STUN around the proxy with the host's own IP.
            kwargs["block_webrtc"] = True
        if self.profile_dir is not None:
            kwargs["user_data_dir"] = str(self.profile_dir)
        if self.engine == "camoufox" and self.fingerprint is not None:
            kwargs["fingerprint"] = self.fingerprint
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

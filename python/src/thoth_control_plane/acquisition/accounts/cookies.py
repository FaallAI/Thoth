"""Parse and validate a browser cookie export for one platform; holds no state.

Two formats are read: Netscape `cookies.txt` (yt-dlp, "Get cookies.txt" extensions; the
`#HttpOnly_` prefix is honored) and the JSON array Cookie-Editor and EditThisCookie export.
Only the platform's own cookies are kept; expired ones are dropped; the platform's login
cookies must be present. Errors carry a code and cookie names, never a cookie value.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

Platform = Literal["tiktok", "threads", "instagram", "x", "youtube"]
PLATFORMS: tuple[Platform, ...] = ("tiktok", "threads", "instagram", "x", "youtube")
PLATFORM_DOMAINS: dict[str, tuple[str, ...]] = {
    "tiktok": ("tiktok.com",),
    "threads": ("threads.net", "threads.com", "instagram.com"),
    "instagram": ("instagram.com",),
    "x": ("x.com", "twitter.com"),
    "youtube": ("youtube.com", "google.com"),
}
REQUIRED_COOKIES: dict[str, tuple[str, ...]] = {
    "tiktok": ("sessionid",),
    "threads": ("sessionid",),
    "instagram": ("sessionid",),
    "x": ("auth_token", "ct0"),
    "youtube": ("SAPISID", "__Secure-3PSID"),
}
MAX_IMPORT_BYTES = 256 * 1024
MAX_COOKIES = 500
_SAME_SITE = {"lax": "Lax", "strict": "Strict", "none": "None", "no_restriction": "None"}
ErrorCode = Literal["invalid_cookie_file", "all_cookies_expired", "missing_required_cookie"]


class CookieImportError(ValueError):
    def __init__(self, code: ErrorCode, missing: tuple[str, ...] = ()) -> None:
        super().__init__(code)
        self.code: ErrorCode = code
        self.missing = missing


@dataclass(frozen=True)
class Cookie:
    name: str
    value: str = field(repr=False)
    domain: str
    path: str = "/"
    expires: float | None = None
    secure: bool = True
    http_only: bool = False
    same_site: str | None = None


@dataclass(frozen=True)
class CookieSet:
    platform: Platform
    cookies: tuple[Cookie, ...]

    def names(self) -> list[str]:
        return sorted({cookie.name for cookie in self.cookies})

    def earliest_expiry(self) -> datetime | None:
        """The earliest expiry among the login cookies; None when they are session-only."""
        required = REQUIRED_COOKIES[self.platform]
        times = [c.expires for c in self.cookies if c.name in required and c.expires]
        return datetime.fromtimestamp(min(times), UTC) if times else None

    def to_json(self) -> str:
        return json.dumps([asdict(cookie) for cookie in self.cookies], separators=(",", ":"))

    @classmethod
    def from_json(cls, platform: Platform, text: str) -> CookieSet:
        return cls(platform, tuple(Cookie(**item) for item in json.loads(text)))

    def to_playwright(self) -> list[dict[str, Any]]:
        out = []
        for c in self.cookies:
            cookie: dict[str, Any] = {
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path,
                "secure": c.secure,
                "httpOnly": c.http_only,
            }
            if c.expires:
                cookie["expires"] = c.expires
            if c.same_site:
                cookie["sameSite"] = c.same_site
            out.append(cookie)
        return out

    def to_request(self) -> dict[str, str]:
        return {cookie.name: cookie.value for cookie in self.cookies}

    def to_netscape(self) -> str:
        lines = ["# Netscape HTTP Cookie File"]
        for c in self.cookies:
            domain = ("#HttpOnly_" if c.http_only else "") + c.domain
            subdomains = "TRUE" if c.domain.startswith(".") else "FALSE"
            secure = "TRUE" if c.secure else "FALSE"
            expires = str(int(c.expires or 0))
            lines.append("\t".join([domain, subdomains, c.path, secure, expires, c.name, c.value]))
        return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class CookieSummary:
    count: int = 0
    names: tuple[str, ...] = ()
    earliest_expiry: datetime | None = None
    error: ErrorCode | None = None
    missing: tuple[str, ...] = ()


def _belongs(domain: str, platform: str) -> bool:
    host = domain.lstrip(".").lower()
    return any(host == d or host.endswith("." + d) for d in PLATFORM_DOMAINS[platform])


def _expiry(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if seconds > 0 else None


def _netscape(text: str) -> list[Cookie]:
    cookies = []
    for raw in text.splitlines():
        line = raw.strip("\r\n")
        http_only = line.startswith("#HttpOnly_")
        if http_only:
            line = line.removeprefix("#HttpOnly_")
        elif not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 7 or not fields[5]:
            continue
        domain, _, path, secure, expires, name, value = fields
        cookies.append(
            Cookie(
                name=name,
                value=value,
                domain=domain,
                path=path or "/",
                expires=_expiry(expires),
                secure=secure.upper() == "TRUE",
                http_only=http_only,
            )
        )
    return cookies


def _json(text: str) -> list[Cookie]:
    try:
        items = json.loads(text)
    except ValueError:
        return []
    cookies = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        name, value, domain = item.get("name"), item.get("value"), item.get("domain")
        if not (isinstance(name, str) and name and isinstance(value, str)):
            continue
        if not (isinstance(domain, str) and domain):
            continue
        same_site = item.get("sameSite")
        path = item.get("path")
        cookies.append(
            Cookie(
                name=name,
                value=value,
                domain=domain,
                path=path if isinstance(path, str) and path else "/",
                expires=_expiry(item.get("expirationDate", item.get("expires"))),
                secure=item.get("secure") is not False,
                http_only=item.get("httpOnly") is True,
                same_site=_SAME_SITE.get(same_site.lower()) if isinstance(same_site, str) else None,
            )
        )
    return cookies


def parse_cookies(platform: Platform, text: str, *, now: datetime) -> CookieSet:
    """The platform's live cookies from an export, or `CookieImportError`."""
    if len(text.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise CookieImportError("invalid_cookie_file")
    parsed = _json(text) if text.lstrip().startswith("[") else _netscape(text)
    if not parsed or len(parsed) > MAX_COOKIES:
        raise CookieImportError("invalid_cookie_file")
    mine = [cookie for cookie in parsed if _belongs(cookie.domain, platform)]
    stamp = now.timestamp()
    live = [c for c in mine if c.expires is None or c.expires > stamp]
    if mine and not live:
        raise CookieImportError("all_cookies_expired")
    unique = {(c.name, c.domain.lower(), c.path): c for c in live}
    names = {name for name, _, _ in unique}
    missing = tuple(name for name in REQUIRED_COOKIES[platform] if name not in names)
    if missing:
        raise CookieImportError("missing_required_cookie", missing)
    return CookieSet(platform, tuple(unique.values()))


def summarize(platform: Platform, text: str, *, now: datetime) -> CookieSummary:
    """The safe summary of an import; never raises and never holds a value."""
    try:
        cookie_set = parse_cookies(platform, text, now=now)
    except CookieImportError as error:
        return CookieSummary(error=error.code, missing=error.missing)
    return CookieSummary(
        count=len(cookie_set.cookies),
        names=tuple(cookie_set.names()),
        earliest_expiry=cookie_set.earliest_expiry(),
    )

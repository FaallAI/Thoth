"""Parse a pasted proxy list for the pool; holds no state.

One proxy per line, `scheme://[user:pass@]host:port`, with scheme `http`, `https`, or
`socks5`. Blank lines and `#` comments are skipped. A SOCKS5 proxy with credentials is
refused: Chromium cannot authenticate to one, so the card browser could never use it.
Invalid lines are reported by number only; a line is never echoed.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit

SCHEMES = ("http", "https", "socks5")
MAX_PROXY_BYTES = 64 * 1024
MAX_PROXY_LINES = 500


class ProxyImportError(ValueError):
    def __init__(self) -> None:
        super().__init__("invalid_proxy_file")
        self.code = "invalid_proxy_file"


@dataclass(frozen=True)
class ProxyEntry:
    url: str
    scheme: str
    display: str


@dataclass(frozen=True)
class ProxyImport:
    entries: tuple[ProxyEntry, ...]
    invalid_lines: tuple[int, ...]


def _encoded(value: str | None) -> str:
    """Percent-encoded exactly once, so an `@` or `:` in a password stays a credential."""
    return quote(unquote(value or ""), safe="")


def parse_proxy(line: str) -> ProxyEntry | None:
    """A normalized proxy, or None for anything outside the accepted shape."""
    try:
        parts = urlsplit(line.strip())
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in SCHEMES or not host or port is None or not 0 < port < 65536:
        return None
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        return None
    has_user = parts.username is not None or parts.password is not None
    if scheme == "socks5" and has_user:
        return None
    if has_user and not (parts.username and parts.password):
        return None
    shown = f"[{host}]" if ":" in host else host
    display = f"{shown}:{port}"
    userinfo = f"{_encoded(parts.username)}:{_encoded(parts.password)}@" if has_user else ""
    return ProxyEntry(url=f"{scheme}://{userinfo}{display}", scheme=scheme, display=display)


def parse_proxy_list(text: str) -> ProxyImport:
    """Every valid proxy once, in order, and the numbers of the invalid lines."""
    if len(text.encode("utf-8")) > MAX_PROXY_BYTES:
        raise ProxyImportError()
    lines = text.splitlines()
    if len(lines) > MAX_PROXY_LINES:
        raise ProxyImportError()
    entries: dict[str, ProxyEntry] = {}
    invalid: list[int] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        entry = parse_proxy(line)
        if entry is None:
            invalid.append(number)
        else:
            entries.setdefault(entry.url, entry)
    return ProxyImport(entries=tuple(entries.values()), invalid_lines=tuple(invalid))

"""Pure URL-to-platform routing shared by the API, the workflow guard, and the activity.

Stdlib only: the Temporal workflow sandbox imports this module, so it must never pull in
browser or HTTP code.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

PYTHON_PLATFORM_HOSTS: dict[str, frozenset[str]] = {
    "tiktok": frozenset({"tiktok.com", "vm.tiktok.com", "vt.tiktok.com"}),
    "threads": frozenset({"threads.net", "threads.com"}),
    "instagram": frozenset({"instagram.com"}),
    # `bare_host` strips `www.` and `m.` only, so the `mobile.` hosts are listed.
    "x": frozenset({"x.com", "twitter.com", "mobile.x.com", "mobile.twitter.com"}),
    "youtube": frozenset({"youtube.com", "youtu.be"}),
}


def bare_host(host: str) -> str:
    """Lowercase, drop a trailing dot, then drop one `www.` or `m.` prefix."""
    host = host.lower().rstrip(".")
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            return host[len(prefix) :]
    return host


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def platform_of(url: str) -> str | None:
    host = bare_host(_host(url))
    for platform, hosts in PYTHON_PLATFORM_HOSTS.items():
        if host in hosts:
            return platform
    return None


def platform_support(url: str) -> Literal["python", "unsupported"]:
    """Python acquires every supported platform; Scout, which took the rest, is retired."""
    return "python" if platform_of(url) is not None else "unsupported"

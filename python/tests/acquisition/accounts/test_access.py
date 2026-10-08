"""A leased session shaped for the browser, the request fetcher, and yt-dlp; no network."""

from __future__ import annotations

import stat
from datetime import UTC, datetime
from pathlib import Path

from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.accounts.cookies import parse_cookies

NOW = datetime(2026, 10, 7, tzinfo=UTC)
SECRET = "s3cr3t-session-value"
PROXY = "http://user:pr0xy-pa55@1.2.3.4:8080"
COOKIES = parse_cookies(
    "instagram",
    "\t".join([".instagram.com", "TRUE", "/", "TRUE", "1893456000", "sessionid", SECRET]) + "\n",
    now=NOW,
)


def test_each_access_path_gets_the_cookies_and_the_proxy() -> None:
    access = SessionAccess(COOKIES, PROXY)
    browser = access.browser_kwargs()
    assert browser["proxy"] == PROXY
    assert [c["value"] for c in browser["cookies"]] == [SECRET]
    assert access.request_kwargs() == {"cookies": {"sessionid": SECRET}, "proxy": PROXY}


def test_without_a_proxy_no_proxy_argument_is_passed() -> None:
    access = SessionAccess(COOKIES)
    assert "proxy" not in access.browser_kwargs()
    assert "proxy" not in access.request_kwargs()


def test_the_yt_dlp_cookie_file_is_private_and_readable_by_yt_dlp(tmp_path: Path) -> None:
    options = SessionAccess(COOKIES, PROXY).yt_dlp_options(tmp_path)
    path = Path(options["cookiefile"])
    assert options["proxy"] == PROXY
    assert parse_cookies("instagram", path.read_text(encoding="utf-8"), now=NOW) == COOKIES
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_session_never_prints_its_secrets() -> None:
    text = repr(SessionAccess(COOKIES, PROXY)) + str(SessionAccess(COOKIES, PROXY)) + repr(COOKIES)
    assert SECRET not in text and "pr0xy-pa55" not in text

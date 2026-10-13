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
    assert browser["proxy"] == {
        "server": "http://1.2.3.4:8080",
        "username": "user",
        "password": "pr0xy-pa55",
    }
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


def test_the_browser_gets_decoded_credentials_while_curl_and_yt_dlp_keep_the_url() -> None:
    encoded = "http://us%40er:p%40ss%3Aw@[2001:db8::1]:8080"
    access = SessionAccess(COOKIES, encoded)
    assert access.browser_kwargs()["proxy"] == {
        "server": "http://[2001:db8::1]:8080",
        "username": "us@er",
        "password": "p@ss:w",
    }
    assert access.request_kwargs()["proxy"] == encoded
    assert SessionAccess(COOKIES, "socks5://10.0.0.1:1080").browser_kwargs()["proxy"] == (
        "socks5://10.0.0.1:1080"
    )


def test_browser_kwargs_carry_profile_locale_and_timezone(tmp_path: Path) -> None:
    access = SessionAccess(
        COOKIES, None, profile_dir=tmp_path, locale="id-ID", timezone="Asia/Jakarta"
    )

    kwargs = access.browser_kwargs()

    assert kwargs["user_data_dir"] == str(tmp_path)
    assert (kwargs["locale"], kwargs["timezone_id"]) == ("id-ID", "Asia/Jakarta")
    # Patchright keeps Scrapling's user agent: it matches the real Chromium and host OS.
    assert "useragent" not in kwargs and "fingerprint" not in kwargs
    assert str(tmp_path) not in repr(access)


def test_only_camoufox_gets_the_fingerprint() -> None:
    firefox = {
        "navigator": {"userAgent": "Mozilla/5.0 (X11; Linux x86_64; rv:150.0) Firefox/150.0"}
    }
    camoufox = SessionAccess(COOKIES, None, fingerprint=firefox, engine="camoufox")
    patchright = SessionAccess(COOKIES, None, fingerprint=firefox, engine="patchright")

    assert camoufox.browser_kwargs()["fingerprint"] == firefox
    assert "fingerprint" not in patchright.browser_kwargs()
    assert "Firefox" not in repr(camoufox)

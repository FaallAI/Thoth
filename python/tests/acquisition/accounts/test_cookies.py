"""Cookie export parsing and validation for each platform; no network."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime

import pytest

from thoth_control_plane.acquisition.accounts.cookies import (
    MAX_COOKIES,
    MAX_IMPORT_BYTES,
    CookieImportError,
    CookieSet,
    parse_cookies,
    summarize,
)

NOW = datetime(2026, 10, 7, tzinfo=UTC)
LATER = int(datetime(2026, 11, 2, tzinfo=UTC).timestamp())
LATEST = int(datetime(2027, 1, 1, tzinfo=UTC).timestamp())
PAST = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp())
SECRET = "s3cr3t-session-value"


def _line(domain: str, name: str, value: str, expires: int = LATER, http_only: bool = False):
    prefix = "#HttpOnly_" if http_only else ""
    flag = "TRUE" if domain.startswith(".") else "FALSE"
    return "\t".join([prefix + domain, flag, "/", "TRUE", str(expires), name, value])


def _netscape(*lines: str) -> str:
    return "# Netscape HTTP Cookie File\n# a comment\n\n" + "\n".join(lines) + "\n"


def test_a_netscape_export_keeps_the_platforms_cookies_and_http_only() -> None:
    text = _netscape(
        _line(".instagram.com", "sessionid", SECRET, http_only=True),
        _line(".instagram.com", "csrftoken", "c", LATEST),
        _line(".google.com", "SID", "g"),
    )
    cookies = parse_cookies("instagram", text, now=NOW)
    assert cookies.names() == ["csrftoken", "sessionid"]
    session = next(c for c in cookies.cookies if c.name == "sessionid")
    assert (session.http_only, session.secure, session.domain) == (True, True, ".instagram.com")
    assert cookies.earliest_expiry() == datetime.fromtimestamp(LATER, UTC)


def test_a_cookie_editor_json_export_is_read() -> None:
    text = json.dumps(
        [
            {
                "name": "auth_token",
                "value": SECRET,
                "domain": ".x.com",
                "path": "/",
                "expirationDate": LATER + 0.5,
                "secure": True,
                "httpOnly": True,
                "sameSite": "no_restriction",
            },
            {"name": "ct0", "value": "csrf", "domain": "x.com", "session": True},
            {"name": "", "value": "dropped", "domain": "x.com"},
            "junk",
        ]
    )
    cookies = parse_cookies("x", text, now=NOW)
    assert cookies.names() == ["auth_token", "ct0"]
    auth = next(c for c in cookies.cookies if c.name == "auth_token")
    assert (auth.same_site, auth.expires) == ("None", LATER + 0.5)


def test_youtube_keeps_its_google_login_cookies() -> None:
    text = _netscape(
        _line(".youtube.com", "SAPISID", "a"),
        _line(".google.com", "__Secure-3PSID", "b"),
        _line(".tiktok.com", "sessionid", "c"),
    )
    assert parse_cookies("youtube", text, now=NOW).names() == ["SAPISID", "__Secure-3PSID"]


def test_threads_accepts_its_own_or_instagrams_session() -> None:
    for domain in (".threads.net", ".threads.com", ".instagram.com"):
        assert parse_cookies("threads", _netscape(_line(domain, "sessionid", "s")), now=NOW)


def test_a_lookalike_domain_is_not_the_platforms() -> None:
    text = _netscape(_line(".notinstagram.com", "sessionid", "s"))
    with pytest.raises(CookieImportError) as caught:
        parse_cookies("instagram", text, now=NOW)
    assert (caught.value.code, caught.value.missing) == ("missing_required_cookie", ("sessionid",))


def test_missing_login_cookies_are_named() -> None:
    text = _netscape(_line(".x.com", "ct0", "c"))
    with pytest.raises(CookieImportError) as caught:
        parse_cookies("x", text, now=NOW)
    assert (caught.value.code, caught.value.missing) == ("missing_required_cookie", ("auth_token",))


def test_expired_cookies_are_dropped_and_all_expired_is_refused() -> None:
    text = _netscape(_line(".tiktok.com", "sessionid", "s", PAST))
    with pytest.raises(CookieImportError) as caught:
        parse_cookies("tiktok", text, now=NOW)
    assert caught.value.code == "all_cookies_expired"
    mixed = _netscape(
        _line(".tiktok.com", "old", "o", PAST), _line(".tiktok.com", "sessionid", "s")
    )
    assert parse_cookies("tiktok", mixed, now=NOW).names() == ["sessionid"]


def test_a_session_only_login_cookie_has_no_expiry() -> None:
    text = _netscape(_line(".tiktok.com", "sessionid", "s", 0))
    cookies = parse_cookies("tiktok", text, now=NOW)
    assert cookies.earliest_expiry() is None


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not a cookie file",
        "[1, 2",
        "{}",
        "x" * (MAX_IMPORT_BYTES + 1),
        _netscape(*[_line(".tiktok.com", f"c{i}", "v") for i in range(MAX_COOKIES + 1)]),
    ],
)
def test_broken_or_oversized_input_is_an_invalid_file(text: str) -> None:
    with pytest.raises(CookieImportError) as caught:
        parse_cookies("tiktok", text, now=NOW)
    assert caught.value.code == "invalid_cookie_file"


def test_a_repeated_cookie_keeps_the_last_copy() -> None:
    text = _netscape(
        _line(".tiktok.com", "sessionid", "old"), _line(".tiktok.com", "sessionid", "new")
    )
    (cookie,) = parse_cookies("tiktok", text, now=NOW).cookies
    assert cookie.value == "new"


def test_the_summary_names_cookies_and_never_holds_a_value() -> None:
    good = summarize("instagram", _netscape(_line(".instagram.com", "sessionid", SECRET)), now=NOW)
    assert (good.count, good.names, good.error) == (1, ("sessionid",), None)
    bad = summarize("x", _netscape(_line(".x.com", "auth_token", SECRET)), now=NOW)
    assert (bad.error, bad.missing, bad.count) == ("missing_required_cookie", ("ct0",), 0)
    assert SECRET not in repr(good) + repr(bad) + json.dumps(asdict(bad), default=str)
    with pytest.raises(CookieImportError) as caught:
        parse_cookies("x", _netscape(_line(".x.com", "auth_token", SECRET)), now=NOW)
    assert SECRET not in str(caught.value) + repr(caught.value)


def test_a_cookie_set_round_trips_and_feeds_every_access_path() -> None:
    text = _netscape(
        _line(".instagram.com", "sessionid", SECRET, http_only=True),
        _line("www.instagram.com", "csrftoken", "c", 0),
    )
    cookies = parse_cookies("instagram", text, now=NOW)
    assert CookieSet.from_json("instagram", cookies.to_json()) == cookies
    assert parse_cookies("instagram", cookies.to_netscape(), now=NOW) == cookies
    assert cookies.to_request() == {"sessionid": SECRET, "csrftoken": "c"}
    by_name = {c["name"]: c for c in cookies.to_playwright()}
    assert by_name["sessionid"] == {
        "name": "sessionid",
        "value": SECRET,
        "domain": ".instagram.com",
        "path": "/",
        "secure": True,
        "httpOnly": True,
        "expires": LATER,
    }
    assert "expires" not in by_name["csrftoken"]


def test_a_request_prefers_the_platforms_own_host_for_a_repeated_name() -> None:
    text = _netscape(
        _line(".x.com", "auth_token", "fresh"),
        _line(".x.com", "ct0", "c"),
        _line(".twitter.com", "auth_token", "stale"),
    )
    assert parse_cookies("x", text, now=NOW).to_request() == {"auth_token": "fresh", "ct0": "c"}
    threads = _netscape(
        _line(".threads.com", "sessionid", "own"), _line(".instagram.com", "sessionid", "other")
    )
    assert parse_cookies("threads", threads, now=NOW).to_request() == {"sessionid": "own"}
